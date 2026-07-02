# 智愿 AI 系统架构优化设计文档

> 版本: v1.0 | 日期: 2026-06-29

## 文档说明

本文档包含两部分：
1. **现状诊断与问题分析**（第1-3章）— 对当前 3.2.0 agent 对话系统的深度分析
2. **Coding Agent 架构设计**（第4-9章）— 基于诊断结论的重构方案

产出物：将以 `docs/architecture-redesign.md` 形式提交到项目中。

---

## 第一部分：现状诊断

### 1. 系统概况

智愿 AI 是一个高考志愿填报 AI 系统，由 4 个模块组成：

| 模块 | 目录 | 技术栈 | 职责 |
|------|------|--------|------|
| 前端 | `zhiyuan-web/` | Next.js 13, React 18, Ant Design 5 | PC Web UI, WebSocket 聊天 + 工作台 |
| 后端 | `zhiyuan-server/` | Spring Boot 2.3, MyBatis-Plus, MySQL | 业务数据、状态管理、40+ 内部API |
| AI Agent | `zhiyuan-agent/` | FastAPI, Pydantic AI, WebSocket | 对话引擎、意图提取、方案编排 |
| 排位服务 | `zhiyuan-rank/` | Flask, Pandas, NumPy | 排名算法、专业推荐 |

核心数据流：用户通过 WebSocket 与 Python Agent 对话 → Agent 调用 Java 后端 API 读写状态 → 后端是所有可变状态的唯一权威源。

### 2. 当前 Agent 架构

#### 2.1 三层路由架构

当前系统在 LLM 处理用户消息前后有三层路由决策，各自独立运作：

```
用户消息
  ↓
[第一层] 关键词守卫 (service.py, ~400行规则)
  - _READONLY_USER_PROMPT_MARKERS: 18个标记 ("先别动/只分析/先看看不要改")
  - _PLAN_ACTION_NEGATIVE_ACK_MARKERS: 13个标记 ("不用替换/先不处理")
  - _PLAN_STYLE_GUARD_PROMPT_KEYWORDS: 26个方案关键词
  - _prompt_is_score_batch_risk_policy_question(): 复合关键词检测
  - _prompt_is_major_group_keep_safest_policy_question(): 复合关键词检测
  ↓ (如果没被短路)
[第二层] TurnDecision LLM 分类器 (turn_decision_tool.py)
  - 独立 LLM 调用, temperature=0
  - 输入：用户文本 + planningStateProfile布尔值 + pendingState
  - 输出：(taskLayer, sideEffect, scopeAnchor, scenario) 分类元组
  - prompt 包含 20+ schemaRules, 18 hardRules, 14 examples (~300行)
  ↓ (如果没被短路)
[第三层] 全 Agent 循环 (chat_agent.py, 30个tools)
  - 系统 prompt 包含 37KB 路由规则 (tool_dispatch_rules.py, 112行密集中文)
  - 从30个tool中选择调用
  - 30个tool: 22个只读 + 8个写入
  ↓
[后处理] 补丁层 (service.py + proposal_compiler.py)
  - _reply_looks_like_unbacked_intent_preview(): 30+标记检测幻觉确认卡
  - _plan_reply_needs_normalization(): 18个严重标记检测强制性语气
  - _reply_is_readonly_policy_misroute(): 7个标记检测错误路由
  - 英文词替换、内部术语清理、悬挂句子修复
```

#### 2.2 核心代码规模

| 文件 | 行数 | 职责 |
|------|------|------|
| `service.py` | 18,279 | 单体编排层：所有路由、守卫、前后处理 |
| `proposal_compiler.py` | 5,650 | 规则引擎：pending处理、边界检测 |
| `plan_execution_tool.py` | 5,160 | 方案执行网关：12种操作族 |
| `intent_state_tool.py` | 4,608 | 意向生命周期管理 |
| `tool_dispatch_rules.py` | 37KB | 系统prompt中的路由规则 |

#### 2.3 系统 Prompt 构成

| 段落 | 来源 | 大小 | 内容类型 |
|------|------|------|---------|
| 角色身份 | `identity.py` | ~500字符 | 角色定义 + 学生信息注入 |
| 方案上下文 | `planning_context.py` | ~300-800字符 | 方案状态、梯度分布、风险 |
| 待确认上下文 | `pending_context.py` | 0或~400-600字符 | 活跃 pending 信息 |
| **路由规则** | **`tool_dispatch_rules.py`** | **~8000字符** | **占静态指令的79%** |
| 风格规则 | `style_rules.py` | ~3000字符 | 术语禁用、格式约束 |
| 技能摘要 | 8个 SKILL.md | ~54KB原文 | 边界摘要注入 |

总计：约 15,000-22,000 tokens/轮。其中用户相关数据仅 ~800-3,000 tokens。

### 3. 问题诊断

#### 3.1 错误模式分类

基于 320+ 回归测试用例和 shadow diff 观测数据，错误分为五大类：

**类别一：实体类型混淆（~35%）— 最高频**

LLM 将非专业概念误识别为专业名称：

| 用户输入 | 错误识别 | 正确类型 |
|---------|---------|---------|
| "建议考公吗" | 偏好专业：考公 | career (职业方向) |
| "我想要优先稳定体制内" | 偏好专业：体制内 | career (职业方向) |
| "公办民办" | 具体专业：公办 | school_nature (学校属性) |
| "全是民办院校" | 具体专业：民办 | school_nature (学校属性) |
| "冲50%稳30%保20%" | 偏好专业：冲 | strategy (策略参数) |
| "只为了保本" | 偏好专业：保本 | strategy (策略参数) |
| "稿费呢高高学费" | 具体专业：稿费 | budget (学费预算, ASR错误) |

**类别二：路由方向混淆（~30%）**

LLM 对 explore/intent/plan 三个层的边界判断错误：

| 用户输入 | 错误路由 | 正确路由 | 条件 |
|---------|---------|---------|------|
| "加入广东和江西" | plan_preview (加入方案) | intent_pending (加入偏好) | 无正式方案时 |
| "方案里有没有民办" | plan_mutation | needs_plan_first | 无正式方案时 |
| "我倾向会计学和审计学" | plan_preview | intent_pending | 偏好表达 |
| "把湖北工程学院的计算机科学与技术加进来" | intent_pending | plan_preview/add_units | 有方案+有候选池时 |
| "先不确认，看看保底学校" | 取消 pending | readonly_while_pending | pending 应保留 |

