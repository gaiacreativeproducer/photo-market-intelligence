"""Localhost-only standard-library server for the read-only dashboard."""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Sequence


SRC_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from dashboard.demo_data import DemoDashboardDataProvider, LocalDashboardDataProvider
from dashboard.routes import DashboardRouter


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

    def log_message(self, format: str, *args) -> None:
        return


def create_server(
    port: int = 8765, demo: bool = False,
    project_root: Optional[Path] = None, user_directory: Optional[Path] = None,
) -> DashboardHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be from 0 to 65535")
    root = project_root or Path(__file__).resolve().parents[2]
    provider = DemoDashboardDataProvider(root, user_directory) if demo else LocalDashboardDataProvider(root, user_directory)
    data = provider.load()
    router = DashboardRouter(data, root / "web")
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
