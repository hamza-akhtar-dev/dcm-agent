"""Local control API used by the agent dashboard.

Stdlib only, bound to loopback by the caller. It never touches agent state directly:
it calls Agent methods that set flags, and the agent's main loop applies them.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .main import Agent


def serve(agent: Agent, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/status":
                self._send(200, agent.status())
            elif self.path == "/jobs":
                self._send(200, {"jobs": agent.ledger.jobs(), "now": time.time()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid JSON"})
                return
            try:
                if self.path == "/online":
                    agent.set_online(True)
                elif self.path == "/offline":
                    agent.set_online(False)
                elif self.path == "/config":
                    agent.apply_limits(
                        cpu_cores=body.get("cpu_cores"),
                        memory_mb=body.get("memory_mb"),
                        gpu=body.get("gpu"),
                    )
                elif self.path == "/profile":
                    agent.ledger.set_username(str(body.get("username", "")))
                else:
                    self._send(404, {"error": "not found"})
                    return
            except (ValueError, TypeError) as exc:
                self._send(400, {"error": str(exc)})
                return
            self._send(200, agent.status())

        def log_message(self, *args: Any) -> None:  # keep the agent log clean
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
