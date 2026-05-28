"""LLM-backed semantic intent router.

This module is intentionally shadow-only at this stage.  It should not mutate
state, call planning tools, or generate user-facing replies.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from pydantic_ai import Agent

from app.config import LLMConfig
from app.agent.context import RequestContext
from app.config import SemanticRouterConfig
from app.llm.client import LLMClient
from app.models.conversation_phase import PendingConfirmation
from app.models.semantic_router import (
    FixedScenarioRouteFrame,
    FixedScenarioRouteResult,
    SemanticIntentFrame,
    SemanticRouterShadowResult,
)


_INSTRUCTIONS = """\
你是高考志愿规划系统的语义路由器，只输出 JSON 对象，不回答用户，不调用工具。

目标：判断用户这一轮到底是在问信息探索、偏好/约束管理、方案查询/调整，还是普通收口。

必须遵守：
- 只返回一个 JSON 对象，不要 Markdown，不要解释文字，不要代码块。
- 不要因为“是不是 / 看看 / 几个 / 怎么 / 影响 / 可以吗”这类泛化词直接判成方案查询。
- 用户问“是不是坑 / 怎么排优先级 / 怎么选 / 要不要避开 / 会少啥选择 / 有什么要求”时，优先按 explore/policy/requirement/major/career 判断。
- 用户问分数、位次、批次线、压线、模考波动、单科忽高忽低、总分不稳、出分前预估如何影响填报时，通常是 explore + topic=score + sideEffect=readonly；不要因为“别画大饼 / 稳一点 / 保底”就判成 intent 或 plan mutation。
- topic=policy 只用于政策、资格、批次规则、报名要求、体检限制、专项资格等制度性问题；普通“成绩波动怎么填志愿”不是 policy。
- topic=major 用于专业比较、专业方向选择、专业学习/就业适配；如果用户核心是在用单科/总分/位次判断填报风险，优先 topic=score。
- 用户明确要加入、删除、移动、排序、替换、补齐方案时，sideEffect=preview；除非输入明确是在确认上一轮 pending，不能 apply。
- 用户明确表达长期偏好、可接受、排除、不要、别碰并希望系统后续记住/筛掉时，taskLayer=intent，sideEffect=preview；只是在描述风险边界、要求务实分析或“别画大饼”，不是 intent。
- 用户明确问“当前方案/候选里有没有某院校或专业”时，才是 plan query。
- 输出 requiredFacts，说明后续回复至少要覆盖哪些事实，避免薄回复。

参考：
- “一模二模差挺多，这个成绩波动填志愿咋看” => explore/explain/score/readonly
- “分数刚压本科线，别给我画大饼” => explore/analyze/score/readonly
- “孩子数学忽高忽低，理工还能不能碰” => explore/analyze/score/readonly
- “会计审计还行，土木别要” => intent/set_constraint/major/preview
- “按录取率从低到高排下，先看预览” => plan/sort/plan/preview

JSON 字段：
{
  "taskLayer": "explore|intent|plan|general",
  "verb": "query|analyze|compare|recommend|explain|review|generate|add|remove|move|sort|replace|confirm|reject|set_preference|set_constraint|remove_preference|clarify",
  "topic": "plan|major|school|region|career|score|policy|requirement|general",
  "sideEffect": "readonly|preview|apply|none",
  "confidence": 0.0,
  "ambiguity": [],
  "missingInfo": [],
  "entities": {
    "schools": [],
    "majors": [],
    "regions": [],
    "careerDirections": [],
    "positions": [],
    "sortFields": [],
    "reviewIssues": []
  },
  "responseNeed": {
    "depth": "brief|normal|rich",
    "requiredFacts": [],
    "mustNotDo": []
  },
  "reason": ""
}
"""

_PROMPT_PREFIX = "请根据以下上下文输出语义路由 JSON：\n"

_FIXED_ROUTE_INSTRUCTIONS = """\
你是高考志愿规划系统的高置信固定场景路由器，只输出 JSON 对象，不回答用户，不调用工具。

目标：只识别少量可以安全走快捷入口的固定场景。拿不准、信息不足、用户在闲聊或开放咨询时，必须输出 fixedScenario="none"。

可选 fixedScenario：
1. major_compare.readonly
   - 用户明确在 2-3 个具体专业之间比较、取舍、排优先级。
   - 只读分析，不记录偏好，不改方案。
   - 示例：“法学和财政学哪个更适合普通家庭女生，先只分析不要记偏好”、“财管会计审计怎么排优先级”。
