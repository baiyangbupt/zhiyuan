# Release 3.1.0 Summary And Upgrade Plan

本文是 `3.1.0` 发布收口文档，作为功能范围、风险边界、回归验证和 `3.0.3 -> 3.1.0` 升级准备的主入口。生产可执行步骤以 `docs/release-3.1.0-production-upgrade-plan.md` 为准。

## 1. 当前结论

`3.1.0` 是 `3.0.3` 之后的数据新鲜度、审查修复和 Agent 编排增强版本。主路径结论：

- Backend、Web、Agent 都需要升级；Rank 服务本轮没有代码变更，继续沿用现有容器。
- 数据库需要新增 `assistant_planning_data_freshness_schedule`，生产 Flyway 长期关闭时必须手工执行 `zhiyuan-server/src/main/resources/db/migration/V6__add_planning_data_freshness_schedule.sql`。
- 数据新鲜度后台巡检默认关闭：`planning.data-freshness.schedule.enabled=false`。生产先以关闭状态上线，确认稳定后再单独开启。
- `PREDICT` 模拟填报展示“数据为 2025 年的志愿数据”，不触发招生计划自动同步；`VOLUNTEER` 智能填报使用 2026 年招生计划，并纳入静默检查、候选刷新和审查 stale 机制。
- 高副作用方案动作继续执行 `preview -> pendingConfirmation -> confirm -> apply`；卡片确认仍是主入口。
- 审查修复统一到 `review -> fix proposal -> apply -> repair report`，旧 `plan-adjustment/apply` 返回 410，旧 compensation 外部入口不再作为发布能力。

## 2. 升级范围

| 模块 | 是否升级 | 说明 |
| --- | --- | --- |
| `zhiyuan-server` | 是 | 数据新鲜度状态、巡检索引、审查规则注册表、FixProposal、修复 apply policy、工作区状态增强 |
| `zhiyuan-web` | 是 | 工作区数据同步弱提示、hover 摘要、候选/方案/审查状态联动、修复建议展示 |
| `zhiyuan-agent` | 是 | 方案动作编排、review repair 回复合成、pending confirmation 路由、对话回归框架 |
| `zhiyuan-rank` | 否 | `prod-3.0.3..develop` 没有 Rank 代码变更，继续沿用现有服务 |
| 数据库 | 是 | 新增 V6 数据新鲜度巡检索引表 |

## 3. 主要能力

### 3.1 数据新鲜度

- 新增 `DataFreshnessStateDTO` 和 `DataFreshnessScheduleDTO`，工作区可返回最新同步时间、预计下次同步、变更摘要、候选刷新/重新审查标记。
- 新增后台巡检索引表 `assistant_planning_data_freshness_schedule`，避免后台任务扫描完整 planning state。
- `VOLUNTEER` 会话支持打开工作区后的节流式静默检查，检测到真实变化后标记候选池、初始推荐和审查状态 stale。
- 无真实变化时不弹窗、不打扰用户；有增量影响时，在用户首次访问新数据时通过工作区提示/弹窗感知摘要。
- `PREDICT` 会话只展示 2025 静态数据说明，不进入后台巡检。

### 3.2 审查与修复

- 新增后端 `ReviewRuleRegistry`，统一审查规则元数据。
- 新增 `FixProposalStateDTO`、`FixProposalDTO`、dry-run、candidate shortage、repair report 等对象。
- `fix-proposals/generate` 负责生成可展示、可验证的修复建议。
- `fix-proposals/apply` 是正式高副作用修复入口，应用前校验 proposal 状态、版本、策略和候选可用性。
- 专业组内安全垫、数量缺口、比例失衡、梯度断层、高收费、中外合作、限报等问题进入统一审查/修复表达。
- `plan-adjustment/analyze` 仅保留只读兼容；`plan-adjustment/apply` 明确退场。

### 3.3 Agent 对话与方案动作

- Agent 主链路统一到 `collect_plan_context_inputs -> plan_next_action -> execute_plan_action`。
- `PlanActionPlan` 只作为动作 envelope，复合目标、可行性、取舍依据和歧义放入 `composite_proposal`。
- 删除历史 `planning_router_tool` 主路由依赖，减少字符串快路由和历史 preview 恢复造成的误执行。
- 强化只读分析、复合调整、按目标补齐、候选不足解释和审查后修复建议回复。
- 新增 3.1.0 生产抽象对话、review repair、constraint plan action 等回归 case。

### 3.4 Web 工作区

- 工作区顶部弱提示展示数据同步信息；hover 展示预计下次同步和最近变化摘要。
- 候选区进入时按后端状态自动刷新，不额外暴露“检查更新”按钮。
- 方案区和候选区都展示推荐系数、录取概率、历年信息等用户可感知字段。
- 审查状态、修复建议和对话 pending confirmation 保持同一高副作用确认边界。
- Agent WebSocket 路径保持 `/gaotu-assistant-agent/plus/chat/{tenantId}/bot/{botId}/do`。

## 4. 数据库要求

