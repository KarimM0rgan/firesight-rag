"""
Tests for citation handling and the no-support refusal path.

These need neither the corpus nor an API key: the refusal decision is made
before any model call, which is the point of implementing it that way.
"""

import pytest

from firesight.generation.synthesize import (
    MIN_SUPPORT_SCORE,
    REFUSAL,
    build_prompt,
    extract_citations,
)
from firesight.retrieval.vector_store import Hit


def hit(score: float, doc: str = "NFIRS 5.0 Complete Reference Guide",
        section: str = "Incident Type", page: int | None = 42,
        text: str = "A structure fire is coded in series 111-123.") -> Hit:
    return Hit(
        chunk_id="abc123",
        text=text,
        score=score,
        source_document=doc,
        section=section,
        page=page,
        publisher="U.S. Fire Administration (FEMA)",
        year="2015",
        url="https://example.gov/doc.pdf",
        rank=1,
    )


# ── citation extraction ───────────────────────────────────────────────────
def test_extracts_em_dash_citation():
    text = "A structure fire is series 111 [NFIRS 5.0 Complete Reference Guide — Incident Type]."
    assert extract_citations(text) == [
        "NFIRS 5.0 Complete Reference Guide — Incident Type"
    ]


def test_hyphen_separator_is_normalised_to_the_canonical_form():
    """
    A model that writes a plain hyphen must still produce a citation that
    compares equal to Hit.citation(), which uses an em dash. So the separator
    is normalised rather than echoed back.
    """
    assert extract_citations("Claim [Doc A - Section B].") == ["Doc A — Section B"]


def test_normalised_citation_matches_hit_citation_exactly():
    h = hit(0.9, doc="Doc A", section="Section B", page=None)
    assert extract_citations(f"Claim [{h.citation()}].") == [h.citation()]


def test_dedupes_repeated_citations_preserving_order():
    text = "One [D — S1]. Two [D — S2]. Three [D — S1]."
    assert extract_citations(text) == ["D — S1", "D — S2"]


def test_no_citations_found_in_uncited_answer():
    assert extract_citations("Structure fires are series 111.") == []


def test_ignores_bracketed_text_that_is_not_a_citation():
    assert extract_citations("See [1] and [note].") == []


# ── prompt construction ───────────────────────────────────────────────────
def test_prompt_carries_metadata_the_model_must_cite():
    p = build_prompt("What is a structure fire?", [hit(0.8)])
    assert "source_document: NFIRS 5.0 Complete Reference Guide" in p
    assert "section: Incident Type" in p
    assert "page: 42" in p


def test_prompt_contains_the_exact_refusal_string():
    """The model's refusal must be byte-comparable to what we detect."""
    assert REFUSAL in build_prompt("q", [hit(0.8)])


def test_prompt_forbids_parametric_knowledge_and_nfpa_text():
    p = build_prompt("q", [hit(0.8)])
    assert "ONLY the passages above" in p
    assert "NFPA" in p


# ── the support floor ─────────────────────────────────────────────────────
def test_support_floor_is_a_cosine_similarity_in_range():
    assert 0.0 < MIN_SUPPORT_SCORE < 1.0


def test_refuses_without_calling_the_model_when_nothing_clears_the_floor(
    monkeypatch,
):
    import firesight.generation.synthesize as syn

    monkeypatch.setattr(syn, "search", lambda *a, **k: [hit(MIN_SUPPORT_SCORE - 0.2)])

    def explode(*a, **k):
        raise AssertionError("the model must not be called without support")

    monkeypatch.setattr(syn, "complete", explode)

    a = syn.answer("What is the airspeed velocity of an unladen swallow?")
    assert a.is_refusal
    assert a.answer == REFUSAL
    assert "support floor" in a.refusal_reason


def test_refuses_when_retrieval_returns_nothing(monkeypatch):
    import firesight.generation.synthesize as syn

    monkeypatch.setattr(syn, "search", lambda *a, **k: [])
    monkeypatch.setattr(
        syn, "complete", lambda *a, **k: pytest.fail("must not call the model")
    )
    assert syn.answer("anything").is_refusal


def test_passes_only_supported_chunks_to_the_model(monkeypatch):
    import firesight.generation.synthesize as syn
    from firesight.generation.llm import Reply

    monkeypatch.setattr(
        syn,
        "search",
        lambda *a, **k: [hit(0.9, section="Kept"), hit(0.1, section="Dropped")],
    )
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        return Reply("Answer [NFIRS 5.0 Complete Reference Guide — Kept].", 10, 5, 0.0, "m")

    monkeypatch.setattr(syn, "complete", fake)
    a = syn.answer("q")
    assert a.answered
    assert "section: Kept" in captured["prompt"]
    assert "section: Dropped" not in captured["prompt"]
    assert a.citations == ["NFIRS 5.0 Complete Reference Guide — Kept"]


def test_model_refusal_is_detected_and_marked(monkeypatch):
    import firesight.generation.synthesize as syn
    from firesight.generation.llm import Reply

    monkeypatch.setattr(syn, "search", lambda *a, **k: [hit(0.9)])
    monkeypatch.setattr(syn, "complete", lambda *a, **k: Reply(REFUSAL, 10, 5, 0.0, "m"))
    a = syn.answer("q")
    assert a.is_refusal
    assert a.refusal_reason == "model declined: no support in passages"


def test_rerank_scores_do_not_bypass_the_support_floor(monkeypatch):
    """
    A cross-encoder score is not a cosine similarity. The floor must be
    applied to the preserved retrieval score, or reranking would smuggle
    unsupported chunks past it.
    """
    import firesight.generation.synthesize as syn

    h = hit(8.5)  # large cross-encoder score
    h.retrieval_score = 0.10  # but the embedding said it was irrelevant
    monkeypatch.setattr(syn, "search", lambda *a, **k: [h])
    monkeypatch.setattr(
        syn, "complete", lambda *a, **k: pytest.fail("must not call the model")
    )
    assert syn.answer("q").is_refusal
