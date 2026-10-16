from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ["ops/healthcheck.sh", "ops/release-smoke.sh", "scripts/start-codex-local.sh"]
TOKEN = "offline-probe-credential"
ESCAPED_TOKEN = 'offline-"quoted"-\\path\\n-credential'
REAL_CURL = shutil.which("curl")


def functions(path, names):
    text = (ROOT / path).read_text()
    return "\n".join(re.search(rf"^{name}\(\) \{{.*?^\}}", text, re.M | re.S).group() for name in names)


def run_probes(tmp_path, script, *, token=TOKEN, outcome="200", host_curl=False, echo_token=False, public_outcome="200"):
    executable = tmp_path / "curl"
    capture = tmp_path / "calls.jsonl"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import ast, json, os, pathlib, re, subprocess, sys\n"
        "arguments = sys.argv[1:]\n"
        "internal = any('/inner/' in argument for argument in arguments)\n"
        "configured = '--config' in arguments and arguments[arguments.index('--config') + 1] == '-'\n"
        "stdin = sys.stdin.read() if configured or '@-' in arguments else ''\n"
        "expected = 'X-Internal-Service-Token: ' + os.environ['INTERNAL_SERVICE_TOKEN']\n"
        "header_matches = False\n"
        "directives = []\n"
        "if configured:\n"
        "    directives = [line.partition('=')[0].strip() for line in stdin.splitlines()]\n"
        "    try:\n"
        "        header_matches = json.loads(stdin.partition('=')[2].strip()) == expected\n"
        "    except ValueError:\n"
        "        pass\n"
        "if internal and os.environ.get('HOST_CURL') == '1':\n"
        "    options = ['--config', '-'] if configured else ['--header', '@-']\n"
        "    result = subprocess.run([os.environ['REAL_CURL'], '-q', '--silent', '--show-error', *options, '--proto', '=file', '--libcurl', '/dev/stdout', 'file:///dev/null'], input=stdin, text=True, capture_output=True, timeout=3)\n"
        "    headers = re.findall(r'curl_slist_append\\(slist\\d+, (\"(?:[^\"\\\\]|\\\\.)*\")\\)', result.stdout)\n"
        "    header_matches = result.returncode == 0 and [ast.literal_eval(header) for header in headers] == [expected]\n"
        "with open(os.environ['CURL_CAPTURE'], 'a') as output:\n"
        "    output.write(json.dumps({'args': arguments, 'internal': internal, 'configured': configured, 'header_matches': header_matches, 'directives': directives, 'stdin_empty': not stdin}) + '\\n')\n"
        "outcome = os.environ['CURL_OUTCOME'] if internal else os.environ.get('PUBLIC_OUTCOME', '200')\n"
        "body = json.dumps({'status': 'UP', 'echo': os.environ['INTERNAL_SERVICE_TOKEN'] if internal and os.environ.get('ECHO_TOKEN') == '1' else ''})\n"
        "if '-o' in arguments:\n"
        "    pathlib.Path(arguments[arguments.index('-o') + 1]).write_text(body)\n"
        "else:\n"
        "    print(body, end='')\n"
        "if outcome == 'timeout':\n"
        "    print(os.environ['INTERNAL_SERVICE_TOKEN'], file=sys.stderr)\n"
        "    if '-w' in arguments:\n"
        "        print(arguments[arguments.index('-w') + 1].replace('%{http_code}', '000'), end='')\n"
        "    sys.exit(28)\n"
        "if '-w' in arguments:\n"
        "    print(arguments[arguments.index('-w') + 1].replace('%{http_code}', outcome), end='')\n"
        "if any(flag in arguments for flag in ['-f', '-fsS', '--fail']) and int(outcome) >= 400:\n"
        "    sys.exit(22)\n"
    )
    executable.chmod(0o755)
    if script == "ops/healthcheck.sh":
        source = functions(script, ["have", "run_check", "http_check"])
        commands = 'http_check "backend" "http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health" internal\nhttp_check "public" "http://127.0.0.1:8090/health"'
    elif script == "ops/release-smoke.sh":
        source = functions(script, ["have", "curl_check"])
        commands = 'curl_check "backend" "http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health" \'"status"\' internal\ncurl_check "public" "http://127.0.0.1:8090/health"'
    else:
        source = functions(script, ["wait_for_http"])
        commands = 'wait_for_http "backend" "http://127.0.0.1:8090/gaotu-assistant-bot/inner/ops/health"\nwait_for_http "web" "http://127.0.0.1:3000/health"'
    environment = {
        **os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CURL_CAPTURE": str(capture),
        "RUN_DIR": str(tmp_path), "INTERNAL_SERVICE_TOKEN": token, "CURL_OUTCOME": outcome,
        "HOST_CURL": "1" if host_curl else "0", "REAL_CURL": REAL_CURL or "",
        "ECHO_TOKEN": "1" if echo_token else "0", "PUBLIC_OUTCOME": public_outcome,
    }
    completed = subprocess.run(
        ["bash", "-c", 'set -uo pipefail\nTIMEOUT_SECONDS=1\nrecord() { printf "CHECK %s %s %s\\n" "$1" "$2" "${3:-}"; }\nfail() { printf "FAIL %s\\n" "$1"; return 1; }\nsleep() { SECONDS=$((SECONDS + 100)); }\n' + source + "\n" + commands],
        env=environment, capture_output=True, text=True, timeout=5,
    )
    assert completed.returncode == 0, completed.stderr
    calls = [json.loads(line) for line in capture.read_text().splitlines()]
    return completed, calls


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("outcome", ["200", "302", "401", "timeout"])
def test_authenticated_probes_require_2xx_and_keep_failures_secret(tmp_path, script, outcome):
    completed, calls = run_probes(tmp_path, script, outcome=outcome)
    internal = [call for call in calls if call["internal"]]
    assert len(internal) == 1
    if outcome == "200":
        assert "backend is healthy" in completed.stdout or "CHECK backend PASS" in completed.stdout
    else:
        assert "FAIL" in completed.stdout
        assert "backend is healthy" not in completed.stdout
        assert "CHECK backend PASS" not in completed.stdout
    assert TOKEN not in completed.stdout + completed.stderr
    assert internal[0]["configured"]
    assert internal[0]["header_matches"]
    assert internal[0]["directives"] == ["header"]
    assert internal[0]["args"][0] == "-q"
    assert TOKEN not in " ".join(internal[0]["args"])
    assert not {"-L", "--location", "--location-trusted", "-k", "--insecure"}.intersection(internal[0]["args"])
    public = [call for call in calls if not call["internal"]]
    assert len(public) == 1
    assert public[0]["stdin_empty"]
    assert not public[0]["configured"]
    if script == "ops/release-smoke.sh":
        assert {"-k", "-L"}.issubset(public[0]["args"])
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            assert TOKEN not in artifact.read_text()


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("outcome", ["200", "302", "401", "timeout"])
def test_authenticated_response_cannot_persist_an_echoed_credential(tmp_path, script, outcome):
    completed, _ = run_probes(tmp_path, script, outcome=outcome, echo_token=True)
    assert TOKEN not in completed.stdout + completed.stderr
    for artifact in tmp_path.rglob("*"):
        if artifact.is_file():
            assert TOKEN not in artifact.read_text()


