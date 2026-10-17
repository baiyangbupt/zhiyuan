from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.harness.binding import ThreadBinding
from app.gateway.artifact_store import SqliteArtifactStore
from app.mcp_server.context import (
    ThreadBindingRegistry,
    TrustedContextError,
    extract_trusted_thread_id,
    extract_trusted_thread_id_from_metadata,
)
from app.mcp_server.response import error
from app.mcp_server.tools_readonly import (
    CAPABILITIES,
    InternalClientBackend,
    ReadonlyDomainTools,
    _kind_for,
)
from app.util import internal_client

try:
    from mcp.server import Server as SdkServer
    from mcp.server.models import InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, ToolAnnotations
except ImportError:  # pragma: no cover - exercised only before dependency installation
    SdkServer = None  # type: ignore[assignment,misc]
    InitializationOptions = Any  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    Tool = Any  # type: ignore[assignment,misc]
    ToolAnnotations = Any  # type: ignore[assignment,misc]

READONLY_TOOL_NAMES = frozenset(CAPABILITIES)
MCP_PROTOCOL_VERSION = "2024-11-05"

_COMMON_INPUT_PROPERTIES: dict[str, Any] = {
    "query": {"type": "string", "description": "用户提供的院校或专业名称"},
    "entityType": {"type": "string", "enum": ["school", "major"]},
    "name": {"type": "string"},
    "schoolId": {"type": "string"},
    "majorId": {"type": "string"},
    "groupCode": {"type": "string"},
    "admissionMode": {"type": "string", "enum": ["major", "major_group", "majorGroup"]},
    "province": {"type": "string"},
    "city": {"type": "string"},
    "schoolType": {"type": "string"},
    "ownership": {"type": "string"},
    "educationLevel": {"type": "string"},
    "areaId": {"type": "string"},
    # 省份编码（补录编码表用的名字；与 areaId 同义，兼容两种叫法）。
    "provinceCode": {"type": "string", "description": "省份编码（6 位，如 330000 浙江）"},
    "batch": {"type": "string"},
    # 批次 **level** 编码（01 本科 / 02 专科）——不是批次码（浙江第一段=17）。
    # 一分一段表按 level 取；取值来自 `catalog.get_batch_options` 的 `level`。
    "batchLevel": {"type": "string", "description": "批次 level 编码（01 本科 / 02 专科）；可从 catalog.get_batch_options 的 level 取"},
    "year": {"type": "integer"},
    # 科类编码**按省份口径**，全国不是一套：3+3 省份（浙江…）是 N；
    # 3+1+2 省份（安徽/江苏/广东/河北…）是 WL（物理类）/ LS（历史类）。
    # 实测：安徽 600 分传 WL 有位次、传 N 回空——"查不到"常常是科类给错，
    # 不是没有数据（2026-10-07 实测）。
    "subjectType": {
        "type": "string",
        "description": "科类编码，按省份口径：3+3 省份（如浙江）用 N；3+1+2 省份（如安徽/江苏）用 WL（物理类）/ LS（历史类）；不得跨省外推",
    },
    "stateVersion": {"type": "integer"},
    "dimensions": {"type": "array", "items": {"type": "string"}},
    "prepareType": {"type": "string", "enum": ["VOLUNTEER", "PREDICT"]},
    # 招生单位编号：`admission.get_enrollment_plan` 的必填项，来源是
    # `catalog.list_admission_units`（免分数）。
    "schoolUnitId": {"type": "string"},
}

# 同口径并列用：2–5 个**已确认**的实体（歧义要在进入对比之前解决掉）。
# **只属于 `admission.compare`，不进公共属性**：以前它被塞给所有工具，模型据此
# 对 `admission.check_eligibility` 发批量调用，而 handler 只认单条 `majorId`——
# 整批报 "majorId is required" 后退化成逐条重试（2026-10-17：一个续接回合
# 15 次资格核验）。schema 必须与 handler 同形：没有批量入口就别给批量参数。
_ENTITIES_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"schoolId": {"type": "string"}, "majorId": {"type": "string"}},
        "additionalProperties": False,
    },
}


