# Admission Evidence Fact Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a read-only, evidence-backed admission fact layer that treats `major` (专业+大学) and `major_group` (院校专业组) as a cross-cutting conversation dimension, validates system-provided admission rates and risk tiers, and renders only verified facts.

**Architecture:** Java remains the authority for admission-unit data and the existing probability calculation. A canonical `AdmissionMode` is derived from the session's `VolunteerModel` at the Java/Python boundary and travels through snapshots, state patches, MCP requests/responses, Evidence, Gateway outputs, Shadow fixtures, and frontend events. Python validates facts and references without recomputing probabilities; write paths remain unchanged.

**Tech Stack:** Python 3.10, Pydantic v2, FastAPI, pytest, Domain MCP; Java 8, Spring Boot, Lombok, JUnit 5, Maven; TypeScript/React frontend with Node tests.

---

## Scope and Compatibility Rules

The implementation must preserve the existing `legacy` default and existing backend field names while adding a strict canonical boundary:

- Canonical values are `major` and `major_group`.
- Java's `VolunteerModel.major` maps to `major`; `VolunteerModel.majorGroup` maps to `major_group`.
- The adapter may accept `majorGroup`, `major_group`, and `major` as input aliases, but all emitted contracts use canonical values.
- In `major` mode, one admission unit is one professional + university plan (`planMajorDataId` plus the school plan identity).
- In `major_group` mode, one admission unit is one university major group (`planSchoolDataId`/`unitId` plus `groupCode`); group majors are nested details and never increase unit counts.
- A major-group card uses the unit/group admission rate and tier. A nested major rate is detail evidence only.
- Existing backend `admissionRatio`/`schoolEnrollRatio` fields are adapted; no probability is recomputed in Python, Java, or the browser.
- A session mode change invalidates admission Evidence, candidate/review/artifact projections, and active read-only caches. It cannot apply or reuse a proposal created under the other mode.

## File Map

### Python

- Modify `zhiyuan-agent/app/gateway/contracts.py`: canonical mode, admission fact/detail, Evidence fields, snapshot/state-patch fields.
- Modify `zhiyuan-agent/app/gateway/snapshot.py`: derive and project mode from authoritative workspace state; invalidate mode-dependent projections.
- Modify `zhiyuan-agent/app/gateway/output_validation.py`: validate admission facts, mode, rate/tier boundaries, Evidence scope and versions.
- Modify `zhiyuan-agent/app/mcp_server/response.py`: admission-aware envelope fields and structured error data.
- Modify `zhiyuan-agent/app/mcp_server/tools_readonly.py`: mode propagation, backend field adaptation, unit/detail validation, mode mismatch errors.
- Modify `zhiyuan-agent/app/harness/binding.py` or the existing context adapter only if the mode must be included in trusted MCP context; do not accept model-supplied identity.
- Create `zhiyuan-agent/app/admission/facts.py`: pure normalizers and validators shared by MCP/Gateway tests.
- Create `zhiyuan-agent/tests/unit/test_admission_facts.py`.
- Modify `zhiyuan-agent/tests/unit/test_domain_mcp_tools.py`, `test_output_validation.py`, `test_snapshot_projection.py`, and `test_shadow_metrics.py`.
- Modify `zhiyuan-agent/tests/fixtures/mcp/fake_backend.py` and `tests/fixtures/shadow/baseline_manifest.json` with both modes.

### Java

- Modify `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationTurnSnapshotDTO.java`: add canonical `admissionMode`.
- Modify `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationStatePatchDTO.java`: allow an `admissionMode` state path and mode invalidation metadata.
- Modify `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java`: add mode, unit, scope, algorithm and observation fields.
- Create `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/AdmissionFactDTO.java` and `AdmissionMajorDetailDTO.java` for strict serialization.
- Modify `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java`: derive canonical mode from `CandidatePoolStateDTO.getVolunteerModel()` and project mode-dependent evidence/state.
- Add focused tests under `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotServiceTest.java` and a DTO serialization test if the existing contract test does not cover the new fields.

