"""Job execution backends.

`DockerRuntime` is the real thing: `docker run` with hard resource limits. `LocalRuntime`
is the demo/CI backend for machines with no Docker and no GPU -- it runs a real CPU
workload locally for the job's requested duration instead of pulling the image, so the
whole marketplace (leasing, churn, retries, logs, billing) exercises its real code paths
on hardware that cannot run containers.
"""

from __future__ import annotations

import contextlib
import json
import math
import random
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

LogSink = Callable[[str, str], None]  # (stream, text)

# docker exits with these when it could not even start the container (bad image, no
# daemon, unsupported flag). That is a worker-side problem, so the coordinator should
# retry elsewhere rather than blaming the submitter's code.
DOCKER_START_FAILURE_CODES = {125, 126, 127}

OUTPUT_DIR_IN_CONTAINER = "/dcm/out"
RESULT_FILENAME = "result.json"


@dataclass
class RunResult:
    exit_code: int | None
    result: str | None = None
    start_failed: bool = False
    reason: str | None = None


class JobRuntime(Protocol):
    name: str

    def run(
        self,
        job: dict[str, Any],
        *,
        attempt_id: str,
        log: LogSink,
        cancel: threading.Event,
    ) -> RunResult: ...


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def select_runtime(preference: str) -> JobRuntime:
    """preference: docker | local | auto"""
    if preference == "docker":
        return DockerRuntime()
    if preference == "local":
        return LocalRuntime()
    return DockerRuntime() if docker_available() else LocalRuntime()


class DockerRuntime:
    name = "docker"

    def run(
        self,
        job: dict[str, Any],
        *,
        attempt_id: str,
        log: LogSink,
        cancel: threading.Event,
    ) -> RunResult:
        container_name = f"dcm-{attempt_id}"
        out_dir = Path(tempfile.mkdtemp(prefix=f"dcm-{attempt_id}-"))
        argv = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--cpus", str(job["cpu_cores"]),
            "--memory", f"{job['memory_mb']}m",
            "--pull", "missing",
            "-v", f"{out_dir}:{OUTPUT_DIR_IN_CONTAINER}",
            "-e", f"DCM_OUTPUT_DIR={OUTPUT_DIR_IN_CONTAINER}",
            "-e", f"DCM_ATTEMPT_ID={attempt_id}",
        ]
        if job.get("gpu_required"):
            argv += ["--gpus", "all"]
        for key, value in (job.get("env") or {}).items():
            argv += ["-e", f"{key}={value}"]
        argv.append(job["image"])
        argv += list(job.get("command") or [])

        log("system", f"$ {_one_line(argv)}")
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            shutil.rmtree(out_dir, ignore_errors=True)
            return RunResult(
                exit_code=None, start_failed=True, reason=f"could not launch docker: {exc}"
            )

        readers = [
            threading.Thread(target=_pump, args=(proc.stdout, "stdout", log), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, "stderr", log), daemon=True),
        ]
        for thread in readers:
            thread.start()

        killed = False
        while proc.poll() is None:
            if cancel.is_set() and not killed:
                log("system", "Stop requested — killing the container")
                subprocess.run(
                    ["docker", "kill", container_name],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                killed = True
            time.sleep(0.2)
        for thread in readers:
            thread.join(timeout=5)

        exit_code = proc.returncode
        result = _read_result(out_dir, log)
        shutil.rmtree(out_dir, ignore_errors=True)
        if exit_code in DOCKER_START_FAILURE_CODES:
            return RunResult(
                exit_code=exit_code,
                start_failed=True,
                reason=f"docker could not start the container (exit {exit_code})",
            )
        return RunResult(exit_code=exit_code, result=result)


class LocalRuntime:
    """Stand-in executor for machines without Docker.

    Executes the job's command directly on the host using subprocess. Emulates
    container environment variables, output mounts, and cancellation.
    """

    name = "local"

    def run(
        self,
        job: dict[str, Any],
        *,
        attempt_id: str,
        log: LogSink,
        cancel: threading.Event,
    ) -> RunResult:
        env = dict(job.get("env") or {})
        out_dir = Path(tempfile.mkdtemp(prefix=f"dcm-{attempt_id}-"))
        
        # Configure output path environment variables
        env["DCM_OUTPUT_DIR"] = str(out_dir)
        env["DCM_ATTEMPT_ID"] = attempt_id

        # Determine command to run
        command = list(job.get("command") or [])
        if not command:
            log("stderr", "local runtime error: no command specified in job")
            shutil.rmtree(out_dir, ignore_errors=True)
            return RunResult(exit_code=1, reason="missing command")

        log("system", f"local runtime: executing command without Docker: {_one_line(command)}")

        try:
            # Execute command directly on host system
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env={**subprocess.os.environ, **env},
            )
        except OSError as exc:
            shutil.rmtree(out_dir, ignore_errors=True)
            return RunResult(
                exit_code=None, start_failed=True, reason=f"could not launch local command: {exc}"
            )

        # Stream stdout and stderr outputs
        readers = [
            threading.Thread(target=_pump, args=(proc.stdout, "stdout", log), daemon=True),
            threading.Thread(target=_pump, args=(proc.stderr, "stderr", log), daemon=True),
        ]
        for thread in readers:
            thread.start()

        killed = False
        while proc.poll() is None:
            if cancel.is_set() and not killed:
                log("system", "Stop requested — terminating local process")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                killed = True
            time.sleep(0.1)

        for thread in readers:
            thread.join(timeout=5)

        exit_code = proc.returncode
        result = _read_result(out_dir, log)
        shutil.rmtree(out_dir, ignore_errors=True)

        if killed:
            return RunResult(exit_code=137, reason="cancelled")

        return RunResult(exit_code=exit_code, result=result)


def _one_line(argv: list[str], limit: int = 220) -> str:
    """Inline scripts passed as `-c` would otherwise wreck the log view."""
    flat = " ".join(arg.replace("\n", "; ").strip() for arg in argv)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _pump(pipe: Any, stream: str, log: LogSink) -> None:
    if pipe is None:
        return
    try:
        for line in pipe:
            log(stream, line.rstrip("\n"))
    except (OSError, ValueError):
        pass
    finally:
        with contextlib.suppress(OSError):
            pipe.close()


def _read_result(out_dir: Path, log: LogSink) -> str | None:
    path = out_dir / RESULT_FILENAME
    if not path.exists():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        log("system", f"could not read {RESULT_FILENAME}: {exc}")
        return None
    log("system", f"captured {RESULT_FILENAME} ({len(text)} bytes)")
    return text
