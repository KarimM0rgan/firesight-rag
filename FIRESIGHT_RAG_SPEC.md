# FireSight RAG — Project Specification

**Owner:** Karim E. Morgan
**Target completion:** ~4 weeks from start (aim for a public repo before late October)
**Repo name:** `firesight-rag`
**Purpose:** A resume-grade applied GenAI project — a hybrid retrieval system that answers natural-language questions about fire department performance using both structured NFIRS incident data and unstructured reference documents, with an honest evaluation harness.

---

## 0. Instructions for Claude Code

Read this entire file before writing any code. Then:

1. Start with **M0** and do not skip ahead.
2. After each milestone, stop and report: what was built, what the acceptance criteria measured, and what you'd change. Wait for confirmation before starting the next milestone.
3. **Do not fabricate data, metrics, or evaluation results.** If a number can't be measured, say so.
4. If a design decision in this spec conflicts with what you find in the actual data, flag it and propose an alternative rather than silently working around it.
5. Commit at the end of each milestone with a descriptive message. Never commit secrets, API keys, `.env` files, or raw data files over 50 MB.

### What makes this project worth building

The differentiator is **not** that it uses RAG. Every student project uses RAG. The differentiator is:

- It runs over **real civic data with real messiness**, not a toy PDF corpus.
- It **routes** between structured (SQL) and unstructured (vector) retrieval instead of stuffing everything into one vector store.
- It reports **measured evaluation metrics** with a documented methodology, not screenshots of good-looking answers.

If a milestone forces a tradeoff, protect those three properties.

---

## 1. Success criteria

The project is done when all of the following are true:

- [ ] A user can ask a plain-English question and get a correct, **cited** answer that names its sources (table + query, or document + section).
- [ ] The router correctly classifies question type (structured / unstructured / hybrid / out-of-scope) on a held-out set, with measured accuracy.
- [ ] An evaluation suite of **≥50 hand-written question/answer pairs** runs as a single command and emits a metrics report.
- [ ] Retrieval quality, answer faithfulness, and text-to-SQL execution accuracy are each measured and reported with numbers.
- [ ] Latency and cost per query are logged and reported (p50/p95).
- [ ] At least one **failure analysis** section exists in the README describing categories of questions the system gets wrong, with examples.
- [ ] The README is written for a hiring manager who has 90 seconds.

### Explicit non-goals

- No fine-tuning. That's a separate later project.
- No multi-agent orchestration. A router is not an agent framework; keep it simple.
- No authentication, user accounts, or multi-tenancy.
- No production deployment beyond a working demo (Streamlit or Gradio is sufficient).
- No mobile UI.

---

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Package mgmt | `uv` (fall back to `pip` + `venv` if unavailable) | |
| Structured store | DuckDB | Zero-config, fast on analytical queries, file-based — right choice for NFIRS-scale tables |
| Vector store | ChromaDB (local, persisted) | Swap to pgvector only if there's a concrete reason |
| Embeddings | `BAAI/bge-small-en-v1.5` or `all-MiniLM-L6-v2` via `sentence-transformers` | Local, free, no API dependency for retrieval |
| Generation | Anthropic or OpenAI API, model configurable via env var | Must be swappable in one config line |
| Orchestration | Plain Python + a thin router. LangChain/LlamaIndex **only** where they save real work | Avoid framework lock-in; you should be able to explain every step in an interview |
| Evaluation | Ragas or DeepEval + custom SQL execution-accuracy harness | |
| Observability | Langfuse (self-hosted or free tier) or structured JSON logs | Every query logs: question, route, retrieved context, tokens, latency, cost |
| UI | Streamlit | Karim has shipped Streamlit + Plotly before — reuse that muscle |
| Testing | `pytest` | |
| Lint/format | `ruff` | |

Keep dependencies minimal. Every added package should justify itself.

---

## 3. Data

### 3.1 Inspect before assuming

**Do this first.** Do not write schema code based on this spec's guesses. Locate and profile the actual data:

- Karim has prior NFIRS work: benchmarking Sewanee Fire Department against ~1,138 regional peer departments, including P90 response-time percentiles and NFPA compliance rates. Find those artifacts (Jupyter notebooks, CSVs, parquet files) and treat them as the source of truth for schema and derived metrics.
- Report back: table names, row counts, column names and dtypes, null rates, date ranges, and any obvious data-quality problems (duplicate incident IDs, impossible timestamps, sentinel values like `9999`).
- Reconcile any derived metric you rebuild against the original notebook's numbers. **If they don't match, stop and investigate.** A silent metric drift makes the whole project untrustworthy.

