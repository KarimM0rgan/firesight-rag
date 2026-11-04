# Reconciliation — rebuilt pipeline vs. prior CS444 output

Pinned by [`tests/test_reconciliation.py`](../tests/test_reconciliation.py).
Regenerate with `uv run python -m firesight.ingest.structured`, then
`uv run python scripts/check_zero_responses.py`.

---

## 1. Sewanee — matches, with one documented delta

| Figure | Prior work | Rebuilt | Status |
|---|---:|---:|---|
| 2024 incidents | 283 | 283 | match |
| Median response (min) | 6.0 | 6.0 | match |
| **P90 response (min)** | **13.0** | **13.0** | **match** |
| Fire / EMS / service / false-alarm counts | 24 / 45 / 28 / 169 | 24 / 45 / 28 / 169 | match |
| Scored incidents, same `> 0` rule | 272 | 271 | **−1, explained** |
| P95 response (min) | 18.9 | 18.0 | changed by filter |
| % within 8 min | 72.4% | 73.3% | changed by filter |

### The −1

`TN_26161_02262024_2400624_0`, incident type **611 "Dispatched & canceled en
route"**, recorded with a 1-minute alarm-to-arrival interval. The prior work
counted it as a 1-minute response. No unit reached a scene, so there is no
arrival to measure — it is excluded by `NON_RESPONSE_INCIDENT_TYPES`. The rule
was not tuned to reproduce 272.

### The arithmetic closes exactly

```
283  total 2024 incidents
 −1  cancelled en route (type 611)                  -> NON_RESPONSE_INCIDENT_TYPES
 −1  type 743, 724-minute interval (05:54 -> 17:58) -> outside the 0..90 window
−10  same-minute arrivals                           -> kept now, dropped by legacy rule
───
271  scored under the legacy `response_min > 0` rule
281  scored under the primary `0 <= response_min <= 90` rule
```

---

## 2. Effect of keeping zero-minute responses

Sewanee has 10 same-minute arrivals in 2024.

| | Legacy (`> 0`) | Primary (`>= 0`) | Δ |
|---|---:|---:|---:|
| Scored incidents | 271 | 281 | +10 |
| Median (min) | 6.0 | 6.0 | 0.0 |
| **P90 (min)** | **13.0** | **13.0** | **0.0** |
| P95 (min) | 18.9 | 18.0 | −0.9 |
| % within 8 min | 72.3% | 73.3% | +1.0pp |

**The headline metric does not move.** Dropping zeros did inflate the slow tail,
as predicted, but for Sewanee the effect lands on P95 and the compliance rate —
P90 is identical under both definitions. A null result on the headline is worth
stating plainly: it shows the filter choice was tested rather than assumed. Both
definitions ship in `metrics_department_year`, so every report carries the
sensitivity row.

---

## 3. Zero-artifact rule — withdrawn and replaced

### What was withdrawn

The original rule's second test — *"no department's zero rate exceeds 3× the
cohort median"* — was **unsatisfiable by construction**. With a median of 1.82%
the threshold fell to 5.45%, below the cohort's own P90 of 8.82%, so any
right-skewed distribution failed it regardless of the data. It was applied as
pre-committed and flagged rather than revised mid-run; it is now withdrawn.

### What replaced it

Evidence first, threshold second. Thresholds in
[`config.py`](../src/firesight/config.py).

**(1) Sentinel evidence.** NFIRS arrival times ending `0000` or `9999` are
placeholders, not clock readings. A department whose zeros are ≥50%
sentinel-backed, with ≥10 such records, is flagged on that evidence directly.

The materiality guard matters: **17 departments hold sentinel records, and 16 of
them hold only 1–4.** Three have a *100% sentinel share* on the strength of a
single corrupt row. Flagging a department over one bad record would be wrong;
without the guard this rule would condemn three otherwise-normal departments.

**(2) Plausibility floor.** Otherwise, flag a zero rate above **25%**. One call
in four arriving in the same clock minute as the alarm is not a credible
response profile at any department size.

### Does sentinel evidence explain the high-zero departments? Mostly no.

