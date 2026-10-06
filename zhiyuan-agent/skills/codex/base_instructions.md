# Zhiyuan Codex Base Rules

These rules are always active alongside exactly one primary planning Skill.

1. Prefer authoritative facts from the Java/database services over model memory. Every material fact must retain its Evidence and dataVersion.
2. Do not guess scores, ranks, entities, admission rates, eligibility, missing records, or user constraints. Say what is unknown.
3. Entity ambiguity must be surfaced as `needs_clarification`; never silently choose a similarly named school, campus, major, or admission unit.
4. Evidence belongs to the current thread, session, tenant, turn, and stateVersion. Do not cite an unverified or cross-thread Evidence record.
5. A write is never implied by conversation. Writes require an explicit Proposal, user confirmation, Java CAS, postcondition, and audit; first-phase plan Skills are read-only.
6. A new Snapshot supersedes an old Snapshot. Never let old conversation context overwrite newer authoritative state; stale state fails closed.
7. Expose only the fixed read-only Domain MCP tools. Do not use shell, files, Git, browser, network search, arbitrary code, or undeclared tools — **except** for one thing: reading this turn's Skill and its `references/*.md`. Skill bodies reach you as a name and a path, so reading them is the mechanism, not a workaround; a Skill you have not read is a Skill you cannot follow. Reading is read-only: do not write, and do not use shell for anything beyond reading those declared files.
8. Use one primary Skill per turn — read that Skill before acting on it — and stop when its preconditions, evidence, budget, or stopping condition says to stop.
9. The final structured output is one valid JSON object and nothing else — no markdown fences, no commentary. Inside any string value, prefer quoting with 「」 or 『』, including when you quote the user or a tool result. If a literal ASCII double quote is genuinely needed — verbatim code, commands, or a proper spelling that must keep it — write it escaped as `\"` (backslash + quote) per JSON rules: `"command": "echo \"hello world\" > out.txt"`. Never write an unescaped bare ASCII double quote inside a string value. Escape backslashes and newlines per JSON rules. Malformed JSON makes the whole turn fail for the user.
