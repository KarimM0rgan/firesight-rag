# M5 pre-fix baseline — 42-question SQL set

**Measured before any fix.** This document and the report it cites exist
independently of the fixes that follow, so the post-fix comparison cannot be
made against a moving target.

Question set and references are frozen at the hashes in
[`eval/m5_frozen_set.json`](../eval/m5_frozen_set.json). Neither file may change
between this baseline and the re-run.

---

## Headline

| Metric | Result (Wilson 95% CI) |
|---|---|
| Execution accuracy | 42/42 = 100.0% [91.6, 100.0] |
| **Exact row match — PRIMARY** | **24/42 = 57.1% [42.2, 70.9]** |
| Answer containment — secondary, post-hoc | 34/42 = 81.0% [66.7, 90.0] |

This **replaces** the n=20 exact-match figure (9/20 = 45.0% [25.8, 65.8]) as the
project's primary SQL metric. The interval narrows from 40 points to 29.

Containment remains labelled post-hoc: it was defined after exact match returned
45% on the first scored run, as disclosed in the README.

Retry rate 0%. Latency p50 1,903 ms. Cost $0.6524 for the run.

## By category

`percentile_vs_rank` exists because s18 showed the model substituting a rank for
a percentile and picking the wrong tie rule. It was added to find out whether
that was a one-off.

| Category | n | Exact match (95% CI) | Failed |
|---|---:|---|---|
| aggregation | 6 | 6/6 = 100.0% [61.0, 100.0] | — |
| data_quality | 3 | 3/3 = 100.0% [43.9, 100.0] | — |
| registry | 3 | 3/3 = 100.0% [43.9, 100.0] | — |
| time_series | 3 | 3/3 = 100.0% [43.9, 100.0] | — |
| cohort | 6 | 5/6 = 83.3% [43.6, 97.0] | s17 |
| local_export | 2 | 1/2 = 50.0% [9.4, 90.5] | s39 |
| call_mix | 3 | 1/3 = 33.3% [6.2, 79.2] | s11, s12 |
| **percentile_vs_rank** | **4** | **1/4 = 25.0% [4.6, 69.9]** | **s21, s23, s24** |
| single_metric | 6 | 1/6 = 16.7% [3.0, 56.4] | s01, s03, s04, s29, s35 |
| peer_comparison | 2 | 0/2 = 0.0% [0.0, 65.8] | s09, s25 |
| ranking | 2 | 0/2 = 0.0% [0.0, 65.8] | s10, s18 |
| sensitivity | 1 | 0/1 = 0.0% [0.0, 79.3] | s19 |
| out_of_scope_for_nfirs | 1 | 0/1 = 0.0% [0.0, 79.3] | s20 |

**It was not a one-off.** Three of four percentile questions fail, and two of
those three (s18, s24) are the *same* error: getting the direction or the tie
rule of a percentile wrong. `single_metric` at 1/6 looks alarming but is almost
entirely the extra-column class below.

## The 18 failures, categorized

### A — Correct answer plus extra context columns (10)

`s01, s03, s04, s09, s11, s12, s21, s29, s35, s39`

All ten return the verified value and add supporting figures — asked for a P90,
the model returns the P90 *and* the sample size. All ten pass containment. This
is scorer strictness about incidental columns, not a reasoning failure.

Example — s01, "What was Sewanee's P90 response time in 2024?": expected
`(13.0)`, got `(13.0, 281.0)`. The 281 is `n_with_response_time`, which is
arguably information the reference should have asked for.

### B — Omitted a reference column (3)

`s17` dropped `n_incidents`; `s19` dropped the legacy scored count; `s20`
dropped the median while correctly returning the requested P90. The substantive
answer is right in each case, but a reference value is genuinely absent, so
these fail containment too.

### C — Genuine semantic error (4)

| # | Error |
|---|---|
| **s18** | returned a **rank** (122nd) where a **percentile** was asked for, and used `<=` instead of midpoint tie handling |
| **s24** | **inverted the percentile direction** — counted departments with *lower* compliance where compliance is better-is-higher, giving 91.5% instead of 8.5% |
| **s23** | used a different cohort: excluded Sewanee itself *and* dropped the `n_with_response_time > 10` pool filter, giving 25 tied departments instead of 23 |
| **s10** | no secondary sort key, so "the fastest five" is non-deterministic under ties |

s18 and s24 are one bug with two faces: **the model does not reliably know
which direction a percentile runs, or how ties are handled.** Both are the
project's headline output.

### D — Rounding precision (1)

`s25` returned `MEDIAN(...)` rounded to 2 decimals (41.35) where the reference
rounds to 1 (41.3). The underlying value is identical; the gap exceeds the
scorer's 0.01 tolerance. This is a reference/scorer artifact, not a model error.

---

## What this predicts about the fixes

- Fixing s18's class (schema description + few-shot examples stating the
  midpoint rule and the rank/percentile distinction) should move **s18, s24 and
  possibly s21** — three questions, not one.
- Fixing s10 adds a deterministic sort key; the question has limited
  discriminating power either way, because "the fastest five" is genuinely
  ambiguous under ties.
- Category A (10 questions) is a **measurement** question, not a model one.
  Whatever is decided there must be labelled as scorer leniency rather than
  folded in with the model fixes.
