# Release 3.1.2 Feature List

## 1. 版本定位

`3.1.2` 是基于 `deploy-prod-3.1.1-hotfix-mobile-feedback` 的移动端和方案工作台热修版本，目标是收敛近期生产回捞和本地测试环境暴露的方案调整、候选列表、学费过滤、计划年份展示和对话链路稳定性问题。

本版本不引入新的主框架，不切换方案动作协议，不新增数据库迁移。核心原则是：沿用 3.1.x 现有 Plan mutation / pending confirmation / Java repair proposal 主链路，优先修复明确线上问题和阻塞体验。

## 2. 对比基线

| 项 | 记录 |
| --- | --- |
| 对比基线分支 | `origin/deploy-prod-3.1.1-hotfix-mobile-feedback` |
| merge-base | `a248b1dc4b3761208e4375ca5555b4cb9554c466` |
| merge-base commit | `fix: correct legacy volunteer import target counts` |
| 目标 tag | `prod-3.1.2` |
| tag commit | `11172c7d7703df7cebbce94f8902f1cdf82ba9d6` |
| tag commit message | `fix: adjust volunteer plan filters and display` |
| diff 范围 | `origin/deploy-prod-3.1.1-hotfix-mobile-feedback...prod-3.1.2` |
| diff 规模 | `28 files changed, 1701 insertions(+), 174 deletions(-)` |

增量提交：

```text
11172c7 fix: adjust volunteer plan filters and display
2334a38 fix: avoid blocking intent updates on overlay refresh
8884180 fix: preserve replaced pending id during intent recovery
a57f6b4 fix: stabilize mobile hotfix planning flow
```

说明：本地分支中存在 merge commit `9ad3af1`，用于合入部署分支，不单独作为 feature 项。

## 3. Feature List

### 3.1 Agent 方案目标识别和链路兜底

- 增加明确方案目标的确定性识别兜底：
  - “只保留/仅保留/只要”某专业。
  - “只看/仅看/去掉非”某省份或地区。
  - “学费控制在/不超过/以内/去掉高收费”预算约束。
- 识别到明确的方案调整目标后，直接生成 `plan_mutation` 预览卡，避免误落成长期专业意向、地域意向、普通分析或原子移除动作。
- 支持复合目标恢复，例如“只保留临床医学，同时去掉非北京”能够以 `targetScopes` 传给后端 user-goal proposal。
- 对学费预算类诉求优先走 `tuition_budget_scope` 用户目标方案，不把“高收费”误写成专业或学校偏好。
- 在 intent preview 或 plan attempt 已经走偏时，增加二次恢复逻辑，将明确方案目标拉回 `apply_fix_proposal` 确认卡。

维护说明：

- 这部分是 3.1.2 的低风险兜底，不是完整语义框架替换。
- 只承接边界清楚、带明显动作词和实体/预算的场景。
- 更长期的语义结构化、实体 resolver 和上下文引用能力仍应进入 3.2.0 结构性优化。

### 3.2 Agent 方案动作版本和 pending 稳定性

- `plan_execution_tool` 在审查问题预览/执行时从最新 planning state 获取 `planning_version`，避免使用旧版本生成确认 payload。
- 审查问题扩展出的 `volunteer_ids` 会进入 `resolved_apply_payload`，确认执行时保持和预览一致。
- 修复 intent recovery 时替换 pending 后 pending id 丢失的问题，避免前端确认卡和后端 pending 状态对不上。
- 意向约束应用后刷新推荐 overlay 增加 8 秒超时保护：
  - overlay 刷新超时只标记 `recommendationRefresh.success=false`。
  - 主流程仍成功返回，避免用户意向更新被候选池查询阻塞。

### 3.3 Server 上游数据和修复方案返回

- `GaotuClient#getProgramFullList` 支持使用独立 `programDataUrl`，便于全量方案数据接口和主志愿服务地址解耦。
- 志愿数据查询、全量方案查询、推荐数量查询遇到上游超时时，统一转成业务错误 `110 / 志愿数据获取超时`。
- token 登录时，如果上游返回“用户选科信息不存在”，提示改为“请在首页完善高考省份和选科信息后再进入AI智能填报”。
- 修复方案 action 增补总数字段：
  - `totalUnitCount`
  - `totalVolunteerCount`
  - `totalReplacementPairCount`
- replacement、remove、fill、rebalance 等修复动作在返回给前端前补齐总数，便于前端展示“共 N 组/条，当前展开 M 组/条”。

### 3.4 Web 移动端消息和工作台体验

- WebSocket 消息到达后先插入临时 agent 消息，减少移动端等待期间的空白和重复拉历史导致的抖动。
- WebSocket 地址支持从当前页面协议和 host 回退生成，降低本地/测试环境 base url 配置差异带来的连接问题。
- 候选列表专业组改为受控展开状态。
- 从候选列表加入方案时：
  - 保留当前候选项滚动锚点。
  - 自动展开对应专业组。
  - 加入成功后聚焦目标项。
  - 抑制一次不必要的候选池刷新，减少跳动。
