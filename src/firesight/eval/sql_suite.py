"""
Score the text-to-SQL agent against eval/structured_questions.jsonl.

    uv run python -m firesight.eval.sql_suite

Reports two numbers separately, as the spec requires:

  * execution accuracy -- the generated SQL ran without error
  * result accuracy    -- the generated SQL returned the verified answer

A query can execute perfectly and still be wrong, so collapsing these into one
figure would hide the failure mode that actually matters.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from firesight.config import REPO_ROOT, settings
from firesight.generation.llm import available as llm_available
from firesight.retrieval.sql_agent import ask

QUESTIONS = REPO_ROOT / "eval" / "structured_questions.jsonl"
REFERENCE = REPO_ROOT / "eval" / "reference_answers.json"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

NUMERIC_TOLERANCE = 0.01


@dataclass
class Score:
    id: str
    question: str
    difficulty: str
    category: str
    executed: bool
    result_match: bool
    answer_contained: bool
    n_attempts: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    generated_sql: str | None = None
    failure_reason: str | None = None
    mismatch_detail: str | None = None


def _norm(v) -> object:
    """Compare 13 and 13.0 and '13.0' as equal; leave everything else as text."""
    if v is None:
        return None
    s = str(v).strip()
    try:
        f = float(s)
        return round(f / NUMERIC_TOLERANCE) * NUMERIC_TOLERANCE
    except ValueError:
        return s.casefold()


def answer_contained(expected: list[list], actual: list[tuple]) -> bool:
    """
    Looser, and arguably the more faithful measure: does the returned result
    CONTAIN the verified answer?

    Strict row-multiset equality marks a query wrong for selecting extra
    context columns. Measured on this set, that was most of the apparent
    failures -- asked for a P90, the model returned the P90 *and* the sample
    size, which is a better answer than the reference and scored as wrong.

    Both numbers are reported, because the looser one can be fooled: a query
    returning many columns may contain the answer incidentally.
    """
    exp_rows = [{_norm(c) for c in r} for r in expected]
    act_rows = [{_norm(c) for c in r} for r in actual]
    if len(act_rows) < len(exp_rows):
        return False
    unused = list(act_rows)
    for want in exp_rows:
        hit = next((i for i, got in enumerate(unused) if want <= got), None)
        if hit is None:
            return False
        unused.pop(hit)
    return True


def results_match(expected: list[list], actual: list[tuple]) -> tuple[bool, str | None]:
    """
    Row-set comparison, order-insensitive.

    Column order and column naming are not scored -- two correct queries can
    legitimately name or order columns differently. Row multiset and cell
    values are scored.
    """
    exp_rows = sorted(tuple(_norm(c) for c in r) for r in expected)
    act_rows = sorted(tuple(_norm(c) for c in r) for r in actual)

    if exp_rows == act_rows:
        return True, None
    if len(exp_rows) != len(act_rows):
        return False, f"expected {len(exp_rows)} row(s), got {len(act_rows)}"

    # Same shape: report the first differing row for the failure analysis.
    for e, a in zip(exp_rows, act_rows, strict=True):
        if e != a:
            return False, f"expected {e!r}, got {a!r}"
    return False, "rows differ"


def run(limit: int | None = None) -> dict:
    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    raw = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        reference = {r["id"]: r for r in raw["answers"]}
        from firesight.eval.fingerprint import check_against

        drift = check_against(raw.get("db_fingerprint"))
        if drift:
            raise SystemExit(
                "Reference answers are STALE -- the structured store has changed "
                f"since they were generated: {drift}.\n"
                "Run scripts/verify_reference_sql.py again before scoring, or the "
                "model will be marked wrong for returning the correct figures."
            )
    else:
        reference = {r["id"]: r for r in raw}

    missing = [q["id"] for q in questions if q["id"] not in reference]
    if missing:
        raise SystemExit(
            f"No verified answer for {missing}. "
            "Run scripts/verify_reference_sql.py first."
        )

    budget = limit if limit is not None else settings.eval_max_questions
    questions = questions[:budget]

    scores: list[Score] = []
    t0 = time.perf_counter()

    for q in questions:
        ref = reference[q["id"]]
        ans = ask(q["question"])

        match, detail = False, None
        contained = False
        if ans.answered and ans.result is not None:
            if ref.get("ok"):
                match, detail = results_match(ref["rows"], ans.result.rows)
                contained = answer_contained(ref["rows"], ans.result.rows)
            else:
                detail = "reference query itself failed; cannot score"

        scores.append(
            Score(
                id=q["id"],
                question=q["question"],
                difficulty=q["difficulty"],
                category=q["category"],
                executed=ans.answered,
                result_match=match,
                answer_contained=contained,
                n_attempts=ans.n_attempts,
                latency_ms=round(ans.latency_ms, 1),
                input_tokens=ans.input_tokens,
                output_tokens=ans.output_tokens,
                cost_usd=round(ans.cost_usd, 6),
                generated_sql=ans.sql,
                failure_reason=ans.failure_reason,
                mismatch_detail=detail,
            )
        )
        print(
            f"  [{'PASS' if match else 'FAIL'}] {q['id']} "
            f"exec={'Y' if ans.answered else 'N'} match={'Y' if match else 'N'} "
            f"{ans.latency_ms:.0f}ms  {q['question'][:50]}"
        )
        if ans.cost_usd and sum(s.cost_usd for s in scores) > settings.eval_max_usd:
            print(f"  ! cost cap ${settings.eval_max_usd} reached; stopping early")
            break

    n = len(scores)
    lat = sorted(s.latency_ms for s in scores)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": "sql",
        "model": settings.llm_model,
        "provider": settings.llm_provider,
        "n_questions": n,
        "execution_accuracy": round(sum(s.executed for s in scores) / n, 4) if n else None,
        "result_accuracy": round(sum(s.result_match for s in scores) / n, 4) if n else None,
        "answer_containment_accuracy": (
            round(sum(s.answer_contained for s in scores) / n, 4) if n else None
        ),
        "retry_rate": round(sum(s.n_attempts > 1 for s in scores) / n, 4) if n else None,
        "latency_p50_ms": lat[len(lat) // 2] if lat else None,
        "latency_p95_ms": lat[max(0, int(len(lat) * 0.95) - 1)] if lat else None,
        "mean_input_tokens": round(sum(s.input_tokens for s in scores) / n, 1) if n else None,
        "mean_output_tokens": round(sum(s.output_tokens for s in scores) / n, 1) if n else None,
        "total_cost_usd": round(sum(s.cost_usd for s in scores), 5),
        "mean_cost_usd": round(sum(s.cost_usd for s in scores) / n, 6) if n else None,
        "wall_clock_s": round(time.perf_counter() - t0, 1),
        "by_difficulty": {
            d: {
                "n": len([s for s in scores if s.difficulty == d]),
                "result_accuracy": round(
                    sum(s.result_match for s in scores if s.difficulty == d)
                    / len([s for s in scores if s.difficulty == d]),
                    4,
                ),
            }
            for d in sorted({s.difficulty for s in scores})
        },
        "scores": [asdict(s) for s in scores],
    }
    return report


def write_report(report: dict) -> tuple:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS_DIR / f"sql_suite_{stamp}.json"
    md_path = RESULTS_DIR / f"sql_suite_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Text-to-SQL suite",
        "",
        f"- **Run:** {report['generated_at']}",
        f"- **Model:** `{report['model']}` ({report['provider']})",
        f"- **Questions:** {report['n_questions']}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Execution accuracy | {report['execution_accuracy']:.1%} |",
        f"| Result accuracy (exact row match) | {report['result_accuracy']:.1%} |",
        f"| Answer containment (reference values present) "
        f"| {report['answer_containment_accuracy']:.1%} |",
        f"| Retry rate | {report['retry_rate']:.1%} |",
        f"| Latency p50 | {report['latency_p50_ms']:.0f} ms |",
        f"| Latency p95 | {report['latency_p95_ms']:.0f} ms |",
        f"| Mean cost / query | ${report['mean_cost_usd']:.5f} |",
        f"| Total run cost | ${report['total_cost_usd']:.5f} |",
        "",
        "## By difficulty",
        "",
        "| Difficulty | n | Result accuracy |",
        "| --- | --- | --- |",
    ]
    for d, v in report["by_difficulty"].items():
        lines.append(f"| {d} | {v['n']} | {v['result_accuracy']:.1%} |")

    failures = [s for s in report["scores"] if not s["result_match"]]
    lines += ["", f"## Failures ({len(failures)})", ""]
    if not failures:
        lines.append("_None._")
    for s in failures:
        lines += [
            f"### {s['id']} — {s['question']}",
            "",
            f"- executed: {s['executed']}",
            f"- reason: {s['failure_reason'] or s['mismatch_detail']}",
            "",
            "```sql",
            (s["generated_sql"] or "(no SQL produced)"),
            "```",
            "",
        ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    p = argparse.ArgumentParser(description="Score the text-to-SQL agent.")
    p.add_argument("--limit", type=int, default=None, help="cap questions scored")
    args = p.parse_args()

    if not llm_available():
        raise SystemExit(
            "No API key for provider "
            f"{settings.llm_provider!r}. Set it in .env and re-run.\n"
            "Nothing was scored, so no report was written -- a metrics file "
            "without a real run would be worse than no file."
        )

    report = run(args.limit)
    json_path, md_path = write_report(report)
    print(f"\nexecution accuracy : {report['execution_accuracy']:.1%}")
    print(f"result accuracy    : {report['result_accuracy']:.1%}")
    print(f"\nwrote {md_path}\n      {json_path}")


if __name__ == "__main__":
    main()
