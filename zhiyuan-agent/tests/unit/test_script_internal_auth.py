from __future__ import annotations

import importlib
import http.client
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib import error, request

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOKEN = 'offline-"quoted"-\\credential'
INTERNAL_URL = "http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health"
PUBLIC_URL = "http://127.0.0.1:8090/gaotu-assistant-bot/chat/1/conversation/ws-ticket"


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", TOKEN)
    return SimpleNamespace(
        collect=importlib.import_module("collect_production_flow_assets"),
        verify=importlib.import_module("verify_production_flow_capabilities"),
        replay=importlib.import_module("replay_production_dialog_flow_local"),
    )


@pytest.fixture
def ssh_calls(monkeypatch):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, '{"code":0,"data":{}}\n__ZHIYUAN_HTTP_STATUS__:200', "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def invoke(scripts, kind, url=INTERNAL_URL):
    if kind == "collect":
        return scripts.collect._json_from_ssh("offline-host", url)
    if kind == "verify":
        return scripts.verify._run_ssh_json_post("offline-host", url, {"text": "北京 '$()'\n上海"})
    return scripts.replay._http_json("GET", url)


@pytest.mark.parametrize("kind", ["collect", "verify"])
def test_ssh_credential_and_payload_are_config_stdin_only(scripts, ssh_calls, kind):
    result = invoke(scripts, kind)
    assert result["code"] == 0
    arguments, kwargs = ssh_calls[0]
    assert TOKEN not in " ".join(arguments)
    assert "curl -q --config -" in arguments[-1]
    configuration = kwargs["input"]
    directives = dict(line.split(" = ", 1) for line in configuration.splitlines() if " = " in line)
    headers = [json.loads(line.split(" = ", 1)[1]) for line in configuration.splitlines() if line.startswith("header = ")]
    assert f"X-Internal-Service-Token: {TOKEN}" in headers
    assert json.loads(directives["url"]) == INTERNAL_URL
    assert "location" not in directives
    assert "insecure" not in directives
    assert "show-error" not in directives
    assert "__ZHIYUAN_HTTP_STATUS__:%{http_code}" in json.loads(directives["write-out"])
    assert directives["max-time"].isdigit()
    if kind == "verify":
        assert json.loads(json.loads(directives["data-binary"])) == {"text": "北京 '$()'\n上海"}
        assert "北京" not in arguments[-1]


@pytest.mark.parametrize("kind", ["collect", "verify", "replay"])
@pytest.mark.parametrize("token", [None, "", " ", "bad\rcredential", "bad\ncredential", " padded "])
def test_invalid_credentials_fail_before_any_transport(scripts, monkeypatch, kind, token):
    if token is None:
        monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", token)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("SSH must not run"))
    monkeypatch.setattr(request, "urlopen", lambda *args, **kwargs: pytest.fail("HTTP must not run"))
    monkeypatch.setattr(request.OpenerDirector, "open", lambda *args, **kwargs: pytest.fail("HTTP must not run"))
    with pytest.raises((ValueError, RuntimeError), match="INTERNAL_SERVICE_TOKEN"):
        invoke(scripts, kind)


@pytest.mark.parametrize("kind", ["collect", "verify"])
@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_ssh_non_success_never_becomes_business_response(scripts, monkeypatch, kind, status):
    monkeypatch.setattr(subprocess, "run", lambda arguments, **kwargs: subprocess.CompletedProcess(
        arguments, 0, f'{TOKEN}\n__ZHIYUAN_HTTP_STATUS__:{status}', TOKEN,
    ))
    with pytest.raises(RuntimeError) as failure:
        invoke(scripts, kind)
    assert TOKEN not in str(failure.value)


