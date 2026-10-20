# Review Solver Contract Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans, with local execution and review checkpoints; no delegated workers are authorized for this batch.

**Goal:** Implement the approved J5.5 §2.5/§4.4 distinction between confirmed objectives, solver objectives and the final frozen result.

**Architecture:** Keep the existing readonly preview → prepare → claim → transactional frozen replay. Record a separate digest at the staged-solver boundary after enrichment and planner patches. Before replay, compare the frozen confirmed-objective digest with `compileConfirmed(state)`. Before and after persistence, independently count final selected facts against every confirmed selection/coverage/tier objective and compare the frozen solver results. Keep the original finding probe mandatory.

**Tech Stack:** Java 8, Spring/MyBatis, Maven/JUnit 5, existing deterministic solver.

**Spec:** `docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md` §2.5, §4.3, §4.4.

## Global Constraints

- Implementation phase: no dependency, DDL, feature-flag, deployment, restart, branch or commit changes. The subsequently approved local submission phase is recorded below; it does not authorize push, merge or deployment.
- Preserve user-goal and legacy/off-switch paths, and all unrelated frontend/docs changes.
- New solver digests are audit metadata, not a replacement for the pre-enrichment canonical digest or frozen input digest.
- Existing frozen review commands without the new audit field remain executable if their existing canonical/result contract validates; one-sided or inconsistent new digest metadata is rejected.
- No re-solving during apply; unknown/missing/duplicate hard objective results fail closed.

## Task 1: Close Failure Audit Verification

- [x] Reproduce exception-payload leakage in the audit fallback log, then retain only operation ID and exception type.
- [x] Verify real Spring Boot/MyBatis prepare, claim, plan write, rollback, independently committed failed command and reconcile in a fresh local-only cloned schema.
- [x] Verify successful Direct/Search commit and idempotent replay in the same business stack.
- [x] Record final fresh verification and the remaining process-crash/audit-storage failure window.

## Task 2: Separate Objective Digests

- [x] Add failing behavior tests for actual enriched/patched solver digest, canonical mismatch and frozen metadata disagreement.
- [x] Carry `solverObjectiveDigest` from the staged solver into all solver-backed proposals and pending snapshots; preserve confirmed digest semantics and preview binding.
- [x] Verify Direct and older pending compatibility.

## Task 3: Verify Final Solver Results

- [x] Reproduce forged/missing frozen objective results that pass the original finding probe.
- [x] Validate exact frozen selection/order/selected majors and independently recompute selection, confirmed coverage and tier results from the final state.
- [x] Expose verified objective metadata/results in the execution report without introducing a second solving path.
- [x] Run focused tests, the full Java suite, dedicated DB regressions, diff checks and runtime-artifact protection checks; record evidence without credentials.

## Task 4: Approved Local Submission and Isolated Acceptance

- [x] Independently verify the audit-only batch on the original baseline, excluding objective-contract assertions.
- [x] Commit the failure-audit batch locally as `65f58a7`.
- [x] Reproduce and close the missing Search solver result and nested working-major validation gaps.
- [x] Reproduce and close three review findings: unselected-major coverage overcount, unchecked flattened working items, and legacy group-mode normalization.
- [x] Verify the complete source snapshot: 71 apply tests, 1652 full Java tests with 12 skipped, 8 full-stack database tests, 4 transaction-boundary tests, and 66 related Python tests.
- [x] Commit the objective-contract batch locally as `915a8df`, preserving all unrelated work.
- [x] Run isolated HTTP acceptance with a newly cloned database and the temporary jar; record the exact scope without claiming real-model WS or browser coverage.
- [x] Prepare and verify the plan and verification records for a separate local documentation commit, with no push, deployment or restart of existing services.