def _input_schema(*required: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(_COMMON_INPUT_PROPERTIES),
        "required": list(required),
        "additionalProperties": False,
    }


# 默认描述：对所有工具都成立的那一句只读声明。
_DEFAULT_TOOL_DESCRIPTION = "Zhiyuan authoritative read-only domain query"

# 逐工具描述：**模型实际读到的那句话**。默认那句太粗，"口径"它读不到——
# 位次这种"同分不可分辨"的边界必须在描述里写死，否则模型只能猜，
# 而猜出来的是一个**精确名次**，正是这条工具要防的事。
#
# 产物形状的工具（候选 / 比较）共用下面这句：结果里的 `artifacts` 是
# `artifactRefs` 的**唯一合法来源**。不写这句的代价实测过（2026-10-08 事故）：
# 契约要求 recommendation/review 输出必须带 artifactRefs，工具没给 id 时
# 模型只能自己编，编出来的 id 没有会话章 → 整轮不可恢复地失败。
_ARTIFACT_REF_HINT = (
    "结果里的 artifacts 是本回合签发的产物引用；输出 responseType=recommendation/review 时，"
    "artifactRefs 只能从这里原样抄 artifactId/artifactType/stateVersion **三个字段**"
    "（不多抄、不改写、更不自行编造 id——自行编造的 id 缺会话章，会让整轮失败）。"
)

# 方案读（两个别名同实现）共用这一句：返回的是**方案条目明细**，不是招生事实。
# 不写清楚的话，模型会把"方案里有什么"变成一个靠印象回答的问题。
_PLAN_READ_DESCRIPTION = (
    "读取当前方案/工作区的条目明细（只读、不改状态）：优先读**排序方案**"
    "（kind=orderedPlan，items 带 position 位置、tier 档位、schoolName 院校、"
    "majorName 专业、volunteerId），尚未生成排序方案时回落**工作台方案**"
    "（kind=workingPlan）。两源都含 units（院校专业组单元）：unitId、schoolName、"
    "cityName 校区/城市文本、schoolNature、admissionRatio 录取率、finalScore；"
    "unit 内 majorItems 是专业明细（majorId/majorName/tier/tuitionPerYear 学费/"
    "admissionRatio/finalScore）。字段逐字来自上游、缺省即缺省，不得据此补值；"
    "空方案（items:[]）是正常态、不是读取失败；讨论方案内容一律以本工具返回为准，"
    "不得凭印象复述。"
)