**类别三：极性/否定错误（~15%）**

双重否定反转和混合极性处理失败：

| 用户输入 | 错误极性 | 正确极性 |
|---------|---------|---------|
| "不要排除经济学类" | exclude_hard: 经济学类 | positive/acceptable |
| "别排除江西财经大学" | exclude_hard: 江西财经大学 | positive/acceptable |
| "别避开东北" | avoid: 东北 | positive/acceptable |
| "不要排除经济学类，但临床医学还是排除" | 全正面或全负面 | 经济学正面 + 临床医学负面 |

**类别四：实体解析不一致（~15%）**

同一实体在管道不同阶段解析结果不同：

| 不一致点 | 原因 |
|---------|------|
| intent_tool vs plan_execution_tool 的专业名归一化 | intent 走 async remote catalog，plan_execution 只走 local static |
| 4种不同的 compact 函数 | school/major/polarity/plan_execution 各用不同的文本清洗逻辑 |
| _major_scope_matches vs _major_scope_exact_name_matches | 同一工具内两种匹配策略对同一实体结果不同 |
| canonicalize_plan_major_scopes 只对 remove_units 生效 | add_units/replace_units 不做同样的校准 |
| "江西财经大学"中"江西"泄露到地域偏好 | school resolver 和 region resolver 独立匹配，无 span 互斥 |

**类别五：ASR/口语容错（~5%）**

语音识别错误和口语表达处理失败：

| 用户输入 | 错误处理 | 正确处理 |
|---------|---------|---------|
| "稿费呢高高学费" | 具体专业：稿费 | budget: 高收费 (ASR: 稿费→高费) |

#### 3.2 实体解析管道分析

当前实体解析分散在 **4个层次**，可能产生不一致结果：

| 层次 | 调用时机 | 数据源 | 代表文件 |
|------|---------|--------|---------|
| Domain Resolver (确定性) | 各处分散调用 | 本地静态数据 | `school_entity_resolver.py`, `major_entity_resolver.py` |
| Async Catalog (网络) | intent 工具内部 | 远程 catalog API | `code_enrichment.py` → `resolve_major_names_async()` |
| Intent Extraction (LLM) | 意向分析工具 | 二级 LLM 调用 | `career_intent_tool.py`, `major_intent_tool.py` 等 |
| Plan Execution (临时) | 方案执行时 | 混合 | `plan_execution_tool.py` 内部解析 |

关键问题：intent 工具经过 `_normalize_major_intent_names_for_batch()` (async catalog) → `_refine_major_intents_by_explicit_mentions()` (local) 的完整链路，但 plan_execution_tool 只走 `canonicalize_major_intent_payload()` (local)。同一个专业名经过不同链路可能得到不同结果。

#### 3.3 路由冲突的根本原因

三层路由竞争的根因是**结构性的**：

1. **TurnDecision** 只看到最新一句话 + 几个布尔值，没有完整历史和工具结果
2. **全 Agent** 有完整历史和工具访问权，但受 37KB 路由规则约束，规则之间可能矛盾
3. **关键词守卫** 是对前两者错误的事后修补，每修一个边界就加一条规则

当三者对同一消息给出不同判断时（例如 TurnDecision 说 `intent_pending`，全 Agent 选了 `plan_mutation` 工具，关键词守卫检测到 `_READONLY_USER_PROMPT_MARKERS`），系统用更多的 `_classify_*` 函数和 `_should_defer_*` 函数来仲裁。

**service.py 中的仲裁函数列表（部分）：**
- `_classify_active_pending_turn_decision()` (line 896)
- `_classify_runtime_intent_profile_side_effect()` (line 5919)
- `_should_defer_runtime_intent_hard_cut_to_current_plan_action()` (line 5107)
- `_turn_decision_allows_runtime_intent_soft_candidate()` (line 5053)
- `_turn_decision_blocks_full_agent_intent_pending()` (line 5031)
- `_prompt_explicitly_readonly()` (line 10455)
- `_reply_is_readonly_policy_misroute()` (line 10550)

每个函数都是一个补丁。补丁的总量只会增长，不会减少。

#### 3.4 补丁模式分析

补丁按方向分为三类，比例约为 3:1:1：

**过度激进（~60%）— LLM 在不该产生副作用时产生了副作用**
- 用户说"先别动"，LLM 仍生成确认卡
- 用户问政策问题，LLM 路由到方案修改
- 用户拒绝操作，LLM 解读为新的操作请求
- Agent 回复中出现未经工具创建的"幻觉确认卡"
- Agent 使用强制/命令式语气

**过度保守（~20%）— LLM 在该产生意向时没有产生**
- TurnDecision 将 `intent_pending` 误分类为 `plan_preview`
- 实体提取失败导致意向丢失

**边界模糊（~20%）— intent vs plan, 当前 vs 未来**
- "加入广东"在有方案/无方案时应走不同路径
- "仅保留江苏的学校"可以是偏好约束或方案筛选
- "把华中科技大学加到意向"在有/无 pending 时行为不同

---

## 第二部分：架构决策

### 4. 两种优化路线对比

#### 路线A：优化当前路由框架

保持三层路由架构，在 LLM 调用前加实体预处理层，给 TurnDecision 提供结构化输入，逐步移除关键词守卫。

```
用户消息 → 实体预处理(确定性) → TurnDecision(LLM, 结构化输入) → 30个tool → 后处理
```

#### 路线B：Coding Agent 范式

将用户状态物化为沙箱文件，Agent 通过读文件理解上下文、调用工具执行操作。不做预路由，不做后处理补丁。

```
用户消息 → Agent读取状态文件 → Agent理解需求 → Agent调用9个工具执行 → 工具内部做实体解析
```

#### 对比分析

