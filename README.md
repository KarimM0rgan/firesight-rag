# FireSight RAG

Hybrid retrieval over real fire-service data: natural-language questions are routed
to **text-to-SQL** over 33.3M NFIRS incident records, to **vector search** over a
reference-document corpus, or to both — and answered with citations.

> **Status: M1 complete (structured store + text-to-SQL).** Vector retrieval (M2),
> routing (M3), and the full eval harness (M4) are not built yet. Milestones are
> specified in [FIRESIGHT_RAG_SPEC.md](FIRESIGHT_RAG_SPEC.md). This README is
> rewritten at M6.
>
> **Text-to-SQL accuracy is not yet measured** — scoring needs an API key, which
> this environment does not have. The harness and the 20-question set are built and
> run on one command; no accuracy figure is claimed until it has actually run.

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
| **Config** | [`src/firesight/config.py`](src/firesight/config.py) — paths, models, guardrails, peer-group definition, and the three named exclusions |

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
uv run python -m firesight.eval.sql_suite        # score the agent (needs an API key)
```

```bash
uv run python -m firesight.retrieval.sql_agent "What was Sewanee's P90 response time in 2024?"
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
  ingest/         NFIRS + local export -> DuckDB;  documents -> Chroma
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
