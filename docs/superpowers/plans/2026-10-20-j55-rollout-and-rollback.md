# J5.5 审查修复灰度放量 Runbook（2026-10-20）

状态：代码与自动测试完成，默认全关。本文定义放量顺序、验收矩阵与回滚动作。

## 1. 开关

| 开关 | 默认 | 作用 |
|---|---|---|
| `review.fix.command.enabled` | false | 总开关；关闭时 prepare/apply 全部不可用 |
| `review.fix.search.enabled` | false | Search 类修复开关；关闭时只保留 Direct 倒挂 |
| `review.fix.search.strategies` | 空 | 空或 `all` = 全部；否则按 `count,coverage,safety,ratio,risk` 过滤 |

对应环境变量：`REVIEW_FIX_COMMAND_ENABLED`、`REVIEW_FIX_SEARCH_ENABLED`、
`REVIEW_FIX_SEARCH_STRATEGIES`。

## 2. 放量顺序

1. **Phase 0**：全部关闭，确认现有路径与回滚基线。
2. **Phase 1**：只开总开关，Search 关。仅 Direct 倒挂可确认。
3. **Phase 2**：`review.fix.search.enabled=true`，
   `review.fix.search.strategies=count,coverage`。先放量补齐类。
4. **Phase 3**：策略扩到 `count,coverage,safety,ratio`。
5. **Phase 4**：策略扩到 `all`（含 risk）。

每一步至少观察一个完整业务日，再进入下一步。

## 3. 验收矩阵

普通专业与专业组各跑一遍：

| 策略 | 900700（major） | 900045（majorGroup） |
|---|---|---|
| Direct 倒挂 | ✓ | ✓ |
| count_target | ✓ | ✓ |
| coverage | ✓ | ✓ |
| safety_guard | ✓ | ✓ |
| ratio_distribution | ✓ | ✓ |
| risk replace/remove | ✓ | ✓ |

每一步链路：

```
preview → prepare → claim → execute → complete
```

通过标准：

- preview ready 且 `requiresConfirmation=true`
- prepare 返回 `prepared`
- execute 完成步骤含
  `proposal_applied / ordered_plan_regenerated / review_rerun /
  postcondition_verified`
- `postconditionReport.satisfied=true`
- pending 终态 `applied`
- 会话恢复后版本/条数/档位与验收前一致

## 4. 观测

- staged solver 日志：
  - `staged solver ready: sourceVersion=... candidates=... selected=...
    durationMs=... stages=safety=...`
  - `staged solver blocked: reason=... objective=... durationMs=...`
- 审查修复关键错误码：
  - `review_fix_command_disabled`
  - `review_fix_search_disabled`
  - `review_fix_changed` / `review_fix_stale`
  - `review_fix_postcondition_failed`（40905）
- pending 巡检：`active` / `applying` 数量；`applying` 需用
  `/session/pending/reconcile` 对账，不能只等 TTL。

## 5. 回滚

1. 先关 `review.fix.search.enabled`：Search 类提案立即停止生成，
   已冻结的 Search pending 在 apply 时返回 `review_fix_search_disabled`。
2. 再关 `review.fix.command.enabled`：所有新 prepare/apply 停止；Direct 也回退。
3. 已 apply 的方案不回滚，只回退后续执行路径。
4. 旧 pending 与新代码混用时，跨版本确认应作废后重新预览；不要假定旧 jar
   会消费新的 frozenProposal。
5. 恢复验收会话的 HEX 快照，清理 pending/command/request 测试行。

## 6. 当前基线

- Java 全量测试与 Python unit 全绿（数字见当次提交说明）。
- 默认运行时：两个 review 开关均关闭。
- 最近验收：900700（major）、900045（majorGroup）各策略真栈通过并恢复。
- **2026-10-20 求解器默认变化**：组内两阶段 MILP
  （`planning.group-inner.major-optimization.enabled`）与 initial solver
  （`planning.initial.solver.enabled`）均改为默认 on。review fix 的
  preview/frozen replay 会携带 `selectedMajorIdsByUnit`，因此正式放量
  Phase 1 前必须在最终 jar 上重跑 Direct/Search 真栈验收，确认冻结专业
  清单、apply 物化和回滚仍一致；不能直接沿用默认关闭时期的验收结论。