TOOL_DESCRIPTIONS: dict[str, str] = {
    "admission.get_current_plan": _PLAN_READ_DESCRIPTION,
    # 新名与旧名是同一个工具：描述也共用同一句，不许两份说法分叉。
    "planning.get_working_plan": _PLAN_READ_DESCRIPTION,
    "catalog.get_score_position": (
        "一分一段表查询：按省份+分数查位次。同分考生不可分辨——"
        "highest_rank/lowest_rank 是区间（same_score_count 为同分人数），"
        "区间用于展示，只能报区间，不能报单一名次；"
        "测算用 default_rank（= lowest_rank，最保守口径，同分最后一名）；"
        "subjectType 是**各省口径**的科类编码：3+3 省份（浙江）用 N；"
        "3+1+2 省份（安徽/江苏）用 WL（物理类）/ LS（历史类）——这些省份传 N 会回空，"
        "看起来像\"该省没有数据\"其实是科类不适用；先问清/确认用户科类再查，"
        "不得跨省外推编码；上游无数据省份回不可用，不得估算（禁估算）。"
    ),
    # 候选预览：只读的候选纵切（过滤 → 分页 → 一页样例）。
    "recommendation.preview_candidates": (
        "会话候选池预览（只读）：按过滤条件（冲/稳/保档位、省份/城市/院校/专业关键词，"
        "含 negative* 排除项）分页取候选；`total` 是全量条数、`items` 只是这一页"
        "（`returned_items_are_sample` 为真时不得拿这页概括分布）；"
        "候选值由系统从会话候选池**真实载入**，不要自己填数字；预览不改任何状态。"
        "compare_candidates / explain_fit 的 entityId 取自这里的返回。"
        + _ARTIFACT_REF_HINT
    ),
    "recommendation.preview_majors": (
        "基于会话画像的专业方向打分推荐（只读）：把当前会话的分数/选科/性别画像"
        "交给 rank 服务做专业级打分，按综合分取 topN（上限 8 条切片）。"
        "答的是「适合什么**专业方向**」（专业类/大类层），**不落到具体志愿单元**；"
        "要具体院校/专业组的候选，用 recommendation.preview_candidates"
        "（专业方向 vs 具体志愿单元，两层别混用）。"
        "分数维度按 rank 服务口径：综合分是各维度的熵权合成，跨专业只比排序、"
        "不比绝对值，四个维度分（性别适配/满意度/薪酬/热度）不得改口径转述。"
        "画像缺分数时不可用：返回 unavailable=true 与原因码，如实说明不可用，"
        "不得用热度榜等无个性化数据顶替（禁估算、禁冒充）。"
        + _ARTIFACT_REF_HINT
    ),
    "recommendation.compare_candidates": (
        "对同伴会话内的候选志愿做矩阵比较（只读）；先 preview_candidates 拿 entityId "
        "再比较；未接线维度如实标不可用。"
        "入参 entityIds 2~5 个（= preview_candidates 返回的 entityId，即 volunteerId）；"
        "值由系统从会话候选池**真实载入**，不要自己填数字；"
        "口径不齐的数值列整列进 unavailable_dimensions（值为 null 是「不可比/无数据」，"
        "不是 0，不得凭印象补齐）；结论只能引用 cells 里带 source 的值。"
        + _ARTIFACT_REF_HINT
    ),
    "recommendation.explain_fit": (
        "解释某个候选为什么匹配/不匹配（只读）；概率不可用一律如实说；"
        "只引用带 source 的条目。"
        "先调 recommendation.preview_candidates 定位候选拿 entityId（= volunteerId），"
        "再对**单个**候选调这条（入参 entityId 单个）；"
        "值由系统从会话候选池与会话状态**真实载入**，不要自己填。"
        "matched 是逐条带 source 的匹配点（source 是来源字段对，如 "
        "「candidate.mustSubjects vs userScoreDetail.subjectList」）——**没有 source 的"
        "匹配点不存在、不许引用**；risks.flags/risks.reasonCodes 是候选行原样标志，"
        "转述不得改写；fit_dimensions 是各维度状态（matched/conflict/no_match/unknown/"
        "not_applicable），unknown 与 limitations 里列出的缺失字段如实说清，不得补值；"
        "probability 恒为 unavailable（无权威概率源）：**适配与概率分开讲**，"
        "不得估算或拿历年分数、院校热度顶替，绝不给出录取概率数字。"
        + _ARTIFACT_REF_HINT
    ),
    # 同口径并列（历史/率）：口径 = (年份, 省份, 批次, 科类)，四项必须给全——
    # 跨年、跨批次的数字并排放进一张表，读者会默认它们可比，而那是这张表最危险的错误。
    "admission.compare": (
        "把 2~5 个院校/专业在**同一口径**下并列（只读）：口径四项"
        "（entities/areaId/batch/year/subjectType）全部必填，缺一项就拒绝，"
        "不用\"最近一年\"或默认省份凑；口径不齐的列如实标不可用，"
        "值为 null 是「不可比/无数据」，不是 0，不得凭印象补齐。"
        + _ARTIFACT_REF_HINT
    ),
    # 批次编码表：补录草稿的 batch 码（按省不同：浙江第一段=17）与 level
    # （01 本科 / 02 专科）都取自这条；`subjectType` 按省份口径，多科类省份必给
    # ——可以给科类码（WL/LS），也可以给选考科目码/名（01/物理，Java 侧翻译）。
    "catalog.get_batch_options": (
        "批次编码表（补录成绩用）：[{code, name, level, score, pos}]——batch 码与"
        "level（01 本科 / 02 专科）只能从这里取，\"本科批\"这种名字不是编码。"
        "subjectType 按省份口径（3+1+2 省份 WL 物理类 / LS 历史类；3+3 省份 N）；"
        "可以给科类码，也可以给选考科目码/名（01/物理），Java 会翻译成该省科类。"
        "产品规则：用户总分 ≥ 本科批线（level=01 那条的 score）时，批次直接按"
        "本科批处理、不再追问；低于本科线才问/取专科批。"
    ),
}


TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "entity.resolve": _input_schema("query"),
    "catalog.search_schools": _input_schema(),
    "catalog.get_school": _input_schema(),
    "catalog.search_majors": _input_schema(),
    "catalog.get_major": _input_schema(),
    "admission.get_current_plan": _input_schema(),
    # 新名与旧名共用同一份 schema：它们是同一个工具，形状不该有两份。
    "planning.get_working_plan": _input_schema(),
    "admission.get_history": _input_schema(
        "areaId", "batch", "schoolId", "year", "subjectType"
    ),
    # 选科资格：**一次只核一个专业**。handler 只读单条 `majorId`（Java 侧
    # `majors["level3"]`），没有批量入口——schema 里就不该出现 `entities`，
    # 否则模型会按"能批量"的想象发调用，失败后再逐条重试，放大成 N+1。
    # 需要核多个时，先按选科组合去重、只核没核过的新专业（见
    # `candidate-recommendation` 技能的单轮预算）。
    "admission.check_eligibility": {
        "type": "object",
        "properties": {
            **_COMMON_INPUT_PROPERTIES,
            "majorId": {
                "type": "string",
                "description": (
                    "单个专业的 level3 专业 id（一次只核一个，没有批量参数）；"
                    "多专业先按选科组合去重，只核没有核过的新专业，禁止逐候选循环"
                ),
            },
        },
        "required": ["majorId"],
        "additionalProperties": False,
    },
    # 口径四项全部必填：缺一项就没法判断"能不能并排"，而那正是这个工具存在的理由。
    "admission.compare": {
        "type": "object",
        "properties": {**_COMMON_INPUT_PROPERTIES, "entities": _ENTITIES_PROPERTY},
        "required": ["entities", "areaId", "batch", "year", "subjectType"],
        "additionalProperties": False,
    },
    # 批次字典：`batch` 的合法取值只能从这里来（按省份不同）。
    "catalog.list_batches": _input_schema("areaId"),
    # 补录编码表：省份必填（批次码/科目码都是**按省份**的）。`subjectType` 可选，
    # 多科类省份（江苏 WL/LS）必须给；`score` 是契约保留字段（上游批次策略不按分数筛，
    # 传了会在结果 limitations 里如实标注）。
    "catalog.get_batch_options": {
        "type": "object",
        "properties": {
            **_COMMON_INPUT_PROPERTIES,
            "score": {"type": "integer", "description": "高考总分（契约保留：不参与批次筛选）"},
        },
        "required": ["provinceCode"],
        "additionalProperties": False,
    },
    "catalog.get_subject_options": _input_schema("provinceCode"),
    # 一分一段：省份 + 分数必填；科类 `subjectType` 默认 N，`batchLevel` 默认 01
    # （本科段，可由 `catalog.get_batch_options` 的 `level` 得到），`year` 默认当前年。
    "catalog.get_score_position": _input_schema("provinceCode", "score"),
    # 招生单元树：专业级那条链的入口，两个参数都是必需。
    "catalog.list_admission_units": _input_schema("schoolId", "areaId"),
    # schoolId 是 Java 侧的必填（`admission_source_school_required`）——上游那套
    # 「招生单元」是按 (学校, 地区) 展开的，缺了学校就无从校验。
    # 六项全必填：上游在缺项时**返回空而不是报错**，所以缺参必须在工具入口挡住，
    # 否则模型会连查几年、年年"0 行"，最后如实说"取不到"——而数据本来就在。
    # 招生章程：schoolId 必填；year 可选（标题里带年份，给了就选那一年的）。
    "admission.get_charter": _input_schema("schoolId"),
    "admission.get_enrollment_plan": _input_schema(
        "schoolUnitId", "schoolId", "areaId", "year", "subjectType", "batch"
    ),
    # 候选预览：只收过滤与分页。**身份字段(tenantId/sessionId)不在这里**——
    # 它们由受信 binding 注入；就算模型塞了，`_trusted_arguments` 也会丢掉。
    "recommendation.preview_candidates": {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "properties": {
                    # 档位是这套数据的原生分档：冲/稳/保。
                    "tiers": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["冲", "稳", "保"]},
                    },
                    "provinceNames": {"type": "array", "items": {"type": "string"}},
                    "cityNames": {"type": "array", "items": {"type": "string"}},
                    "schoolKeywords": {"type": "array", "items": {"type": "string"}},
                    "majorKeywords": {"type": "array", "items": {"type": "string"}},
                    "negativeProvinceNames": {"type": "array", "items": {"type": "string"}},
                    "negativeCityNames": {"type": "array", "items": {"type": "string"}},
                    "negativeSchoolKeywords": {"type": "array", "items": {"type": "string"}},
                    "negativeMajorKeywords": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            # 一次最多 20 条（硬上限，超了截断不报错）；total 给的是全量条数。
            "page": {"type": "integer", "minimum": 1},
            "pageSize": {"type": "integer", "minimum": 1},
        },
        "required": [],
        "additionalProperties": False,
    },
    # 专业方向推荐：入参只有切片大小 `topN`。**身份字段不在这里**——会话身份由
    # 受信 binding 注入（与 preview_candidates 同一口径）；模型塞进来的会被
    # `_trusted_arguments` 丢掉。topN 上限 8（硬上限，超了截断不报错）。
    "recommendation.preview_majors": {
        "type": "object",
        "properties": {
            "topN": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
                "description": "最多返回多少条专业方向（上限 8）",
            },
        },
        "required": [],
        "additionalProperties": False,
    },
    # 候选比较：**entityIds 必填且 2~5 个**（少于 2 不是比较，多于 5 表格读不过来；
    # 与 Java `CandidateComparisonService.MIN/MAX_ENTITIES` 同一口径）。
    # entityId = preview_candidates 返回的 entityId（即 volunteerId）。
    # **身份字段不在这里**——tenant/session 由受信 binding 注入，模型塞进来的会被
    # `_trusted_arguments` 丢掉。dimensions 可选：不在接线名单里的维度会如实进
    # unavailable_dimensions（不静默丢）。
    "recommendation.compare_candidates": {
        "type": "object",
        "properties": {
            "entityIds": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": "要比较的候选（2~5 个）entityId，取自 recommendation.preview_candidates 的返回",
            },
            # 不设 enum：名单外的维度要**如实降级**（unavailable_dimensions +
            # dimension_source_not_wired），而不是在 schema 层被拒——被拒的话
            # 模型看不到"这个维度不够数据"，只会换个说法再试。
            "dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "要比的维度（可选；缺省为全部已接线维度）。"
                    "已接线：admissionRatio/finalScore/planNum/tuitionPerYear/"
                    "schoolEnrollRatio/cityName；名单外的维度会进 unavailable_dimensions"
                ),
            },
        },
        "required": ["entityIds"],
        "additionalProperties": False,
    },
    # 适配性解释：**entityId 必填且只有一个**（解释的是"某一个"候选为什么匹配/
    # 不匹配；要多实体并列用 compare_candidates）。entityId = preview_candidates
    # 返回的 entityId（即 volunteerId）。**身份字段不在这里**——tenant/session
    # 由受信 binding 注入，模型塞进来的会被 `_trusted_arguments` 丢掉。
    "recommendation.explain_fit": {
        "type": "object",
        "properties": {
            "entityId": {
                "type": "string",
                "description": "要解释的单个候选 entityId，取自 recommendation.preview_candidates 的返回",
            },
        },
        "required": ["entityId"],
        "additionalProperties": False,
    },
}

TOOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schemaVersion",
        "kind",
        "status",
        "data",
        "evidenceRefs",
        "resolvedEntities",
        "limitations",
        "nextCursor",
        "stateVersion",
    ],
    "properties": {
        "schemaVersion": {"type": "integer", "enum": [1]},
        # `kind` 决定 `data` 的形状。六种数据混用会让"这是历史分数还是录取概率"
        # 变成一个靠字段猜的问题，而猜错的方向是把过去当未来。
        "kind": {
            "type": "string",
            # `orderedPlan` = 排序后的当前方案（方案读命中 ordered-plan 源时的 kind）；
            # `workingPlan` = 工作台方案/排序方案生成前的工作区。
            "enum": ["catalog", "history", "probability", "enrollment", "policy", "eligibility", "workingPlan", "orderedPlan", "comparison", "candidate"],
        },
        "status": {"type": "string"},
        "data": {},
        # 证据**本体**（Java 签发），不是指向证据的编号：下游账本要用它做跨回合核验。
        "evidenceRefs": {"type": "array", "items": {}},
        # 本回合签发的产物引用（候选/比较形状的结果各一条）：带会话/线程章的胖记录。
        # 模型输出 recommendation/review 时，`artifactRefs` 只能从这里抄——
        # 没有它，模型就只能自己编 id，而编出来的必然缺章（2026-10-08 事故）。
        "artifacts": {"type": "array", "items": {}},
        "resolvedEntities": {"type": "array", "items": {}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "nextCursor": {"type": ["string", "null"]},
        "stateVersion": {"type": "integer"},
        "admissionMode": {"type": "string", "enum": ["major", "major_group"]},
        "dataVersion": {"type": "string"},
        "code": {"type": "string"},
    },
    "additionalProperties": False,
}


