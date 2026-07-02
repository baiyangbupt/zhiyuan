# Release 4.0.0 — Zhiyuan Agent 实施设计

> 版本: v1.7 | 日期: 2026-07-02
> 变更: v1.7 新增 §9.14 完整 320 G1-G32 direct 复跑结果，记录 44/49、G25/G27/旧路由残留和性能问题；更新 Phase 4 检查项
> v1.6 新增 §9.13 高收费 follow-up 参数完整性与 filter 安全，明确不使用字符串 precheck、不在工具层做原话 NLU 特化；更新 Phase 4 检查项，确认 direct-only 口语集与确认执行后端 action 断言已通过
> v1.5 更新 §9.5 G17 问题定性（三层防护已到位，剩余为 LLM 可靠性）；重写 §9.9 G25 为三个子问题（routing 抢跑 / schema alias / positive 漏 negative）；新增 §9.12 四阶段下一步计划（环境排障→schema+Prompt→respond 验证→完整回归）
> v1.4 扩展 §9.5-§9.10：G17 selector 归一化三层防护、G4 实体展示保真、G3 查询计数粒度、G32 探索降级维度模板、G25 复核策略、§9.1 respond 软停验证边界
> v1.3 根据 G1-G32 完整回归（49步/46通过/3失败）新增 §9：复合诉求 next_step 策略、pending 下只读路由、正向意向边界澄清、档案提取边界、实现级修复汇总
> v1.2 收口 pending 确认链路：普通方案调整只接受 `action_family` + `atomic_actions` 结构化 payload，非结构化历史 pending 不再保留专用兼容分支
> 前置文档:
> - [release-4.0.0-coding-agent-architecture-redesign.md](release-4.0.0-coding-agent-architecture-redesign.md) — 架构设计
> - [release-4.0.0-coding-agent-poc-plan.md](release-4.0.0-coding-agent-poc-plan.md) — PoC 验证方案
> - [release-4.0.0-coding-agent-implementation-tracking.md](release-4.0.0-coding-agent-implementation-tracking.md) — 实施追踪

## 1. 当前进度与整体路径

### 1.1 PoC 验证结论

PoC 以 4 个正交工具 + 状态前置注入 + next_step 终止信号验证了核心假设：

| 指标 | 当前系统 | PoC 结果 |
|------|---------|---------|
| 工具调用/轮 | 2-5 | 1 |
| System prompt | ~22K tokens | ~3K tokens |
| 输入 token/轮 | 17K-37K | ~1.2K |
| 延迟 | 25-35s | 1.2-2.8s |
| 工具选择正确率（5场景） | ~70% | 100% |

### 1.2 从 PoC 到正式版的整体路径

按架构设计文档 §9 的四阶段迁移方案推进，结合 PoC 已完成的部分：

```
                    PoC 已完成
                    ───────────
Phase 1 ──────────────────────────────────── Phase 2
  SandboxFileCache                            9 工具正式实现
  Backend Adapter                             非阻塞 Shadow
  ZhiyuanAgent 升级                           扩展 Case 集合
  ───────────────────────────────────────────────────────────
Phase 3 ──────────────────────────────────── Phase 4
  Shadow Diff 大规模验证                       功能开关 + 渐进放量
  Confusion Matrix                            监控仪表盘 + 回滚
  320+ 用例跑新系统                            旧代码清理
```

**核心原则：直接实现，不做委托/代理。** 新工具直接使用域层原语（实体解析器、`internal_client` API、静态数据）实现业务逻辑，不包装旧工具函数。旧工具在生产切换稳定后整体移除。

### 1.3 PoC 与正式版的差异

| 维度 | PoC（已完成） | 正式版（本文设计） |
|------|-------------|-----------------|
| 工具数量 | 9（Phase 2 第二/三批首版已落地） | 9 |
| 状态读取 | 从 `ctx.deps` 直读 | 通过 SandboxFileCache |
| explore_topic | major/school 已接 profile API，失败降级只读摘要 | 继续接入权重分析与 career/region 覆盖统计 |
| query_plan | 已扫描 `plan/items.json` 并支持 filters | 继续补齐旧主链路展示维度 |
| preview_intent_change | 已创建结构化 pending，专业/院校/地域已接入 `simulate_plan_diff`，失败降级本地扫描 | 扩展真实 shadow case 观察 diff 稳定性 |
| 确认流程 | `confirm_pending` 已支持结构化 pending | 后续预览工具只产出结构化 payload |
| 方案操作 | `preview_plan_action` 首版已注册，产出结构化 pending；支持核心 review issue 范围删除/排序/重排预览、review issue + filters 复合范围和 replace 自动候选首版 | 扩展候选质量评估 |
| answer_policy | 首版已注册，离线优先整合政策框架、school profile 招生政策和参数可用性校验 | 扩展官方来源抽取和适配匹配 |
| review_plan | 首版已注册，执行/读取审查并可选返回只读修复建议；核心 review issue 可联动方案操作预览；G2/G21 真实工具选择边界已通过 | 扩展真实 service shadow case |
| shadow 模式 | 非阻塞后台 task 首版已落地 | 继续补 shadow diff 与采样评估 |

---

## 2. Phase 1: SandboxFileCache + Backend Adapter

### 2.1 设计目标

将工具对 `RequestContext` 的直接耦合替换为虚拟文件视图，实现：
- 工具通过路径读写，不关心数据来源
- 版本驱动的缓存失效，避免读到过期数据
- 写操作成功后自动失效关联文件

### 2.2 文件路径 → 后端 API 映射

```python
class BackendAdapter:
    """文件路径到后端 API 的映射。每个路径对应一个获取函数。"""

    ROUTE_TABLE: dict[str, Callable] = {
        "score.json":         lambda sid: get_user_score_detail(sid),
        "profile.json":       lambda sid: get_user_init_profile(sid),
        "constraints.json":   lambda sid: get_planning_workspace_state(sid),  # 提取 constraints 段
        "plan/summary.json":  lambda sid: get_planning_state(sid),            # 提取 summary 段
        "plan/items.json":    lambda sid: get_planning_ordered_plan(sid),
        "plan/candidates.json": lambda sid: query_planning_candidate_pool(sid, ...),
        "plan/review.json":   lambda sid: get_planning_state(sid),            # 提取 review 段
        "pending.json":       lambda sid: get_pending_confirmation(sid),
    }
```

**核心设计点：**
- `get_planning_state` 一次返回 summary + review + tier_counts 等多段数据，`BackendAdapter` 负责拆分到对应虚拟文件路径
- `plan/items.json` 可能 5-50KB，需要按需加载而非 cache warming 阶段预取

### 2.3 SandboxFileCache

```python
class SandboxFileCache:
    """会话级虚拟文件缓存。"""

    def __init__(self, session_id: str, adapter: BackendAdapter):
        self._session_id = session_id
        self._adapter = adapter
        self._cache: dict[str, CacheEntry] = {}

    async def read(self, path: str, query: str | None = None) -> dict:
        """读取文件。未缓存或已失效时从后端拉取。"""

    def invalidate(self, paths: list[str]) -> None:
        """写操作成功后失效关联文件。"""

    async def warm(self, paths: list[str]) -> None:
        """预热常用文件。Context 构建阶段并行加载。"""
```

**缓存条目结构：**
```python
@dataclass
class CacheEntry:
    data: dict[str, Any]
    version: int              # 后端 planning version
    fetched_at: float         # monotonic timestamp
    ttl_seconds: float = 300  # 最长存活时间
```

**失效规则（与架构文档 §5.3 一致）：**

| 触发事件 | 失效文件 |
|---------|---------|
| 偏好确认（confirm_pending → intent） | `profile.json`, `constraints.json` |
| 方案变更（confirm_pending → plan） | `plan/summary.json`, `plan/items.json`, `plan/review.json`, `pending.json` |
| 方案生成 | 所有 `plan/*` |
| 审查运行 | `plan/review.json`, `plan/summary.json` |
| Pending 创建/清除 | `pending.json` |

**Cache warming 策略：**
- Context 构建阶段并行预取 `score.json` + `profile.json` + `plan/summary.json` + `pending.json`（共 4 个并行请求）
- `plan/items.json` 和 `plan/candidates.json` 按需加载（仅 `query_plan` 和 `preview_plan_action` 使用）

### 2.4 版本守护

复用现有 `app/sync/state_sync.py` 的 `PlanningStateSync`，适配到 SandboxFileCache：

```python
class SandboxFileCache:
    def _is_stale(self, path: str) -> bool:
        entry = self._cache.get(path)
        if entry is None:
            return True
        # TTL 过期
        if (monotonic() - entry.fetched_at) > entry.ttl_seconds:
            return True
        # 版本漂移：planning 相关文件检查后端版本
        if path.startswith("plan/") or path == "pending.json":
            return entry.version < self._latest_backend_version
        return False
```

### 2.5 与 PoC 的衔接

PoC 中工具通过 `ctx.deps.score_detail`、`ctx.deps.planning_summary` 直接取值。正式版改为：

```python
# PoC
score = ctx.deps.score_detail

# 正式版
sandbox: SandboxFileCache = ctx.deps.sandbox
score = await sandbox.read("score.json")
```

`RequestContext` 增加 `sandbox: SandboxFileCache` 字段。Context 构建阶段创建 cache 实例并执行 warm。

---

## 3. Phase 2: 9 工具正式实现

### 3.1 设计原则

**直接实现，不做委托。** 每个新工具：
- 直接调用 `internal_client` 的后端 API（不经过旧工具函数）
- 直接使用 `app/domain/` 的实体解析器
- 直接从 SandboxFileCache 读取状态
- 输出统一 `{data, next_step, message}` 格式

旧工具中值得保留的是**领域计算逻辑**（如梯度计算、对比格式化），在新工具中重新实现或提取为独立工具函数放入 `app/domain/`。旧工具函数本身（包含路由判断、上下文拼接、多轮状态恢复等胶水）不复用。

### 3.2 工具总览

| 工具 | 类型 | 替代的旧工具 | 主要后端 API |
|------|------|------------|------------|
| `read_state` | 读取 | 隐式状态读取 | SandboxFileCache.read |
| `explore_topic` | 分析 | 6 个 analyze/explore 工具 (1302行) | `get_major_profile`, `get_school_profile_by_name`, `analyze_majors`, `analyze_schools` |
| `compare_entities` | 分析 | 5 个 compare/info 工具 (1584行) + 2 个 score query (358行) | `analyze_majors`, `analyze_schools`, `get_major_profile`, `get_school_profile_by_name` |
| `query_plan` | 查询 | `query_volunteer_plan` + `collect_plan_context_inputs` (1356行) | `get_planning_ordered_plan`, `query_planning_candidate_pool` |
| `preview_intent_change` | 预览 | 5 个 intent preview 工具 (575行) + intent_state_tool (4608行) | `update_planning_constraint_state`, `simulate_plan_diff` |
| `preview_plan_action` | 预览 | plan_execution (5160行) + plan_orchestration (1234行) + plan_semantic_action (855行) | `select_working_plan_items`, `remove_planning_ordered_plan_units`, `move_planning_ordered_plan_unit`, `sort_planning_ordered_plan`, `generate_planning_ordered_plan` |
| `confirm_pending` | 执行 | service.py 中分散的 pending 协议 | 按 pending.kind 分发到对应后端 API |
| `answer_policy` | 查询 | admission_policy (395行) + official_source_search (411行) + admission_fit_match (313行) | `search_official_admission_sources`, `check_plan_param_availability` |
| `review_plan` | 分析 | planning_workflow 审查函数 (2269行) | `run_planning_review`, `generate_planning_fix_proposals` |

### 3.3 各工具核心设计点

#### `read_state` — 沙箱文件读取

PoC 已有基本实现。正式版变更：

- **数据来源**：从 `ctx.deps` 直读 → `SandboxFileCache.read(path)`
- **增加 query 参数**：支持 `query_plan` 级别的过滤表达式（如 `"tier=保 and tuition > 20000"`），但 `read_state` 本身只做简单的 path 读取，复杂查询留给 `query_plan`
- **增加路径**：`plan/items.json`、`plan/candidates.json`、`plan/review.json`、`constraints.json`

```python
StatePath = Literal[
    "score", "profile", "plan/summary", "plan/items",
    "plan/candidates", "plan/review", "pending", "constraints"
]
```

#### `explore_topic` — 方向/适配/兴趣分析

PoC 返回占位文本。正式版直接实现分析逻辑：

**按 topic_type 的后端 API 和数据组装：**

| topic_type | 后端 API | 输出内容 |
|-----------|---------|---------|
| `major` | `get_major_profile(name)` → 专业画像 | 课程方向、就业去向、与选科匹配度、在当前方案中的覆盖情况 |
| `school` | `get_school_profile_by_name(name)` → 院校画像 | 录取线趋势、优势学科、地理位置、与分数档位匹配度 |
| `career` | 无需后端调用，基于 `career_slots` 归一化 + 方案画像 | 方向定义、相关专业映射、当前方案的职业覆盖度 |
| `region` | 无需后端调用，基于 `region_entity_resolver` + 方案统计 | 区域院校分布、当前方案中该区域志愿数、生活成本参考 |

**核心设计点：**
- 实体解析在工具内部完成（`user_question` 中提取实体名 → 解析器归一化）
- 分析结果从后端 API 原始数据直接格式化，不经过旧的 `explore_direction_tool` 的 LLM 二次分析
- 需要方案上下文时，从 SandboxFileCache 读取 `plan/summary.json`
- `next_step: "respond"`

**与旧工具的区别：**
旧 `explore_direction_tool`（1302行）内部起了一个独立 LLM Agent 做分析生成。新工具直接从后端 API 取结构化数据，由外层 ZhiyuanAgent 做自然语言综合。省掉内部 LLM 调用。

**Phase 2 第二批首版落地状态（2026-06-30）：**
- `topic_type=major` 已接 `get_major_profile` / `get_major_category_profile`
- `topic_type=school` 已接 `get_school_profile_by_name`
- 工具返回 `entity`、`entity_level`、`profile_source`、`profile_facts`、`profile_raw`
- 后端 profile 不可用时保留只读降级回复，不改状态、不阻断主流程
- `analyze_majors` / `analyze_schools`、career/region 方案覆盖分析仍留作后续扩展

#### `compare_entities` — 学校/专业对比

新增工具，替代 5 个 compare 工具 + 2 个 info 工具。

```python
async def compare_entities(
    ctx: RunContext[RequestContext],
    entity_type: Literal["major", "school"],
    entities: list[str],             # 2-5 个实体名
    comparison_focus: str | None,    # "就业", "课程", "录取难度"
) -> str
```