### Frontend and docs

- Modify `zhiyuan-web/src/utils/conversationEvents.mjs` and its test for admission fact/evidence event normalization.
- Create or modify `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/AdmissionFactCard.tsx` and `EvidenceDrawer.tsx`.
- Modify `zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx` to show mode labels and mode-change invalidation.
- Modify `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/ArtifactRenderer.tsx` only through structured artifact data; never parse assistant Markdown.
- Create `zhiyuan-agent/docs/admission-evidence-runbook.md` and update the approved design/spec or pilot runbook with rollout checks.

---

## Task 1: Canonical Admission Mode and Pure Fact Validator

**Files:**
- Create: `zhiyuan-agent/app/admission/__init__.py`
- Create: `zhiyuan-agent/app/admission/facts.py`
- Create: `zhiyuan-agent/tests/unit/test_admission_facts.py`

- [ ] **Step 1: Write failing tests for mode aliases, unit identity, and tier boundaries**

```python
import pytest

from app.admission.facts import (
    AdmissionFactError,
    canonical_admission_mode,
    derive_risk_tier,
    validate_admission_fact,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("major", "major"), ("majorGroup", "major_group"), ("major_group", "major_group")],
)
def test_canonical_admission_mode_maps_backend_values(raw, expected):
    assert canonical_admission_mode(raw) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(49.99, "冲"), (50.0, "稳"), (69.99, "稳"), (70.0, "保"), (98.99, "保"), (99.0, "保")],
)
def test_derive_risk_tier_uses_fixed_unit_boundaries(rate, expected):
    assert derive_risk_tier(rate) == expected


def test_rate_above_99_is_not_silently_classified():
    with pytest.raises(AdmissionFactError, match="unsupported_admission_rate"):
        derive_risk_tier(99.01)


def test_major_mode_requires_specific_major_and_major_group_requires_group_code():
    with pytest.raises(AdmissionFactError, match="major_required"):
        validate_admission_fact({"admissionMode": "major", "unitAdmissionRate": 40})
    with pytest.raises(AdmissionFactError, match="group_code_required"):
        validate_admission_fact({"admissionMode": "major_group", "unitAdmissionRate": 40})


def test_major_group_keeps_unit_rate_separate_from_nested_major_rate():
    fact = validate_admission_fact({
        "admissionMode": "major_group",
        "admissionUnitId": "unit-1",
        "groupCode": "101",
        "schoolId": "school-1",
        "unitAdmissionRate": 45,
        "riskTier": "冲",
        "majorItems": [{"majorId": "m-1", "majorAdmissionRate": 85}],
    })
    assert fact["riskTier"] == "冲"
    assert fact["majorItems"][0]["majorAdmissionRate"] == 85


def test_invalid_model_tier_is_rejected_instead_of_trusted():
    with pytest.raises(AdmissionFactError, match="risk_tier_mismatch"):
        validate_admission_fact({
            "admissionMode": "major",
            "admissionUnitId": "unit-1",
            "majorId": "m-1",
            "schoolId": "school-1",
            "unitAdmissionRate": 40,
            "riskTier": "保",
        })
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_admission_facts.py -q`

Expected: FAIL because the canonical mode and fact validator do not exist.

- [ ] **Step 3: Implement the pure validator**

Implement `facts.py` with:

- `AdmissionMode = Literal["major", "major_group"]`.
- `canonical_admission_mode(raw: object) -> AdmissionMode`, raising `unsupported_admission_mode` for unknown values.
- `derive_risk_tier(rate: object) -> str`, accepting finite numeric percentages in `[0, 99]`, returning `冲` for `[0, 50)`, `稳` for `[50, 70)`, and `保` for `[70, 99]`.
- `validate_admission_fact(value: Mapping[str, Any]) -> dict[str, Any]`, normalizing camelCase/snake_case aliases, requiring `admissionUnitId`, school identity, mode-specific identity, `unitAdmissionRate`, and canonical tier, validating nested `majorItems` rates independently, and rejecting duplicate group detail IDs.
- `adapt_backend_admission_rate(value, *, mode)` that reads `unitAdmissionRate` first, then `admissionRatio` for `major`, then `schoolEnrollRatio` for `major_group`; it must return missing data rather than inventing a value.
- `mode_dependent_cache_key(mode, unit_id)` so caches from different modes cannot collide.

