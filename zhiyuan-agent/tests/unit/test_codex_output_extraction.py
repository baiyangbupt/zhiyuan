"""T008: harness output extraction must survive prose-wrapped JSON, and the
smoke script's `evaluation` key must never silently disappear.

See docs/superpowers/tasks/T008-output-extraction/TASK.md for the background:
DeepSeek does not guarantee that `output_schema` produces bare JSON. Sometimes
the model writes prose (and even a markdown table) before the fenced JSON
block. `_parse_json_object` previously only stripped a fence when the whole
string started with it, so prose-then-fence input parsed to `None`.
"""

from __future__ import annotations

import pytest

from app.harness.codex import _extract_output, _extract_output_ex, _parse_json_object
from app.harness.turn_result import CodexTurnResult

import scripts.codex_semantic_smoke as smoke_script


# ---------------------------------------------------------------------------
# _parse_json_object: layered extraction (acceptance items 1-5)
# ---------------------------------------------------------------------------


def test_pure_json_is_direct_source_happy_path_unchanged() -> None:
    """Acceptance #5: whole string is JSON -> source stays 'direct'.

    Guards against accidentally routing every input through fence scanning
    first, which would silently change the dominant (7/8 observed) path.
    """
    parsed, extraction = _parse_json_object('{"responseType": "fact", "message": "ok"}')

    assert parsed == {"responseType": "fact", "message": "ok"}
    assert extraction == {"source": "direct", "candidateCount": None}


def test_prose_prefixed_fenced_json_is_extracted() -> None:
    """Acceptance #1: prose (incl. a markdown table) then a trailing fenced
    JSON block must be extracted, source == 'fenced'. This is the exact shape
    reported in T005's 1/8 failure.
    """
    value = (
        "以下是分析说明：\n\n"
        "| 学校 | 分数 |\n|---|---|\n| 甲大学 | 650 |\n\n"
        "最终结果如下：\n"
        "```json\n"
        '{"responseType": "fact", "message": "已核实"}\n'
        "```"
    )

    parsed, extraction = _parse_json_object(value)

    assert parsed == {"responseType": "fact", "message": "已核实"}
    assert extraction == {"source": "fenced", "candidateCount": 1}


def test_whole_value_as_fence_still_works() -> None:
    """Trap #1: the historical 'entire value starts with a fence' input must
    still work -- fence scanning is a superset, not a replacement.
    """
    parsed, extraction = _parse_json_object('```json\n{"message": "ok"}\n```')

    assert parsed == {"message": "ok"}
    assert extraction == {"source": "fenced", "candidateCount": 1}


def test_two_fenced_blocks_hits_last_and_reports_candidate_count() -> None:
    """Acceptance #4: ambiguity (two fenced JSON blocks) must be visible via
    candidateCount, and resolved by taking the last block.
    """
    value = "草稿：\n```json\n{\"a\": 1}\n```\n定稿：\n```json\n{\"b\": 2}\n```"

    parsed, extraction = _parse_json_object(value)

    assert parsed == {"b": 2}
    assert extraction == {"source": "fenced", "candidateCount": 2}


def test_prose_without_any_json_is_missing() -> None:
    """Acceptance #2: no JSON anywhere -> None, source == 'missing'. Guards
    against over-fixing into fabricating output from nothing.
    """
    value = "本次为您推荐以下两所学校，具体信息请见附表，暂无更多补充。"

    parsed, extraction = _parse_json_object(value)

    assert parsed is None
    assert extraction == {"source": "missing", "candidateCount": None}


def test_non_json_chinese_braces_do_not_degrade_to_regex_scraping() -> None:
    """Acceptance #3: prose containing `{...}`-shaped Chinese text that is not
    valid JSON must still return None -- the embedded fallback must not
    degrade into scraping arbitrary brace-delimited text.
    """
    value = "请提供以下信息：{省份、科类、批次}，谢谢配合。"

    parsed, extraction = _parse_json_object(value)

    assert parsed is None
    assert extraction["source"] == "missing"


def test_embedded_balanced_json_without_fences_is_extracted() -> None:
    """Layer 3 positive case: a balanced {...} JSON object embedded in prose
    with no fences at all.
    """
    value = '系统返回如下：{"responseType": "fact", "message": "ok"} 以上为全部内容。'

    parsed, extraction = _parse_json_object(value)

    assert parsed == {"responseType": "fact", "message": "ok"}
    assert extraction == {"source": "embedded", "candidateCount": None}


# ---------------------------------------------------------------------------
# _extract_output_ex / _extract_output: end-to-end through the recursive
# agentMessage-shaped payload (trap #2: the record must be the actual hit,
# not whatever the last recursive attempt happened to try).
# ---------------------------------------------------------------------------


def test_extract_output_end_to_end_prose_then_fence() -> None:
    event = {
        "item": {
            "type": "agentMessage",
            "text": (
                "结论如下，供参考。\n"
                "```json\n"
                '{"responseType": "fact", "message": "已确认"}\n'
                "```"
            ),
        }
    }

    output, extraction = _extract_output_ex(event)

    assert output == {"responseType": "fact", "message": "已确认"}
    assert extraction == {"source": "fenced", "candidateCount": 1}
    # Backward-compatible wrapper used by existing tests/callers.
    assert _extract_output(event) == output


