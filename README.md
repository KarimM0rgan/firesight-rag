# FireSight RAG

Hybrid retrieval over real fire-service data: natural-language questions are routed
to **text-to-SQL** over 33.3M NFIRS incident records, to **vector search** over a
reference-document corpus, or to both — and answered with citations.

> **Status: M1–M4 measured.** Retrieval figures are at n=50 with intervals;
> generation and routing figures are at n=42/50/46. Remaining provisional
> items are named inline. Five characterized SQL failures are deliberately
> **unfixed** so that their repair can be measured against a set written before
> the fix. Milestones are in [FIRESIGHT_RAG_SPEC.md](FIRESIGHT_RAG_SPEC.md);
> this README is rewritten at M6.
>
> **What M4 changed about earlier claims:** the reranker's benefit shrank by
> 2–4× and is no longer statistically established; `bge-base` lost to
> `bge-small` on every arm; and the refusal floor's clean separation turned out
> to be a small-sample artifact that a fivefold larger question set destroyed.
> All three were cases where more data contradicted a smaller measurement.

## Finding: the system reproduced this project's own tie-handling error

The clearest demonstration of why the evaluation harness exists.

Percentile ranking is this project's headline output. Asked *"How does Sewanee's
P90 response time rank against its peer departments?"*, the model wrote:

```sql
COUNT(*) FROM pool WHERE response_p90_min <= (SELECT response_p90_min FROM pool WHERE is_sewanee)
```

**`<=`, not midpoint.** 23 peer departments share Sewanee's 13.0-minute P90, so
the tie rule is load-bearing:

