#!/usr/bin/env python3
"""把官方年度招生计划与章程导入为只读 catalog。

**为什么需要它**：`docs/contracts/admission-sources-v1.md` 的调查结论是
本仓没有年度计划与章程的官方接口。没有来源时，B3 的两项能力保持关闭，
而不是拿合成数据把业务 gate 关掉——那会让"能力已就绪"变成一个查不出处的说法。

这条路径的边界，写在这里是为了别被后来的使用者放宽：

1. **只接受运维提供的官方数据**，不联网抓取、不代替官方发布；
2. **记录来源**：每条文件带 `sourceUrl` / `publishedAt` / 导入日，
   不宣称"在线实时更新"；
3. **原子落盘**：先写临时文件再 `os.replace`，中途失败不会留下半份 catalog；
4. **manifest 是唯一入口**：Java 只加载 manifest 列出的文件，不接受
   请求传入路径——否则等于把文件读取权交给调用方。

用法：
    python scripts/import_admission_catalog.py --input official.json --catalog-dir /path/to/catalog
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"

# 章程原文摘录上限。与 B3 合同一致：超过就该存全文 Artifact，
# 而不是让一大段文本挤进模型的上下文。
MAX_QUOTE_CHARS = 2000

ENROLLMENT_REQUIRED = (
    "schoolId",
    "admissionYear",
    "areaId",
    "batch",
    "planCount",
    "subjectRequirements",
    "publishedAt",
    "sourceUrl",
)
POLICY_REQUIRED = (
    "schoolId",
    "admissionYear",
    "clauseId",
    "title",
    "quote",
    "sourceUrl",
    "observedAt",
)


class ImportError_(RuntimeError):
    """导入失败。名字带下划线是为了不和内置的 ImportError 撞。"""


def canonical_json(value: Any) -> str:
    """稳定序列化：摘要只取决于内容，不取决于键的书写顺序。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_text(record: dict, field: str, where: str) -> None:
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ImportError_(f"{where}: 缺字段 {field}")


def validate_enrollment(record: dict, index: int) -> dict:
    where = f"enrollment[{index}]"
    if not isinstance(record, dict):
        raise ImportError_(f"{where}: 不是对象")
    for field in ENROLLMENT_REQUIRED:
        _require_text(record, field, where)
    if not isinstance(record.get("subjectRequirements"), list):
        raise ImportError_(f"{where}: subjectRequirements 必须是数组")
    year = record.get("admissionYear")
    if not isinstance(year, int) or year < 2000 or year > 2100:
        # 年份写错会让学生看到"2025 年招 20 人"而实际是别的年份，
        # 而年份是这类数据的第一坐标。
        raise ImportError_(f"{where}: admissionYear 不像年份: {year!r}")
    plan_count = record.get("planCount")
    if not isinstance(plan_count, int) or plan_count < 0:
        raise ImportError_(f"{where}: planCount 必须是非负整数")
    return record


def validate_policy(record: dict, index: int) -> dict:
    where = f"policy[{index}]"
    if not isinstance(record, dict):
        raise ImportError_(f"{where}: 不是对象")
    for field in POLICY_REQUIRED:
        _require_text(record, field, where)
    quote = str(record.get("quote"))
    if len(quote) > MAX_QUOTE_CHARS:
        raise ImportError_(
            f"{where}: quote 超过 {MAX_QUOTE_CHARS} 字，全文应存 Artifact，不要塞进条款"
        )
    year = record.get("admissionYear")
    if not isinstance(year, int) or year < 2000 or year > 2100:
        raise ImportError_(f"{where}: admissionYear 不像年份: {year!r}")
    return record


def load_input(path: Path) -> dict[str, list]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ImportError_("输入不是 UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ImportError_(f"输入不是合法 JSON: {exc}") from exc
    if isinstance(raw, list):
        grouped: dict[str, list] = {"enrollment": [], "policy": []}
        for index, record in enumerate(raw):
            kind = (record or {}).get("kind") if isinstance(record, dict) else None
            if kind not in grouped:
                raise ImportError_(f"[{index}]: 缺 kind 或 kind 不是 enrollment/policy")
            grouped[kind].append(record)
        return grouped
    if not isinstance(raw, dict):
        raise ImportError_("输入必须是对象或数组")
    return {
        "enrollment": list(raw.get("enrollment") or []),
        "policy": list(raw.get("policy") or []),
    }


def atomic_write(path: Path, text: str) -> None:
    """先写临时文件再 rename：中途失败不会留下半份 catalog。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def build_catalog(records: dict[str, list], catalog_dir: Path) -> dict:
    entries: list[dict] = []
    for kind, validator in (("enrollment", validate_enrollment), ("policy", validate_policy)):
        buckets: dict[tuple[int, str], list[dict]] = {}
        for index, record in enumerate(records.get(kind) or []):
            valid = validator(record, index)
            buckets.setdefault((valid["admissionYear"], str(valid["schoolId"])), []).append(valid)

        for (year, school_id), rows in sorted(buckets.items()):
            payload = {"kind": kind, "admissionYear": year, "schoolId": school_id, "records": rows}
            text = canonical_json(payload)
            relative = Path(kind) / str(year) / f"{school_id}.json"
            atomic_write(catalog_dir / relative, text)
            entries.append(
                {
                    "kind": kind,
                    "path": str(relative),
                    "admissionYear": year,
                    "schoolId": school_id,
                    "recordCount": len(rows),
                    "digest": digest(text),
                    "sourceUrl": rows[0].get("sourceUrl"),
                    "publishedAt": rows[0].get("publishedAt") or rows[0].get("observedAt"),
                }
            )
    return {
        "version": 1,
        "sourceMode": "imported_official",
        # 导入日与发布日是两件事：前者是"我们什么时候抄进来的"，
        # 后者是"官方什么时候发的"。只记一个会让读者分不清。
        "importedAt": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="官方数据的 UTF-8 JSON")
    parser.add_argument("--catalog-dir", type=Path, required=True, help="部署目录（Java 读这里）")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不落盘")
    args = parser.parse_args(argv)

    try:
        records = load_input(args.input)
        if args.dry_run:
            for kind, validator in (("enrollment", validate_enrollment), ("policy", validate_policy)):
                for index, record in enumerate(records.get(kind) or []):
                    validator(record, index)
            print(
                json.dumps(
                    {
                        "dryRun": True,
                        "enrollment": len(records.get("enrollment") or []),
                        "policy": len(records.get("policy") or []),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        manifest = build_catalog(records, args.catalog_dir)
        atomic_write(args.catalog_dir / MANIFEST_NAME, canonical_json(manifest))
    except ImportError_ as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "entries": len(manifest["entries"]),
                "catalogDir": str(args.catalog_dir),
                "importedAt": manifest["importedAt"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
