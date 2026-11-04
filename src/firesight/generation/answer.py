"""
End-to-end answering: route the question, then answer on the chosen path.

    uv run python -m firesight.generation.answer "your question"

Four paths:

  structured   -> text-to-SQL; the executed SQL is the citation
  unstructured -> vector retrieval; document + section are the citations
  hybrid       -> BOTH retrievers, synthesised into one answer carrying both
                  citation types
  out_of_scope -> refused, citing the scope-boundary document

The out_of_scope path fetches the scope document deliberately rather than
relying on it ranking. Measured: it does not reach the top 5 for "What
sprinkler pressure does NFPA 13 require?" -- the similarity blindness that lets
that question past the support floor also keeps the document explaining the
refusal out of the results. So a refusal asks for the boundary by name.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from firesight.config import settings
from firesight.generation.llm import LLMError, complete
from firesight.generation.synthesize import DocAnswer, extract_citations
from firesight.generation.synthesize import answer as answer_documents
from firesight.retrieval.router import ExclusionReason, Route, RoutingResult
from firesight.retrieval.router import route as classify
from firesight.retrieval.sql_agent import SQLAnswer
from firesight.retrieval.sql_agent import ask as ask_sql
from firesight.retrieval.vector_store import Hit, scope_context, search


@dataclass
class Citation:
    kind: str  # "sql" | "document" | "scope"
    text: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.text}"


@dataclass
class Answer:
    question: str
    routing: RoutingResult
    answered: bool
    text: str
    citations: list[Citation] = field(default_factory=list)
    sql: str | None = None
    hits: list[Hit] = field(default_factory=list)
    refusal_reason: str | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def route(self) -> Route | None:
        return self.routing.route

    @property
    def citation_kinds(self) -> set[str]:
        return {c.kind for c in self.citations}


HYBRID_PROMPT = """You answer questions about fire-service data using BOTH a \
database result and retrieved documentation. Your answer must rest on both.

## DATABASE RESULT

The following SQL was executed against the structured store:

```sql
{sql}
```

It returned:

{table}

## RETRIEVED PASSAGES

{context}

## RULES

1. Use ONLY the database result and the passages above. Add no outside facts.
2. Cite EVERY claim. Two citation forms, and your answer must use both:
   - for anything from the database, cite [sql]
   - for anything from the documents, cite [source_document — section],
     copying those values exactly as given above
3. If the database result and the documents disagree, say so and cite both.
4. NFPA standards are copyrighted and absent from the corpus. You may name
   which standard governs a topic; you must not state its thresholds. If the
   question needs a threshold, say the corpus does not contain it.
5. Units: response times are MINUTES; compliance rates are PERCENTAGES.
6. Be concise. Three or four sentences.

## QUESTION

{question}

## ANSWER"""


REFUSAL_PROMPT = """A question has been classified as outside this system's \
scope. Write the refusal.

## WHY IT IS OUT OF SCOPE

{reason_label}: {reason_text}

## THE SCOPE BOUNDARY, QUOTED FROM THE PROJECT'S OWN SCOPE DOCUMENT

{context}

## RULES

1. State plainly that the question cannot be answered from this corpus, and name
   the specific boundary it hit.
2. Cite the scope document as [source_document — section], copying those values
   exactly as given above.
3. Where possible, say what the system COULD answer instead, concretely.
4. Do NOT state any NFPA threshold, requirement or figure, even if you know it.
   Naming which standard governs the topic is fine.
5. Two or three sentences. No apology beyond a brief one.

## QUESTION

{question}

## REFUSAL"""