| 维度 | 路线A（优化路由） | 路线B（Coding Agent） |
|------|------------------|---------------------|
| 路由错误 | 减少（更好的输入），不消除 | **消除**（不需要路由） |
| 实体识别错误 | 减少（预处理消歧） | **消除**（工具内部处理） |
| 系统prompt | ~15K tokens（仍需路由规则） | **~3K tokens**（无路由规则） |
| 新场景适配 | 新路由规则+消歧规则 | **新工具**（自然适配） |
| 补丁增长 | 减缓但不停止 | **结构性解决** |
| 状态一致性 | 多层解析可能不一致 | **单一来源**（文件即真相） |
| 迁移成本 | 低（增量改造） | 中（重新设计工具层） |
| 延迟影响 | 持平 | 持平（减少LLM调用次数抵消） |

#### 决策：选择路线B

核心理由：**路线A解决的是"怎么让 LLM 路由更准"，这是一个永远做不完的优化。路线B解决的是"为什么需要路由"，答案是不需要。**

Coding Agent 之所以能稳定工作（Claude Code、Cursor 已在大规模验证），是因为它不做预分类。它读代码文件理解上下文，理解用户需求，然后调用工具。志愿填报系统也可以这样：Agent 读状态文件理解当前情况，理解用户说的话，然后调用工具执行。工具内部做校验，错了就返回错误让 Agent 重试或澄清。

---

## 第三部分：Coding Agent 架构设计

### 5. 沙箱文件系统

#### 5.1 文件结构

每个会话拥有一个虚拟文件系统（内存中，由 Java 后端状态投影）：

```
/session/{session_id}/
├── score.json              # [只读] 成绩信息（不可变）          ~100B
├── profile.json            # [只读] 当前偏好和约束（版本化）     500-2000B
├── constraints.json        # [只读] 报考硬约束/软偏好            200-2000B
├── pending.json            # [只读] 待确认操作                  0-500B
├── meta.json               # [只读] 会话元信息                  ~100B
├── plan/
│   ├── summary.json        # [只读] 方案概况                    500-1500B
│   ├── items.json          # [只读] 完整志愿列表（按需加载）      5-50KB
│   ├── candidates.json     # [只读] 候选池（按需加载）            5-100KB
│   └── review.json         # [只读] 审查结果                    1-10KB
└── knowledge/
    └── (专业/学校目录索引，通过 search_catalog 工具访问)
```

所有文件对 Agent 是**只读**的。Agent 不直接写文件。所有写操作通过工具→Java 后端 API→后端更新状态→沙箱文件失效→下次读取时重新获取。

#### 5.2 文件 Schema 定义

**`score.json`** — 学生成绩（不可变）
```json
{
  "province": "广东",
  "total_score": 580,
  "subject_list": ["物理", "化学", "生物"],
  "sex": "男",
  "volunteer_model": "majorGroup",
  "batch": "01"
}
```

**`profile.json`** — 当前偏好（版本化，变更 2-5 次/会话）
```json
{
  "version": 3,
  "positive": {
    "majors": {"level1": [], "level2": ["计算机类"], "level3": ["软件工程"]},
    "schools": ["华南理工大学"],
    "regions": {"province": ["广东", "北京"], "area": ["南方"]},
    "career": ["market_employment"]
  },
  "negative": {
    "majors": {"level1": ["医学"], "level2": [], "level3": []},
    "schools": [],
    "regions": {"province": [], "area": []}
  },
  "constraints": {
    "only_keep": null,
    "must_have": null,
    "tuition_max": null
  },
  "strength_subjects": ["数学", "物理"]
}
```

**`plan/summary.json`** — 方案概况（版本化，变更 3-10 次/会话）
```json
{
  "version": 12,
  "phase": "PLAN_IDLE",
  "ordered_total": 45,
  "ordered_target": 45,
  "tier_counts": {"冲": 12, "稳": 18, "保": 15},
  "review": {
    "risk_count": 2,
    "warn_count": 3,
    "risk_summaries": ["高收费风险：3个志愿年学费超2万", "梯度断层：保底区间有间隙"]
  },
  "sample_schools": ["华南理工大学", "暨南大学", "深圳大学"]
}
```

**`plan/items.json`** — 完整志愿列表（按需加载，5-50KB）
```json
{
  "version": 12,
  "total": 45,
  "items": [
    {
      "position": 1,
      "volunteer_id": "10561_0805_001",
      "school_name": "华南理工大学",
      "major_name": "软件工程",
      "major_group_name": "第01组",
      "tier": "冲",
      "admission_ratio": 0.35,
      "tuition_per_year": 6850,
      "tags": ["985", "双一流"],
      "school_nature": "公办"
    }
  ]
}
```

**`pending.json`** — 待确认操作
```json
// 无 pending 时
{"active": false}

// 有 pending 时
{
  "active": true,
  "kind": "plan_mutation",
  "action_family": "remove_units",
  "preview_summary": "移出3个高收费志愿（年学费超2万）",
  "affected_scope": "涉及第8、12、23位志愿",
  "source_version": 12,
  "created_turn": 5,
  "max_age_turns": 3
}
```

#### 5.3 同步协议

```python
class SandboxFileCache:
    """会话级虚拟文件缓存，版本驱动失效。"""

    async def read(self, path: str) -> dict:
        """读取文件。未缓存或已失效时从后端拉取。"""
        if path not in self._cache or self._is_stale(path):
            self._cache[path] = await self._fetch_from_backend(path)
        return self._cache[path]

    def invalidate(self, paths: list[str]):
        """写操作成功后，失效受影响的文件。"""
        for path in paths:
            self._cache.pop(path, None)
```

**失效规则：**

| 触发事件 | 失效文件 |
|---------|---------|
| 偏好确认 | `profile.json`, `constraints.json`, `plan/candidates.json` |
| 方案变更 | `plan/summary.json`, `plan/items.json`, `plan/review.json`, `pending.json` |
| 方案生成 | 所有 `plan/*` 文件 |
| 审查运行 | `plan/review.json`, `plan/summary.json` |
| Pending 创建/清除 | `pending.json`, `meta.json` |

### 6. 工具设计（9个工具）

#### 6.1 工具总览

| 工具 | 类型 | 替代的现有工具 |
|------|------|--------------|
| `read_state` | 读取 | 隐式状态读取（分散在所有工具中） |
| `explore_topic` | 分析 | 6个 analyze/explore 工具 |
| `compare_entities` | 分析 | 5个 compare/info 工具 + 2个 score query 工具 |
| `query_plan` | 查询 | `query_volunteer_plan`, `collect_plan_context_inputs` |
| `preview_intent_change` | 预览 | 5个 intent preview 工具 |
| `preview_plan_action` | 预览 | `plan_next_action` + `execute_plan_action`(preview) |
| `confirm_pending` | 执行 | pending 确认协议 (service.py 中的逻辑) |
| `answer_policy` | 查询 | 3个 policy/search/match 工具 |
| `review_plan` | 分析 | `execute_plan_action`(review) + fix proposal 生成 |

