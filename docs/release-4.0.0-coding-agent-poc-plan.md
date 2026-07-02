# Release 4.0.0 — Zhiyuan Agent PoC 验证方案

> 版本: v1.0 | 日期: 2026-06-30
> 前置文档: [release-4.0.0-coding-agent-architecture-redesign.md](release-4.0.0-coding-agent-architecture-redesign.md)
> 实施追踪: [release-4.0.0-coding-agent-implementation-tracking.md](release-4.0.0-coding-agent-implementation-tracking.md)

## 1. PoC 目标

验证架构设计文档中提出的"Zhiyuan Agent 五机制"能否解决 3.2.0 的工具乱试问题：

| 机制 | 验证内容 |
|------|---------|
| 状态前置注入 | Agent 无需先调工具摸底，第一次调用就是业务工具 |
| next_step 终止信号 | 工具返回后 Agent 知道该停还是继续 |
| 硬性工具上限（3次/轮） | 即使 Agent 想继续调用也会被截断 |
| 正交工具设计（4个） | 每个意图只有一个对应工具，不存在候选竞争 |
| 协议事件快捷路径 | 按钮点击等结构化事件不进 Agent 循环（PoC 不实现，仅设计验证） |

**不在 PoC 范围内**：完整 9 工具实现、沙箱文件系统、service.py 替换、生产部署。

## 2. 测试场景

5 个场景覆盖架构设计文档第 3 章诊断的五大错误类型：

| # | 用户消息 | 当前系统问题 | 预期工具调用 | 验证点 |
|---|---------|------------|------------|--------|
| 1 | "不要医学类" | 可能走 plan_mutation 或 intent，路由不确定 | `preview_intent_change` ×1 | 正确路由到 intent，极性正确（negative） |
| 2 | "计算机适合我吗" | 可能连续调 analyze + compare + get_intro 3个工具 | `explore_topic` ×1 | 走 explore 而非 intent，不乱试多个分析工具 |
| 3 | "方案里有没有民办" | 可能走 review_plan 或 plan_mutation | `query_plan` ×1 | 走 plan 查询，不走 review 或 mutation |
| 4 | "不要排除经济学类" | 双重否定被忽略，"经济学类"放入 negative | `preview_intent_change` ×1 | 双重否定 → positive，实体归一化为 level2 |
| 5 | "建议考公吗" | "考公"被误识为专业名 | `explore_topic` ×1 | 走 career explore，不将"考公"误识为专业 |

**场景上下文**：所有场景共用同一个学生状态——河北 550 分 物化生 男生，已有 45 个志愿方案。

## 3. 文件结构

```
zhiyuan-agent/
├── app/zhiyuan_agent/
│   ├── __init__.py                # 包初始化
│   ├── agent.py                   # ZhiyuanAgent 类（继承 BaseAgent）
│   ├── tools.py                   # 4 个 PoC 工具定义
│   └── prompt.py                  # 精简 system prompt + 状态前置注入
└── tests/unit/
    └── test_zhiyuan_agent_poc.py   # 工具单元测试 + LLM e2e 测试
```

## 4. 模块设计

### 4.1 `app/zhiyuan_agent/prompt.py` — 精简 Prompt + 状态前置注入

#### `build_turn_context(deps: RequestContext) -> str`

从 RequestContext 提取核心状态，生成 ~300 tokens 的摘要文本，注入到 system prompt 中。

**数据来源映射：**

| 状态 | 来源字段 | 输出示例 |
|------|---------|---------|
| 成绩 | `deps.score_detail` | `成绩：河北 550分 物理/化学/生物` |
| 方案概况 | `deps.planning_summary` | `方案：45个志愿 (冲12/稳18/保15)` |
| 风险 | `deps.planning_summary.review_risk_count` | `风险：2项` |
| 待确认 | `deps.conversation_phase.pending` | `待确认：remove_units 操作` |
| 无方案 | `planning_summary is None` 或 `ordered_total == 0` | `方案：尚未生成` |