Do not add string matching against user prompts. This module consumes structured backend fields only.

- [ ] **Step 4: Run focused tests to verify GREEN and commit**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_admission_facts.py -q`

Expected: all focused tests pass.

Commit: `git add zhiyuan-agent/app/admission zhiyuan-agent/tests/unit/test_admission_facts.py && git commit -m "feat: add canonical admission fact validator"`

## Task 2: Extend Python Contracts and Versioned Snapshot

**Files:**
- Modify: `zhiyuan-agent/app/gateway/contracts.py`
- Modify: `zhiyuan-agent/app/gateway/snapshot.py`
- Modify: `zhiyuan-agent/tests/unit/test_snapshot_projection.py`
- Modify: `zhiyuan-agent/tests/unit/test_gateway_contracts.py`

- [ ] **Step 1: Add failing contract tests**

Add tests that assert:

```python
def test_snapshot_requires_canonical_admission_mode():
    snapshot = ConversationTurnSnapshot.model_validate({
        "snapshotVersion": 3,
        "sessionId": "s1",
        "admissionMode": "major_group",
    })
    assert snapshot.admission_mode == "major_group"


def test_state_patch_mode_change_requires_invalidation():
    patch = StatePatch.model_validate({
        "baseVersion": 3,
        "targetVersion": 4,
        "changes": [{"path": "admissionMode", "value": "major_group"}],
        "invalidations": [{"kind": "admission_mode", "reason": "mode_changed"}],
    })
    assert patch.changes[0]["value"] == "major_group"


def test_group_evidence_contains_group_scope_and_unit_rate_is_distinct():
    evidence = EvidenceRef.model_validate({
        "evidenceId": "ev-1",
        "sourceLevel": "authoritative",
        "dataVersion": "v17",
        "admissionMode": "major_group",
        "admissionUnitId": "unit-1",
        "groupCode": "101",
        "stateVersion": 4,
    })
    assert evidence.admission_mode == "major_group"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_snapshot_projection.py tests/unit/test_gateway_contracts.py -q`

Expected: FAIL for missing fields or unsupported `admissionMode` state path.

- [ ] **Step 3: Implement contract fields and projection**

Add to `contracts.py`:

- `AdmissionMode`, `AdmissionMajorDetail`, and `AdmissionFact` contract models.
- `EvidenceRef.admission_mode`, `admission_unit_id`, `group_code`, `algorithm_version`, `state_version`, `scope`, and `observed_at`.
- `TurnOutput.admission_facts` for structured fact output; recommendation/review outputs may reference facts only through validated artifact/evidence refs.
- `ConversationTurnSnapshot.admission_mode` and `admission_facts`/`evidence` fields.
- `StatePatch` allowed path `admissionMode`; enforce that a mode change includes an `admission_mode` invalidation record.

In `snapshot.py`, derive mode from `candidatePoolState.volunteerModel` or the authoritative backend mode field. Normalize `majorGroup` to `major_group`. When the derived mode differs from the previous snapshot, add invalidations for admission facts, Evidence, candidate projection, review projection, artifact projection, and active proposal; do not carry the old mode's references forward.

For legacy fixtures that omit the field, keep the adapter boundary permissive only while projecting the authoritative mode. The serialized Gateway snapshot and all new MCP requests must contain canonical `admissionMode`.

- [ ] **Step 4: Run contract and full targeted tests, then commit**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_snapshot_projection.py tests/unit/test_gateway_contracts.py -q`

