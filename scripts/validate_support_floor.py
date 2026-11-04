"""
Validate the refusal gate OUT OF SAMPLE, and compare two gate signals.

    uv run python scripts/validate_support_floor.py

The 0.70 floor was fitted on eval/document_questions.jsonl and
eval/out_of_corpus_questions.jsonl, so 12/12 and 0/15 on those sets are
in-sample by construction and prove nothing about generalization. This script
scores the SAME floor against eval/heldout_questions.jsonl -- 8 in-corpus and
10 out-of-corpus questions used in no calibration.

It also tests the cross-encoder score as the gate signal instead of
bi-encoder cosine. If the cross-encoder separates the two populations more
cleanly, the reranker has a justification on the refusal path that is
independent of its retrieval gain.

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

CONFIG = "small"
REPORT = REPO_ROOT / "eval" / "support_floor_validation.json"


def _load(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (REPO_ROOT / "eval" / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def bi_encoder_top(question: str) -> float:
    hits = search(question, k=5, config=CONFIG, rerank=False)
    return max((h.score for h in hits), default=0.0)


def cross_encoder_top(question: str) -> float:
    """Best cross-encoder score over the same candidate pool the gate would see."""
    hits = search(question, k=5, config=CONFIG, rerank=True)
    return max((h.score for h in hits), default=float("-inf"))


def describe(name: str, scores: list[float]) -> dict:
    s = sorted(scores)
    return {
        "set": name,
        "n": len(s),
        "min": round(s[0], 4),
        "median": round(statistics.median(s), 4),
        "max": round(s[-1], 4),
        "scores": [round(x, 4) for x in s],
    }


def separation(inside: list[float], outside: list[float]) -> dict:
    lo_in, hi_out = min(inside), max(outside)
    return {
        "in_corpus_min": round(lo_in, 4),
        "out_of_corpus_max": round(hi_out, 4),
        "margin": round(lo_in - hi_out, 4),
        "separated": lo_in > hi_out,
        "midpoint": round((lo_in + hi_out) / 2, 4) if lo_in > hi_out else None,
    }


def gate_at(floor: float, inside: list[float], outside: list[float]) -> dict:
    admitted = sum(1 for x in outside if x >= floor)
    refused = sum(1 for x in inside if x < floor)
    return {
        "floor": floor,
        "out_of_corpus_admitted": admitted,
        "out_of_corpus_total": len(outside),
        "in_corpus_wrongly_refused": refused,
        "in_corpus_total": len(inside),
    }


def main() -> None:
    calib_in = [q["question"] for q in _load("document_questions.jsonl")]
    calib_out = [q["question"] for q in _load("out_of_corpus_questions.jsonl")]
    held = _load("heldout_questions.jsonl")
    held_in = [q["question"] for q in held if q["kind"] == "in_corpus"]
    held_out = [q["question"] for q in held if q["kind"] == "out_of_corpus"]

    floor = settings.min_support_score
    out: dict = {
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "collection": f"firesight_docs_{CONFIG}",
        "configured_floor": floor,
    }

    print(f"configured floor = {floor}   (fitted on the calibration sets)\n")

    for signal, fn in (("bi_encoder_cosine", bi_encoder_top), ("cross_encoder", cross_encoder_top)):
        print(f"{'=' * 76}\nSIGNAL: {signal}\n{'=' * 76}")
        ci = [fn(q) for q in calib_in]
        co = [fn(q) for q in calib_out]
        hi = [fn(q) for q in held_in]
        ho = [fn(q) for q in held_out]

        block = {
            "calibration_in": describe("calibration in-corpus", ci),
            "calibration_out": describe("calibration out-of-corpus", co),
            "heldout_in": describe("held-out in-corpus", hi),
            "heldout_out": describe("held-out out-of-corpus", ho),
            "separation_calibration": separation(ci, co),
            "separation_heldout": separation(hi, ho),
            "separation_pooled": separation(ci + hi, co + ho),
        }
        for key in ("calibration_in", "calibration_out", "heldout_in", "heldout_out"):
            d = block[key]
            print(
                f"  {d['set']:<28} n={d['n']:<3} min={d['min']:>8.3f} "
                f"median={d['median']:>8.3f} max={d['max']:>8.3f}"
            )
        for key, label in (
            ("separation_calibration", "calibration"),
            ("separation_heldout", "HELD-OUT"),
            ("separation_pooled", "pooled"),
        ):
            s = block[key]
            print(
                f"  {label:<13} in-min {s['in_corpus_min']:>8.3f} vs out-max "
                f"{s['out_of_corpus_max']:>8.3f}  margin {s['margin']:>+8.3f}  "
                f"separated={s['separated']}"
            )

        if signal == "bi_encoder_cosine":
            block["gate_calibration"] = gate_at(floor, ci, co)
            block["gate_heldout"] = gate_at(floor, hi, ho)
            g = block["gate_heldout"]
            print(
                f"\n  GATE AT {floor} ON HELD-OUT: "
                f"out-of-corpus admitted {g['out_of_corpus_admitted']}/{g['out_of_corpus_total']}, "
                f"in-corpus wrongly refused {g['in_corpus_wrongly_refused']}/{g['in_corpus_total']}"
            )
        out[signal] = block
        print()

    bi = out["bi_encoder_cosine"]["separation_pooled"]["margin"]
    ce = out["cross_encoder"]["separation_pooled"]["margin"]
    print(f"{'=' * 76}\nWHICH SIGNAL GATES BETTER (pooled margin)\n{'=' * 76}")
    print(f"  bi-encoder cosine : margin {bi:+.3f}")
    print(f"  cross-encoder     : margin {ce:+.3f}")
    out["better_gate_signal"] = "cross_encoder" if ce > bi else "bi_encoder_cosine"
    print(f"  -> {out['better_gate_signal']} separates more cleanly")

    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {REPORT}")


if __name__ == "__main__":
    main()
