# Disposable gateway turn cache

`GatewayService` retains completed turn results in a process-local FIFO cache,
shared across its tenants and sessions. The cache key remains
`(SessionKey(tenant_id, session_id), turn_id)`. Each entry owns its response,
input-content digest, and expiration together; eviction cannot leave a separate
digest behind.

## Configuration and retry semantics

Optional keyword-only constructor parameters:

| Parameter | Default | Constraint |
| --- | --- | --- |
| `turn_cache_max_entries` | `1024` | Positive integer, not a boolean |
| `turn_cache_ttl_seconds` | `3600.0` | Positive, finite seconds |
| `turn_cache_clock` | `time.monotonic` | Monotonic clock; injectable for offline tests |

Existing composition uses these defaults. This change does not add environment
configuration or require changes to callers.

TTL starts when a turn completes, not when it starts. At the exact expiration
time an entry is expired. Cache hits and input conflicts do not refresh its TTL
or FIFO position. Expired entries are pruned before lookup and after an uncached
turn completes; there is no timer or background task. An idle instance may retain
expired entries until its next turn, but the entry-count cap still applies.

Within retention, an identical retry returns the original response object without
repeating the client call or message persistence. Changed content for the same
key still returns `turn_id_input_conflict`, including the original snapshot
version. After expiry or capacity eviction, the key is a cache miss: either the
same or changed content can execute again. This is a disposable optimization,
not durable idempotency or an authorization/approval ledger. It bounds entry
count, not response bytes or in-flight work.

## Deliberately deferred

- Session locks, thread bindings, snapshots, working sets, user-turn watermarks,
  and durable artifact validation records are not evicted by this cache.
  In particular, removing a lock with active owners or waiters could split
  serialization, and dropping artifact records could break cross-turn validation
  or approval. Their process-local session ownership can still grow unbounded.
- Session lifecycle reclamation needs an ownership design that accounts for
  active turns, queued requests, continuations, and pending approvals. It is not
  implemented here.
- MCP artifact issuance now uses the shared local SQLite ledger described in
  `mcp-artifact-ledger.md`. The process-local artifact authority has been removed.
  This prerequisite alone does not implement session lifecycle reclamation.
- Multiworker routing, shared idempotency, and distributed session ownership or
  serialization remain unresolved. Neither this cache nor the existing
  `asyncio.Lock` coordinates workers. Restart still loses cached responses;
  artifact validation survives only while the configured local volume is retained.

The focused tests use fake legacy clients, message stores, and a manual monotonic
clock. They do not start a runtime, call an LLM, or contact live services.