**核心设计点：**
- 实体解析：每个 entity name 走对应解析器归一化。任一歧义 → `next_step: "clarify"` + 候选列表
- 数据获取：并行调 `get_major_profile` / `get_school_profile_by_name`（每个实体一次）
- 对比矩阵：从后端返回的结构化数据中提取对比维度（录取分数、就业率、课程方向等），按 `comparison_focus` 筛选
- 方案关联：从 `plan/summary.json` 读取当前方案，标注"已在方案中"
- `next_step: "respond"`

**与旧工具的区别：**
旧 `major_compare_tool`（600行）和 `school_compare_tool`（446行）内部各自起 LLM 做对比总结。新工具返回结构化对比数据，由外层 Agent 生成自然语言。

**Phase 2 第二批首版落地状态（2026-06-30）：**
- 已注册 `compare_entities` 到 `ZhiyuanAgent`
- 已支持 `entity_type=major|school`、2-5 个对象对比
- profile 数据并发获取，返回结构化 `rows` 对比矩阵
- 已标注 `in_current_plan`，可提示对象是否已在当前方案中
- 返回 raw 已瘦身，避免工具输出过大
- `analyze_majors` / `analyze_schools` 个性化量化指标仍留作后续扩展

#### `query_plan` — 方案/候选查询

PoC 已有基本框架。正式版增加真实方案扫描能力。

**核心变更：**
- **plan 查询**：调 `get_planning_ordered_plan(session_id)` 获取完整志愿列表，在工具内部按 `filters` 扫描匹配
- **candidates 查询**：调 `query_planning_candidate_pool(session_id, ...)` 获取候选池
- **filters 处理**：

| filter key | 匹配逻辑 |
|-----------|---------|
| `school_nature` | 精确匹配 item 的 `school_nature` 字段 |
| `tier` | 精确匹配 `冲/稳/保` |
| `school` | 模糊匹配学校名（走 `school_entity_resolver`） |
| `major` | 模糊匹配专业名（走 `major_entity_resolver`，支持 level1/2/3） |
| `tuition_max` | item 的 `tuition_per_year <= value` |
| `province` | 匹配院校所在省份 |

- **截断策略**：匹配结果超过 `limit`（默认 20）时截断，返回总命中数 + 前 N 条详情
- `next_step: "respond"`

#### `preview_intent_change` — 预览显式报考要求

PoC 已有实体解析和归一化。正式版增加方案影响分析和 pending 创建。

**核心变更：**

1. **方案影响分析**：归一化后基于当前完整画像构造 backend-format proposed profile，调 `simulate_plan_diff(tenant_id, session_id, proposed_profile)` 计算"排除医学会影响哪些志愿"
2. **Pending 创建**：影响分析通过后，调 `save_pending_confirmation(session_id, pending_data)` 创建 pending
3. **约束写入**：确认后调 `update_planning_constraint_state(session_id, intentMode="constraint", ...)` 写入硬性报考要求

**正式版签名（约束简化后）：**
```python
async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: Literal["major", "school", "region", "career"],
    positive: dict[str, Any] | None = None,
    negative: dict[str, Any] | None = None,
    constraint_type: Literal["exclude", "only_keep", "must_have"] = "exclude",
) -> str
```

> 注：`preference` 已从 `constraint_type` 移除。用户对话仅处理硬约束（exclude/only_keep/must_have）。软性推荐系数调整不暴露给用户交互界面，后续从系统隐性角度运行。详见 §3.6。

**返回数据结构（正式版）：**
```json
{
  "data": {
    "intent_type": "major",
    "constraint_type": "exclude",
    "normalized": {"positive": {}, "negative": {"level1": ["医学"]}},
    "plan_impact": {
      "affected_count": 5,
      "affected_items": ["华中科技大学·临床医学", "..."],
      "tier_impact": {"冲": -1, "稳": -2, "保": -2}
    },
    "pending_id": "pending_12345",
    "requires_confirmation": true
  },
  "next_step": "confirm",
  "message": "排除医学门类后，当前方案有5个志愿受影响（冲1/稳2/保2）。确认的话点击采纳。"
}
```

- `next_step: "confirm"`（正常） / `"clarify"`（歧义）

**Phase 2 第一批延伸落地状态（2026-06-30）：**
- 已将 normalized intent 转成 `executionPayload.merged` / `selectedData.selected`
- 已创建 `kind=intent_change`、`actionFamily=apply_selected_intents` 的结构化 `pendingConfirmation`
- 已按 `constraint_type` 设置 `intentMode=constraint` 和 `constraintIntentType`，不再生成 `preference` pending
- 已接入 `simulate_plan_diff(...)` 生成真实 `plan_impact`，包含 before/after tier、promoted、demoted 与 tier delta
- 已保留 `plan/items.json` 本地扫描降级路径，避免 diff 服务不可用时阻断 pending 预览
- 保存成功后会 prime `pending.json`，供 `confirm_pending` 直接读取并执行
- `career` 方向暂不在后端 `UserProfile` 结构中，真实 diff 后续等画像结构支持后再补

#### `preview_plan_action` — 预览方案变更

新增工具。替代 `plan_execution_tool`（5160行）+ `plan_orchestration_tool`（1234行）+ `plan_semantic_action_tool`（855行）。

```python
async def preview_plan_action(
    ctx: RunContext[RequestContext],
    action: Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order"],
    targets: list[str] | None = None,
    target_position: int | None = None,
    filters: dict[str, Any] | None = None,
    review_issue_code: Literal[
        "high_tuition",
        "cooperative_program",
        "admission_limit",
        "special_enrollment",
        "probability_inversion",
        "probability_gap",
        "count_validation",
        "edge_score",
        "safety_guard",
        "major_group_safety_intent_alignment",
        "group_inner_safety_guard",
        "tier_gap",
        "low_safety",
        "career_mismatch",
    ] | None = None,
    raw_user_text: str = "",
) -> str
```

**action → 后端 API 映射：**

| action | 后端 API | 核心逻辑 |
|--------|---------|---------|
| `add` | `select_working_plan_items` → `generate_planning_ordered_plan` | 从候选池选入 → 重新生成正式方案 |
| `remove` | `remove_planning_ordered_plan_units` | 解析 targets 为 unit_id → 移除 |
| `move` | `move_planning_ordered_plan_unit` | 解析 target + position → 移动 |
| `replace` | `remove` + `add` 组合 | 先移出旧的 → 从候选池选入替换 |
| `sort` | `sort_planning_ordered_plan` | 按指定字段重排序 |
| `generate` | `generate_planning_initial_plan` 或 `generate_planning_ordered_plan` | 首次/重新生成方案 |
| `regenerate_order` | `generate_planning_ordered_plan` | 保持候选池不变，重新排序生成 |

**targets 引用解析：**

`targets` 可以是多种引用格式，工具内部统一解析为 `unit_id`：

| 引用格式 | 解析方式 |
|---------|---------|
| `"10561_0805_001"` | 直接使用 volunteer_id |
| `"华南理工大学"` | 从 `plan/items.json` 中按学校名匹配 |
| `"华南理工大学.软件工程"` | 学校名 + 专业名联合匹配 |
| `"第3个"` / `"第3-5个"` | 按 position 索引 |
| `"冲的第一个"` | 按 tier + position 索引 |
| `review_issue_code="high_tuition"` / `"cooperative_program"` | 从 `plan/review.json` 的对应 issue 读取 affected unit ids，并兼容后端 code alias |

解析使用域层 `school_major_ref_resolver`（162行），在新工具中直接引入。

**核心设计点：**
- 所有 action 先构建预览，创建 pending，不立即执行
- 预览需要计算梯度影响（冲/稳/保数量变化），从 `plan/summary.json` 和操作目标推导
- `generate` 操作前校验前置条件：是否有成绩、是否有最低偏好输入。使用 SandboxFileCache 读取 `score.json` 和 `profile.json` 判断
- `next_step: "confirm"`

**与旧工具的区别：**
旧的 `plan_execution_tool`（5160行）包含完整的执行 + 后处理 + 二次审查 + 修复建议生成，是一个 mini 编排引擎。新工具只做预览 + pending 创建。执行由 `confirm_pending` 负责。

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `preview_plan_action` 到 `ZhiyuanAgent`
- 已支持 `add/remove/move/replace/sort/generate/regenerate_order` 创建结构化 `pendingConfirmation`
- `executionPayload` 只使用 `action_family` + `atomic_actions`，不再生成旧式 opaque `planPayload`
- `remove/move` 从 `plan/items.json` 解析当前方案项，`add/replace` 从 `plan/candidates.json` 解析候选 volunteerId
- `remove/replace` 支持 `review_issue_code` 首版联动；当用户明确说“把审查里的高收费/中外合作/限报/特殊招生项移出去”且未给具体 targets 时，从 `plan/review.json` 解析 affected units，并把 `review_issue_target` 写入 `executionPayload` / `atomic_actions`
- `review_issue_code` 收窄为后端当前 preview-fixable 核心规则枚举，并保留 `tier_gap/low_safety/career_mismatch` 语义别名；当前高收费、中外合作、限报、特殊招生 item 风险已有删除范围联动，且支持后端 code alias 和中文摘要归一
- 审查结果只有 `affectedVolunteerIds` 或 `affectedItems[].volunteerId` 时，会用 `plan/items.json` 反查当前方案项并生成执行所需 `unit_ids`
- `remove + review_issue_code + filters` 支持审查问题范围与属性 filters 求交集，例如“高收费且民办”；无交集时不创建 pending
- `regenerate_order/sort` 支持只绑定审查 issue 元信息；录取率倒挂、梯度/冲稳保断层、保底不足等结构性问题可生成排序/重排 pending，payload 携带 `review_issue_target`，确认后仍走结构化 `confirm_pending`
- `review_issue_code` 找不到可操作 unit 时返回 `clarify`，不退回只读审查；`replace` 缺候选时也先澄清
- `replace + review_issue_code` 在用户未指定候选且 `plan/candidates.json` 可用时，可按同档位、同省、学费降低、规避当前 issue 风险标签等保守规则自动选择替换候选；候选池不可用/无命中时仍澄清
- `confirm_pending` 已支持 `replace_units` 结构化执行：remove → select → regenerate
- 位置范围、档位内序号和 G17 风格档位内局部重排已首版支持：`第3-5个`、`冲的第一个`、`tier + admission_ratio max + target_tier/target_ordinal`
- G16 锁定/固定位置已拆出为 `pin_lock` 受控 unsupported action：不创建 pending，不再误走移动/no-change；完整 ordered-plan pin/lock 执行等后端接口稳定后再接
- G30 强基路径已通过 `program_type=强基` 保留为属性 selector，不退化为普通院校偏好
- service 过渡期旧预览 sink 已改为保存扁平结构化 `executionPayload`，不再产生新的旧式 `planPayload` pending；非结构化历史 pending 统一拒绝/失效，不保留 `planPayload` 专用兼容分支，也不回退旧 `execute_plan_action`
- 候选自动选择质量评估和完整 service shadow 仍留作后续扩展，不回引旧 `execute_plan_action`

#### `confirm_pending` — 确认/取消待确认操作

新增工具。将 service.py 中分散的 pending 确认协议收敛到一个工具。

```python
async def confirm_pending(
    ctx: RunContext[RequestContext],
    action: Literal["confirm", "cancel"],
) -> str
```

**核心设计点：**

1. **版本守护**：执行前读 `pending.json` 获取 `source_backend_version`，与后端当前版本比较。版本漂移 → 清除 pending + 返回错误提示。复用 `PlanningStateSync.pre_execute_guard` 的判断逻辑。

2. **按 pending.kind 分发执行：**

| pending.kind | 确认时执行 | 失效文件 |
|-------------|----------|---------|
| `intent_change` | `update_planning_constraint_state(intentMode="constraint")` → 写硬性报考要求 → **如有方案则 `generate_planning_ordered_plan` 再生成**（§3.7） | `constraints.json`, `plan/*`, `pending.json` |
| `plan_mutation` | 按 `action_family` 调对应后端 API（remove/move/sort/add） | `plan/*`, `pending.json` |
| `plan_generation` | `generate_planning_initial_plan` 或 `generate_planning_ordered_plan` | `plan/*`, `pending.json` |

3. **取消**：清除 pending，不调后端。仅失效 `pending.json`。

4. **执行后刷新**：确认执行成功后，失效 SandboxFileCache 中的关联文件路径，下次读取时自动拉取最新。

- `next_step: "respond"`（成功/失败都直接回复）

**Phase 2 第一批落地状态（2026-06-30）：**
- 已注册 `confirm_pending(action="confirm" | "cancel")` 到 `ZhiyuanAgent`
- 已支持无 active pending 防护、取消、版本漂移守护、执行后 sandbox 失效
- `intent_change` 已直接调用 `update_planning_constraint_state(intentMode="constraint")`；用户交互层不再写软性 `preference`
- 结构化 `plan_mutation` 已直接分发到 add/remove/move/sort/generate/regenerate 对应后端 API
- `confirm_pending` 只接受 `action_family` + `atomic_actions` 结构化 payload；非结构化历史 pending 不再委托旧 `execute_plan_action`，会要求重新生成结构化预览；当前 `preview_plan_action` 和 service 过渡 sink 都只产出结构化 payload

#### `answer_policy` — 报考政策问答

新增工具。替代 `admission_policy_tool`（395行）+ `official_source_search_tool`（411行）+ `admission_fit_match_tool`（313行）。

```python
async def answer_policy(
    ctx: RunContext[RequestContext],
    question: str,
    rule_domain: Literal[
        "score_batch", "eligibility", "tuition_budget", "enrollment_rules",
        "school_rule", "transfer_major", "subject_requirement",
        "physical_exam", "oral_exam", "general"
    ] | None = None,
    school_name: str | None = None,
    major_name: str | None = None,
    year: int | None = None,
    use_official_search: bool = False,
) -> str
```

**核心设计点：**
- 如有 `school_name`，先走 `school_entity_resolver` 归一化
- 默认离线优先：学校规则类问题读取 `get_school_profile_by_name(...)` 的招生政策字段
- 对明确学校/专业/省份目标，先保留标准名称用于返回，再转后端编码调 `check_plan_param_availability(...)` 校验可用性
- `use_official_search=True` 时调 `search_official_admission_sources(...)` 补充官方来源
- 结果结构化为 `{policy_facts, student_eligibility, source_references}`
- 只读操作，`next_step: "respond"`

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `answer_policy` 到 `ZhiyuanAgent`
- 已覆盖 `score_batch`、`transfer_major`、`subject_requirement`、`tuition_budget` 等只读规则域
- 已接 school profile 招生政策字段、参数可用性校验和 opt-in 官方来源检索
- 不调用旧 `admission_policy_tool` / `admission_fit_match_tool`；旧 `official_source_search_tool` 仅作为 opt-in 底层检索能力复用
- 返回 `policy_facts`、`student_eligibility`、`source_references`、`source_lookup`，并固定 `state_mutation=false`
- 限制：官方来源网页事实抽取和自动适配匹配尚未接入，后续继续扩展

