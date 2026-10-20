# Planning Integrity Stack Acceptance Plan

> **For agentic workers:** Execute this plan with read-only preflight and isolated runtime checkpoints. Preserve the current working tree and do not commit or deploy during acceptance.

**Goal:** Verify the repaired confirmation and solver contracts against real HTTP/WS services and MySQL persistence without changing the existing local stacks.

**Architecture:** The active 3201 and 3001 stacks share `zhiyuan_codex_local`, so neither is treated as a disposable dataset. Build the current backend from a separate source copy; create a new local schema with selected fixture copies and use temporary ports 18390/18391. Preserve the existing Web, Rank, Java and Agent processes.

**Tech Stack:** Java 8 / Maven offline, Python 3.10, MySQL, Redis, HTTP/WebSocket.

**Spec:** `docs/superpowers/specs/2026-10-19-j55-review-to-action-design.md`; `docs/superpowers/reviews/2026-10-20-planning-integrity-repair-verification.md`.

**Status:** Acceptance and the approved P2 follow-up are complete. The no-commit constraints below applied during acceptance; subsequent explicit user approval authorizes the separate local batch-commit closeout recorded at the end. No push, deployment or runtime update is authorized by this closeout.

## Global Constraints

- Do not change authentication/account settings, shared runtime feature flags, source session records or existing PID files.
- Do not overwrite `zhiyuan-server/target/zhiyuan-server.jar`: the running 18290 process uses it.
- Build from a private `/tmp/planning-integrity-stack-build-*` source copy.
- Create only a new `zhiyuan_integrity_acc_*` schema on verified localhost MySQL port 13306; keep source fixtures 900700/900045 unchanged.
- Reserve only an empty Redis logical database; do not flush shared Redis databases.
- Enable repair/initial/group-inner flags only for the temporary backend process.
- Store private generated configuration and detailed runtime evidence below ignored `.local/codex-local/`; do not print credentials or raw personal data.
- Stop only temporary processes whose recorded command identity matches this acceptance run. No existing service restart, production operation, commit or push.

## 1. Read-only preflight

- [x] Confirm current branch and preserve all unrelated frontend/docs changes.
- [x] Map active services and confirm 3201/18290/18291 and 3001/18090/18091 listeners.
- [x] Confirm both Java stacks use the same local MySQL/Redis configuration.
- [x] Confirm the running jar predates the repaired source and must not be reused as evidence.

## 2. Isolated runtime

- [x] Build a fresh backend jar in the separate source copy.
- [x] Clone schema and selected fixture rows into a new acceptance database; record source hashes and runtime ownership.
- [x] Start backend 18390 and Agent 18391 against the copied dataset, with isolated Redis/thread bindings.
- [x] Verify authenticated health, local-only destinations, current artifact hash, and unchanged existing listeners.

## 3. Behavioral acceptance

- [x] Run preview → prepare → claim → execute → complete for major and majorGroup fixtures, after fixture normalization; record the separate legacy-summary failure below.
- [x] Verify ordinary count FILL preserves compliant selections and frozen major identities.
- [x] Verify explicit coverage identity, cancel/replacement barriers and successful new-preview confirmation through real Python tools and HTTP, without a model.
- [x] Verify direct apply, unclaimed/expired claims, lock/pin and stale confirmations reject before mutation.
- [x] Verify duplicate execution is replayed without a second plan mutation.
- [x] Verify an infeasible confirmed initial target fails with the persisted plan unchanged.
- [x] Distinguish real HTTP/tool execution from real model-driven WS conversation; ticket preflight returned 401 without a browser-user login, so model-driven WS remains unverified.

## 4. Closeout

- [x] Record pass/fail evidence, any new reproducible defects and remaining failure-audit/objective-digest deferrals.
- [x] Verify source fixture hashes and the original live jar/listeners remain unchanged.
- [x] Stop owned temporary processes; retain the isolated schema/evidence for inspection without destructive cleanup.
- [x] Report whether the current patch is ready for the proposed batch commits; do not commit automatically.

## Initial acceptance outcome (before approved follow-up)