2. major_intent.preview
   - 用户明确表达后续要偏好/接受/优先，或明确排除/不要/别碰某些专业。
   - 这是待确认预览，不是直接生效。
   - 示例：“会计审计可以，土木别要”、“医学护理这些别碰，财会还能接受，先看看影响”。
3. career_direction.readonly
   - 用户明确问体制内/考公/稳定就业/读研等职业方向和当前方案或个人选择的承接、支撑、短板。
   - 只读分析，不记录偏好，不改方案。
   - 示例：“当前方案对考公和读研分别有什么支撑和短板”。

必须回 none 的情况：
- 泛泛问某个专业现实不现实、能不能碰、适不适合，但不是两个或三个具体专业比较。
- 体检、色弱、色盲、视力、口试、专项、资格、政策、报考要求、学费、分数波动、压线等咨询。
- 用户要求加入、删除、移动、排序、替换、补齐方案。
- 用户只是闲聊、收口、追问“为啥/怎么说/真的假的”等开放表达。
- 用户明确要求“确认/执行/按这个改”但当前输入本身不是完整 fixed scenario。

输出要求：
- 只返回一个 JSON 对象，不要 Markdown，不要解释文字。
- sideEffect 只能是 readonly 或 preview；不能输出 apply。
- confidence 低于 0.82、存在歧义或缺信息时，fixedScenario 必须是 none。
- 专业名保留用户表达即可，后续会本地目录校验；不要编造专业。
- careerDirections 只能使用：system_public_service、stable_employment、further_study。

