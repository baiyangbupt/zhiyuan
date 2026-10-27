# 方案点名加入（ProposalRequest.add_units）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 codex 写闭环支持“点名把具体院校+专业加入现有方案”，并在用户确认后**纯加入**
（零删除、总数/配额变化显式确认），执行有后置条件、显式成功状态与冻结命令绑定。

**Architecture:** 扩展 `ProposalRequest` 增加 `goalType=add_units` + `exactTargets`；复用
`fix-proposals/user-goal/prepare` 的幂等/单槽/operationId；Java `UserGoalProposalBuilder`
用 effective candidates 解析并做数量/配额预检 + dry-run；pending 冻结 frozenCommand；确认后
Java `add_units` 执行 select→ordered 重生成→后置条件→gated review；网关早分支、回执全链。

**Tech Stack:** Python ≥3.10 / Pydantic、Java 8 / Spring Boot / MyBatis、Next.js/React、
pytest、JUnit、Node test runner。

**Spec:** `docs/superpowers/specs/2026-10-17-plan-action-contract-design.md`（v4）
**Review:** `docs/superpowers/reviews/2026-10-17-plan-action-contract-review*.md`
**Baseline:** `616464c`（`wip/2026-09-28-p2-write-loop-green`）。

## 产品口径（2026-10-18 拍板）

- 点名加入默认 **EXPAND**（当前 45 → 当前+新增，零删除）；REPLACE（总数不变/必须有/换掉）
  是显式语义，第一期不实现，当前不得用 add_units 静默替代；语义含糊先问一次。
- scope / 学费类意向默认**持久**；只有明确“这次/仅本次”才 once，卡上写明。
- 风险姿态用**稳健/均衡/进取 + 目标优先级排序**表达；内部映射为安全 floor/结构目标/软效用
  权重，用户侧只讲取舍。

## Global Constraints

- 先写失败测试，再做最小实现；每个任务跑定向测试；不把未验证的“成功”写进文档。
- 不改 legacy `app/zhiyuan_agent/prompt.py` 20c；不改 legacy add_units 行为（无 rerunReview
  路径不重校验、不跑 review、不加后置条件）。
- 不做 DB migration；pending/prepare 幂等表已存在。
- 不提交、不部署、不重启共享服务，直到 S7 验收与用户确认（若用户另行授权，按授权执行）。
- 不碰他人未跟踪 review 文档、不碰 `tsconfig.tsbuildinfo` 与 Next 构建目录。
- 现有 `.write.md` 三者互斥保持；`exactTargets` 作为 ProposalRequest 内字段，不新增第四草稿。
- 所有面向模型的新字段必须有 schema description 与对象示例；非 add_units 输出 `exactTargets: []`。

---

## Task S1：契约、schema 与版本守门

**Files:**
- Modify `zhiyuan-agent/app/gateway/contracts.py`
- Modify `zhiyuan-agent/app/gateway/service.py`（TURN_OUTPUT_SCHEMA / `_strict_model_schema` /
  `_normalize_nullable_for_upstream` / 版本守门）
- Modify `zhiyuan-agent/tests/unit/test_turn_output_schema.py`
- Modify `zhiyuan-agent/tests/unit/test_gateway_contracts.py`
- Modify `zhiyuan-agent/tests/unit/test_gateway_output_repair.py`
- Modify `zhiyuan-agent/tests/unit/test_shadow_gateway.py`（fixtures）
- Modify `zhiyuan-agent/app/zhiyuan_agent/prompt.py` **不改**（legacy 明确保留）

**Interfaces:**
- `ProposalRequest.goal_type` 增加 `"add_units"`；`exact_targets: list[ExactTarget]`，
  `ExactTarget{school_name?: str, major_name?: str, volunteer_id?: str}`。
- validator：add_units ↔ exact_targets 非空；非 add → 空；add 拒绝 count/tier/requirements/
  priority/target_scopes/negative_scopes/quality_guards/tradeoff_guards/source_review_issue_codes；
  单个 target 需 `(school && major) || volunteer_id`；max_length=20。
