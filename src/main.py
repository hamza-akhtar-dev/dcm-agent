"""Worker agent: `dcm-worker` or `python -m dcm.agent.main`.

What a consumer PC runs. It registers, reports its specs, leases one job at a time, runs
it under hard resource limits, streams logs back, and heartbeats to keep its lease alive.
It is written to be killed at any moment: SIGTERM abandons the lease politely, and a hard
kill is covered by lease expiry on the coordinator.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import signal
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from . import specs
from .control import serve as serve_control
from .ledger import Ledger, hourly_rate
from .runtime import JobRuntime, RunResult, select_runtime

log = logging.getLogger("dcm.worker")

LOG_FLUSH_SECONDS = 0.4
LOG_BATCH_MAX = 200


@dataclass
class AgentConfig:
    coordinator: str
    name: str
    runtime: str
    donate_fraction: float
    cpu_cores: float | None
    memory_mb: int | None
    gpu: bool | None
    gpu_name: str | None
    state_file: Path | None
    die_after_seconds: float | None
    exit_after_jobs: int | None
    control_port: int = 8792  # 0 disables the local control API


class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.machine = specs.probe(donate_fraction=config.donate_fraction)
        if config.cpu_cores is not None:
            self.machine.cpu_cores = config.cpu_cores
        if config.memory_mb is not None:
            self.machine.memory_mb = config.memory_mb
        if config.gpu is not None:
            self.machine.gpu = config.gpu
            self.machine.gpu_name = config.gpu_name or ("Simulated GPU" if config.gpu else None)

        full = specs.probe(donate_fraction=1.0)
        self.max_cores = max(full.cpu_cores, self.machine.cpu_cores)
        self._gpu_name = self.machine.gpu_name or full.gpu_name
        self._online = threading.Event()
        self._online.set()
        self._registered = False
        self._specs_dirty = threading.Event()
        self.max_memory_mb = max(full.memory_mb, self.machine.memory_mb)
        self.ledger = Ledger(
            Path(os.environ.get("DCM_LEDGER", Path.home() / ".dcm-agent" / "ledger.json"))
        )

        self.runtime: JobRuntime = select_runtime(config.runtime)
        self.client = httpx.Client(base_url=config.coordinator.rstrip("/"), timeout=20.0)
        self.worker_id: str | None = None
        self.token: str | None = None
        self.heartbeat_interval = 5.0
        self.poll_interval = 2.0

        self._shutdown = threading.Event()
        self._cancel_run = threading.Event()
        self._orphaned = threading.Event()
        self._active_attempt: str | None = None
        self._logs: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._jobs_done = 0

    # ------------------------------------------------------------------ plumbing

    def _headers(self) -> dict[str, str]:
        return {"X-Worker-Id": self.worker_id or "", "Authorization": f"Bearer {self.token or ''}"}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = self.client.post(path, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            log.warning("%s failed: %s", path, exc)
            return None
        if response.status_code >= 400:
            log.warning("%s -> %s %s", path, response.status_code, response.text[:300])
            return None
        return response.json()

    def _load_worker_id(self) -> str | None:
        if self.config.state_file and self.config.state_file.exists():
            try:
                return json.loads(self.config.state_file.read_text()).get("worker_id")
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _save_worker_id(self) -> None:
        if not self.config.state_file:
            return
        self.config.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.config.state_file.write_text(json.dumps({"worker_id": self.worker_id}, indent=2))

    # ------------------------------------------------------------------ lifecycle

    def register(self) -> None:
        payload = {
            "name": self.config.name,
            "hostname": self.machine.hostname,
            "cpu_cores": self.machine.cpu_cores,
            "memory_mb": self.machine.memory_mb,
            "gpu": self.machine.gpu,
            "gpu_name": self.machine.gpu_name,
            "platform": self.machine.platform,
            "agent_version": __version__,
            "runtime": self.runtime.name,
            "worker_id": self.worker_id or self._load_worker_id(),
        }
        deadline = time.monotonic() + 60
        while True:
            if self._shutdown.is_set():
                raise SystemExit("stopped before registration completed")
            try:
                response = self.client.post("/v1/workers/register", json=payload)
                response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                if time.monotonic() > deadline:
                    raise SystemExit(
                        f"could not reach coordinator at {self.config.coordinator}: {exc}"
                    ) from exc
                log.info("coordinator not ready yet, retrying...")
                time.sleep(2)
        body = response.json()
        self.worker_id = body["worker"]["id"]
        self.token = body["token"]
        self.heartbeat_interval = float(body.get("heartbeat_interval_seconds", 5))
        self.poll_interval = float(body.get("poll_interval_seconds", 2))
        self._save_worker_id()
        self._registered = True
        log.info(
            "registered as %s (%s) — %.1f cores, %d MB, gpu=%s, runtime=%s",
            self.config.name,
            self.worker_id,
            self.machine.cpu_cores,
            self.machine.memory_mb,
            self.machine.gpu,
            self.runtime.name,
        )

    def run_forever(self) -> None:
        self.register()
        if self.config.control_port:
            serve_control(self, "127.0.0.1", self.config.control_port)
            log.info("control API on http://127.0.0.1:%d", self.config.control_port)
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._log_loop, daemon=True).start()
        if self.config.die_after_seconds:
            threading.Thread(target=self._chaos_timer, daemon=True).start()

        while not self._shutdown.is_set():
            if not self._sync_presence():
                self._shutdown.wait(self.poll_interval)
                continue
            lease = self._request_lease()
            if lease is None:
                self._shutdown.wait(self.poll_interval)
                continue
            self._execute(lease)
            self._jobs_done += 1
            if self.config.exit_after_jobs and self._jobs_done >= self.config.exit_after_jobs:
                log.info("finished %d job(s); shutting down as requested", self._jobs_done)
                break
        self.shutdown()

    def shutdown(self) -> None:
        self._shutdown.set()
        self._cancel_run.set()
        if self.worker_id and self._registered:
            self._flush_logs()
            self._post(f"/v1/workers/{self.worker_id}/deregister", {})
            self._registered = False
        self.client.close()

    # ------------------------------------------------------- dashboard control

    def set_online(self, online: bool) -> None:
        """Request only; the main loop acts on it, so a running job is never cut off."""
        (self._online.set if online else self._online.clear)()

    def apply_limits(
        self, *, cpu_cores: float | None, memory_mb: int | None, gpu: bool | None
    ) -> None:
        if memory_mb is not None:
            if not 256 <= memory_mb <= self.max_memory_mb:
                raise ValueError(f"memory_mb must be between 256 and {self.max_memory_mb}")
            self.machine.memory_mb = int(memory_mb)
        if cpu_cores is not None:
            if not 0.5 <= cpu_cores <= self.max_cores:
                raise ValueError(f"cpu_cores must be between 0.5 and {self.max_cores}")
            self.machine.cpu_cores = round(float(cpu_cores), 2)
        if gpu is not None:
            if gpu and not self._gpu_name:
                raise ValueError("no GPU detected on this machine")
            self.machine.gpu = gpu
            self.machine.gpu_name = self._gpu_name if gpu else None
        self._specs_dirty.set()

    def _sync_presence(self) -> bool:
        """Apply dashboard changes between jobs. True when we may lease work."""
        if not self._online.is_set():
            if self._registered:
                self._flush_logs()
                self._post(f"/v1/workers/{self.worker_id}/deregister", {})
                self._registered = False
                log.info("offline: deregistered from the coordinator")
            return False
        if not self._registered or self._specs_dirty.is_set():
            self._specs_dirty.clear()
            self.register()
        return True

    def rate(self) -> dict[str, float]:
        return hourly_rate(self.machine.cpu_cores, self.machine.memory_mb, self.machine.gpu)

    def status(self) -> dict[str, Any]:
        wanted, registered = self._online.is_set(), self._registered
        state = ("online" if registered else "connecting") if wanted else (
            "draining" if registered else "offline"
        )
        return {
            "state": state,
            "busy": self._active_attempt is not None,
            "name": self.config.name,
            "worker_id": self.worker_id,
            "coordinator": self.config.coordinator,
            "runtime": self.runtime.name,
            "cpu_cores": self.machine.cpu_cores,
            "max_cpu_cores": self.max_cores,
            "gpu": self.machine.gpu,
            "gpu_available": bool(self._gpu_name),
            "gpu_name": self._gpu_name,
            "memory_mb": self.machine.memory_mb,
            "max_memory_mb": self.max_memory_mb,
            "rate": self.rate(),
            **self.ledger.stats(self.config.name),
        }

    def request_stop(self, signum: int, _frame: object) -> None:
        log.info("signal %s received — stopping the current job and releasing its lease", signum)
        self._shutdown.set()
        self._cancel_run.set()

    def _chaos_timer(self) -> None:
        """Demo hook: vanish without warning, like a PC being switched off."""
        time.sleep(float(self.config.die_after_seconds or 0))
        log.warning("chaos: simulating a hard power-off (no lease release)")
        os._exit(9)

    # ------------------------------------------------------------------- protocol

    def _request_lease(self) -> dict[str, Any] | None:
        body = self._post(
            f"/v1/workers/{self.worker_id}/lease",
            {
                "available_cpu_cores": self.machine.cpu_cores,
                "available_memory_mb": self.machine.memory_mb,
                "gpu": self.machine.gpu,
            },
        )
        if not body:
            return None
        return body.get("lease")

    def _heartbeat_loop(self) -> None:
        while not self._shutdown.is_set():
            if not self._registered:  # offline: stay silent
                self._shutdown.wait(1)
                continue
            active = [self._active_attempt] if self._active_attempt else []
            body = self._post(
                f"/v1/workers/{self.worker_id}/heartbeat",
                {"status": "online", "active_attempt_ids": active},
            )
            if body and self._active_attempt:
                if self._active_attempt in body.get("cancel_attempt_ids", []):
                    log.info("coordinator asked us to stop %s", self._active_attempt)
                    self._cancel_run.set()
                elif self._active_attempt not in body.get("known_attempt_ids", []):
                    # Our lease is gone -- the coordinator gave this job to someone else.
                    # Keeping the container alive would duplicate work nobody pays for.
                    log.warning("lease for %s was reassigned; stopping", self._active_attempt)
                    self._orphaned.set()
                    self._cancel_run.set()
            self._shutdown.wait(self.heartbeat_interval)

    def _enqueue_log(self, stream: str, text: str) -> None:
        if self._active_attempt:
            self._logs.put((self._active_attempt, stream, text))

    def _log_loop(self) -> None:
        while not self._shutdown.is_set():
            time.sleep(LOG_FLUSH_SECONDS)
            self._flush_logs()

    def _flush_logs(self) -> None:
        batches: dict[str, list[dict[str, str]]] = {}
        drained = 0
        while drained < LOG_BATCH_MAX:
            try:
                attempt_id, stream, text = self._logs.get_nowait()
            except queue.Empty:
                break
            batches.setdefault(attempt_id, []).append({"stream": stream, "text": text})
            drained += 1
        for attempt_id, lines in batches.items():
            self._post(f"/v1/attempts/{attempt_id}/logs", {"lines": lines})

    # ------------------------------------------------------------------ execution

    def _execute(self, lease: dict[str, Any]) -> None:
        attempt_id = lease["attempt_id"]
        job = lease["job"]
        self._active_attempt = attempt_id
        self._cancel_run.clear()
        self._orphaned.clear()
        log.info(
            "leased %s (%s) attempt %s/%s",
            job["id"],
            job["name"],
            lease["attempt_number"],
            lease["max_attempts"],
        )

        started = self._post(f"/v1/attempts/{attempt_id}/start", {"container_id": None})
        if started is None:
            self._active_attempt = None
            return
        self.ledger.start(attempt_id, job["name"], self.rate()["total"])

        deadline = time.monotonic() + job["timeout_seconds"]
        watchdog = threading.Thread(
            target=self._local_timeout, args=(deadline,), daemon=True
        )
        watchdog.start()

        try:
            result = self.runtime.run(
                job, attempt_id=attempt_id, log=self._enqueue_log, cancel=self._cancel_run
            )
        except Exception as exc:  # a runtime blowing up must not kill the agent
            log.exception("runtime error")
            result = RunResult(exit_code=None, start_failed=True, reason=f"runtime error: {exc}")

        self._flush_logs()
        outcome = (
            "error" if result.start_failed
            else "cancelled" if self._cancel_run.is_set() or self._orphaned.is_set()
            else "succeeded" if result.exit_code == 0
            else "failed"
        )
        self.ledger.finish(attempt_id, outcome)
        self._report(attempt_id, result)
        self._active_attempt = None

    def _local_timeout(self, deadline: float) -> None:
        while time.monotonic() < deadline:
            if self._cancel_run.is_set() or self._active_attempt is None:
                return
            time.sleep(0.25)
        if self._active_attempt:
            self._enqueue_log("system", "Local timeout reached — stopping the container")
            self._cancel_run.set()

    def _report(self, attempt_id: str, result: RunResult) -> None:
        if self._orphaned.is_set():
            log.info("dropping result for reassigned attempt %s", attempt_id)
            return
        stopped_early = self._cancel_run.is_set()
        if stopped_early and self._shutdown.is_set():
            # The machine is going away. Release the lease now so the coordinator can
            # reschedule immediately instead of waiting for it to expire.
            self._post(
                f"/v1/attempts/{attempt_id}/abandon",
                {"reason": "Worker agent shut down mid-job (machine went away)"},
            )
            log.info("released lease for %s so it can be rescheduled", attempt_id)
            return
        if result.start_failed:
            self._post(
                f"/v1/attempts/{attempt_id}/complete",
                {
                    "status": "error",
                    "exit_code": result.exit_code,
                    "reason": result.reason or "could not start the container",
                },
            )
            return
        status = "succeeded" if result.exit_code == 0 else "failed"
        if stopped_early:  # the coordinator asked for this job to stop
            status = "cancelled"
        self._post(
            f"/v1/attempts/{attempt_id}/complete",
            {
                "status": status,
                "exit_code": result.exit_code,
                "result": result.result,
                "reason": result.reason,
            },
        )
        log.info("attempt %s reported as %s (exit %s)", attempt_id, status, result.exit_code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Distributed compute marketplace worker agent")
    parser.add_argument(
        "--coordinator",
        default=os.environ.get("DCM_COORDINATOR", "http://127.0.0.1:8791"),
        help="coordinator base URL",
    )
    parser.add_argument(
        "--name",
        default=os.environ.get("DCM_WORKER_NAME", socket.gethostname()),
        help="display name for this machine",
    )
    parser.add_argument(
        "--runtime",
        choices=("auto", "docker", "local"),
        default=os.environ.get("DCM_RUNTIME", "auto"),
        help="auto uses Docker when it is available and falls back to the local runtime",
    )
    parser.add_argument(
        "--donate",
        type=float,
        default=float(os.environ.get("DCM_DONATE_FRACTION", 0.75)),
        help="fraction of this machine's cores/RAM to offer (default 0.75)",
    )
    parser.add_argument("--cpu-cores", type=float, default=None, help="override detected cores")
    parser.add_argument("--memory-mb", type=int, default=None, help="override detected RAM")
    parser.add_argument("--gpu", action="store_true", help="advertise a GPU")
    parser.add_argument("--gpu-name", default=None)
    parser.add_argument(
        "--state-file",
        default=os.environ.get("DCM_WORKER_STATE"),
        help="file used to keep this machine's identity across agent restarts",
    )
    parser.add_argument(
        "--die-after-seconds",
        type=float,
        default=None,
        help="demo: hard-exit after N seconds to show churn recovery",
    )
    parser.add_argument(
        "--exit-after-jobs", type=int, default=None, help="demo: stop after N jobs"
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=int(os.environ.get("DCM_CONTROL_PORT", 8792)),
        help="local port for the agent dashboard (0 disables)",
    )
    parser.add_argument("--log-level", default=os.environ.get("DCM_LOG_LEVEL", "info"))
    return parser


def run() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format=f"%(asctime)s %(levelname)-7s [{args.name}] %(message)s",
    )
    agent = Agent(
        AgentConfig(
            coordinator=args.coordinator,
            name=args.name,
            runtime=args.runtime,
            donate_fraction=args.donate,
            cpu_cores=args.cpu_cores,
            memory_mb=args.memory_mb,
            gpu=True if args.gpu else None,
            gpu_name=args.gpu_name,
            state_file=Path(args.state_file) if args.state_file else None,
            die_after_seconds=args.die_after_seconds,
            exit_after_jobs=args.exit_after_jobs,
            control_port=args.control_port,
        )
    )
    signal.signal(signal.SIGINT, agent.request_stop)
    signal.signal(signal.SIGTERM, agent.request_stop)
    agent.run_forever()


if __name__ == "__main__":
    run()
