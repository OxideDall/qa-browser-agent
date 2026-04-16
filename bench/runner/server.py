"""Local HTTP server for static_ui / spa_dynamic fixtures.

Single shared server instance keyed by site_dir. Bind to 127.0.0.1 only.
Threads handle concurrent requests so SPA bundles load JS+CSS+JSON in parallel.
"""

from __future__ import annotations

import contextlib
import http.server
import socket
import socketserver
import threading
from pathlib import Path
from typing import Iterator


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: D401 — silence default access log
        return


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FixtureServer:
    """One HTTP server per site_dir. Lifetime tied to context manager."""

    def __init__(self, site_dir: Path):
        self.site_dir = site_dir.resolve()
        self.port = _free_port()
        # SimpleHTTPRequestHandler uses cwd; switch to site_dir via a factory.
        site_dir_str = str(self.site_dir)

        class _Handler(_SilentHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=site_dir_str, **kwargs)

        self._httpd = _ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@contextlib.contextmanager
def serve(site_dir: Path) -> Iterator[FixtureServer]:
    srv = FixtureServer(site_dir)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()