#### 6.2 工具详细设计

##### `read_state` — 读取沙箱文件

```python
async def read_state(
    ctx: RunContext[SessionContext],
    path: str,           # "plan/summary.json", "profile.json" 等
    query: str | None,   # 过滤表达式: "tier=保 and tuition > 20000"
) -> str
```

- **实体解析**：无（纯读取）
- **后端 API**：`get_planning_workspace_state`, `get_planning_state`, `get_user_profile` 等
- **错误处理**：无方案时返回 `{"error": "not_found", "hint": "还没有生成方案"}`

##### `explore_topic` — 方向/适配/兴趣分析

```python
async def explore_topic(
    ctx: RunContext[SessionContext],
    topic_type: Literal["career", "school", "major", "region", "interest_profile"],
    user_question: str,
    entities: list[str] | None,
    include_plan_context: bool,
) -> str
```

- **实体解析**：工具内部调用 `resolve_major_entity` / `resolve_school_entity`。歧义时返回候选列表让 Agent 问用户。
- **后端 API**：`get_major_profile_by_name`, `get_school_profile_by_name`, `get_planning_state`
- **替代**：`analyze_current_career_direction`, `analyze_current_interest_profile`, `analyze_current_major_interest`, `analyze_current_region_interest`, `analyze_current_school_interest`, `analyze_current_interest`

##### `compare_entities` — 学校/专业对比

```python
async def compare_entities(
    ctx: RunContext[SessionContext],
    entity_type: Literal["major", "school"],
    entities: list[str],       # 2-5个实体名
    comparison_focus: str | None,  # "就业", "课程", "录取难度"
) -> str
```

- **实体解析**：模糊匹配 + 别名表。无法解析时返回澄清请求。
- **替代**：`compare_majors`, `compare_majors_adhoc`, `compare_major_options`, `compare_schools`, `compare_schools_adhoc`, `get_major_introduction`, `get_major_introductions`, `get_school_introduction`

##### `query_plan` — 方案/候选查询

```python
async def query_plan(
    ctx: RunContext[SessionContext],
    scope: Literal["plan", "candidates", "both"],
    filters: dict | None,  # {"school": "华南理工", "tier": "保", "tuition_max": 20000}
    question: str | None,
    limit: int = 20,
) -> str
```

- **实体解析**：过滤条件中的学校/专业名模糊匹配，省份名归一化
- **无方案时**：返回 `{"has_plan": false, "guidance": "还没有生成方案"}`
- **替代**：`query_volunteer_plan`, `collect_plan_context_inputs`（部分）

##### `preview_intent_change` — 预览偏好变更

```python
async def preview_intent_change(
    ctx: RunContext[SessionContext],
    intent_type: Literal["major", "school", "region", "career"],
    positive: dict | None,     # {"level2": ["计算机类"]}
    negative: dict | None,     # {"level1": ["医学"]}
    constraint_type: Literal["preference", "only_keep", "must_have", "exclude"],
    raw_user_text: str,
) -> str
```

- **实体解析**：所有实体名在工具内部归一化。"医学" → level1 门类。歧义返回候选列表。
- **极性处理**：Agent 通过参数明确传入 positive/negative，工具不猜极性。
- **返回**：预览卡数据 + 对方案的影响分析 + 创建 pending
- **替代**：5个 `preview_current_*_intent_confirmation` 工具

##### `preview_plan_action` — 预览方案变更

```python
async def preview_plan_action(
    ctx: RunContext[SessionContext],
    action: Literal["add", "remove", "move", "replace", "sort", "generate", "regenerate_order"],
    targets: list[str] | None,       # volunteer_id 或描述性引用
    target_position: int | None,
    filters: dict | None,            # 批量操作过滤条件
    goal_type: str | None,           # "only_keep_scope", "exclude_scope"
    goal_scopes: list[dict] | None,  # [{"entity_type": "major_level1", "values": ["医学"]}]
    raw_user_text: str,
) -> str
```

- **实体解析**：`targets` 可以是 volunteer_id、"华南理工大学.软件工程"、"第3个" 等。工具内部通过 `resolve_school_major_ref` 和位置查找解析。
- **返回**：变更预览 + 梯度影响 + 创建 pending
- **替代**：`plan_next_action`, `execute_plan_action`(preview), `generate_planning_fix_proposals`

##### `confirm_pending` — 确认/取消待确认操作

```python
async def confirm_pending(
    ctx: RunContext[SessionContext],
    action: Literal["confirm", "cancel"],
) -> str
```

- **版本守护**：执行前检查 `source_version` 与当前后端版本。版本漂移时清除过期 pending 并返回错误。
- **替代**：service.py 中分散的 pending 确认协议

##### `answer_policy` — 回答报考政策问题

```python
async def answer_policy(
    ctx: RunContext[SessionContext],
    question: str,
    rule_domain: str | None,    # "score_batch", "eligibility", "tuition_budget"
    school_name: str | None,
) -> str
```

- **只读**：不修改任何状态
- **替代**：`answer_admission_policy_question`, `search_official_admission_sources`, `match_admission_rule_to_student`

##### `review_plan` — 运行方案审查

```python
async def review_plan(
    ctx: RunContext[SessionContext],
    focus: Literal["full_review", "risk_only", "tier_balance", "tuition", "career_fit"] | None,
    generate_fix_proposals: bool,
) -> str
```

- **返回**：风险项 + 严重度 + 影响志愿 + 修复建议（如果 `generate_fix_proposals=True`）
- **替代**：review 相关的 `execute_plan_action` 操作 + `generate_planning_fix_proposals`

#### 6.3 实体解析策略

**原则：所有实体解析在工具内部完成。Agent 传原始文本或半结构化名称，工具负责归一化和消歧。**

