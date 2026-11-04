"""
Execute every reference SQL in eval/structured_questions.jsonl and record its
result as the verified answer.

This establishes the ground truth the M1 acceptance numbers are scored against,
and it needs no API key -- it exercises the database and the read-only guard
only. Run it before scoring the model so that a disagreement can be attributed
to the model rather than to a broken reference query.

    uv run python scripts/verify_reference_sql.py

Writes eval/reference_answers.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import REPO_ROOT  # noqa: E402
from firesight.retrieval.sql_guard import execute  # noqa: E402

QUESTIONS = REPO_ROOT / "eval" / "structured_questions.jsonl"
OUT = REPO_ROOT / "eval" / "reference_answers.json"


def main() -> None:
    lines = QUESTIONS.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    out = []
    failures = 0

    for q in rows:
        rec = {
            "id": q["id"],
            "question": q["question"],
            "difficulty": q["difficulty"],
            "category": q["category"],
            "reference_sql": q["reference_sql"],
        }
        try:
            res = execute(q["reference_sql"])
            rec["ok"] = True
            rec["columns"] = res.columns
            rec["rows"] = [[str(v) if v is not None else None for v in r] for r in res.rows]
            rec["row_count"] = res.row_count
            rec["elapsed_ms"] = round(res.elapsed_ms, 1)
            status = "OK"
            preview = rec["rows"][0] if rec["rows"] else "(no rows)"
        except Exception as e:  # noqa: BLE001 - reported, not raised
            failures += 1
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
            status = "FAIL"
            preview = rec["error"]

        if q.get("notes"):
            rec["notes"] = q["notes"]
        out.append(rec)
        print(f"  [{status}] {q['id']} {q['question'][:58]:<58} -> {preview}")

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    ok = len(out) - failures
    print(f"\n{ok}/{len(out)} reference queries executed. Wrote {OUT}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
