"""
Text-to-SQL: question -> SQL -> validated execution -> answer, with the query
shown.

The generated SQL is always surfaced. For structured answers it *is* the
citation: a reader can copy it, run it, and check the number themselves.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from firesight.config import settings
from firesight.generation.llm import LLMError, complete
from firesight.retrieval.schema import build_prompt
from firesight.retrieval.sql_guard import (
    SQLResult,
    SQLTimeoutError,
    SQLValidationError,
    execute,
)

SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class Attempt:
    sql_raw: str
    sql_executed: str | None = None
    error: str | None = None
    ok: bool = False


@dataclass
class SQLAnswer:
    """Everything needed to display, cite, audit and score one answer."""

    question: str
    answered: bool
    sql: str | None = None
    result: SQLResult | None = None
    failure_reason: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    def answer_text(self) -> str:
        if not self.answered or self.result is None:
            return (
                "I couldn't answer that from the structured data. "
                f"({self.failure_reason})"
            )
        return self.result.as_markdown()


def extract_sql(text: str) -> str:
    """Pull SQL out of the model's reply, tolerating a missing code fence."""
    blocks = SQL_BLOCK.findall(text or "")
    if blocks:
        return blocks[0].strip()
    # No fence: assume the whole reply is the query.
    return (text or "").strip()


def ask(question: str, *, max_retries: int = 1) -> SQLAnswer:
    """
    Answer `question` with SQL.

    One retry on failure, with the error message fed back to the model. After
    that, fail honestly rather than guessing.
    """
    t0 = time.perf_counter()
    ans = SQLAnswer(question=question, answered=False)
    feedback: str | None = None

    for _ in range(max_retries + 1):
        try:
            reply = complete(build_prompt(question, feedback))
        except LLMError as e:
            ans.failure_reason = f"model call failed: {e}"
            ans.latency_ms = (time.perf_counter() - t0) * 1000
            return ans

        ans.input_tokens += reply.input_tokens
        ans.output_tokens += reply.output_tokens
        ans.cost_usd += reply.cost_usd

        sql_raw = extract_sql(reply.text)
        attempt = Attempt(sql_raw=sql_raw)
        ans.attempts.append(attempt)

        try:
            res = execute(sql_raw)
        except SQLValidationError as e:
            attempt.error = f"rejected by read-only validation: {e}"
            feedback = str(e)
            continue
        except SQLTimeoutError as e:
            attempt.error = str(e)
            feedback = f"{e}. Make the query cheaper."
            continue
        except Exception as e:  # noqa: BLE001 - DB errors are fed back verbatim
            attempt.error = f"execution error: {e}"
            feedback = str(e)
            continue

        attempt.sql_executed = res.sql
        attempt.ok = True
        ans.answered = True
        ans.sql = res.sql
        ans.result = res
        break

    if not ans.answered:
        last = ans.attempts[-1].error if ans.attempts else "no attempt made"
        ans.failure_reason = last

    ans.latency_ms = (time.perf_counter() - t0) * 1000
    return ans


def main() -> None:
    """`python -m firesight.retrieval.sql_agent "your question"`"""
    import sys

    if len(sys.argv) < 2:
        sys.exit('usage: python -m firesight.retrieval.sql_agent "question"')
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        sys.exit(
            "No API key set. Put ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env.\n"
            "To check the database without a model, use scripts/verify_reference_sql.py."
        )

    ans = ask(" ".join(sys.argv[1:]))
    print(f"\nQ: {ans.question}\n")
    if ans.sql:
        print(f"SQL ({ans.n_attempts} attempt(s)):\n{ans.sql}\n")
    print(ans.answer_text())
    print(
        f"\n{ans.latency_ms:.0f} ms | {ans.input_tokens} in / {ans.output_tokens} out "
        f"| ${ans.cost_usd:.5f} | model {settings.llm_model}"
    )


if __name__ == "__main__":
    main()