歧义处理标准返回格式：
```json
{
  "status": "ambiguous",
  "input": "计算机",
  "candidates": [
    {"canonical": "计算机类", "level": "level2", "type": "category"},
    {"canonical": "计算机科学与技术", "level": "level3", "type": "major"}
  ],
  "suggestion": "你说的计算机是指计算机类（包含多个专业）还是计算机科学与技术这个具体专业？"
}
```

Agent 收到歧义结果后询问用户，而不是猜测。这从根本上消除了当前系统中"静默使用第一个候选"的问题。

**极性/否定处理**：
- Agent 负责理解自然语言中的极性（LLM 擅长这个）
- Agent 通过参数明确传入 `positive`/`negative`
- 工具不猜极性，只做实体归一化
- 双重否定（"不要排除X"→ positive）由 Agent 在调用工具前判断

**ASR/口语纠错**：
- 工具内部做模糊匹配（Levenshtein距离 + 拼音匹配）
- 无法匹配时返回 `{"status": "no_match", "did_you_mean": ["高收费"]}`
- Agent 向用户确认纠正结果

### 7. 系统 Prompt 设计

目标大小：~3-5KB（对比当前 ~22K tokens）

```
你是高考志愿填报顾问孙成老师，拥有17年咨询经验。你通过对话帮助学生理解方向、
整理意向、生成和调整志愿方案。

## 你的工作方式

你有一个会话沙盒，包含学生的所有状态信息。先读取状态，理解现状，再决定行动。

可用文件：
- score.json: 成绩（省份、总分、选科、性别）
- profile.json: 当前偏好（正面/负面 × 专业/学校/地域/职业方向）
- plan/summary.json: 方案概况（数量、梯度分布、审查风险）
- plan/items.json: 完整志愿列表
- plan/candidates.json: 候选池
- plan/review.json: 审查结果
- constraints.json: 报考约束
- pending.json: 待确认操作

## 行动原则

1. 先读后做：回答需要方案/偏好事实时，先 read_state 确认。
2. 只读回答：分析、对比、政策解释、查询，直接回答，不改状态。
3. 预览才改：变更偏好或方案必须先 preview，等用户确认后 confirm。
4. 工具处理实体：不确定的专业/学校/地域名传给工具，工具内部消歧。
5. 极性判断：
   - "不要X" → negative
   - "不要排除X" → positive（双重否定）
   - "只保留X" → positive + constraint_type="only_keep"

## 回复风格

- 自然中文，不用 emoji
- 确认前不说"已记录/已调整/已执行"
- 偏好未确认时说"确认前不会生效"
- 查询先给结论句
- 分析保留结构但不超过4个要点
- 不强迫选择，不用命令式话术
- 禁用术语：payload, stage, action_family, volunteerId, 草稿, 候选池, 自动修复
```

**与当前系统对比：**
- 当前：~22K tokens，79% 是路由规则
- 新设计：~3K tokens，0% 路由规则
- 删除的内容：tool_dispatch_rules.py 的全部 112行密集路由指令

### 8. Agent 循环设计

#### 8.1 消息处理管道

```
用户消息到达 (WebSocket)
  │
  ▼
[1. 加载上下文] (~200ms, 并行)
  ├── 从后端获取 score, profile, planning workspace, pending
  ├── 填充沙箱文件缓存
  └── 从 SQLite 加载对话历史
  │
  ▼
[2. 注入到 Agent]
  ├── 系统 prompt (3KB, 静态)
  ├── 沙箱摘要 (score + plan/summary 概要, ~300 tokens)
  ├── 对话历史 (滑动窗口, 最近20轮)
  └── 用户消息
  │
  ▼
[3. Agent 循环] (标准 Pydantic AI agent.iter())
  ├── Agent 按需 read_state 读取详细状态
  ├── Agent 调用工具执行操作
  ├── 工具内部做实体解析+后端API调用
  └── Agent 生成最终回复
  │
  ▼
[4. 输出处理] (~50ms, 最小化)
  ├── 内部术语安全网过滤 (保留但不作为主要防线)
  ├── 持久化对话历史
  └── WebSocket 发送回复
```

#### 8.2 关键变化：无预路由、无后处理补丁

| 环节 | 当前系统 | 新系统 |
|------|---------|--------|
| 预路由 | 关键词守卫 + TurnDecision LLM | **无** |
| 路由决策 | 37KB system prompt + 30 tools | Agent 读状态文件自行判断 |
| 后处理 | 幻觉检测、风格修正、极性修补 | 内部术语过滤（安全网） |
| LLM 调用次数 | 1-3次预路由 + 1-4次工具调用 | 0次预路由 + 1-4次工具调用 |

#### 8.3 确认协议

```
轮次N: 用户说 "不要医学类"
  Agent 调用 read_state("profile.json") → 当前无医学排除
  Agent 调用 read_state("plan/summary.json") → 方案有45个志愿
  Agent 调用 preview_intent_change(
      intent_type="major",
      negative={"level1": ["医学"]},
      constraint_type="exclude"
  )
  工具: 归一化"医学"为level1门类 → 检查方案影响(5个受影响) → 创建pending
  Agent 回复: "整理了一下：排除医学门类后，当前方案里有5个志愿会被影响。
              确认的话点击采纳按钮。"

轮次N+1: 用户点击确认按钮（或输入"确认"）
  Agent 调用 read_state("pending.json") → 有活跃 intent_change pending
  Agent 调用 confirm_pending(action="confirm")
  工具: 版本检查 → 应用到后端 → 清除pending → 失效相关沙箱文件
  Agent 调用 read_state("plan/summary.json") → 方案现在40个
  Agent 回复: "已采纳。医学门类已排除，方案从45个调整为40个。"
```

#### 8.4 Pending 状态机（简化版）

```
IDLE ──preview_intent_change/preview_plan_action──→ PREVIEWING
                                                        │
                              ┌──confirm_pending(confirm)──→ 执行 → IDLE
                              │
                              ├──confirm_pending(cancel)────→ 清除 → IDLE
                              │
                              ├──3轮未操作────────────────→ 自动过期 → IDLE
                              │
                              ├──新preview请求──────────→ 替换旧pending → PREVIEWING
                              │
                              └──版本漂移检测─────────→ 自动失效 → IDLE
```