**核心价值**：Agent 在第一次推理时就知道"有方案 45 个志愿"，不需要先调 `read_state` 摸底。对"加入广东和江西"这种消息，Agent 直接看到"方案：尚未生成"就知道走偏好而非方案修改。

#### `build_zhiyuan_agent_instructions(ctx: RunContext[RequestContext]) -> str`

动态 callable，总大小 ~3KB（对比当前 ~22K tokens）。

**组装顺序：**

```
1. 角色定义（复用 build_identity）      ~500 字符
2. 状态摘要（build_turn_context）       ~300 tokens
3. 行动原则                            ~300 字符
4. 回复风格                            ~150 字符
─────────────────────────────────────
总计                                   ~3K tokens
```

**行动原则（静态段）：**

```
## 行动原则

1. 先读后做：回答需要方案/偏好事实时，先 read_state 确认。
   但上方状态摘要已包含核心信息，只在需要详细数据时才调 read_state。
2. 只读回答：分析、对比、政策解释、查询，直接回答，不改状态。
3. 预览才改：变更偏好或方案必须先 preview，等用户确认后 confirm。
4. 工具处理实体：不确定的专业/学校/地域名传给工具，工具内部消歧。
5. 极性判断：
   - "不要X" → negative
   - "不要排除X" → positive（双重否定）
   - "只保留X" → positive + constraint_type="only_keep"
```

**回复风格（静态段）：**

```
## 回复风格

- 自然中文，确认前不说"已记录/已调整/已执行"
- 查询先给结论句，分析保留结构但不超过4个要点
- 禁用术语：payload, stage, action_family, volunteerId, 候选池, 自动修复
```

**关键对比**：当前系统 `tool_dispatch_rules.py` 有 37KB 的路由规则（占 system prompt 的 79%），新设计 **0 行路由规则**。

### 4.2 `app/zhiyuan_agent/tools.py` — 4 个 PoC 工具

#### 统一返回格式

所有工具返回带 `next_step` 字段的 JSON 字符串：

```python
class ToolResult(TypedDict):
    data: Any                   # 业务数据
    next_step: Literal[
        "respond",              # 直接用这个结果回复用户
        "confirm",              # 展示预览并等待用户确认
        "clarify",              # 有歧义，需要问用户澄清
        "continue",             # 可以继续调用其他工具（罕见）
    ]
    message: str | None         # 可选的面向用户摘要
```

**对比当前系统**：当前 `tool_reply_policy.py` 在工具外部用 396 行代码判断"该不该停"。新设计让工具自己说。

#### 工具一：`read_state`

```python
async def read_state(
    ctx: RunContext[RequestContext],
    path: str,      # "score" | "profile" | "plan/summary" | "pending"
) -> str
```

- PoC 中直接从 `ctx.deps` 取值（不做沙箱文件系统），格式化为 JSON 返回
- `next_step: "respond"`（状态查询是终端操作）
- 未来正式版：从 SandboxFileCache 读取，支持 query 过滤

#### 工具二：`explore_topic`

```python
async def explore_topic(
    ctx: RunContext[RequestContext],
    topic_type: str,      # "career" | "major" | "school" | "region"
    user_question: str,   # 用户原始问题
) -> str
```

- PoC 中返回占位分析结果，重点验证 Agent 是否选对此工具
- `next_step: "respond"`
- 替代当前系统的 6 个 analyze/explore 工具，消除"该调哪个分析工具"的歧义
- 未来正式版：内部委托到现有 `analyze_current_career_direction` 等实现

#### 工具三：`preview_intent_change`

```python
async def preview_intent_change(
    ctx: RunContext[RequestContext],
    intent_type: str,                    # "major" | "school" | "region" | "career"
    positive: dict | None = None,        # {"level1": [...], "level2": [...], ...}
    negative: dict | None = None,        # {"level1": [...], "level2": [...], ...}
    constraint_type: str = "preference", # "preference" | "only_keep" | "must_have" | "exclude"
) -> str
```