#### `review_plan` — 方案审查

新增工具。替代 `planning_workflow_tool` 中的审查函数（部分 2269 行）。

```python
async def review_plan(
    ctx: RunContext[RequestContext],
    focus: Literal["full_review", "risk_only", "tier_balance", "tuition", "career_fit"] | None = None,
    generate_fix_proposals: bool = False,
    force_refresh: bool = True,
) -> str
```

**核心设计点：**

1. **审查执行**：调 `run_planning_review(session_id)` 触发后端审查
2. **结果读取**：审查完成后从 SandboxFileCache 读 `plan/review.json`，包含风险项列表
3. **Focus 过滤**：按 `focus` 参数筛选审查结果中的相关项
4. **修复建议**：如果 `generate_fix_proposals=True`，调 `generate_planning_fix_proposals(session_id)` 获取建议，只读展示，不自动应用
5. **结果结构化**：

```json
{
  "data": {
    "issues": [
      {"code": "HIGH_TUITION_RISK", "severity": "risk", "affected_count": 3, "summary": "3个志愿年学费超2万"}
    ],
    "fix_proposals": [...],
    "tier_balance": {"冲": 12, "稳": 18, "保": 15, "assessment": "梯度合理"}
  },
  "next_step": "respond",
  "message": "审查发现2项风险：高收费风险涉及3个志愿，梯度断层涉及保底区间。需要处理哪一项？"
}
```

**Phase 2 第三批首版落地状态（2026-06-30）：**
- 已注册 `review_plan` 到 `ZhiyuanAgent`
- 默认调用 `run_planning_review(...)` 执行后端审查；后端不可用时降级读取 `plan/review.json`
- 支持 `focus` 过滤风险、梯度、学费和职业适配相关 issues
- 支持 `generate_fix_proposals=True` 只读返回处理方向，不自动生成或应用方案变更
- 无正式方案时不调用审查接口，直接返回只读防护
- 返回 `summary`、`issues`、`tier_balance`、`fix_proposals`，并固定 `state_mutation=false`、`plan_mutation=false`
- 与 `preview_plan_action` 的边界已收紧：只读审查问题走 `review_plan`；用户明确要求移出、删除、替换或处理审查项时走 `preview_plan_action(review_issue_code=...)`
- 限制：候选自动选择质量评估和更多 service shadow case 仍需扩展

- 只读操作，`next_step: "respond"`
- 如果用户明确要求方案变更（如"移除高收费志愿"），由 Agent 直接调 `preview_plan_action` 发起待确认预览；`review_plan` 不作为变更处理终点

### 3.4 工具实现顺序

按依赖关系和验证价值排序：

```
第一批（基础 + 核心查询）：
  read_state 升级（接入 SandboxFileCache）
  query_plan 升级（真实方案扫描）
  confirm_pending（确认流程闭环）

第二批（分析 + 变更）：
  explore_topic 升级（真实后端数据）
  preview_intent_change 升级（方案影响 + pending）
  compare_entities（新增）

第三批（方案操作 + 辅助）：
  preview_plan_action（新增，最复杂）
  review_plan（新增）
  answer_policy（新增）
```

### 3.5 属性注册表与通用查询引擎

#### 问题：5 处分散的属性处理

当前系统中"属性/标签"维度的别名归一、过滤匹配、约束映射分散在 5 处，各自硬编码：

| 机制 | 位置 | 硬编码内容 |
|------|------|-----------|
| 办学性质别名 | `intent_entity_profile_tool._SCHOOL_NATURE_ALIASES` | 公办/公立/民办/私立 → 标准值 |
| 特殊限制别名 | `intent_entity_profile_tool._SPECIAL_LIMIT_ALIASES` | 高收费/高学费/中外合作/合作办学 → 标准值 |
| 方案查询过滤 | `plan_query_tool._matches_structured_filters` | schoolNature/schoolCategory/schoolLevel/tier 等字段逐一拼 haystack |
| 约束 scope 类型 | `plan_orchestration_models.PlanEntityResolution` | entity_type 枚举 major/school/region/career/tag/risk/program_type |
| 审查 issue 别名 | `review_issue_registry` | HIGH_TUITION_RISK/cooperative 等 code alias |

**后果：** 新增一个属性维度（如"中外合作"筛选、"双一流"标签查询）需要在 3-5 个文件里各加一套别名映射和匹配逻辑。

#### 设计：数据驱动的属性注册表

在 `app/domain/attribute_registry.py` 定义一份注册表，所有工具共享：

```python
@dataclass(frozen=True)
class AttributeDimension:
    key: str                              # 唯一标识，如 "school_nature"
    label: str                            # 用户可见标签，如 "办学性质"
    type: Literal["enum", "numeric", "tag_set"]
    item_fields: list[str]                # 对应 plan item JSON 字段路径
    values: list[str] | None              # enum 类型的合法值列表
    aliases: dict[str, str]               # 用户表达 → 标准值映射
    supports: set[str]                    # 该维度支持的操作集合

ATTRIBUTE_REGISTRY: dict[str, AttributeDimension] = {
    "school_nature": AttributeDimension(
        key="school_nature",
        label="办学性质",
        type="enum",
        item_fields=["schoolNature"],
        values=["公办", "民办"],
        aliases={
            "公立": "公办", "公办院校": "公办", "公立学校": "公办",
            "私立": "民办", "民办院校": "民办", "私立学校": "民办",
        },
        supports={"query", "exclude", "only_keep"},
    ),
    "program_type": AttributeDimension(
        key="program_type",
        label="招生类型",
        type="enum",
        item_fields=["enrollmentType"],
        values=["普通类", "中外合作", "高收费"],
        aliases={
            "合作办学": "中外合作", "中外合作办学": "中外合作", "国际项目": "中外合作",
            "高学费": "高收费", "学费高": "高收费",
        },
        supports={"query", "exclude"},
    ),
    "school_level": AttributeDimension(
        key="school_level",
        label="院校层次",
        type="tag_set",
        item_fields=["schoolLevel", "schoolRankTags"],
        values=["985", "211", "双一流", "一本", "二本"],
        aliases={"985院校": "985", "211院校": "211", "双一流院校": "双一流"},
        supports={"query", "only_keep"},
    ),
    "tier": AttributeDimension(
        key="tier",
        label="梯度",
        type="enum",
        item_fields=["tier"],
        values=["冲", "稳", "保"],
        aliases={"冲刺": "冲", "稳妥": "稳", "保底": "保"},
        supports={"query"},
    ),
    "tuition": AttributeDimension(
        key="tuition",
        label="学费",
        type="numeric",
        item_fields=["tuitionPerYear"],
        values=None,
        aliases={},
        supports={"query", "exclude"},
    ),
    "province": AttributeDimension(
        key="province",
        label="院校省份",
        type="enum",
        item_fields=["provinceName"],
        values=None,  # 31省自动枚举
        aliases={},
        supports={"query", "only_keep", "exclude"},
    ),
    "major_category": AttributeDimension(
        key="major_category",
        label="专业门类",
        type="tag_set",
        item_fields=["majorCategory", "majorDiscipline"],
        values=None,  # 从静态数据加载
        aliases={},
        supports={"query", "exclude", "only_keep"},
    ),
    "school_category": AttributeDimension(
        key="school_category",
        label="院校类型",
        type="enum",
        item_fields=["schoolCategory"],
        values=["综合", "理工", "师范", "财经", "医药", "农林", "政法", "语言", "艺术", "体育", "民族", "军事"],
        aliases={"工科院校": "理工", "师范院校": "师范"},
        supports={"query", "only_keep"},
    ),
}
```

#### 通用方法

注册表提供 3 个共享方法，替代各工具内部的硬编码逻辑：

```python
def normalize_attribute(key: str, user_text: str) -> str | None:
    """将用户表达归一化到标准值。走 aliases → fuzzy match → None。"""

def build_item_haystack(key: str, item: dict) -> list[str]:
    """从 plan item 中提取该属性维度的 haystack（用于过滤匹配）。"""

def match_item(key: str, item: dict, target_values: list[str]) -> bool:
    """判断 plan item 是否匹配给定属性值。numeric 类型支持范围。"""
```

#### 各工具如何消费注册表

| 工具 | 消费方式 |
|------|---------|
| `query_plan` | `_matches_structured_filters` 改为遍历 `ATTRIBUTE_REGISTRY`，用 `build_item_haystack` + `match_item` 替代逐字段拼 haystack |
| `preview_intent_change` | 约束创建时，用 `normalize_attribute` 归一化用户输入；`supports` 字段决定该维度是否允许当前 `constraint_type` 操作 |
| `preview_plan_action` | 属性/标签 filters 走 `ATTRIBUTE_REGISTRY`；`review_issue_code` 别名和后端 code 归一走共享 `review_issue_registry.normalize_review_issue_code` |
| `review_plan` | 按 `focus` 过滤审查结果；issue code/alias 统一走共享 `review_issue_registry`，不在工具内另建别名表 |
| `prompt` | 工具调用示例中的 `filters` 参数值从注册表生成，保持一致 |

#### supports 字段与 intent 操作的关系

`supports` 集合区分两类操作：

- **用户交互操作**（`query`, `exclude`, `only_keep`, `must_have`）：暴露给用户对话界面，用户可以通过自然语言表达
- **系统内部操作**（`prefer`, `acceptable`, `deprioritize`）：**当前不定义**，后续从系统隐性角度运行时再扩展

当前阶段，`supports` 只包含用户交互操作。注册表不承载软性推荐系数逻辑。

#### 实施路径

1. 先创建 `app/domain/attribute_registry.py`，定义注册表数据结构和 3 个通用方法
2. `query_plan` 的 `_matches_structured_filters` 改走注册表（影响范围最大，收益最高）
3. `preview_intent_change` 的约束归一化改走注册表
4. 旧工具中的 `_SCHOOL_NATURE_ALIASES`、`_SPECIAL_LIMIT_ALIASES` 保留到生产切换后删除

> 当前落地状态：`query_plan`、`preview_plan_action(remove, filters=...)`、`preview_intent_change` 已接入 `attribute_registry`。`preview_plan_action(remove, filters=...)` 已覆盖 `school_nature`、`program_type`、`school_category`、`school_level` 等属性定位，无命中时不创建 pending。`preview_intent_change` 会保留结构化 selector，并在确认执行时将属性 selector 编码为现有后端可接受的 hard scope（如 `院校性质:民办`、`招生类型:中外合作`）。`zhiyuan-server` hard constraint 过滤链路已支持这些 scope，避免确认后的候选/修复方案重新纳入被排除属性。`review_issue_code` 归一化已收敛到共享 `app/tools/review_issue_registry.py`，新 agent 不再维护独立 issue alias 大表。

### 3.6 Intent 约束简化：仅保留强筛选

#### 设计原则

用户在对话中表达的意向大部分是确定性的（"不要民办"、"只看公办"、"必须有计算机"），不涉及推荐系数的微调。因此：

- **用户对话交互只暴露硬约束操作**：`exclude`（排除）、`only_keep`（仅保留）、`must_have`（必须有）
- **软性推荐系数调整不暴露给用户交互界面**：当前不定义 `preference`/`preferred`/`acceptable`/`exclude_soft` 等强度级别。后续从系统隐性角度（基于用户行为推断、方案优化算法）运行
- **旧系统的强度检测逻辑（`_school_nature_strength_from_text` 中的 preferred/acceptable/exclude_soft/exclude_hard 四档）在新工具中不复用**

#### `preview_intent_change` 签名调整

```python
ConstraintType = Literal["exclude", "only_keep", "must_have"]

async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: Literal["major", "school", "region", "career"],
    positive: dict[str, Any] | None = None,
    negative: dict[str, Any] | None = None,
    constraint_type: Literal["exclude", "only_keep", "must_have"] = "exclude",
) -> str
```

变更点：
- `constraint_type` 从 `Literal["preference", "only_keep", "must_have", "exclude"]` 改为 `Literal["exclude", "only_keep", "must_have"]`
- 默认值从 `"preference"` 改为 `"exclude"`（最常见的硬约束场景）
- 移除 `preference` 选项——用户不再通过此工具设置软偏好

#### 约束操作语义

| constraint_type | 语义 | 用户表达示例 | 方案影响 |
|----------------|------|------------|---------|
| `exclude` | 排除匹配项，不出现在方案中 | "不要民办"、"排除医学" | 移除已有匹配项，后续生成不再包含 |
| `only_keep` | 仅保留匹配项，移除不匹配项 | "只看公办"、"只保留计算机相关" | 移除不匹配项，缩小范围 |
| `must_have` | 方案中必须包含至少 N 个匹配项 | "必须有计算机"、"至少保留3个广东" | 不足时从候选池补充 |

#### Prompt 行动原则调整

原第 5 条：
> 极性判断必须在调用工具前完成："不要X" 是 negative；"排除X" 是 negative；"不要排除X/不排除X/别把X排除" 是 positive；"只保留X" 是 positive 且 constraint_type=only_keep。

调整为：
> 极性判断必须在调用工具前完成："不要X"/"排除X" 是 negative + constraint_type=exclude；"不要排除X/不排除X/别把X排除" 不能写成 negative，当前按 positive 显式要处理；"只看X/只保留X" 是 positive + constraint_type=only_keep；"必须有X/至少要有X" 是 positive + constraint_type=must_have。纯撤回既有排除但不要求必须包含，需要后续补充独立 allow/unexclude 操作。

#### 工具调用示例调整

```
- "不要医学类" -> preview_intent_change(intent_type="major", negative={"level1":["医学"]}, constraint_type="exclude")
- "不要排除经济学类" -> preview_intent_change(intent_type="major", positive={"level2":["经济学类"]}, constraint_type="must_have")
- "只看公办学校" -> preview_intent_change(intent_type="school", positive={"school_nature":"公办"}, constraint_type="only_keep")
- "不要民办" -> preview_intent_change(intent_type="school", negative={"school_nature":"民办"}, constraint_type="exclude")
- "必须有计算机类" -> preview_intent_change(intent_type="major", positive={"level1":["工学"], "level2":["计算机类"]}, constraint_type="must_have")
```

注意：原示例中 `constraint_type="preference"` 的用法全部移除。"不要排除经济学类" 当前不再作为软偏好处理，也不能落到 negative；在仅支持 `exclude/only_keep/must_have` 的阶段先按 positive `must_have` 处理。若后续需要表达“解除排除但不强制包含”，需要新增独立 allow/unexclude 操作。

