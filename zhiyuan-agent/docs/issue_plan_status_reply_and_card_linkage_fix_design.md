# Issue 修复设计：方案现状回复单薄与无联动卡片

> Status: Implemented, product-structure WebSocket validation added, pending full frontend regression
> Owner: agent / web 联调
> Created: 2026-05-05
> Scope: 快捷回复“看看现在的方案”、方案状态查询 `query_state`、工作台 followup 卡片

## 1. Issue 描述

### 1.1 现象一：快捷回复“看看现在的方案”回复过于单薄

用户在前端点击快捷回复“看看现在的方案”后，系统返回内容类似：

```text
方案情况如下：

已填满 45 个志愿（目标 45 个）；冲稳保分布：冲18 / 稳13 / 保14；审查暂无明显风险；方案前几个志愿：石家庄铁道大学四方学院第01组-会计学...@1、北京中医药大学东方学院第01组-中医学...@2；偏好匹配：当前偏好/要求：偏好专业=财政学类,经济学类,法学类；排除专业=中西医结合类,护理学类；偏好地域=内蒙古,北京,天津。

承接情况：当前方案里较贴近的有27个，明显冲突的有0个。
贴近偏好：北京中医药大学东方学院第01组-中医学...@2（匹配偏好专业:中医学类）
```

主要问题：

- 结构像工具日志或后端摘要，不像面向用户的规划说明。
- 前排志愿用 `学校-专业(冲)@1` 这类内部格式展示
- 专业备注、办学地点、色觉限制等长文本直接堆在一句里
- 偏好承接以“承接情况 / 贴近偏好”拼接输出，缺少用户可扫读的结构
- 回复没有解释“这个方案现在好在哪里、需要看哪里、下一步怎么做”

### 1.2 现象二：部分卡片没有联动效果

用户在对话中输入某些内容后会触发 `planningWorkspaceAction` 卡片，但部分卡片点击后只是打开/刷新已有工作台视图，没有产生可感知的新结果或定位变化。

这类卡片的问题：

- 用户以为卡片代表一次可操作结果，但点击后看不到增量。
- 只读查询场景也可能追加“打开排序方案 / 打开审查结果”卡片，造成噪音。
- 后续还会提供两个具体无联动卡片样例，需要纳入修复判断。

## 2. 影响范围

已确认涉及：

- `zhiyuan-web` 快捷回复配置：`看看现在的方案`
- `zhiyuan-agent` planning 查询链路：`query_state`
- `zhiyuan-agent` service followup 卡片追加逻辑
- `status_overview` 兜底回复逻辑

可能涉及：

- `query_ordered/query_draft/query_candidates` 的 view-only 工作台卡片
- 前端 `MessageList` 对 `planningWorkspaceAction` 的展示和点击行为
- 对话回归中对 followup target 的断言

不直接涉及：

- 方案生成、排序、审查算法本身
- 用户画像/偏好写入逻辑
- WebSocket 协议结构大改

## 3. 修复目标

- 快捷回复“看看现在的方案”输出结构化、可扫读、面向用户的方案现状说明。
- 去掉或收敛没有实际联动效果的工作台卡片，尤其是只读查询场景。
- 保留真正有价值的卡片：方案生成、调整、复审、候选库刷新、确认后变更等。
- 建立可回归的测试覆盖，避免后续再次退化为字符串拼接。
- 更新 changelog 和相关文档，形成可追踪的交付记录。

## 4. 非目标

- 不重做前端卡片渲染协议。
- 不改变现有 WebSocket 消息基础结构。
- 不改变方案生成、排序、审查、候选池业务逻辑。
- 不在本次把全部 planning 回复升级为富内容协议，只治理当前暴露明显的方案现状与无效卡片问题。

## 5. 根因分析

### 5.1 快捷回复入口

前端 `sessionDetailV2` 中配置快捷回复：

- label: `看看现在的方案`
- messageText: `看看现在的方案`

消息发送后进入 agent 主链路，意图通常会被规划成 `query_state`。

### 5.2 回复生成链路

`query_state` handler 会读取：

- planningState 轻量摘要
- ordered plan 或 draft plan 明细
- review summary
- intent relation facts

随后生成 `PlanExecutionResult`：

- `result_kind=status_overview`
- `summary/state_summary` 为当前方案摘要
- `facts` 为结构化业务事实

当主模型没有充分润色，或服务层使用最近一次 plan execution 兜底回复时，用户会看到偏工具格式的 `summary`。

根因判断：

- `summary/state_summary` 承载的是“给模型看的事实摘要”和“给用户看的最终回复”双重职责。
- `status_overview` 的 summary 以字符串拼接为主，包含内部排序位置、专业长备注、偏好匹配理由。
- timeout fallback 直接消费 `summary`，导致模型润色失败时用户看到原始拼接文本。

### 5.3 工作台卡片链路

agent service 会从工具返回中提取：

