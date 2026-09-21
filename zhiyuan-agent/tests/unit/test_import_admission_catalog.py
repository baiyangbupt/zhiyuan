"""B3 导入工具的测试。

它守的是"没有官方接口时那条替代路径"的边界：只收官方数据、校验到位、
原子落盘、manifest 是唯一入口。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "import_admission_catalog.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("import_admission_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def catalog(tmp_path):
    module = _load_module()
    return module, tmp_path / "catalog"


def _enrollment(**overrides):
    record = {
        "schoolId": "s1",
        "admissionYear": 2026,
        "areaId": "31",
        "batch": "本科批",
        "planCount": 20,
        "tuitionPerYear": 6000,
        "durationYears": 4,
        "subjectRequirements": ["物理"],
        "publishedAt": "2026-06-01",
        "sourceUrl": "https://school.example.edu/plan/2026",
    }
    record.update(overrides)
    return record


def _policy(**overrides):
    record = {
        "schoolId": "s1",
        "admissionYear": 2026,
        "clauseId": "article-12",
        "title": "身体条件",
        "quote": "原文条款的逐字摘录",
        "sourceUrl": "https://school.example.edu/policy/2026",
        "observedAt": "2026-06-02T08:00:00Z",
    }
    record.update(overrides)
    return record


def test_splits_files_by_year_and_school_and_writes_a_manifest(catalog) -> None:
    module, catalog_dir = catalog

    manifest = module.build_catalog(
        {"enrollment": [_enrollment()], "policy": [_policy()]}, catalog_dir
    )

    paths = {entry["path"] for entry in manifest["entries"]}
    assert paths == {"enrollment/2026/s1.json", "policy/2026/s1.json"}
    assert manifest["sourceMode"] == "imported_official"
    # 导入日与发布日是两件事，都要有。
    assert manifest["importedAt"]
    assert manifest["entries"][0]["publishedAt"]


def test_manifest_digest_matches_what_was_written(catalog) -> None:
    module, catalog_dir = catalog

    manifest = module.build_catalog({"enrollment": [_enrollment()]}, catalog_dir)

    entry = manifest["entries"][0]
    on_disk = (catalog_dir / entry["path"]).read_text(encoding="utf-8")
    assert module.digest(on_disk) == entry["digest"]


def test_same_school_across_years_is_isolated(catalog) -> None:
    """同校跨年条款必须分开存：混在一个文件里，"哪一年适用"就变成了靠字段猜。"""
    module, catalog_dir = catalog

    manifest = module.build_catalog(
        {
            "policy": [
                _policy(admissionYear=2025, clauseId="a", quote="2025 年的说法"),
                _policy(admissionYear=2026, clauseId="b", quote="2026 年的说法"),
            ]
        },
        catalog_dir,
    )

    assert {entry["path"] for entry in manifest["entries"]} == {
        "policy/2025/s1.json",
        "policy/2026/s1.json",
    }


def test_missing_required_field_is_refused(catalog) -> None:
    module, catalog_dir = catalog
    record = _enrollment()
    del record["planCount"]

    with pytest.raises(module.ImportError_, match="planCount"):
        module.build_catalog({"enrollment": [record]}, catalog_dir)


def test_a_plan_count_that_is_not_a_number_is_refused(catalog) -> None:
    module, catalog_dir = catalog

    # "20 人" 这种字符串看起来无害，但下游要拿它做数量约束。
    with pytest.raises(module.ImportError_, match="planCount"):
        module.build_catalog({"enrollment": [_enrollment(planCount="20")]}, catalog_dir)


def test_an_implausible_year_is_refused(catalog) -> None:
    module, catalog_dir = catalog

    with pytest.raises(module.ImportError_, match="admissionYear"):
        module.build_catalog({"enrollment": [_enrollment(admissionYear=26)]}, catalog_dir)


def test_overlong_policy_quote_is_refused_not_truncated(catalog) -> None:
    """全文该存 Artifact。截断后的"原文"既不是原文，也无法被核对。"""
    module, catalog_dir = catalog

    with pytest.raises(module.ImportError_, match="quote"):
        module.build_catalog(
            {"policy": [_policy(quote="x" * (module.MAX_QUOTE_CHARS + 1))]}, catalog_dir
        )


def test_input_must_be_utf8_json(catalog) -> None:
    module, _ = catalog
    import tempfile

    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as handle:
        handle.write(b"\xff\xfe not utf8")
        path = Path(handle.name)
    try:
        with pytest.raises(module.ImportError_, match="UTF-8"):
            module.load_input(path)
    finally:
        path.unlink()


def test_dry_run_does_not_touch_the_catalog(catalog) -> None:
    module, catalog_dir = catalog
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump({"enrollment": [_enrollment()]}, handle)
        path = Path(handle.name)
    try:
        assert module.main(["--input", str(path), "--catalog-dir", str(catalog_dir), "--dry-run"]) == 0
        assert not catalog_dir.exists()
    finally:
        path.unlink()


def test_entries_without_kind_are_refused(catalog) -> None:
    module, _ = catalog
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump([_enrollment()], handle)
        path = Path(handle.name)
    try:
        with pytest.raises(module.ImportError_, match="kind"):
            module.load_input(path)
    finally:
        path.unlink()
