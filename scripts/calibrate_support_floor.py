"""
Calibrate the retrieval support floor that drives the "I don't know" path.

    uv run python scripts/calibrate_support_floor.py

Compares top-1 similarity for the labelled in-corpus questions against a set
of deliberately out-of-corpus questions, and reports the floor that separates
them.

WHY THIS EXISTS. The floor was originally guessed at 0.45, which turned out to
admit every out-of-corpus question tested -- "What is the capital of Mongolia?"
scores 0.529 against this corpus. bge-small-en-v1.5 compresses cosine
similarity into a narrow high band, so an eyeballed threshold is worthless.
The floor is a measured parameter and it is model-specific: changing
FIRESIGHT_EMBED_MODEL invalidates it and this script must be re-run.

Needs no API key.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import REPO_ROOT, settings  # noqa: E402
from firesight.retrieval.vector_store import search  # noqa: E402

IN_Q = REPO_ROOT / "eval" / "document_questions.jsonl"
OUT_Q = REPO_ROOT / "eval" / "out_of_corpus_questions.jsonl"
REPORT = REPO_ROOT / "eval" / "support_floor_calibration.json"


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def top_scores(questions: list[dict], config: str) -> list[float]:
    out = []
    for q in questions:
        hits = search(q["question"], k=5, config=config, rerank=False)
        out.append(round(max((h.score for h in hits), default=0.0), 4))
    return out


def main() -> None:
    config = "small"
    inside = _load(IN_Q)
    outside = _load(OUT_Q)

    a = top_scores(inside, config)
    b = top_scores(outside, config)

    lo_in, hi_out = min(a), max(b)
    separated = lo_in > hi_out
    # Midpoint of the gap, leaving margin on both sides.
    recommended = round((lo_in + hi_out) / 2, 2) if separated else None

    print(f"embedding model : {settings.embed_model}")
    print(f"collection      : firesight_docs_{config}")
    print(
        f"\nIN-CORPUS  n={len(a)}  min={min(a):.3f} "
        f"median={statistics.median(a):.3f} max={max(a):.3f}"
    )
    print(
        f"OUT-CORPUS n={len(b)}  min={min(b):.3f} "
        f"median={statistics.median(b):.3f} max={max(b):.3f}"
    )
    print(f"\ngap: in-corpus floor {lo_in:.3f} vs out-of-corpus ceiling {hi_out:.3f}")

    print("\n  floor   out-admitted   in-refused")
    grid = {}
    for f in [round(x / 100, 2) for x in range(45, 85, 5)]:
        fp = sum(1 for x in b if x >= f)
        fn = sum(1 for x in a if x < f)
        grid[f] = {"out_admitted": fp, "in_refused": fn}
        print(f"  {f:.2f}    {fp:>3}/{len(b)}         {fn:>3}/{len(a)}")

    if separated:
        print(f"\nRECOMMENDED MIN_SUPPORT_SCORE = {recommended}")
        print(f"  (currently configured: {settings.min_support_score})")
        if abs(settings.min_support_score - recommended) > 0.02:
            print("  ^ configured value is off; update FIRESIGHT_MIN_SUPPORT.")
    else:
        print(
            "\nNO CLEAN SEPARATION. In-corpus and out-of-corpus scores overlap, so a "
            "similarity floor alone cannot gate the refusal path on this corpus."
        )

    REPORT.write_text(
        json.dumps(
            {
                "embed_model": settings.embed_model,
                "collection": f"firesight_docs_{config}",
                "in_corpus_scores": a,
                "out_of_corpus_scores": b,
                "in_corpus_min": lo_in,
                "out_of_corpus_max": hi_out,
                "separated": separated,
                "recommended_floor": recommended,
                "configured_floor": settings.min_support_score,
                "grid": {str(k): v for k, v in grid.items()},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
