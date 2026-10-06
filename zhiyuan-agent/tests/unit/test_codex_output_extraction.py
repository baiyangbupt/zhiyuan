"""T008: harness output extraction must survive prose-wrapped JSON, and the
smoke script's `evaluation` key must never silently disappear.

See docs/superpowers/tasks/T008-output-extraction/TASK.md for the background:
DeepSeek does not guarantee that `output_schema` produces bare JSON. Sometimes
the model writes prose (and even a markdown table) before the fenced JSON
block. `_parse_json_object` previously only stripped a fence when the whole
string started with it, so prose-then-fence input parsed to `None`.
"""

from __future__ import annotations

import json
import logging

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
    """放宽控制字符/救回**不等于**什么都收：真解析不出来的照旧判 miss。

    不然"能解析"就会变成"总能解析"，而 schema 校验前面那道门也就白设了。
    （2026-10-06 起尾逗号属于救回层——见下面 `test_salvage_recovers_trailing_comma`；
    这里换成单引号 JSON：救回链里没有任何一步会碰它。）
    """
    payload = "{'responseType':'fact','message':'x'}"

    extracted, info = _extract_output_ex({"item": {"type": "agentMessage", "text": payload}})

    assert extracted is None
    assert info["source"] == "missing"


# ---------------------------------------------------------------------------
# 第四层：窄口径救回（2026-10-06 真事故）
#
# 病：模型在 JSON 字符串值里写未转义的英文双引号（`有的省是"第一段/第二段"…`），
# `json.loads` 报 `Expecting ',' delimiter` → 三层抽取全落空 → `output_missing`
# → 修复回合也救不回来 → 用户看到"当前对话引擎暂时不可用"。
#
# 救回只有三种可证明的处理：去围栏 / 去尾随逗号 / 字符串值内成对的引号→「」。
# 其它形态一律不碰——宁可走修复回合，不可改错内容。
# ---------------------------------------------------------------------------

# 真事故原文：session 10041948（2026-10-06 19:22）的 `task_complete.last_agent_message`
# （1250 字符），出处
# `.local/codex-local/runtime-home/sessions/2026/10/06/rollout-2026-10-06T19-21-39-01a110f2-a4b3-70d1-a551-51c6cb80f063.jsonl`。
# `message` 字符串值里有四处未转义 `"`，`json.loads` 在 line 3 column 261 报
# `Expecting ',' delimiter`。
REAL_BAD_AGENT_MESSAGE = r'''{
  "responseType": "clarification",
  "message": "成绩我记下了，先跟你对一遍，确认没抄错：\n\n- 语文 112、数学 125、外语 118\n- 物理 85、化学 86、生物 84\n- 总分 610，位次 22000\n\n这条成绩要落库，还差两样东西，我不能替你猜：\n\n1. **省份**：各科的科目编码和批次编码都是按省份定的。你报的是「物理 + 化学 + 生物」组合，但需要你亲口说省份（如浙江、江苏、湖北……），否则我给出的科目编码可能是别省的，确认卡会在落库前被判作废。\n2. **批次**：你走的是哪个批次？有的省是"第一段/第二段"，有的是"本科批/专科批"——请说你所在批次的名字，我按省份查编码表核对。\n\n补上省份和批次，我立刻生成成绩确认卡给你核对，确认后才真正写入。提醒一句：目前会话里省份、批次等硬事实仍缺失，在写入之前我不会给出录取分数、概率或冲稳保结论。",
  "artifactRefs": [],
  "evidenceRefs": [],
  "admissionFacts": [],
  "uncertainties": [
    "用户所报科目与总分（语数外 + 物化生，总分 610、位次 22000）尚未与任何省份的科目编码、计分口径核对，是否与该省高考总分口径一致仍待确认。"
  ],
  "limitations": [
    "本轮未生成成绩确认卡：后端要求各科与批次携带标准编码，而科目编码与批次编码都依赖用户所在省份，该省份当前未知（会话 missingFacts 含 province）。",
    "本轮未做招生事实查询，因此没有任何录取分数、位次对照或报考资格结论可供引用。",
    "用户报出的成绩属于用户自述（sourceType=user），在确认链写入生效前不作为已确认事实使用。"
  ],
  "clarification": "请补充：① 你所在的省份；② 你填报的批次（如第一段/第二段，或本科批/专科批）。有了这两项我就生成成绩确认卡。",
  "nextStep": "用户回答省份与批次后，先按省份查询科目编码表与批次编码表，再输出成绩确认卡（scoreUpdateRequest）待用户确认。",
  "executionStatus": "blocked",
  "proposalRef": null,
  "proposalRequest": null,
  "conversationAction": {
    "actionType": "request_clarification",
    "proposalRef": null,
    "expectedSourceVersion": 0,
    "intent": "inferred"
  },
  "scoreUpdateRequest": null
}'''


def test_real_failing_message_is_broken_without_salvage() -> None:
    """先钉住病本身：这份真文本严格解析必须失败。

    没有这一条，后面的"救回成功"可能只是因为它本来就是合法 JSON，什么都没证明。
    """
    with pytest.raises(json.JSONDecodeError) as excinfo:
        json.loads(REAL_BAD_AGENT_MESSAGE)

    assert excinfo.value.msg == "Expecting ',' delimiter"
    assert excinfo.value.lineno == 3 and excinfo.value.colno == 261