#### 对 G-case 的影响

| Case | 原预期 | 调整后 |
|------|--------|--------|
| G4 偏好强度 | `constraint_type="preference"` + strength 四档 | 改为 `constraint_type` 三档之一（exclude/only_keep/must_have），不再测试强度级别 |
| G8 软偏好不应走方案变更 | 预期 `preview_intent_change` + preference | 简化：用户软性表达走 `explore_topic`（分析建议），硬性约束走 `preview_intent_change`。软偏好不再产生 intent pending |
| G29 软偏好强度校准 | 测试 preferred/acceptable 校准 | 移除或重新定义：强度校准不再暴露给用户对话。如用户说"尽量考虑X"，Agent 回复建议而非创建约束 |

### 3.7 约束即方案调整：有方案时的约束语义

#### 核心问题

用户在有方案的场景下说"不要民办""只想看公办"等表达时，是在对着当前方案沟通，期望的是**方案立即调整**，而不仅仅是记录一条对当前方案没有影响的"未来意向"。

当前实现的 gap：
- `preview_intent_change` 预览阶段已通过 `simulate_plan_diff` 展示方案影响（正确）
- 但 `confirm_pending` 对 `intent_change` 的执行（`_apply_intent_pending`，`tools.py:3327`）只写入约束（`update_planning_constraint_state`），**不触发方案再生成**
- 确认后消息是"已采纳这次报考要求，后续方案会按新的硬性要求处理"——暗示约束在下次方案重新生成时才生效，当前方案不变
- 用户预期：确认后方案应该已经调整好了

#### 设计原则：约束 = 持久记录 + 即时方案调整

| 场景 | 用户表达 | 约束记录 | 方案调整 |
|------|---------|---------|---------|
| **无方案** | "不要民办" | 写入 constraints → 后续生成方案时生效 | 无方案可调 |
| **有方案** | "不要民办" | 写入 constraints → 持久生效 | **立即再生成方案**，移除不符合约束的项 |
| **有方案** | "方案里的民办不要了" | 不自动推断为长期要求 | 按当前方案调整预览处理 |

关键点：裸属性诉求，或明确表达后续报考要求时，走 `preview_intent_change`；口语里的"民办就算了""中外合作别考虑了""公办以外不用看"也属于显式要/不要。只有用户用"方案里/当前方案/当前这些/里面这些/这批/这些/这几个"锚定当前方案，并明确说移出、删除、去掉、不要了，才按当前方案调整处理，调用 `preview_plan_action(remove, filters=...)`。不要在没有当前方案锚点时把裸属性诉求改判成一次性方案调整。

#### 路由判断：属性级 vs 具体项

正确的路由区分是"报考要求 vs 当前方案调整 vs 具体项操作"：

| 操作类型 | 特征 | 示例 | 路由 |
|---------|------|------|------|
| **报考要求** | 裸属性/标签/类别诉求，或明确表示以后也要遵循；包含"算了/别考虑/不用看"等口语否定 | "不要民办""民办就算了""只看公办""中外合作不考虑" | `preview_intent_change` |
| **当前方案筛选调整** | 属性/标签/类别 + 当前方案锚点 + 移出/删除/去掉/不要了 | "方案里的民办不要了""当前这些中外合作都移出去" | `preview_plan_action(remove, filters=...)` |
| **具体项** | 按名称/位置/编号定位特定项 | "把华南理工大学移出去""第3个不要了""冲的第一个换掉" | `preview_plan_action` |

如果用户明确锚定当前方案，只按这次方案调整处理，不默认替用户记录长期报考要求。后续可以在确认卡或回复里提示"这次只调整当前方案；如果后续也都不考虑，可以再采纳为报考要求"。

#### `confirm_pending` 的 intent_change 执行流程调整

```python
async def _apply_intent_pending(ctx, pending) -> tuple[bool, dict, str]:
    # 1. 写入约束（已有）
    response = await update_planning_constraint_state(...)

    # 2. 新增：如果当前有方案，立即再生成
    has_plan = await _has_active_plan(ctx)
    plan_regen_result = None
    if success and has_plan:
        plan_regen_result = await internal_client.generate_planning_ordered_plan(
            tenant_id, ctx.deps.sessionid
        )

    # 3. 消息调整
    if success and has_plan and plan_regen_result:
        message = "已采纳报考要求并重新调整方案，新方案已按约束更新。"
    elif success and not has_plan:
        message = "已记录报考要求，后续生成方案时会遵循该约束。"
    else:
        message = "报考要求写入未成功，请重新生成预览后再确认。"
```

**失效路径调整**（`_invalidate_after_pending_action`）：
- `intent_change` + 有方案 → 失效 `constraints.json` + 所有 `plan/*` + `pending.json`（已有）
- 方案再生成后 sandbox 自动在下次读取时拉取最新方案

**preview 消息调整**：
- 有方案时：`"排除民办后，当前方案有5个志愿受影响（冲1/稳2/保2）。确认后将记录约束并重新调整方案。"`
- 无方案时：`"已记录排除民办的约束，后续生成方案时将不包含民办院校。确认即可。"`

#### Prompt 路由指引补充

在行动原则中增加属性级 vs 具体项的路由判断（现有第 5 条极性规则之后）：

> 用户按属性/标签/类别表达显式报考要求（办学性质、招生类型、专业门类等）时，走 preview_intent_change；用户用"方案里/当前这些/这批"锚定当前方案并要求移出、删除、去掉、不要了时，走 preview_plan_action(remove, filters=...)。只有用户明确要求后续都遵循时，才记录为报考要求。

---

## 4. 非阻塞 Shadow 模式

### 4.1 当前问题

PoC shadow 早期在 `_maybe_run_zhiyuan_agent_poc_shadow` 中阻塞执行，位于主链路 guard pipeline 之前。shadow 耗时 1.2-2.8s 会直接叠加到用户感知延迟。

**Phase 2 第一批落地状态（2026-06-30）：**
- `_maybe_run_zhiyuan_agent_poc_shadow(...)` 已改为只创建独立 shadow context 并启动后台 `asyncio.Task`
- 主链路不等待 shadow；turn event 中如任务未完成则记录 `status=running`
- shadow 完成后独立写 `zhiyuan_agent_poc_shadow_event`
- `_observability_timing_fields(...)` 会在 turn event 发送前尝试读取已完成 task 的结果
- 已新增 `ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE`，默认 `1.0`

### 4.2 设计方案

```python
async def _maybe_run_zhiyuan_agent_poc_shadow(self, request_context: RequestContext) -> None:
    if not self._zhiyuan_agent_shadow_enabled:
        return
    if not self._should_sample():   # 采样率控制
        return

    # 非阻塞启动
    shadow_context = request_context.replace(...)  # 副本
    task = asyncio.create_task(
        self._run_zhiyuan_agent_shadow(shadow_context, request_context)
    )
    # 注册到 request_context，在 turn event 发送前收集结果
    request_context._shadow_task = task
```

**结果收集时序：**
```
主链路:  context构建 → shadow启动(非阻塞) → guard → agent循环 → 输出处理
                         ↓                                        ↓
shadow:              ZhiyuanAgent.run  ──────────────────→  结果写入
                                                              ↓
observability:                                    turn_event 发送前 await shadow_task（带超时）
```

### 4.3 核心设计点

| 要素 | 设计 |
|------|------|
| 采样率 | `ZHIYUAN_AGENT_SHADOW_SAMPLE_RATE=1.0`（离线评估 100%，线上可降到 0.1） |
| 超时 | `ZHIYUAN_AGENT_SHADOW_TIMEOUT_SECONDS=15`，超时后丢弃，不影响主链路 |
| 结果收集 | turn event 发送前检查已完成 task；来不及则保留 `status: "running"`，完整结果走独立 shadow event |
| 错误隔离 | shadow 内部异常不传播到主链路，仅记录到 observability |
| 资源隔离 | shadow 使用 `RequestContext.replace()` 副本，不共享主链路的 SandboxFileCache 实例 |

---

## 5. Phase 3: Shadow Diff 大规模验证

### 5.1 Case 集合扩展

当前 shadow case 集合：5 个 PoC 设计场景。

目标：覆盖 G1-G32 中与当前工具能力匹配的 case。现有 `dialog_regression_320_g1_g32_shadow_cases.json` 已有 21 个 case 定义（G1-G32 中的 21 个），每个 case 有 `fixtureContract`（所需后端状态）、`planningStateProfile`（场景前置条件）、`prompts`（多轮对话 + 断言）。

**Case 与 9 工具的映射分析：**

| Case | 用户意图 | 预期工具 | 当前工具覆盖 |
|------|---------|---------|------------|
| G1 排除英语专业 | intent 变更 + 方案影响 | `preview_intent_change` + `confirm_pending` | Phase 2 第一批 |
| G2 审查修复预览边界 | 审查 + 修复建议 | `review_plan` | Phase 2 第三批 |
| G3 pending 中的只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G4 偏好强度 | 约束设置 | `preview_intent_change` | Phase 2 第一批（约束简化后仅硬约束，不再测试强度级别） |
| G7 预算只读 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G8 软偏好不应走方案变更 | 偏好 vs 方案边界 | 软性表达走 `explore_topic`；硬约束走 `preview_intent_change` | Phase 2 第一批（软偏好不再产生 intent pending） |
| G10 无 pending 时确认 | 边界防护 | `confirm_pending` | Phase 2 第一批 |
| G16 方案固定/锁定 | 方案操作 | `preview_plan_action` | Phase 2 第三批 |
| G17 梯度内重排 | 方案操作 | `preview_plan_action` | Phase 2 第三批 |
| G19 无方案时引用方案 | 防护 | `query_plan` | Phase 2 第一批 |
| G21 只读审查不应自动生成 | 审查边界 | `review_plan` | Phase 2 第三批 |
| G22 school pending 中的只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G23 地域维度不应识别为专业 | 实体分类 | `preview_intent_change` | Phase 2 第一批 |
| G25 混合正负极性 | 极性处理 | `preview_intent_change` | Phase 2 第一批 |
| G26 方案投影切片查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G27 学费只读 + 候选观察 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G29 软偏好强度校准 | 约束/建议边界 | 软性表达走 `explore_topic`；硬约束走 `preview_intent_change` | Phase 2 第一批（强度校准不再暴露给用户对话） |
| G30 特殊招生路径保留 | 显式意向 + 招生类型 selector | `preview_intent_change` | Phase 2 第一批/第三批联动（`program_type=强基` 已落地） |
| G31 pending 不阻塞只读查询 | 方案查询 | `query_plan` | Phase 2 第一批 |
| G32 无方案引用方案防御 | 防护 | `query_plan` | Phase 2 第一批 |
| G12 延迟分解 | 性能观测 | 不涉及工具选择 | — |

**Phase 2 第一批完成后可跑的 case：** G1, G3, G4, G7, G8, G10, G19, G22, G23, G25, G26, G27, G29, G31, G32（15 个）
**Phase 2 第三批完成后补充：** G2, G16, G17, G21, G30（5 个）

### 5.2 Confusion Matrix 设计

对比主链路实际行为与 ZhiyuanAgent 的工具选择，识别方向差异和正确性差异。

**维度定义：**

| 维度 | 主链路数据源 | ZhiyuanAgent 数据源 |
|------|-----------|-------------------|
| 路由方向 | `routingPath`（`full_agent` / `runtime_intent_hard_cut` / `fast_route_*`） | `firstToolNames[0]`（映射到方向类别） |
| 工具选择 | `toolCallNames`（如 `preview_current_major_intent_confirmation`） | `toolCallNames`（如 `preview_intent_change`） |
| 结果类型 | `resultKind`（`text` / `pendingConfirmationCard` / ...） | `nextSteps[0]`（`respond` / `confirm` / `clarify`） |

**工具名映射表（旧 → 新方向类别）：**

```
preview_current_major_intent_confirmation  → intent_change
preview_current_school_intent_confirmation → intent_change
preview_current_city_intent_confirmation   → intent_change
analyze_current_career_direction           → explore
analyze_current_major_interest             → explore
analyze_current_region_interest            → explore
query_volunteer_plan                       → plan_query
collect_plan_context_inputs                → plan_query
execute_plan_action                        → plan_action
compare_majors / compare_schools           → compare
answer_admission_policy_question           → policy
```

**报告输出格式：**

```json
{
  "total": 50,
  "agreement": {
    "direction_match": 42,
    "direction_match_rate": 0.84
  },
  "confusion_matrix": {
    "intent_change": {"intent_change": 10, "explore": 1, "plan_query": 0},
    "explore":       {"intent_change": 0,  "explore": 8, "plan_query": 1},
    "plan_query":    {"intent_change": 0,  "explore": 0, "plan_query": 12}
  },
  "disagreements": [
    {
      "case": "G8-soft-preference",
      "main_direction": "plan_action",
      "zhiyuan_direction": "explore",
      "main_correct": false,
      "zhiyuan_correct": true,
      "reason": "主链路将软偏好误路由到方案变更；新系统中软偏好走 explore_topic 分析建议"
    }
  ]
}
```

---

## 6. Phase 4: 生产切换要点

### 6.1 功能开关

```python
# 会话级开关
ZHIYUAN_AGENT_ENABLED=false          # 默认关闭
ZHIYUAN_AGENT_ROLLOUT_PERCENT=0      # 渐进放量百分比（0-100）
```

开关判断顺序：
1. 会话级 `ZHIYUAN_AGENT_ENABLED=true` → 强制使用新系统
2. `ZHIYUAN_AGENT_ROLLOUT_PERCENT` → 按 session_id hash 决定
3. 都未命中 → 使用旧系统

direct route 接管原则：

- 不增加基于用户原文字符串匹配的前置语义闸门。
- 是否接管只由功能开关/rollout、当前是否存在 active pending、4.0 agent 的结构化工具返回决定。
- `next_step=confirm` 且后端已创建 active pending 时，由 service 构造确认卡；没有确认前不改动报考要求或方案。
- 已存在 active pending 的会话继续走统一 pending 确认流程，由 `confirm_pending` 执行确认/取消。

### 6.2 渐进放量

```
Week 1:  1% （约 50-100 会话/天）→ 观察核心指标
Week 2:  5% → 确认无回归后提速
Week 3: 20% → 覆盖更多场景类型
Week 4: 50% → 大规模验证
Week 5: 100% → 全量切换
```

### 6.3 核心监控指标

| 指标 | 告警阈值 | 说明 |
|------|---------|------|
| 工具调用成功率 | < 95% | 后端 API 调用失败 |
| 平均工具调用次数/轮 | > 3 | 退化为乱试 |
| P95 延迟 | > 当前基线 × 1.2 | 性能退化 |
| Pending 确认成功率 | < 90% | 版本冲突过多 |
| 用户满意度（显式反馈） | 下降 > 5% | 回复质量退化 |