- mutating action 的 `workspace_refresh_targets`
- read-only query 的 view targets

然后追加 `planningWorkspaceAction` followup 卡片。问题主要出在 read-only query：它没有产生新数据，只是引导打开已有视图，容易被用户认为“卡片没有联动效果”。

根因判断：

- service 只根据 action/followup target 推断是否追加卡片，缺少“是否真的有增量联动”的规则。
- read-only query 的卡片语义与 mutating action 的卡片语义混在一起。
- 前端看到的都是同一种 `planningWorkspaceAction`，无法区分“新结果”与“打开已有视图”。

## 6. 修复设计

### 6.1 工作台卡片修复规则

将工作台卡片分成两类：

| 类型 | 示例 action | 是否保留卡片 | 原因 |
|------|-------------|--------------|------|
| 产生数据变化 | `generate_plan`, `add_units`, `remove_units`, `regenerate_order`, `apply_compensation` | 保留 | 用户需要查看更新后的排序/审查/草稿 |
| 产生审查结果 | `review_plan` | 保留 | 用户需要查看新审查结果 |
| 候选刷新/偏好筛选 | intent preview / constraint candidate | 保留 | 候选库视图确有新筛选上下文 |
| 只读查询 | `query_state`, `query_ordered`, `query_draft` | 默认不追加 | 没有新结果，纯引导卡片价值低 |
| 候选只读查询 | `query_candidates` | 待确认 | 如果有明确筛选条件，可保留打开候选库；否则不追加 |

建议第一阶段先去掉 `query_state/query_ordered/query_draft` 的 view-only followup。`query_candidates` 是否保留，等拿到两个“无联动卡片”样例后再判定。

修复原则：

- 对用户不可感知的新结果，不追加卡片。
- 对真实变更或刷新，保留卡片并让标题/按钮明确“查看更新后的结果”。
- 对只读查询，优先把核心信息写在聊天文本里，而不是要求用户点卡片。

### 6.2 方案现状回复修复

`status_overview` 不再输出一整段拼接文本，改为稳定结构：

```text
我看了当前方案，核心情况如下：

- 完整度：45/45 个志愿。
- 冲稳保：冲18 / 稳13 / 保14。
- 审查：暂时没有明显风险。
- 偏好承接：当前方案里较贴近的有27个，明显冲突的有0个。
- 贴近偏好的例子：北京中医药大学东方学院-中医学（冲，第2位）；珠海科技学院-汉语言文学（冲，第10位）。
- 前排示例：石家庄铁道大学四方学院-会计学（冲，第1位）；北京中医药大学东方学院-中医学（冲，第2位）。

下一步可以继续看审查明细，或直接告诉我想往更稳、某个地域、某类专业方向调整。
```

展示约束：

- 最多展示 2-3 个示例，不列 5 个长专业。
- 不暴露 `@1`、`id=xxx`、`unknown` 等内部格式。
- 长专业备注保留在工作台详情，不在聊天首屏完整展开。
- “偏好承接”先讲结论，再给例子。
- 没有方案时明确说“当前还没有正式方案”，不伪造数量。

### 6.3 模型润色与兜底修复

理想路径：

- 工具返回结构化 `facts`
- 主模型基于 `facts` 生成自然语言
- service 只做极轻的安全/术语清理

兜底路径：

- 如果主模型超时或输出缺失，service 基于 `facts` 生成同样结构化的 fallback
- fallback 不使用原始 `summary` 直接拼接

这样既满足“大模型润色优先”，又保证模型不可用时不会退回生硬文本。

### 6.4 日志与排查方式

本地服务脚本：

```bash
bash scripts/status.sh
bash scripts/start-all.sh
bash scripts/stop-all.sh
bash scripts/logs.sh agent --follow
bash scripts/logs.sh web --follow
bash scripts/logs.sh server --follow
bash scripts/logs.sh rank --follow
```

日志位置：

- 根目录统一日志：`logs/agent.log`, `logs/web.log`, `logs/server.log`, `logs/rank.log`
- Java 自有日志：`zhiyuan-server/logs/*.log`
- PID 文件：`.pids/*.pid`

建议新增/确认 agent 日志点：

- `execute_plan_action` 返回的 `action_family/result_kind/workspace_refresh_targets`
- service 最终附加的 followup targets
- `status_overview` fallback 是否触发

## 7. 验收标准

### 7.1 回复内容验收

快捷回复“看看现在的方案”满足：

- 有分段或列表结构。
- 至少覆盖完整度、冲稳保、审查状态。
- 如果有偏好信息，说明偏好承接结论。
- 示例志愿不超过 3 个。
- 不出现 `@1`、`id=`、`unknown` 等内部格式。
- 不出现一行内拼接 5 个以上长志愿。
- 没有方案时不伪造方案存在。

### 7.2 卡片行为验收