### 3.2 Structured corpus (DuckDB)

Expected shape — verify against reality:

- `incidents` — one row per incident: id, department id, incident type, timestamps (alarm / dispatch / en route / arrival), location.
- `departments` — one row per department: id, name, state, county, population served, station count, staffing type (career / volunteer / combination).
- `metrics_department_year` — precomputed per-department aggregates: incident volume, response-time percentiles (p50/p90), NFPA compliance rate, peer-group assignment.

Build the third table as a materialized view or ETL step so the SQL agent queries pre-aggregated metrics instead of recomputing percentiles over millions of rows on every question. This matters for latency.

### 3.3 Unstructured corpus (Chroma)

**Copyright constraint, read carefully:** NFPA standards (1710, 1720, etc.) are copyrighted. Do not scrape, redistribute, or commit their full text to a public repo. Use instead:

- NFIRS official documentation and coding manuals (USFA, public domain)
- USFA published reports and topical research series
- State fire marshal reports and public incident-reporting guidance
- Municipal fire department annual reports (publicly posted)
- Karim's own written methodology notes from the prior benchmarking work

Chunking: start with ~500-token chunks and ~15% overlap, respecting document section boundaries. **Do not treat this as settled** — M4 requires testing at least two chunking configurations and reporting which wins on retrieval metrics.

Every chunk must carry metadata: `source_document`, `section`, `page`, `publisher`, `year`, `url`.

---

## 4. Milestones

### M0 — Scaffold and data profile

Set up the repo, environment, and produce a written data profile.

**Structure:**

```
firesight-rag/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── data/
│   ├── raw/              # gitignored
│   ├── processed/        # gitignored
│   └── PROFILE.md        # committed — the data profile writeup
├── src/firesight/
│   ├── config.py
│   ├── ingest/           # ETL to DuckDB, document loading + chunking
│   ├── retrieval/        # sql_agent.py, vector_store.py, router.py
│   ├── generation/       # prompt templates, answer synthesis, citation assembly
│   ├── eval/             # harness, metrics, golden set
│   └── app/              # Streamlit UI
├── notebooks/            # exploration only, not the deliverable
├── tests/
└── eval/
    ├── golden_set.jsonl
    └── results/          # committed reports
```

**Acceptance:** `data/PROFILE.md` exists with row counts, schema, null rates, date coverage, and a "known data quality issues" list. `uv run pytest` passes on an empty test suite. Repo initialized, `.gitignore` covers `.env`, `data/raw/`, `data/processed/`, `*.duckdb`.

---

### M1 — Structured retrieval (text-to-SQL)

Natural-language question → SQL → executed result → natural-language answer with the query shown.

Requirements:
- Schema description is injected into the prompt, including column semantics and units. Bad schema descriptions cause most text-to-SQL failures.
- Include 5–8 few-shot examples of question → correct SQL, drawn from real questions a fire chief would ask.
- **Read-only enforcement:** reject any generated SQL containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, or `ATTACH`. Parse and validate before execution — do not rely on prompting alone.
- Query timeout and row-limit caps.
- On execution error, retry once with the error message fed back; then fail gracefully with an honest "I couldn't answer that."
- The generated SQL is always surfaced to the user. This is the citation for structured answers.

**Acceptance:** 20 structured questions written by hand; report execution accuracy (query runs without error) and result accuracy (result matches a manually verified answer) as separate numbers. Both must be measured, not estimated.

---

### M2 — Unstructured retrieval (vector RAG)

Document ingestion, chunking, embedding, retrieval, and cited answer synthesis.

Requirements:
- Ingestion pipeline is idempotent and re-runnable.
- Retrieval returns top-k with scores; k configurable.
- Answers cite `source_document` + `section` inline. **An answer with no retrieved support must say it doesn't know** rather than answering from parametric knowledge. Test this explicitly with an out-of-corpus question.
- Add a reranking step (cross-encoder, e.g. `bge-reranker-base`) and measure whether it actually helps. If it doesn't, remove it and say so in the README — a negative result honestly reported is a strength.

**Acceptance:** 15 document-grounded questions; report Recall@5 and MRR against manually labeled relevant chunks. Report faithfulness (does the answer stay within retrieved context) via Ragas or manual labeling.

---

### M3 — Router and hybrid answers

A classifier routes each question to one of four paths:

| Route | Example |
|---|---|
| `structured` | "What was our p90 response time in 2023?" |
| `unstructured` | "How does NFIRS define a structure fire?" |
| `hybrid` | "How does our p90 response time compare to peer departments, and does it meet the applicable standard?" |
| `out_of_scope` | "What's the weather in Nashville?" |