### 6.4 可删除代码（全量切换稳定后）

| 文件 | 行数 | 说明 |
|------|------|------|
| `app/tools/` 目录（37个文件） | ~28,000 | 旧工具实现 |
| `app/domain/proposal_compiler.py` | 5,650 | 规则引擎 |
| `app/tools/turn_decision_tool.py` | 514 | 预路由分类器 |
| `app/agent/instructions/tool_dispatch_rules.py` | 117 | 路由规则 |
| `app/agent/tool_reply_policy.py` | 396 | 外部终止判断 |
| service.py 中的旧编排逻辑 | ~15,000 | 单体编排层 |
| **合计** | **~50,000** | |

**保留的代码：**
- `app/domain/` 中的实体解析器（已被新工具直接引用）
- `app/util/internal_client.py`（后端 HTTP 客户端）
- `app/data/`（静态数据文件）
- `app/sync/state_sync.py`（适配到 SandboxFileCache）
- `app/agent/base_agent.py`（ZhiyuanAgent 基类）

---

## 7. 实施检查清单

### Phase 1 检查项
- [x] SandboxFileCache 基本读写 + 版本失效
- [x] BackendAdapter 8 个路径映射
- [x] Cache warming（4 路径并行预取）
- [x] ZhiyuanAgent 的 deps 从直读改为 sandbox 读取
- [x] 单元测试：cache hit/miss/invalidate/warm

### Phase 2 第一批检查项
- [x] read_state 接入 SandboxFileCache
- [x] query_plan 真实方案扫描 + filters
- [x] 属性注册表首版创建，并接入 query_plan filters
- [x] confirm_pending 完整确认/取消流程 + 版本守护
- [x] 非阻塞 shadow 模式
- [x] plan item enrichment：ordered-plan items 按 volunteerId 从候选池合并属性字段（§8.1）
- [x] shadow 采集闭环：runner 合并后置 shadow event（§8.2）
- [x] confirm intent_change 有方案时触发方案再生成（§3.7）
- [ ] G1/G3/G7/G10/G19/G22/G31/G32 shadow case 通过

### Phase 2 第二批检查项
- [x] explore_topic 接入 `get_major_profile` / `get_school_profile_by_name`
- [x] preview_intent_change pending 创建（结构化 `pendingConfirmation`）
- [x] preview_intent_change 接入 `simulate_plan_diff`
- [x] preview_intent_change 移除用户交互层软偏好，统一写硬约束 `intentMode=constraint`
- [x] preview_intent_change 接入属性注册表，支持属性/标签 selector
- [x] Java hard constraint 过滤支持属性 scope（院校性质、招生类型、院校类型、院校层次、专业标签等）
- [x] 真实 LLM selection 覆盖属性 selector：不要民办、只看公办、不要中外合作、不要师范类院校
- [x] compare_entities 新工具
- [ ] G4/G8/G23/G25/G26/G27/G29 shadow case 通过（G4/G8/G29 需按约束简化后重新定义）

### Phase 2 第三批检查项
- [x] preview_plan_action 新工具（7 种 action）
- [x] preview_plan_action(remove) 支持 filters 按属性/标签定位当前方案项
- [x] preview_plan_action(remove filters) 覆盖中外合作、院校类型、院校层次及无命中不创建 pending
- [x] preview_plan_action(remove review_issue_code + filters) 支持审查问题范围与属性 filters 求交集
- [x] preview_plan_action 支持位置范围、档位内序号和 G17 档位内局部重排 selector
- [x] preview_plan_action 扩展后端核心 review issue：限报/特殊招生 item 删除预览，录取率倒挂/保底不足结构排序或重排预览
- [x] G16 锁定/固定位置受控 unsupported，不创建 pending、不误走 move
- [x] G30 强基路径作为 `program_type=强基` selector 保留
- [x] review_plan 新工具
- [x] answer_policy 新工具
- [x] G2/G21 真实 LLM 工具选择边界通过（只读处理方向/合理性查询不自动生成或修改方案）
- [ ] G2/G21 完整 service shadow case 通过

### Phase 3 检查项
- [x] 全量 G1-G32 完整回归首轮（49步/46通过/3失败：G4/G17/G25）
- [x] §9.1 复合诉求 next_step 策略调整（respond 软停已落地）
- [x] §9.2 pending 下只读查询路由放开（G21/G27 性能修复已落地）
- [x] §9.3 正向意向边界 prompt 调整（"想学X" → must_have 已落地）
- [x] §9.4 direct route 入口增加成绩可用性前置检查（已落地）
- [x] §9.5 G17 selector 归一化三层防护（已落地，direct 已通过，LLM 可靠性为观察项）
- [x] §9.6 G4 实体归一化展示保真（display_aliases 已落地）
- [x] §9.7 G3 查询计数粒度口径（志愿为主粒度已落地）
- [x] §9.8 G32 无方案探索降级内容策略（维度模板已落地）
- [ ] §9.9 G25 路由抢跑排障（确认 direct route 可命中 G25）
- [ ] §9.9 G25 schema alias 兼容（major_name → level2 fallback）
- [ ] §9.9 G25 混合正负 Prompt 加固（positive+negative 同传示例）
- [ ] §9.10 respond 软停真实 LLM 效果验证（G12 复合诉求 + 单意图不多调）
- [ ] §9.12 阶段 D 完整 G1-G32 direct 回归 × 2 次（通过率 ≥ 43/49）
- [ ] 全量 G1-G32 case 通过（≥20/21）
- [ ] Confusion matrix 报告生成
- [ ] 320+ 历史回归 case 跑新系统（方向一致率 > 85%）
- [ ] 性能基线：P95 延迟 < 8s

### Phase 4 检查项
- [x] 功能开关 + 放量逻辑
- [x] direct route 接入 service 主流程，默认关闭
- [x] direct route 移除字符串 precheck，按结构化工具返回和 active pending 状态接管
- [x] direct route 真实口语集合、G case 子集、确认执行闭环首轮验证通过
- [x] 确认执行闭环覆盖最终后端 action 断言：pending applied、planningState version 增长、方案项/报考要求真实变化
- [x] direct-only 真实口语集合复跑 14/14，通过口语/指代/省略 case，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json`
- [x] direct 确认执行闭环复跑 4/4，确认后端方案项删除和报考要求写入真实生效，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json`
- [x] G case direct 子集 direct-only 复跑 8/8；shadow 关闭时原始 shadow 断言失败不计入 direct 主链路失败，metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json`
- [x] 完整 320 G1-G32 direct 复跑 44/49，问题已归档，metrics: `/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json`
- [ ] 监控仪表盘
- [ ] 回滚流程验证
- [ ] 1% → 100% 渐进放量
- [ ] 旧代码清理（~50K 行）

---

## 8. 真实口语验证问题清单（2026-07-01）

真实多轮对话验证中发现的问题。按优先级排列，每项包含根因分析和修复方案。

### 8.1 P0 — plan/items.json 数据契约已补齐

**现象：**
`plan/items.json`（来源 `get_planning_ordered_plan` 的 `orderedPlanState.items`）每个 item 只有 `position`、`volunteerId`、`tier`、`schoolName`、`majorName`、`provinceName` 等基础定位字段，**不包含** `schoolNature`、`schoolCategory`、`tuitionPerYear`、`enrollmentType`（招生类型）、`reasonCodes`（审查原因码）等属性字段。

**影响：**
- `query_plan(filters={"school_nature":"民办"})` 在真实数据上可以命中
- `preview_plan_action(action="remove", filters={"school_nature":"民办"})` 和 `preview_plan_action(action="remove", filters={"program_type":"中外合作"})` 可以命中
- `_plan_item_brief()`（`tools.py:2359`）能读到 `schoolNature`/`tuitionPerYear`
- 属性注册表（§3.5）的 `build_item_haystack` 可直接用于真实方案项
- 真实用户说"方案里有没有民办"时，工具返回正确的命中结果

**实现：**
`sandbox.py` 的 `_ordered_items_file_from_response` 已按 `volunteerId` 从候选池数据合并属性字段，合并字段覆盖学校性质、学校类别、层次、学费、标签和 `reasonCodes` 等。合并策略遵循 ordered item 原值优先、候选池补空字段，候选池不可用时保留原始 ordered items。

**关联代码：**
- `sandbox.py:412` `_enrich_ordered_items_from_candidates` — ordered items enrichment
- `sandbox.py:429` `_ordered_items_file_from_response` — 输出 enriched `plan/items.json`
- `tools.py:2311` `_matches_plan_item` — 使用 enrichment 后的完整字段
- `tools.py:2359` `_plan_item_brief` — 使用 enrichment 后的 `schoolNature`/`tuitionPerYear`

**真实验证：**
- `里面有民办没`：`query_plan(scope="plan", filters={"school_nature":"民办"})` 真实命中 `70` 条
- `方案里的民办不要了`：`preview_plan_action(remove, filters={"school_nature":["民办"]})` 真实返回确认卡
- `当前这些中外合作都移出去`：4.0 shadow 真实返回 `preview_plan_action(remove, filters={"program_type":["中外合作"]})`

**文档状态：** §3.3 `query_plan` 和 `preview_plan_action` 的 `filters` 描述已升级为真实数据可用；不再保留“仅单测 fixture 下支持”的旧表述。

### 8.2 P0 — Shadow 采集闭环已打通

**现象：**
非阻塞 shadow 在快速主链路下，`conversation_turn_event` 发送时 shadow task 尚未完成，只留下 `status=running`。完整结果通过独立的 `zhiyuan_agent_poc_shadow_event` 写入日志。

但 `dialog_regression_runner` 只从 history 消息的 `conversation_turn_event` 中读取 `zhiyuanAgentPocShadow` 字段（`runner.py:1060-1062`），不合并后置的 shadow event，导致：
- shadow 实际成功（正确选了 `preview_intent_change`），但 runner 判定"no shadow result"
- "那高收费的别要了" 等 case 无法正确评估 4.0 的工具选择质量
- shadow 覆盖率统计偏低

**根因：**
`_observability_timing_fields`（`service.py:5003`）在 turn event 发送时检查 shadow task 是否 `done()`——如果 shadow 还在跑，不等待，直接发不带 shadow 的 turn event。shadow 完成后 `_log_zhiyuan_agent_poc_shadow_event`（`service.py:13196`）写独立日志事件，但 runner 不解析这个事件类型。

**修复方案（两步）：**

**步骤 1 — runner 合并后置 shadow event（快速修复）：**

在 `_extract_turn_observability`（`runner.py:1046` 附近）增加对后置 shadow event 的解析：

```python
# 现有逻辑：从 conversation_turn_event 中读 zhiyuanAgentPocShadow
if kind == "text":
    data = _parse_json_object(part.get("content"))
    if data.get("event") == "conversation_turn_event":
        raw_poc_shadow = data.get("zhiyuanAgentPocShadow")
        if isinstance(raw_poc_shadow, dict):
            zhiyuan_agent_poc_shadow = raw_poc_shadow

    # 新增：合并独立 shadow event
    if data.get("event") == "zhiyuan_agent_poc_shadow_event":
        shadow_data = data.get("shadow") or data
        if isinstance(shadow_data, dict) and shadow_data.get("status"):
            zhiyuan_agent_poc_shadow = shadow_data
```

**步骤 2 — turn event 等待 shadow 带超时（可选优化）：**

在 `_observability_timing_fields` 中，如果 shadow task 未完成，用短超时等待：

```python
shadow_task = getattr(request_context, "_zhiyuan_agent_poc_shadow_task", None)
if isinstance(shadow_task, asyncio.Task) and not shadow_task.done():
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(shadow_task), timeout=2.0)
```

这让大部分 shadow 结果能嵌入 turn event，减少对 runner 合并逻辑的依赖。但不能设太长超时，避免阻塞主链路。

**关联代码：**
- `service.py:5003` `_observability_timing_fields` — 可选增加短超时等待
- `service.py:13195-13196` `_run_zhiyuan_agent_poc_shadow` — shadow event 发射点
- `runner.py:1046-1062` `_extract_turn_observability` — 需要合并 shadow event

**真实验证结果：**
- 2026-07-01 real websocket shadow 复跑 `examples/dialog_regression_400_realistic_user_cases.json`，14 个 step 全部拿到完成态 `zhiyuanAgentPocShadow`
- `zhiyuanAgentPocShadow.observed=14`，`statuses.success=14`
- `runtimeShadowSummary.observations=0`，本次不依赖 runtime diff 汇总，直接从 turn observability 与后置 shadow event 合并完成

### 8.3 P1 — Case 语义边界：显式诉求优先，区分报考要求和当前方案调整

**修正后的理解：**
之前把"方案里的民办不要了"一律归到报考要求，会把隐含长期意向强加给用户。当前口径改为显式诉求优先：裸句"不要民办"更像报考要求；"方案里的民办不要了""当前这些中外合作都移出去"明确锚定当前方案，暂时按方案调整处理是合理的。

**正确的路由规则（基于操作粒度，非指代词）：**

| 操作粒度 | 示例 | 路由 | 原因 |
|---------|------|------|------|
| **报考要求**（裸属性/标签/类别或明确后续要求） | "不要民办""民办就算了""中外合作都不要了""以后别考虑民办" | `preview_intent_change` | 记录为后续报考要求，确认后按要求影响方案 |
| **当前方案筛选调整** | "方案里的民办不要了""当前这些中外合作都移出去" | `preview_plan_action(remove, filters=...)` | 用户当前最明确的诉求是调整现有方案 |
| **审查 issue 联动** | "审查里的高收费先处理了" | `preview_plan_action(review_issue_code=...)` | 从审查结果定位具体 items 操作 |
| **具体项**（名称/位置） | "把华南理工大学移出去""第3个不要了" | `preview_plan_action(action="remove")` | 一次性操作，不产生持久约束 |

**修复方案：**
1. 裸属性/标签/类别诉求 case 期望 `preview_intent_change`
2. 带当前方案锚点且要求移出/删除的属性筛选 case 期望 `preview_plan_action(remove, filters=...)`
3. 保留审查联动和具体项操作的 case 期望 `preview_plan_action`
4. 补充具体项操作 case：

```json
{
  "name": "G33-specific-item-removal",
  "prompts": [
    {"text": "把广州南方学院移出去", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]},
    {"text": "第3个不要了", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]},
    {"text": "审查里的高收费项处理掉", "expectedZhiyuanAgentPocFirstToolNames": ["preview_plan_action"]}
  ]
}
```

5. 确保 `preview_intent_change` 的 confirm 流程在有方案时触发方案再生成（§3.7 的实现要求）

### 8.4 P1 — 老链路语义 bug："先别动" 误判为 pin_or_lock_unit

**现象：**
"贵的合作的这些怎么处理，先别动" 被老链路误判为 `pin_or_lock_unit`（锁定/固定位置），把"先别动"当成了锁定操作。

**4.0 的正确路由：**
这是一个只读审查问题——用户在问"怎么处理"，然后说"先别动"表示暂不操作。应该走 `review_plan(focus="tuition", generate_fix_proposals=True)` 返回处理方向但不创建 pending。

**当前障碍：**
这个 case 在老链路上触发了错误操作，但 4.0 shadow 结果在本轮真实复跑中已可稳定采集；旧主链语义仍可保留为后续替换依据，不再作为 4.0 验证阻塞项。

**修复方案：**
1. 先修 §8.2 的 shadow 采集断链
2. 补该 case 到 shadow case 集合，断言期望 `review_plan`
3. 确认 4.0 prompt 的行动原则第 10 条（"用户问当前方案风险、审查一下...调用 review_plan"）已覆盖此场景
4. 如果 4.0 也误判，在 prompt 示例中增加：

```
- "这些高收费的怎么处理，先别动" -> review_plan(focus="tuition", generate_fix_proposals=True)
```

### 8.5 P2 — 文档与真实实现状态已对齐

**现象：**
§3.3 中 `query_plan` 和 `preview_plan_action` 的 Phase 2 落地状态之前写得偏保守，容易让人误以为真实数据仍不能命中属性过滤。

**修复方案：**

在相关工具的落地状态描述中改为已验证可用，并保留真实验证备注：

- `query_plan` 落地状态更新为：真实 ordered-plan 数据可通过 enrichment 命中 `school_nature` 等属性过滤
- `preview_plan_action` 落地状态更新为：`filters-based remove` 已在真实口语 shadow 中验证
- §7 Phase 2 检查清单中将 enrichment 和 shadow 采集闭环标为完成

### 8.6 修复优先级与依赖关系

```
P0 enrichment (§8.1) ──────────────────────────────┐
                                                    ├──→ 属性过滤在真实数据上可用