class DomainMcpServer:
    def __init__(self, tools: ReadonlyDomainTools | None = None) -> None:
        self.tools = {name: None for name in READONLY_TOOL_NAMES}
        self.tool_runner = tools


def tool_listing() -> list[dict[str, Any]]:
    """工具清单的**唯一来源**：生产 stdio 循环与 SDK server 都从这里取。

    以前这里写了两遍，于是它们分叉了：`readOnlyHint` 只加在 SDK 那份上，
    而生产走的是手写循环，线上工具因此没有只读注解——真实二进制对未声明只读的
    MCP 工具一律要求审批，而生产策略是 approvalPolicy=never，无处可批，
    结果每个域内调用都以 `MCP tool call requires approval, but approval
    policy is never` 失败。两份清单从同一处生成，这个分叉就不可能再发生。

    注解同时是安全承诺，必须与 `READONLY_TOOL_NAMES` 严格一致。
    """
    annotations = {"readOnlyHint": True}
    return [
        {
            "name": name,
            "description": TOOL_DESCRIPTIONS.get(name, _DEFAULT_TOOL_DESCRIPTION),
            "inputSchema": TOOL_INPUT_SCHEMAS[name],
            "annotations": dict(annotations),
        }
        for name in sorted(READONLY_TOOL_NAMES)
    ]


def build_server() -> DomainMcpServer:
    return DomainMcpServer()


def build_sdk_server(
    tool_runner: ReadonlyDomainTools | None = None,
    *,
    binding_registry: ThreadBindingRegistry | None = None,
    artifact_store: Any | None = None,
) -> Any:
    """Build the production MCP SDK server around the governed tool runner.

    The SDK owns JSON-RPC framing and schema validation.  Domain authorization,
    state checks, retries and evidence scoping remain in ``ReadonlyDomainTools``.
    """
    if SdkServer is None:  # pragma: no cover - dependency is declared and installed in CI
        raise RuntimeError("mcp SDK is not installed")

    if binding_registry is not None and artifact_store is None:
        artifact_store = SqliteArtifactStore(str(binding_registry.path))

    server = SdkServer(
        "zhiyuan-domain-readonly",
        version="0.1.0",
        instructions="Read-only Zhiyuan catalog and admission facts; all writes are denied.",
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=entry["name"],
                description=entry["description"],
                inputSchema=entry["inputSchema"],
                outputSchema=TOOL_OUTPUT_SCHEMA,
                annotations=ToolAnnotations(**entry["annotations"]),
            )
            for entry in tool_listing()
        ]

    @server.call_tool(validate_input=True)
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        metadata = getattr(server.request_context, "meta", None) or {}
        return await _call_domain_tool(
            name,
            arguments or {},
            metadata=metadata,
            binding_registry=binding_registry,
            artifact_store=artifact_store,
            fallback_tool_runner=tool_runner,
        )

    return server


