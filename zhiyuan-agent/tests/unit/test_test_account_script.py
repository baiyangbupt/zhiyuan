"""Safety boundaries for the isolated local browser test account helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/prepare-codex-test-account.py"


def _module():
    spec = importlib.util.spec_from_file_location("prepare_codex_test_account", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_config(tmp_path: Path) -> None:
    (tmp_path / "application-codex-local.yml").write_text(
        "jdbc:mysql://127.0.0.1:13306/zhiyuan_codex_local", encoding="utf-8",
    )


@pytest.mark.parametrize("name", ["../codex-test", "codex-test/other", "codex-test';DELETE", "real-user", "codex-test-", "codex-test-" + "a" * 64])
def test_unsafe_account_name_is_rejected_without_changing_target(name):
    module = _module()
    original = (module.USERNAME, module.CREDENTIALS)
    with pytest.raises(ValueError):
        module.configure_account(name)
    assert (module.USERNAME, module.CREDENTIALS) == original


def test_named_accounts_keep_distinct_private_credentials(monkeypatch, tmp_path, capsys):
    module = _module()
    module.PRIVATE_DIR = tmp_path
    _local_config(tmp_path)
    monkeypatch.setattr(module, "run", lambda command, input_text=None:
                        "127.0.0.1:13306" if command[:2] == ["docker", "port"] else "")
    inserts = []

    def database(statement):
        if statement.startswith("SELECT user_id"):
            return ""
        assert statement.startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;")
        inserts.append(statement)
        return str(100 + len(inserts))

    monkeypatch.setattr(module, "sql", database)
    records = []
    files = []
    for name in ("codex-test-alice", "codex-test-bob"):
        module.configure_account(name)
        module.prepare()
        files.append(module.CREDENTIALS)
        records.append(json.loads(module.CREDENTIALS.read_text()))
        assert module.CREDENTIALS.stat().st_mode & 0o777 == 0o600
    assert files[0] != files[1]
    assert records[0]["userId"] != records[1]["userId"]
    assert records[0]["password"] != records[1]["password"]
    assert records[0]["username"] == "codex-test-alice"
    assert records[1]["username"] == "codex-test-bob"
    assert json.loads(files[0].read_text()) == records[0]
    assert "codex-test-bob" not in inserts[0]
    assert "codex-test-alice" not in inserts[1]
    output = capsys.readouterr().out
    assert all(record["password"] not in output for record in records)


def test_concurrent_account_winner_does_not_get_a_second_credential_file(monkeypatch, tmp_path):
    module = _module()
    module.PRIVATE_DIR = tmp_path
    _local_config(tmp_path)
    module.configure_account("codex-test-race")
    monkeypatch.setattr(module, "run", lambda command, input_text=None:
                        "127.0.0.1:13306" if command[:2] == ["docker", "port"] else "")
    monkeypatch.setattr(module, "sql", lambda statement:
                        "" if statement.startswith("SELECT user_id") else "0")
    with pytest.raises(RuntimeError, match="created concurrently"):
        module.prepare()
    assert not module.CREDENTIALS.exists()


def test_dry_run_never_calls_external_process_or_writes_credential(monkeypatch, capsys) -> None:
    credentials = SCRIPT.parents[1] / ".local/codex-local/browser-test-credentials.json"
    before = credentials.read_bytes() if credentials.exists() else None

    def unexpected_process(*args, **kwargs):
        raise AssertionError("dry run must not call Docker or MySQL")

    monkeypatch.setattr(subprocess, "run", unexpected_process)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    runpy.run_path(str(SCRIPT), run_name="__main__")

    assert (credentials.read_bytes() if credentials.exists() else None) == before
    assert "Dry run:" in capsys.readouterr().out


def test_wrong_container_port_refuses_before_database_access(monkeypatch) -> None:
    module = _module()
    calls: list[list[str]] = []

    def fake_run(command, input_text=None):
        calls.append(command)
        return "127.0.0.1:3306"

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "sql", lambda statement: pytest.fail("database must not be queried"))
    with pytest.raises(RuntimeError, match="outside the isolated local container"):
        module.prepare()
    assert calls == [["docker", "port", module.CONTAINER, "3306/tcp"]]


def test_wrong_java_database_refuses_before_database_access(monkeypatch, tmp_path) -> None:
    module = _module()
    module.PRIVATE_DIR = tmp_path
    (tmp_path / "application-codex-local.yml").write_text(
        "jdbc:mysql://127.0.0.1:13306/other_database", encoding="utf-8",
    )
    monkeypatch.setattr(module, "run", lambda command, input_text=None: "127.0.0.1:13306")
    monkeypatch.setattr(module, "sql", lambda statement: pytest.fail("database must not be queried"))
    with pytest.raises(RuntimeError, match="Java configuration does not target"):
        module.prepare()


def test_existing_unowned_codex_test_refuses_all_writes(monkeypatch, tmp_path) -> None:
    module = _module()
    module.PRIVATE_DIR = tmp_path
    module.CREDENTIALS = tmp_path / "browser-test-credentials.json"
    _local_config(tmp_path)
    commands: list[list[str]] = []
    statements: list[str] = []

    def fake_run(command, input_text=None):
        commands.append(command)
        return "127.0.0.1:13306" if command[:2] == ["docker", "port"] else ""

    def fake_sql(statement):
        statements.append(statement)
        return "123"

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "sql", fake_sql)
    with pytest.raises(RuntimeError, match="not owned by this fixture"):
        module.prepare()
    assert len(statements) == 1 and statements[0].startswith("SELECT user_id")
    assert all("INSERT" not in statement and "UPDATE" not in statement for statement in statements)
    assert not module.CREDENTIALS.exists()
    assert any(command[:2] == ["docker", "exec"] for command in commands)


def test_private_file_cannot_retarget_nonfixture_account(monkeypatch, tmp_path) -> None:
    module = _module()
    module.PRIVATE_DIR = tmp_path
    module.CREDENTIALS = tmp_path / "browser-test-credentials.json"
    _local_config(tmp_path)
    module.CREDENTIALS.write_text(json.dumps({
        "username": "unrelated-account",
        "password": "a" * 32,
        "userId": 123,
    }), encoding="utf-8")
    original = module.CREDENTIALS.read_bytes()
    statements: list[str] = []

    def fake_run(command, input_text=None):
        return "127.0.0.1:13306" if command[:2] == ["docker", "port"] else ""

    def fake_sql(statement):
        statements.append(statement)
        return ""

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "sql", fake_sql)
    with pytest.raises(RuntimeError, match="non-fixture account"):
        module.prepare()
    assert len(statements) == 1 and statements[0].startswith("SELECT user_id")
    assert module.CREDENTIALS.read_bytes() == original


@pytest.mark.parametrize("changed_field", ["tenant_id", "channel"])
def test_stale_fixture_identity_refuses_update(monkeypatch, tmp_path, changed_field) -> None:
    module = _module()
    module.PRIVATE_DIR = tmp_path
    module.CREDENTIALS = tmp_path / "browser-test-credentials.json"
    _local_config(tmp_path)
    module.CREDENTIALS.write_text(json.dumps({
        "username": "codex-browser-e2e-68da100f6273e2db",
        "password": "a" * 32,
        "userId": 123,
    }), encoding="utf-8")
    original = module.CREDENTIALS.read_bytes()
    statements: list[str] = []

    monkeypatch.setattr(
        module, "run",
        lambda command, input_text=None: "127.0.0.1:13306" if command[:2] == ["docker", "port"] else "",
    )

    def fake_sql(statement):
        statements.append(statement)
        if statement.startswith("SELECT user_id"):
            return ""
        if statement.startswith("SELECT credential_id"):
            return "17"
        if statement.startswith("SELECT COUNT(*)"):
            assert ("u.tenant_id=1" if changed_field == "tenant_id" else "u.channel='ytell'") in statement
            return "0"  # The database row no longer satisfies the fixture ownership predicate.
        pytest.fail("a changed fixture identity must not reach a database write")

    monkeypatch.setattr(module, "sql", fake_sql)
    with pytest.raises(RuntimeError, match="fixture user identity changed"):
        module.prepare()
    assert len(statements) == 3
    assert not any(statement.startswith(("UPDATE", "INSERT")) for statement in statements)
    assert module.CREDENTIALS.read_bytes() == original
