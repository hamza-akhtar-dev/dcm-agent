"""Machine spec probing.

Self-reported specs are trivially spoofable; the coordinator treats them as a claim,
not a fact (see the trust section of the architecture doc). This module is the honest
client-side half.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass

import psutil


@dataclass
class MachineSpecs:
    cpu_cores: float
    memory_mb: int
    gpu: bool
    gpu_name: str | None
    platform: str
    hostname: str


def detect_gpu() -> tuple[bool, str | None]:
    if shutil.which("nvidia-smi") is None:
        return False, None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None
    if out.returncode != 0:
        return False, None
    names = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if not names:
        return False, None
    return True, names[0]


def probe(*, donate_fraction: float = 0.75) -> MachineSpecs:
    """Report only the share of the machine the owner is donating.

    A consumer PC is somebody's daily driver: claiming every core would make the
    machine unusable and guarantee the owner uninstalls the agent.
    """
    total_cores = psutil.cpu_count(logical=True) or 1
    total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
    gpu, gpu_name = detect_gpu()
    return MachineSpecs(
        cpu_cores=max(1.0, round(total_cores * donate_fraction, 2)),
        memory_mb=max(256, int(total_mb * donate_fraction)),
        gpu=gpu,
        gpu_name=gpu_name,
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        hostname=socket.gethostname(),
    )
