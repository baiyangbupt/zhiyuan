# Evidence Policy

- `authoritative`: Java/database records or the system admission-rate engine.
- `computed`: deterministic backend calculations with algorithm and data versions.
- `planner_experience`: explanation or questioning guidance; never a substitute for an admission fact.

Every important fact shown to a user carries an `evidenceId`, source level, dataVersion, scope (province, year, batch, subject mode and admission unit) and limitations.

Evidence is scoped to the current tenant, session, thread and turn. A missing, stale, cross-thread or unverifiable Evidence record is a hard failure. Return a structured recoverable error instead of silently dropping the citation.

Historical rows must preserve `comparability`, `coverage`, `missingFields` and fallback scope. Distinguish zero, not recruited, not published, not collected and not applicable. Never turn missing admission data into zero values.

The admission-rate engine remains authoritative for招生单元录取率. The planner may explain its output but must not recalculate or change risk boundaries.
