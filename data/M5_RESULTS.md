# M5 results — pre-fix vs post-fix, same 42 questions

Question set and references **byte-identical** across both runs, verified
against [`eval/m5_frozen_set.json`](../eval/m5_frozen_set.json). Baseline is
[`M5_BASELINE.md`](M5_BASELINE.md), committed before any fix.

## Headline

| Metric | Pre-fix | Post-fix |
|---|---|---|
| Execution accuracy | 42/42 = 100.0% [91.6, 100.0] | 42/42 = 100.0% [91.6, 100.0] |
| **Exact row match — PRIMARY** | 24/42 = 57.1% [42.2, 70.9] | **25/42 = 59.5% [44.5, 73.0]** |
| Containment — secondary, post-hoc | 34/42 = 81.0% [66.7, 90.0] | 36/42 = 85.7% [72.2, 93.3] |

**The primary metric moved by one question and the change is not significant.**
Two questions fixed, one regressed: paired sign test p = 1.000. The intervals
overlap almost entirely. Reading 57.1% → 59.5% as an improvement is reading
noise.

## Which questions changed state

| # | Pre | Post | What happened |
|---|---|---|---|
| s10 | fail | **PASS** | deterministic sort key applied |
| s23 | fail | **PASS** | full cohort filter applied |
| **s02** | PASS | **fail** | **regression — see below** |

Containment additionally gained s24 and lost s11.

## The fix worked where the primary metric cannot see it

**s24 — the direction bug is fixed.** This is the substantive result of M5, and
exact match does not show it:

| | Returned | Correct? |
|---|---|---|
| Pre-fix | `(73.3, 768.0, 91.5)` | **no** — percentile inverted |
| Post-fix | `(73.3, 768.0, 8.5)` | **yes** — 8.5 is correct |

The model echoed the rule back in a comment: *"Compliance: HIGHER is better, so
better-than-Sewanee is `>`; ties contribute half."* It still fails exact match
because of two extra context columns — a Category A artifact sitting on top of a
genuine semantic repair.

Reported separately rather than netted out, as required: **1 question gained
exact match from the percentile work (s23), 1 gained correct semantics without
gaining exact match (s24), and 1 got worse (s18, below).**

## The fix backfired on s18, the question it was written for

s18 still fails, and the reason is a wording defect I introduced. The new rule
said to give a percentile *"unless it explicitly asks for a position or a
count."* The model read *"how does Sewanee's P90 rank against its peers"* as an
explicit request for a position, and said so:

> `/* "Rank" is explicitly requested (an ordinal position, not a percentile). */`

Pre-fix it returned `(13.0, 122.0, 768.0)` — a rank with `<=` ties. Post-fix it
returns `(13.0, 100.0, 23.0, 768.0)` — a rank, a tie count and a pool size, with
**no percentile at all**. The tie handling improved (it now surfaces the
23-department tie group explicitly) while the rank-vs-percentile choice became
*more* confidently wrong.

**Not re-fixed.** Changing the wording again after seeing this output is another
post-hoc edit, and the budget for a third scored run is gone. Recorded for the
next milestone: the rule needs to say that "rank" and "compare" in a question
about a department's standing both mean *percentile*, and that a position should
be given only when a question asks how many departments are faster — which is
what s22 asks, and which the model already answers correctly.

## s02 — a real regression, caused by the fix

| | SQL | Result |
|---|---|---|
| Pre | `SELECT n_incidents` | `(283.0)` — exact match |
| Post | `SELECT n_incidents, n_response_incidents` | `(283.0, 282.0)` — fails |

Richer schema guidance made the model more verbose, and the extra column cost an
exact match on a question it had previously answered perfectly. **This is the
cost of the fix**, and it is the same Category A mechanism behind 10 of the 18
baseline failures: nothing is wrong with the answer.

## percentile_vs_rank category

| | Exact match | Failed |
|---|---|---|
| Pre-fix | 1/4 = 25.0% [4.6, 69.9] | s21, s23, s24 |
| Post-fix | **2/4 = 50.0% [15.0, 85.0]** | s21, s24 |

Both remaining failures return the **correct value** with extra columns — s21
returns `(13.0, 768.0, 14.4)` against an expected `(14.4)`, and s24 returns
`(73.3, 768.0, 8.5)` against `(8.5)`. On semantics the category is 4/4 post-fix;
on exact match it is 2/4. That gap is the measurement, not the model.

## Honest summary

- **Semantics improved**: the percentile direction bug is gone (s24), cohort
  filtering is applied (s23), ordering is deterministic (s10).
- **The primary metric barely moved** (+1 question, p = 1.000), because most of
  the improvement lands on questions whose references ask for different columns
  than the model returns.
- **One fix backfired** (s18) and **one regression was introduced** (s02).
- Containment, the metric that tolerates incidental columns, moved further
  (81.0% → 85.7%) and is arguably the better view of this change — which is
  exactly why it stays labelled secondary and post-hoc rather than being
  promoted now that it tells a nicer story.

Spend: $0.6524 pre-fix + $0.8760 post-fix.