- `query_state` 不追加无增量 `planningWorkspaceAction` 卡片。
- `query_ordered/query_draft` 默认不追加只读 view-only 卡片。
- 方案生成、调整、复审后仍正常追加对应工作台卡片。
- 候选库卡片根据后续两个样例确认是否保留或收敛。

### 7.3 工程验收

- 有单元测试覆盖。
- 有对话回归断言覆盖。
- changelog 记录修复内容。
- 文档记录本地日志查看与验证方式。

## 8. 测试计划

### 8.1 单元测试

新增或调整：

- `tests/unit/test_plan_execution_tool.py`
  - `query_state` 返回 `status_overview`
  - `summary` 包含分段结构，不包含 `方案前几个志愿：...@1`
  - `workspace_refresh_targets` 对 `query_state` 为空

- `tests/unit/test_chat_service_history_persistence.py`
  - `query_state` 不追加 `planningWorkspaceAction` followup
  - 历史 intent preview 不影响本轮 query_state 卡片判断
  - timeout fallback 对 `status_overview` 使用结构化 facts 输出

- `tests/unit/test_planning_workflow_tool.py`
  - 偏好承接 facts 仍保留完整结构
  - majorGroup 场景按 unit 口径计数，避免 row 口径膨胀

### 8.2 对话回归测试

新增/扩展 plan-correctness case：

- 快捷回复“看看现在的方案”
  - 断言包含“完整度”“冲稳保”“审查”
  - 断言不包含 `@1`
  - 断言不出现过长的前 5 志愿拼接
  - 断言无 followup target 或无工作台卡片

- 无方案场景
  - 断言不伪造方案
  - 断言引导生成方案

- 有风险场景
  - 断言风险/提醒简明展示
  - 可继续追问审查明细

### 8.3 产品结构调用验证

已补充 `tests/unit/test_ws_compat.py::test_ws_compat_structured_session_query_state_returns_rich_text_without_workspace_card`：

- 使用 FastAPI `TestClient` 连接前端兼容入口 `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`。
- 以结构化 session/planning state 准备 45 个志愿、冲稳保、审查状态、用户偏好和 ordered plan 示例。
- 通过 plus 入站格式发送：

```json
{"sessionId":"sess-structured-query-state","userId":"user-structured-query-state","content":"看看现在的方案","inputType":"text"}
```

- 真实走 `ChatService.handle_message`、`execute_plan_action(query_state)`、WebSocket compat 出站格式，只 mock 模型外壳和后端 planning 数据依赖。
- 断言返回 `text`，包含完整度、冲稳保、审查、偏好示例等结构化内容。
- 断言不出现 `方案前几个志愿`、`@1`、`(unknown)` 等内部格式。
- 断言 `query_state` 的 `workspace_refresh_targets=[]`，且本轮没有持久化/发送 `planningWorkspaceAction` followup。

### 8.4 前端验证

手工验证：

- 点击“看看现在的方案”后，聊天区只出现文本回复，不出现无增量卡片。
- 执行真正方案调整后，仍出现“打开排序方案 / 打开审查结果”卡片。
- 移动端不出现长文本撑破聊天气泡。

## 9. 文档与 Changelog 更新

本次落实同步更新：

- `zhiyuan-agent/docs/CHANGELOG.md`
  - 在 `Unreleased` 增加“Changed / Fixed”记录
  - 写明 query_state 只读查询不再追加无增量工作台卡片
  - 写明方案状态 fallback 改为结构化用户口径

- `zhiyuan-agent/docs/dialog_regression_report.md`
  - 增加本次 plan status / card linkage 回归验证结果

- 如涉及前端卡片策略，再更新：
  - `zhiyuan-web/docs/chat-rich-content-rendering-plan.md`

## 10. 实施步骤

1. 已确认本 issue 的首阶段修复范围：先治理 `query_state` 方案现状回复和只读 followup 卡片。
2. 已调整 agent service 的只读 view-only 卡片附加逻辑。
3. 已调整 `query_state` summary 与 `status_overview` fallback 文案。
4. 已补单元/回归测试断言，并增加产品结构 WebSocket 调用验证。
5. 已更新 changelog 和回归报告。
6. 已通过 `tests/unit/test_ws_compat.py` 全文件验证；待前端真实服务联调。
7. 待拿到两个具体“没有联动效果”的卡片样例后，再补齐卡片治理白名单/黑名单。

## 11. 待确认问题

- `query_candidates` 是否算“有联动效果”：如果它只是打开已有候选库，应去掉；如果它带明确筛选条件，应保留。
- “看看现在的方案”是否应该强制走模型润色，还是允许 service 在简单状态查询上直接返回结构化回复。本次保留模型优先，fallback 使用结构化兜底。
- 前排示例是否展示 2 个还是 3 个；是否需要按“冲/稳/保”各取一个而不是取排序前几位。
- 偏好承接里的“较贴近 27 个”是否应展示给用户，还是改成“整体承接较好/一般/偏弱”的等级表达。
