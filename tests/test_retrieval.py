"""
Integration tests against the real corpus. Skipped when it isn't ingested.

No API key needed: embeddings, the cross-encoder, and the refusal gate are all
local.
"""

import json

import pytest

from firesight.config import REPO_ROOT, settings
from firesight.ingest.documents import CHUNK_CONFIGS, Tokenizer
from firesight.retrieval.vector_store import (
    CorpusUnavailableError,
    corpus_stats,
    search,
)


def _corpus_ready() -> bool:
    try:
        corpus_stats("small")
    except (CorpusUnavailableError, Exception):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _corpus_ready(),
    reason="corpus not ingested; run `python -m firesight.ingest.documents`",
)


def _questions(name: str) -> list[dict]:
    path = REPO_ROOT / "eval" / name
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ── corpus integrity ──────────────────────────────────────────────────────
def test_both_chunk_configs_are_populated():
    for name in CHUNK_CONFIGS:
        assert corpus_stats(name)["chunks"] > 500


def test_no_chunk_exceeds_the_embedding_window():
    """
    Silent truncation at 512 tokens would quietly drop the tail of every long
    chunk, so this is checked rather than assumed.
    """
    from firesight.retrieval.vector_store import _collection

    tok = Tokenizer(settings.embed_model)
    for name, cfg in CHUNK_CONFIGS.items():
        got = _collection(cfg.collection).get(include=["documents"], limit=6000)
        longest = max(tok.count(t) for t in got["documents"])
        assert longest <= 512, f"{name} has a {longest}-token chunk"


def test_chunk_text_preserves_case_and_punctuation():
    """
    Chunks are sliced from the original string by character offset. Rebuilding
    them by decoding token ids would lowercase everything, because
    bge-small-en-v1.5 is an uncased model.
    """
    hits = search("NFIRS module completed for wildland fires", k=10, config="small")
    joined = " ".join(h.text for h in hits)
    assert any(c.isupper() for c in joined)
    assert "NFIRS" in joined


def test_no_table_of_contents_chunks_survive_ingest():
    from firesight.retrieval.vector_store import _collection

    got = _collection("firesight_docs_small").get(include=["metadatas"], limit=6000)
    sections = {m["section"].strip().lower() for m in got["metadatas"]}
    assert "table of contents" not in sections


def test_local_incident_export_is_never_in_the_corpus():
    """
    PROFILE.md section 7: incident addresses, building names, coordinates and
    personnel identifiers must not leave the raw file.
    """
    from firesight.retrieval.vector_store import _collection

    for cfg in CHUNK_CONFIGS.values():
        got = _collection(cfg.collection).get(
            include=["documents", "metadatas"], limit=6000
        )
        docs = {m["source_document"] for m in got["metadatas"]}
        assert not any("sewanee-incidents" in d.lower() for d in docs)
        blob = " ".join(got["documents"]).lower()
        for leak in ("alabama avenue", "snowden hall", "benedict hall", "apparatus_"):
            assert leak not in blob, f"local export leaked into {cfg.name}: {leak!r}"


# ── metadata completeness ─────────────────────────────────────────────────
def test_every_hit_carries_a_usable_citation():
    for h in search("How does NFIRS define a structure?", k=5, config="small"):
        assert h.source_document and h.source_document != "?"
        assert h.section and h.section != "?"
        assert h.publisher and h.year
        assert " — " in h.citation()


# ── ranking behaviour ─────────────────────────────────────────────────────
def test_scores_are_descending_and_bounded():
    hits = search("NFIRS incident type codes", k=8, config="small")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.01 <= s <= 1.01 for s in scores)
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))


def test_k_is_respected():
    for k in (1, 3, 7):
        assert len(search("structure fire", k=k, config="small")) == k


def test_rerank_changes_the_ordering_and_preserves_the_retrieval_score():
    q = "Which NFIRS module is completed for wildland or vegetation fires?"
    plain = search(q, k=5, config="small", rerank=False)
    reranked = search(q, k=5, config="small", rerank=True)
    assert all(h.retrieval_score is not None for h in reranked)
    assert all(h.retrieval_score is None for h in plain)
    # Reranking must actually reorder something, or it is doing nothing.
    assert [h.chunk_id for h in plain] != [h.chunk_id for h in reranked]


# ── the refusal gate ──────────────────────────────────────────────────────
def test_support_floor_sits_in_the_measured_gap():
    """
    Calibrated: in-corpus questions score >= 0.750, out-of-corpus <= 0.662.
    A floor outside that gap either admits junk or refuses real questions.
    """
    assert 0.663 <= settings.min_support_score <= 0.749


@pytest.mark.parametrize("q", [q["question"] for q in _questions("out_of_corpus_questions.jsonl")])
def test_out_of_corpus_questions_are_refused_before_any_model_call(monkeypatch, q):
    import firesight.generation.synthesize as syn

    monkeypatch.setattr(
        syn, "complete", lambda *a, **k: pytest.fail("model called without support")
    )
    a = syn.answer(q, config="small")
    assert a.is_refusal
    assert "support floor" in (a.refusal_reason or "")


@pytest.mark.parametrize("q", [q["question"] for q in _questions("document_questions.jsonl")])
def test_in_corpus_questions_clear_the_support_floor(q):
    import firesight.generation.synthesize as syn

    hits = search(q, k=5, config="small")
    best = max(h.score for h in hits)
    assert best >= syn.MIN_SUPPORT_SCORE, f"{q!r} would be wrongly refused ({best:.3f})"
