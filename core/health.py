"""
Hᴇᴀʟᴛʜ ────────
Tiny, dependency-free HTTP server that answers 200 on every request so
Render's health check / any uptime pinger can keep the bot warm:

    GET /healthz   -> 200 "ok"
    GET /          -> 200 "ok"

Runs on a daemon thread next to the asyncio event loop — it never
blocks the bot. Port comes from the standard Render env var `PORT`
(falls back to 8000 for local `docker run`).
"""
from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("health")

DEFAULT_PORT = 8000
_BODY = b"ok"


class _HealthHandler(BaseHTTPRequestHandler):
    """Answers 200 to everything (GET/HEAD) — nothing else needed."""

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        self._respond()

    def do_HEAD(self) -> None:  # noqa: N802 (http.server API)
        self._respond()

    def _respond(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(_BODY)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(_BODY)

    def log_message(self, _fmt: str, *_args) -> None:
        # pings are noisy — keep the health server silent
        return


def pick_port() -> int:
    """PORT is injected by Render for web services; used as-is if valid."""
    raw = os.environ.get("PORT")
    if raw:
        try:
            return max(1, min(int(raw), 65535))
        except (TypeError, ValueError):
            log.warning("invalid PORT=%r — using %s", raw, DEFAULT_PORT)
    return DEFAULT_PORT


def start_health_server(host: str = "0.0.0.0", port: int | None = None) -> ThreadingHTTPServer | None:
    """Bind the tiny HTTP server on a background thread. Never raises."""
    port = pick_port() if port is None else port
    server: ThreadingHTTPServer | None = None
    for attempt in range(3):
        try:
            server = ThreadingHTTPServer((host, port), _HealthHandler)
            break
        except OSError as exc:
            log.error("health server bind failed on %s:%s (%s) — retrying…", host, port, exc)
            if attempt == 2:
                return None
    assert server is not None
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
    thread.start()
    log.info("health server up on http://%s:%d/healthz -> 200", host, port)
    return server
