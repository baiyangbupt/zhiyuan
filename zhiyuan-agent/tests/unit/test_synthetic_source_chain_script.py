"""Safety boundaries for the reusable synthetic source chain probe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
BUILDER = ROOT / "scripts/validation/build_synthetic_source_fixture.py"
PROBE = ROOT / "scripts/validation/probe_synthetic_source_chain.py"


def _module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_dry_run_and_resume_dry_run_never_touch_external_boundaries(monkeypatch, tmp_path, capsys):
    module = _module(PROBE)
    module.EVIDENCE_ROOT = tmp_path / "would-not-be-created"
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: pytest.fail("dry run called Docker"))
    monkeypatch.setattr(module, "http", lambda *args, **kwargs: pytest.fail("dry run called HTTP"))
    monkeypatch.setattr(module, "sql", lambda *args, **kwargs: pytest.fail("dry run queried DB"))
    for extra in ([], ["--resume-evidence", str(tmp_path / "missing")]):
        monkeypatch.setattr(sys, "argv", [str(PROBE), *extra])
        module.main()
    assert not module.EVIDENCE_ROOT.exists()
    assert capsys.readouterr().out.count("Dry run only") == 2


def test_fixture_builder_dry_run_has_no_output_and_apply_never_overwrites(monkeypatch, tmp_path, capsys):
    module = _module(BUILDER)
    module.EVIDENCE_ROOT = tmp_path
    destination = tmp_path / "session-42"
    monkeypatch.setattr(sys, "argv", [str(BUILDER), "--session-id", "42", "--output-dir", str(destination)])
    module.main()
    assert not destination.exists()
    assert "Dry run:" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", [str(BUILDER), "--session-id", "42", "--output-dir", str(destination), "--apply"])
    module.main()
    source = json.loads((destination / "session_volunteer_42.json").read_text())
    assert len(source["detailList"]) == 12
    assert all(row["planSchoolDataId"].startswith("synthetic-42-") for row in source["detailList"])
    assert json.loads((destination / "score-detail.json").read_text())["prepareType"]["code"] == "PREDICT"
    with pytest.raises(FileExistsError):
        module.main()


@pytest.mark.parametrize("mutation", [
    lambda config: config["ali"]["oss"].pop("enabled"),
    lambda config: config["ali"]["oss"].update(enabled=True),
    lambda config: config["spring"]["datasource"]["dynamic"]["datasource"]["master"].update(
        url="jdbc:mysql://production.example:3306/zhiyuan?useSSL=true"),
    lambda config: config["volunteer"]["rank"].update(url="http://production.example:18292"),
    lambda config: config["gaotu"]["zhiyuan"].update(**{"program-data-url": "https://real.example"}),
])
def test_apply_preflight_rejects_nonlocal_or_nonisolated_config_before_db(monkeypatch, tmp_path, mutation):
    module = _module(PROBE)
    module.LOCAL = tmp_path
    module.SOURCE_ROOT = tmp_path / "tmp"
    config = {
        "spring": {"datasource": {"dynamic": {"datasource": {"master": {
            "url": "jdbc:mysql://127.0.0.1:13306/zhiyuan_codex_local?useSSL=false",
        }}}}},
        "volunteer": {"rank": {"url": "http://127.0.0.1:18292"}},
        "gaotu": {"zhiyuan": {
            "temp-data-path": str(module.SOURCE_ROOT),
            "zhiyuan-url": "https://127.0.0.1.invalid",
            "program-data-url": "https://127.0.0.1.invalid",
            "user-url": "https://127.0.0.1.invalid",
            "risk-url": "https://127.0.0.1.invalid",
        }},
        "ali": {"oss": {"enabled": False, "namespace": "codex-local"}},
    }
    mutation(config)
    (tmp_path / "application-codex-local.yml").write_text(yaml.safe_dump(config))
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: pytest.fail("unsafe config reached Docker"))
    with pytest.raises(RuntimeError):
        module.validate_local_config()


def test_disabled_oss_skip_log_is_not_remote_bridge_activity():
    module = _module(PROBE)
    log = "\n".join([
        "AliOSSService : OSS download skipped because OSS is disabled",
        "VolunteerBizService : 本地文件不存在，尝试从OSS下载",
        "AliOSSService : 开始从OSS下载文件，bucket: test",
        "AliOSSService : 开始上传文件到OSS，bucket: test",
        "JsonHttpUtil : invoke HTTP error: https://127.0.0.1.invalid/path",
    ])
    assert len(module.remote_bridge_lines(log)) == 3