Expected: all tests pass, including pre-existing snapshot tests updated with explicit mode fixtures.

Commit: `git add zhiyuan-agent/app/gateway/contracts.py zhiyuan-agent/app/gateway/snapshot.py zhiyuan-agent/tests/unit/test_snapshot_projection.py zhiyuan-agent/tests/unit/test_gateway_contracts.py && git commit -m "feat: carry admission mode through gateway snapshots"`

## Task 3: Make Domain MCP Admission Tools Mode-Aware

**Files:**
- Modify: `zhiyuan-agent/app/mcp_server/response.py`
- Modify: `zhiyuan-agent/app/mcp_server/tools_readonly.py`
- Modify: `zhiyuan-agent/tests/unit/test_domain_mcp_tools.py`
- Modify: `zhiyuan-agent/tests/fixtures/mcp/fake_backend.py`

- [ ] **Step 1: Write failing MCP tests for both admission modes and structured errors**

Cover these cases:

```python
async def test_major_group_history_returns_group_rate_and_nested_major_details(...):
    result = await tools.call("admission.get_history", {
        "admissionMode": "major_group",
        "areaId": "31", "batch": "本科批", "schoolId": "s1",
        "groupCode": "101", "year": 2026, "subjectType": "物理类",
        "stateVersion": 42,
    })
    assert result["data"]["admissionMode"] == "major_group"
    assert result["data"]["admissionFacts"][0]["unitAdmissionRate"] == 45
    assert result["data"]["admissionFacts"][0]["riskTier"] == "冲"
    assert result["data"]["admissionFacts"][0]["majorItems"][0]["majorAdmissionRate"] == 85


async def test_mode_mismatch_is_rejected_without_backend_call(...):
    result = await tools.call("admission.get_current_plan", {"admissionMode": "major"})
    assert result["status"] == "admission_mode_mismatch"
    backend.get_current_plan.assert_not_awaited()


async def test_missing_group_detail_is_insufficient_data_not_zero_rate(...):
    result = await tools.call("admission.check_eligibility", {
        "admissionMode": "major_group", "groupCode": "101",
    })
    assert result["status"] == "insufficient_data"
    assert "majorDetailAvailable" in result["limitations"]
```

- [ ] **Step 2: Run MCP tests to verify RED**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py -q`

Expected: FAIL because the envelope and tool dispatch do not carry/validate mode-specific facts.

- [ ] **Step 3: Implement mode-aware envelope and dispatch**

In `response.py`, extend `ok()` and `error()` with `admission_mode` and `data_version`, preserving existing top-level aliases (`stateVersion`, `resolvedEntities`, `evidence`, `limitations`).

In `tools_readonly.py`:

- Derive the trusted mode from the binding/session context and reject a request mode that differs from it with `admission_mode_mismatch` before dispatch.
- Strip model-controlled identity fields as today; `admissionMode` is an allowed semantic selector only when equal to trusted context.
- Normalize backend responses through `validate_admission_fact`.
- For `major`, require a concrete major identity and use the professional+university unit rate.
- For `major_group`, require group code/unit identity, use the group/unit rate, retain nested major details, and add `majorDetailAvailable=false` when details are absent.
- Return `insufficient_data` with `missingFields`/`limitations` for missing unit, year/batch, rate, or requested group details; never fill zero or reuse a previous version.
- Include one EvidenceRef per valid fact with `admissionMode`, unit ID, group code where applicable, data/algorithm versions, trusted session scope, and current `stateVersion`.
- Keep one retry for backend failures and cache only by `(tool, canonical arguments, trusted mode, stateVersion, dataVersion)`.

Update fake backend fixtures with one `major` fact and one `major_group` fact containing two nested majors. Add malformed, stale, and missing-data fixtures.

- [ ] **Step 4: Run MCP tests and self-check, then commit**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_domain_mcp_tools.py -q && .venv/bin/python -m app.mcp_server.server --self-check`

