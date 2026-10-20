# Planning Integrity Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Close the important confirmation, mutation-authority, and frozen solver integrity findings from the two latest reviews.

**Architecture:** Preserve the approved evaluation → preview → prepare → claimed execution flow. Enforce authorization before mutation, distinguish optional initial optimization from confirmed hard objectives, and use the same selected-major facts for solving, freezing, and materialization. No new features or rollout expansion.

**Tech Stack:** Java 8, Spring, Maven/JUnit 5; Python 3.10+, Pydantic AI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`; `docs/superpowers/reviews/2026-10-20-initial-plan-optimizer-validation.md`; review findings in this conversation.

## Global Constraints

- Preserve existing unrelated working changes; do not commit during implementation without separate user approval, deploy, restart, or change runtime feature flags. The subsequently approved batch commits are recorded below.
- Use existing dependencies and Java 8-compatible APIs.
- Add regression tests before fixes and observe their expected failure.
- Keep Maven execution centralized; worker diagnostics may compile into separate `/tmp` directories.
- Git 1.8.3.1 has no worktree support; work in the current non-main branch with disjoint file ownership.

## Task 1: Confirmation candidate lifecycle

**Files:** `zhiyuan-agent/app/zhiyuan_agent/tools.py`; focused Python unit tests.

- [x] Reproduce canceled previews, newer unavailable previews, and mismatched coverage identity.
- [x] Make cancellation and newer preview results terminate historical candidate eligibility; never revive a canceled/replaced preview.
- [x] Match explicit `coverage:<index>` exactly while retaining generic coverage ambiguity handling.
- [x] Run focused tests and relevant Python unit regressions.

Task 1 checkpoint: 44 focused lifecycle/coverage tests and the full Python unit suite pass; full result is 2978 passed, 32 skipped, 20 warnings. Real-LLM opt-in cases remain disabled. Sandboxed socket/WebSocket restrictions required the full suite to be rerun outside the sandbox.

## Task 2: Review mutation authorization

**Files:** review preview planners and a shared protection helper; `UserGoalProposalBuilder.java`; adjacent tests.

- [x] Reproduce deletion of locked working units, movement of item-level pins, and ordinary count-fill removal of compliant existing selections.
- [x] Centralize protection checks across working/ordered item and unit carriers, failing closed for unsupported protected plans.
- [x] Require hard retention for ordinary count FILL, preserving authorized structural repair paths.
- [x] Carry required-major count into FILL policy and add negative/positive regression cases.

Task 2 checkpoint: isolated Java 8 compilation and JUnit verification pass 222/222. The same tests against the baseline implementation show 33 failures. Structural-replacement authority now comes from the current include/quota request rather than the mere existence of historical coverage/tier objectives.

## Task 3: Solver fact and reduction integrity

**Files:** `CandidateSnapshotBuilder.java`, `InitialContentPolicySupport.java`, `InnerMajorPlanBuilder.java`, `StagedDeterministicPlanSolver.java`, `CandidatePoolReducer.java`; focused tests.

- [x] Reproduce incorrect actual-major risk baseline, current-group coverage, phase-two cap mismatch, and the 600/601 reduction regressions.
- [x] Represent retained current units with their actual selected majors; reuse stage-one planned majors in stage two.
- [x] Make baseline content checks read actual selected majors even with group-inner optimization disabled.
- [x] Protect priority witnesses and preserve feasibility for initial content constraints during reduction.

Task 3 checkpoint: isolated verification passes 82 tests, five original failure probes, and three 601/1001/10001-candidate scale probes. Witness models stay within 600 candidates. Budget exhaustion or timeout remains a fail-closed diagnostic, not a claim of universal feasibility.

## Task 4: Claimed execution and exact replay

**Files:** `PlanningStateService.java`, `PendingPlanningCommandBizService.java`, `CanonicalPlanningRuntime.java`; runtime/service/executor tests.

- [x] Reproduce public apply bypass, confirmed-goal fallback, and frozen-major substitution.
- [x] Reject direct review apply under the new command path; invoke replay only from the claim-validated executor.
- [x] Permit initial fallback only for optional optimization, never silently ignore confirmed selection/coverage/tier requirements.
- [x] Carry the frozen major map through mutation and validate actual selected-major identity.
- [x] Preserve legacy/user-goal compatibility where explicitly supported.

Task 4 checkpoint: the runtime, frozen review replay, and pending command suites pass together: 116 tests, zero failures/errors. Additional malformed major-map regressions first failed in three cases, then passed with pre-mutation validation. Full integration and independent review remain pending.

## Task 5: Integration and verification

- [x] Run targeted Java/Python tests, then full Java and relevant Python unit suites.
- [x] Independently review the patch and resolve material findings.
- [x] Record verified coverage and any explicitly deferred issues without claiming deployment readiness.

Repair-phase test checkpoint after the independent-review fix: Java 1596 tests, zero failures/errors, 10 skipped; Python 2978 passed, 32 skipped, 20 warnings. `git diff --check` passes. Whole-patch review found one major-order contract mismatch; two regression tests reproduced it, the implementation was aligned with the existing order-independent selection digest, and scoped re-review closed the finding with no remaining important findings in this repair scope.

Verification and explicit deferrals: `docs/superpowers/reviews/2026-10-20-planning-integrity-repair-verification.md`. Keep the existing branch and unrelated working changes in place; no deployment or runtime change is part of completion.

## Approved Batch-Commit Closeout (2026-10-20)

After the separately approved acceptance follow-up, the user approved local batch commits. The acceptance-discovered read-backfill defect is fixed; the latest isolated stack result is 22 passed. This is bounded repair acceptance, not full J5.5 or release acceptance.

- [x] Rerun full Java tests before committing: 1601 tests, zero failures/errors, 10 skipped.
- [x] Rerun full Python unit tests outside the socket-restricted sandbox: 2978 passed, 32 skipped, 20 warnings.
- [x] Verify the planner/solver batch independently against the original backend baseline in a `/tmp` source snapshot, without the executor batch: 1581 tests, zero failures/errors, 10 skipped.
- [x] Commit Python lifecycle repairs (`b38eaf4`), planner/solver repairs (`60b10f3`), and executor/replay repairs (`41747d1`) separately; record the plans and verification in a documentation-only batch.
- [x] Exclude existing frontend edits, generated artifacts, unrelated historical documents, private configuration and acceptance evidence. No push, deployment or service restart is part of this closeout.

## Interface/Ownership Check

| Tasks | Shared interface | Resolution |
|---|---|---|
| 1 / 2–4 | Existing prepare/execute payload | No wire-format change required. |
| 2 / 3 | `MutationPolicyDTO.requiredMajorCount` and FILL semantics | Task 2 sets count; Task 3 reuses stage-one plans, with raw fallback only for legacy facts. |
| 3 / 4 | `selectedMajorIdsByUnit` and current-unit planned facts | Task 3 produces truthful plans; Task 4 replays and verifies them without reselecting. |
| 2 / 4 | Review planner protects users; executor validates claim | Both must hold; planner checks do not replace execution authorization. |
| 4 / initial fallback | Confirmed versus temporary objectives | Existing confirmed objective compiler determines whether fallback is allowed. |

Each task's tests assert behavior rather than source text. Production write scopes are disjoint; integration tests are coordinated by the main worker.