- **实体解析**：调用现有确定性解析器
  - `intent_type="major"` → `major_entity_resolver.resolve_major_entity()`
  - `intent_type="school"` → `school_entity_resolver.resolve_school_entity()`
  - `intent_type="region"` → `region_entity_resolver.resolve_region_entity()`
- **歧义处理**：解析器返回多个候选时 → `next_step: "clarify"` + 候选列表
- **正常返回**：归一化结果 + `next_step: "confirm"`
- **极性处理**：Agent 通过参数明确传入 positive/negative，工具不猜极性。双重否定（"不要排除X"→positive）由 Agent 在调用前判断
- 替代当前系统的 5 个 `preview_current_*_intent_confirmation` 工具

#### 工具四：`query_plan`

```python
async def query_plan(
    ctx: RunContext[RequestContext],
    scope: str = "plan",        # "plan" | "candidates"
    filters: dict | None = None, # {"school_nature": "民办", "tier": "保", ...}
) -> str
```

- PoC 中从 `deps.planning_summary` 返回方案概况
- 无方案时返回 `{"has_plan": false, "guidance": "还没有生成方案"}`
- `next_step: "respond"`
- 替代当前系统的 `query_volunteer_plan` + `collect_plan_context_inputs`

### 4.3 `app/zhiyuan_agent/agent.py` — ZhiyuanAgent 类

```
ZhiyuanAgent(BaseAgent[str])
│
├── __init__(llm_client)
│   └── super().__init__(tools=[read_state, explore_topic, preview_intent_change, query_plan],
│                        instructions=build_zhiyuan_agent_instructions,
│                        deps_type=RequestContext)
│
├── MAX_TOOL_CALLS_PER_TURN = 3
│
├── should_return_directly_from_tool(tool_names, tool_returns, deps)
│   └── 解析 tool_return JSON 中的 next_step
│       "respond" / "confirm" / "clarify" → return True
│       "continue" → return False
│
├── render_direct_tool_output(tool_names, tool_returns, deps)
│   └── 从 JSON 提取 message / analysis / preview 字段
│
└── _guard_repeated_tool_calls (复用 BaseAgent 机制)
    └── 追加总数上限检查：sum(toolNameCounts.values()) > MAX_TOOL_CALLS_PER_TURN
```

**工具调用总数硬上限实现方式**：

BaseAgent 已有 `_guard_repeated_tool_calls` 机制检查单工具重复。ZhiyuanAgent 在此基础上追加总数检查——通过 observability dict 中的 `toolNameCounts` 累加判断。超限时走现有 guard 输出路径（提取最近一次工具返回作为回复）。

### 4.4 `tests/unit/test_zhiyuan_agent_poc.py` — 测试

#### 第一层：工具单元测试（不需要 LLM，不需要后端）

用 `make_run_context()` 构造上下文，直接调用工具函数：

```
TestReadState
├── test_read_score           # 返回成绩信息，next_step == "respond"
├── test_read_plan_summary    # 有方案时返回概况
└── test_read_plan_no_plan    # 无方案时返回 has_plan: false

TestExploreTopic
├── test_career_explore       # topic_type=career，next_step == "respond"
└── test_major_explore        # topic_type=major，next_step == "respond"

TestPreviewIntentChange
├── test_negative_major_l1        # negative level1 医学 → 归一化正确
├── test_positive_major_l2        # positive level2 经济学类 → 归一化正确
├── test_ambiguous_major          # "计算机" → 返回 clarify + 候选列表
└── test_region_normalize         # "内蒙" → "内蒙古"

TestQueryPlan
├── test_query_with_plan      # 有方案返回概况
└── test_query_no_plan        # 无方案返回 has_plan: false
```

#### 第二层：LLM e2e 测试（opt-in，需要 API key）

用真实 LLM + RequestContext（不 mock 后端查询，因为工具从 deps 取数据）：

```
@pytest.mark.skipif(os.getenv("RUN_zhiyuan_agent_POC") != "1")
TestZhiyuanAgentLLMSelection
├── test_exclude_medical          # "不要医学类" → preview_intent_change ×1
├── test_explore_major_fit        # "计算机适合我吗" → explore_topic ×1
├── test_query_plan_school_type   # "方案里有没有民办" → query_plan ×1
├── test_double_negation          # "不要排除经济学类" → preview_intent_change ×1, positive
└── test_career_explore           # "建议考公吗" → explore_topic ×1
```

