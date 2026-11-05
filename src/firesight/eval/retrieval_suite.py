"""
Score document retrieval, and decide whether the reranker earns its place.

    uv run python -m firesight.eval.retrieval_suite
    uv run python -m firesight.eval.retrieval_suite --k 5 --configs default,small

Runs every arm (chunk config x rerank on/off) over the same labelled
questions and reports Recall@k, MRR and hit rate for each, then states
plainly whether reranking helped.

LABELLING. Ground truth is a set of `(source_document, section)` pairs, not
chunk ids. Chunk ids are a hash of the chunking parameters, so id-based labels
would be invalidated by the very config change M4 has to measure. Sections are
stable across configs, which makes one labelled set usable by every arm.

`answer_must_contain` is scored separately as `answer_present@k` -- a stricter
check that the text actually answering the question was retrieved, not merely
a chunk from the right section.

Needs no API key: embeddings and the cross-encoder are local.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from firesight.config import REPO_ROOT, settings
from firesight.eval.stats import from_bools, mean_ci, proportion
from firesight.retrieval.vector_store import Hit, search

QUESTIONS = REPO_ROOT / "eval" / "document_questions.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

# Questions answered by project-authored material are an easier retrieval task
# than questions answered by the external USFA documents: the document is short,
# cleanly sectioned, and written in the same register as the questions. Metrics
# are reported split by origin so a headline cannot be quietly propped up by
# self-reference.
# The single project-authored corpus document. Reported as its own origin
# category so methodology retrieval is visible separately from external
# retrieval rather than pooled into one headline.
METHODOLOGY_DOCUMENTS = {"FireSight Methodology"}

# The scope boundary is corpus furniture, not an answer source. It is excluded
# from retrieval scoring and does not count toward the project-authored share.
SCOPE_DOCUMENTS = {"FireSight Corpus Scope"}


def question_origin(q: dict) -> str:
    docs = {s["source_document"] for s in q.get("relevant_sections", [])}
    docs -= SCOPE_DOCUMENTS
    if not docs:
        return "scope"
    internal = docs & METHODOLOGY_DOCUMENTS
    external = docs - METHODOLOGY_DOCUMENTS
    if internal and external:
        return "mixed"
    return "methodology" if internal else "external"


@dataclass
class QuestionScore:
    id: str
    question: str
    difficulty: str
    origin: str
    n_labelled: int
    recall_at_k: float
    reciprocal_rank: float
    hit: bool
    answer_present: bool
    first_relevant_rank: int | None
    retrieved: list[str] = field(default_factory=list)


@dataclass
class ArmResult:
    config: str
    rerank: bool
    k: int
    n_questions: int
    recall_at_k: float
    mrr: float
    hit_rate: float
    answer_present_rate: float
    latency_p50_ms: float
    latency_p95_ms: float
    by_origin: dict = field(default_factory=dict)
    recall_ci: dict = field(default_factory=dict)
    mrr_ci: dict = field(default_factory=dict)
    hit_rate_ci: dict = field(default_factory=dict)
    answer_present_ci: dict = field(default_factory=dict)
    embed_model: str = ""
    scores: list[QuestionScore] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.config}{' + rerank' if self.rerank else ''}"


def load_questions() -> list[dict]:
    if not QUESTIONS.exists():
        raise SystemExit(f"missing {QUESTIONS}")
    return [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _pair(hit: Hit) -> tuple[str, str]:
    return (hit.source_document.strip(), hit.section.strip())


def _flat(text: str) -> str:
    """
    Collapse whitespace before substring matching.

    Markdown chunks keep their newlines, so a natural answer phrase that happens
    to wrap across a line would otherwise never match. Normalising both sides
    makes `answer_must_contain` depend on the words, not on where the source
    file wrapped them.
    """
    return " ".join((text or "").split()).lower()


def score_question(q: dict, hits: list[Hit], k: int) -> QuestionScore:
    labelled = {
        (str(s["source_document"]).strip(), str(s["section"]).strip())
        for s in q.get("relevant_sections", [])
    }
    needles = [_flat(s) for s in q.get("answer_must_contain", [])]

    top = hits[:k]
    found = {_pair(h) for h in top} & labelled

    first_rank = next((h.rank for h in top if _pair(h) in labelled), None)
    answer_present = any(
        all(n in _flat(h.text) for n in needles) for h in top
    ) if needles else False

    return QuestionScore(
        id=q["id"],
        question=q["question"],
        difficulty=q.get("difficulty", "?"),
        origin=question_origin(q),
        n_labelled=len(labelled),
        recall_at_k=(len(found) / len(labelled)) if labelled else 0.0,
        reciprocal_rank=(1.0 / first_rank) if first_rank else 0.0,
        hit=first_rank is not None,
        answer_present=answer_present,
        first_relevant_rank=first_rank,
        retrieved=[f"{h.rank}. {h.score:.3f} {h.citation()}" for h in top],
    )


def run_arm(questions: list[dict], config: str, rerank: bool, k: int) -> ArmResult:
    scores: list[QuestionScore] = []
    lats: list[float] = []
    for q in questions:
        t0 = time.perf_counter()
        hits = search(q["question"], k=k, rerank=rerank, config=config)
        lats.append((time.perf_counter() - t0) * 1000)
        scores.append(score_question(q, hits, k))

    lats_sorted = sorted(lats)
    n = len(scores)
    by_origin = {}
    for o in sorted({s.origin for s in scores}):
        rows = [s for s in scores if s.origin == o]
        by_origin[o] = {
            "n": len(rows),
            "recall_at_k": round(statistics.mean(r.recall_at_k for r in rows), 4),
            "mrr": round(statistics.mean(r.reciprocal_rank for r in rows), 4),
            "hit_rate": round(sum(r.hit for r in rows) / len(rows), 4),
        }
    return ArmResult(
        config=config,
        rerank=rerank,
        k=k,
        n_questions=n,
        recall_at_k=round(statistics.mean(s.recall_at_k for s in scores), 4),
        mrr=round(statistics.mean(s.reciprocal_rank for s in scores), 4),
        hit_rate=round(sum(s.hit for s in scores) / n, 4),
        answer_present_rate=round(sum(s.answer_present for s in scores) / n, 4),
        latency_p50_ms=round(lats_sorted[n // 2], 1),
        latency_p95_ms=round(lats_sorted[max(0, int(n * 0.95) - 1)], 1),
        by_origin=by_origin,
        recall_ci=mean_ci([q.recall_at_k for q in scores]).as_dict(),
        mrr_ci=mean_ci([q.reciprocal_rank for q in scores]).as_dict(),
        hit_rate_ci=from_bools(q.hit for q in scores).as_dict(),
        answer_present_ci=from_bools(q.answer_present for q in scores).as_dict(),
        embed_model=settings.embed_model,
        scores=scores,
    )


def rerank_verdict(arms: list[ArmResult]) -> dict:
    """
    Compare rerank on/off within each chunk config and state the outcome.

    Uses a PAIRED sign test on per-question reciprocal rank, because both arms
    see the same questions and comparing independent intervals throws the
    pairing away. A consistently positive mean with a non-significant sign test
    is reported as "not established" rather than "positive" -- the n=15
    measurement overstated this effect by 2-4x and the lesson was to stop
    reporting a direction as a result.
    """
    import math

    out = {}
    for cfg in sorted({a.config for a in arms}):
        base = next((a for a in arms if a.config == cfg and not a.rerank), None)
        rr = next((a for a in arms if a.config == cfg and a.rerank), None)
        if not base or not rr:
            continue
        d_recall = round(rr.recall_at_k - base.recall_at_k, 4)
        d_mrr = round(rr.mrr - base.mrr, 4)
        positive = d_recall > 0 or d_mrr > 0
        n = base.n_questions
        # One question is worth 1/n of Recall@k, so a delta smaller than that
        # is not even one question's worth of evidence.
        one_question = round(1.0 / n, 4) if n else 0.0
        questions_worth = round(d_recall / one_question, 1) if one_question else 0.0
        # Paired sign test on reciprocal rank, question by question.
        by_id = {s.id: s for s in base.scores}
        deltas = [
            s.reciprocal_rank - by_id[s.id].reciprocal_rank
            for s in rr.scores
            if s.id in by_id
        ]
        improved = sum(1 for d in deltas if d > 1e-9)
        worsened = sum(1 for d in deltas if d < -1e-9)
        discordant = improved + worsened
        p_value = None
        if discordant:
            tail = sum(math.comb(discordant, k) for k in range(min(improved, worsened) + 1))
            p_value = round(min(1.0, 2 * tail / 2**discordant), 4)

        significant = p_value is not None and p_value < 0.05
        if positive and significant:
            verdict = f"POSITIVE and significant (sign test p={p_value:.3f}, n={n})"
        elif positive:
            verdict = (
                f"directionally positive ({improved} improved / {worsened} worsened) "
                f"but NOT ESTABLISHED"
                + (f" (sign test p={p_value:.3f})" if p_value is not None else "")
                + f" at n={n}"
            )
        else:
            verdict = f"no improvement on n={n} -- candidate for removal"

        out[cfg] = {
            "recall_delta": d_recall,
            "mrr_delta": d_mrr,
            "latency_cost_ms": round(rr.latency_p50_ms - base.latency_p50_ms, 1),
            "n_questions": n,
            "one_question_worth": one_question,
            "recall_delta_in_questions": questions_worth,
            "direction": "positive" if positive else "negative or flat",
            "paired_improved": improved,
            "paired_worsened": worsened,
            "sign_test_p": p_value,
            "significant_at_05": significant,
            "verdict": verdict,
        }
    return out


def write_report(report: dict) -> tuple:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    jp = RESULTS_DIR / f"retrieval_suite_{stamp}.json"
    mp = RESULTS_DIR / f"retrieval_suite_{stamp}.md"
    jp.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Document retrieval suite",
        "",
        f"- **Run:** {report['generated_at']}",
        f"- **Embedding model:** `{report['embed_model']}`",
        f"- **Reranker:** `{report['rerank_model']}`",
        f"- **Questions:** {report['n_questions']}",
        f"- **k:** {report['k']}",
        "",
        f"- **Embedding model:** `{report['arms'][0]['embed_model']}`" if report["arms"] else "",
        "",
        "Recall@k and MRR carry normal-approximation intervals (they are means);",
        "hit rate and answer-present carry Wilson intervals (they are proportions).",
        "",
        "| Arm | Recall@k (95% CI) | MRR (95% CI) | Hit rate | Answer present | p50 ms |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for a in report["arms"]:
        r, m = a["recall_ci"], a["mrr_ci"]
        h, ap = a["hit_rate_ci"], a["answer_present_ci"]
        lines.append(
            f"| {a['config']}{' + rerank' if a['rerank'] else ''} "
            f"| {r['mean']:.3f} [{r['ci_low']:.3f}, {r['ci_high']:.3f}] "
            f"| {m['mean']:.3f} [{m['ci_low']:.3f}, {m['ci_high']:.3f}] "
            f"| {proportion(h['successes'], h['n']).fmt_short()} "
            f"| {proportion(ap['successes'], ap['n']).fmt_short()} "
            f"| {a['latency_p50_ms']:.0f} |"
        )

    lines += ["", "## By question origin", "",
              "Project-authored notes are an easier retrieval target than the external",
              "USFA documents. A headline that does not separate them is flattered.",
              "",
              "| Arm | Origin | n | Recall@k | MRR | Hit rate |",
              "| --- | --- | ---: | ---: | ---: | ---: |"]
    for a in report["arms"]:
        for o, v in a["by_origin"].items():
            lines.append(
                f"| {a['config']}{' + rerank' if a['rerank'] else ''} | {o} | {v['n']} "
                f"| {v['recall_at_k']:.3f} | {v['mrr']:.3f} | {v['hit_rate']:.3f} |"
            )

    lines += ["", "## Reranker decision", ""]
    for cfg, v in report["rerank_verdict"].items():
        lines += [
            f"**{cfg}** — {v['verdict']}",
            "",
            f"- ΔRecall@k: {v['recall_delta']:+.4f} "
            f"({v['recall_delta_in_questions']:+.1f} of {v['n_questions']} questions; "
            f"one question = {v['one_question_worth']:.3f})",
            f"- ΔMRR: {v['mrr_delta']:+.4f}",
            f"- added latency (p50): {v['latency_cost_ms']:+.1f} ms",
            f"- paired: {v['paired_improved']} improved / {v['paired_worsened']} worsened, "
            f"sign test p={v['sign_test_p']}",
            f"- significant at 0.05: {v['significant_at_05']}",
            "",
        ]

    best = report["arms"][0]
    worst_qs = [s for s in best["scores"] if not s["hit"]]
    lines += ["", f"## Misses in `{best['config']}` ({len(worst_qs)})", ""]
    if not worst_qs:
        lines.append("_None._")
    for s in worst_qs:
        lines += [
            f"### {s['id']} — {s['question']}",
            "",
            "Retrieved instead:",
            "",
            *[f"- {r}" for r in s["retrieved"]],
            "",
        ]
    mp.write_text("\n".join(lines), encoding="utf-8")
    return jp, mp


def main() -> None:
    p = argparse.ArgumentParser(description="Score document retrieval.")
    p.add_argument("--k", type=int, default=settings.top_k)
    p.add_argument("--configs", default="default,small")
    p.add_argument("--no-rerank", action="store_true", help="skip the rerank arms")
    args = p.parse_args()

    questions = load_questions()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]

    arms: list[ArmResult] = []
    for cfg in configs:
        for rerank in ([False] if args.no_rerank else [False, True]):
            label = f"{cfg}{' + rerank' if rerank else ''}"
            print(f"  running arm: {label} ...", flush=True)
            try:
                arms.append(run_arm(questions, cfg, rerank, args.k))
            except Exception as e:  # noqa: BLE001 - reported, keeps other arms alive
                print(f"    ! arm {label} failed: {e}", flush=True)

    if not arms:
        raise SystemExit("no arm completed; is the corpus ingested?")

    arms.sort(key=lambda a: (-a.recall_at_k, -a.mrr))
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": "retrieval",
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model,
        "k": args.k,
        "n_questions": len(questions),
        "arms": [asdict(a) for a in arms],
        "rerank_verdict": rerank_verdict(arms),
    }
    jp, mp = write_report(report)

    print(f"\n{'arm':<22}{'Recall@k':>10}{'MRR':>8}{'Hit':>7}{'AnsPresent':>12}{'p50 ms':>9}")
    print("-" * 70)
    for a in arms:
        print(
            f"{a.label:<22}{a.recall_at_k:>10.3f}{a.mrr:>8.3f}"
            f"{a.hit_rate:>7.3f}{a.answer_present_rate:>12.3f}{a.latency_p50_ms:>9.0f}"
        )
    print(f"\n{'arm':<22}{'origin':<10}{'n':>4}{'Recall@k':>10}{'MRR':>8}{'Hit':>7}")
    print("-" * 61)
    for a in arms:
        for o, v in a.by_origin.items():
            print(
                f"{a.label:<22}{o:<10}{v['n']:>4}{v['recall_at_k']:>10.3f}"
                f"{v['mrr']:>8.3f}{v['hit_rate']:>7.3f}"
            )

    print("\nReranker decision:")
    for cfg, v in report["rerank_verdict"].items():
        print(
            f"  {cfg:<10} ΔRecall {v['recall_delta']:+.4f}  ΔMRR {v['mrr_delta']:+.4f}"
            f"  +{v['latency_cost_ms']:.0f} ms  ->  {v['verdict']}"
        )
    print(f"\nwrote {mp}\n      {jp}")


if __name__ == "__main__":
    main()