Expected: all tests pass; self-check reports eight tools, zero write tools, and both modes represented in read-only admission fixtures.

Commit: `git add zhiyuan-agent/app/mcp_server zhiyuan-agent/tests/unit/test_domain_mcp_tools.py zhiyuan-agent/tests/fixtures/mcp/fake_backend.py && git commit -m "feat: make admission domain mcp mode-aware"`

## Task 4: Enforce Admission Facts in Gateway Output Validation

**Files:**
- Modify: `zhiyuan-agent/app/gateway/output_validation.py`
- Modify: `zhiyuan-agent/app/gateway/service.py`
- Modify: `zhiyuan-agent/tests/unit/test_output_validation.py`
- Modify: `zhiyuan-agent/tests/integration/test_shadow_gateway.py`

- [ ] **Step 1: Write failing validation tests**

Add cases for:

- valid `major` fact with `<50` rate and `冲`;
- valid `major_group` fact with a group rate of `70` and `保`, plus a nested major rate of `40` that does not change the group tier;
- rate `99`, NaN, infinity, and missing rate;
- unknown unit ID or missing mode-specific identity;
- Evidence mode different from snapshot mode;
- Evidence with another session, thread, tenant, state version, or data version;
- fact/artifact recommendation with no EvidenceRef;
- mode change carrying an old artifact/proposal.

Example assertion:

```python
with pytest.raises(OutputContractError, match="admission_mode_mismatch"):
    validate_turn_output(
        turn_output={"responseType": "fact", "message": "", "evidenceRefs": ["ev-group"]},
        current_snapshot={"snapshotVersion": 8, "sessionId": "s1", "admissionMode": "major"},
        evidence_ledger={"ev-group": {"admissionMode": "major_group", "stateVersion": 8}},
        artifacts={},
    )
```

- [ ] **Step 2: Run validation tests to verify RED**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_output_validation.py tests/integration/test_shadow_gateway.py -q`

Expected: FAIL for missing admission fact/mode validation.

- [ ] **Step 3: Implement fail-closed validation**

Extend `validate_turn_output()` to:

- validate every structured admission fact with the pure validator;
- ensure fact mode equals snapshot mode;
- ensure each fact is backed by an EvidenceRef whose mode, unit ID, group code, tenant/session/thread, `stateVersion`, `dataVersion`, and algorithm version match;
- reject unknown unit references and nested-major duplicates;
- reject any model-supplied tier that does not equal the server-derived tier;
- reject mode-dependent artifacts/proposals after a snapshot mode change;
- return stable `OutputContractError` codes: `admission_mode_mismatch`, `admission_unit_not_found`, `admission_rate_invalid`, `risk_tier_mismatch`, `evidence_stale`, `evidence_scope_mismatch`, and `missing_admission_evidence`.

In `gateway/service.py`, pass the trusted snapshot mode into MCP calls and preserve the validated facts/evidence in `evidence.updated` and recommendation/review artifact payloads. A validation error must produce a recoverable structured result and must not persist an artifact or proposal.

- [ ] **Step 4: Run targeted Gateway/Shadow tests and commit**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_output_validation.py tests/integration/test_shadow_gateway.py -q`

Expected: all tests pass; invalid facts never reach output artifacts.

Commit: `git add zhiyuan-agent/app/gateway/output_validation.py zhiyuan-agent/app/gateway/service.py zhiyuan-agent/tests/unit/test_output_validation.py zhiyuan-agent/tests/integration/test_shadow_gateway.py && git commit -m "feat: validate admission evidence in gateway outputs"`

## Task 5: Project Canonical Mode and Admission DTOs in Java

