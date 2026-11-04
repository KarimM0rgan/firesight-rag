# FireSight RAG

Hybrid retrieval over real fire-service data: natural-language questions are routed
to **text-to-SQL** over 33.3M NFIRS incident records, to **vector search** over a
reference-document corpus, or to both — and answered with citations.

> **Status: M2 complete (structured store, text-to-SQL, vector retrieval).**
> Routing (M3) and the full eval harness (M4) are not built yet. Milestones are
> specified in [FIRESIGHT_RAG_SPEC.md](FIRESIGHT_RAG_SPEC.md). This README is
> rewritten at M6.
>
> **Two numbers are not yet measured** because scoring them needs a generation API
> key this environment does not have: text-to-SQL accuracy, and answer
> faithfulness. Both harnesses are built and run on one command, and both refuse to
> write a report without a real run rather than emit a placeholder. Retrieval
> metrics below are measured — they use local embeddings and need no key.

## Measured retrieval quality

15 hand-labelled document questions, k=5. Labels are `(document, section)` pairs
rather than chunk ids, so one labelled set survives a chunking-config change.

| Arm | Recall@5 | MRR | Hit rate | Answer present | p50 latency |
|---|---:|---:|---:|---:|---:|
| **small + rerank** | **0.700** | **0.711** | **0.800** | 0.667 | 2,401 ms |
| default + rerank | 0.700 | 0.628 | 0.800 | 0.667 | 4,576 ms |
| default (no rerank) | 0.600 | 0.474 | 0.667 | 0.533 | 30 ms |
| small (no rerank) | 0.567 | 0.452 | 0.600 | 0.467 | 28 ms |

`default` = 500-token chunks, 15% overlap. `small` = 220-token, 20% overlap.
*Answer present* is a stricter check than Recall: it asks whether the chunk
containing the literal answer text was retrieved, not merely a chunk from the
right section.

### The reranker earns its place — but costs 90× the latency

`bge-reranker-base` improves both metrics in both chunk configurations:

| Config | ΔRecall@5 | ΔMRR | Added latency |
|---|---:|---:|---:|
| default | +0.100 | +0.153 | +4,546 ms |
| small | +0.133 | +0.259 | +2,374 ms |

**Verdict: keep it, but ship it off by default** (`FIRESIGHT_RERANK=1` to enable).
The quality gain is real and consistent across both configurations, which is what
distinguishes it from noise. But 2.4 seconds per query on CPU against 28 ms makes
it a deliberate choice, not a default. With a GPU, or an ONNX-quantised
cross-encoder, it would be on.

**Caveat on the sample size.** n=15, so a single question is worth 0.067 Recall@5.
The deltas above are 1.5–2 questions each. They point the same way in both
configurations, but this needs re-measuring against M4's 50-question golden set
before anyone leans on the exact figures.

### A tuning interaction worth knowing

Cross-encoder truncation must be **at least the chunk size**. Dropping
`FIRESIGHT_RERANK_MAX_LEN` from 512 to 256 halves latency but takes `default`
(500-token chunks) from Recall@5 0.700 back to 0.600 — exactly the no-reranker
score, because half the evidence is cut off before scoring. With `small`
(220-token chunks), 256 is sufficient and the gain survives.

### The "I don't know" path is calibrated, not guessed

A question whose best retrieval score falls below `min_support_score` is refused
**before any model call**, which makes the no-support path deterministic and
testable rather than a hope about model behaviour.

The floor was first set at 0.45 by eyeball. That was wrong: measured against 12
deliberately out-of-corpus questions, 0.45 admitted **all 12** — "What is the
capital of Mongolia?" scores 0.529 against this corpus, because
`bge-small-en-v1.5` compresses cosine similarity into a narrow high band.

Calibrated ([`scripts/calibrate_support_floor.py`](scripts/calibrate_support_floor.py)):
labelled in-corpus questions score **≥ 0.750**; out-of-corpus questions score
**≤ 0.662**. The floor sits at **0.70**, in the gap. At that setting **12/12
out-of-corpus questions are refused and 0/15 in-corpus questions are wrongly
refused**. The value is model-specific — changing the embedding model requires
re-running the calibration.

## Read this before trusting any ranking

The benchmarkable cohort is **not a random sample of US fire departments.** Three
filters stack:

1. NFIRS peer criteria require station count, career and volunteer headcount — fields
   blank for **42–63%** of departments. Only the ~37% that file complete
   administrative data can be evaluated at all, and departments diligent about
   paperwork plausibly differ from those that aren't.
2. Departments need >10 scored response times to rank.
3. 134 departments whose same-minute-arrival rate exceeded 3× the cohort median are
   excluded as a reporting artifact.

What remains is **768 departments**, not the 1,138 claimed by the prior work on this
data. Every ranking this system outputs carries that caveat — see
[`data/RECONCILIATION.md`](data/RECONCILIATION.md).

### Headline figures are the worst case across pool definitions

Excluding a department for an implausible zero rate removes a *fast-looking*
department from the cohort, which inflates Sewanee's rank. That bias runs toward
the client, so the published figure is the **least favorable value across all three
pool definitions**, not the best-looking one.

| Pool | n | P90 regional | P90 TN | Compliance regional | Compliance TN |
|---|---:|---:|---:|---:|---:|
| **A** no exclusion | 782 | 14.6% | 10.4% | 9.0% | 6.5% |
| **B** sentinel evidence + 25% plausibility floor (live) | 768 | 14.4% | 10.5% | 8.5% | 6.5% |
| **C** withdrawn 3×-median rule | 648 | 13.0% | 9.9% | 7.0% | 6.2% |
| **Published** | — | **14.6%** | **10.5%** | **9.0%** | **6.5%** |

More exclusion, better rank — monotonically. Pool C flattered Sewanee most, which
is why it is not the headline. Peer median P90 is 18.0 min against Sewanee's 13.0
under every definition.

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
uv run python -m firesight.eval.sql_suite        # score the agent (needs an API key)
```

```bash
uv run python -m firesight.retrieval.sql_agent "What was Sewanee's P90 response time in 2024?"
```

```bash
uv run python -m firesight.generation.synthesize "How does NFIRS define a structure?"
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
  retrieval/      sql_agent.py, vector_store.py, router.py
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
