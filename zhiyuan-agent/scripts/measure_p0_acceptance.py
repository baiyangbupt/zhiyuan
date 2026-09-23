"""P0 验收条测量：两个复杂场景各跑 N 次，报通过率 + Wilson 95% 置信区间。

判据（`README.md` 第六节修订后的形式）：「20 次中至少 19 次」+ 报置信区间，
不再用"连续 3 次"——那条在真实可靠性 95% 时有 85.7% 的概率通过，区分不了 85% 与 100%。

用法: .venv/bin/python scripts/measure_p0_acceptance.py [N]   （默认 20）

判据与留底见 `docs/superpowers/tasks/P0-acceptance-measurement/REPORT.md`；
P3（流程门禁）把它当作主判据。
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time

SCENARIOS = ["reference-complete-history", "mixed-read-write"]
AGENT = "/root/dev/zhiyuan/zhiyuan-agent"


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 区间：小样本比正态近似稳。"""
    if total == 0:
        return (0.0, 1.0)
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def run_one(scenario: str) -> dict:
    proc = subprocess.run(
        [".venv/bin/python", "scripts/codex_semantic_smoke.py", "--scenario", scenario],
        cwd=AGENT, capture_output=True, text=True, timeout=300,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"passed": None, "failures": ["unparsable_output"], "error": proc.stderr[-200:]}
    evaluation = payload.get("evaluation") or {}
    return {
        "passed": evaluation.get("passed"),
        "failures": evaluation.get("failures") or [],
        "validationError": bool(payload.get("outputValidationError")),
        "status": payload.get("status"),
    }


def main() -> None:
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    summary = {}
    for scenario in SCENARIOS:
        passed = 0
        failure_counter: dict[str, int] = {}
        print(f"── {scenario}（{attempts} 次）", flush=True)
        for index in range(1, attempts + 1):
            started = time.monotonic()
            result = run_one(scenario)
            if result["passed"]:
                passed += 1
            for failure in result["failures"]:
                failure_counter[failure] = failure_counter.get(failure, 0) + 1
            flag = "ok  " if result["passed"] else "FAIL"
            print(f"  run {index:2}: {flag} {round(time.monotonic() - started, 1)}s "
                  f"failures={result['failures']}", flush=True)
        low, high = wilson(passed, attempts)
        summary[scenario] = {
            "passed": passed,
            "attempts": attempts,
            "rate": round(passed / attempts, 4),
            "wilson95": [round(low, 4), round(high, 4)],
            "failures": failure_counter,
            "meets_criterion": passed >= attempts - 1,
        }
        print(f"  → {passed}/{attempts} = {passed / attempts:.1%}，"
              f"Wilson 95% CI [{low:.1%}, {high:.1%}]；判据（≥{attempts - 1}/{attempts}）："
              f"{'满足' if passed >= attempts - 1 else '不满足'}", flush=True)

    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
