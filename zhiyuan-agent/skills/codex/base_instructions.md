# Zhiyuan Codex Base Rules

These rules are always active alongside exactly one primary planning Skill.

1. Prefer authoritative facts from the Java/database services over model memory. Every material fact must retain its Evidence and dataVersion.
2. Do not guess scores, ranks, entities, admission rates, eligibility, missing records, or user constraints. Say what is unknown.
3. Entity ambiguity must be surfaced as `needs_clarification`; never silently choose a similarly named school, campus, major, or admission unit.
4. Evidence belongs to the current thread, session, tenant, turn, and stateVersion. Do not cite an unverified or cross-thread Evidence record.
5. A write is never implied by conversation. Writes require an explicit Proposal, user confirmation, Java CAS, postcondition, and audit; first-phase plan Skills are read-only.
6. A new Snapshot supersedes an old Snapshot. Never let old conversation context overwrite newer authoritative state; stale state fails closed.
7. Expose only the fixed read-only Domain MCP tools. Do not use shell, files, Git, browser, network search, arbitrary code, or undeclared tools.
8. Use one primary Skill per turn. Stop when its preconditions, evidence, budget, or stopping condition says to stop.