Start with an LLM-based classifier and a strict output schema. Hybrid answers must run both retrievers and synthesize a single response carrying **both** citation types.

**Acceptance:** router accuracy measured on a labeled set of ≥40 questions spanning all four routes, reported as a confusion matrix. Out-of-scope must be refused, not answered.

---

### M4 — Evaluation harness

This milestone is the point of the project. Do not rush it.

- **Golden set:** ≥50 question/answer pairs in `eval/golden_set.jsonl`, hand-written and hand-verified. Fields: `question`, `expected_route`, `reference_answer`, `relevant_chunk_ids` (unstructured) or `reference_sql` / `reference_result` (structured), `difficulty`, `category`.
- Deliberately include hard cases: ambiguous questions, questions requiring a peer-group definition, questions whose answer is genuinely not in the data.
- **Single command runs everything:** `uv run python -m firesight.eval.run --all` → writes a timestamped markdown + JSON report to `eval/results/`.

Metrics to report:
- Retrieval: Recall@k, MRR, hit rate
- Generation: faithfulness, answer relevance
- SQL: execution accuracy, result-match accuracy
- Routing: per-class precision/recall
- Ops: p50/p95 latency, mean tokens, mean cost per query

Run the suite across at least two chunking configurations and two values of k. Put the comparison table in the README.

**Acceptance:** report generated and committed. Every headline number in the README traces to a file in `eval/results/`.

---

### M5 — Demo UI

Streamlit app: question box, streamed answer, expandable panel showing the route taken, generated SQL (if any), retrieved chunks with scores, latency, and token cost.

Making the internals visible is deliberate — it demonstrates the engineering, and it's what an interviewer will click first.

**Acceptance:** runs from a single command, handles errors without crashing, includes 6–8 clickable example questions covering all routes.

---

### M6 — README and failure analysis

Written for a hiring manager with 90 seconds, then a reviewer with 10 minutes.

Required sections:
1. One-paragraph what and why, with the headline metrics up front
2. Architecture diagram (Mermaid is fine)
3. Metrics table with methodology link
4. Chunking / k ablation comparison
5. **Failure analysis** — categories of questions the system gets wrong, with real examples and hypotheses about why
6. What you'd do next with more time
7. Setup instructions that actually work on a clean machine
8. Data sources and licensing note

Section 5 is the one that signals seniority. Most portfolio READMEs claim everything works. Naming your system's limits precisely reads as engineering judgment.

**Acceptance:** a peer can clone the repo and reach a working demo using only the README.

---

## 5. Guardrails

- Never commit secrets. `.env.example` documents required variables with dummy values.
- Never commit raw NFIRS extracts or any file over 50 MB. If data can't be redistributed, document how to obtain it.
- No copyrighted standards text in the repo.
- Cap eval runs by default (configurable) so a single command can't burn an unexpected amount of API spend. Log cumulative cost per run.
- All committed metrics must come from a real, reproducible run.

---

## 6. Resume framing

After M6, the project earns roughly this shape of bullet — with real numbers substituted:

> **FireSight — Hybrid RAG for Fire Department Benchmarking** · Python, DuckDB, ChromaDB, Ragas
> Built a retrieval system routing natural-language queries across structured NFIRS incident data (text-to-SQL) and a document corpus (vector retrieval), serving benchmarking comparisons across 1,100+ departments. Evaluated on a 50-question hand-labeled golden set: __% routing accuracy, __% SQL execution accuracy, Recall@5 of __, __% answer faithfulness, p95 latency __s at $__ per query.

Fill the blanks only with measured values. If a number is weak, report it anyway and explain the failure mode — that conversation goes better in an interview than a suspiciously perfect table.

---

## 7. Command reference

```bash
uv sync                                          # install
cp .env.example .env                             # then fill in keys

uv run python -m firesight.ingest.structured     # build DuckDB
uv run python -m firesight.ingest.documents      # chunk + embed corpus

uv run python -m firesight.eval.run --all        # full eval suite
uv run python -m firesight.eval.run --suite sql  # single suite

uv run streamlit run src/firesight/app/main.py   # demo

uv run pytest                                    # tests
uv run ruff check --fix .                        # lint
```

---

## 8. Before going public

- [ ] Secret scan the full git history, not just the working tree (`gitleaks detect` or equivalent)
- [ ] Confirm no raw data or copyrighted text committed
- [ ] Verify setup instructions on a clean clone
- [ ] Add a LICENSE (MIT is fine)
- [ ] **Separately: scrub the credentials still sitting in `db.py` in the PathCheck repo before that one goes public**