- 版本守门：`source_version_guard != snapshot` → `stale_state` 可修复；新增
  `_PROPOSAL_VERSION_REPAIR_HINT`。

- [ ] 写失败测试：schema 含 add_units/exactTargets、required 纪律、nullable 归一化；
  name-only/ID-only/both/neither；add 空 targets；非 add 带 targets；add 混 count/requirements/
  priority/scopes/guards；>20；版本不符走修复回合。
- [ ] 实现 `ExactTarget`/`ProposalRequest` 扩展与两个 validator。
- [ ] 把 `add_units`/`exact_targets` 合并进 `TURN_OUTPUT_SCHEMA`（在 nullable 归一化之前），
  确认 `_strict_model_schema` required 行为；同步 fixtures 为 `exactTargets: []`。
- [ ] 把版本守门放进 `validate_turn_output`/`_validate_round`，新增专用修复提示。
- [ ] 跑 `pytest tests/unit/test_turn_output_schema.py tests/unit/test_gateway_contracts.py
  tests/unit/test_gateway_output_repair.py tests/unit/test_shadow_gateway.py -q`；全绿。

## Task S2：Java resolver、纯加入预检、frozenCommand

**Files:**
- Modify `zhiyuan-server/.../service/biz/PlanningStateService.java`（包内 resolver、prepare 分支、
  dataValue）
- Modify `zhiyuan-server/.../service/biz/UserGoalProposalBuilder.java`（add_units 分支 + 预检）
- Modify `zhiyuan-server/.../service/biz/RepairProposalTaxonomy.java`（ADD_UNITS）
- Modify `zhiyuan-server/.../model/dto/planning/FixProposalDTO.java`（affectedItems/addedCount/
  removedCount/targetCountBefore/After）
- Modify `zhiyuan-server/.../model/dto/planning/UserGoalFixProposalReq.java`（exactTargets）
- Modify `zhiyuan-server/src/test/.../UserGoalProposalBuilderTest.java`（或新增）
- Modify `zhiyuan-server/src/test/.../PlanningStateServiceTest.java`（prepare 同池）

**Interfaces:**
- `resolveEffectiveCandidatesForProposal(state)` 包内方法（refresh=false），只在 add_units 分支用。
- 解析结果表 + 全有或全无；no_plan/source_unavailable 判定写死。
- 数量/配额：override = **当前 working plan 实际数量 + 新增数量**，同一 countMode（unit mode
  用单元数/addedUnitCount，entry mode 用条目数）；current != confirmedTarget → 阻断；
  有精确档位配额 → 阻断；dry-run（state 副本+override）验证全新增入、零删除、总数/档位；
  有选择目标但 dry-run 不可用 → 一律 blocked。
- frozenCommand `{commandType, operationId, volunteerIds, targetCountOverride,
  tierQuotaOverride(null), rerunReview:true, sourceVersion}` + digest 写入 pending dataValue；
  prepareUserGoalProposal 按 goalType 写 kind=plan_action/actionFamily=add_units/
  commandType/volunteerIds。
- 幂等 digest 只覆盖模型输入；exactTargets 稳定排序。

- [ ] 写失败测试：prepare/execute 同池；unique/ambiguous/no_match/not_in_pool/target_mismatch/
  banned/locked/no_plan/source_unavailable；部分/全部已选；current==confirmed 45→51；
  current!=confirmed（40 vs 45）阻断；unit mode 6 条落 2 组只 +2 单元；entry mode 用条目数；
  有精确档位配额阻断；dry-run 删除既有项 blocked；dry-run 不可用 blocked；
  frozenCommand（含 operationId）/digest；同 requestId 重放/不同输入 409。
- [ ] 实现包内 resolver，add_units builder/预览 DTO/字段，预检+dry-run，dataValue/frozenCommand。
- [ ] 跑 Java 定向测试（`mvn -Dtest=...`）；全绿。

## Task S3：Java apply、后置条件、显式成功、review A

