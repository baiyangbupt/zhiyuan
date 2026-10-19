# J5.5a Command And Readonly Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地逐 probe 的类型化绝对命令与独立只读审查预览，保留现有确认执行链。

**Architecture:** Evaluation mapper 在所有 findings 派生完成后统一生成 typed delta；唯一 compiler 转换为绝对目标并计算 canonical digest。新增只读入口复用审查计算，但只使用只读 loader 和内存候选解析，不写 overlay/review/proposal/pending。a 阶段命令均不可执行，不把 legacy proposal 冒充 frozen preview。

**Tech Stack:** Java 8, Spring Boot 2.3.8, JUnit 5, Mockito, Maven。

**Spec:** `docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`；以 `docs/superpowers/reviews/2026-10-19-j55-review-to-action-design-review.md` §7 的修订要求优先。

## Global Constraints

- 不切换旧 `/fix-proposals/generate`、prepare、apply、Python 确认链；b 具备冻结后态和原 probe 后置校验后才切换。
- pass/not_applicable/unknown/needs_input 不产生修复命令；不支持的组内替换不编造 unit 替换。
- 现有区间目标保留区间；安全派生阈值仅为 effective target，不写长期用户目标。
- 本阶段命令 `executable=false`，`requiresConfirmation=true`。
- 不重启服务、不部署、不提交；保留工作区已有非本任务修改。

## Task 1: Typed Command And Probe Compilation

**Files:** 新建 `PlanCommandDTO.java`、`PlanCommandCompiler.java`、`FindingObjectiveDeltaBuilder.java`；修改 `ObjectiveDeltaDTO.java`、`EvaluationFindingDTO.java`、`ReviewEvaluationMapper.java`、`EvaluationVersion.java`；删除旧 `CompiledActionDTO.java`、`ActionCompiler.java`。目录分别为 `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/` 与 `service/biz/`。

- [x] 增加行为测试：绝对 count/safety/coverage、区间保留、unknown/unsupported、canonical digest、输入隔离。
- [x] 执行定向测试，确认 RED。
- [x] 实现 typed delta 与 compiler，最终 findings 统一编译；明确 capability 与来源。
- [x] 更新旧类型断言，执行 mapper/compiler/golden 和 legacy proposal 回归（旧 Golden 基线失败单独记录）。

## Task 2: Pure Read Preview

**Files:** 新建 `ReviewFixPreviewDTO.java`、`common/exception/ReviewFixStaleException.java`；修改 `PlanningStateService.java`、`PlanningStateController.java`、`common/config/GlobalExceptionHandler.java`；新增相应 service/controller 测试。

- [x] 增加只读预览测试：fresh findings、版本不变、零持久化/overlay/pending、副作用隔离、stale 拒绝。
- [x] 执行定向测试，确认 RED。
- [x] 拆出共享内存审查计算，新增 `/session/fix-proposals/preview`，返回 evaluation/commands，不返回可执行假卡。
- [x] 执行只读与原 runReview/generate 回归测试。

## Task 3: Review And Handoff

- [x] 回填 spec 的第三轮修订：一次确认、冻结与后置校验前置、区间/effective 目标、FILL 保留。
- [x] 执行 Java 完整测试与 diff 检查；不改无关失败。
- [x] 记录实际测试证据和剩余 b/c 门禁，明确未切换线上执行路径。

验收记录：`docs/superpowers/reviews/2026-10-19-j55a-command-and-readonly-preview-acceptance.md`。
最终全量测试 1293 项零失败、10 跳过；命令快照 8 份通过、2 份无审查结果显式跳过。
旧 J5.0 Golden 的既有失败已在未修改 HEAD 复现，仍为 b/c 切流前待解决项。
