"""
Score answer faithfulness on the M2 document set.

    uv run python -m firesight.eval.faithfulness_suite

Faithfulness here means: does every claim in the answer rest on a retrieved
passage? An answer can be fluent, correctly cited in form, and still assert
something the passages do not support -- that is the failure mode this measures,
and it is distinct from retrieval quality (already measured) and from whether
the answer is factually true in the world (not measured, and not the claim).

Two signals, deliberately separate:

* **Faithfulness** -- judged by the model against the retrieved passages only.
  The judge never sees the question's label or the expected answer, so it
  cannot grade correctness by accident.
* **Citation validity** -- checked mechanically, not judged. Every inline
  `[document - section]` must correspond to a passage actually retrieved for
  that question. A citation to a real document that was not retrieved is a
  fabricated citation, and no LLM is needed to catch it.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from firesight.config import REPO_ROOT, settings
from firesight.eval.stats import from_bools, proportion
from firesight.generation.llm import LLMError, complete
from firesight.generation.llm import available as llm_available
from firesight.generation.synthesize import answer as answer_documents
from firesight.generation.synthesize import citation_key

QUESTIONS = REPO_ROOT / "eval" / "document_questions.jsonl"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

JUDGE_PROMPT = """You are checking whether an ANSWER is fully supported by the \
PASSAGES it was given. You are NOT checking whether the answer is true in the \
world, and you are NOT checking whether it is a good answer to the question.

Judge only this: is every factual claim in the answer stated in, or directly
entailed by, the passages?

## PASSAGES

{context}

## ANSWER

{answer}

## RULES

- A claim restating a passage is supported.
- A claim that generalises beyond the passages, adds a number not present, or
  asserts something the passages do not say is UNSUPPORTED, even if true.
- Inline citation markers like [Document - Section] are not claims; ignore them.
- Hedges ("the corpus does not say", "this is not covered") are not claims.

Return ONLY a JSON object, no prose, no code fence:

{{"total_claims": <int>, "unsupported_claims": <int>,
  "unsupported": ["<short quote>", ...], "verdict": "faithful" | "unfaithful"}}

"verdict" is "faithful" only when unsupported_claims is 0.