@pytest.mark.parametrize("kind", ["collect", "verify"])
@pytest.mark.parametrize("outcome", ["ssh_error", "timeout", "invalid_json", "credential_echo"])
def test_ssh_failures_do_not_expose_sensitive_output(scripts, monkeypatch, kind, outcome):
    def run(arguments, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(arguments, 1, output=TOKEN, stderr=TOKEN)
        if outcome == "ssh_error":
            return subprocess.CompletedProcess(arguments, 1, TOKEN, TOKEN)
        body = json.dumps({"code": 0, "echo": TOKEN}) if outcome == "credential_echo" else TOKEN
        return subprocess.CompletedProcess(arguments, 0, body + "\n__ZHIYUAN_HTTP_STATUS__:200", TOKEN)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError) as failure:
        invoke(scripts, kind)
    assert TOKEN not in str(failure.value)
    assert failure.value.__suppress_context__ or failure.value.__context__ is None


def install_http(monkeypatch, *, status=200, body=b'{"code":0,"data":{}}'):
    calls = []

    class Response(io.BytesIO):
        def __init__(self):
            super().__init__(body)
            self.status = status

    def opened(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(request, "urlopen", opened)
    monkeypatch.setattr(request.OpenerDirector, "open", opened)
    return calls


def test_replay_internal_request_authenticates_without_caller_override(scripts, monkeypatch):
    calls = install_http(monkeypatch)
    result = invoke(scripts, "replay")
    assert result["code"] == 0
    assert result["_status"] == 200
    req = next(value for value in calls[0][0] if isinstance(value, request.Request))
    assert dict((key.lower(), value) for key, value in req.header_items())["x-internal-service-token"] == TOKEN
    with pytest.raises(ValueError, match="override"):
        scripts.replay._http_json("GET", INTERNAL_URL, extra_headers={"x-INTERNAL-service-token": "attacker"})


def test_replay_public_ticket_does_not_receive_service_credential(scripts, monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
    calls = install_http(monkeypatch)
    scripts.replay._http_json("POST", PUBLIC_URL, {"sessionId": "1"}, extra_headers={"tk": "login-only", "pf": "WEB"})
    req = next(value for value in calls[0][0] if isinstance(value, request.Request))
    headers = dict((key.lower(), value) for key, value in req.header_items())
    assert "x-internal-service-token" not in headers
    assert headers["tk"] == "login-only"


def test_replay_installs_non_redirecting_opener(scripts, monkeypatch):
    original_build = request.build_opener
    handlers = []

    def build(*values):
        handlers.extend(values)
        return original_build(*values)

    monkeypatch.setattr(request, "build_opener", build)
    install_http(monkeypatch)
    invoke(scripts, "replay")
    redirect = next(handler for handler in handlers if isinstance(handler, request.HTTPRedirectHandler))
    with pytest.raises(error.HTTPError):
        redirect.redirect_request(request.Request(INTERNAL_URL), None, 302, "redirect", {}, "https://untrusted.invalid/")


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_replay_rejects_non_success_without_echo(scripts, monkeypatch, status):
    install_http(monkeypatch, status=status, body=TOKEN.encode())
    with pytest.raises(RuntimeError) as failure:
        invoke(scripts, "replay")
    assert TOKEN not in str(failure.value)


@pytest.mark.parametrize("kind", ["collect", "verify", "replay"])
def test_entrypoints_validate_credential_before_reading_assets_or_mutating(scripts, monkeypatch, tmp_path, kind):
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN")
    arguments = {
        "collect": ["collect", "--host", "offline-host", "--sessions", "123", "--output-dir", str(tmp_path / "output")],
        "verify": ["verify", "--host", "offline-host", "--asset-dir", str(tmp_path / "missing-assets")],
        "replay": ["replay"],
    }
    monkeypatch.setattr(sys, "argv", arguments[kind])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("must not spawn before authentication preflight"))
    monkeypatch.setattr(scripts.replay.asyncio, "run", lambda *args: pytest.fail("must not start replay before authentication preflight"))
    with pytest.raises((ValueError, RuntimeError), match="INTERNAL_SERVICE_TOKEN"):
        getattr(scripts, kind).main()
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("exception", [http.client.BadStatusLine(TOKEN), http.client.IncompleteRead(TOKEN.encode(), 500)])
def test_malformed_http_responses_do_not_expose_credentials(scripts, monkeypatch, exception):
    def opened(*args, **kwargs):
        raise exception

    monkeypatch.setattr(request.OpenerDirector, "open", opened)
    with pytest.raises(RuntimeError) as failure:
        invoke(scripts, "replay")
    assert TOKEN not in str(failure.value)
    assert failure.value.__suppress_context__


def test_escaped_json_credential_echo_is_not_written_to_artifacts(scripts, monkeypatch):
    escaped = "".join(f"\\u{ord(char):04x}" for char in TOKEN)
    install_http(monkeypatch, body=('{"echo":"' + escaped + '"}').encode())
    with pytest.raises(RuntimeError, match="credential"):
        invoke(scripts, "replay")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_http_timeout_fails_locally(scripts, ssh_calls, timeout):
    with pytest.raises(ValueError, match="timeout"):
        scripts.verify.request_json("POST", INTERNAL_URL, {}, ssh_host="offline-host", timeout_seconds=timeout)
    assert not ssh_calls


def test_fractional_timeout_rounds_up_for_legacy_curl(scripts, ssh_calls):
    scripts.verify._run_ssh_json_post("offline-host", INTERNAL_URL, {}, timeout=1.2)
    assert "max-time = 2\n" in ssh_calls[0][1]["input"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["setup", "first", "confirm"])
async def test_http_failures_leave_a_blocked_record_for_every_replay_case(scripts, monkeypatch, tmp_path, phase):
    replay = scripts.replay
    args = SimpleNamespace(
        asset_dir=str(tmp_path), session_offset=10000, case_id=[], parallelism=2,
        backend_url="http://127.0.0.1:9", agent_url="ws://127.0.0.1:9",
        volunteer_data_dir=str(tmp_path), case_file="", user_id="offline-user",
        origin="http://127.0.0.1", response_timeout=1,
    )
    cases = [{"caseId": f"offline-{index}", "sourceSessionId": str(index), "prompt": "test"} for index in (1, 2)]
    monkeypatch.setattr(replay, "_load_case_defs", lambda args: cases)
    for name in ("_read_json", "_build_user_score_detail", "_build_user_profile", "_ensure_session_record", "_write_extra_data", "_clear_pending", "_get_planning_state", "_summarize_ordered"):
        monkeypatch.setattr(replay, name, lambda *args, **kwargs: {})
    monkeypatch.setattr(replay, "_extract_volunteer_files", lambda *args: [])
    monkeypatch.setattr(replay, "_probe_volunteer_visibility", lambda *args: None)
    monkeypatch.setattr(replay, "_get_extra_data", lambda *args: {"ready": True})
    monkeypatch.setattr(replay, "_count_check_matches", lambda *args: 0)
    monkeypatch.setattr(replay, "_pending_cards", lambda *args: [{"kind": "plan_mutation", "pendingId": "offline-pending"}])

    async def exchange(*args, **kwargs):
        return [], [], 1

    monkeypatch.setattr(replay, "_ws_exchange", exchange)
    counts = {}

    def fail_http(*args, **kwargs):
        raise RuntimeError("HTTP request rejected (status 401)")

    def ticket(args, session_id):
        counts[session_id] = counts.get(session_id, 0) + 1
        if phase == "first" or counts[session_id] == 2:
            fail_http()
        return "offline-ticket"

    monkeypatch.setattr(replay, "_fetch_ws_ticket", ticket)
    if phase == "setup":
        monkeypatch.setattr(replay, "_write_extra_data", fail_http)
    result = await replay._run(args)
    assert result["summary"] == {"blocked": 2}
    assert len(result["records"]) == 2
    prefix = {"setup": "setup_failed:", "first": "first_turn_failed:", "confirm": "confirm_turn_failed:"}[phase]
    assert all(record["blockers"][0].startswith(prefix) for record in result["records"])