JSON 字段：
{
  "fixedScenario": "none|major_compare.readonly|major_intent.preview|career_direction.readonly",
  "sideEffect": "readonly|preview",
  "confidence": 0.0,
  "entities": {
    "majorNames": [],
    "positiveMajorNames": [],
    "negativeMajorNames": [],
    "careerDirections": []
  },
  "ambiguity": [],
  "missingInfo": [],
  "mustFallbackReason": "",
  "reason": ""
}
"""

_FIXED_ROUTE_PROMPT_PREFIX = "请根据以下上下文输出固定场景路由 JSON：\n"


def _extract_json_object(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("semantic router output is not a JSON object")
    return value


def _parse_semantic_frame(text: Any) -> SemanticIntentFrame:
    if isinstance(text, SemanticIntentFrame):
        return text
    return SemanticIntentFrame.model_validate(_extract_json_object(text))


def _parse_fixed_scenario_frame(text: Any) -> FixedScenarioRouteFrame:
    if isinstance(text, FixedScenarioRouteFrame):
        return text
    return FixedScenarioRouteFrame.model_validate(_extract_json_object(text))


class SemanticIntentRouter:
    def __init__(self, llm_client: LLMClient, config: SemanticRouterConfig | None = None):
        self.llm_client = llm_client
        self.config = config or SemanticRouterConfig()
        self.router_llm_client = self._build_router_llm_client()
        self.agent: Agent | None = None
        self.fixed_route_agent: Agent | None = None

    def _build_router_llm_client(self) -> LLMClient:
        if not self.config.llm_model_name:
            return self.llm_client

        main_cfg = self.llm_client.config
        router_cfg = LLMConfig(
            provider=self.config.llm_provider or main_cfg.provider,
            model_name=self.config.llm_model_name,
            api_key=self.config.llm_api_key or main_cfg.api_key,
            base_url=self.config.llm_base_url or main_cfg.base_url,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        return LLMClient(router_cfg)

    def _agent(self) -> Agent:
        if self.agent is None:
            self.agent = Agent(
                model=self.router_llm_client.model,
                output_type=str,
                instructions=_INSTRUCTIONS,
                tools=[],
                model_settings=self._router_model_settings(),
            )
        return self.agent

    def _fixed_route_agent(self) -> Agent:
        if self.fixed_route_agent is None:
            self.fixed_route_agent = Agent(
                model=self.router_llm_client.model,
                output_type=str,
                instructions=_FIXED_ROUTE_INSTRUCTIONS,
                tools=[],
                model_settings=self._router_model_settings(),
            )
        return self.fixed_route_agent

    def _router_model_settings(self) -> dict[str, Any]:
        settings = dict(self.router_llm_client.model_settings or {})
        if self.config.llm_enable_thinking is not None:
            extra_body = settings.get("extra_body")
            if not isinstance(extra_body, dict):
                extra_body = {}
            extra_body = {**extra_body, "enable_thinking": self.config.llm_enable_thinking}
            settings["extra_body"] = extra_body
        return settings

    async def route_shadow(
        self,
        user_prompt: str,
        *,
        request_context: RequestContext,
        active_pending: PendingConfirmation | None = None,
    ) -> SemanticRouterShadowResult:
        if not self.config.enabled:
            return SemanticRouterShadowResult(enabled=False, status="disabled")

        started_at = time.monotonic()
        prompt = self._build_prompt(
            user_prompt,
            request_context=request_context,
            active_pending=active_pending,
        )
        try:
            task = self._agent().run(prompt, model_settings=self._router_model_settings())
            if float(self.config.timeout_seconds) > 0:
                result = await asyncio.wait_for(
                    task,
                    timeout=max(0.1, float(self.config.timeout_seconds)),
                )
            else:
                result = await task
            frame = _parse_semantic_frame(result.output)
            return SemanticRouterShadowResult(
                enabled=True,
                status="success",
                frame=frame,
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
            )
        except asyncio.TimeoutError:
            return SemanticRouterShadowResult(
                enabled=True,
                status="timeout",
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
                errorType="timeout",
                errorMessage=f"semantic router timed out after {self.config.timeout_seconds}s",
            )
        except Exception as exc:
            return SemanticRouterShadowResult(
                enabled=True,
                status="error",
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
                errorType=type(exc).__name__,
                errorMessage=str(exc),
            )

    async def route_fixed_scenario(
        self,
        user_prompt: str,
        *,
        request_context: RequestContext,
        active_pending: PendingConfirmation | None = None,
    ) -> FixedScenarioRouteResult:
        if not self.config.fixed_route_enabled:
            return FixedScenarioRouteResult(enabled=False, status="disabled")

        started_at = time.monotonic()
        prompt = self._build_fixed_route_prompt(
            user_prompt,
            request_context=request_context,
            active_pending=active_pending,
        )
        try:
            task = self._fixed_route_agent().run(prompt, model_settings=self._router_model_settings())
            timeout_seconds = float(self.config.fixed_route_timeout_seconds)
            if timeout_seconds > 0:
                result = await asyncio.wait_for(task, timeout=max(0.1, timeout_seconds))
            else:
                result = await task
            frame = _parse_fixed_scenario_frame(result.output)
            return FixedScenarioRouteResult(
                enabled=True,
                status="success",
                frame=frame,
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
            )
        except asyncio.TimeoutError:
            return FixedScenarioRouteResult(
                enabled=True,
                status="timeout",
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
                errorType="timeout",
                errorMessage=f"fixed scenario router timed out after {self.config.fixed_route_timeout_seconds}s",
            )
        except Exception as exc:
            return FixedScenarioRouteResult(
                enabled=True,
                status="error",
                durationMs=int((time.monotonic() - started_at) * 1000),
                promptChars=len(prompt),
                errorType=type(exc).__name__,
                errorMessage=str(exc),
            )

    def _build_prompt(
        self,
        user_prompt: str,
        *,
        request_context: RequestContext,
        active_pending: PendingConfirmation | None,
    ) -> str:
        payload = self._prompt_payload(
            user_prompt,
            request_context=request_context,
            active_pending=active_pending,
        )
        return _PROMPT_PREFIX + self._json_with_budget(payload)

    def _build_fixed_route_prompt(
        self,
        user_prompt: str,
        *,
        request_context: RequestContext,
        active_pending: PendingConfirmation | None,
    ) -> str:
        payload = self._prompt_payload(
            user_prompt,
            request_context=request_context,
            active_pending=active_pending,
        )
        return _FIXED_ROUTE_PROMPT_PREFIX + self._json_with_budget(payload, prefix_len=len(_FIXED_ROUTE_PROMPT_PREFIX))

    def _prompt_payload(
        self,
        user_prompt: str,
        *,
        request_context: RequestContext,
        active_pending: PendingConfirmation | None,
    ) -> dict[str, Any]:
        return {
            "userPrompt": str(user_prompt or "")[:600],
            "recentChat": self._recent_chat(request_context.chat_history),
            "pending": self._pending_payload(active_pending),
            "planningSummary": self._planning_summary_payload(request_context),
            "scoreDetail": self._score_payload(request_context),
        }

    def _json_with_budget(self, payload: dict[str, Any], *, prefix_len: int = len(_PROMPT_PREFIX)) -> str:
        """Return a complete JSON payload within the configured prompt budget.

        The router model is sensitive to malformed context.  Keep the JSON
        valid while progressively dropping low-value context instead of cutting
        through a serialized object.
        """
        budget = max(600, int(self.config.max_prompt_chars) - prefix_len)

        def dump(value: dict[str, Any]) -> str:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        text = dump(payload)
        if len(text) <= budget:
            return text

        compact = dict(payload)
        compact["recentChat"] = self._compact_recent_chat(compact.get("recentChat"))
        compact["planningSummary"] = self._compact_planning_summary(compact.get("planningSummary"))
        compact["pending"] = self._compact_pending(compact.get("pending"))
        compact["scoreDetail"] = self._compact_score(compact.get("scoreDetail"))

        text = dump(compact)
        if len(text) <= budget:
            return text

        compact["recentChat"] = []
        text = dump(compact)
        if len(text) <= budget:
            return text

        compact["planningSummary"] = self._minimal_planning_summary(compact.get("planningSummary"))
        text = dump(compact)
        if len(text) <= budget:
            return text

        minimal = {
            "userPrompt": str(payload.get("userPrompt") or "")[:300],
            "pending": self._compact_pending(compact.get("pending")),
            "planningSummary": compact.get("planningSummary"),
            "scoreDetail": compact.get("scoreDetail"),
        }
        return dump(minimal)

    def _compact_recent_chat(self, recent_chat: Any) -> list[dict[str, str]]:
        if not isinstance(recent_chat, list):
            return []
        compact: list[dict[str, str]] = []
        for item in recent_chat[-2:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role and content:
                compact.append({"role": role[:20], "content": content[:180]})
        return compact

    def _compact_planning_summary(self, summary: Any) -> dict[str, Any] | None:
        if not isinstance(summary, dict):
            return None
        compact = dict(summary)
        for key in ("riskSummaries", "positiveRegions", "positiveMajors"):
            values = compact.get(key)
            if isinstance(values, list):
                compact[key] = [str(value)[:40] for value in values[:2]]
        return compact

    def _minimal_planning_summary(self, summary: Any) -> dict[str, Any] | None:
        if not isinstance(summary, dict):
            return None
        keys = (
            "phase",
            "version",
            "orderedTotal",
            "orderedTargetTotal",
            "tierCounts",
            "reviewWarnCount",
            "reviewRiskCount",
        )
        return {key: summary.get(key) for key in keys if key in summary}

    def _compact_pending(self, pending: Any) -> dict[str, Any] | None:
        if not isinstance(pending, dict):
            return None
        preview = str(pending.get("previewSummary") or "").strip()
        return {
            "kind": pending.get("kind"),
            "actionFamily": pending.get("actionFamily"),
            "previewSummary": preview[:180],
        }

    def _compact_score(self, score: Any) -> dict[str, Any] | None:
        if not isinstance(score, dict):
            return None
        subjects = score.get("subjects")
        return {
            "province": score.get("province"),
            "totalScore": score.get("totalScore"),
            "subjects": subjects[:3] if isinstance(subjects, list) else subjects,
            "sex": score.get("sex"),
            "volunteerModel": score.get("volunteerModel"),
        }

    def _recent_chat(self, chat_history: list[dict] | None) -> list[dict[str, Any]]:
        history = chat_history or []
        recent = history[-max(0, int(self.config.max_history_messages)) :]
        result: list[dict[str, Any]] = []
        for item in recent:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role and content:
                result.append({"role": role[:20], "content": content[:500]})
        return result

    def _pending_payload(self, pending: PendingConfirmation | None) -> dict[str, Any] | None:
        if pending is None:
            return None
        return {
            "kind": pending.kind,
            "actionFamily": pending.action_family,
            "previewSummary": pending.preview_summary,
        }

    def _planning_summary_payload(self, request_context: RequestContext) -> dict[str, Any] | None:
        summary = request_context.planning_summary
        if summary is None:
            return None
        return {
            "phase": summary.phase,
            "version": summary.version,
            "orderedTotal": summary.ordered_total,
            "orderedTargetTotal": summary.ordered_target_total,
            "tierCounts": summary.tier_counts,
            "reviewWarnCount": summary.review_warn_count,
            "reviewRiskCount": summary.review_risk_count,
            "riskSummaries": summary.risk_summaries[:3],
            "positiveRegions": summary.positive_regions[:5],
            "positiveMajors": summary.positive_majors[:5],
        }

    def _score_payload(self, request_context: RequestContext) -> dict[str, Any] | None:
        score = request_context.score_detail
        if score is None:
            return None
        return {
            "province": score.province,
            "totalScore": score.total_score,
            "subjects": score.subject_list,
            "sex": score.sex,
            "volunteerModel": score.volunteer_model,
        }
