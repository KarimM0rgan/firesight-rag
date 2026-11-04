# Reconciliation — rebuilt pipeline vs. prior CS444 output

Pinned by [`tests/test_reconciliation.py`](../tests/test_reconciliation.py) (12 tests).
Regenerate the inputs with `uv run python -m firesight.ingest.structured`.

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
arrival to measure — it is excluded by `NON_RESPONSE_INCIDENT_TYPES`.

This is the exclusion rule working as designed, not metric drift. Per the M1
instruction, the rule was not tuned to reproduce 272.

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

The predicted direction holds — dropping zeros did inflate the slow tail — but
for Sewanee the effect lands on P95 and the compliance rate, **not on P90**.
The headline metric is unchanged either way. Both definitions ship in
`metrics_department_year`, so every report can carry the sensitivity row.

---

## 3. Peer figures — do not reconcile, and should not

The prior peer numbers were computed with a state-blind FDID join
(`PROFILE.md` §5 ①). They are superseded.

| Figure | Prior work | Corrected | Why it moved |
|---|---:|---:|---|
| Peer departments identified | — | 1,568 | correct `(state, fdid)` key |
| Peer departments reporting in 2024 | 1,233 | 936 | contamination removed |
| **Benchmarkable cohort** (>10 scored) | **1,138** | **648** | contamination removed, then 134 zero-artifact departments excluded |
| TN departments in cohort | 255 | 202 | same |

### Corrected rankings

Percentiles use midpoint tie-handling — 18 departments share Sewanee's P90 of
13.0 min, and strict `<` would have flattered Sewanee by placing it at the top
of its own tie group.

| Ranking | Published | Corrected | Direction |
|---|---|---|---|
| P90, regional | top 29% | **top 13.0%** | better |
| P90, Tennessee | top 13% | **top 9.9%** | better |
| Compliance (% ≤ 8 min), regional | top 22% | **top 7.0%** | better |
| Compliance, Tennessee | top 9% | **top 6.2%** | better |

Sewanee ranks **better** than previously published once the contaminating
departments are removed, against a cohort roughly half the claimed size. Peer
median P90 is 18.0 min against Sewanee's 13.0.

Any ranking query must filter `metrics_department_year.in_benchmark_pool`.

---

## 4. Zero-response distribution check

Run: [`scripts/check_zero_responses.py`](../scripts/check_zero_responses.py).
The decision rule was fixed before the output was seen.

| Input | Value |
|---|---|
| Testable departments (≥30 scored incidents) | 647 |
| Median zero rate | 1.82% |
| P90 zero rate | 8.82% |
| Max zero rate | 75.45% |
| Total zeros | 4,757 |
| Top-10 share of all zeros | 21.6% |
| Departments above 3× median (5.45%) | 134 |
| Zeros held by those 134 | 2,994 |

**Verdict: CONCENTRATED.** Test (a) passed (21.6% < 25%); test (b) failed (134
departments exceed 3× median, not 0). Pre-committed consequence applied: those
134 departments are flagged `is_zero_artifact` and dropped from
`in_benchmark_pool`. Zeros are kept everywhere else. Sewanee is not among them
(zero rate 3.6%).

Incident-type composition (query 4) showed zeros spread across ordinary
response types — medical assist 13.0%, public service 12.1%, EMS 8.3%, and 95
building fires — **not** concentrated in non-response types. Cancelled-en-route
never appears, having already been excluded at ingest. So no incident-type
filter change was made and the response-time filter stays clean, as instructed.

> **One caveat on the rule, raised after the fact and not acted on.** Test (b)
> — "no department's zero rate exceeds 3× the cohort median" — cannot be
> satisfied by any right-skewed distribution: with a median of 1.82% the
> threshold is 5.45%, below the cohort's own P90 of 8.82%, so >10% of
> departments exceed it by construction. The verdict was therefore determined
> before the data was seen. The evidence actually points toward *diffuse with a
> heavy head*: test (a) passed comfortably and query 4 found no artifact
> signature. The rule was applied exactly as pre-committed; flagging this for a
> future revision rather than revising it now.

Departments with fewer than 30 scored incidents (287 of the 934 with any
scored incident) cannot be tested and are left in the pool, flagged
`testable = false`.

---

## 5. Local export exclusions

Three independently named rules replace the prior work's undocumented
15-record exclusion, which was not reverse-engineered.

| Rule | Rows caught | Definition |
|---|---:|---|
| `TEST_RECORD_FLAGS` | 13 | `natureOfCall` is a test page or training entry |
| `NON_FINALIZED_RECORDS` | 1 | `reviewStatus = 'archived'` |
| `LEGACY_TEST_EXCLUSION` | — | inherited rule, reconciliation only, never reported |

`draft` is deliberately **not** an exclusion: 183 of 197 records are drafts,
which reflects workflow adoption rather than data quality. Excluding them would
leave 14 records.

After exclusions: 156 scored turnout intervals, median 1.0 min, P90 4.0 min,
over 2025-09-19 → 2026-03-19. The prior notebook reported 182 records and
n=130; the counts differ because the rules differ, which is the intended
outcome.