async def _call_domain_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    metadata: object,
    binding_registry: ThreadBindingRegistry | None,
    fallback_tool_runner: ReadonlyDomainTools | None = None,
    artifact_store: Any | None = None,
) -> dict[str, Any]:
    active_tool_runner = fallback_tool_runner
    if binding_registry is not None:
        try:
            thread_id = extract_trusted_thread_id_from_metadata(metadata)
            capability = CAPABILITIES.get(name)
            if capability is None:
                return error("tool_not_found", name, kind=_kind_for(name), state_version=0)
            binding = await binding_registry.resolve(
                thread_id=thread_id,
                capability=capability,
            )
        except TrustedContextError as exc:
            return error(str(exc), "trusted binding is unavailable", kind=_kind_for(name), state_version=0)
        try:
            expected_state_version = binding.snapshot_version
            if expected_state_version is None:
                raise ValueError("binding snapshot version is missing")
            expected_state_version = int(expected_state_version)
            if expected_state_version < 0:
                raise ValueError("negative binding snapshot version")
        except (TypeError, ValueError, AttributeError) as exc:
            return error("state_version_unavailable", str(exc), kind=_kind_for(name), state_version=0)
        try:
            state_version = await _read_snapshot_version(binding)
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as exc:
            return error("state_version_unavailable", str(exc), kind=_kind_for(name), state_version=0)
        if state_version != expected_state_version:
            # 版本在本回合中途前进了 → **有界重基**，不再把余下的读全部硬挡。
            # 2026-10-14 实测（会话 10041982）：本回合拉候选名单时前端把候选池生成了一遍
            # （`ensureCandidatePoolReady`），规划版本 +1；之后每个工具调用都撞上
            # "the authoritative snapshot changed during this turn"，模型"拉到一半"只能停手
            # 让用户回「继续」。
            # 守卫的宗旨是"绝不把**旧**版本的数据拼给用户"，不是"回合必须死在版本推进上"：
            # 重取最新快照、连续两次读到同一版本（写已落定）就按新版本继续读；旧证据/旧产物
            # 不会因此混拼——账本与产物各自按自己的版本核验（Gateway 侧产物上限、Java 侧
            # 证据 dataVersion ），重定版本之后本回合签发的都是**新版本**的读数。
            # 版本还在动（真并发写没停）或重读失败，维持 fail-closed。
            # 只重基**本次调用**、不回写登记表：绑定版本是 Gateway 每回合写一次的回合起点，
            # MCP 子进程不该改它；代价只是本回合后续调用各多读一次快照（有界、幂等）。
            try:
                state_version, settled = await _rebase_snapshot_version(
                    binding, observed=state_version
                )
            except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as exc:
                return error("state_version_unavailable", str(exc), kind=_kind_for(name), state_version=0)
            if not settled:
                return error(
                    "stale_state",
                    "the authoritative snapshot changed during this turn",
                    kind=_kind_for(name),
                    state_version=state_version,
                )
        active_tool_runner = ReadonlyDomainTools(
            binding,
            artifact_store=artifact_store,
            backend=InternalClientBackend(
                tenant_id=binding.tenant_id,
                chat_session_id=binding.session_id,
                thread_id=binding.thread_id,
                # 权威快照版本要**同时**给适配器：它自己给信封盖版本戳
                # （不给就 5 个工具全 backend_unavailable ✗，见 tools_readonly 的注释）。
                current_state_version=state_version,
            ),
            current_state_version=state_version,
            # MCP_MODE 由启动环境传入（composition 的 MCP_ENV_VARS 透传）；
            # 未设置时按只读——多一个开关不会自己变宽，少一个开关也不会。
            mode=os.environ.get("MCP_MODE", "readonly"),
        )
    if active_tool_runner is None:
        return error("binding_unconfigured", "trusted binding is unavailable", kind=_kind_for(name), state_version=0)
    return await active_tool_runner.call(name, arguments)


