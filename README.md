# FireSight RAG

Hybrid retrieval over real fire-service data: natural-language questions are routed
to **text-to-SQL** over 33.3M NFIRS incident records, to **vector search** over a
reference-document corpus, or to both — and answered with citations.

> **Status: M0 complete (scaffold + data profile).** No retrieval is implemented yet.
> Milestones M1–M6 are specified in [FIRESIGHT_RAG_SPEC.md](FIRESIGHT_RAG_SPEC.md).
> This README is rewritten at M6; there are no performance claims here yet because
> nothing has been measured yet.

## What's here now

| | |
|---|---|
| **Data profile** | [`data/PROFILE.md`](data/PROFILE.md) — schemas, row counts, null rates, date coverage, and the known data-quality problems found by full scans |
| **Evidence** | [`data/profile_stats.json`](data/profile_stats.json) — the raw numbers behind every figure in the profile |
| **Profiler** | [`scripts/profile_source_data.py`](scripts/profile_source_data.py) — reproduces that JSON from the source files |
| **Config** | [`src/firesight/config.py`](src/firesight/config.py) — paths, models, guardrails, and the peer-group definition |

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