P0 shadow 采集 (§8.2) ─────────────────────────────┐│
                                                    ├──→ shadow 验证闭环
P0 约束即方案调整 (§3.7) ──────────────────────────┐││
  confirm intent_change 触发方案再生成             │││
                                                   ├┘│
P1 case 语义边界 (§8.3) ──────────────────────────┘  │
P1 老链路 bug 验证 (§8.4) ─── 作为替换依据保留 ──────┘
P2 文档修正 (§8.5) ─── 已完成，保持与真实实现一致 ───→ 更新落地状态描述
```

实施顺序：§8.1 + §3.7 → §8.2 → §8.3 + §8.4 → §8.5

---

## 9. Golden Case 回归设计调整（2026-07-02）

G1-G32 完整回归（49 步、46 通过、3 失败）暴露了若干需要设计级调整的问题。按影响分类：A 类需要新增或修改设计段落；B 类为实现级修复，在此记录结论。

### 9.1 复合诉求 `next_step` 策略调整

**触发 case：** G12 `高收费的志愿占比多少 能不能换成便宜的`

**现象：**
用户在同一句话中包含"查询 + 调整"两个意图。Agent 调用 `query_plan` 并返回 `next_step="respond"`，`should_return_directly_from_tool` 在 `respond` 时返回 True，工具结果直接返回用户，LLM 没有机会处理第二个意图（"换成便宜的"方案调整）。

**根因：**
当前 `should_return_directly_from_tool` 对 `respond`/`confirm`/`clarify` 三种 `next_step` 全部返回 True，即所有工具结果都会短路后续 LLM 处理。这对单意图场景是最优的（避免工具乱试），但对复合意图场景过于激进。

**设计调整：**

将 `next_step` 的短路行为按语义分层：

| `next_step` | 含义 | `should_return_directly` | 理由 |
|-------------|------|------------------------|------|
| `confirm` | 已创建 pending，等用户确认 | **True**（硬停） | 用户必须先处理确认卡 |
| `clarify` | 需要用户澄清，无法继续 | **True**（硬停） | 歧义未解决，继续调用无意义 |
| `respond` | 只读结果已就绪 | **False**（软停） | LLM 可判断是否还有未处理意图 |

调整后，只读工具（`query_plan`/`read_state`/`review_plan`/`answer_policy`/`explore_topic`/`compare_entities`）返回 `respond` 时，LLM 仍然可以继续处理下一个意图。`MAX_TOOL_CALLS_PER_TURN=3` 的硬上限仍然防止工具乱试。

**Prompt 指引补充：**

在行动原则中增加复合诉求处理规则：

> 用户一句话包含查询和操作两个意图时（如"方案里有几个民办 把它们去掉"），先调只读工具回答查询部分，再按操作意图调用对应工具。只读工具的结果不终止本轮处理。

**`agent.py` 调整要点：**
- `should_return_directly_from_tool`: 仅在 `next_step in ("confirm", "clarify")` 时返回 True
- `render_direct_tool_output`: 只在 `should_return_directly_from_tool` 为 True 时调用
- `respond` 时工具结果作为中间上下文注入 LLM，由 LLM 决定是直接回复还是继续调用工具

**影响范围：**
- 复合诉求可以在 1 轮内完成查询 + 操作
- 单意图场景中 LLM 在收到只读结果后大概率直接回复，不会增加不必要的工具调用
- `confirm`/`clarify` 仍然硬停，不影响 pending 安全

### 9.2 Pending 下只读查询路由

**触发 case：** G21（`万一强基没过校测普通批怎么衔接`，耗时 51651ms）、G27（`两万以上的都算贵 帮我看看有几个`，耗时 19073ms）

**现象：**
当存在 active pending 时，只读查询（策略问答、方案查询）仍然落到旧 `full_agent` 链路，走 `pending_readonly_plan_query` + 旧 `execute_plan_action`，耗时远高于 direct route。

**根因：**
Phase 4 direct route 的入口条件是"无 active pending 或用户表达为确认/取消"。当 pending 存在但用户表达不是确认/取消时，整个请求回退到旧链路。但只读查询（`answer_policy`/`query_plan`/`explore_topic`/`compare_entities`/`review_plan`）不与 pending 冲突，不需要回退。

**设计调整：**

Direct route 接管条件从"无 pending"扩展为"无 pending 或只读查询"：

```
direct route 适用条件：
  1. 无 active pending                               → 所有工具可用
  2. 有 active pending + 用户表达为确认/取消          → confirm_pending
  3. 有 active pending + 用户表达为只读查询           → 只读工具可用（新增）
  4. 有 active pending + 用户表达为新变更请求          → pending_conflict_guard（保持）
```

**条件 3 的只读工具集合：**
`read_state` / `query_plan` / `answer_policy` / `explore_topic` / `compare_entities` / `review_plan`

这些工具不创建新 pending、不修改方案、不修改约束，与已有 pending 无冲突。

**实现要点：**
- service 层 `_route_to_direct_agent` 检查 pending 存在时，仍然进入 direct route，但在工具注册时只暴露只读子集
- 或者更简单：不做工具子集限制，依赖 `preview_intent_change`/`preview_plan_action` 内部的 pending 冲突检查（已有 `pending_conflict_new_request_guard`）
- 推荐后者：保持 agent 工具集不变，冲突由工具自身守护。service 层只需放开 direct route 的 pending 检查

**预期效果：**
- G21 策略问答：从 51651ms 降到 direct route 典型延迟（3-6s）
- G27 只读方案查询：从 19073ms 降到 direct route 典型延迟

### 9.3 正向意向 `constraint_type` 边界澄清

**触发 case：** G4（`网络与新媒体作为优先方向，跨境电商也可以考虑`）、G23（`想学计算机或电子信息`、`城市优先长三角`）、G29（`网络与新媒体优先，跨境电商也可以考虑`）

**核心矛盾：**
§3.6 移除了 `preference`，只保留 `exclude/only_keep/must_have`。但用户表达的正向意向不全是"必须有"：

| 表达 | 当前设计 | 用户预期 |
|------|---------|---------|
| "要计算机" / "必须有计算机" | `positive + must_have` ✓ | 方案中确保包含 |
| "不要民办" | `negative + exclude` ✓ | 方案中排除 |
| "想学计算机" / "对计算机感兴趣" | ❓ | 记录偏好，方案适当倾斜 |
| "优先长三角" / "城市优先X" | ❓ | 记录偏好，方案适当倾斜 |
| "跨境电商也可以考虑" | ❓ | 知道了，不强制 |

**设计决策：分三层处理**

1. **明确要求 → `must_have`**：
   "要X"/"必须有X"/"至少要有X" → `positive + constraint_type="must_have"`。这是硬约束，方案必须包含匹配项。

2. **主动正向意向 → `must_have`（宽松语义）**：
   "想学X"/"对X感兴趣"/"X方向" → `positive + constraint_type="must_have"`。用户主动说出来的正向意向应当作为报考要求被记录。`must_have` 在此语境下表示"方案应当包含"，而非"强制最低数量"。

3. **弱肯定/探索 → 不创建约束**：
   "也可以考虑X"/"X也行" → 不调用 `preview_intent_change`，可用 `explore_topic` 提供参考信息。这类表达不构成报考要求，属于 §3.6 已定义的"软偏好不暴露给用户对话"范围。
   "优先X" → 如果有明确对象（"优先长三角"），按 `must_have` 记录为正向意向；如果只是排序偏好（"优先考虑便宜的"），走 `explore_topic` 或 `review_plan` 分析。

**Prompt 行动原则调整（第 5 条扩展）：**

在现有极性判断规则后追加：

> "想学X"/"想去X"/"对X感兴趣"/"X方向" 是正向报考要求，按 positive + constraint_type=must_have 处理；"也可以考虑X"/"X也行"/"不排斥X" 是弱肯定探索，不创建约束，可用 explore_topic 提供参考。

**工具调用示例补充：**

```
- "想学计算机或电子信息" -> preview_intent_change(intent_type="major", positive={"level2":["计算机类","电子信息类"]}, constraint_type="must_have")
- "城市优先长三角" -> preview_intent_change(intent_type="region", positive={"region_group":["长三角"]}, constraint_type="must_have")
- "跨境电商也可以考虑" -> explore_topic(topic_type="major", user_question="跨境电商专业怎么样")
```

**实体归一化显示问题（G4 附带）：**
"跨境电商" 被实体解析器归一为 "电子商务"。当归一化发生时，卡片展示应保留用户原词作为辅助说明。调整 `_format_intent_preview_card` 在实体名与用户原词不一致时展示 `用户原词 → 归一名` 格式。

### 9.4 档案/成绩 inline 提取边界

**触发 case：** G22/G31（用户口头修正省份/成绩/选科）、G23（`我575分安徽物化生先看看`）

**现象：**

| 场景 | 表现 |
|------|------|
| G23 "我575分安徽物化生先看看" | direct 调 `read_state` 后回复"还没有拿到成绩信息"，未从用户输入提取成绩 |
| G22 "湖北/620/物化生" | 文本回复承认新信息，但后续查询仍读旧档案 `湖南 548 历政生` |
| G31 同上模式 | 同上 |

**根因：**
4.0 工具集（9 个）全部面向"方案规划"阶段，不包含成绩/档案提取和更新能力。在 3.x 系统中，成绩提取由 `intake_agent` + `extract_score_from_text` 完成；档案修正由 `profile_manager.update_score_detail` 处理。4.0 direct route 跳过了 intake 阶段的工具。

**设计决策：明确边界，不在 4.0 工具集中加成绩提取**

理由：
- 成绩/省份/选科是一次性设置操作，生命周期与方案规划工具不同
- 真实场景中，绝大多数用户通过问卷或前端表单完成成绩录入，oral inline 提取是少数情况
- 在 9 个工具中加入 `update_profile` 会引入状态写入 + 错误纠正复杂度

**过渡方案：**
1. **direct route 入口增加成绩可用性前置检查**：如果 `score.json` 没有有效成绩（`available=false`），直接回退到旧链路的 intake 流程，不进入 direct agent
2. **Prompt 调整**：在行动原则中增加边界说明——当用户提供新的成绩/省份/选科信息但系统无法更新时，告知用户通过正式渠道录入，不假装已记录
3. **后续独立扩展**：成绩提取作为 Phase 5 独立能力，不阻塞当前 9 工具方案规划链路

**direct route 入口条件更新：**

```
direct route 前置条件：
  原有：ZHIYUAN_AGENT_ENABLED + rollout_percent + 非 intake 阶段
  新增：score.json.available == true（无有效成绩时回退旧链路 intake）
```

### 9.5 G17 — 档位内移动 selector 字段归一化与 raw_user_text 补偿

**触发 case：** G17 `帮我把保底区里录取率最高的那个调到保底的第一位`

**现象与演进：**
- 子集回归曾通过，完整 G1-G32 回归中出现 "还没有唯一定位到要调整的方案项"
- v1.4 落地三层防护后，主 4.0 direct 已能稳定生成 `move_ordered_unit` 确认卡
- 但 shadow 仍观察到模型有时只调用 `preview_plan_action`，不传 `filters` 也不传 `raw_user_text`，导致工具直接返回 `clarify`

**当前问题定性：**

核心瓶颈不再是工具解析逻辑，而是**模型参数完整度的 LLM 可靠性问题**。三层防护的效果：

| 防护层 | 状态 | 覆盖场景 |
|--------|------|---------|
| 层 1 Prompt 示例 | 已落地 | 模型传正确字段名 → 正常工作 |
| 层 2 raw_user_text 补偿 | 已落地 | 模型漏传 selector 但传了 raw_user_text → 从文本提取 |
| 层 3 ambiguous_selector 澄清 | 已落地 | 模型什么都没传 → 返回 clarify 而非静默选错 |

shadow 中失败的场景属于"模型连 filters 和 raw_user_text 都没传"——此时层 2 和层 3 都无法补偿。这是 LLM 层面的不稳定，不应继续在工具层加 hack。

**后续方向：**
1. **不再在工具层加码**——三层防护已是合理边界，更多工具内 fallback 会让行为不可预测
2. **Prompt 巩固**——确认当前 prompt 中 G17 示例已足够明确，不需要增加更多 selector 示例
3. **观察稳定率**——记录 G17 在 direct route 上的通过率，如果 ≥ 80% 则接受当前设计；如果 < 80% 则需要评估是否在 prompt 增加更强的参数完整性指引
4. **shadow 与 direct 差异不阻塞**——shadow 是在 dry-run 隔离上下文中运行，模型行为可能与 direct 不一致（对话历史不同、sandbox 状态不同），不应以 shadow 的失败否定 direct 的通过

### 9.6 G4 — 实体归一化展示保真

**触发 case：** G4 `那把网络与新媒体作为优先方向，跨境电商也可以考虑`

**现象：**
用户说"跨境电商"，经实体归一后卡片只展示"电子商务"或"跨境电子商务"，用户原话消失。tracking doc 记录（line 715-718）：曾尝试在工具代码内维护 `_MAJOR_DISPLAY_ALIASES` 别名补丁，已回退——不是框架内的统一方案。

**根因：**
实体解析器返回 `EntityResolutionResult(raw_text="跨境电商", candidates=[EntityResolutionCandidate(canonical_name="电子商务", ...)])`。但 `_normalize_intent_side`（`tools.py:1720`）和后续 `_preview_message`（`tools.py:1737`）只取 `canonical_name` 写入 `normalized["positive"]` / `normalized["negative"]`，不保留 `raw_text`。卡片展示从 `normalized` 的 values 直接 join，所以用户原词消失。

**问题定位：展示层，非执行层。** 执行 payload 写入后端用 `canonical_name` 是正确的（实体消歧必须用规范名）。问题仅在用户可见的 `preview_summary` 和 `message` 中丢失了原词。

**修复设计：实体解析层输出 raw → canonical 映射，展示层统一使用**

**步骤 1 — `_normalize_intent_side` 保留 raw → canonical 映射：**

在归一化输出中增加 `_display_aliases` 字段，记录所有 raw_text ≠ canonical_name 的映射：

```python
def _normalize_intent_side(values, entity_type, batch) -> tuple[dict, dict]:
    normalized = {}
    display_aliases = {}  # canonical_name -> raw_text
    for result in resolved_results:
        if result.best and result.raw_text != result.best.canonical_name:
            display_aliases[result.best.canonical_name] = result.raw_text
        # ... existing canonical_name writing ...
    return normalized, display_aliases