REASON_LABELS = {
    ExclusionReason.NFPA_STANDARD: (
        "Copyrighted standard",
        "the answer is a requirement or threshold from an NFPA standard, whose "
        "text is deliberately not in this corpus",
    ),
    ExclusionReason.STATE_OR_LOCAL_CODE: (
        "State or local code",
        "the answer is in a state fire marshal regulation or municipal ordinance, "
        "which this corpus does not hold",
    ),
    ExclusionReason.TIMESTAMP_NOT_RECORDED: (
        "Timestamp not recorded",
        "NFIRS records only alarm and arrival times, so turnout and travel "
        "intervals do not exist in the data for the peer cohort or for 2024",
    ),
    ExclusionReason.YEAR_NOT_COVERED: (
        "Year not covered",
        "this corpus holds the 2024 NFIRS public data release only",
    ),
    ExclusionReason.LIVE_OR_PERSONAL_DATA: (
        "Live or personal data",
        "the answer would require current operational data or identifiable "
        "personal information, neither of which is in the corpus",
    ),
    ExclusionReason.OUTSIDE_DOMAIN: (
        "Outside the domain",
        "the question is not about fire-service data",
    ),
    ExclusionReason.NONE: ("Out of scope", "the corpus does not cover this"),
}


def _refuse_with_scope(
    question: str, reason: ExclusionReason, config: str
) -> tuple[str, list[Citation], list[Hit], int, int, float]:
    hits = scope_context(question, k=2, config=config)
    label, reason_text = REASON_LABELS.get(reason, REASON_LABELS[ExclusionReason.NONE])

    if not hits:
        text = (
            f"That's outside what this system covers ({reason_text}). "
            "The scope boundary document could not be retrieved, so this refusal "
            "is uncited."
        )
        return text, [], [], 0, 0, 0.0

    context = "\n\n".join(
        f"source_document: {h.source_document}\n"
        f"section: {h.section}\n"
        f"text: {h.text}"
        for h in hits
    )
    try:
        reply = complete(
            REFUSAL_PROMPT.format(
                reason_label=label,
                reason_text=reason_text,
                context=context,
                question=question,
            ),
            max_tokens=400,
        )
    except LLMError:
        # Deterministic fallback: still cited, just not phrased by the model.
        text = (
            f"That's outside this corpus. {label}: {reason_text}. "
            f"See [{hits[0].source_document} — {hits[0].section}]."
        )
        return (
            text,
            [Citation("scope", hits[0].citation())],
            hits,
            0,
            0,
            0.0,
        )

    cites = [Citation("scope", c) for c in extract_citations(reply.text)] or [
        Citation("scope", h.citation()) for h in hits[:1]
    ]
    return (
        reply.text.strip(),
        cites,
        hits,
        reply.input_tokens,
        reply.output_tokens,
        reply.cost_usd,
    )


def _answer_hybrid(question: str, config: str, rerank: bool) -> tuple:
    """Run both retrievers and synthesise one answer carrying both citation types."""
    sql_ans: SQLAnswer = ask_sql(question)
    hits = search(question, rerank=rerank, config=config)

    tokens_in = sql_ans.input_tokens
    tokens_out = sql_ans.output_tokens
    cost = sql_ans.cost_usd

    if not sql_ans.answered and not hits:
        return (
            False,
            "I couldn't answer that from either the structured data or the documents.",
            [],
            sql_ans.sql,
            hits,
            "both retrievers failed",
            tokens_in,
            tokens_out,
            cost,
        )

    table = sql_ans.result.as_markdown() if sql_ans.result else "_(query failed)_"
    context = "\n\n".join(
        f"[{i}] source_document: {h.source_document}\n"
        f"    section: {h.section}"
        + (f"\n    page: {h.page}" if h.page else "")
        + f"\n    text: {h.text}"
        for i, h in enumerate(hits, start=1)
    )
    try:
        reply = complete(
            HYBRID_PROMPT.format(
                sql=sql_ans.sql or "-- no query produced",
                table=table,
                context=context,
                question=question,
            ),
            max_tokens=900,
        )
    except LLMError as e:
        return (
            False,
            f"Retrieval succeeded but synthesis failed: {e}",
            [],
            sql_ans.sql,
            hits,
            f"model call failed: {e}",
            tokens_in,
            tokens_out,
            cost,
        )

    tokens_in += reply.input_tokens
    tokens_out += reply.output_tokens
    cost += reply.cost_usd

    cites: list[Citation] = []
    if sql_ans.sql and "[sql]" in reply.text.lower():
        cites.append(Citation("sql", sql_ans.sql))
    cites += [Citation("document", c) for c in extract_citations(reply.text)]

    return (
        True,
        reply.text.strip(),
        cites,
        sql_ans.sql,
        hits,
        None,
        tokens_in,
        tokens_out,
        cost,
    )


