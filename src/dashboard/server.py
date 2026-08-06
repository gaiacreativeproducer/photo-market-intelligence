"""Localhost-only standard-library server for the read-only dashboard."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence


SRC_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from dashboard.demo_data import DemoDashboardDataProvider, LocalDashboardDataProvider
from dashboard.routes import DashboardRouter
from assistant import DeterministicAssistantProvider
from notifications import NotificationStore


HOST = "127.0.0.1"
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"


class DashboardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, router: DashboardRouter):
        self.router = router
        super().__init__(address, DashboardRequestHandler)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, content_type, body = self.server.router.dispatch(self.path)
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        problem = self._validate_local_request()
        if problem:
            self._respond(*problem); return
        if self.headers.get_content_type() != "application/json":
            self._respond(415, "application/json; charset=utf-8", b'{"error":{"code":"content_type","message":"application/json required"}}'); return
        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: length = -1
        if length < 0 or length > 65536:
            self._respond(413, "application/json; charset=utf-8", b'{"error":{"code":"body_too_large","message":"request body exceeds 64 KiB"}}'); return
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict): raise ValueError
        except (json.JSONDecodeError, ValueError):
            self._respond(400, "application/json; charset=utf-8", b'{"error":{"code":"invalid_json","message":"JSON object required"}}'); return
        self._respond(*self.server.router.dispatch_post(self.path, value))

    def _validate_local_request(self):
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        allowed = {"127.0.0.1", "localhost", f"127.0.0.1:{port}", f"localhost:{port}"}
        if host not in allowed:
            return 400, "application/json; charset=utf-8", b'{"error":{"code":"invalid_host","message":"local Host required"}}'
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            return 403, "application/json; charset=utf-8", b'{"error":{"code":"invalid_origin","message":"same local Origin required"}}'
        return None

    def _respond(self, status, content_type, body):
        self.send_response(int(status)); self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body))); self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def create_server(
    port: int = 8765, demo: bool = False,
    project_root: Optional[Path] = None, user_directory: Optional[Path] = None,
) -> DashboardHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be from 0 to 65535")
    root = project_root or Path(__file__).resolve().parents[2]
    runtime = user_directory or root / "data" / "user"
    provider = DemoDashboardDataProvider(root, user_directory) if demo else LocalDashboardDataProvider(root, user_directory)
    data = provider.load()
    notification_store = NotificationStore(runtime)
    preferences = notification_store.load_preferences()
    assistant = DeterministicAssistantProvider(data, runtime, preferences.assistant_history_enabled)
    router = DashboardRouter(data, root / "web", notification_store, assistant)
    return DashboardHTTPServer((HOST, port), router)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Photo Market Intelligence local dashboard")
    parser.add_argument("--demo", action="store_true", help="use deterministic enriched fixtures")
    parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args(argv)
    try:
        server = create_server(arguments.port, arguments.demo)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    host, port = server.server_address
    print(f"Dashboard URL: http://{host}:{port}")
    print(f"Mode: {server.router.data.mode}")
    print(f"Products: {len(server.router.data.products)}")
    print("Read-only: yes")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