```

**步骤 2 — `_preview_message` 使用 display_aliases 展示原词：**

```python
def _preview_message(intent_type, normalized, constraint_type, display_aliases=None):
    # ... existing code ...
    for name, payload in (("要", positive), ("不要", negative)):
        values = []
        for item in payload.values():
            for v in _as_list(item):
                alias = (display_aliases or {}).get(v)
                display = f"{alias}（{v}）" if alias and alias != v else v
                values.append(display)
        # ...
```

展示效果：`"专业要求：要：跨境电商（电子商务）、网络与新媒体。确认前不会生效。"`

**步骤 3 — `_intent_summary_from_merged` 同步应用 display_aliases：**

`pending.json` 中的 `preview_summary` 需要从合并后的 intents 中展示原词。在 merged payload 中保留 `display_aliases`，`_intent_summary_from_merged` 使用同样的 `alias（canonical）` 格式。

**不改变的部分：**
- 写入后端 `update_planning_constraint_state` 的 payload 继续使用 `canonical_name`
- `simulate_plan_diff` 继续使用 `canonical_name`
- 实体解析器本身不需要修改（已有 `raw_text` 字段）

### 9.7 G3 — 查询计数粒度口径

**触发 case：** G3 `当前方案里有没有相关专业` → 回复 "正式方案有45个志愿，命中114条"

**现象：**
用户问方案里有没有某专业，回复显示"命中114条"但方案只有45个志愿。114 是专业明细（一个志愿=一个学校+多个专业明细行）粒度的命中数，45 是志愿/方案项粒度。两个数字混在同一句话中，用户理解为计数矛盾。

**根因：**
`_plan_query_count_metrics`（`tools.py:2863`）已区分了 `matched_plan_item_total`（按 group 去重的志愿级计数）和 `matched_detail_total`（明细级计数）。`query_plan` 的消息模板（`tools.py:4656-4659`）在 `detail_granularity=True` 且两者不等时展示"命中 N 个志愿，涉及 M 条专业明细"。

但 `detail_granularity` 的判断（`tools.py:2873`）是 `total_detail > total_plan_items`——只比较全量，不比较命中结果。当全量方案的明细行数等于志愿数时（无多专业展开），`detail_granularity=False`，但命中筛选可能因专业名匹配到子字段而膨胀。

**修复设计：**

**调整 1 — `_plan_query_count_metrics` 增加命中级粒度判断：**

```python
detail_granularity = bool(
    (total_plan_items > 0 and total_detail > total_plan_items)
    or (matched_plan_total > 0 and detail_total > matched_plan_total)
)
```

当命中明细数 > 命中志愿数时，也启用双粒度展示。

**调整 2 — 消息模板明确主粒度为志愿：**

当前模板：`"命中{matched_total}条"`（matched_total 可能是志愿级也可能是明细级）

改为永远以志愿为主粒度：

```python
if count_metrics.get("detail_granularity") and detail != volunteer:
    matched_phrase = f"命中{volunteer}个志愿（涉及{detail}条专业明细）"
else:
    matched_phrase = f"命中{volunteer}个志愿"
```

**调整 3 — `_matches_plan_item` 匹配边界收紧：**

检查当前专业匹配是否跨志愿边界膨胀。如果 `filters` 包含专业名，匹配应以志愿为单位——志愿内有任一专业明细命中即算该志愿命中，但同一志愿不应重复计数。当前 `_matches_plan_item` 返回 True/False 应已是志愿级，复核 `plan/items.json` 的数据结构确保一个志愿不会作为多条出现。

### 9.8 G32 — 无方案探索降级内容策略

**触发 case：** G32 `有什么专业是比较好就业的吗`、`计算机和电子信息有什么区别`

**现象：**
无正式方案时，`explore_topic` / `compare_entities` 如果后端 profile API 无数据，返回偏元说明（"这是只读探索问题""暂时没有拿到完整资料"），实质内容不足。tracking doc（line 716-718）记录：曾尝试在 tools.py 内硬编码专业说明，已回退——不应在工具代码维护专业知识。

**根因：**
`explore_topic` 在 `profile_source != "backend_profile"` 时，message 只说"暂时没有拿到完整资料，会先按当前方案和问题本身做只读判断"（`tools.py:602`）。`compare_entities` 类似，`unavailable` 列表非空时标注"缺少完整资料，只能做有限对照"（`tools.py:709`）。工具返回的 `analysis` 是固定的 3 条元说明（`tools.py:614-618`），不包含任何专业/院校实际内容。

由于 `next_step="respond"` 当前改为软停（§9.1），LLM 会收到工具返回的 JSON 并生成用户可见回复。但 JSON 中 `profile_facts` 为空、`analysis` 为元说明，LLM 只能基于自身训练知识回答——内容质量取决于 LLM 对该专业/院校的了解，不可控。

**修复设计：结构化维度模板 + LLM 知识补充**

**方向决策：** 不在 tools.py 内维护专业百科内容。降级时由工具提供结构化的**对比维度框架**，由 LLM 基于自身知识填充内容。

**步骤 1 — explore_topic 降级时输出维度框架：**

当 `profile_facts` 为空且 `profile_source` 不是 `backend_profile` 时，`analysis` 字段改为对应 `topic_type` 的标准维度列表，引导 LLM 沿这些维度组织回答：

```python
_EXPLORE_FALLBACK_DIMENSIONS = {
    "major": [
        "学什么：核心课程和培养方向",
        "做什么：主要就业方向和职业路径",
        "怎么选：选科要求、录取分位段、男女比例等报考注意点",
        "和当前成绩/选科的适配度判断",
    ],
    "school": [
        "学校定位：层次、隶属、优势学科",
        "录取难度：分数段、位次参考",
        "就业/升学：保研率、就业去向",
        "和当前成绩的匹配度判断",
    ],
    "career": [
        "发展路径：典型职业阶梯",
        "对应专业：哪些专业方向可进入",
        "现实因素：编制、薪资水平、地域差异",
    ],
}
```

Message 调整：从"暂时没有拿到完整资料"改为"按以下维度整理分析"，明确告知 LLM 按维度回答。

**步骤 2 — compare_entities 降级时输出对比矩阵框架：**

当对比对象缺少 profile 时，提供结构化的空对比矩阵，维度根据 `comparison_focus` 或默认维度填充：

```python
"dimensions_template": [
    {"dimension": "培养方向差异", "fill_from": "llm_knowledge"},
    {"dimension": "就业方向差异", "fill_from": "llm_knowledge"},
    {"dimension": "录取难度", "fill_from": "llm_knowledge"},
]
```

**步骤 3 — message 避免元说明表述：**

将 "这是X探索问题，不会改动报考要求或方案" 改为 "关于{entity}的分析如下" — `state_mutation: false` 已经告诉 LLM 这是只读操作，message 不需要再重复说明。

**效果预期：**
- LLM 收到维度框架后，会按维度组织回答，内容密度显著提升
- 不在工具代码维护专业百科，维度框架是通用的
- 有 profile 数据时仍然优先使用 API 数据

### 9.9 G25 — 混合正负诉求路由与参数完整性

**触发 case：** G25 `把生物医学工程和智能医学工程加意向 排除临床医学和口腔`

**最新复跑发现（v1.4 后）：**

| 维度 | 现象 |
|------|------|
| 主链路路由 | **未进入 4.0 direct**，被旧 `runtime_intent_hard_cut` 接管，走旧链路，耗时约 22s |
| 可见结果内容 | 内容正确：生物医学工程、智能医学工程为正向；临床医学、口腔医学为负向 |
| 4.0 验证意义 | 这不是 4.0 工具链验证通过——是旧链路偶然给出了正确结果 |
| Shadow schema 问题 | 模型曾传 `major_name` 而非 `level2`，工具不识别导致 summary 为空 |
| Shadow 参数遗漏 | 模型有时只传 positive、漏 negative，负向部分丢失 |

**问题 1：`runtime_intent_hard_cut` 抢跑路由**

`service.py` 的处理顺序（line 15993-16008）：
1. `_maybe_handle_zhiyuan_agent_direct_route` — 如果返回 None，继续
2. 旧 `runtime_intent_profile_plan_reroute` — 含 `runtime_intent_hard_cut` 判断

direct route 返回 None 的原因可能是：
- `_score_available_for_zhiyuan_agent_direct` 检查不通过（成绩前置条件）
- `ZHIYUAN_AGENT_ENABLED` 未开启
- 或 G25 测试环境中 rollout bucket 未命中

但即使 direct route 开启，当前 `runtime_intent_hard_cut` 的判断条件（`service.py:5207-5226`）也会在 confidence ≥ 0.65 + side_effect=intent_pending + scope_anchor=future_reference 时抢先拦截。"把X加意向 排除Y" 这类表达恰好会被旧 `turn_decision` 分类器识别为 intent_update + future_reference，即使 direct route 已开启。

**修复方向：direct route 优先级高于 runtime_intent_hard_cut**

当前架构中 direct route 已在旧 intent pipeline 之前执行（line 15993 先于 16008），所以只要 direct route 成功返回非 None，就不会走旧链路。G25 的问题是 direct route 本身返回了 None。

需要确认并修复：
1. **测试环境配置**：确认 G25 复跑时 `ZHIYUAN_AGENT_ENABLED=1` + rollout 100%
2. **成绩前置条件**：确认 G25 的 fixture 有有效成绩（`score.json.available=true`）
3. **如果确认配置正确但仍走旧链路**：检查 direct route 是否因 agent 内部错误而 catch-and-return-None

**问题 2：Schema 字段 alias 兼容**

Shadow 中模型传 `positive={"major_name": ["生物医学工程", "智能医学工程"]}` 而非 `positive={"level2": ["生物医学工程", "智能医学工程"]}`。

当前 `_normalize_major_payload`（`tools.py:1688`）已有 `major_name` 作为 fallback key：
```python
for key in ("items", "values", "names", "majors", "major_name", "major_names", "majorName", "majorNames"):
```

如果 summary 仍为空，可能原因：
- 模型传的字段名不在上述列表中（如 `major` 单数形式、`majorList` 等）
- 或者 `negative` 侧的 payload 结构不同

**修复：扩展 fallback key 集合 + 增加 field alias 单测**

在 `_normalize_major_payload` 的 fallback keys 中追加常见变体：
```python
("items", "values", "names", "majors", "major_name", "major_names",
 "majorName", "majorNames", "major", "majorList", "major_list")