对比当前系统：
- 当前：pending 状态在 Python agent 和 Java backend 双端维护，`proposal_compiler.py` 5650行处理各种边界
- 新设计：pending 状态仅在 Java backend（权威源），沙箱文件是只读投影，`confirm_pending` 工具做版本守护

### 9. 迁移方案

#### 阶段一：基础设施（2周）

**交付物：**
- `app/sandbox/file_cache.py` — 虚拟文件系统 + 版本失效
- `app/sandbox/backend_adapter.py` — 文件路径 → 后端 API 映射
- `app/coding_agent/tools.py` — 9个新工具定义（存根，委托现有实现）
- `app/coding_agent/prompt.py` — 新系统 prompt
- `app/coding_agent/agent.py` — 新 Agent 类

**复用的现有代码：**
- `app/domain/major_entity_resolver.py` (661行) — 完整复用
- `app/domain/school_entity_resolver.py` (212行) — 完整复用
- `app/domain/region_entity_resolver.py` (304行) — 完整复用
- `app/util/internal_client.py` — 全部后端调用复用
- `app/data/` — 静态数据文件复用

#### 阶段二：工具实现（3周）

**交付物：**
每个工具的完整实现，内部复用现有领域逻辑：

| 新工具 | 复用的现有实现 |
|--------|-------------|
| `read_state` | `internal_client.py` 的 get_* 系列 API |
| `explore_topic` | `explore_direction_tool.py` 核心分析逻辑 |
| `compare_entities` | `major_compare_tool.py`, `school_compare_tool.py` 对比逻辑 |
| `query_plan` | `planning_workflow_tool.py` 查询函数 |
| `preview_intent_change` | `intent_state_tool.py` 意向分析 + `intent_preview_tool.py` 预览生成 |
| `preview_plan_action` | `plan_execution_tool.py` 执行逻辑 + `plan_orchestration_tool.py` 编排 |
| `confirm_pending` | 新实现，调用现有后端 API |
| `answer_policy` | `admission_policy_tool.py` + `official_source_search_tool.py` |
| `review_plan` | `planning_workflow_tool.py` 审查函数 |

**不复用的现有代码：**
- `service.py` (18,279行) — 替换
- `proposal_compiler.py` (5,650行) — 移除
- `turn_decision_tool.py` (514行) — 移除
- `tool_dispatch_rules.py` (117行) — 移除
- `plan_orchestration_tool.py` (1,234行) — 移除（逻辑内联到 `preview_plan_action`）
- `plan_semantic_action_tool.py` (855行) — 移除

#### 阶段三：Shadow Diff 验证（2周）

**交付物：**
- Shadow runner：新旧系统并行运行，记录差异
- 回归测试适配：320+ 测试用例跑新系统
- Diff 分析报告

**验证指标：**

| 指标 | 当前基线 | 目标 |
|------|---------|------|
| 实体类型混淆率 | ~35% | <5% |
| 路由方向错误率 | ~30% | <3% |
| 极性错误率 | ~15% | <2% |
| P95 延迟 | ~12s (复杂场景) | <8s |
| 非预期状态修改 | 偶发 | 0 (硬门禁) |

#### 阶段四：生产切换（1周）

**交付物：**
- 功能开关：`use_coding_agent=true/false`（会话级）
- 渐进放量：1% → 5% → 20% → 50% → 100%
- 监控仪表盘
- 回滚流程

**可删除的代码（切换稳定后）：**

| 文件 | 行数 | 说明 |
|------|------|------|
| `service.py` | 18,279 | 单体编排层 |
| `proposal_compiler.py` | 5,650 | 规则引擎 |
| `turn_decision_tool.py` | 514 | 预路由分类器 |
| `tool_dispatch_rules.py` | 117 | 路由规则 |
| `plan_orchestration_tool.py` | 1,234 | 方案编排 |
| `plan_semantic_action_tool.py` | 855 | 语义动作分类器 |
| 关键词守卫常量 | ~300 | service.py 中的标记列表 |
| **合计** | **~27,000** | |

**保留的代码：**
- `app/domain/` — 实体解析器（内联到新工具中）
- `app/util/internal_client.py` — 后端 HTTP 客户端
- `app/data/` — 静态数据文件
- `app/sync/state_sync.py` — 版本检查逻辑（适配到 SandboxFileCache）

### 10. Agent 循环控制：防止工具乱试

#### 10.1 问题根因

在 3.2.0 使用 Pydantic AI full agent 模式时，观察到 Agent 频繁反复调用工具（"工具乱试"），即使用户意图非常确定。根因分析如下：

| 根因 | 说明 | 当前系统表现 |
|------|------|------------|
| **工具语义重叠** | 30个工具中多个可响应同一意图，Agent 不确定选哪个就逐个尝试 | `analyze_current_major_interest` vs `compare_majors` vs `get_major_introduction` 对"这个专业适合我吗"都可能被选中 |
| **缺少终止信号** | 工具返回结果后，Agent 不知道"够了可以回复用户了"还是"需要继续调用" | `tool_reply_policy.py` 的 4 种策略中，大多数工具返回 `continue_model`，Agent 倾向于继续调用 |
| **缺乏状态前置知识** | Agent 不知道当前方案/偏好状态，只能通过调工具"摸索"上下文 | 第一步调 `query_state` 看方案，第二步调 `analyze_current_interest` 看偏好，第三步才开始处理用户问题 |

#### 10.2 机制一：状态前置注入

**原理**：在每轮对话前，将核心状态摘要直接注入到用户消息上方，Agent 不需要"先摸底再干活"。

```python
def build_turn_context(sandbox: SandboxFileCache) -> str:
    """构造每轮注入的状态摘要，~300 tokens。"""
    score = sandbox.read_cached("score.json")
    profile = sandbox.read_cached("profile.json")
    plan = sandbox.read_cached("plan/summary.json")
    pending = sandbox.read_cached("pending.json")

    lines = []
    lines.append(f"成绩：{score['province']} {score['total_score']}分 {'/'.join(score['subject_list'])}")

    if profile.get("positive") or profile.get("negative"):
        pos = profile.get("positive", {})
        neg = profile.get("negative", {})
        if pos.get("majors"):
            lines.append(f"偏好专业：{_compact(pos['majors'])}")
        if neg.get("majors"):
            lines.append(f"排除专业：{_compact(neg['majors'])}")
        if pos.get("regions"):
            lines.append(f"偏好地域：{_compact(pos['regions'])}")

    if plan.get("ordered_total", 0) > 0:
        lines.append(f"方案：{plan['ordered_total']}个志愿 "
                     f"(冲{plan['tier_counts'].get('冲',0)}/"
                     f"稳{plan['tier_counts'].get('稳',0)}/"
                     f"保{plan['tier_counts'].get('保',0)})")
        if plan.get("review", {}).get("risk_count", 0) > 0:
            lines.append(f"风险：{plan['review']['risk_count']}项")
    else:
        lines.append("方案：尚未生成")

    if pending.get("active"):
        lines.append(f"待确认：{pending['preview_summary']}")

    return "\n".join(lines)
```