**Files:**
- Modify `zhiyuan-server/.../service/biz/PendingPlanningCommandBizService.java`
- Modify `zhiyuan-server/.../model/dto/planning/PendingPlanningCommandReq.java`（rerunReview）
- Modify `zhiyuan-server/.../model/dto/planning/PendingPlanningCommandRes.java`（actualChanges/
  postconditionReport/reviewState）
- Modify `zhiyuan-server/.../service/biz/UnifiedPlanPostconditionValidator.java`（add 后置条件）
- Modify Java tests `PendingPlanningCommandBizServiceTest.java`

**Interfaces:**
- execute 从 pending 读 frozenCommand；add_units 请求只发 5 个字段，Java validate 允许请求层
  volunteerIds 空/省略；篡改字段 → 40908，且 40908 先于 replay 的 40903。
- targetCountOverride（current+added，按 countMode）在事务内写入已确认目标；select→generate。
- 后置条件：新增全在、原条目零删除、总数/档位符合；失败 40905 抛异常回滚。
- review：rerunReview=true 时同事务；失败抛 `BusinessException(40907)`（或 setRollbackOnly 后抛），
  禁止 catch-return；成功后重读 state/planningState；reviewState.sourceVersion=N、
  resultPlanVersion=N+1。
- 成功后 explicitStatus=applied + postconditionReport.satisfied=true + actualChanges/reviewState；
  compact replay 保留；legacy 无 flag 不变。

- [ ] 写失败测试：add_units 只带 5 字段成功、带空 volunteerIds 成功；frozenCommand 篡改
  40908 且先于 replay 40903；target override（entry/unit 两口径）；后置条件全新增入/零删除/
  总数；失败 40905 回滚（回读方案）；review 失败 40907 **且回滚**（回读未加入）；成功后
  applied；review 版本语义；legacy add_units 不触发重校验/40905/review。
- [ ] 实现；跑 Java 定向测试；全绿。

## Task S4：网关 prepare 映射、apply 早分支、回执

**Files:**
- Modify `zhiyuan-agent/app/gateway/service.py`（prepare result.proposals[] 提取、status 映射、
  早分支调用）
- Modify `zhiyuan-agent/app/gateway/conversation_actions.py`（早分支、frozen 参数、40907/40908
  文案、reviewState）
- Modify `zhiyuan-agent/app/server.py`（`_action_result_payload` actualChanges/reviewState）
- Modify `zhiyuan-agent/app/util/internal_client.py`（execute 参数 rerun_review 如需）
- Modify `zhiyuan-agent/tests/unit/test_gateway_action_continuation.py`、
  `test_conversation_actions.py`、新增 prepare 映射测试

**Interfaces:**
- prepare：`data.result.proposals[0]`，pendingId/ready 映射；pendingId=null/blocked/info/
  superseded/preparing；prepared 不透传；proposalRef=pendingId。
- apply：`commandType=add_units` 早分支，跳过 proposalApply/canonical/region/major；只传
  commandType/pendingId/operationId/claim/expectedPlanVersion；internal_client 对 add_units
  不再拼 volunteerIds/rerun_review；旧 plan_mutation 拒绝先于 operation_id_missing。
- 回执：as_dict/action payload 加 reviewState；成功/失败两路。

- [ ] 写失败测试：prepare 结果形状/blocked 无按钮；早分支不调用 canonical（mock 断言）；
  expectedPlanVersion 来源；旧 pending 文案；回执字段。
- [ ] 实现；跑定向 pytest；全绿。

## Task S5：前端卡片与回执

**Files:**
- Modify `zhiyuan-web/src/utils/conversationEvents.mjs`（result 白名单）
- Modify `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/ProposalCard.tsx`
- Modify `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/proposalCardText.mjs`
- Modify 相关 test.mjs
- Modify `MessageList/index.tsx`（如需）

**Interfaces:**
- 预览：addedCount/removedCount=0/targetCountBefore→After/affectedItems；ready 才出按钮。
- 回执：actualChanges/reviewState；失败“未生效（审查失败/后置条件失败）”；冷加载去重。

