from __future__ import annotations

from pathlib import Path
import subprocess


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
