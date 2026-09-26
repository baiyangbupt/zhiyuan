#!/usr/bin/env python3
"""给 Codex 验收准备**可重置**的合成数据（Task C3）。

三条硬约束，都来自任务书 ✓：

1. **只碰本地 private-resettable 数据** ✓：目标实例必须与 `--expect-instance` 指名的容器
   对得上 ✓——`"private-resettable"` **这个字符串本身不是隔离证明** ✗（那只是数据源声明的名字 ✓）。
   核对方式是真身份 ✓：**该容器公布的 3306 端口 == 我实际要连的端口** ✓。
   （本机现状：这套 MySQL/Redis 容器**同时被正在跑的共享栈用着** ✗，所以这条不是形式主义 ✓。）
2. **reset 只删本次 runId 建的数据** ✓：删除清单**只来自** `fixture-ids.json` 的 `createdRows` ✓——
   绝不 `DROP`/`TRUNCATE`/按前缀删 ✗（那会清掉别人的栈 ✓）。
3. **不从线上复制个人资料** ✗：账户、成绩、画像全为**合成** ✓。

默认 **dry-run** ✓：不写库；要写必须显式 `--apply` ✓，且要过实例核对 ✓（fail-closed ✓）。

用法：
    zhiyuan-agent/.venv/bin/python scripts/seed-codex-acceptance.py --expect-instance <容器名> --run-id r1 --apply
    zhiyuan-agent/.venv/bin/python scripts/seed-codex-acceptance.py --reset .runtime/codex-acceptance/r1/fixture-ids.json --apply

产物（**忽略目录** ✓）：`.runtime/codex-acceptance/<runId>/fixture-ids.json` ✓、
`credentials.json`（0600 ✓，**不进** fixture ✓）。
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

if sys.version_info < (3, 10):  # 本机 /usr/bin/python3 是 3.6 ✗：先给一句人话再报错 ✓
    raise SystemExit("需要 Python >= 3.10 ✓（用 .venv 或 .tools 里的解释器 ✓）")

REPO_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ROOT = REPO_ROOT / ".runtime" / "codex-acceptance"

TENANT_ID_BASE = 90_000
SESSION_ID_BASE = 9_800_000
ACCOUNT_ID_BASE = 9_100_000


def derive_ids(run_id: str, tenant_count: int = 2, sessions_per_tenant: int = 2) -> dict[str, Any]:
    """由 runId **确定性**推出要建的 id ✓（同 runId 重跑得同一套 ✓，便于清理 ✓）。

    偏移用逐字符求和 % 1000 ✓，不用 `hash()` ✗（后者每个进程都不同 ✓）。
    """
    if not run_id.strip():
        raise ValueError("runId 不能为空 ✗（空 runId 圈不出这次建的数据 ✓）")
    offset = sum(ord(char) for char in run_id) % 1000
    tenants: list[dict[str, Any]] = []
    for index in range(tenant_count):
        tenants.append(
            {
                "tenantId": TENANT_ID_BASE + offset * 10 + index,
                "accountId": ACCOUNT_ID_BASE + offset * 10 + index,
                "accountName": "codex-acceptance-%s-%d" % (run_id, index),
                "sessionIds": [
                    SESSION_ID_BASE + offset * 100 + index * 10 + slot
                    for slot in range(sessions_per_tenant)
                ],
            }
        )
    return {"runId": run_id, "offset": offset, "tenants": tenants, "createdRows": []}


def synthetic_profile(tenant: Mapping[str, Any]) -> dict[str, Any]:
    """**合成**成绩与画像 ✓（不含任何真实个人资料 ✗）。"""
    index = int(tenant["tenantId"]) % 10
    return {
        "province": ["广东", "江西", "山东", "安徽"][index % 4],
        "examYear": 2026,
        "score": 480 + (index % 5) * 20,
        "subjectList": ["物理", "化学"],
        "positiveMajors": ["临床医学类", "计算机类"],
        "negativeMajors": ["哲学类"],
    }


def build_seed_rows(fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把 fixture 变成"要建哪些行"的清单 ✓——**每建一行都记一行** ✓（reset 的依据就是它 ✓）。"""
    rows: list[dict[str, Any]] = []
    for tenant in fixture.get("tenants") or []:
        profile = synthetic_profile(tenant)
        rows.append(
            {
                # 真表名是 `assistant_tenant_info` ✓（不是 `assistant_tenant` ✗——那是先前的臆造 ✓），
                # 且 `create_time` NOT NULL 无默认 ✗ → 必须由 `nowColumns` 补 ✓。
                "table": "assistant_tenant_info",
                "keyColumn": "id",
                "keyValue": int(tenant["tenantId"]),
                "values": {
                    "id": int(tenant["tenantId"]),
                    "tenant_id": int(tenant["tenantId"]),
                    "company_name": tenant["accountName"],
                },
                "nowColumns": ["create_time"],
            }
        )
        for session_id in tenant["sessionIds"]:
            rows.append(
                {
                    "table": "assistant_chat_session",
                    "keyColumn": "id",
                    "keyValue": int(session_id),
                    # 列与 `NOW()` 的用法**照抄 harness 里已验证可用的那条插入** ✓
                    # （`start_time`/`create_time`/`update_time` 都是 NOT NULL ✗）。
                    "values": {
                        "id": int(session_id),
                        "tenant_id": int(tenant["tenantId"]),
                        "bot_id": 1,
                        "user_id": str(tenant["accountId"]),
                        "user_name": tenant["accountName"],
                        "session_status": 1,
                    },
                    "nowColumns": ["start_time", "create_time", "update_time"],
                    "extraData": {"planningState": {"sessionId": int(session_id)}, "userScoreDetail": profile},
                }
            )
    return rows


