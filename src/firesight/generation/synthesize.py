"""
Cited answer synthesis over retrieved chunks.

Two properties the spec requires, implemented deliberately:

1. **Inline citations.** Every claim carries `[source_document — section]`.
   The prompt demands it and `extract_citations()` verifies it afterwards, so
   an uncited answer is detectable rather than assumed-good.

2. **Refusal without support.** If nothing is retrieved, or everything
   retrieved is below `MIN_SUPPORT_SCORE`, the question is refused WITHOUT
   calling the model at all. That makes the no-support path deterministic and
   testable, instead of hoping the model declines on instruction.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from firesight.config import settings
from firesight.generation.llm import LLMError, complete
from firesight.retrieval.vector_store import Hit, search

# Cosine similarity below this is treated as no support. Calibrated, not
# guessed -- see settings.min_support_score and
# scripts/calibrate_support_floor.py.
MIN_SUPPORT_SCORE = settings.min_support_score

REFUSAL = (
    "I don't know. The document corpus doesn't contain material that answers "
    "this question, so I can't give a grounded answer."
)

CITATION = re.compile(r"\[([^\]\[]+?)\s+[-—]{1,2}\s+([^\]\[]+?)\]")


@dataclass
class DocAnswer:
    question: str
    answered: bool
    answer: str
    hits: list[Hit] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    refusal_reason: str | None = None
    latency_ms: float = 0.0
    retrieval_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def is_refusal(self) -> bool:
        return not self.answered


def build_prompt(question: str, hits: list[Hit]) -> str:
    context = "\n\n".join(
        f"[{i}] source_document: {h.source_document}\n"
        f"    section: {h.section}"
        + (f"\n    page: {h.page}" if h.page else "")
        + f"\n    text: {h.text}"
        for i, h in enumerate(hits, start=1)
    )
    return f"""You answer questions about fire-service data standards using ONLY the \
retrieved passages below.

## RETRIEVED PASSAGES

{context}

## RULES

1. Use ONLY the passages above. Do not add facts from your own knowledge, even
   if you are confident they are correct and even if a passage looks incomplete.
2. Cite inline after every claim, as [source_document — section]. Copy the
   source_document and section values exactly as given above.
3. If the passages do not answer the question, reply with exactly:
   "{REFUSAL}"
   Do not partially answer from general knowledge, and do not speculate.
4. If the passages conflict, say so and cite both.
5. Be concise. Two or three sentences is usually enough.
6. NFPA standards are copyrighted and are not in this corpus. If the question
   needs an NFPA threshold, say the corpus does not contain it and cite nothing
   for that part.

## QUESTION

{question}

## ANSWER"""


def extract_citations(text: str) -> list[str]:
    """Pull `[document — section]` pairs out of an answer, in order, deduped."""
    out, seen = [], set()
    for doc, sec in CITATION.findall(text or ""):
        cite = f"{doc.strip()} — {sec.strip()}"
        if cite not in seen:
            seen.add(cite)
            out.append(cite)
    return out


def answer(
    question: str,
    *,
    k: int | None = None,
    rerank: bool = False,
    config: str = "default",
) -> DocAnswer:
    t0 = time.perf_counter()
    hits = search(question, k=k, rerank=rerank, config=config)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    # Reranker scores are not cosine similarities, so the support floor is
    # applied to the retrieval score it preserved.
    def support(h: Hit) -> float:
        return h.retrieval_score if h.retrieval_score is not None else h.score

    supported = [h for h in hits if support(h) >= MIN_SUPPORT_SCORE]

    if not supported:
        best = max((support(h) for h in hits), default=0.0)
        return DocAnswer(
            question=question,
            answered=False,
            answer=REFUSAL,
            hits=hits,
            refusal_reason=(
                f"no chunk reached the support floor "
                f"(best {best:.3f} < {MIN_SUPPORT_SCORE})"
            ),
            latency_ms=(time.perf_counter() - t0) * 1000,
            retrieval_ms=retrieval_ms,
        )

    try:
        # Budget must cover the model's `thinking` block as well as its
        # text. At 700 the thinking consumed it all and the text block
        # came back empty -- the same bug that produced a 21.7% schema-
        # violation rate in the router.
        reply = complete(build_prompt(question, supported), max_tokens=2000)
    except LLMError as e:
        return DocAnswer(
            question=question,
            answered=False,
            answer=f"Retrieval succeeded but synthesis failed: {e}",
            hits=hits,
            refusal_reason=f"model call failed: {e}",
            latency_ms=(time.perf_counter() - t0) * 1000,
            retrieval_ms=retrieval_ms,
        )

    text = reply.text.strip()
    refused = REFUSAL.lower()[:40] in text.lower()
    return DocAnswer(
        question=question,
        answered=not refused,
        answer=text,
        hits=supported,
        citations=extract_citations(text),
        refusal_reason="model declined: no support in passages" if refused else None,
        latency_ms=(time.perf_counter() - t0) * 1000,
        retrieval_ms=retrieval_ms,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        cost_usd=reply.cost_usd,
    )


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        sys.exit('usage: python -m firesight.generation.synthesize "question"')
    a = answer(" ".join(sys.argv[1:]))
    print(f"\nQ: {a.question}\n")
    print(a.answer, "\n")
    if a.refusal_reason:
        print(f"[refused: {a.refusal_reason}]\n")
    print("Retrieved:")
    for h in a.hits:
        print(f"  {h.rank}. {h.score:.3f}  {h.citation()}")
    print(f"\n{a.latency_ms:.0f} ms total ({a.retrieval_ms:.0f} ms retrieval)")


if __name__ == "__main__":
    main()
