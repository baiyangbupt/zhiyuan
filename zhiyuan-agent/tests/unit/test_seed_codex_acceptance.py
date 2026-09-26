"""`scripts/seed-codex-acceptance.py` 的守卫（Task C3）。

这个脚本能**删数据** ✓，而它的目标实例在本机**同时被共享栈用着** ✗
（13306/16379 是同一套 MySQL/Redis ✓）——所以这里的重点不是"功能对不对" ✓，
而是**删除范围绝不可能越界** ✓：只删 fixture 里记录在案的 id ✓。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT = ROOT_DIR / "scripts" / "seed-codex-acceptance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_codex_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # `@dataclass` 会回查 `sys.modules[cls.__module__]` ✗——不登记就拿到 None ✓，
    # 报的是一句与真正原因无关的 `AttributeError` ✗（所以必须先登记 ✓）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _load_module()


def test_derive_ids_is_deterministic_and_inside_reserved_ranges() -> None:
    first = seed.derive_ids("run-a")
    again = seed.derive_ids("run-a")
    other = seed.derive_ids("run-b")

    assert first == again, "同 runId 必须得到同一套 id（否则清理无从下手）"
    assert first != other, "不同 runId 不该撞到同一套 id"
    assert len(first["tenants"]) == 2, "任务书要求两个 tenant"
    for tenant in first["tenants"]:
        assert tenant["tenantId"] >= 90_000, "tenant 必须落在保留段，别碰线上号段"
        assert len(tenant["sessionIds"]) >= 2
        for session_id in tenant["sessionIds"]:
            assert session_id >= 9_800_000


def test_seed_rows_use_real_tables_and_cover_not_null_columns() -> None:
    """表名与 NOT NULL 列必须与真库对得上 ✓——先前就是这里臆造了一张不存在的表 ✗。

    真库事实（2026-09-26 只读核对 ✓）：租户表是 `assistant_tenant_info` ✓（且 `create_time`
    NOT NULL 无默认 ✗）；`assistant_chat_session` 的 `start_time`/`create_time`/`update_time`
    同样 NOT NULL ✗（harness 里那条可用插入给了三个 `NOW()` ✓）。
    """
    fixture = seed.derive_ids("run-schema")
    rows = seed.build_seed_rows(fixture)

    tables = {row["table"] for row in rows}
    assert tables == {"assistant_tenant_info", "assistant_chat_session"}
    assert "assistant_tenant" not in tables, "不存在的表名不许再出现 ✗"

    for row in rows:
        now_columns = set(row.get("nowColumns") or [])
        if row["table"] == "assistant_tenant_info":
            assert {"id", "tenant_id", "company_name"} <= set(row["values"])
            assert "create_time" in now_columns
            assert "tenant_name" not in row["values"], "臆造的列名 ✗"
        else:
            assert {"id", "tenant_id", "bot_id", "user_id", "user_name", "session_status"} <= set(row["values"])
            assert {"start_time", "create_time", "update_time"} <= now_columns


def test_reset_statements_cover_exactly_the_recorded_ids() -> None:
    """删多少、删谁，**完全由 fixture 决定** ✓——这是本脚本最重要的一条 ✓。"""
    fixture = {
        "runId": "run-a",
        "createdRows": [
            {"table": "assistant_chat_session", "keyColumn": "id", "keyValue": 9_800_123},
            {"table": "assistant_tenant", "keyColumn": "id", "keyValue": 90_123},
        ],
    }

    statements = seed.build_reset_statements(fixture)

    assert len(statements) == 2
    assert statements[0] == ("DELETE FROM `assistant_chat_session` WHERE `id` = %s", (9_800_123,))
    assert "TRUNCATE" not in " ".join(sql for sql, _ in statements).upper()
    assert "DROP" not in " ".join(sql for sql, _ in statements).upper()


def test_reset_refuses_a_fixture_without_recorded_rows() -> None:
    with pytest.raises(ValueError, match="createdRows"):
        seed.build_reset_statements({"runId": "run-a"})


def test_reset_refuses_non_identifier_table_or_column() -> None:
    with pytest.raises(ValueError, match="标识符"):
        seed.build_reset_statements(
            {"createdRows": [{"table": "x; DROP TABLE y", "keyColumn": "id", "keyValue": 1}]}
        )


def test_verify_instance_requires_name_and_matching_port() -> None:
    with pytest.raises(ValueError, match="expect-instance"):
        seed.verify_instance(seed.InstanceIdentity("c", 13306), "", 13306)

    with pytest.raises(ValueError, match="不符"):
        seed.verify_instance(seed.InstanceIdentity("other", 13306), "c", 13306)

    # 名字对但端口不对：说明那个容器公布的不是我要连的实例 ✓——一样中止 ✓
    with pytest.raises(ValueError, match="公布的 3306"):
        seed.verify_instance(seed.InstanceIdentity("c", 33060), "c", 13306)

    seed.verify_instance(seed.InstanceIdentity("c", 13306), "c", 13306)


def test_dry_run_touches_nothing() -> None:
    """默认 dry-run ✓：不写库、不连库 ✓（连库都不该尝试 ✓）。"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-id", "run-dry"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert "dry-run" in result.stdout
    assert "INSERT" not in result.stdout.upper()


def test_apply_without_run_id_is_refused() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--apply"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--run-id" in result.stderr


def test_reset_needs_a_real_fixture_file(tmp_path: Path) -> None:
    fixture = {
        "runId": "run-a",
        "createdRows": [{"table": "assistant_tenant", "keyColumn": "id", "keyValue": 90_123}],
    }
    path = tmp_path / "fixture-ids.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--reset", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "reset 计划：1 条删除" in result.stdout
    assert "90_123" not in result.stdout  # 参数是 %s 占位，不该被拼进 SQL 文本 ✓
    assert "dry-run" in result.stdout
