# Architecture Review Hardening Implementation Plan

> **For agentic workers:** Execute task-by-task using the executing-plans workflow. Each task uses test-driven development; do not commit, deploy, restart services, or replace concurrent user changes.

**Goal:** Close the confirmed security, admission-tier and request-idempotency defects from the architecture review against the updated working tree.

**Architecture:** Keep Java authoritative for planning state and commands. Bind every WebSocket message to its authenticated connection identity, sanitize rendered Markdown, classify unknown probabilities separately, and wire durable request admission without consuming rejected requests. Protect internal HTTP routes with an explicit service credential and document the coordinated rollout.

**Tech Stack:** FastAPI/Python, Spring Boot/Java 8, Next.js/React, Redis, pytest, JUnit, Node test runner.

**Baseline:** Started at `5c1344a`; preserve the existing modified `zhiyuan-web/tsconfig.tsbuildinfo` and untracked Next build directories. Work in the current checkout as requested, without creating branches.

## Tasks

- [x] Connection identity: add negative message/control/compat/legacy tests, observe failures, then enforce ticket scope before dispatch. Missing trusted identity must fail closed.
- [x] Markdown: add malicious HTML/protocol and normal-formatting tests, observe failures, then use a maintained HTML sanitizer shared by all Markdown sinks.
- [x] Admission tiers: add null/non-finite/out-of-range/fractional boundary tests, observe failures, then use continuous ranges and an explicit unknown bucket excluded from automatic safety selections.
- [x] Request admission: add busy/retry/concurrency/digest/duplicate tests, observe failures, then wire Redis admission, serialize per-session admission, and expose duplicate recovery rather than silently discarding it.
- [x] Internal API authentication: add HTTP-boundary tests, observe failures, then protect internal/admin/debug/evidence routes and propagate credentials through Agent/MCP and operational probes. No production rollout in this task.
- [x] Operational safeguards: eliminate the implicit production backend fallback; bound disposable gateway caches and document the remaining durable-artifact/multi-instance limits. Do not change approved automatic-plan product behavior or attempt broad service extraction.
- [x] Validation and handoff: run focused suites and broader offline regression checks, review the diff, document exact rollout requirements and deferred architectural work. Report unrelated baseline failures separately.

## Validation

- Python: focused WebSocket, runtime, event-store, HTTP-client, configuration and gateway suites; offline unit/integration suites where feasible.
- Java: targeted interval and internal-authentication tests, then relevant planning/ranking tests against existing dependencies. No live shared-database tests.
- Web: Node security/formatting tests and existing utility suites; type-check without incremental writes and distinguish pre-existing errors.
- Final: `git diff --check`, working-tree review, no generated build artifacts or secrets in the patch.

## Deferred Architectural Work

- Distributed session ownership/fencing and multi-worker support need a separate migration, not an additional uvicorn worker flag.
- Durable MCP artifact registration and canonical geographic-ID migration need explicit storage/API contracts.
- Large planning/workspace service extraction and complete legacy TypeScript/lint cleanup are separate refactors; this batch must not disguise them as completed.
- Automatic prefilled plans remain existing approved product behavior; read/write separation requires an agreed state contract before changing it.

## Execution Notes

- Independent review found two additional defects within scope: detached action receipts were marked complete before execution ended, and installed curl 7.29 does not support stdin header files. Both were corrected with regression coverage, including actual native/compat workers and host-curl file-only checks.
- Busy-followup regression exposed Python closure rebinding: accepted native progress and compat work could inherit a later message's turn/content. Task inputs and emitters now capture their original scope.
- Real Redis tests use a disposable `--network none` container and Unix socket, not a shared database. Node 22 tests use an existing isolated container with a read-only repository mount because the host glibc cannot run the installed Node 22 binary directly.
- Baseline TypeScript diagnostics are identical to the modified checkout. The existing clone-source quality gate lacks local session fixture files, and one fake-harness integration assertion already expects tool progress before the current assistant delta; both reproduce against `7b6a0a4` in temporary extracted copies.
- Final verification: 2382 offline Python unit tests passed (33 e2e + one baseline fixture check deselected), 45 focused integration tests passed/one missing-binary skip, 18 real isolated-Redis tests passed, 76 offline Java tests passed, 118 Node tests passed, and isolated Chromium rendering passed. Existing streaming first-frame assertions and TypeScript/lockfile baseline debt remain explicitly listed in `../reviews/2026-10-16-architecture-hardening-handoff.md`.
- Independent scoped re-review approved both the receipt and curl-probe repairs; no serious findings remain within the stated single-worker/retention contract. Changes remain uncommitted and undeployed.