| Tie rule | Percentile | Error vs specified |
|---|---:|---:|
| strict `<` (optimistic) | 12.9% | −1.5 pts |
| **midpoint (specified)** | **14.4%** | — |
| `<=` (model's choice, pessimistic) | 15.9% | +1.5 pts |

**3.0 percentage points of spread on the headline figure**, from a single
operator. And the model made the same class of mistake this project made
earlier, in the opposite direction: the first peer rankings used strict `<`,
which placed Sewanee at the top of its own tie group and flattered it. The
methodology document specifies midpoint handling precisely because this choice
is not free — and the model silently picked an end of it.

It also answered a **different question**: it returned a *rank* (122nd of 768)
where the reference returns a *percentile*. 122/768 = 15.9%, close enough to
14.4% that neither a reader nor a cursory reviewer would catch the substitution.

A number that is wrong by 3 points and looks completely plausible is exactly what
an eval set is for. Nothing here was caught by reading the output; it was caught
by comparing against a verified reference.

**Deliberately not fixed.** The obvious fix is to state the tie rule in the
schema prompt, but that is a change informed by having seen it scored. It lands
after M4 as its own milestone, measured against a set written before the fix.

## Measured results

Every figure carries a **Wilson 95% confidence interval**, emitted by the
harness rather than added by hand. These samples are 8–20 observations; a bare
point estimate at that size invites reading `8/8` as a rate, which it is not.

| Metric | n | Result (95% CI) |
|---|---:|---|
| **SQL execution accuracy** | 20 | 20/20 = 100.0% [83.9, 100.0] |
| **SQL result accuracy — exact row match (PRIMARY)** | 20 | 9/20 = 45.0% [25.8, 65.8] |
| SQL answer containment (secondary) | 20 | 15/20 = 75.0% [53.1, 88.8] |
| **Answer faithfulness** | 13 | 13/13 = 100.0% [77.2, 100.0] |
| Citation rate | 13 | 13/13 = 100.0% [77.2, 100.0] |
| Citation validity (page-insensitive) | 13 | 13/13 = 100.0% [77.2, 100.0] |
| **Router accuracy** | 46 | 44/46 = 95.7% [85.5, 98.8] |
| Router macro F1 | 46 | 0.956 |
| **Adversarial excluded-material routing** | 8 | 8/8 = 100.0% [67.6, 100.0] |
| Adversarial exclusion-reason accuracy | 8 | 8/8 = 100.0% [67.6, 100.0] |
| Router schema-violation rate | 46 | 0/46 = 0.0% [0.0, 7.7] |

Retrieval metrics (local embeddings, no API key) are further down.

### What the small samples do and do not support

**`8/8` on adversarial routing is not "100%".** Its interval spans
**[67.6%, 100.0%]** — 32 percentage points. The correct reading: *the design
assumption that a router can be told the excluded-material distinction, where
embedding similarity provably cannot make it, is supported by every case tested,
and the sample is far too small to claim a rate.* Eight consecutive successes
would arise by chance roughly 1 in 256 times if the true rate were 50%, so this
is real evidence — it is just not a measured rate.

The same applies to **faithfulness at n=13**: 13/13 reads as 100% but the
interval bottoms out at **77.2%**. And to **SQL exact-match at 45%**, whose
interval [25.8, 65.8] is wide enough that it cannot be distinguished from 60%
or from 30%.

Only two figures here have intervals narrow enough to be worth comparing
against anything: router accuracy (±7 points) and SQL execution accuracy.

### Known labeling ambiguity, frozen as written

Two of the router's 46 labels are arguably wrong, and **both stay as written**:

- **r12** *"How many of our 2024 incidents are missing an arrival time?"* →
  labelled `structured`, routed `out_of_scope`. The question is answerable (the
  SQL set answers it), so this looks like a model error.
- **r27** *"Our P90 response time is 13 minutes; which NFPA standard governs
  response time for a volunteer department like ours?"* → labelled `hybrid`,
  routed `unstructured`. The question **supplies** the P90, so no database query
  is needed and the model's call may be better than the label.

Revising a label after seeing model output is the same post-hoc problem as
inventing a metric after seeing a result. **95.7% stands under the labels as
written.** If either label is wrong, the true accuracy is higher, not lower —
which is the direction that makes freezing them safe.

The general rule adopted from M4 onward: all labels are written and verified
before any model run, and a label discovered to be wrong is recorded as a
finding rather than corrected into a better number.

### Metric pre-commitment, and a post-hoc disclosure

**Disclosure.** Answer containment was **defined after** exact row matching
returned 45%. Seeing that figure prompted the question of whether the scorer was
too strict — it was, in a specific way: a query asked for a P90 that returned the
P90 *and* the sample size was marked wrong. Containment measures whether the
verified answer is present in the result. Both numbers are reported, and the
order in which they were invented is stated here because a metric introduced
after seeing a result is exactly the kind of thing a reader should be able to
discount.

**Pre-commitment for M4, recorded before that run.** **Exact row match is the
primary metric; answer containment is secondary.** Rationale: containment can be
satisfied by a query that returns a wide result set containing the answer
incidentally, so it has a failure mode that flatters the system. Exact match has
no such failure mode — it is merely strict. Where the two disagree, the headline
figure is exact match, and the gap between them is reported as a measure of how
often the model answers correctly in an unexpected shape.

### The five genuine SQL failures, characterized and NOT yet fixed

Characterized before anything is tuned. Fixing failures already seen scored is
how a 45% becomes an unreproducible 70%, so these are described and left alone;
any fix lands with a fresh measurement.

Of 20 questions, 9 matched exactly, 6 more were correct in an unexpected shape
(counted by containment), and **5 are genuine disagreements**:

| # | Question | Category |
|---|---|---|
| s10 | fastest five TN peers | **non-deterministic tie ordering** |
| s18 | how does our P90 rank | **rank vs percentile, with a tie-handling error** |
| s17 | which peer group | column-set difference |
| s19 | P90 change if zeros excluded | column-set difference (omission) |
| s20 | turnout time P90 | column-set difference (omission) |

**s10 — tie ordering.** The model wrote
`ORDER BY response_p90_min ASC` with no secondary key. Several TN departments
share a whole-minute P90, so which five come back is arbitrary and varies run to
run. The reference adds `, fd_name ASC`. Not a reasoning error: the query answers
the question, and "the fastest five" is genuinely ambiguous under ties. It does
mean this question cannot discriminate between a good and a bad model.

**s17, s19, s20 — column-set differences.** Each returns the right answer with a
different supporting column: s17 substituted `response_p90_min` for
`n_incidents`; s19 and s20 omitted one of the reference's five columns (the
legacy scored count, and the median alongside the requested P90). All three got
the substantive answer right. They fail exact match, and s17/s19/s20 also fail
containment because a reference value is genuinely absent from the result.

#### s18 in detail — the one that matters most

Percentile ranking is this project's core output, so a model confusion here
matters more than one-fifth of a 20-question set suggests.

Asked *"How does Sewanee's P90 response time rank against its peer
departments?"*, the model produced:

```sql
SELECT (SELECT response_p90_min FROM pool WHERE is_sewanee) AS sewanee_p90_min,
       (SELECT COUNT(*) FROM pool
          WHERE response_p90_min <= (SELECT response_p90_min FROM pool WHERE is_sewanee))
         AS rank_from_fastest,
       COUNT(*) AS peer_pool_size
FROM pool
```

Returned `(13.0, 122, 768)` against the reference's `(13.0, 768, 14.4)`.

Two distinct problems, and the dangerous part is that the answer looks right:

1. **It answered a different question.** It returned a *rank* (122nd) where the
   reference returns a *percentile* (14.4%). Both are legitimate readings of
   "rank", and 122/768 = 15.9% is close enough to 14.4% that neither a reader nor
   a cursory reviewer would notice the substitution.