JSON:"""

JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class FaithScore:
    id: str
    question: str
    origin: str
    answered: bool
    refused: bool
    answer: str
    n_hits: int
    citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    citation_valid: bool = False
    has_citation: bool = False
    total_claims: int | None = None
    unsupported_claims: int | None = None
    unsupported: list[str] = field(default_factory=list)
    faithful: bool | None = None
    judge_error: str | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0


def _judge(context: str, answer_text: str) -> tuple[dict | None, str | None, float]:
    try:
        reply = complete(
            JUDGE_PROMPT.format(context=context, answer=answer_text),
            max_tokens=1500,
        )
    except LLMError as e:
        return None, f"judge call failed: {e}", 0.0
    match = JSON_OBJ.search(reply.text or "")
    if not match:
        return None, f"judge returned no JSON: {(reply.text or '')[:120]!r}", reply.cost_usd
    try:
        return json.loads(match.group(0)), None, reply.cost_usd
    except json.JSONDecodeError as e:
        return None, f"judge JSON invalid: {e}", reply.cost_usd


def run(limit: int | None, config: str, rerank: bool) -> dict:
    from firesight.eval.retrieval_suite import question_origin

    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if limit:
        questions = questions[:limit]

    scores: list[FaithScore] = []
    spend = 0.0
    t0 = time.perf_counter()

    for q in questions:
        a = answer_documents(q["question"], config=config, rerank=rerank)
        spend += a.cost_usd

        # Page-insensitive: see citation_key(). A citation naming a document
        # and section that was retrieved is valid whether or not it carries the
        # page number.
        retrieved = {citation_key(h.citation()) for h in a.hits}
        invalid = [c for c in a.citations if citation_key(c) not in retrieved]

        s = FaithScore(
            id=q["id"],
            question=q["question"],
            origin=question_origin(q),
            answered=a.answered,
            refused=a.is_refusal,
            answer=a.answer,
            n_hits=len(a.hits),
            citations=a.citations,
            invalid_citations=invalid,
            has_citation=bool(a.citations),
            citation_valid=bool(a.citations) and not invalid,
            latency_ms=round(a.latency_ms, 1),
            cost_usd=round(a.cost_usd, 6),
        )

        # Only answers get judged. A refusal makes no claims to support.
        if a.answered and a.hits:
            context = "\n\n".join(
                f"source_document: {h.source_document}\nsection: {h.section}\n"
                f"text: {h.text}"
                for h in a.hits
            )
            verdict, err, cost = _judge(context, a.answer)
            spend += cost
            s.cost_usd = round(s.cost_usd + cost, 6)
            if verdict is None:
                s.judge_error = err
            else:
                s.total_claims = verdict.get("total_claims")
                s.unsupported_claims = verdict.get("unsupported_claims")
                s.unsupported = verdict.get("unsupported") or []
                s.faithful = (verdict.get("verdict") == "faithful") and (
                    (s.unsupported_claims or 0) == 0
                )

        scores.append(s)
        mark = (
            "REFUSED"
            if s.refused
            else ("FAITHFUL" if s.faithful else ("UNFAITH" if s.faithful is False else "?"))
        )
        cite = "cite-ok" if s.citation_valid else ("NO-CITE" if not s.has_citation else "BAD-CITE")
        print(f"  [{mark:9}] [{cite:8}] {s.id} {s.question[:40]}", flush=True)

        if spend > settings.eval_max_usd:
            print(f"  ! cost cap ${settings.eval_max_usd} reached; stopping early")
            break

    judged = [s for s in scores if s.faithful is not None]
    answered = [s for s in scores if s.answered]
    lats = sorted(s.latency_ms for s in scores)
    n = len(scores)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": "faithfulness",
        "model": settings.llm_model,
        "config": config,
        "rerank": rerank,
        "n_questions": n,
        "n_answered": len(answered),
        "n_refused": sum(s.refused for s in scores),
        "n_judged": len(judged),
        "faithfulness": (
            round(sum(bool(s.faithful) for s in judged) / len(judged), 4) if judged else None
        ),
        "faithfulness_ci": from_bools(bool(s.faithful) for s in judged).as_dict(),
        "mean_unsupported_claims": (
            round(statistics.mean(s.unsupported_claims or 0 for s in judged), 3)
            if judged
            else None
        ),
        "citation_rate": (
            round(sum(s.has_citation for s in answered) / len(answered), 4) if answered else None
        ),
        "citation_validity": (
            round(sum(s.citation_valid for s in answered) / len(answered), 4)
            if answered
            else None
        ),
        "citation_rate_ci": from_bools(s.has_citation for s in answered).as_dict(),
        "citation_validity_ci": from_bools(s.citation_valid for s in answered).as_dict(),
        "judge_failures": sum(1 for s in scores if s.judge_error),
        "by_origin": {
            o: {
                "n": len([s for s in judged if s.origin == o]),
                "faithfulness": round(
                    sum(bool(s.faithful) for s in judged if s.origin == o)
                    / max(1, len([s for s in judged if s.origin == o])),
                    4,
                ),
            }
            for o in sorted({s.origin for s in judged})
        },
        "latency_p50_ms": lats[len(lats) // 2] if lats else None,
        "total_cost_usd": round(spend, 5),
        "mean_cost_usd": round(spend / n, 6) if n else None,
        "wall_clock_s": round(time.perf_counter() - t0, 1),
        "scores": [asdict(s) for s in scores],
    }


def _ci(rep: dict, key: str) -> str:
    """Render a stored Wilson interval as 'k/n = p% [lo, hi]'."""
    d = rep.get(key) or {}
    return proportion(d.get("successes", 0), d.get("n", 0)).fmt()


def write_report(rep: dict) -> tuple:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    jp = RESULTS_DIR / f"faithfulness_suite_{stamp}.json"
    mp = RESULTS_DIR / f"faithfulness_suite_{stamp}.md"
    jp.write_text(json.dumps(rep, indent=2), encoding="utf-8")

    def pct(v) -> str:
        return "n/a" if v is None else f"{v:.1%}"

    lines = [
        "# Answer faithfulness suite",
        "",
        f"- **Run:** {rep['generated_at']}",
        f"- **Model:** `{rep['model']}`  ·  **Arm:** {rep['config']}"
        f"{' + rerank' if rep['rerank'] else ''}",
        f"- **Questions:** {rep['n_questions']} "
        f"({rep['n_answered']} answered, {rep['n_refused']} refused, "
        f"{rep['n_judged']} judged)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Faithfulness (zero unsupported claims) | {_ci(rep, 'faithfulness_ci')} |",
        f"| Mean unsupported claims per answer | {rep['mean_unsupported_claims']} |",
        f"| Citation rate (any citation) | {_ci(rep, 'citation_rate_ci')} |",
        f"| Citation validity, page-insensitive | {_ci(rep, 'citation_validity_ci')} |",
        f"| Judge failures | {rep['judge_failures']} |",
        f"| Latency p50 | {rep['latency_p50_ms']:.0f} ms |",
        f"| Cost | ${rep['total_cost_usd']:.5f} total, "
        f"${rep['mean_cost_usd']:.5f} per question |",
        "",
        "## By question origin",
        "",
        "| Origin | n judged | Faithfulness |",
        "| --- | ---: | ---: |",
    ]
    for o, v in rep["by_origin"].items():
        lines.append(f"| {o} | {v['n']} | {v['faithfulness']:.1%} |")

    bad = [s for s in rep["scores"] if s["faithful"] is False or s["invalid_citations"]]
    lines += ["", f"## Unfaithful answers and fabricated citations ({len(bad)})", ""]
    if not bad:
        lines.append("_None._")
    for s in bad:
        lines += [
            f"### {s['id']} — {s['question']}",
            "",
            f"- unsupported claims: {s['unsupported_claims']} of {s['total_claims']}",
        ]
        if s["unsupported"]:
            lines += [f"  - {u}" for u in s["unsupported"]]
        if s["invalid_citations"]:
            lines.append(f"- **citations not in retrieved set:** {s['invalid_citations']}")
        lines += ["", "```", s["answer"][:700], "```", ""]

    mp.write_text("\n".join(lines), encoding="utf-8")
    return jp, mp


def main() -> None:
    p = argparse.ArgumentParser(description="Score answer faithfulness.")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--config", default="small")
    p.add_argument("--rerank", action="store_true")
    args = p.parse_args()

    if not llm_available():
        raise SystemExit(
            f"No API key for provider {settings.llm_provider!r}. Set it in .env.\n"
            "Nothing was scored, so no report was written."
        )

    rep = run(args.limit, args.config, args.rerank)
    jp, mp = write_report(rep)
    print(f"\nfaithfulness      : {rep['faithfulness']:.1%} of {rep['n_judged']} judged")
    print(f"citation rate     : {rep['citation_rate']:.1%}")
    print(f"citation validity : {rep['citation_validity']:.1%}")
    print(f"refused           : {rep['n_refused']}/{rep['n_questions']}")
    print(f"spend             : ${rep['total_cost_usd']:.4f}")
    print(f"\nwrote {mp}\n      {jp}")


if __name__ == "__main__":
    main()
