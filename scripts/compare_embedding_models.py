"""
bge-base vs bge-small: retrieval quality against latency and index size.

    uv run python scripts/compare_embedding_models.py

Runs the labelled golden set through every arm (model x chunk config x
rerank) and reports Recall@5 and MRR with intervals, plus the two costs a
bigger encoder imposes: query latency and on-disk index size.

Both models are reported regardless of which wins. A larger encoder is only
worth it if the quality gain clears its interval AND the latency is tolerable,
and that is a judgment the numbers should inform rather than settle.

Collections are scoped by model (see documents.embed_slug) because embeddings
from different models are not comparable and must not share an index.

Needs no API key.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import REPO_ROOT, settings  # noqa: E402
from firesight.eval.retrieval_suite import (  # noqa: E402
    load_questions,
    question_origin,
    score_question,
)
from firesight.eval.stats import from_bools, mean_ci  # noqa: E402
from firesight.ingest.documents import embed_slug  # noqa: E402

MODELS = ["BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5"]
OUT = REPO_ROOT / "eval" / "results" / "embedding_ab.json"


def index_size_bytes() -> int:
    """Approximate on-disk cost: the Chroma segment dirs plus a share of sqlite."""
    root = settings.chroma_path
    if not root.exists():
        return 0
    # Segment directories are opaque UUIDs, so total store size is reported
    # and attributed per model by chunk count instead of guessing.
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def run_arm(questions, model: str, config: str, rerank: bool, k: int) -> dict:
    import firesight.retrieval.vector_store as vs

    # Point every cached loader at this model.
    object.__setattr__(settings, "embed_model", model)
    vs._embedder.cache_clear()
    vs._collection.cache_clear()

    scores, lats = [], []
    for q in questions:
        t0 = time.perf_counter()
        hits = vs.search(q["question"], k=k, rerank=rerank, config=config)
        lats.append((time.perf_counter() - t0) * 1000)
        scores.append(score_question(q, hits, k))

    lats.sort()
    n = len(scores)
    by_origin = {}
    for o in sorted({question_origin(q) for q in questions}):
        rows = [s for s, q in zip(scores, questions, strict=True) if question_origin(q) == o]
        if rows:
            by_origin[o] = {
                "n": len(rows),
                "recall_at_k": round(statistics.mean(r.recall_at_k for r in rows), 4),
                "mrr": round(statistics.mean(r.reciprocal_rank for r in rows), 4),
            }

    return {
        "model": model,
        "slug": embed_slug(model),
        "config": config,
        "rerank": rerank,
        "n": n,
        "recall_ci": mean_ci([s.recall_at_k for s in scores]).as_dict(),
        "mrr_ci": mean_ci([s.reciprocal_rank for s in scores]).as_dict(),
        "hit_rate_ci": from_bools(s.hit for s in scores).as_dict(),
        "answer_present_ci": from_bools(s.answer_present for s in scores).as_dict(),
        "latency_p50_ms": round(lats[n // 2], 1),
        "latency_p95_ms": round(lats[max(0, int(n * 0.95) - 1)], 1),
        "by_origin": by_origin,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--configs", default="default,small")
    p.add_argument("--no-rerank", action="store_true")
    args = p.parse_args()

    questions = load_questions()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    original = settings.embed_model
    arms = []

    try:
        for model in MODELS:
            for config in configs:
                for rerank in ([False] if args.no_rerank else [False, True]):
                    label = f"{model.rsplit('/', 1)[-1]} / {config}{' +rr' if rerank else ''}"
                    print(f"  {label} ...", flush=True)
                    try:
                        arms.append(run_arm(questions, model, config, rerank, args.k))
                    except Exception as e:  # noqa: BLE001
                        print(f"    ! failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
    finally:
        object.__setattr__(settings, "embed_model", original)

    store_bytes = index_size_bytes()
    report = {
        "n_questions": len(questions),
        "k": args.k,
        "store_total_bytes": store_bytes,
        "arms": arms,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    header = (
        f"{'model / arm':<34}{'Recall@k (95% CI)':<24}"
        f"{'MRR (95% CI)':<24}{'p50 ms':>8}"
    )
    print("\n" + header)
    print("-" * len(header))
    for a in arms:
        r, m = a["recall_ci"], a["mrr_ci"]
        name = f"{a['model'].rsplit('/', 1)[-1]} / {a['config']}"
        if a["rerank"]:
            name += " +rr"
        recall = f"{r['mean']:.3f} [{r['ci_low']:.3f}, {r['ci_high']:.3f}]"
        mrr = f"{m['mean']:.3f} [{m['ci_low']:.3f}, {m['ci_high']:.3f}]"
        print(f"{name:<34}{recall:<24}{mrr:<24}{a['latency_p50_ms']:>8.0f}")

    print(f"\nChroma store on disk (all models, all configs): {store_bytes / 1e6:.0f} MB")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