# 版本前进后的重基次数上界（"落定确认"的额外读数次数）。一次通常就够
# （写已完成：第二读与第一读同版本）；给到 2 只是让"写还在收尾"的多写序列
# 多一次机会。超界一律 fail-closed，不做无界重试。
_REBASE_ATTEMPTS = 2


async def _read_snapshot_version(binding: ThreadBinding) -> int:
    """读一次权威快照版本（Java 的 turn-snapshot）。

    读不到、解不出、负数都抛出去——调用侧转 `state_version_unavailable`（fail-closed）。
    """
    snapshot_response = await internal_client.get_conversation_turn_snapshot(
        binding.tenant_id,
        binding.session_id,
    )
    snapshot_data = (snapshot_response or {}).get("data") or {}
    raw_version = snapshot_data.get("snapshotVersion", snapshot_data.get("version"))
    state_version = int(raw_version)
    if state_version < 0:
        raise ValueError("negative snapshot version")
    return state_version


async def _rebase_snapshot_version(
    binding: ThreadBinding, *, observed: int
) -> tuple[int, bool]:
    """重基到最新版本：**连续两次读到同一版本**才算落定（有界，最多 `_REBASE_ATTEMPTS` 次）。

    返回 `(last_version, settled)`。`settled=False`（次数用完版本仍在动）由调用侧
    按 `stale_state` fail-closed：那是"真并发写还没停"的形状，此时把任何一个中间
    版本当"最新"读，都可能把半程数据拼给用户。
    """
    previous = observed
    for _ in range(_REBASE_ATTEMPTS):
        current = await _read_snapshot_version(binding)
        if current == previous:
            return current, True
        previous = current
    return previous, False


def serve(binding_registry_path: str) -> None:
    """Run a minimal JSON-RPC stdio MCP server compatible with Codex App Server.

    The installed MCP SDK's stdio transport does not consume stdin in this
    deployment environment.  We retain its schema builder for tests while the
    production transport uses the small, protocol-specific loop below.
    """
    registry = ThreadBindingRegistry(binding_registry_path)
    artifact_store = SqliteArtifactStore(binding_registry_path)
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}
        result: dict[str, Any] | None = None
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", MCP_PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "zhiyuan-domain-readonly", "version": "0.1.0"},
                "instructions": "Read-only Zhiyuan catalog and admission facts; all writes are denied.",
            }
        elif method == "tools/list":
            result = {"tools": tool_listing()}
        elif method == "tools/call":
            outcome = asyncio.run(
                _call_domain_tool(
                    str(params.get("name") or ""),
                    dict(params.get("arguments") or {}),
                    metadata=params.get("_meta") or {},
                    binding_registry=registry,
                    artifact_store=artifact_store,
                )
            )
            result = {
                "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                "isError": False,
            }
        elif method == "resources/list":
            # 我们不暴露 resource，但**必须回答**：真实 MCP 客户端在握手后会
            # 逐一探测 resources/list 与 resources/templates/list，收不到应答就
            # 一直等，整个 server 卡在未连接状态（实测 mcpServerStatus/list 超时）。
            result = {"resources": []}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        if request_id is None:
            continue
        if result is None:
            # 兜底：任何**未识别但带 id** 的请求都要明确回错。
            # 沉默不是"优雅降级"，是让对方永久挂起——握手失败点上没有任何日志。
            response: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        else:
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--binding-registry", default="")
    args = parser.parse_args()
    if args.self_check:
        print(json.dumps({"tools": sorted(READONLY_TOOL_NAMES), "write_tools": 0}, ensure_ascii=False))
        return
    if not args.binding_registry:
        parser.error("--binding-registry is required for MCP serving")
    serve(args.binding_registry)


if __name__ == "__main__":
    main()