生产升级前必须确认：

```sql
CREATE TABLE IF NOT EXISTS assistant_planning_data_freshness_schedule (...);
```

以仓库 SQL 为准：

```text
zhiyuan-server/src/main/resources/db/migration/V6__add_planning_data_freshness_schedule.sql
```

需要检查：

- 表 `assistant_planning_data_freshness_schedule` 存在。
- 唯一约束 `uk_planning_data_freshness_schedule_session` 存在。
- 索引 `idx_planning_data_freshness_schedule_due` 和 `idx_planning_data_freshness_schedule_status` 存在。
- 生产若使用 `--spring.flyway.enabled=false`，必须手工执行 V6，不能依赖服务启动自动迁移。

## 5. 配置要求

- `planning.data-freshness.schedule.enabled=false` 作为生产首发默认值。
- `planning.data-freshness.schedule.batch-size=5`、`seed-batch-size=10`、`max-consecutive-tasks=2` 可作为初始保守值。
- Agent 生产继续使用线上已验证的 `LLM_PROVIDER/LLM_MODEL_NAME/LLM_BASE_URL/LLM_API_KEY`，真实 key 只放运行环境。
- Web 生产构建继续使用 `/assistant-pc` basePath，不写本地 override 到正式生产镜像。
- 主站代理继续保留：
  - `/assistant-pc/` -> Web
  - `/gaotu-assistant-bot/` -> Backend
  - `/gaotu-assistant-agent/` -> Agent WebSocket/health

## 6. 验证结果

最近一次完整回归记录：

| 验证项 | 结果 |
| --- | --- |
| Agent 全量测试 | `2564 passed, 8 skipped` |
| Server Maven 全量测试 | `451 passed, 4 skipped`, `BUILD SUCCESS` |
| Web `standardtest` build | 通过 |
| Web `prod` build | 通过 |

本机标准测试环境验证记录（2026-06-18）：

| 验证项 | 结果 |
| --- | --- |
| Backend 3.1.0 JAR 构建 | 通过，`mvn clean package -DskipTests` |
| Web 3.1.0 standardtest build | 通过，`basePath=/assistant-pc`，代理指向本机 `18090/18091` |
| Backend 本地启动 | 通过，`localtest` profile，端口 `18090`，Flyway 当前 schema version `6` |
| Web 本地启动 | 通过，端口 `3001` |
| Agent 本地启动 | 通过，容器 `zhiyuan-agent-local302` 使用镜像 `zhiyuan-agent:local310` |
| Rank 本地服务 | 通过，沿用 `zhiyuan-rank-local302`，端口 `18092` |
| Release smoke | 通过，`12` 项通过，`0` failure，`0` warning |

3.1.0 新增发布冒烟脚本：

```bash
ZHIYUAN_SERVER_PORT=18090 \
ZHIYUAN_WEB_PORT=3001 \
ZHIYUAN_AGENT_PORT=18091 \
ZHIYUAN_RANK_PORT=18092 \
bash ops/release-smoke.sh --local
```

带真实会话做工作区只读冒烟：

```bash
bash ops/release-smoke.sh --local --session-id <chatSessionId>
```

远端主站代理冒烟：

```bash
bash ops/release-smoke.sh --remote https://test-www.gaotuzhiyuan.com --session-id <chatSessionId>
```

## 7. 3.0.3 -> 3.1.0 升级口径

执行顺序：

1. 确认回滚点：`prod-3.0.3` 的 Backend/Web/Agent 镜像、JAR、配置和 systemd/container 启动方式可恢复。
2. 在生产库执行并验证 V6 SQL。
3. 以 `planning.data-freshness.schedule.enabled=false` 构建并部署 Backend。
4. 部署 Agent。
5. 部署 Web。
6. 跑 `ops/release-smoke.sh` 远端冒烟。
7. 人工验证主站 `test-www.gaotuzhiyuan.com/assistant-pc` 跳转鉴权、会话列表、详情页、对话、候选、方案、审查、数据同步提示。
8. 观察稳定后，如需要开启后台巡检，再单独调整 `planning.data-freshness.schedule.enabled=true` 并控制批量参数。

## 8. 回滚口径

- 应用回滚到 `prod-3.0.3`。
- 数据库 V6 表可以保留，不需要删除；3.0.3 不依赖该表。
- 如果已开启后台巡检，回滚前先关闭 `planning.data-freshness.schedule.enabled` 并停止新版本服务。
- 3.1.0 写入的 planning state 增强字段在 3.0.3 下应作为未知 JSON 字段保留，不做批量清理。

## 9. 关联文档

- `docs/release-3.1.0-production-upgrade-plan.md`
- `docs/release-3.1.0-data-freshness-and-impact-notification-design.md`
- `docs/release-3.1.0-review-repair-requirements.md`
- `docs/release-3.1.0-dialog-auto-explorer.md`
- `docs/release-3.1.0-dialog-auto-explorer-issue-summary-20260614.md`
- `docs/release-3.1.0-dialog-case-recovery-index-20260614.md`
