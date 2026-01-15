from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

import pytest

from tools import e2e_local_ai_speed


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


@contextmanager
def _run_http_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _OkHandler)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_is_http_ready_ignores_proxy_for_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = "http://127.0.0.1:1"
    monkeypatch.setenv("HTTP_PROXY", proxy)
    monkeypatch.setenv("http_proxy", proxy)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    monkeypatch.setenv("https_proxy", proxy)
    monkeypatch.setenv("ALL_PROXY", proxy)
    monkeypatch.setenv("all_proxy", proxy)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    with _run_http_server() as url:
        assert e2e_local_ai_speed._is_http_ready(url, timeout_s=0.8)
