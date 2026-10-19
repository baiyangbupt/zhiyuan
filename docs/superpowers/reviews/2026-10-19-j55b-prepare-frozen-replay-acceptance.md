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

## 尚未完成

- 其余 Direct 策略（remove/replace/group-inner）与 Search planner 尚未接入。
- 专业组模式、pin/lock、已确认优先规则仍拒绝冻结。
- 未做真栈 prepare→confirm→apply 验收；未部署、未重启服务。
- 旧 generate/apply 分支仍保留，供灰度回滚；J5.5d 再删。
- 生产默认开关仍关闭。

## 下一批门禁

1. 在真栈打开 `review.fix.command.enabled`，用 900040/900045 做一条倒挂修复
   prepare→claim→execute→postcondition，并恢复快照。
2. 再决定是否扩展 Direct remove/replace；Search 按 J5.5c 单独开。
3. 在真栈验收前不得宣称 J5.5b 全闭环或已上线。