def build_reset_statements(fixture: Mapping[str, Any]) -> list[tuple[str, tuple[Any, ...]]]:
    """把 fixture 里**记录在案的** id 变成删除语句 ✓。

    只认 `createdRows` ✓：删除范围**天然受限于本次 runId** ✓；
    没有按前缀/时间窗/全表的语句 ✗（那会误伤别人的数据 ✓）。
    """
    rows = fixture.get("createdRows")
    if not isinstance(rows, list):
        raise ValueError("fixture 里没有 createdRows —— 拒绝按猜测删除 ✗")
    statements: list[tuple[str, tuple[Any, ...]]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("createdRows 里出现非对象条目 ✗")
        table = str(row.get("table") or "").strip()
        key = str(row.get("keyColumn") or "").strip()
        value = row.get("keyValue")
        if not table or not key or value is None:
            raise ValueError("createdRows 条目不完整 ✗：%r" % (row,))
        _assert_identifier(table)
        _assert_identifier(key)
        statements.append(("DELETE FROM `%s` WHERE `%s` = %%s" % (table, key), (value,)))
    return statements


@dataclass(frozen=True)
class InstanceIdentity:
    container_name: str
    published_port: int


def verify_instance(identity: InstanceIdentity, expected_name: str, target_port: int) -> None:
    """实例身份核对 ✓：**指名容器公布的端口 == 实际要连的端口** ✓。

    为什么不看数据源字符串 ✗：`private-resettable` 是声明 ✓，声明可以是错的 ✓；
    端口归属是事实 ✓——写错库的代价与"多写一条断言"不成比例 ✓。
    """
    if not expected_name:
        raise ValueError("必须显式给 --expect-instance（拒绝对未指名的实例写数据 ✗）")
    if identity.container_name != expected_name:
        raise ValueError(
            "目标实例不符：期望 %s，实际 %s（中止，不动任何数据）" % (expected_name, identity.container_name)
        )
    if int(identity.published_port) != int(target_port):
        raise ValueError(
            "容器 %s 公布的 3306 是 %s，而这次要连的是 %s（中止，不动任何数据）"
            % (expected_name, identity.published_port, target_port)
        )


def container_published_port(container_name: str) -> int:
    """读容器公布的 3306 宿主端口 ✓（只读 ✓）。"""
    result = subprocess.run(
        ["docker", "port", container_name, "3306/tcp"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("读不到容器 %s 的端口：%s" % (container_name, result.stderr.strip()))
    for line in result.stdout.splitlines():
        _, _, port = line.strip().rpartition(":")
        if port.isdigit():
            return int(port)
    raise ValueError("容器 %s 没有公布 3306 端口 ✗" % container_name)


def write_fixture(run_dir: Path, fixture: Mapping[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "fixture-ids.json"
    target.write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def write_credentials(run_dir: Path, credentials: Mapping[str, str]) -> Path:
    """凭证单独存 ✓、0600 ✓、**不进 fixture** ✗（fixture 是要被读、被贴进报告的 ✓）。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "credentials.json"
    target.write_text(json.dumps(credentials, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return target


def _connect(args: argparse.Namespace) -> Any:
    import mysql.connector  # 只有真写库时才需要 ✓

    return mysql.connector.connect(
        host=args.host,
        port=int(args.port),
        database=args.database,
        user=args.user,
        password=args.password,
        connection_timeout=10,
    )


def _apply_reset(cursor: Any, statements: Sequence[tuple[str, tuple[Any, ...]]]) -> int:
    deleted = 0
    for sql, params in statements:
        cursor.execute(sql, params)
        deleted += cursor.rowcount
    return deleted


def _assert_identifier(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError("只允许标识符 ✓：%r" % (name,))
    return name


def _apply_seed(cursor: Any, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for row in rows:
        values = dict(row["values"])
        now_columns = list(row.get("nowColumns") or [])
        columns = [_assert_identifier(str(name)) for name in values]
        columns += [_assert_identifier(str(name)) for name in now_columns]
        placeholders = ["%s"] * len(values) + ["NOW()"] * len(now_columns)
        cursor.execute(
            "INSERT IGNORE INTO `%s` (%s) VALUES (%s)"
            % (_assert_identifier(str(row["table"])),
               ", ".join("`%s`" % name for name in columns),
               ", ".join(placeholders)),
            tuple(values.values()),
        )
        created.append(
            {"table": row["table"], "keyColumn": row["keyColumn"], "keyValue": row["keyValue"]}
        )
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed resettable acceptance data (Task C3).")
    parser.add_argument("--expect-instance", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--reset", default="", help="fixture-ids.json：只删其中记录的 id")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run ✓）")
    parser.add_argument("--host", default=os.getenv("CODEX_ACCEPTANCE_DB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CODEX_ACCEPTANCE_DB_PORT", "13306")))
    parser.add_argument("--database", default=os.getenv("CODEX_ACCEPTANCE_DB_NAME", ""))
    parser.add_argument("--user", default=os.getenv("CODEX_ACCEPTANCE_DB_USER", ""))
    parser.add_argument("--password", default=os.getenv("CODEX_ACCEPTANCE_DB_PASSWORD", ""))
    args = parser.parse_args(argv)

    if args.reset:
        fixture = json.loads(Path(args.reset).read_text(encoding="utf-8"))
        statements = build_reset_statements(fixture)
        print("reset 计划：%d 条删除（**只删 fixture 里记录的 id** ✓）" % len(statements))
        for sql, params in statements:
            print("  %s -- %r" % (sql, params))
        if not args.apply:
            print("dry-run ✓：加 --apply 才真正执行 ✓")
            return 0
    else:
        if not args.run_id:
            raise SystemExit("缺少 --run-id（没有 runId 就圈不出这次建的数据 ✗）")
        fixture = derive_ids(args.run_id)
        rows = build_seed_rows(fixture)
        run_dir = ACCEPTANCE_ROOT / args.run_id
        print("runId=%s → %d 行；首个合成画像：%s" % (
            args.run_id, len(rows),
            json.dumps(synthetic_profile(fixture["tenants"][0]), ensure_ascii=False)))
        if not args.apply:
            print("dry-run ✓：加 --apply 才真正建数据 ✓（并要求实例核对通过 ✓）")
            return 0
        if not (args.database and args.user):
            raise SystemExit("真要写库时必须给 --database/--user（或对应的 CODEX_ACCEPTANCE_DB_* ✓）")
        fixture["createdRows"] = [dict(row) for row in rows]
        write_fixture(run_dir, {"runId": args.run_id, "tenants": fixture["tenants"], "createdRows": []})

    if not (args.database and args.user):
        raise SystemExit("真要写库时必须给 --database/--user（或对应的 CODEX_ACCEPTANCE_DB_* ✓）")

    # 实例核对**在连接之前** ✓（连错库这件事，连上就已经晚了 ✓）。
    verify_instance(
        InstanceIdentity(args.expect_instance, container_published_port(args.expect_instance)),
        args.expect_instance,
        args.port,
    )
    connection = _connect(args)
    try:
        cursor = connection.cursor()
        try:
            if args.reset:
                deleted = _apply_reset(cursor, statements)
                print("reset 完成 ✓：删除 %d 行（只限本次 runId ✓）" % deleted)
            else:
                created = _apply_seed(cursor, rows)
                fixture["createdRows"] = created
                write_fixture(ACCEPTANCE_ROOT / args.run_id, fixture)
                write_credentials(
                    ACCEPTANCE_ROOT / args.run_id,
                    {"user": args.user, "password": "***（见本地配置 ✓）", "database": args.database},
                )
                print("seed 完成 ✓：%d 行；fixture 已写 ✓" % len(created))
        finally:
            cursor.close()
        connection.commit()
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
