# J5.5b Frozen Preview And Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复旧 Golden 的不完整评价上下文，并交付 J5.5b 的原 probe 预检与首个只读冻结后态，不提前开放确认执行。

**Architecture:** Golden 使用生产 EvaluationContextBuilder，严格区分 legacy 翻译与已迁移的派生 probe；迁移差异必须按事实验证并报告。独立 FindingPostconditionEvaluator 对新鲜复算结果做 fail-closed 原问题/硬约束校验；Direct 预览仅在完整选中集、顺序和事实均可物化时冻结普通专业模式的概率排序，所有输出仍不可确认。prepare/pending/gateway 和 Search 留待后续批次。

**Tech Stack:** Java 8, Spring Boot 2.3.8, JUnit 5, Mockito, offline Maven。

**Spec:** `docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md` §4.4、§5.4、§9 J5.5b；对应 review §7。

## Global Constraints

- 不改旧 generate/prepare/apply/Python 路由，不提交、不部署、不重启；保留已有改动。
- 所有命令保持 executable=false；新冻结预览仍 preview_only，不能冒充完整 J5.5b。
- 不伪造 solverResult；不把 dry-run 计数冒充 selected/ordered/专业级后态。
- 原 probe 必须新鲜复算；solver ready 不等于 repair achieved；缺字段/unknown/unavailable 必须关闭。
- 排序不修改选中集、专业和长期目标；组模式、pin/lock、信息不完整暂不支持。
- 区间和安全 effective-only 语义不变。

## Task 1: Golden Harness

**Files:** `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/EvaluationGoldenShadowTest.java`；必要时相邻专用测试/测试辅助类。

**Interfaces:** 消费完整 state/pool 和生产 EvaluationContextBuilder；产出真实快照的显式历史差异报告，未迁移 probe 严格历史一致。

- [x] 在旧 Golden 上复现既有失败，补针对 harness 的失败测试。
- [x] 移除手工残缺 context；派生项以独立事实断言验证并报告迁移，不放宽 legacy 对照。
- [x] 运行 10 份快照的旧/新 Golden，报告 8 个可评价、2 个无 review 的显式跳过。

Golden 首次完整对照暴露 5 份专业组快照的合作办学漏报：已选专业名称仍含“中外合作”，但 unit 投影没有保留成员名称的风险标记。此差异不是合理迁移；追加 `EvaluationContextBuilder` 的 canonical cooperation 标签修复与对应 RED→GREEN 测试，并 bump `objective-compiler-v3`。最终对照必须复跑，不能将原漏报登记成预期成功。

## Task 2: Original Probe Preflight

**Files:** 新建 `service/biz/FindingPostconditionEvaluator.java`、`model/dto/planning/FindingPostconditionDTO.java` 和相邻测试。

**Interfaces:** `evaluate(String findingCode, ReviewStateDTO freshlyEvaluatedReview)` 返回原 probe/硬约束是否满足及明确原因；供冻结预览和后续 apply 共用。

- [x] 测试原 probe 仍 fail（尤其 safety）、unknown/missing/unavailable、硬约束失败、成功。
- [x] 运行测试确认 RED，再实现最小 evaluator 并确认 GREEN。

## Task 3: Readonly Frozen Ordering

**Files:** 新建 `DirectReviewPreviewPlanner.java`、`FrozenReviewPlanDTO.java`；修改 `FixProposalDTO.java`、`PlanOrderingEngine.java`、`PlanningStateService.java`；新增 planner/engine/controller 回归。

**Interfaces:** planner 消费 typed finding、完整 state/候选和只读审查复算函数；产出有稳定 proposalId/previewDigest、完整冻结 selected/ordered/facts 和 preflight 的 FixProposalDTO。

- [x] 测试完整排序、稳定 digest、输入隔离、事实变化、缺失候选/概率、pin/lock/组模式拒绝、硬约束/原问题失败。
- [x] 运行测试确认 RED；扩展纯排序引擎并物化真实冻结后态，不制造 solverResult。
- [x] 在只读 preview 接入受支持的排序，验证无持久化、无 pending、版本不变。

## Task 4: Verification And Handoff

- [x] 独立代码审查，修复有依据的问题。
- [x] 执行定向、Golden、全量 Java 回归和 diff 检查。
- [x] 更新验收文档和 spec 状态，明确 prepare/执行/组内替换/Search 未切换。

最终证据：Java clean test 1341 项零失败、10 跳过；显式 Golden 24 项零失败，两套快照均 8 可评价/2 无 review 跳过，历史状态差异 0。独立审查两项 P2 均 RED→GREEN 并复审关闭。详见 `docs/superpowers/reviews/2026-10-19-j55b-frozen-preview-preflight-acceptance.md`；本计划仅完成 b 前置批次，不代表 b 确认执行闭环完成。