Acceptance execution is complete, but the patch is **not acceptance-green**: 20 scenarios passed and two legacy-state scenarios reproduced the same P2 defect. A completed checkbox records execution/evidence, not release approval.

- Initial P2, now fixed in the follow-up below: review preview/prepare accept a legacy ordered summary with `targetCount=0`, but the executor calls the mutating `getPlanningState` before frozen replay. Read-backfill changes the summary covered by `planContentDigest`, and legitimate confirmation fails with `409 review_fix_stale` without an intervening user edit. Major and majorGroup cases both reproduce it; the command transaction rolls back.
- Normalized fixtures pass all six main paths. Normalization was an acceptance-control variable, not a production fix or a reason to waive the legacy-state defect.
- Browser-user authentication was not supplied. An internal service credential does not grant a browser WS ticket; the preflight correctly returned `401 unauthenticated`. No authentication bypass, account switch or external model call was attempted.
- No new production code was changed during this acceptance pass. Resolve the legacy-state defect with a focused regression before declaring the backend batch ready; failure auditing and full objective-digest closure remain separate follow-ups.

Evidence and exact scope: `docs/superpowers/reviews/2026-10-20-planning-integrity-stack-acceptance.md`.

## 5. Approved P2 follow-up

The user approved the bounded follow-up: use the read-only loader for the claimed review-command pre-execution version check; retain all frozen-digest and owner guards and leave other command paths unchanged.

- [x] Add red regressions using the real PlanningStateService loader and executor for both legacy summary shapes, plus real version/content drift: four red cases (two `review_fix_stale` errors and two unexpected read-backfill mutations).
- [x] Apply the minimal loader selection change and run focused/full backend tests: 123 focused; 1601 total, zero failures/errors, 10 skipped. Add a compatibility case for user-goal execution with the review flag enabled.
- [x] Build a fresh isolated artifact and rerun raw legacy fixtures without GET-state normalization, plus relevant refusal/replay/tool/rollback boundaries: 22 scenarios passed, including six raw legacy main paths and explicit version/content drift refusal. The two tool-lifecycle cases retain the existing pre-preview warm-up setup.
- [x] Stop owned processes, verify original fixture/artifact/listener integrity, and update the acceptance conclusion.

## Follow-up outcome

The approved P2 is closed: legitimate raw legacy-state confirmations now succeed in both models, while real version/content drift still rejects without mutation. The bounded repair is ready for the proposed batch-commit review; it is not full release acceptance.

- Fresh isolated run: `zhiyuan_integrity_acc_20261020_170509`, with evidence under `.local/codex-local/planning-integrity-acceptance-readonly-20261020/`.
- Only the feature-enabled review-command pre-execution version read uses `loadPlanningStateReadOnly`; legacy, user-goal and other command paths retain their existing loader.
- All six main HTTP paths start with `targetCount=0`, with no GET-state fixture normalization. Both formerly failing count cases now complete version 7→8 and replay without a second mutation.
- Python lifecycle unit regression: 44 passed. No Python production code changed in this follow-up.
- Temporary Java 10731 / Agent 10832 stopped; source fixture hashes, original live jar hash and original service PID/listeners unchanged. Original 3201/3001 runtime artifacts were not updated.
- No commit, push or deployment occurred during acceptance. Model-driven WS acceptance, independent failure audit and full objective-digest closure remain deferred as documented.

## Approved Batch-Commit Closeout (2026-10-20)

- [x] After explicit user approval, rerun full Java/Python unit suites: Java 1601 tests, zero failures/errors, 10 skipped; Python 2978 passed, 32 skipped, 20 warnings.
- [x] Verify the planner/solver-only snapshot independently: 1581 Java tests, zero failures/errors, 10 skipped, without the execution repair batch.
- [x] Commit the three code batches separately: `b38eaf4` (Python confirmation lifecycle), `60b10f3` (planner/solver integrity), `41747d1` (claimed execution and frozen replay).
- [x] Record acceptance and commit evidence in a separate documentation batch; preserve unrelated frontend edits and historical documents.

The 22 isolated scenarios refer to the completed acceptance run above; this submission phase reruns unit suites only and does not restart the isolated stack or access the shared session database. Runtime rollout and model-driven WS acceptance remain separate work.
