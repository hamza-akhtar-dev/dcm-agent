"""Local job history and credit wallet for the agent dashboard.

Credits are computed from the local rate card below. Replace `hourly_rate` with the
coordinator's pricing once the agent can fetch it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

RATE_CPU_CORE, RATE_GPU, RATE_RAM_GB = 10.0, 100.0, 1.0  # credits per hour
MAX_JOBS = 500


def hourly_rate(cpu_cores: float, memory_mb: int, gpu: bool) -> dict[str, float]:
    cpu = cpu_cores * RATE_CPU_CORE
    ram = memory_mb / 1024 * RATE_RAM_GB
    gpu_rate = RATE_GPU if gpu else 0.0
    return {
        "cpu": round(cpu, 2),
        "ram": round(ram, 2),
        "gpu": gpu_rate,
        "total": round(cpu + ram + gpu_rate, 2),
    }


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"username": "", "jobs": []}
        try:
            self.data.update(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
        for job in self.data["jobs"]:  # the agent died mid-job last time
            if job["status"] == "running":
                job["status"], job["ended_at"] = "cancelled", job["started_at"]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))

    def start(self, attempt_id: str, name: str, rate: float) -> None:
        with self._lock:
            self.data["jobs"].append({
                "id": attempt_id, "name": name, "status": "running",
                "started_at": time.time(), "ended_at": None, "rate": rate, "credits": 0.0,
            })
            del self.data["jobs"][:-MAX_JOBS]
            self._save()

    def finish(self, attempt_id: str, status: str) -> None:
        with self._lock:
            for job in self.data["jobs"]:
                if job["id"] == attempt_id:
                    job["status"], job["ended_at"] = status, time.time()
                    if status == "succeeded":
                        hours = (job["ended_at"] - job["started_at"]) / 3600
                        job["credits"] = round(hours * job["rate"], 4)
            self._save()

    def jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self.data["jobs"]))

    def set_username(self, username: str) -> None:
        username = username.strip()[:32]
        if not username:
            raise ValueError("username cannot be empty")
        with self._lock:
            self.data["username"] = username
            self._save()

    def stats(self, default_name: str) -> dict[str, Any]:
        with self._lock:
            jobs = self.data["jobs"]
            done = sum(j["status"] == "succeeded" for j in jobs)
            failed = sum(j["status"] in ("failed", "error") for j in jobs)
            return {
                "username": self.data["username"] or default_name,
                "completed": done,
                "failed": failed,
                "completion_rate": done / (done + failed) if done + failed else None,
                "rating": None,  # ratings come from consumers, via the coordinator
                "balance": round(sum(j["credits"] for j in jobs), 4),
            }