2. **The tie handling is wrong, in the pessimistic direction.** `<=` counts every
   department tied with Sewanee as at-or-faster. **23 departments share Sewanee's
   13.0-minute P90**, so the choice between `<`, midpoint and `<=` moves the
   answer by 23 places. The methodology document specifies midpoint tie handling
   precisely because this choice is load-bearing — and the model silently picked
   one end of it:

   | Tie rule | Departments counted | Percentile |
   |---|---:|---:|
   | strict `<` (optimistic) | 99 | 12.9% |
   | **midpoint (specified)** | — | **14.4%** |
   | `<=` (model's choice, pessimistic) | 122 | 15.9% |

This is the project's own earlier mistake, reproduced by the model. The first
peer rankings used strict `<`, which placed Sewanee at the top of its own tie
group and flattered it by 1.5 points; the model used `<=`, which places it at the
bottom and penalises it by 1.5 points. The full spread across tie rules is 3.0
percentage points on the project's headline figure.

**Not fixed.** The fix is plainly to state the tie rule and the rank-vs-percentile
distinction in the schema prompt, but that is a change informed by having seen it
scored. It goes into M4 with a fresh measurement, and the before/after will be
reported.

### The truncation bug: a reasoning block will eat the whole token budget

The most useful finding of this round was not a metric. It was that **a model
which emits a reasoning block before its text will consume the entire
`max_tokens` budget producing reasoning, return zero text blocks, and look
exactly like a malformed response.**

The router was calling the model with `max_tokens=300` — generous for a
four-field JSON object. The symptom was a **21.7% schema-violation rate** and 5
of 46 questions unroutable, with violation messages like
`no JSON object in reply: ''` and replies truncated mid-string
(`'{"route": "structured", "exclusion_reason": "none'`).

That reads as a model that cannot follow an output schema. It was not.
**Reproduced with two direct API calls** rather than inferred:

| `max_tokens` | `stop_reason` | content blocks | output tokens | text |
|---|---|---|---|---|
| 300 | `max_tokens` | `['thinking']` | 300 | `''` |
| 1000 | `end_turn` | `['thinking', 'text']` | 580 | valid JSON |

The thinking block alone exceeded 300 tokens, so the budget was exhausted before
any text was generated, and the text-extraction step returned an empty string.

**It was depressing three separate metrics**, which is why it was worth chasing
rather than working around:

| Metric | With the bug | Fixed |
|---|---:|---:|
| Router accuracy | 84.8% | **95.7%** |
| Router schema violations | 21.7% | **0.0%** |
| Answer faithfulness | 11/13 | **13/13** |

Faithfulness moved because truncated answers stop mid-sentence, and a judge
correctly reads an unfinished claim as unsupported. The same latent bug was
present on every generation path (synthesis at 700, refusal at 400, hybrid at
900) and all were raised.

The fix is a one-line budget change, and it is **not** router tuning: the
classifier's prompt, schema and examples are untouched. What changed is that the
reply now has room to exist.

## Measured retrieval quality (n=50)

50 hand-labelled document questions, labels written and verified **before** any
model run. Recall@k and MRR carry normal-approximation intervals (they are
means); hit rate carries Wilson intervals (it is a proportion).

### Embedding model: bge-small beats bge-base, and costs half as much

Both reported regardless of which won — and the larger encoder lost on **every
one of four paired arms**:

| Model | Chunk config | Rerank | Recall@5 (95% CI) | MRR (95% CI) | p50 |
|---|---|---|---|---|---:|
| **bge-small** | small | on | **0.850 [0.756, 0.944]** | **0.712 [0.607, 0.817]** | 2,431 ms |
| **bge-small** | default | on | 0.840 [0.741, 0.939] | 0.669 [0.561, 0.777] | 4,637 ms |
| **bge-small** | small | off | 0.820 [0.716, 0.924] | 0.613 [0.499, 0.727] | **26 ms** |
| **bge-small** | default | off | 0.795 [0.687, 0.903] | 0.598 [0.486, 0.710] | 26 ms |
| bge-base | small | on | 0.800 [0.692, 0.908] | 0.646 [0.534, 0.757] | 2,464 ms |
| bge-base | default | on | 0.750 [0.634, 0.866] | 0.602 [0.489, 0.715] | 4,593 ms |
| bge-base | small | off | 0.740 [0.620, 0.860] | 0.632 [0.513, 0.752] | 52 ms |
| bge-base | default | off | 0.735 [0.614, 0.856] | 0.619 [0.495, 0.743] | 53 ms |

**Verdict: keep `bge-small`.** It wins on Recall@5 in all four paired
comparisons, at **half the query latency** (26 ms vs 52 ms) and **half the
vector size** (384 dimensions vs 768). No individual comparison is significant —
every pair of intervals overlaps — but four out of four in the same direction is
not what noise usually looks like, and there is no cost argument for the larger
model either, so the decision is not close.

This is a negative result for the obvious upgrade, and it is the reason the
comparison was run rather than assumed.

### Reranker 2×2 at n=50: the n=15 verdict was 2–4× too optimistic

The n=15 measurement is **superseded**. Paired comparison on the same 50
questions (the correct analysis — comparing independent intervals wastes the
pairing):

| Config | ΔRecall@5 | ΔMRR | improved / worsened | sign test |
|---|---|---|---:|---:|
| default | +0.045 [0.000, 0.101] | +0.071 [0.000, 0.169] | 16 / 9 | p = 0.23 |
| small | +0.030 [0.000, 0.082] | +0.099 [0.009, 0.189] | 14 / 5 | p = 0.064 |

| | n=15 estimate | n=50 measurement |
|---|---:|---:|
| ΔRecall@5, default | +0.100 | **+0.045** |
| ΔRecall@5, small | +0.133 | **+0.030** |

**The underpowered estimate overstated the effect by 2–4×** — which is exactly
what "directionally positive, underpowered" was warning about, and why the
earlier number was not promoted to a claim.

**Verdict at n=50: not established.** The direction is consistently positive
(14–16 questions improve against 5–9 worsening) and the `small`-config MRR
interval just excludes zero, but neither sign test reaches p<0.05. Combined with
a **90× latency cost** (2,431 ms against 26 ms), the reranker stays **off by
default** (`FIRESIGHT_RERANK=1`). The honest statement is that its benefit is
real in direction and too small to demonstrate at this sample size.

### Self-reference, still visible at n=50

| Arm | Origin | n | Recall@5 | MRR |
|---|---|---:|---:|---:|
| small + rerank | **external USFA/PDR** | 42 | **0.821** | 0.675 |
| small + rerank | methodology | 8 | 1.000 | 0.906 |
| default, no rerank | **external USFA/PDR** | 42 | **0.756** | 0.549 |
| default, no rerank | methodology | 8 | 1.000 | 0.854 |

Methodology questions still score a **perfect 1.000** on every arm. The gap has
narrowed as the external set grew (0.821 against 1.000, versus 0.583 against
1.000 at n=15), but it has not closed, and it will not: eight cleanly-sectioned
chunks written in the same register as the questions are an easy target.

**Take the external figure as the headline: Recall@5 0.821, not 0.850.** The
methodology share is capped at 8/50 (16%) so it cannot carry the number, and the
two are reported separately rather than pooled.

## The "I don't know" path

A question whose best retrieval score falls below `min_support_score` is refused
**before any model call**, which makes the no-support path deterministic and
testable rather than a hope about model behaviour.

The floor was first set at 0.45 by eyeball. That was wrong: measured against 12
out-of-corpus questions, 0.45 admitted **all 12** — "What is the capital of
Mongolia?" scores 0.529 against this corpus, because `bge-small-en-v1.5`
compresses cosine similarity into a narrow high band.

### At n=50 the floor's premise no longer holds

Expanding the in-corpus set from 15 to 50 questions **broke the clean
separation** the floor was built on. Recalibrated:

| Set | in-corpus min | out-of-corpus max | margin | separated? |
|---|---:|---:|---:|---|
| Calibration at n=15 | 0.750 | 0.662 | **+0.088** | yes |
| **Calibration at n=50** | **0.619** | 0.662 | **−0.043** | **no** |
| Held-out (8 in, 10 out) | 0.730 | 0.740 | −0.010 | no |
| Pooled | 0.619 | 0.740 | −0.121 | no |

**No floor separates the two populations.** At the configured 0.70: 0/12
calibration out-of-corpus admitted, but **2/50 in-corpus questions wrongly
refused** — `d14` ("How is the peer group defined?", 0.686) and `d31` ("What
goes in the cross street field?", 0.619). Lowering to 0.65 would admit 3/12
out-of-corpus to save one of them.

The +0.088 gap measured at n=15 was a **small-sample artifact**. A fivefold
larger question set found in-corpus questions scoring below the out-of-corpus
ceiling, which is the thing the earlier maintenance-hazard note predicted would
eventually happen and which no threshold tuning fixes.

The floor stays at **0.70** — deliberately not lowered into the overlap, and
deliberately not raised. The two wrongly-refused questions are pinned by id so
the failure is recorded rather than tuned away, and the structural conclusion is
that a similarity floor is the wrong instrument for this job. The router's
explicit out-of-scope path is the one that actually works (8/8 adversarial), and
it does not depend on a threshold at all.

### Out-of-sample performance — the number that counts

The floor (0.70) was fitted on the calibration questions, so its score on those
is in-sample and proves nothing about generalization. Validated against a
held-out set of 8 in-corpus and 10 out-of-corpus questions used in no
calibration ([`scripts/validate_support_floor.py`](scripts/validate_support_floor.py)):

| Set | Out-of-corpus refused | In-corpus wrongly refused | Separation margin |
|---|---:|---:|---:|
| Calibration (in-sample) | 12/12 | **1/15** | +0.025 |
| **Held-out (out-of-sample)** | **9/10** | **0/8** | **−0.010** |
| Pooled | 21/22 | 1/23 | −0.054 |

**The corpus split cost the gate accuracy, and that is reported rather than
tuned away.** Splitting methodology from build artifacts removed content that
previously scored well for peer-group questions, leaving a 15-chunk methodology
document as a thinner target. One calibration question — *"How is the peer group
defined for benchmarking?"* — now scores **0.686 against the 0.70 floor** and
would be wrongly refused. The in-sample margin fell from +0.088 to +0.025 and the
pooled margin from −0.010 to −0.054.

Retrieval is not at fault: that question's labelled section is still inside the
top 5. The failure is the *absolute score*, not the ranking.

Not fixed by rewording the question (that tunes the benchmark to the system) and
not fixed by lowering the floor (that admits more out-of-corpus questions, and
the pooled margin is already negative). It is pinned by id in the test suite, so
it is recorded precisely and the suite fails if it spreads.

**On held-out data the two populations overlap.** In-corpus questions bottom out
at 0.730; out-of-corpus questions top out at 0.740. The clean +0.088 gap seen at
calibration did not survive, so no floor separates them perfectly — at 0.745 you
refuse all out-of-corpus questions but start refusing a real one.

The single failure is instructive, and it is the adversarial case: *"What is the
recommended pressure for a fire sprinkler system under NFPA 13?"* scores 0.740
and is admitted. The gate is reliable against generic out-of-domain questions and
weakest exactly where it matters most — fire-domain questions whose answer sits in
copyrighted material the corpus deliberately excludes. The prompt carries a
specific NFPA instruction as a second line of defence, but that is model
behaviour, not a guarantee.

### The cross-encoder is a good reranker and a bad gate

Tested as an alternative gate signal, on the theory that it should separate the
populations more cleanly. It does the opposite:

| Signal | Pooled in-corpus min | Pooled out-of-corpus max | Margin |
|---|---:|---:|---:|
| bi-encoder cosine | 0.686 | 0.740 | −0.054 |
| cross-encoder | 0.001 | 1.000 | **−0.999** |

The cross-encoder scores *"What is the current interest rate set by the Federal
Reserve?"* at **1.000** and the genuine in-corpus *"What does the resources field
count?"* at **0.005**. It is well calibrated for ranking candidates against each
other and badly calibrated as an absolute measure of support. **So the reranker
has no justification on the refusal path** — its case rests entirely on the
retrieval gain above.

### Maintenance hazard

The floor is **not a portable constant**. It is specific to this embedding model
and this corpus, and its real margin is **−0.010**, not the +0.088 that
calibration suggested. Consequences:

- **Adding or removing documents requires re-running the calibration.** New
  content shifts the in-corpus score distribution.
- **Changing `FIRESIGHT_EMBED_MODEL` invalidates it entirely.**
- With a margin that thin, a single new borderline question can flip the gate's
  behaviour. Treat 0.70 as a measured parameter under test, not a settled one.

Both scripts are committed and re-runnable; evidence lives in
[`eval/support_floor_calibration.json`](eval/support_floor_calibration.json) and
[`eval/support_floor_validation.json`](eval/support_floor_validation.json).

## The router, and the one thing similarity cannot do

Every question is classified into one of four routes by an LLM classifier whose
output is validated against a strict schema
([`router.py`](src/firesight/retrieval/router.py)). A reply that invents a route
name, omits a reason, or contradicts itself is **rejected and retried**, not
coerced — and the schema-violation rate is a reported metric.

| Route | Path | Citation |
|---|---|---|
| `structured` | text-to-SQL over DuckDB | the executed SQL |
| `unstructured` | vector search over the documents | document + section |
| `hybrid` | **both**, synthesised into one answer | both kinds, in one answer |
| `out_of_scope` | refused | the scope-boundary document |

### Why the router gets the excluded-material distinction explicitly

The hard case is not "what's the weather in Nashville". It is a question that is
squarely about the fire service, shares every keyword with the corpus, and whose
answer lives in material the corpus deliberately excludes:

> *"What is the recommended pressure for a fire sprinkler system under NFPA 13?"*

That question scores **0.740** against this corpus — above the 0.70 support floor
**and** above the 0.730 floor of genuine in-corpus questions. It is the single
held-out gate failure, and **no threshold fixes it**: pushing the floor to 0.745
starts refusing real questions. Embedding similarity provably cannot make this
call, so the distinction is given to the router in words instead.

Fifteen of the 46 labelled router questions are `out_of_scope`, of which **8 are
adversarial excluded-material cases** spanning three mechanisms — NFPA standards,
state and municipal codes, and timestamps NFIRS never recorded. They are scored
as their own category in the confusion matrix.

The subtlest case is turnout time, where the same metric is in or out of scope
depending on who is asked about:

| Question | Route | Why |
|---|---|---|
| "What is our median turnout time?" | `structured` | the local export has dispatch and en-route timestamps |
| "What was the peer-group median turnout time in 2024?" | `out_of_scope` | NFIRS records only alarm and arrival — the interval does not exist |

### Refusals are cited, not bare

A refusal names the boundary it hit and cites
[`data/corpus/SCOPE.md`](data/corpus/SCOPE.md), a short document stating what the
corpus excludes and why. It contains no NFPA substance, is tagged
`exclude_from_scoring` so it cannot inflate retrieval metrics, and counts as
neither external nor project-authored in the origin audit.

The `out_of_scope` path **fetches that document by name** rather than hoping it
ranks. Measured: it does not reach the top 5 for the NFPA-13 question or for
state-fire-code questions — the same similarity blindness that lets those
questions past the floor also keeps the document explaining the refusal out of
the results. Filtered retrieval within the scope document returns the right
section in every case tested (NFPA 13 → "NFPA standards", state code → "State and
municipal fire codes", peer turnout → "Turnout and travel time", pre-2024 trend →
"Years other than 2024").

**Known imperfection, not chased.** *"What turnout time does NFPA 1710 require?"*
cites the "Turnout and travel time" section rather than "NFPA standards". Both are
genuine boundaries for that question — the interval is absent from NFIRS *and* the
threshold is copyrighted — and the router's `exclusion_reason` still drives the
refusal's framing, so the refusal fires correctly and names the right reason. Only
the cited section is the less precise of the two.

**It lives in its own Chroma collection, outside the main index.** It was briefly
in the main index and that cost real ranking precision for presence nothing used
— the `out_of_scope` path fetches it by name regardless. Moving it out recovered
the loss in full:

| Arm | MRR before | MRR sharing the index | MRR after moving out |
|---|---:|---:|---:|
| small + rerank | 0.711 | 0.644 | **0.711** |
| default + rerank | 0.628 | 0.594 | **0.628** |
| default | 0.474 | 0.441 | **0.474** |
| small | 0.452 | 0.386 | 0.419 |

Recall@5 was unchanged throughout on three arms (0.700 / 0.700 / 0.600).

### One question had to be removed, and that is a design constraint

A labelled question asking *"what share of NFIRS departments leave the station
count blank?"* was dropped rather than re-labelled. Its answer — a specific
percentage — existed only in a generated build artifact, so a user asking it
would have been answered from **a number that changes on every rebuild.**

Questions whose answers live in generated output are unanswerable by
construction, not mislabelled. The corpus can hold the *rules* by which a figure
is derived; it cannot hold the figure, because the figure is an output of the
system being documented. That is a constraint on what a document corpus can
cover, and it is why methodology was split from build artifacts rather than
merely trimmed.

### A measurement-stability hazard, now closed

`small`'s Recall@5 did not return to its 0.567 baseline — it sits at 0.533. That
residual is **not** the scope document. It is traced to an edit to
`data/RECONCILIATION.md`, which is itself a corpus document: the Fix 8 rewrite
grew it from 11,759 to 13,190 bytes, adding a section that displaced one of
question d14's two labelled sections out of the top 5. The arithmetic matches
exactly — 0.5 recall on one question of 15 is 0.033, and 0.567 − 0.533 = 0.033.

So **writing the project's documentation moved the project's retrieval metrics** —
a circularity, not merely instability: documenting a measurement changed the
measurement.

**Fixed structurally rather than by policy.** The corpus is now an explicit
allowlist (`CORPUS_MANIFEST`), not a directory glob, so nothing becomes corpus by
sitting in the right folder. Project-authored material is split in two:

- **Methodology** — the peer-group definition, the response-time filter, the
  alarm-to-arrival constraint, the incident-type exclusions — lives in one
  **frozen** document, [`data/corpus/METHODOLOGY.md`](data/corpus/METHODOLOGY.md),
  pinned by SHA-256. A user asking how a figure was derived gets a cited answer,
  and editing that document is a deliberate act that forces re-measurement.
- **Build artifacts** — `PROFILE.md`, `RECONCILIATION.md`, this README, anything
  under `eval/results/` — are out of the corpus entirely, enforced by a denylist
  tested from both directions.

A test fails if a measured metric (`Recall@5`, `MRR`, a confusion matrix, an
accuracy figure) ever appears in the frozen document, which closes the
circularity by construction rather than by discipline.

## Read this before trusting any ranking

The benchmarkable cohort is **not a random sample of US fire departments.** Three
filters stack:

1. NFIRS peer criteria require station count, career and volunteer headcount — fields
   blank for **42–63%** of departments. Only the ~37% that file complete
   administrative data can be evaluated at all, and departments diligent about
   paperwork plausibly differ from those that aren't.
2. Departments need >10 scored response times to rank.
3. 20 departments whose same-minute-arrival rate is implausible are excluded as a
   reporting artifact; 14 of them were in the ranking pool.

What remains is **768 departments**, not the 1,138 claimed by the prior work on this
data. Every ranking this system outputs carries that caveat — see
[`data/RECONCILIATION.md`](data/RECONCILIATION.md).

### Headline: Pool B

All four figures come from one cohort — **Pool B, 768 departments**, the live
exclusion rule. Percentiles use midpoint tie-handling; lower is better.

| Metric | Sewanee | Cohort |
|---|---:|---|
| P90 response time, regional percentile | **14.4%** | 768 departments, 8 states |
| P90 response time, Tennessee percentile | **10.5%** | 237 TN departments |
| 8-minute compliance, regional percentile | **8.5%** | 768 departments, 8 states |
| 8-minute compliance, Tennessee percentile | **6.5%** | 237 TN departments |

Sewanee's P90 is 13.0 min against a peer median of 18.0 min.

**Two things are true at once about the regional P90 figure, and both matter.**
The corrected 14.4% is *better* than the 29% originally published for this
department — and it is computed against a **materially different cohort**: 768
departments under a corrected `(state, fdid)` join, against roughly 1,138 under a
state-blind join that merged in unrelated departments' incidents. It is not a
like-for-like improvement in rank; it is a different measurement that happens to
land more favourably. Quoting the improvement without the cohort change would
misrepresent it.

#### Sensitivity to the exclusion rule

Excluding a department for an implausible zero rate removes a *fast-looking*
department from the cohort, which inflates Sewanee's rank — the bias runs toward
the client, so the alternatives are published rather than buried.

| Pool | n | P90 regional | P90 TN | Compliance regional | Compliance TN |
|---|---:|---:|---:|---:|---:|
| **A** no exclusion | 782 | 14.6% | 10.4% | 9.0% | 6.5% |
| **B** live rule (headline) | 768 | 14.4% | 10.5% | 8.5% | 6.5% |
| **C** withdrawn 3×-median rule | 648 | 13.0% | 9.9% | 7.0% | 6.2% |

More exclusion, better rank — monotonically. Pool C, the rule that was withdrawn
for being unsatisfiable by construction, flattered Sewanee most. Pool B sits
within 0.2pp of the no-exclusion case on every metric, so the headline does not
depend on the exclusion rule being right.

### The zero-response filter choice was tested, not assumed

Keeping same-minute arrivals rather than discarding them leaves Sewanee's **P90
unchanged at 13.0 min**, while moving P95 by **−0.9 min** and 8-minute compliance
by **+1.0pp**. The predicted bias is real but lands off the headline metric. A null
result on the headline is worth stating plainly.

Supporting evidence: of 95 zero-minute *building fire* incidents, 80 (84%) sit in
departments with unremarkable zero rates and only 2 carry a placeholder timestamp —
spread, not clustered. Station-adjacent fires genuinely do produce same-minute
arrivals.

NFIRS also records **only alarm-to-arrival**. There is no dispatch or en-route
timestamp, so turnout and travel time cannot be computed from it for any department
or year. The system is instructed to say so rather than substitute total response
time.

## What's here now

| | |
|---|---|
| **Data profile** | [`data/PROFILE.md`](data/PROFILE.md) — schemas, row counts, null rates, date coverage, and nine known data-quality problems found by full scans |
| **Reconciliation** | [`data/RECONCILIATION.md`](data/RECONCILIATION.md) — rebuilt figures vs. prior output, the one documented delta, and the corrected rankings |
| **Evidence** | [`data/profile_stats.json`](data/profile_stats.json) — the raw numbers behind every figure in the profile |
| **Structured store** | [`src/firesight/ingest/structured.py`](src/firesight/ingest/structured.py) — NFIRS + local export → 5 DuckDB tables |
| **Text-to-SQL** | [`src/firesight/retrieval/sql_agent.py`](src/firesight/retrieval/sql_agent.py), [`schema.py`](src/firesight/retrieval/schema.py) — prompt, few-shot examples, retry-once |
| **Read-only guard** | [`src/firesight/retrieval/sql_guard.py`](src/firesight/retrieval/sql_guard.py) — AST validation + row cap + timeout, with 40 adversarial tests |
| **Document corpus** | [`src/firesight/ingest/documents.py`](src/firesight/ingest/documents.py) — PDF/markdown → chunks → Chroma, idempotent, two chunk configs |
| **Vector retrieval** | [`src/firesight/retrieval/vector_store.py`](src/firesight/retrieval/vector_store.py) — embedding search + optional cross-encoder rerank |
| **Cited synthesis** | [`src/firesight/generation/synthesize.py`](src/firesight/generation/synthesize.py) — inline citations, calibrated refusal gate |
| **Router** | [`src/firesight/retrieval/router.py`](src/firesight/retrieval/router.py) — 4 routes, strict schema, excluded-material rules |
| **Hybrid + refusal** | [`src/firesight/generation/answer.py`](src/firesight/generation/answer.py) — end-to-end answering, both citation types, cited refusals |
| **Scope boundary** | [`data/corpus/SCOPE.md`](data/corpus/SCOPE.md) — what the corpus excludes and why |
| **Config** | [`src/firesight/config.py`](src/firesight/config.py) — paths, models, guardrails, peer-group definition, and the three named exclusions |

## Document corpus

1,684 chunks (`default`) / 3,244 (`small`) across five documents, plus a separate
8-chunk scope-boundary collection outside the main index. Membership is an
explicit allowlist (`CORPUS_MANIFEST`), not a directory glob — a file becomes
corpus only by being named there, enforced by test. Every source is public domain
or own work:

| Document | Publisher | Chunks |
|---|---|---:|
| NFIRS 5.0 Complete Reference Guide | USFA/FEMA | 691 |
| NFIRS 5.0 Design Documentation | USFA/FEMA | 573 |
| NFIRS Code Dictionary (245 incident types, 244 coded fields) | USFA/FEMA | 305 |
| NFIRS 5.0 Fire Data Analysis Guidelines and Issues | USFA/FEMA | 103 |
| **FireSight Methodology** (frozen, SHA-256 pinned) | own work | 12 |
| *FireSight Corpus Scope* | *own work, separate collection* | *8* |

Build artifacts are denylisted: `PROFILE.md`, `RECONCILIATION.md`, this README and
`eval/results/` are **not** corpus, and a test checks that from both directions.

USFA documents are US federal government works (17 U.S.C. §105). **NFPA standards
are copyrighted and are never ingested** — where a compliance threshold is needed,
it is cited by standard number only, and the prompt instructs the model to say the
corpus does not contain it.

**The local incident export is deliberately not in the corpus.** It carries street
addresses, building names, coordinates and personnel identifiers for real
incidents. A test asserts no chunk contains them.

Sections come from each PDF's own bookmark outline rather than a heading regex —
the NFIRS documents are mostly tables, and a regex happily mistakes a table row
like "7 Death" for a chapter title. Chunk text is sliced from the original string
by character offset, never rebuilt by decoding token ids, because
`bge-small-en-v1.5` is uncased and a decode round-trip lowercases every citation.

## Pipeline

```bash
uv run python -m firesight.ingest.structured     # build DuckDB (~30 s)
```

```bash
uv run python scripts/verify_reference_sql.py    # verify the 20 reference answers
```

```bash
uv run python scripts/check_zero_responses.py    # zero-response distribution check
```

```bash
uv run python -m firesight.ingest.documents --clean   # build the Chroma corpus
```

Use `--clean`, not `--rebuild`, for a reset. `--rebuild` calls Chroma's
`delete_collection`, which leaves the collection's HNSW segment directory behind,
so repeated rebuilds accumulate orphans. Measured here: **14 segment directories
and 131 MB for what should be 4 collections**, which a clean rebuild returned to
4 directories and ~30 MB. `--clean` removes the store outright.

The test suite slowed from 96 s to 24 min while those orphans accumulated, and
returned to **110 s** immediately after a clean rebuild. That is strong evidence
the segments were the cause, though not a controlled experiment — CPU state also
differed between runs, and query latency itself stayed at 28–48 ms throughout, so
retrieval was never slow. What was slow was the client's startup scan.

```bash
uv run python scripts/calibrate_support_floor.py # calibrate the refusal gate
```

```bash
uv run python -m firesight.eval.retrieval_suite --k 5   # Recall@k, MRR, reranker decision
```

```bash
uv run python -m firesight.eval.sql_suite        # SQL accuracy (needs an API key)
```

```bash
uv run python -m firesight.eval.router_suite     # router confusion matrix (needs an API key)
```

```bash
uv run python -m firesight.retrieval.sql_agent "What was Sewanee's P90 response time in 2024?"
```

```bash
uv run python -m firesight.generation.synthesize "How does NFIRS define a structure?"
```

```bash
uv run python -m firesight.generation.answer "What turnout time does NFPA 1710 require?"
```

## Setup

Requires [uv](https://docs.astral.sh/uv/). `uv` fetches its own Python 3.12 —
the project pins `>=3.11,<3.13` because `sentence-transformers`/`torch` have no
3.13+ wheels yet.

```bash
uv sync
```

```bash
cp .env.example .env
```

Then edit `.env`: set an API key, and point `FIRESIGHT_NFIRS_DIR` and
`FIRESIGHT_LOCAL_INCIDENTS` at your local copies of the source data
(see [`data/PROFILE.md`](data/PROFILE.md) for how to obtain them — none of it is
redistributable through this repo).

Verify the install:

```bash
uv run pytest
```

Regenerate the data profile (~4 min; scans 6.7 GB):

```bash
uv run python scripts/profile_source_data.py
```

## Layout

```
src/firesight/
  config.py       paths, models, guardrails, peer-group definition
  ingest/         structured.py (-> DuckDB), documents.py (-> Chroma)
  retrieval/      sql_agent.py, sql_guard.py, vector_store.py, router.py
  generation/     prompts, answer synthesis, citation assembly
  eval/           harness, metrics, golden set
  app/            Streamlit demo
scripts/          one-off operational scripts (data profiling)
eval/             golden_set.jsonl + committed result reports
data/PROFILE.md   the data profile (committed); the data itself is not
```

## Data and licensing

The structured corpus is the **NFIRS 2024 Public Data Release** (U.S. Fire
Administration, public domain). It is not committed here — it is ~12 GB
uncompressed. `data/PROFILE.md` documents how to obtain it.

The local department export contains incident-level addresses and is **not
redistributable**; see the privacy note in `data/PROFILE.md`.

NFPA standards (1710, 1720, …) are copyrighted and their text will not appear in
this repo. Where a compliance threshold is referenced, it is cited by standard
number and section only.

Code is MIT licensed.
