# Codex App Server PoC / Shadow Report

## Fixed runtime

- Codex App Server commit: `89650c6`
- Transport: stdio JSONL
- Python MCP SDK: `mcp==1.12.4`
- Domain MCP: 8 read-only tools, 0 write tools

## Checks

- initialize, thread/start, inject_items, turn/start, outputSchema and thread/resume were verified against the fixed Codex binary.
- Thread binding and MCP `_meta.threadId` propagation were verified with the binding fixture; model-supplied identity fields are ignored.
- `skills/list` discovers the six Zhiyuan planner Skills after `skills/extraRoots/set`; only metadata is listed until the selected Skill is read.

## Shadow gates

The offline runner accepts only `baseline_manifest.json`, `golden_cases.json` and `adversarial_cases.json`. It emits one JSONL trace per baseline case with correlation IDs, snapshot version, Skill, tool/evidence counts, write flag, latency and status. It never accepts arbitrary production session IDs or connects to production services.

The hard gates are `unauthorizedWrites`, `unknownAdmissionUnits`, `factsWithoutEvidence` and `crossSessionProposalUse`; all must be zero for GO. Differences in wording, latency or candidate ranking are reported separately and do not by themselves establish superiority.

## Limitations

This report covers deterministic fixtures and protocol checks, not live model quality or production traffic. The first phase keeps plan mutation and final CAS execution outside Codex.

## Pilot verification record

- Python target suite: `60 passed, 1 skipped`.
- Java target suite: Maven exit code 0 for conversation contracts, snapshot, binding, controller and planning-state tests.
- Frontend: Node event tests passed; `npm run build:dev` passed in the authorized build environment. Full TypeScript checking still reports pre-existing repository errors outside this pilot.
- Fixed Codex protocol/binding check: `initialize=ok`, `thread_start=ok`, `inject_items=ok`, `turn_start=ok`, `output_schema=ok`, `thread_resume=ok`, `binding=trusted`, `model_identity_override=ignored`, `revoked=denied`.
- Legacy regression: `test_state_sync.py` passed 40 tests. The existing `test_ws_compat.py` and `test_chat_service_history_persistence.py` suites exceeded the local timeout without failure output; they are not claimed as passing and should be rerun in CI or a full service environment before production canary.

The release gate is therefore suitable for offline/Shadow validation, not an unconditional production rollout. Keep `GATEWAY_MODE=legacy` until the two timed-out legacy suites complete in a service-backed environment.