**Files:**
- Create: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/AdmissionFactDTO.java`
- Create: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/AdmissionMajorDetailDTO.java`
- Modify: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationTurnSnapshotDTO.java`
- Modify: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationStatePatchDTO.java`
- Modify: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/ConversationEvidenceDTO.java`
- Modify: `zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java`
- Test: `zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotServiceTest.java`

- [ ] **Step 1: Add failing Java serialization and projection tests**

Cover both `VolunteerModel.major` and `VolunteerModel.majorGroup`:

```java
@Test
void snapshotUsesMajorModeForProfessionalUniversitySessions() {
    PlanningWorkspaceStateRes workspace = workspaceWithVolunteerModel("major");
    ConversationTurnSnapshotDTO snapshot = serviceUnderTest(workspace).getTurnSnapshot(1L, 2L, "admission-fact-analysis");
    assertEquals("major", snapshot.getAdmissionMode());
}

@Test
void snapshotUsesMajorGroupModeAndDoesNotFlattenNestedMajors() {
    PlanningWorkspaceStateRes workspace = workspaceWithVolunteerModel("majorGroup");
    ConversationTurnSnapshotDTO snapshot = serviceUnderTest(workspace).getTurnSnapshot(1L, 2L, "admission-fact-analysis");
    assertEquals("major_group", snapshot.getAdmissionMode());
}
```

Add DTO JSON assertions for `admissionMode`, `admissionUnitId`, `groupCode`, `unitAdmissionRate`, `majorItems`, `dataVersion`, and `algorithmVersion`.

- [ ] **Step 2: Run Java tests to verify RED**

Run: `cd zhiyuan-server && mvn -q -Dtest=ConversationSnapshotServiceTest test`

Expected: FAIL because the snapshot and Evidence DTOs do not expose canonical mode/fact fields.

- [ ] **Step 3: Implement DTOs and snapshot projection**

Use Lombok DTOs with explicit field names matching the Python contract. `AdmissionFactDTO` must contain mode, unit identity, group code, school/major identity, `unitAdmissionRate`, `riskTier`, optional nested `majorItems`, score/rank ranges, data and algorithm versions, observation time, and limitations. `AdmissionMajorDetailDTO` contains major identity and `majorAdmissionRate` only.

Add `admissionMode` to `ConversationTurnSnapshotDTO`, and add mode-aware Evidence fields to `ConversationEvidenceDTO`. Add `admissionMode` to `ConversationStatePatchDTO` or its change payload according to the existing DTO shape; mode changes must list invalidation targets.

In `ConversationSnapshotService`, normalize only the authoritative `VolunteerModel` value. Keep `majorGroup` as a backend-only compatibility input and emit `major_group`. Do not infer the mode from the number of `majorList` entries. Preserve the unit/group hierarchy when projecting workspace state.

- [ ] **Step 4: Run Java target tests and commit**

Run: `cd zhiyuan-server && mvn -q -Dtest=ConversationSnapshotServiceTest,ConversationContractSerializationTest test`

Expected: all selected tests pass and serialized fields use canonical names.

Commit: `git add zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/Admission* zhiyuan-server/src/main/java/com/ytell/zhiyuan/model/dto/planning/Conversation* zhiyuan-server/src/main/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotService.java zhiyuan-server/src/test/java/com/ytell/zhiyuan/service/biz/ConversationSnapshotServiceTest.java && git commit -m "feat: expose canonical admission mode in planning snapshots"`

## Task 6: Frontend Structured Admission Facts and Mode Boundaries

**Files:**
- Modify: `zhiyuan-web/src/utils/conversationEvents.mjs`
- Modify: `zhiyuan-web/src/utils/conversationEvents.test.mjs`
- Create: `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/AdmissionFactCard.tsx`
- Modify: `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/EvidenceDrawer.tsx`
- Modify: `zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents/ArtifactRenderer.tsx`
- Modify: `zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx`

- [ ] **Step 1: Write failing Node/React-facing normalization tests**

Test that:

- a `major` fact displays “专业+大学” and the unit rate/tier;
- a `major_group` fact displays “院校专业组”, group rate/tier, and nested majors separately;
- a mode-change event clears old facts/artifacts and marks the workspace for re-query/review;
- a fact without structured `unitAdmissionRate` renders no probability number, even when assistant Markdown contains one;
- stale/insufficient/error states render status text without fabricated numbers.

- [ ] **Step 2: Run frontend tests to verify RED**

Run: `cd zhiyuan-web && node --test src/utils/conversationEvents.test.mjs`

Expected: FAIL for missing admission event normalization and mode-specific rendering.

- [ ] **Step 3: Implement structured rendering**

Normalize `admissionMode` aliases at the event boundary. Add `AdmissionFactCard` with stable fields for mode, school, major/group, unit rate, tier, year/batch, and data status. For `major_group`, render group-level rate/tier first and nested major rates in a detail list with explicit labels.

Extend `EvidenceDrawer` to show Evidence ID, source, unit/group identity, data version, algorithm version, state version, observation time, scope, and limitations. The drawer must use structured event payloads only.

When a mode-change event arrives, clear mode-dependent event state and show a re-query/re-review status. Keep Proposal controls unchanged and non-executable for this read-only slice.

- [ ] **Step 4: Run Node tests and build, then commit**

Run: `cd zhiyuan-web && node --test src/utils/conversationEvents.test.mjs && npm run build:dev`

Expected: all tests pass and the development build succeeds.

Commit: `git add zhiyuan-web/src/utils/conversationEvents.mjs zhiyuan-web/src/utils/conversationEvents.test.mjs zhiyuan-web/src/pageComponents/sessionDetailV2/ConversationEvents zhiyuan-web/src/pageComponents/sessionDetailV2/WorkspacePanel/index.tsx && git commit -m "feat: render structured admission facts by mode"`

## Task 7: Shadow Fixtures, Hard Gates, and Runbook

**Files:**
- Modify: `zhiyuan-agent/tests/fixtures/shadow/baseline_manifest.json`
- Modify: `zhiyuan-agent/tests/unit/test_shadow_metrics.py`
- Modify: `zhiyuan-agent/scripts/codex_shadow_replay.py`
- Create: `zhiyuan-agent/tests/fixtures/shadow/admission_evidence_cases.json`
- Create: `zhiyuan-agent/docs/admission-evidence-runbook.md`
- Modify: `zhiyuan-agent/docs/codex-shadow-runbook.md`

- [ ] **Step 1: Add failing Shadow gate tests**

Add fixed cases for:

- valid professional+university fact;
- valid university major-group fact with nested details;
- exact rate boundaries 49.99, 50, 69.99, and 70;
- rate 99/data missing/unknown unit;
- wrong tier supplied by the model;
- no Evidence;
- cross-session Evidence;
- mode mismatch and mode switch with stale artifact;
- group detail requested but unavailable.

Assert metrics named `unknown_admission_units`, `facts_without_evidence`, `risk_tier_mismatches`, `stale_admission_evidence`, `cross_mode_references`, and `unsupported_rate_values` are all zero for the valid package and nonzero for deliberately invalid fixtures.

- [ ] **Step 2: Run the gate tests to verify RED**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_shadow_metrics.py -q`