**效果**：Agent 在第一次推理时就知道"有方案、45个志愿、2个风险"，不需要先调 `read_state` 摸底。对于"加入广东和江西"这种消息，Agent 直接看到"方案：尚未生成"就知道走偏好而非方案修改。

**对比当前系统**：当前 `planning_context.py` 也注入了方案上下文，但信息分散在多个 instruction 段中（~800-3000 tokens），且与 37KB 路由规则混在一起，Agent 往往被路由规则的权重压过，仍然先调工具确认。

#### 10.3 机制二：工具返回 `next_step` 终止信号

**原理**：每个工具的返回值中包含 `next_step` 字段，明确告诉 Agent 下一步该做什么。

```python
class ToolResult(TypedDict):
    data: Any           # 工具返回的业务数据
    next_step: Literal[
        "respond",      # 直接用这个结果回复用户，不要再调工具
        "confirm",      # 展示预览并等待用户确认
        "clarify",      # 有歧义，需要问用户澄清
        "continue",     # 可以继续调用其他工具补充信息（罕见）
    ]
    message: str | None # 可选的面向用户的摘要
```

**各工具的 `next_step` 映射：**

| 工具 | 正常返回 | 歧义返回 |
|------|---------|---------|
| `read_state` | `respond` 或 `continue`（取决于是否为独立查询） | — |
| `explore_topic` | `respond` | — |
| `compare_entities` | `respond` | `clarify`（实体不明确） |
| `query_plan` | `respond` | — |
| `preview_intent_change` | `confirm` | `clarify`（实体歧义） |
| `preview_plan_action` | `confirm` | `clarify`（目标不明确） |
| `confirm_pending` | `respond` | — |
| `answer_policy` | `respond` | — |
| `review_plan` | `respond` | — |

**对比当前系统**：当前 `tool_reply_policy.py` 有 4 种策略（`continue_model` / `direct_reply` / `direct_blocking` / `preview_wait_confirm`），但判断逻辑复杂（396行），且大多数工具返回 `continue_model`，没有给 Agent 明确的"停下来"信号。新设计将终止信号**内置到工具返回值**中，Agent 自然遵从。

#### 10.4 机制三：硬性工具调用上限

**原理**：每轮对话设置硬性工具调用上限，超过上限后强制终止 Agent 循环。

```python
MAX_TOOL_CALLS_PER_TURN = 3

async def run_agent_loop(agent, user_message, context):
    tool_call_count = 0
    async with agent.iter(user_message, deps=context) as agent_run:
        async for node in agent_run:
            if isinstance(node, ToolCallNode):
                tool_call_count += 1
                if tool_call_count > MAX_TOOL_CALLS_PER_TURN:
                    # 强制终止：用已有的工具结果生成回复
                    return agent_run.force_respond_with_collected()
            # ... 正常处理
```

**为什么 3 次够用**：

| 典型场景 | 工具调用序列 | 次数 |
|---------|------------|------|
| "这个专业适合我吗" | `explore_topic` | 1 |
| "不要医学类" | `read_state("plan/summary.json")` → `preview_intent_change(...)` | 2 |
| "审查一下方案" | `review_plan(...)` | 1 |
| "把第3个移到第1位" | `preview_plan_action(action="move", ...)` | 1 |
| "加入广东和江西"（需确认状态） | `read_state("plan/summary.json")` → `preview_intent_change(...)` | 2 |

在状态前置注入（机制一）的支持下，Agent 已经不需要"先摸底"的那 1-2 次调用。绝大多数场景 1-2 次工具调用即可完成。

**对比当前系统**：当前 `base_agent.py` 的 `_TOOL_REPEAT_LIMITS` 只限制同一个工具的重复次数，不限制总次数。Agent 可以在一轮中调 `analyze_current_major_interest` → `compare_majors` → `get_major_introduction` → `query_volunteer_plan` 各一次（4次不同工具），每次都合规但整体是乱试。

#### 10.5 机制四：9个正交工具（消除语义重叠）

**原理**：当前 30 个工具中存在大量语义重叠，是 Agent 乱试的直接诱因。新设计将工具缩减到 9 个，每个工具覆盖一个独立的意图空间，不存在"两个工具都能处理这个需求"的情况。

**语义重叠消除示例：**

| 用户意图 | 当前系统（多个候选） | 新系统（唯一映射） |
|---------|-------------------|------------------|
| "计算机适合我吗" | `analyze_current_major_interest` / `compare_majors` / `get_major_introduction` | `explore_topic(topic_type="major")` |
| "不要医学" | `preview_current_major_intent_confirmation` / `plan_next_action(remove_units)` | `preview_intent_change(intent_type="major", negative=...)` |
| "方案里有民办吗" | `query_volunteer_plan` / `execute_plan_action(query_state)` / `review_plan` | `query_plan(scope="plan", filters={"school_nature": "民办"})` |
| "考公方向怎么看" | `analyze_current_career_direction` / `analyze_current_interest_profile` | `explore_topic(topic_type="career")` |

每个工具的职责边界清晰，Agent 不需要 37KB 的路由规则来判断"该调哪个"。

#### 10.6 机制五：协议事件确定性快捷路径

**原理**：对于协议级事件（非自然语言，而是 UI 操作触发的结构化消息），不经过 Agent 循环，直接走确定性处理。

