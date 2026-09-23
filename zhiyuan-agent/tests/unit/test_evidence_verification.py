"""P1c-2 分流表：六行逐行钉住。

分流表来自设计文档第六章，**没有一行是这里自己发明的**；本文件的用途是让
"改坏了"和"改对了"长得不一样——尤其那两行 fail-closed（`unknown` 与 Java 不可达），
它们的失效方式都是"静默放宽"，不写下来就没人会发现。
"""
from __future__ import annotations

from app.gateway.evidence_verification import classify, recheck_instruction


def _records(**statuses: str) -> dict:
    return {
        evidence_id: {
            "status": status,
            "sourceSystem": "gaotu.schoolMajorScoreLine",
            "paramsDigest": f"digest-{evidence_id}",
        }
        for evidence_id, status in statuses.items()
    }


def test_all_valid_proceeds() -> None:
    decision = classify(["ev-1", "ev-2"], _records(**{"ev-1": "valid", "ev-2": "valid"}))

    assert decision.action == "proceed"


def test_no_references_proceeds() -> None:
    assert classify([], {}).action == "proceed"


def test_unknown_blocks_the_turn_and_does_not_retry() -> None:
    """台账里没有 = 没发生过。硬失败、整轮作废、**不重试**。"""
    decision = classify(["ev-1", "ev-ghost"], _records(**{"ev-1": "valid"}))

    assert decision.action == "fail"
    assert decision.code == "evidence_not_authoritative"
    assert decision.detail == "ev-ghost"
    assert decision.recheck_ids == (), "不重试：unknown 不许带重查指令"


def test_a_stale_reference_triggers_a_recheck() -> None:
    decision = classify(["ev-1", "ev-old"], _records(**{"ev-1": "valid", "ev-old": "stale"}))

    assert decision.action == "recheck"
    assert decision.recheck_ids == ("ev-old",)
    assert "ev-old" in decision.recheck_hint
    assert "gaotu.schoolMajorScoreLine" in decision.recheck_hint
    assert "digest-ev-old" in decision.recheck_hint


def test_expired_counts_as_dead_like_stale() -> None:
    decision = classify(["ev-old"], _records(**{"ev-old": "expired"}))

    assert decision.action == "recheck"


def test_stale_is_rechecked_regardless_of_output_type() -> None:
    """失效一律重查——**不再看输出类型**（2026-09-22 作废了"非 fact 只剥离"那一行）。

    作废的依据是实测：`clarification` 引用证据的回合里，正文照样在报具体数字
    （"浙江的批次码：第一段=17……控制线 494 分"）。剥离引用之后，用户看得见的正文里
    仍带着可能失效的数字，而机器检查会通过——那是个用户可见的形状，不是纸面问题。
    """
    decision = classify(["ev-1", "ev-old"], _records(**{"ev-1": "valid", "ev-old": "stale"}))

    assert decision.action == "recheck"
    assert decision.recheck_ids == ("ev-old",)


def test_a_missing_record_is_treated_as_unknown_not_as_fine() -> None:
    """查不到的那条**按 unknown 处置**——缺了就当没问题，等于给伪造留门。"""
    decision = classify(["ev-not-returned"], _records(**{"ev-other": "valid"}))

    assert decision.action == "fail"
    assert decision.detail == "ev-not-returned"


def test_recheck_instruction_names_the_source_and_digest() -> None:
    """回注给模型的指令必须带来源与参数摘要，否则它不知道"用同样的参数再查一遍"是哪个参数。"""
    text = recheck_instruction(["ev-old"], _records(**{"ev-old": "stale"}))

    assert "ev-old" in text
    assert "gaotu.schoolMajorScoreLine" in text
    assert "digest-ev-old" in text
    assert "重新取数" in text