Expected: FAIL because the replay and metrics do not inspect admission mode/fact invariants.

- [ ] **Step 3: Implement replay assertions and operational runbook**

Update the replay to record admission mode in each case/result and to fail closed when an admission fact lacks Evidence or uses a group detail as the unit fact. The runbook must document:

- canonical mode mappings;
- the unit-level rate and tier boundaries;
- group vs nested-major display semantics;
- missing/stale/version-mismatch behavior;
- exact commands for offline replay, MCP self-check, and log correlation;
- rollout defaults (`GATEWAY_MODE=legacy`, Shadow first) and rollback behavior.

- [ ] **Step 4: Run Shadow package and commit**

Run: `cd zhiyuan-agent && .venv/bin/python -m pytest tests/unit/test_shadow_metrics.py tests/integration/test_shadow_gateway.py -q && .venv/bin/python scripts/codex_shadow_replay.py --manifest tests/fixtures/shadow/baseline_manifest.json --admission-cases tests/fixtures/shadow/admission_evidence_cases.json --offline`

Expected: all tests pass; valid hard-gate metrics are zero and invalid fixtures are reported as rejected rather than rendered.

Commit: `git add zhiyuan-agent/tests/fixtures/shadow zhiyuan-agent/tests/unit/test_shadow_metrics.py zhiyuan-agent/scripts/codex_shadow_replay.py zhiyuan-agent/docs/admission-evidence-runbook.md zhiyuan-agent/docs/codex-shadow-runbook.md && git commit -m "test: add admission evidence shadow gates"`