- 修复方案预览展示总数和未展开数量：
  - 替换动作展示“共 N 组，另有 M 组未展开”。
  - 移出、补足、补保底、补梯度动作展示总条数/组数。
- 请求层对特殊业务码做收口，避免不应全局拦截的业务码触发错误跳转。

### 3.5 学费过滤、招生计划年份和候选列表补页

- 新建会话学费区间默认上限从 `100000` 调整为 `200000`。
- 后端推荐响应中的默认 `tuitionRange` 和 `tuitionRangeConfig.max` 同步调整为 `200000`。
- 招生计划年份展示按填报模式固定：
  - 模拟填报：`2025招生计划`
  - 智能填报：`2026招生计划`
  - 未识别模式才回退 `examYear || 2026`
- 候选列表在筛选后如果当前页内容不足以撑出滚动高度，会自动补拉下一页，避免“全部 8 个但默认只显示 5 个，用户无法滚动加载剩余项”。
- 候选筛选浮层支持点击外部区域和 `Esc` 收起。

## 4. 涉及模块

| 模块 | 文件数 | 主要内容 |
| --- | ---: | --- |
| `zhiyuan-agent` | 8 | 明确方案目标兜底、预算约束恢复、pending/version 稳定、overlay refresh 超时保护和单测 |
| `zhiyuan-server` | 12 | 上游数据超时处理、用户选科缺失提示、修复方案总数字段、学费默认上限 |
| `zhiyuan-web` | 8 | 移动端消息即时展示、候选组展开/滚动稳定、修复预览数量展示、学费/年份/筛选加载交互 |

完整文件范围：

```text
zhiyuan-agent/app/handlers/mutation_handlers.py
zhiyuan-agent/app/models/conversation_phase.py
zhiyuan-agent/app/service.py
zhiyuan-agent/app/tools/intent_state_tool.py
zhiyuan-agent/app/tools/plan_execution_tool.py
zhiyuan-agent/tests/regression/test_execution_preview.py
zhiyuan-agent/tests/unit/test_chat_service_history_persistence.py
zhiyuan-agent/tests/unit/test_intent_state_tool.py
zhiyuan-server/src/main/java/com/ytell/zhiyuan/manager/gaotu/GaotuClient.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/FixProposalActionDTO.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/RepairReportDTO.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/GaotuService.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/PlanningStateService.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/RepairProposalStateBuilder.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/RepairReplacementActionBuilder.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/RepairReportBuilder.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/RepairRiskActionBuilder.java
zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/VolunteerResponseBuilder.java
zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/GaotuServiceTest.java
zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/RepairReplacementActionBuilderTest.java
zhiyuan-web/src/hooks/useWebSocket.tsx
zhiyuan-web/src/interface/api/volunteer.ts
zhiyuan-web/src/pageComponents/session/ModalForm/index.tsx
zhiyuan-web/src/pageComponents/sessionDetailV2/MessageList/index.tsx
zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx
zhiyuan-web/src/service/apis/sessionDetail.ts
zhiyuan-web/src/service/apis/user.ts
zhiyuan-web/src/service/request/index.ts
```

## 5. 验证状态

本轮已执行的本地验证：

- `zhiyuan-agent` 定向单测：
  - `tests/unit/test_intent_state_tool.py -k "overlay_refresh_timeout or stale_without_candidate_filtering or mixed_constraint"`
  - 结果：`3 passed, 182 deselected`
- `zhiyuan-server` 编译：
  - `mvn -q -DskipTests compile`
  - 结果：通过
- `zhiyuan-web` 类型检查：
  - `./node_modules/.bin/tsc --noEmit --pretty false`
  - 结果：失败，剩余错误集中在既有 `subjectScores`、`userCenter`、`service`、`request` 等文件；本次修改后的 `ModalForm` 类型错误已消除。

建议上线前补充：

- 标准测试环境新建智能填报会话，确认学费默认上限为 `20万/年`。
- 使用历史会话 `11802961` 或同类样本，确认筛选“北部湾”后候选列表能继续加载剩余专业组，筛选浮层能正常收起。
- 分别检查智能填报和模拟填报工作台，确认招生计划年份为 `2026` 和 `2025`。
- 回归高收费/预算类对话，确认进入方案调整预览卡，而不是专业意向或只读分析。
- 回归“只保留某专业/某地区”类对话，确认 pending card 的 `targetScopes` 与用户原话一致。

## 6. 发布注意事项

- `prod-3.1.2` tag 当前指向 `11172c7d7703df7cebbce94f8902f1cdf82ba9d6`。
- 本文档是在 tag 创建后补充到分支上的 release 说明；如果需要让 `prod-3.1.2` tag 本身包含本文档，需要单独确认是否移动已推送 tag。
- 本地测试环境部署脚本、`assets/` 回捞样本、`data/tmp` 删除和构建缓存不属于 3.1.2 发布内容。
