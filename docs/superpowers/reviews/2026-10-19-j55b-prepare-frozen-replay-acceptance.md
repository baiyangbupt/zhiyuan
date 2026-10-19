# J5.5b：prepare → pending → 冻结回放验收（概率倒挂 Direct 切片）

日期：2026-10-19。基线：`ccf2417`。本批仅本地代码与自动测试；未部署、未重启、
未开放生产默认开关。

## 交付边界

- 只打通**普通专业模式、probability_inversion → sort_by_probability** 这一条
  Direct 冻结链；其他策略仍走旧逻辑 / preview_only。
- 只读 `/session/fix-proposals/preview` 在开关打开时返回可确认的冻结 proposal
  （ready/requiresConfirmation=true）；开关关闭时保持 preview_only，行为不变。
- 新增 `/session/fix-proposals/review/prepare`：
  - 重新计算同一份审查与 proposal，校验 proposalId / previewDigest /
    commandDigest / evaluationVersion / sourceVersionGuard；
  - 冻结整份 proposal + FrozenReviewPlan（working/ordered/selected/factsDigest）
    + planContentDigest + 三个摘要；
  - 落 pending：kind=plan_change_proposal、
    actionFamily=apply_plan_change_proposal；
  - 同 requestId 重放返回同一 operationId，不生成第二份 pending。
- apply 只回放冻结内容：
  - 校验 pending 顶层摘要、当前 planContentDigest、选中事实 factsDigest；
  - 原样写回 working/ordered，不重排、不重新生成；
  - 写入前和写入后各按原 probe 复算一次；不满足抛 40905，事务回滚；
  - 直连 `/fix-proposals/apply` 且无冻结 pending → 409
    `review_fix_requires_pending`。
- Python 侧：
  - `preview_review_fix_proposals` 读取新只读预览；
  - 倒挂排序的预览改走新端点，不再创建本地 pending；
  - 用户一次确认时先 `prepare_review_fix_proposal`，再复用
    claim→execute→complete；
  - `_proposal_apply_payload` 透传 commandDigest/previewDigest/evaluationVersion。
- 灰度开关：`review.fix.command.enabled`（默认 false）。关闭时 prepare 拒绝，
  apply 保留旧“重新生成”路径作为回滚位。

## 验证

- Java：`mvn -o clean test` → **1356 tests / 0 failures / 0 errors / 10 skipped**。
- Python：`pytest -q tests/unit` → **2923 passed / 32 skipped**。
- 定向：
  - `DirectReviewPreviewPlannerTest`：开关开 → ready/requiresConfirmation/
    executable/frozen/previewDigest；开关关 → preview_only。
  - `PlanningStateServiceReviewFixPrepareTest`：冻结字段齐全、32 hex operationId、
    同 requestId 重放、digest 不匹配/版本漂移/开关关闭均 409。
  - `PlanningStateServiceReviewFixApplyTest`：冻结顺序逐字回放、篡改摘要 409、
    方案漂移 409、事实漂移 409、原 probe 后置失败回滚、无 pending 409。
  - Python：预览只读不建 pending、确认先 prepare 后执行、三摘要透传、
    历史压缩保留候选。
- 清理：删除已无引用的 `PlanSolver410AdrBenchmarkTest` 配套 fixture
  `release-4.1.0/plan-solver-adr-cases.json`，并从 4.1.0 baseline manifest 移除
  对应条目；`test_release_410_m0_contract.py` 恢复通过。

## 真栈验收（2026-10-19）

环境：Java 18290 以 `-Dreview.fix.command.enabled=true` 重启（新 jar）；
agent 18291 未改。fixture：900700（普通专业 major、80 条、无组/无锁/无优先规则），
先备份 planningState/userScoreDetail，再在夹具中构造：

- 2 条浙江条目改为保档（满足本省保底 2）；
- 候选比例设为 90/10，其余 100，形成可修复倒挂（修复后 10,90,100...）。

结果：

1. 只读 preview：`status=preview_only`（信封）、proposal `status=ready`、
   `requiresConfirmation=true`、frozenReviewPlan/factsDigest/previewDigest 齐全，
   preflight `satisfied=true`。
2. prepare：`prepared`，pendingId/operationId 正常；pending 顶层含
   proposalId/commandDigest/previewDigest/evaluationVersion/planContentDigest、
   frozenProposal/frozenReviewPlan/frozenRequestDigest。
3. claim：active→applying（claimToken）。
4. execute `apply_plan_change_proposal`：完成步骤
   `proposal_applied / ordered_plan_regenerated / review_rerun /
   postcondition_verified`，版本 1→2；最终 80 条、倒挂 0、本省保底 2；
   postcondition satisfied=true。
5. complete：applying→applied。
6. 恢复：planningState/userScoreDetail 回滚到原 HEX，版本 1、80 条、
   比例全 1.0、档位全冲；删除 pending/command/proposal-request 测试行。
7. 运行时已用**开关关闭**重启（pid 12344），健康 200；900040 5/80、
   900045 14/44 未受影响。

真实问题与修复：`assistant_conversation_proposal_request.result_json` 仍是
TEXT 量级，prepare 回填整份 preview 会 `Data too long`。现改为只回填轻量摘要
（proposalId/digests/status/summary），完整冻结负载只放 pending.dataValue；
真栈 prepare 已通过。后续如需在 request 表存完整结果，应单独迁移 MEDIUMTEXT。

## 尚未完成

- 其余 Direct 策略（remove/replace/group-inner）与 Search planner 尚未接入。
- 专业组模式、pin/lock、已确认优先规则仍拒绝冻结。
- 已做一条真栈 prepare→claim→execute→complete 验收；仅 900700 夹具，
  不代表其他策略/会话已验收。
- 旧 generate/apply 分支仍保留，供灰度回滚；J5.5d 再删。
- 生产默认开关仍关闭（验收后已重启为关闭）。

## 下一批门禁

1. 在真栈打开 `review.fix.command.enabled`，用 900040/900045 做一条倒挂修复
   prepare→claim→execute→postcondition，并恢复快照。
2. 再决定是否扩展 Direct remove/replace；Search 按 J5.5c 单独开。
3. 在真栈验收前不得宣称 J5.5b 全闭环或已上线。
