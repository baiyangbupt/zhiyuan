from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "ops" / "release-smoke.sh"


@pytest.mark.parametrize(
    ("base_path", "expected_session_path"),
    [
        (None, "/assistant-pc/session"),
        ("", "/session"),
    ],
)
def test_release_smoke_supports_production_and_dev_web_base_paths(
    tmp_path: Path,
    base_path: str | None,
    expected_session_path: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
set -eu
output=''
url=''
write_out=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    -m|-w|-o)
      [ "$1" = "-o" ] && output="$2"
      [ "$1" = "-w" ] && write_out="$2"
      shift 2
      ;;
    -*)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done
body='<html><script id="__NEXT_DATA__"></script>{"status":"UP","data":{}}</html>'
if [ -n "$output" ]; then
  printf '%s' "$body" > "$output"
else
  printf '%s' "$body"
fi
printf '%s\\n' "$url" >> "$FAKE_CURL_LOG"
printf '%s' "${write_out//\\%\\{http_code\\}/200}"
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_CURL_LOG": str(curl_log),
            "ZHIYUAN_SMOKE_WEBSOCKET": "off",
            "INTERNAL_SERVICE_TOKEN": "offline-regression-credential",
        }
    )
    if base_path is None:
        env.pop("ZHIYUAN_WEB_BASE_PATH", None)
    else:
        env["ZHIYUAN_WEB_BASE_PATH"] = base_path

    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT), "--local"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    urls = curl_log.read_text(encoding="utf-8").splitlines()
    assert f"http://127.0.0.1:3001{expected_session_path}" in urls
    assert (
        f"http://127.0.0.1:3001{expected_session_path.replace('/session', '/sessionDetailV2')}"
        in urls
    )
    if base_path == "":
        assert "web basePath manifest    PASS  development basePath disabled" in result.stdout