```

补充单测覆盖：`positive={"major_name": [...]}` 和 `negative={"major_name": [...]}` 应正确归一化到 `level2`。

**问题 3：模型只传 positive 漏 negative — 结构性缺陷**

模型有时将 `"把X加意向 排除Y"` 只映射到 `positive={"level2": ["X"]}` 而完全不传 `negative`。这不是 schema alias 问题，是**模型意图分解能力的不稳定性**。

**为什么不能靠工具内字符串匹配解决：**
- 在 `raw_user_text` 中 regex 匹配"排除"/"不要"后提取实体并回填 negative，本质上是在工具层重新做意图解析
- 这与 4.0 的设计原则冲突——意图解析应由 LLM 完成，工具层只负责实体归一化和执行
- 一旦开始在工具里做文本 NLU，边界会持续膨胀（"别考虑"/"不用看"/"算了" 等更多口语表达），维护成本高于 Prompt 修复

**修复方向：Prompt 层面加固，不在工具层加文本 NLU**

a. **Prompt 示例强化**：增加混合正负的明确示例，减少模型拆分或遗漏：

```
- "把X加意向 排除Y" -> preview_intent_change(intent_type="major", positive={"level2":["X"]}, negative={"level2":["Y"]}, constraint_type="must_have")
```

b. **工具层轻量校验（不做 NLU）**：如果 `raw_user_text` 中明显包含"排除/不要/不考虑"关键词，但 `negative` 为空，工具可在返回的 `message` 中追加提示："用户消息中似乎包含排除诉求，但未收到 negative 参数。如果确实要排除，请补充。"这是**提示而非自动补全**。

c. **观察频率**：如果混合正负遗漏发生率 < 20%，通过 Prompt 可接受；如果 > 20%，需要评估是否引入轻量预处理步骤（在 agent 层面、工具调用前解析）。

### 9.10 §9.1 respond 软停真实效果验证边界

**关联设计：** §9.1 将 `respond` 从硬停改为软停，允许 LLM 在只读工具返回后继续处理复合诉求。已落地（tracking doc line 729），单测通过，但**真实 LLM 效果未完全确认**。

**已知状态：**
- `should_return_directly_from_tool` 仅对 `confirm`/`clarify` 硬停——已改代码并通过单测
- 真实 websocket G12/G21/G23/G25/G27 复跑尚未完成（tracking doc line 744）
- 无法确认 LLM 在 respond 软停下是否会多调工具或改写内容

**需要验证的风险：**

| 风险 | 场景 | 影响 |
|------|------|------|
| LLM 多调工具 | 用户只问了一个只读问题，LLM 收到结果后额外调用不相关工具 | 延迟增加、可能产生副作用 |
| 回复质量下降 | 原来 `respond` 硬停直接返回工具 JSON 的 `message`，现在 LLM 二次生成可能改写内容 | 信息损失或幻觉 |
| token 消耗增加 | 每个只读工具调用后 LLM 都需要做一次推理决策 | 成本上升 |

**验证方案：**

**步骤 1 — 单意图基线复跑：**
用 400 真实口语集（14 步）+ G case 子集（8 步）复跑，对比 respond 软停前后：
- 工具调用次数是否增加（期望：不增加，LLM 识别到单意图后直接回复）
- 回复内容是否有实质变化（diff 检查）

**步骤 2 — G12 复合诉求验证：**
复跑 G12 `高收费的志愿占比多少 能不能换成便宜的`，确认 LLM 在 `query_plan` 返回后是否继续调用 `preview_plan_action`。

**步骤 3 — 防护增强（如果步骤 1 发现多余调用）：**

如果 LLM 确实在单意图场景多调工具，增加以下防护：

a. **Prompt 约束**：在行动原则中增加——"只读工具返回后，如果用户消息只包含一个问题，直接用工具结果回答，不需要再调用其他工具"
b. **工具结果注入方式**：只读工具返回时，在工具结果 JSON 中增加 `"single_intent_hint": true`，LLM 可据此判断是否需要继续
c. **回退方案**：如果防护无效且多余调用严重，将 `respond` 改回硬停，G12 复合诉求通过 Prompt 引导 LLM 在首次工具调用前先识别复合意图并规划调用序列

**判定标准：** 单意图工具调用数不增加（≤1）+ G12 复合诉求成功处理两个意图 → §9.1 设计成立。否则回退或增加防护。

### 9.11 调整后的优先级与依赖

**已落地（代码已改 + 单测通过，待真实 LLM 验证）：**

| 编号 | 内容 | 状态 |
|------|------|------|
| §9.1 | 复合诉求 respond 软停 | 代码落地，待 §9.10 真实验证 |
| §9.2 | Pending 下只读查询 direct route | 代码落地 |
| §9.3 | 正向意向 "想学X" → must_have | Prompt 落地 |
| §9.4 | 成绩前置检查 | 代码落地 |
| §9.5 | G17 三层防护 | 代码落地，direct 已通过，shadow 仍有不稳定 |
| §9.6 | G4 展示保真 display_aliases | 代码落地 |
| §9.7 | G3 查询计数粒度 | 代码落地 |
| §9.8 | G32 探索降级维度模板 | 代码落地 |

**待推进：**

```
§9.9-问题1 G25 路由抢跑 ─────────────────────────────────────────── P0（阻塞 4.0 验证）
  确认测试环境 ZHIYUAN_AGENT_ENABLED=1 + rollout 100%
  确认 G25 fixture 有有效成绩
  如果配置正确仍走旧链路，排查 direct route 内部错误

§9.9-问题2 G25 schema alias ──────────────────────────────────────── P1
  _normalize_major_payload fallback keys 追加 major/majorList
  补充 major_name alias 单测

§9.9-问题3 G25 模型只传 positive 漏 negative ───────────────────── P1
  Prompt 增加混合正负明确示例
  工具层轻量校验：raw_user_text 含排除关键词但 negative 为空 → 提示
  观察频率后决定是否需要预处理步骤

§9.10 respond 软停真实验证 ────────────────────────────────────────── P0
  400 口语集 + G case 子集复跑
  G12 复合诉求验证
  如果多余调用 → Prompt 约束或回退硬停

§9.5 G17 稳定率观察 ──────────────────────────────────────────────── P1（观察项）
  direct route 通过率 ≥ 80% 接受
  shadow 不稳定不阻塞 direct
```

### 9.12 下一步计划

**阶段 A：环境与路由排障（当日可完成）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| A1 | 确认测试环境 `ZHIYUAN_AGENT_ENABLED=1` + rollout = 100，G25 fixture 有有效成绩 | G25 进入 direct route |
| A2 | 如 A1 配置正确但 G25 仍未进 direct，在 `_maybe_handle_zhiyuan_agent_direct_route` 入口加 debug log，定位 return None 的具体分支 | 找到 direct route 拒绝原因 |
| A3 | 修复 direct route 拒绝原因后，单跑 G25 × 3 次确认 direct 路由命中 | 3/3 进入 direct route |

**阶段 B：schema 兼容与 Prompt 加固（1-2 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| B1 | `_normalize_major_payload` fallback keys 追加 `"major"`, `"majorList"`, `"major_list"` | alias 单测通过 |
| B2 | Prompt 增加混合正负示例：`"把X加意向 排除Y" -> preview_intent_change(positive=..., negative=..., ...)` | Prompt 已更新 |
| B3 | 工具层增加轻量校验：`raw_user_text` 含"排除/不要/不考虑"但 `negative` 为空 → message 追加提示 | 单测通过 |
| B4 | G25 单 case × 5 次 direct 复跑 | ≥ 4/5 positive + negative 均完整 |

**阶段 C：respond 软停真实验证（1-2 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| C1 | 400 口语集 direct 复跑 | 工具调用数 max ≤ 1（与软停前一致） |
| C2 | G case 子集 direct 复跑 | 工具调用数不增加 |
| C3 | G12 `高收费的志愿占比多少 能不能换成便宜的` 单跑 × 3 | ≥ 2/3 同时处理查询和调整两个意图 |
| C4 | 如 C1/C2 发现单意图场景多余调用 | 增加 Prompt 约束或回退 respond 硬停 |

**阶段 D：完整回归收口（2-3 天）**

| 步骤 | 动作 | 验证标准 |
|------|------|---------|
| D1 | 完整 G1-G32 direct 回归 × 2 次 | 通过率 ≥ 43/49（允许 G17 shadow 级不稳定） |
| D2 | G25 在完整回归中 positive + negative 均完整 | 2/2 完整 |
| D3 | 性能观察：direct route P95 延迟 | < 8s |
| D4 | 更新 Phase 3 检查项，标记完成 | — |

实施顺序：A → B → C → D

### 9.13 高收费 follow-up 参数完整性与 filter 安全

**触发 case：** 先问 `有啥问题，咋弄`，下一轮说 `那高收费的别要了`

**现象：**

| 场景 | 表现 | 风险 |
|------|------|------|
| 模型调用 `preview_plan_action(remove, review_issue_code=high_tuition)` | 当前审查结果里没有可操作的 `high_tuition` affected units，工具返回 `review_issue_units_not_in_plan` | 用户明确要求移出高收费项，但流程停在澄清 |
| 模型调用 `preview_plan_action(remove, filters={"tuition_level":"high"})` | 旧 filter 归一不支持 `tuition_level` / `fee_level` | 不能稳定命中高收费方案项 |
| 工具遇到未知 filter key | 旧逻辑可能跳过未知 key | 存在把未知 filter 当作全量匹配的风险 |

**设计边界：**

这类问题仍在 4.0 direct route 框架内解决：

1. 不恢复字符串 precheck。路由仍以 LLM 工具选择和结构化工具结果为准。
2. 不在工具层从原话做 NLU 特化。工具只做结构化参数归一、校验和安全兜底。
3. 不把普通高收费 follow-up 强行等同于审查 issue。只有用户明确说“审查里的/风险项/问题项”时，才优先使用 `review_issue_code=high_tuition`；否则当前方案锚定的高收费移出用 `filters={"program_type":["高收费"]}` 或费用 filter。
4. 如果工具返回的是“模型漏参/定位不完整”类 clarify，agent 可以让模型补参重试一次；如果是 active pending 冲突、真实无命中、用户需要选择范围等业务澄清，则直接返回给用户。

**实现策略：**

| 层级 | 调整 | 说明 |
|------|------|------|
| Prompt | `preview_plan_action` 必须携带 `targets` / `filters` / `review_issue_code` / 位置 selector 之一，并尽量保留 `raw_user_text` | 防止只传 `action=remove` |
| Prompt | 增加自修正规则：遇到 `missing_targets`、`missing_filters`、`review_issue_not_found`、`review_issue_units_not_in_plan` 时，如原话已有属性/标签/审查问题/位置定位，补参重试一次 | 让 `那高收费的别要了` 从错误 issue 定位回到 filters |
| Agent | 对上述不完整参数类 clarify 不立刻给用户，允许模型继续一次 | 只处理模型参数完整度问题，不吞掉真实业务澄清 |
| Tools | `tuition_level=high`、`tuitionLevel=high`、`fee_level=high`、`feeLevel=high` 归一为 `program_type=["高收费"]` | 接受模型常见结构化表达 |
| Tools | 未知 filter key 不再跳过匹配 | 防止错误全量命中后创建大范围删除 pending |

**验证结果：**

| 验证 | 结果 |
|------|------|
| 聚焦单测 + runner 单测 | `tests/unit/test_zhiyuan_agent_poc.py tests/unit/test_dialog_regression_runner.py -q`：`205 passed, 28 skipped` |
| 真实 LLM opt-in | `那高收费的别要了` 通过，模型能带定位参数 |
| 真实 service direct-only 口语集 | `examples/dialog_regression_400_realistic_user_cases.json`：`14/14` successful，metrics: `/private/tmp/zhiyuan_400_realistic_direct_only_after_retry_reason_fix.json` |
| 真实 service direct 确认执行闭环 | `examples/dialog_regression_400_direct_confirm_execution_cases.json`：`4/4` successful，后端断言覆盖 pending applied、planningState version 增长、方案项删除和 `院校性质:民办` 写入，metrics: `/private/tmp/zhiyuan_400_direct_confirm_execution_after_retry_filter_fix.json` |
| G case direct 子集 direct-only | `/private/tmp/zhiyuan_400_g_case_direct_subset_direct_only.json`：`8/8` successful，G17/G25/G30/G32 direct 断言通过，metrics: `/private/tmp/zhiyuan_400_g_case_direct_only_after_retry_filter_fix_rerun.json` |

**验收口径：**

direct 主链路和 shadow 观测分开验收。shadow 是 dry-run 隔离后台任务，可能在 turn event 阶段仍为 `running` 或因超时缺观测；这类情况单独记录为 shadow 稳定性问题，不直接判定 direct 主链路失败。

### 9.14 完整 320 G1-G32 direct 复跑结果

**验证环境：**

- service：本地 `8075` direct-only，`ZHIYUAN_AGENT_POC_SHADOW=0`
- 后端：`8080`
- case：`examples/dialog_regression_320_g1_g32_shadow_cases.json`
- metrics：`/private/tmp/zhiyuan_400_direct_320_g1_g32_after_retry_filter_fix_rerun.json`

**总体结果：**

| 指标 | 结果 |
|------|------|
| steps | 49 |
| successfulSteps | 44 |
| failedSteps | 5 |
| failedByReason | environment=1, content=3, tool=3 |
| latency median | 16433ms |
| latency p95 | 45480ms |
| latency max | 68550ms |

说明：`failedByReason` 是按断言类型统计，同一个 step 可以同时触发 content/tool failure，因此数量会大于 `failedSteps`。

**已通过的关键路径：**

| 场景 | 结果 |
|------|------|
| G1 裸排除 + 当前方案影响 | `preview_intent_change`，生成报考要求确认卡 |
| G2/G7/G21 只读审查 | `review_plan` 或旧 full_agent，只读不改方案 |
| G3 pending 下只读查询 | 先创建 intent pending，后续 `query_plan` 只读查询 |
| G12 查询 + 替换复合诉求 | `query_plan -> preview_plan_action`，生成替换确认卡 |
| G16 锁定暂不支持 | `preview_plan_action` 返回 unsupported，不创建 pending |
| G17 档位内移动 | `preview_plan_action`，生成 `move_ordered_unit` 确认卡 |
| G22/G31 档案口语修正 | 不写系统档案，提示需正式更新 |
| G26 当前方案切片查询 | `query_plan`，返回保底末尾志愿 |

**问题归档：**

| 编号 | 场景 | 现象 | 定性 |
|------|------|------|------|
| 320-R1 | G8 | 清理 backend planning intent 超时，case 未进入 agent | 环境/后端准备失败，需重跑确认 |
| 320-R2 | G25 | `把生物医学工程和智能医学工程加意向 排除临床医学和口腔` 被旧 `runtime_intent_hard_cut` 接管，输出“偏好专业/排除专业”，不是 4.0 “专业要求：要/不要” | 旧路由抢跑；8-case direct 子集同诉求已通过，工具能力本身可用 |
| 320-R3 | G27 | `方案里学费贵的太多了 能不能帮我换成便宜的` direct 调用 3 次工具，最终未生成替换确认卡 | `replace` 自动候选/高收费替换策略不稳定 |
| 320-R4 | G27 | `两万以上的都算贵 帮我看看有几个` 实际 `query_plan` 返回 37 个，旧断言期望 `execute_plan_action/query_ordered` | case 断言仍是旧链路口径，应更新为 4.0 `query_plan` |
| 320-R5 | G27 | `那把两万以上且跟我意向不沾边的先删掉` 实际生成 `remove_units` 确认卡，旧断言期望 pending 冲突 guard | 受首轮未建 pending 影响，需在修复首轮后重新定义 |
| 320-R6 | G21/G30 | 强基多轮仍走 `full_agent` / `runtime_intent_hard_cut`，并出现“偏好/报考想法”旧文案 | direct route 覆盖范围未完全替换旧链路 |
| 320-R7 | G23/G29 | 正向软表达和“优先/可以考虑”仍触发旧 pending card | 与 4.0 显式要/不要口径不一致，后续通过旧链路清理解决 |
| 320-R8 | G23/G21/G30 | 多个旧 full_agent step 耗时 30-68s | 性能问题主要集中在旧链路和政策/探索多工具回答 |
| 320-R9 | G22/G31 | 中间轮次有“已更正”等口头措辞 | 需统一为“你口头说明的是……系统档案仍未更新”，避免用户误解已写入系统 |

**后续顺序：**

1. 先修 4.0 direct 内的问题：G27 高收费 replace 自动候选与首轮 pending 创建。
2. 更新历史 case 中已切到 4.0 的断言口径：`query_plan` 不再要求旧 `execute_plan_action/query_ordered`。
3. 再处理旧路由抢跑：G25/G21/G30/G23/G29 这类已由 4.0 子集证明可表达的诉求，应切到 direct 或在旧链路清理阶段删除对应 hard-cut。
4. 最后重跑完整 320 G1-G32；确认类 case 仍必须包含最终后端 action 断言。