def answer(
    question: str, *, config: str = "default", rerank: bool | None = None
) -> Answer:
    rerank = settings.rerank_enabled if rerank is None else rerank
    t0 = time.perf_counter()

    routing = classify(question)
    out = Answer(question=question, routing=routing, answered=False, text="")
    out.input_tokens += routing.input_tokens
    out.output_tokens += routing.output_tokens
    out.cost_usd += routing.cost_usd

    if routing.decision is None:
        out.text = (
            "I couldn't classify that question, so I won't guess at an answer. "
            f"({routing.error})"
        )
        out.refusal_reason = f"routing failed: {routing.error}"
        out.latency_ms = (time.perf_counter() - t0) * 1000
        return out

    r = routing.decision.route

    if r is Route.OUT_OF_SCOPE:
        text, cites, hits, tin, tout, cost = _refuse_with_scope(
            question, routing.decision.exclusion_reason, config
        )
        out.text, out.citations, out.hits = text, cites, hits
        out.input_tokens += tin
        out.output_tokens += tout
        out.cost_usd += cost
        out.refusal_reason = routing.decision.exclusion_reason.value
        out.answered = False

    elif r is Route.STRUCTURED:
        sql_ans = ask_sql(question)
        out.sql = sql_ans.sql
        out.answered = sql_ans.answered
        out.text = sql_ans.answer_text()
        out.refusal_reason = sql_ans.failure_reason
        out.input_tokens += sql_ans.input_tokens
        out.output_tokens += sql_ans.output_tokens
        out.cost_usd += sql_ans.cost_usd
        if sql_ans.sql:
            out.citations.append(Citation("sql", sql_ans.sql))

    elif r is Route.UNSTRUCTURED:
        doc: DocAnswer = answer_documents(question, rerank=rerank, config=config)
        out.answered = doc.answered
        out.text = doc.answer
        out.hits = doc.hits
        out.refusal_reason = doc.refusal_reason
        out.input_tokens += doc.input_tokens
        out.output_tokens += doc.output_tokens
        out.cost_usd += doc.cost_usd
        out.citations = [Citation("document", c) for c in doc.citations]

    else:  # hybrid
        ok, text, cites, sql, hits, reason, tin, tout, cost = _answer_hybrid(
            question, config, rerank
        )
        out.answered, out.text, out.citations = ok, text, cites
        out.sql, out.hits, out.refusal_reason = sql, hits, reason
        out.input_tokens += tin
        out.output_tokens += tout
        out.cost_usd += cost

    out.latency_ms = (time.perf_counter() - t0) * 1000
    return out


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        sys.exit('usage: python -m firesight.generation.answer "question"')
    a = answer(" ".join(sys.argv[1:]))
    d = a.routing.decision
    print(f"\nQ: {a.question}\n")
    if d:
        print(f"route: {d.route.value}  (confidence {d.confidence:.2f})")
        if d.exclusion_reason is not ExclusionReason.NONE:
            print(f"       exclusion_reason={d.exclusion_reason.value}")
        print(f"       {d.reason}\n")
    print(a.text, "\n")
    if a.sql:
        print(f"SQL:\n{a.sql}\n")
    if a.citations:
        print("Citations:")
        for c in a.citations:
            shown = c.text if c.kind != "sql" else c.text.replace("\n", " ")[:90]
            print(f"  [{c.kind}] {shown}")
    print(
        f"\n{a.latency_ms:.0f} ms | {a.input_tokens} in / {a.output_tokens} out "
        f"| ${a.cost_usd:.5f}"
    )


if __name__ == "__main__":
    main()