```python
DETERMINISTIC_EVENTS = {
    "pending_confirm_click":  lambda ctx: confirm_pending(ctx, action="confirm"),
    "pending_cancel_click":   lambda ctx: confirm_pending(ctx, action="cancel"),
    "pending_expired":        lambda ctx: expire_pending(ctx),
    "card_button_action":     lambda ctx: execute_card_action(ctx),
}

async def handle_message(session, message):
    # 协议事件：直接处理，不进 Agent
    if message.event_type in DETERMINISTIC_EVENTS:
        return await DETERMINISTIC_EVENTS[message.event_type](session.context)

    # 自然语言：走 Agent 循环
    return await run_agent_loop(agent, message.text, session.context)
```

**对比当前系统**：当前系统中，卡片按钮点击也要经过 `service.py` 的 `_classify_active_pending_turn_decision()` 分类，可能被 TurnDecision 误判为新的意图表达，导致 pending 被错误清除或覆盖。

#### 10.7 五机制联动效果

| 问题 | 当前系统应对 | Coding Agent 应对 |
|------|------------|------------------|
| Agent 不知道当前状态，先摸底 | 无解决方案，Agent 总要先调 1-2 个工具探路 | **状态前置注入**：核心状态在 system prompt 中，0 次探路调用 |
| 工具返回后 Agent 不知道该停还是继续 | `tool_reply_policy.py` (396行) 试图在外部判断 | **next_step 信号**：工具自己说"respond"或"confirm"，Agent 自然停止 |
| Agent 在一轮中调用过多工具 | `_TOOL_REPEAT_LIMITS` 只限同一工具的重复 | **硬上限 3 次**：超过就强制用已有结果回复 |
| 多个工具可以处理同一意图 | 37KB 路由规则试图指导选择 | **9个正交工具**：每个意图只有一个对应工具 |
| UI 操作被当作自然语言处理 | 关键词守卫 + TurnDecision 分类 | **确定性快捷路径**：协议事件不进 Agent 循环 |

---

## 附录 A：架构对比总图

```
┌─────────────────────────────────────────────────────────────────┐
│  当前架构 (v3.2.0)                                              │
│                                                                 │
│  用户消息                                                        │
│    ↓                                                            │
│  [关键词守卫] ←── 400行规则 ←── _READONLY_MARKERS 等             │
│    ↓ (没短路)                                                    │
│  [TurnDecision LLM] ←── 300行prompt (20 schemaRules, 18 hardR) │
│    ↓ (没短路)                                                    │
│  [全Agent] ←── 37KB路由规则 + 30个tools                          │
│    ↓                                                            │
│  [proposal_compiler] ←── 5650行补丁                              │
│    ↓                                                            │
│  [回复守卫] ←── 幻觉检测 + 风格修正 + 术语清理                     │
│    ↓                                                            │
│  回复                                                            │
│                                                                 │
│  系统prompt: ~22K tokens | 工具: 30个 | 路由决策: 3层竞争          │
└─────────────────────────────────────────────────────────────────┘

                            ↓ 迁移 ↓

┌─────────────────────────────────────────────────────────────────┐
│  目标架构 (Coding Agent)                                         │
│                                                                 │
│  用户消息                                                        │
│    ↓                                                            │
│  [加载沙箱] ←── 并行拉取后端状态，填充虚拟文件                      │
│    ↓                                                            │
│  [Agent 循环]                                                    │
│    ├── read_state("plan/summary.json") → 理解当前方案状态          │
│    ├── read_state("profile.json") → 理解当前偏好                  │
│    ├── (Agent 自主推理：用户想做什么)                               │
│    ├── 调用合适的工具 (工具内部做实体解析+校验)                      │
│    └── 生成回复                                                   │
│    ↓                                                            │
│  [术语安全网] ←── 最小化过滤（安全网，不是主要防线）                  │
│    ↓                                                            │
│  回复                                                            │
│                                                                 │
│  系统prompt: ~3K tokens | 工具: 9个 | 路由决策: 0层（Agent自主）    │
└─────────────────────────────────────────────────────────────────┘
```

## 附录 B：典型场景对比

### 场景1："加入广东和江西"（无正式方案）

**当前系统：**
1. 关键词守卫：检测到"加入"在 `_PLAN_STYLE_GUARD_PROMPT_KEYWORDS` 中
2. TurnDecision：分类为 `taskLayer=plan, sideEffect=plan_preview`（错误）
3. `_should_defer_runtime_intent_hard_cut_to_current_plan_action()`: 检测到无方案，尝试纠正
4. `content_has_future_reference_anchor()`: 检查是否有未来引用标记
5. 最终仲裁：可能走 intent_pending 也可能走 plan_preview（不确定）

**Coding Agent：**
1. Agent 调用 `read_state("plan/summary.json")` → `{"phase": "EXPLORE", "ordered_total": 0}`
2. Agent 看到没有方案，理解"加入广东和江西"是偏好表达
3. Agent 调用 `preview_intent_change(intent_type="region", positive={"province": ["广东", "江西"]})`
4. 工具归一化地域名，创建 pending，返回预览
5. 完成。无路由冲突。

### 场景2："不要排除经济学类"

**当前系统：**
1. `intent_polarity.py`: `has_double_negation()` 检测双重否定 → 但可能在 intent tool 执行前没被调用
2. LLM 可能将"经济学类"放入 `negative` 参数（忽略"不要排除"）
3. 后处理发现极性错误 → 但可能没有对应的补丁

**Coding Agent：**
1. Agent 理解"不要排除" = 双重否定 = 正面（LLM 擅长理解自然语言否定）
2. Agent 调用 `preview_intent_change(intent_type="major", positive={"level2": ["经济学类"]}, constraint_type="preference")`
3. 工具内部归一化"经济学类"为 level2
4. 完成。Agent 做语义理解，工具做实体归一化。

### 场景3："建议考公吗"

**当前系统：**
1. LLM 可能生成 `偏好专业：考公`（将 career direction 误识为 major）
2. 后处理没有针对性补丁
3. 错误被写入偏好

**Coding Agent：**
1. Agent 理解这是一个探索性问题（"建议...吗" = 咨询，不是设置偏好）
2. Agent 调用 `explore_topic(topic_type="career", user_question="建议考公吗")`
3. 工具返回考公方向的分析
4. 即使 Agent 误判要设置偏好，调用 `preview_intent_change(intent_type="career", ...)` 时，工具内部会将"考公"识别为 career 方向而非专业
5. 双重保障：Agent 语义理解 + 工具类型校验
