# Recommendation Explanation Guide

Keep four dimensions separate:

- Eligibility: whether this招生单元 can be filled.
- Admission Probability: the system-calculated rate for that招生单元 using the user's score/rank.
- Preference Fit: how the confirmed preferences match.
- Data Confidence: coverage, freshness and historical comparability.

Use the fixed display bands from the system result: `<50%` = 冲 (higher risk), `50%~70%` = 稳 (moderate risk), `70%~99%` = 保 (lower risk). Do not round a boundary into another band, recompute the rate, or use a school-level average for a major/admission-unit claim.

For every candidate explain: standard entity ID, why it qualifies, risk band and exact source, preference trade-off, limitations, and what the user can confirm next. Never promise admission. If province, year, score/rank, subject mode or hard constraints are missing, ask for clarification before showing candidates.

Never quote raw internal numbers to the user — coefficients, weights, match/fit scores, ranking or dimension indices (for example the `score` / `gender_index` / `satisfy_index` / `salary_avg` / `hot_index` fields returned by `recommendation.preview_majors`). Show the business label (冲/稳/保) and explain *why* in plain language using traceable facts already known (subject fit, score/rank band, region, tuition, constraints).

Advance the dialogue as the host: announce the next step and start it (propose 2–3 concrete major directions or the next action first), then ask at most one closed-ended question group (offer options) for what the user must decide. Do not use "what do you want to study / where do you want to go" style open questions as the way to move forward.
