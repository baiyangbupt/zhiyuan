from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOKEN = 'offline-"curl"-\\credential'


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", TOKEN)
    return importlib.import_module("internal_http")


@pytest.fixture
def endpoint():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length)) if length else None
            received.append({"path": self.path, "token": self.headers.get("X-Internal-Service-Token"), "payload": payload})
            if self.path.endswith("redirect"):
                self.send_response(302)
                self.send_header("Location", "/public/redirect-target")
                self.end_headers()
                return
            self.send_response(403 if self.path.endswith("denied") else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"code": 0, "data": payload}, ensure_ascii=False).encode())

        do_POST = do_GET

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


@pytest.fixture(params=["urllib", "host-curl"])
def sender(request, transport, monkeypatch):
    if request.param == "urllib":
        return lambda method, url, payload=None: transport.request_json(method, url, payload, timeout_seconds=3)
    executable = shutil.which("curl")
    assert executable, "host curl is required to verify supported curl configuration syntax"
    run = subprocess.run

    def local_curl(arguments, **kwargs):
        assert arguments[-1] == "curl -q --config -"
        result = run([executable, "-q", "--config", "-"], input=kwargs["input"], text=True, capture_output=True, timeout=4)
        assert "expected a proper numerical parameter" not in result.stderr
        return result

    monkeypatch.setattr(subprocess, "run", local_curl)
    return lambda method, url, payload=None: transport.request_json(method, url, payload, timeout_seconds=3, ssh_host="never-contacted")


def test_real_transports_preserve_credential_and_literal_json(sender, endpoint):
    origin, received = endpoint
    payload = {"prompt": "北京 '$HOME' `echo nope` $(nope)\n上海 \\", "nested": {"count": 3}}
    response = sender("POST", origin + "/inner/good", payload)
    assert response["data"] == payload
    assert response["_status"] == 200
    assert received == [{"path": "/inner/good", "token": TOKEN, "payload": payload}]


def test_real_transports_never_follow_redirects(sender, endpoint):
    origin, received = endpoint
    with pytest.raises(RuntimeError) as failure:
        sender("GET", origin + "/inner/redirect")
    assert TOKEN not in str(failure.value)
    assert len(received) == 1
    assert received[0]["path"] == "/inner/redirect"


def test_real_transports_enforce_http_status(sender, endpoint):
    origin, received = endpoint
    with pytest.raises(RuntimeError):
        sender("GET", origin + "/inner/denied")
    assert len(received) == 1


def test_real_transports_do_not_authenticate_public_routes(sender, endpoint, monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
    origin, received = endpoint
    assert sender("GET", origin + "/public/ticket")["code"] == 0
    assert received[0]["token"] is None
