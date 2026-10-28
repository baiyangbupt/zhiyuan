from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest
import yaml


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT = ROOT_DIR / "scripts" / "codex-local-infra.sh"
COMPOSE_FILE = ROOT_DIR / "docker-compose.codex-local.yml"


def test_infra_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_infra_help_is_read_only_and_documents_reset_boundary() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "reset" in result.stdout
    assert "dedicated Codex local volumes" in result.stdout


def test_compose_uses_named_isolated_volumes_and_health_checks() -> None:
    source = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "name: zhiyuan_codex_local_mysql_data" in source
    assert "name: zhiyuan_codex_local_redis_data" in source
    assert "mysqladmin ping" in source
    assert "redis-cli" in source


def test_infra_script_does_not_use_the_shared_compose_file() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker-compose.codex-local.yml" in source
    assert "docker-compose.yml" not in source
    assert "--remove-orphans" in source


@pytest.mark.parametrize("fallback", [None, "", "VOLUNTEER"])
def test_generated_local_config_persists_demo_mode_across_regeneration(tmp_path, fallback) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o700)
    state = tmp_path / "state"
    state.mkdir()
    (state / "infra.env").write_text(
        "MYSQL_ROOT_PASSWORD=test-only-password\nMYSQL_DATABASE=isolated_test\n"
        "MYSQL_PORT=13306\nREDIS_PORT=16379\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["CODEX_LOCAL_INFRA_DIR"] = str(state)
    env.pop("CODEX_LOCAL_PREPARE_TYPE_FALLBACK", None)
    if fallback is not None:
        env["CODEX_LOCAL_PREPARE_TYPE_FALLBACK"] = fallback
    for _ in range(2):
        result = subprocess.run(
            ["bash", str(SCRIPT), "start"], cwd=ROOT_DIR,
            env=env, text=True, capture_output=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        config = yaml.safe_load((state / "application-codex-local.yml").read_text())
        assert config.get("demo", {}).get("prepare-type-fallback") == (
            "PREDICT" if fallback is None else fallback
        )
        assert config["ali"]["oss"]["enabled"] is False
        assert config["ali"]["oss"]["namespace"] == "codex-local"


def test_invalid_demo_mode_is_rejected_before_private_state_is_created(tmp_path) -> None:
    state = tmp_path / "not-created"
    env = os.environ.copy()
    env["CODEX_LOCAL_INFRA_DIR"] = str(state)
    env["CODEX_LOCAL_PREPARE_TYPE_FALLBACK"] = "INVALID"

    result = subprocess.run(
        ["bash", str(SCRIPT), "start"], cwd=ROOT_DIR,
        env=env, text=True, capture_output=True, check=False,
    )

    assert result.returncode != 0
    assert "CODEX_LOCAL_PREPARE_TYPE_FALLBACK" in result.stderr
    assert not state.exists()