def test_salvage_recovers_the_real_message_and_the_content_is_equivalent(caplog) -> None:
    """真文本 → 救回成功，且解析结果与"模型想写的那份"**逐字段相等**。

    等价判据不是"能解析"：把坏文本里那两处内层引号手工换成 「」 后就是模型的本意
    （`{省份、批次}` 那两段中文引用），救回结果必须与它完全一致——不许少字段、
    不许改别的字符、不许把引号吃掉就算数。
    """
    intended = json.loads(
        REAL_BAD_AGENT_MESSAGE.replace('"第一段/第二段"', "「第一段/第二段」").replace(
            '"本科批/专科批"', "「本科批/专科批」"
        )
    )

    with caplog.at_level(logging.WARNING, logger="app.harness.codex"):
        extracted, info = _extract_output_ex(
            {"item": {"type": "agentMessage", "text": REAL_BAD_AGENT_MESSAGE}}
        )

    assert extracted == intended
    assert extracted["responseType"] == "clarification"
    assert extracted["clarification"] == intended["clarification"]
    assert info["source"] == "salvaged"
    assert info["salvageLayer"] == "direct"
    assert info["salvageActions"] == ["in_string_quotes"]
    # 救回必须留痕：WARNING + 截断摘录（不是静默改写）
    assert "salvaged malformed model JSON" in caplog.text
    assert "excerpt=" in caplog.text
    assert "responseType" in caplog.text  # 摘录从文本开头截起，能定位是哪份输出


def test_salvage_log_excerpt_is_truncated_to_200_chars(caplog) -> None:
    payload = '{"message": "' + "长" * 400 + '他说"好"，走了"}'

    with caplog.at_level(logging.WARNING, logger="app.harness.codex"):
        extracted, info = _parse_json_object(payload)

    assert extracted == {"message": "长" * 400 + "他说「好」，走了"}
    assert info["source"] == "salvaged"
    records = [record for record in caplog.records if "salvaged malformed" in record.getMessage()]
    assert len(records) == 1
    excerpt = records[0].args[-1]
    assert excerpt.endswith("…")
    assert len(excerpt) == 201  # 200 字符 + 截断标记


def test_salvage_strips_a_fence_around_repairable_json() -> None:
    """① 去 markdown 围栏：围栏里的引号坏了时，围栏也不能挡住救回。"""
    payload = '```json\n{"message": "他说"你好"，就走了"}\n```'

    extracted, info = _parse_json_object(payload)

    assert extracted == {"message": "他说「你好」，就走了"}
    assert info["salvageActions"] == ["fence", "in_string_quotes"]


def test_salvage_strips_an_unterminated_fence_too() -> None:
    """围栏忘了收口（没有结尾 ```）时严格层连候选都找不到——救回层照样先去围栏。"""
    payload = '```json\n{"message": "他说"你好"，就走了"}'

    extracted, info = _parse_json_object(payload)

    assert extracted == {"message": "他说「你好」，就走了"}
    assert info["salvageActions"] == ["fence", "in_string_quotes"]
    assert info["salvageLayer"] == "direct"


def test_salvage_recovers_trailing_comma() -> None:
    """② 去尾随逗号：尾逗号在严格 JSON 里本来就不合法，去掉它不改任何合法写法。

    这条**覆盖**了 2026-09-21 那条"尾逗号照旧判 miss"的旧预期：旧预期防的是
    "什么都收"，而尾逗号是可以证明无损的一种；防误收由剩下的拒收用例守着。
    """
    extracted, info = _parse_json_object('{"responseType": "fact", "message": "x",}')

    assert extracted == {"responseType": "fact", "message": "x"}
    assert info["source"] == "salvaged"
    assert info["salvageActions"] == ["trailing_comma"]


def test_salvage_does_not_touch_commas_inside_strings() -> None:
    """去尾逗号只认字符串**外**的逗号：`"x,}"` 是内容，一个字符不许动。"""
    extracted, info = _parse_json_object('{"message": "x,}", "n": 1}')

    assert extracted == {"message": "x,}", "n": 1}
    assert info["source"] == "direct"  # 本来就是合法 JSON，连救回层都不进


def test_salvage_refuses_a_missing_comma_between_members() -> None:
    """真不可救之一：`{"a": "x" "b": "y"}` 的失败点也是 `Expecting ',' delimiter`，
    但它是**结构**错误（本该有个逗号），不是"字符串值内的引号"。

    这里必须拒绝——若按内层引号替换，`"fact" "message": "x"` 会被拼成一段
    `fact「」message「」x` 的正文，等于把结构错误吞成内容错误。
    """
    payload = '{"responseType": "fact" "message": "x"}'

    extracted, info = _parse_json_object(payload)

    assert extracted is None
    assert info == {"source": "missing", "candidateCount": None}


def test_salvage_refuses_a_single_stray_quote() -> None:
    """真不可救之二：只多出一个引号（不成对）——没有可证明的配对，宁可失败。"""
    payload = '{"message": "冠军是勇士"队"}'

    extracted, info = _parse_json_object(payload)

    assert extracted is None
    assert info == {"source": "missing", "candidateCount": None}


def test_salvage_refuses_quotes_that_wrap_structural_fragments() -> None:
    """真不可救之三：引号对里包的是纯 ASCII 结构片段（`"message"`、`"x"`），
    不是中文正文——不能当成"值内引号"。"""
    payload = '{"a": "已核实" "b": "x"}'

    extracted, info = _parse_json_object(payload)

    assert extracted is None
    assert info == {"source": "missing", "candidateCount": None}


def test_embedded_json_with_bad_quotes_is_salvaged_through_the_agent_message_shape() -> None:
    """围栏/散文包裹的真形状（agentMessage 的 text）同样只走救回层，不改前三层。"""
    payload = '系统返回如下：{"message": "他说"你好"，就走了"} 以上为全部内容。'

    extracted, info = _extract_output_ex({"item": {"type": "agentMessage", "text": payload}})

    assert extracted == {"message": "他说「你好」，就走了"}
    assert info["source"] == "salvaged"
    assert info["salvageLayer"] == "embedded"
    assert info["salvageActions"] == ["in_string_quotes"]
