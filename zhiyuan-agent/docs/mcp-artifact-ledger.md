# MCP artifact issuance ledger

## Authority

Real `codex_readonly` / `codex_write` composition requires
`CODEX_APP_SERVER_BINDING_REGISTRY_PATH` before starting Codex. Gateway and stdio
MCP use its existing SQLite file, with a separate `codex_artifact_issuance` table.
The SDK builder also shares this file when given a binding registry. Direct test
tool runners must explicitly receive an artifact store to issue product results.

Only successful candidate/comparison tool results are registered. Trusted MCP
resolves the binding, reads the authoritative workspace version, obtains the tool
result and commits issuance before returning `artifacts`. Failure produces an
error envelope without product data or references; even cached references must
still exist in the ledger.

Gateway queries by the latest output's reference IDs and current tenant/session.
Assistant text, tool events, historical messages and self-reported scope fields
cannot register records. Missing, foreign or expired IDs are indistinguishable
to a scoped lookup. The existing one-repair-round path can call read-only tools
to replace a missing reference; it cannot manufacture an issuance record.
Storage failures are not repaired by trusting events or falling back to memory.

## Identity and retention

- Records contain scope, type, state version, tool name, parameter/result SHA256
  digests, original audit thread, issuance generation and issuance/expiry times.
  Full results, binding handles and service credentials are not stored here.
- The ID incorporates immutable content identity and a random issuance generation.
  Identical live results reuse the original record atomically, without extending
  retention. Content changes get a new ID. Reissuing an expired result also gets
  a new ID, so an old reference cannot become valid again after cleanup.
- Default TTL is 24 hours from initial issuance, not from the last access. Exact
  expiry is invalid. Workspace version checks can invalidate references earlier.
  There is no operational environment override in this batch.
- Each compact record is limited to 16 KiB; a scoped read accepts at most 128 IDs.
  JSON rejects non-finite values. Reads check the stored checksum, identity, scope,
  ID and timestamps; corruption is rejected rather than silently overwritten.
- A successful issuance transaction deletes at most 128 expired rows using the
  expiry index. There is no autonomous idle cleanup or strict disk-byte cap;
  SQLite freed pages may be reused without shrinking the file. Live records are
  not removed to satisfy a cache capacity limit.

The validator independently checks tenant/session, type, and reference-version
agreement. A higher tool version still requires a fresh authoritative Java
snapshot before widening the existing rebase interval. A different runtime
thread does not invalidate a same-scope, same-version unexpired artifact.

## Deployment and upgrade limits

The database is trusted local service state, not user-editable content. Place it
on a persistent volume accessible to both trusted processes, outside model-writable
workspace paths. File mode is enforced as `0600`; provision the parent directory
and service UID permissions appropriately. Filesystem access controls remain the
trust boundary: checksums are corruption detection, not a defense against an
attacker who controls this database. Do not commit this file, sidecars or backups.

Retaining the same volume supports Gateway/MCP process restarts, not lost-volume
recovery or cross-host sharing. Legacy process-memory records are not migrated
from historical model text. Their first post-upgrade reference requires a genuine
tool reissuance. Java `art_*` frozen-command/proposal storage is unchanged.

This remains a single-worker deployment. Distributed session fencing, safe idle
session reclamation and pending-approval lifecycle management are separate work.
No live service restart, database migration or deployment is performed by this patch.