| Department | Scored | Zeros | Zero rate | Sentinel | Sentinel share |
|---|---:|---:|---:|---:|---:|
| KY/24116 | 379 | 231 | 60.9% | **0** | 0% |
| TN/90131 | 263 | 138 | 52.5% | **135** | **97.8%** |
| MS/34007 | 110 | 83 | 75.5% | **0** | 0% |

Only **TN/90131** is sentinel-driven, and conclusively so. The two the brief
asked about specifically — KY/24116 and MS/34007 — carry **no sentinel records
at all**, so only the plausibility floor catches them. The sentinel path adds
nothing net on this data: TN/90131 exceeds 25% anyway. It is kept because it
generalizes to a future year where a sentinel-heavy department sits below the
floor.

### What the live rule flags

**20 departments**, holding 760 of 4,856 zeros. Of those 20, 8 fall below the
30-incident testability bar and only **14 reach the ranking pool** (which
requires >10 scored response times), so the pool drops 782 → 768.

The 8 untestable ones are noise cases — KY/50242 has a single scored incident
which is a zero, giving a 100% rate. Six of the eight have ≤3 scored incidents
and can never enter the ranking pool, so flagging them is harmless. They are
reported as `testable = false` rather than silently dropped.

---

## 4. Sensitivity: Sewanee's rank under three pool definitions

All percentiles use midpoint tie-handling — 18 departments share Sewanee's P90
of 13.0 min, and strict `<` would flatter Sewanee by placing it at the top of
its own tie group. Lower percentile = better rank.

| Pool | n | P90 regional | P90 TN | Compliance regional | Compliance TN |
|---|---:|---:|---:|---:|---:|
| **A** no zero-artifact exclusion | 782 | 14.6% | 10.4% | 9.0% | 6.5% |
| **B** new rule (20 flagged) | 768 | 14.4% | **10.5%** | 8.5% | 6.5% |
| **C** withdrawn 3× median (134 flagged) | 648 | 13.0% | 9.9% | 7.0% | 6.2% |
| **Published headline (worst-of)** | — | **14.6%** | **10.5%** | **9.0%** | **6.5%** |

**The published figures are the worst value across all three pools**, not any
single pool's. The bias runs toward the client — every department dropped for a
high zero rate is a *fast-looking* department leaving the cohort, which inflates
Sewanee's rank. The monotonicity is visible above: more exclusion, better rank.
Pool C, the withdrawn rule, flattered Sewanee most (13.0% vs 14.6%).

So: **Sewanee's P90 is top 14.6% regionally and top 10.5% in Tennessee; its
8-minute compliance rate is top 9.0% regionally and top 6.5% in Tennessee.**
Peer median P90 is 18.0 min against Sewanee's 13.0 under every pool definition.

Any ranking query must filter `metrics_department_year.in_benchmark_pool`
(= pool B). Pool A is reproducible by dropping that predicate.

---

## 5. Zero-count reconciliation — 5,229 / 4,856 / 4,757

Three figures were in play across M0 and M1. They differ by filter, not by error.

| Figure | Value | Definition |
|---|---:|---|
| M0 profile (`rt_zero`) | **5,229** | every peer incident row with `response_min = 0`, including non-response incident types |
| — of which non-response | −373 | types 57/571/61/611, excluded from M1 scoring |
| M1 Q3 (unfiltered) | **4,856** | `response_min = 0 AND NOT is_non_response`, all departments |
| — in departments with <30 scored incidents | −99 | excluded by Q1's `HAVING count(*) >= 30` testability gate |
| M1 Q1 (testable cohort) | **4,757** | the 647 departments with ≥30 scored incidents |

`5,229 − 373 = 4,856`, and `4,856 − 99 = 4,757`. Both deltas close exactly.

---

## 6. Cohort-count reconciliation — 779 → 648

M0 reported 779 benchmarkable departments; M1 reported 648 after dropping 134,
which left 3 rows unaccounted. Traced:

| Step | Count | Cause |
|---|---:|---|
| M0 profiler rule, reproduced exactly | **779** | `response_min > 0 AND <= 90`, `>10` per department, **non-response types included** |
| Exclude non-response incident types | **777** | −2 departments fall below the >10 bar once cancelled-en-route and station-cover calls stop counting |
| Keep zero-minute responses | **782** | +5 departments cross the >10 bar once same-minute arrivals count |
| Drop zero-artifact departments (withdrawn rule) | **648** | −134 |
| Drop zero-artifact departments (new rule) | **768** | −14 in-pool of 20 flagged |

The "3 unaccounted" was a net figure hiding two offsetting moves: **−2 then +5.**
The five departments that crossed the threshold only because zeros are kept are
GA/01004, KY/63770, AR/57001, GA/13006 and TN/88121 — each sitting at 11–12
scored incidents against 5–10 under the legacy rule.

---

## 7. Zero-minute building fires — evidence the zeros are real

95 incidents coded **111 "Building fires"** have a same-minute arrival. If these
clustered in the flagged departments they would be artifacts; if spread, they are
most likely station-adjacent or crew-witnessed fires.

| Measure | Value |
|---|---|
| Departments holding them | **57** |
| Distribution | 41 depts hold 1, 8 hold 2, 6 hold 3; two outliers hold 9 and 11 |
| Sentinel-backed | **2 of 95** |
| In departments above the 25% floor | 15 |
| **In otherwise-normal departments** | **80 of 95 (84%)** |

**Spread, not concentrated.** 84% sit in departments with an unremarkable zero
rate, and almost none carry a sentinel timestamp. A volunteer department whose
station sits beside the building that caught fire genuinely does arrive in the
alarm minute.

This is direct evidence **for keeping zeros** and **against** a blanket
department-level exclusion: the mechanism producing most zeros looks real, and
the artifact signature is confined to a small, identifiable tail. It also
supports keeping the floor at 25% rather than anything tighter — a lower
threshold would start discarding genuine station-adjacent response.

### Not implemented — a proposal

Isolated sentinel records would be better handled at **row level** than by
flagging departments. A `0000`/`9999` arrival time is a corrupt timestamp, so it
belongs excluded like a NULL, wherever it appears. For TN/90131 that would
remove its 135 corrupt rows and leave 128 valid incidents in the cohort, instead
of discarding the department whole — its remaining zero rate would be 2.3%.

Not adopted, because the brief specified department-level flagging. Raised for a
decision rather than actioned.

---

## 8. Peer figures — do not reconcile, and should not

The prior peer numbers were computed with a state-blind FDID join
(`PROFILE.md` §5 ①) and are superseded.

| Figure | Prior work | Corrected |
|---|---:|---:|
| Peer departments identified | — | 1,568 |
| Peer departments reporting in 2024 | 1,233 | 936 |
| **Benchmarkable cohort** | **1,138** | **768** |
| TN departments in cohort | 255 | 237 |

Also fixed while reconciling: NC/00713 reports `vol_ff` as both 0 and 38 across
duplicate `fdheader` rows, and any magnitude-based tie-break moved departments in
or out of the cohort (the peer count swung 1,568 → 1,567 → 1,563 across
attempts). Eligibility now comes from whether **any** source row qualifies,
decoupled from the displayed attributes, with `has_conflicting_staffing_rows`
exposing the ambiguity.

---

## 9. Local export exclusions

Three independently named rules replace the prior work's undocumented 15-record
exclusion, which was not reverse-engineered.

| Rule | Rows caught | Definition |
|---|---:|---|
| `TEST_RECORD_FLAGS` | 13 | `natureOfCall` is a test page or training entry |
| `NON_FINALIZED_RECORDS` | 1 | `reviewStatus = 'archived'` |
| `LEGACY_TEST_EXCLUSION` | — | inherited rule, reconciliation only, never reported |

`draft` is deliberately **not** an exclusion: 183 of 197 records are drafts,
reflecting workflow adoption rather than data quality. Excluding them would leave
14 records.

After exclusions: 156 scored turnout intervals, median 1.0 min, P90 4.0 min, over
2025-09-19 → 2026-03-19. The prior notebook reported 182 records and n=130; the
counts differ because the rules differ, which is the intended outcome.
