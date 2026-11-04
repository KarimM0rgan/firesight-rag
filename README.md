# FireSight RAG

Hybrid retrieval over real fire-service data: natural-language questions are routed
to **text-to-SQL** over 33.3M NFIRS incident records, to **vector search** over a
reference-document corpus, or to both — and answered with citations.

> **Status: M3 built, not yet measured.** The structured store, text-to-SQL,
> vector retrieval, router and hybrid answer path all exist. The full eval harness
> (M4) is not built. Milestones are in
> [FIRESIGHT_RAG_SPEC.md](FIRESIGHT_RAG_SPEC.md); this README is rewritten at M6.
>
> **Four numbers remain unmeasured** because every one needs a generation API key
> that is not present in this environment: text-to-SQL execution accuracy, SQL
> result accuracy, answer faithfulness, and router accuracy. All four harnesses
> are built, run on one command each, and refuse to write a report without a real
> run rather than emit a placeholder. Everything measured below uses local
> embeddings and needs no key.

## Measured retrieval quality

15 hand-labelled document questions, k=5. Labels are `(document, section)` pairs
rather than chunk ids, so one labelled set survives a chunking-config change.

### The 2×2: chunk size × reranking

| Chunk config | Rerank | Recall@5 | MRR | Hit rate | Answer present | p50 latency |
|---|---|---:|---:|---:|---:|---:|
| default (500 tok, 15%) | off | 0.600 | 0.474 | 0.667 | 0.533 | 29 ms |
| default (500 tok, 15%) | on | 0.700 | 0.628 | 0.800 | 0.667 | 4,508 ms |
| small (220 tok, 20%) | off | 0.567 | 0.452 | 0.600 | 0.467 | 34 ms |
| small (220 tok, 20%) | on | **0.700** | **0.711** | **0.800** | **0.667** | 2,416 ms |

*Answer present* is stricter than Recall: it asks whether the chunk containing the
literal answer text was retrieved, not merely a chunk from the right section.

### Reranker verdict: directionally positive, underpowered

`bge-reranker-base` improves both metrics in both chunk configurations:

| Config | ΔRecall@5 | in questions | ΔMRR | Added latency |
|---|---:|---:|---:|---:|
| default | +0.100 | +1.5 of 15 | +0.153 | +4,480 ms |
| small | +0.133 | +2.0 of 15 | +0.259 | +2,382 ms |

**n=15, so one question is worth 0.067 Recall@5 — these deltas are 1.5 and 2.0
questions.** That is not enough evidence to call the reranker's benefit
established. It points the same way in both configurations, which is mildly
reassuring, but the honest statement is: *directionally positive, underpowered,
re-measure against the 50-question golden set at M4.*

It ships **off by default** (`FIRESIGHT_RERANK=1` to enable) because 2.4 s per
query on CPU against 34 ms is a deliberate choice regardless of the quality
question. With a GPU or an ONNX-quantised cross-encoder it would be on.

### Retrieval scores are inflated by self-reference

Four of the 15 questions are answered by the project's own notes rather than by
the external USFA documents. Those four are a materially easier retrieval task —
the notes are few, cleanly sectioned in markdown, and written in the same
register as the questions.

| Arm | Origin | n | Recall@5 | MRR | Hit rate |
|---|---|---:|---:|---:|---:|
| small + rerank | **external USFA/PDR** | 11 | **0.636** | 0.667 | 0.727 |
| small + rerank | project-authored | 4 | 0.875 | 0.833 | 1.000 |
| default | external USFA/PDR | 11 | 0.545 | 0.374 | 0.636 |
| default | project-authored | 4 | 0.750 | 0.750 | 0.750 |

**Take the external figure as the real one: Recall@5 0.636, not 0.700.** The gap
holds across every arm. M4's golden set must rebalance toward external sources —
a target of ≤20% project-authored, against the current 27%.

### A tuning interaction worth knowing

Cross-encoder truncation must be **at least the chunk size**. Dropping
`FIRESIGHT_RERANK_MAX_LEN` from 512 to 256 halves latency but takes `default`
(500-token chunks) from Recall@5 0.700 back to 0.600 — exactly the no-reranker
score, because half the evidence is cut off before scoring. With `small`
(220-token chunks), 256 is sufficient and the gain survives.

## The "I don't know" path

A question whose best retrieval score falls below `min_support_score` is refused
**before any model call**, which makes the no-support path deterministic and
testable rather than a hope about model behaviour.

The floor was first set at 0.45 by eyeball. That was wrong: measured against 12
out-of-corpus questions, 0.45 admitted **all 12** — "What is the capital of
Mongolia?" scores 0.529 against this corpus, because `bge-small-en-v1.5`
compresses cosine similarity into a narrow high band.

### Out-of-sample performance — the number that counts

The floor (0.70) was fitted on the calibration questions, so its score on those
is in-sample and proves nothing about generalization. Validated against a
held-out set of 8 in-corpus and 10 out-of-corpus questions used in no
calibration ([`scripts/validate_support_floor.py`](scripts/validate_support_floor.py)):

| Set | Out-of-corpus refused | In-corpus wrongly refused | Separation margin |
|---|---:|---:|---:|
| Calibration (in-sample) | 12/12 | 0/15 | +0.088 |
| **Held-out (out-of-sample)** | **9/10** | **0/8** | **−0.010** |
| Pooled | 21/22 | 0/23 | −0.010 |

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
| bi-encoder cosine | 0.730 | 0.740 | −0.010 |
| cross-encoder | 0.005 | 1.000 | **−0.995** |

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
section every time (NFPA → "NFPA standards", state code → "State and municipal
fire codes", peer turnout → "Turnout and travel time").

**Measured cost of adding it.** Its 8–9 chunks compete for ranking slots like any
others. Recall@5 held at 0.700 on the reranked arms, but MRR fell from 0.711 to
0.644 on the best arm and `small` without reranking dropped from 0.567 to 0.533.
That is the price of cited refusals, and it is paid in ranking precision.

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

1,708 chunks (`default`) / 3,287 (`small`) across six documents. Every source is
public domain or own work:

| Document | Publisher | Chunks |
|---|---|---:|
| NFIRS 5.0 Complete Reference Guide | USFA/FEMA | 777 |
| NFIRS 5.0 Design Documentation | USFA/FEMA | 608 |
| NFIRS Code Dictionary (245 incident types, 244 coded fields) | USFA/FEMA | 305 |
| NFIRS 5.0 Fire Data Analysis Guidelines and Issues | USFA/FEMA | 138 |
| FireSight Data Profile | own work | 20 |
| FireSight Reconciliation Notes | own work | 16 |

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
uv run python -m firesight.ingest.documents --rebuild   # build the Chroma corpus
```

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
