"""P1c-2：证据核验的分流表（设计文档第六章，逐态写死）。

证据的权威性不是一个可以缓存的判断：同一条证据上一轮还作数、这一轮可能已经失效
（上游数据变了、过了新鲜度上限、版本台账重建过）。所以模型每次引用，都要去问一次
Java 台账"这还作数吗"——**这个模块只负责"问完之后怎么处置"**，问的那一步在
`app/util/internal_client.py::verify_evidence`。

分流表来自设计文档第六章（原六行，2026-09-22 合并为三行 + 一条不可达），
**不在这里自行发挥**（要加行先改设计文档）：

| 核验状态 | 处置 |
|---|---|
| 全部 `valid` | 继续现有校验链 |
| 任一 `unknown` | 硬失败、整轮作废、**不重试** |
| 任一 `stale`/`expired`（**任何输出类型**） | 拒绝本轮输出，回注失效信息，**重查一次** |
| Java 不可达 | 硬失败，不放行（在客户端那一层抛，见 `verify_evidence`） |

设计文档第六章原本还有一行「仅被非 `fact` 输出引用 → 剥离引用、输出继续」，
**2026-09-22 作废**：实测（~200 回合的 rollout）里 `clarification` 引用证据有 6 条，
抽查正文**都在报具体数字**，即"非事实表述不承载招生数据"这个前提不成立——
剥离引用之后，用户看得见的正文里仍带着可能失效的数字，而机器检查会通过。

写成**纯函数**是有意的：每一行都可单测，不需要起栈、不需要 mock 出一个 Java。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

VALID = "valid"
STALE = "stale"
EXPIRED = "expired"
UNKNOWN = "unknown"

Action = Literal["proceed", "recheck", "fail"]


@dataclass(frozen=True)
class Decision:
    """分流结果。`fail` 与另外三种的区别是：整轮作废，没有兜底输出。"""

    action: Action
    code: str = ""
    detail: str = ""
    recheck_ids: tuple[str, ...] = ()
    recheck_hint: str = ""

    @property
    def blocks_the_turn(self) -> bool:
        return self.action == "fail"


def classify(evidence_ids: Sequence[str], records: Mapping[str, Mapping[str, Any]]) -> Decision:
    """按分流表给出处置（`response_type` 不再是入参——见模块 docstring 里那次作废）。

    `records` 是 `{evidenceId: {status, sourceSystem, paramsDigest, …}}`。
    **查不到的那条按 `unknown` 处置**——"台账里没有就是没发生过"，这一条比
    "缺了就当没问题"重要得多：后者等于给伪造留门。
    """
    ids = [str(item) for item in evidence_ids]
    if not ids:
        return Decision("proceed")

    unknown = [item for item in ids if _status(records, item) == UNKNOWN]
    if unknown:
        # 硬失败、整轮作废、**不重试**：台账里没有就是没发生过，
        # 重试只会让模型把同一段编造再说一遍。
        return Decision("fail", code="evidence_not_authoritative", detail=unknown[0])

    dead = [item for item in ids if _status(records, item) in (STALE, EXPIRED)]
    if not dead:
        return Decision("proceed")

    # 失效是正常的数据演进，给一次重查机会；**上限 1 次由调用方保证**（这里不循环）——
    # 写成循环迟早会变成无限重试。
    return Decision(
        "recheck",
        recheck_ids=tuple(dead),
        recheck_hint=recheck_instruction(dead, records),
    )


def recheck_instruction(ids: Iterable[str], records: Mapping[str, Mapping[str, Any]]) -> str:
    """回注给模型的重查指令：失效 ID + 来源 + 参数摘要（第六章原话）。"""
    lines: list[str] = []
    for evidence_id in ids:
        record = records.get(evidence_id) or {}
        lines.append(
            "- {id}（来源 {source}，参数摘要 {digest}，状态 {status}）".format(
                id=evidence_id,
                source=str(record.get("sourceSystem") or "未知"),
                digest=str(record.get("paramsDigest") or "未知"),
                status=str(record.get("status") or ""),
            )
        )
    return (
        "你刚才引用的以下证据已失效，不能作为结论依据：\n"
        + "\n".join(lines)
        + "\n请用**同样的查询参数**重新取数，然后基于新结果重新作答；"
        "不要沿用旧值，也不要凭印象补。"
    )


def _status(records: Mapping[str, Mapping[str, Any]], evidence_id: str) -> str:
    record = records.get(evidence_id)
    if not isinstance(record, Mapping):
        return UNKNOWN
    status = str(record.get("status") or "").strip().lower()
    return status or UNKNOWN


__all__ = [
    "Decision",
    "EXPIRED",
    "STALE",
    "UNKNOWN",
    "VALID",
    "classify",
    "recheck_instruction",
]