- [ ] 写 Node 测试（纯逻辑）；实现渲染；`node --test` 全绿；旧前端字段兼容。

## Task S6：prompt / 技能 / 插件

**Files:**
- Modify `zhiyuan-agent/skills/codex/developer_instructions.md`
- Modify `zhiyuan-agent/skills/codex/developer_instructions.write.md`
- Modify 三个 `zhiyuan-codex-planner/skills/*/SKILL.md`
- Modify `.codex-plugin/plugin.json`（cachebuster）

**Interfaces:**
- 点名加入 → `proposalRequest(goalType="add_units", exactTargets=[{schoolName, majorName}])`；
  先调 `recommendation.preview_candidates` 复制准确名称；非 add 输出 `exactTargets: []`；
  `must_include_scope` 不是点加入；responseType=text/partial。
- legacy prompt.py 不动。

- [ ] 更新文本与示例；plugin cachebuster + `codex plugin add`；18291 重启（经用户授权）；
  验证插件缓存版本。

## Task S7：真实栈验收与回滚演练

- [ ] 六条点名 + 当前总数 45 → 预览“45→51、零删除”→ 确认 → working/ordered +6、零删除、
  总数 51、review 语义正确；卡片显示实际加入+审查摘要。
- [ ] 反例：精确档位配额阻断、陈旧版本、重复确认、歧义、部分已选、候选失效、review 失败
  回滚、后置条件失败回滚、frozenCommand 篡改 40908、开关关闭、旧 plan_mutation。
- [ ] 回滚演练：关 `PLAN_ACTION_CONTRACT_ENABLED` + 回退 plugin/prompt；legacy add_units 回归。
- [ ] 记录真实栈结果、耗时、P95；更新 review/plan 文档。

## 后续纵切（本期不实现，但设计/契约预留）

- **S8 REPLACE（必须有 + 总数不变）**：契约增加 `addPolicy=expand|replace`；replace 走
  同一 objective compiler，冻结“新增集合 + 移出集合”，solver 以“指定条目 lower bound +
  最小改动/低效用优先移出”求解；预览完整列出新增/移出；后置“指定全在、只删已确认项”。
  纯加入默认 expand，不静默替换。
- **S9 scope/学费默认持久**：`applyUserGoalTargetToPlanningState` 持久化 targetScopes /
  tuition cap；带 `lifecycle=persist|once`；once 卡面写明“仅本次”。重新生成后不得撤销。
- **S10 风险姿态与目标优先级**：新增 `RiskPosture=steady|balanced|aggressive` 与
  `GoalPriorityOrder`；映射为安全 floor、冲稳保结构目标、软效用权重；golden 场景验证
  “稳健/均衡/进取”结构向量单调；用户侧只说取舍。

## Validation

- Python：S1/S4 定向 pytest + 相关 gateway 全量；`test_turn_output_schema`、
  `test_gateway_contracts`、`test_gateway_output_repair`、`test_shadow_gateway`、
  `test_conversation_actions`、`test_gateway_action_continuation`。
- Java：resolver/builder、prepareOnce、add_units、postcondition、review、legacy 回归。
- Web：Node 纯逻辑测试 + typecheck（区分既有基线错误）。
- E2E：真实栈六条 + 反例；不使用合成 900xxx 无候选文件会话。

## Rollback

- 关闭 `PLAN_ACTION_CONTRACT_ENABLED`（prepare 拒绝）并回退 plugin/prompt 版本；
- apply 映射保留，已存在的 plan_action pending 仍可确认；
- legacy `plan_mutation` 明确拒绝文案；
- 不删表、不 migration。

## Notes

- 先 S1→S2→S3→S4→S5→S6→S7 串行；S1/S4 与 S2/S3 有文件不冲突时可并行，但 apply 依赖
  prepare 的 dataValue 形状，S4 必须在 S2/S3 之后验收。
- 每个任务先写失败测试；测试失败要保留输出以便审查。
- 不把“prompt 改了”当作功能完成；以真实栈六条点名为准。
