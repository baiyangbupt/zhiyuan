"""修复回合必须带着**上一回合的坏文本**（2026-10-06 真事故，session 10041948）。

病：模型在最终 JSON 的字符串值里写了未转义的英文双引号 →
`json.loads` 报 `Expecting ',' delimiter` → harness 抽不出结构化输出 →
`_extract_output` 抛 `output_missing` → `_repair_turn_output` 只拿到一句 issue
字符串，**看不到自己写坏的那段文本** → 重复同类错误 → 升级 `output_schema_invalid`
→ 用户看到"当前对话引擎暂时不可用"。

这里用**可注入的 fake harness** 钉住三件事（不用真模型）：
① 修复提示里带着上一回合原始文本（截断 1500 字符）+「」硬性要求；
② 第一次坏、修复回合返回合法输出 → 整轮成功（`outputRepaired=True`）；
③ 修复回合再失败 → 仍按既有语义报 `output_schema_invalid`（不吞、只修一次）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.gateway.service import (
    _RECOVERABLE_TURN_FAILURE,
    GatewayService,
    _last_agent_text,
    _repair_output_excerpt,
)
from app.harness.binding import ThreadBinding

# 真事故 `message` 里的那句（ASCII 双引号未转义，四处、两对）
BAD_MESSAGE_TEXT = (
    '{"responseType": "clarification", "message": '
    '"你走的是哪个批次？有的省是"第一段/第二段"，有的是"本科批/专科批"——'
    '请说你所在批次的名字，我按省份查编码表核对。"}'
)

VALID_OUTPUT: dict[str, Any] = {
    "responseType": "text",
    "message": "已收到，请补充省份与批次，我再生成成绩确认卡。",
}


@dataclass
class Collected:
    status: str
    output: dict | None
    events: list
    turn_id: str = "turn-1"
    payload: dict = field(default_factory=dict)


class RepairHarness:
    """按调用次序返回预置的收集结果；顺手把每次的 input_items 记下来。"""

    def __init__(self, scripted: list[Collected]) -> None:
        self.scripted = scripted
        self.turns: list[list] = []

    async def create_thread(self, **kwargs):
        return {"thread": {"id": "thr-repair"}}

    async def resume_thread(self, thread_id: str):
        return {"thread": {"id": thread_id}}

    async def inject_items(self, thread_id: str, items: list[dict]):
        return {}

    async def start_turn(self, thread_id: str, input_items: list[dict], output_schema=None):
        self.turns.append(input_items)
        return {"turn": {"id": f"turn-{len(self.turns)}"}}

    async def start_turn_and_collect(self, thread_id, input_items, output_schema=None, **kwargs):
        self.turns.append(input_items)
        index = min(len(self.turns) - 1, len(self.scripted) - 1)
        return self.scripted[index]


def _bad_agent_event() -> dict:
    """harness 收集到的那条坏输出事件（形状照 `item/completed` 的 agentMessage）。"""
    return {
        "type": "assistant.completed",
        "item": {"type": "agentMessage", "text": BAD_MESSAGE_TEXT},
    }


def _snapshot() -> dict:
    return {
        "sessionId": "session-1",
        "version": 42,
        "phase": "candidate_exploration",
        "allowedCapabilities": ["catalog_read"],
    }


def _binding() -> ThreadBinding:
    return ThreadBinding(
        thread_id="thr-repair",
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        allowed_capabilities=frozenset({"catalog_read"}),
    )


def _gateway(codex: RepairHarness) -> GatewayService:
    return GatewayService(
        mode="codex_readonly",
        codex=codex,
        legacy=None,
        message_store=None,
        binding_loader=lambda **kwargs: _binding(),
        snapshot_loader=lambda **kwargs: _snapshot(),
    )


def _turn(gateway: GatewayService) -> dict:
    return gateway.handle_turn(
        tenant_id="tenant-1",
        session_id="session-1",
        user_id="user-1",
        turn_id="ui-1",
        content="帮我更新一下成绩，总分610、位次22000",
    )


def _prompt_text(items: list) -> str:
    return "\n".join(
        str(item.get("text", "")) for item in items if isinstance(item, dict)
    )


# ---------------------------------------------------------------------------
# ① 修复提示带坏文本 + 引号硬规则
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repair_prompt_carries_previous_raw_text_and_the_quote_rule() -> None:
    codex = RepairHarness(
        [
            Collected(status="completed", output=None, events=[_bad_agent_event()]),
            Collected(status="completed", output=dict(VALID_OUTPUT), events=[]),
        ]
    )

    result = await _turn(_gateway(codex))

    assert "error" not in result
    assert result["output"]["message"] == VALID_OUTPUT["message"]
    assert result["recovery"] == {"outputRepaired": True}
    assert len(codex.turns) == 2

    turn_input = codex.turns[1]
    prompt = _prompt_text(turn_input)
    assert BAD_MESSAGE_TEXT in prompt  # 坏文本整段摆回去了（短于 1500）
    assert "「」" in prompt and "『』" in prompt
    assert "字符串值内不得出现英文双引号" in prompt
    assert "只输出一段合法 JSON" in prompt
    assert "校验问题：" in prompt

    # 第一回合（正常输入）里没有这段摘录——它不是用户说的话。
    assert BAD_MESSAGE_TEXT not in _prompt_text(codex.turns[0])


@pytest.mark.asyncio
async def test_repair_prompt_truncates_a_long_previous_text_at_1500_chars() -> None:
    long_text = '{"responseType": "text", "message": "' + "长" * 3000 + '"}'
    codex = RepairHarness(
        [
            Collected(
                status="completed",
                output=None,
                events=[{"item": {"type": "agentMessage", "text": long_text}}],
            ),
            Collected(status="completed", output=dict(VALID_OUTPUT), events=[]),
        ]
    )

    result = await _turn(_gateway(codex))

    assert "error" not in result
    prompt = _prompt_text(codex.turns[1])
    marker = "上一回合失败输出的原始文本（最多截取前 1500 字符，用于定位；截断处不完整属正常）：\n"
    assert marker in prompt
    excerpt = prompt.split(marker, 1)[1]
    assert excerpt == long_text[:1500]
    assert long_text[1500:] not in prompt, "超过 1500 字符的部分不许进提示词"


@pytest.mark.asyncio
async def test_repair_without_a_raw_text_keeps_the_old_prompt_shape() -> None:
    """拿不到原文（旧 harness / 非 collect 路径）＝不带摘录，其余规则照旧。"""
    codex = RepairHarness([Collected(status="completed", output=dict(VALID_OUTPUT), events=[])])
    gateway = _gateway(codex)

    repaired = await gateway._repair_turn_output("thr-repair", "output_missing: no output")

    assert repaired == {"output": VALID_OUTPUT, "events": []}
    prompt = _prompt_text(codex.turns[0])
    assert "output_missing: no output" in prompt
    assert "上一回合失败输出的原始文本" not in prompt


# ---------------------------------------------------------------------------
# ② 第一次坏、修复回合合法 → 整轮成功；③ 再失败 → output_schema_invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_bad_round_still_fails_with_output_schema_invalid() -> None:
    """不吞：修复回合再拿不到合法输出，仍按既有语义 `output_schema_invalid`
    作废整轮，用户看到那条通用文案；修复只跑一次，不循环。"""
    codex = RepairHarness(
        [
            Collected(status="completed", output=None, events=[_bad_agent_event()]),
            Collected(status="completed", output=None, events=[_bad_agent_event()]),
        ]
    )

    result = await _turn(_gateway(codex))

    assert result["error"].startswith("output_schema_invalid")
    assert result["reply"] == _RECOVERABLE_TURN_FAILURE
    assert len(codex.turns) == 2, "修复回合只许一次"


@pytest.mark.asyncio
async def test_repair_round_is_not_tried_when_the_first_round_is_valid() -> None:
    """对照：首轮就合法时不许凭空多跑一个回合（修复回路的接线不能改变正常路径）。"""
    codex = RepairHarness([Collected(status="completed", output=dict(VALID_OUTPUT), events=[])])

    result = await _turn(_gateway(codex))

    assert "error" not in result
    assert result["recovery"] == {"outputRepaired": False}
    assert len(codex.turns) == 1


# ---------------------------------------------------------------------------
# 取原文 / 截断这两个纯函数
# ---------------------------------------------------------------------------


def test_last_agent_text_reads_every_active_shape_and_prefers_the_last() -> None:
    assert _last_agent_text({"item": {"type": "agentMessage", "text": "A"}}) == "A"
    assert (
        _last_agent_text(
            {
                "events": [
                    {"item": {"type": "agentMessage", "text": "A"}},
                    {"item": {"type": "mcpToolCall", "text": "不是正文"}},
                    {"payload": {"message": "B"}},  # 事件适配后的形状
                ]
            }
        )
        == "B"
    )
    # 重查等场景：最后一段才是模型刚写的
    assert (
        _last_agent_text(
            {"events": [{"item": {"type": "agentMessage", "text": "旧"}},
                        {"item": {"type": "agentMessage", "text": "新"}}]}
        )
        == "新"
    )
    assert _last_agent_text({"events": [{"item": {"type": "agentMessage", "text": "  "}}]}) is None
    assert _last_agent_text({"events": [{"item": {"type": "mcpToolCall", "text": "工具"}}]}) is None
    assert _last_agent_text(None) is None
    assert _last_agent_text("不是 Mapping") is None


def test_repair_output_excerpt_truncates_at_1500_and_skips_blanks() -> None:
    assert _repair_output_excerpt(None) is None
    assert _repair_output_excerpt("   \n ") is None
    assert _repair_output_excerpt("短文本") == "短文本"
    assert len(_repair_output_excerpt("长" * 2000)) == 1500