## Task 8: Cross-Component Verification and Release Record

**Files:**
- Modify: `docs/superpowers/specs/2026-09-07-admission-evidence-design.md` only for verified implementation notes.
- Create: `docs/superpowers/verification/2026-09-07-admission-evidence-verification.md`.

- [ ] **Step 1: Run Python contract, MCP, Gateway, and Shadow tests**

Run:

```bash
cd zhiyuan-agent
.venv/bin/python -m pytest \
  tests/unit/test_admission_facts.py \
  tests/unit/test_gateway_contracts.py \
  tests/unit/test_snapshot_projection.py \
  tests/unit/test_domain_mcp_tools.py \
  tests/unit/test_output_validation.py \
  tests/unit/test_shadow_metrics.py \
  tests/integration/test_shadow_gateway.py -q
```

Expected: all selected tests pass; no write tool is registered.

- [ ] **Step 2: Run Java serialization and snapshot tests**

Run: `cd zhiyuan-server && mvn -q -Dtest=ConversationSnapshotServiceTest,ConversationContractSerializationTest,ConversationStatePatchServiceTest test`

Expected: exit code 0 and canonical mode fields present for both models.

- [ ] **Step 3: Run frontend tests and build**

Run: `cd zhiyuan-web && node --test src/utils/conversationEvents.test.mjs && npm run build:dev`

Expected: exit code 0; no Markdown-derived admission number is rendered.

- [ ] **Step 4: Run protocol/self-check and legacy regression evidence**

Run:

```bash
cd zhiyuan-agent
.venv/bin/python -m app.mcp_server.server --self-check
.venv/bin/python -m pytest tests/unit/test_state_sync.py -q
```

Expected: MCP reports eight read-only tools and zero writes; state sync remains green. The previously documented local `TestClient`/WebSocket lifespan hang must remain explicitly recorded rather than claimed as passed until CI/full service environment completes it.

- [ ] **Step 5: Record release evidence and commit**

The verification record must include the exact commands/results, both mode mappings, tier boundary results, zero hard-gate metrics, default legacy mode, and the known old WebSocket test environment limitation. Do not claim a production canary or full legacy WebSocket pass from offline tests.

Commit: `git add docs/superpowers/specs/2026-09-07-admission-evidence-design.md docs/superpowers/verification/2026-09-07-admission-evidence-verification.md && git commit -m "docs: record admission evidence verification"`

## Self-Review Checklist

- [ ] Every requirement in the approved design maps to at least one task: mode model (1/2/5), MCP envelope (3), Gateway fail-closed validation (4), frontend structured rendering (6), Shadow gates/runbook (7), and release verification (8).
- [ ] No task recomputes admission probability or changes Rank/Solver, Proposal/CAS, or write paths.
- [ ] `major` and `major_group` are canonicalized once and reused across all components; `majorGroup` appears only as an input compatibility alias.
- [ ] Group-level risk uses the group/unit rate; nested major rates cannot alter unit tier or unit counts.
- [ ] Missing, stale, cross-session, cross-thread, cross-tenant, and cross-mode Evidence all fail closed.
- [ ] Existing `legacy` behavior and the known local WebSocket regression limitation are preserved and honestly reported.
- [ ] No placeholders (`TODO`, `TBD`, “later”) remain in the plan.
