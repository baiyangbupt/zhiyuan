#!/usr/bin/env python3
"""串行运行核心 Codex 语义场景，并输出 JSONL 结果。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.codex_semantic_smoke import (
    authoritative_history_scenario,
    complete_history_scenario,
    mixed_read_write_scenario,
    reference_missing_scope_scenario,
    run_scenario,
)
from scripts.codex_semantic_report import classify_result


SCENARIOS = {
    "reference-missing-scope": reference_missing_scope_scenario,
    "reference-complete-history": complete_history_scenario,
    "reference-authoritative-history": authoritative_history_scenario,
    "mixed-read-write": mixed_read_write_scenario,
}


async def run_batch(names: list[str], retries: int = 1) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    retries = max(0, retries)
    for name in names:
        for attempt in range(retries + 1):
            try:
                result = await run_scenario(SCENARIOS[name])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A harness or App Server failure must not prevent the remaining
                # scenarios from producing a regression report.
                result = {
                    "scenario": name,
                    "status": "environment_blocked",
                    "errorCode": "scenario_runner_exception",
                    "errors": [{"type": type(exc).__name__}],
                }
            result["batchScenario"] = name
            result["batchAttempt"] = attempt + 1
            result["retryCategory"] = classify_result(result)
            results.append(result)
            if result["retryCategory"] not in {"environment_blocked", "model_failure"}:
                break
            if attempt < retries:
                await asyncio.sleep(2)
    return results


def write_jsonl(output: Path, results: list[dict[str, object]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", choices=sorted(SCENARIOS))
    parser.add_argument("--output", type=Path, required=True, help="JSONL 输出路径")
    parser.add_argument("--retries", type=int, default=1, help="环境失败后的重试次数")
    args = parser.parse_args()
    names = args.scenario or list(SCENARIOS)
    results = asyncio.run(run_batch(names, args.retries))
    write_jsonl(args.output, results)
    print(f"已写入 {len(results)} 次回放（{len(names)} 个场景）: {args.output}")


if __name__ == "__main__":
    main()