@pytest.mark.parametrize("script", SCRIPTS)
def test_public_probes_preserve_existing_redirect_success(tmp_path, script):
    completed, _ = run_probes(tmp_path, script, public_outcome="302")
    assert "web is healthy" in completed.stdout or "CHECK public PASS" in completed.stdout


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("token", ["", " \t", "secret\rheader", "secret\nheader", 'secret"\nlocation = true'])
def test_missing_and_multiline_credentials_fail_without_invoking_curl(tmp_path, script, token):
    completed, calls = run_probes(tmp_path, script, token=token)
    assert not any(call["internal"] for call in calls)
    assert "FAIL" in completed.stdout
    assert "secret" not in completed.stdout + completed.stderr
    assert len(calls) == 1
    assert calls[0]["stdin_empty"]


@pytest.mark.parametrize("script", SCRIPTS)
def test_quoted_and_backslash_credentials_are_escaped_in_stdin_config(tmp_path, script):
    completed, calls = run_probes(tmp_path, script, token=ESCAPED_TOKEN)
    internal = next(call for call in calls if call["internal"])
    assert internal["configured"]
    assert internal["header_matches"]
    assert internal["directives"] == ["header"]
    assert ESCAPED_TOKEN not in completed.stdout + completed.stderr


@pytest.mark.skipif(not REAL_CURL, reason="host curl is unavailable")
@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("token", [TOKEN, ESCAPED_TOKEN])
def test_real_host_curl_file_protocol_compiles_the_intended_header(tmp_path, script, token):
    completed, calls = run_probes(tmp_path, script, token=token, host_curl=True)
    internal = next(call for call in calls if call["internal"])
    assert internal["header_matches"], "Host curl did not compile the intended credential header"
    assert token not in completed.stdout + completed.stderr


@pytest.mark.skipif(not REAL_CURL, reason="host curl is unavailable")
def test_host_file_protocol_demonstrates_legacy_header_at_dash_limit():
    result = subprocess.run(
        [REAL_CURL, "-q", "--silent", "--show-error", "--header", "@-", "--proto", "=file", "--libcurl", "/dev/stdout", "file:///dev/null"],
        input=f"X-Internal-Service-Token: {TOKEN}\n", text=True, capture_output=True, timeout=3,
    )
    assert result.returncode == 0
    version = subprocess.run([REAL_CURL, "--version"], text=True, capture_output=True, check=True).stdout.split()[1]
    if tuple(int(part) for part in version.split(".")) >= (7, 55, 0):
        pytest.skip("host curl supports reading headers from stdin")
    assert 'curl_slist_append(slist1, "@-")' in result.stdout
    assert TOKEN not in result.stdout + result.stderr