每个测试断言：
1. `usage.tool_calls <= 2`（硬上限 3，但预期 1-2 次够用）
2. 第一个工具调用名称正确
3. 对于 intent 场景，验证极性参数正确

## 5. 复用的现有代码

| 组件 | 路径 | 用途 |
|------|------|------|
| `BaseAgent[str]` | `app/agent/base_agent.py` | Agent 基类、循环控制、observability |
| `LLMClient` / `LLMConfig` | `app/llm/client.py`, `app/config.py` | LLM 连接管理 |
| `RequestContext` / `PlanningSummary` | `app/agent/context.py` | 依赖注入容器 |
| `build_identity(deps)` | `app/agent/instructions/identity.py` | 角色定义文本 |
| `resolve_major_entity` | `app/domain/major_entity_resolver.py` (661行) | 专业实体解析 |
| `resolve_school_entity` | `app/domain/school_entity_resolver.py` (212行) | 学校实体解析 |
| `resolve_region_entity` | `app/domain/region_entity_resolver.py` (304行) | 地域实体解析 |
| `make_request_context` | `tests/factories.py` | 测试数据工厂 |
| `make_run_context` | `tests/factories.py` | 模拟 RunContext |

**不新增任何依赖**，全部使用现有 `pydantic-ai`、`fastapi`、标准库。

## 6. 成功标准

| 指标 | 当前系统基线 | PoC 目标 | 测量方式 |
|------|------------|---------|---------|
| 工具调用次数/轮 | 2-5 次 | ≤2 次 | `usage.tool_calls` |
| 工具选择正确率 | ~70%（30个工具竞争） | >95%（4个正交工具） | 5 场景中工具名命中率 |
| System prompt 大小 | ~22K tokens | ~3K tokens | 字符计数 |
| "考公"走 career | 失败（识别为专业） | 成功 | 场景5 断言 |
| "不要排除X"极性正确 | 失败（放入 negative） | 成功 | 场景4 断言 |

## 7. 验证命令

```bash
# 工具单元测试（无 LLM 成本，~2秒）
cd zhiyuan-agent
pytest tests/unit/test_zhiyuan_agent_poc.py -v -k "not LLM"

# LLM e2e 验证（需要 .env 中的 LLM_API_KEY）
RUN_zhiyuan_agent_POC=1 pytest tests/unit/test_zhiyuan_agent_poc.py -v -s -k "LLM"
```

## 8. PoC → 正式迁移的衔接

PoC 验证通过后，按架构设计文档第 9 章的迁移方案推进：

| PoC 组件 | 正式版演化方向 |
|---------|-------------|
| `build_turn_context` 从 deps 取值 | 改为从 SandboxFileCache 读取 |
| `explore_topic` 返回占位 | 内部委托到现有 analyze_* 实现 |
| `preview_intent_change` 本地解析 | 增加 async catalog 远程解析 + 方案影响分析 |
| `query_plan` 从 deps 取值 | 改为调用 `internal_client.get_planning_ordered_plan` |
| 4 个工具 | 扩展到 9 个（增加 confirm_pending、preview_plan_action、answer_policy、review_plan、compare_entities） |
| `ZhiyuanAgent` 独立运行 | 通过功能开关与 `ChatAgent` 并行，shadow diff 验证 |

## 9. 当前落地记录

最新实施进度和真实 LLM / service shadow 对比结果统一记录在：

- [release-4.0.0-coding-agent-implementation-tracking.md](release-4.0.0-coding-agent-implementation-tracking.md)

截至 2026-06-30，PoC 独立 agent、service shadow 开关、runner 指标提取和 5 个真实 LLM 场景均已完成；service websocket 小样本为 `5 successful / 0 failed`，PoC shadow 为 `5/5 success`，每轮 PoC 工具调用数均为 1。
