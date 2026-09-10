from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT_DIR = Path(__file__).resolve().parents[3]
PREFLIGHT = ROOT_DIR / "scripts" / "preflight-codex-local.sh"
START = ROOT_DIR / "scripts" / "start-codex-local.sh"
STOP = ROOT_DIR / "scripts" / "stop-codex-local.sh"


def _run(script: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    process_env.update(env or {})
    for name in (
        "CODEX_LOCAL_SERVER_CONFIG",
        "CODEX_LOCAL_DATASET",
        "CODEX_LOCAL_CODEX_HOME",
        "CODEX_LOCAL_RUN_DIR",
    ):
        if not (env or {}).get(name):
            process_env.pop(name, None)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT_DIR,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_local_stack_scripts_have_valid_bash_syntax() -> None:
    for script in (PREFLIGHT, START, STOP):
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_start_refuses_to_build_or_launch_without_private_server_config() -> None:
    result = _run(START, "--skip-web")

    assert result.returncode != 0
    assert "CODEX_LOCAL_SERVER_CONFIG" in result.stderr
    assert "building backend jar" not in result.stdout


def test_preflight_rejects_a_checked_in_server_config_before_using_it(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(ROOT_DIR / "zhiyuan-server/src/main/resources/application-local.yml"),
            "CODEX_LOCAL_DATASET": "private-resettable",
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "must not use zhiyuan-server/src/main/resources defaults" in result.stderr


def test_preflight_requires_an_explicit_isolated_data_source(tmp_path: Path) -> None:
    config = tmp_path / "application-codex-local.yml"
    config.write_text("server:\n  port: 18290\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(config),
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "private-resettable" in result.stderr


def test_stop_refuses_to_target_an_arbitrary_directory(tmp_path: Path) -> None:
    result = _run(STOP, str(tmp_path))

    assert result.returncode != 0
    assert "run directory must be a direct child" in result.stderr


def test_preflight_rejects_a_run_directory_with_path_traversal(tmp_path: Path) -> None:
    config = tmp_path / "application-codex-local.yml"
    config.write_text("server:\n  port: 18290\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    escaped_run_dir = ROOT_DIR / ".runtime" / "codex-local-run" / ".." / "outside-run"

    result = _run(
        PREFLIGHT,
        "--skip-web",
        "--skip-build",
        "--run-dir",
        str(escaped_run_dir),
        env={
            "CODEX_LOCAL_SERVER_CONFIG": str(config),
            "CODEX_LOCAL_DATASET": "private-resettable",
            "CODEX_LOCAL_CODEX_HOME": str(codex_home),
        },
    )

    assert result.returncode != 0
    assert "run directory must be a direct child" in result.stderr


def test_lifecycle_scripts_require_a_per_run_process_marker() -> None:
    start_source = START.read_text(encoding="utf-8")
    stop_source = STOP.read_text(encoding="utf-8")

    assert 'exec env "CODEX_LOCAL_RUN_DIR=$RUN_DIR" setsid "$@"' in start_source
    assert "environment_matches_run" in stop_source
    assert 'CODEX_LOCAL_RUN_DIR=$RUN_DIR' in stop_source