def test_extract_output_end_to_end_missing_json() -> None:
    event = {"item": {"type": "agentMessage", "text": "抱歉，我没有足够的信息回答这个问题。"}}

    output, extraction = _extract_output_ex(event)

    assert output is None
    assert extraction == {"source": "missing", "candidateCount": None}
    assert _extract_output(event) is None


# ---------------------------------------------------------------------------
# codex_semantic_smoke.run_scenario: acceptance #6 -- `evaluation` must exist
# and be `passed=False` when output can't be extracted, with a control case
# proving the same code path gives `passed=True` for a normal output (i.e.
# the check isn't vacuously always false).
# ---------------------------------------------------------------------------


class _StubHarness:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_server_request_handler(self, _handler: object) -> None:
        pass

    async def start(self) -> None:
        return None

    async def create_thread(self, **_kwargs: object) -> dict[str, object]:
        return {"thread": {"id": "thread-stub"}}

    async def close(self) -> None:
        return None


def _stub_harness_returning(result: CodexTurnResult) -> type:
    class _Harness(_StubHarness):
        async def start_turn_and_collect(self, *_args: object, **_kwargs: object) -> CodexTurnResult:
            return result

    return _Harness


@pytest.mark.asyncio
async def test_smoke_payload_evaluation_present_and_failed_when_output_missing() -> None:
    result = CodexTurnResult(
        status="completed",
        turn_id="turn-x",
        output=None,
        output_extraction={"source": "missing", "candidateCount": None},
    )
    original = smoke_script.CodexAppServerHarness
    smoke_script.CodexAppServerHarness = _stub_harness_returning(result)
    try:
        payload = await smoke_script.run_scenario(smoke_script.reference_missing_scope_scenario)
    finally:
        smoke_script.CodexAppServerHarness = original

    assert "evaluation" in payload
    assert payload["evaluation"]["passed"] is False
    assert "output_missing" in payload["evaluation"]["failures"]
    assert "trace" not in payload
    assert payload["outputExtraction"] == {"source": "missing", "candidateCount": None}


@pytest.mark.asyncio
async def test_smoke_payload_evaluation_present_when_status_not_completed() -> None:
    """Covers the second silent-gap path: status != 'completed'."""
    result = CodexTurnResult(status="timed_out", turn_id="turn-x", error_code="turn_timeout")
    original = smoke_script.CodexAppServerHarness
    smoke_script.CodexAppServerHarness = _stub_harness_returning(result)
    try:
        payload = await smoke_script.run_scenario(smoke_script.reference_missing_scope_scenario)
    finally:
        smoke_script.CodexAppServerHarness = original

    assert "evaluation" in payload
    assert payload["evaluation"]["passed"] is False
    assert "trace" not in payload


@pytest.mark.asyncio
async def test_smoke_payload_evaluation_passed_true_when_output_present_control() -> None:
    """Control for the two tests above: the same branch-selection code must
    still produce `passed=True` for a normal, schema-valid output. Without
    this, a bug that made the check unconditionally `passed=False` would go
    unnoticed.
    """
    valid_output = {
        "responseType": "clarification",
        "message": "需要先明确省份：甲大学(school-1)、乙大学(school-2)",
    }
    result = CodexTurnResult(
        status="completed",
        turn_id="turn-x",
        output=valid_output,
        output_extraction={"source": "direct", "candidateCount": None},
    )
    original = smoke_script.CodexAppServerHarness
    smoke_script.CodexAppServerHarness = _stub_harness_returning(result)
    try:
        payload = await smoke_script.run_scenario(smoke_script.reference_missing_scope_scenario)
    finally:
        smoke_script.CodexAppServerHarness = original

    assert payload["evaluation"]["passed"] is True


def test_extraction_tolerates_raw_control_characters_in_strings() -> None:
    """模型在 JSON 字符串里写**真换行**时，不能整轮判成"没有输出"。

    `json.loads` 默认严格：字符串内的裸控制字符（真换行/制表符）会让整段解析失败。
    实测 2026-09-21 一轮查北大招生章程的回答（2435 字、按"第一章/第几条"分段）在
    `line 1 column 76` 报 `Invalid control character`，三层抽取全失败 →
    `output_missing` → **整轮失败**，而内容本身完全合规。

    放宽的只有这一条（`strict=False`）。契约校验仍在 pydantic 那一层——
    这不是"放松校验"，是"先把话听清再判"。
    """
    payload = (
        '{"responseType":"fact","message":"第一章 总则\n第一条 为保证招生工作顺利进行…",'
        '"nextStep":"无"}'
    )
    assert "\n" in payload  # 这就是裸换行，不是转义

    extracted, info = _extract_output_ex({"item": {"type": "agentMessage", "text": payload}})

    assert info["source"] == "direct"
    assert extracted is not None
    assert extracted["responseType"] == "fact"
    assert "第一章" in extracted["message"]


def test_extraction_still_rejects_genuinely_broken_json() -> None:
    """放宽控制字符**不等于**什么都收：尾逗号这类真错误照旧判 miss。

    不然"能解析"就会变成"总能解析"，而 schema 校验前面那道门也就白设了。
    """
    payload = '{"responseType":"fact","message":"x",}'

    extracted, info = _extract_output_ex({"item": {"type": "agentMessage", "text": payload}})

    assert extracted is None
    assert info["source"] == "missing"
