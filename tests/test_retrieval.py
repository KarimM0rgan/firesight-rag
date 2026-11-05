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


# Known, unfixed: d14 scores 0.686 against the 0.70 floor and would be wrongly
# refused. It appeared when the corpus was split by document kind (Fix 11) --
# removing the build artifacts removed content that previously scored well for
# peer-group questions, leaving METHODOLOGY.md's 15 chunks as a thinner target.
#
# Deliberately NOT fixed by rewording the question (that tunes the test to the
# system) or by lowering the floor (that admits more out-of-corpus questions,
# and the pooled margin is already negative). Pinned by id so the regression is
# recorded precisely and the test fails if it spreads to other questions.
# Two in-corpus questions now score below the 0.70 floor and would be wrongly
# refused. d14 appeared when the corpus was split by document kind; d31 appeared
# when the golden set grew 15 -> 50, which also destroyed the floor's clean
# separation (in-corpus min 0.619 vs out-of-corpus max 0.662 -- see the README).
#
# Neither is fixed by rewording the question (that tunes the benchmark to the
# system) nor by moving the floor (0.65 would admit 3/12 out-of-corpus to save
# one of these). Pinned by id so the failures are recorded exactly and the suite
# fails if they spread.
KNOWN_BELOW_FLOOR = {"d14", "d31"}


def test_in_corpus_questions_clear_the_support_floor():
    import firesight.generation.synthesize as syn

    below = {}
    for q in _questions("document_questions.jsonl"):
        best = max(h.score for h in search(q["question"], k=5, config="small"))
        if best < syn.MIN_SUPPORT_SCORE:
            below[q["id"]] = round(best, 3)

    assert set(below) == KNOWN_BELOW_FLOOR, (
        f"support-floor failures changed: {below}. "
        f"Known and accepted: {sorted(KNOWN_BELOW_FLOOR)}. "
        "A new entry is a regression; a missing one means the gate improved and "
        "this pin should be tightened."
    )


def test_the_floor_no_longer_separates_the_populations_at_n50():
    """
    Records the structural finding rather than a threshold: at n=50 the
    in-corpus minimum (0.619) sits BELOW the out-of-corpus maximum (0.662), so
    no similarity floor can gate the refusal path cleanly. The router's
    explicit out-of-scope path is the mechanism that works.
    """
    import json

    path = REPO_ROOT / "eval" / "support_floor_calibration.json"
    if not path.exists():
        pytest.skip("calibration not run")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["separated"] is False
    assert data["in_corpus_min"] < data["out_of_corpus_max"]


def test_the_known_floor_failure_still_retrieves_its_answer():
    """
    d14 is refused by the gate, but retrieval itself is not at fault: the
    labelled section is still inside the top 5. The failure is the absolute
    score, not the ranking -- which is the distinction the cross-encoder gate
    experiment also turned on.
    """
    from firesight.eval.retrieval_suite import score_question

    for qid in sorted(KNOWN_BELOW_FLOOR):
        q = next(x for x in _questions("document_questions.jsonl") if x["id"] == qid)
        s = score_question(q, search(q["question"], k=5, config="small"), 5)
        assert s.hit, f"{qid} no longer retrieves its labelled section at all"


# ── out-of-sample gate validation (Fix 6) ─────────────────────────────────
HELDOUT = _questions("heldout_questions.jsonl")
HELDOUT_IN = [q for q in HELDOUT if q["kind"] == "in_corpus"]
HELDOUT_OUT = [q for q in HELDOUT if q["kind"] == "out_of_corpus"]


def test_heldout_set_does_not_overlap_the_calibration_sets():
    """A validation set that shares questions with the fit is not a validation set."""
    calib = {q["question"] for q in _questions("document_questions.jsonl")}
    calib |= {q["question"] for q in _questions("out_of_corpus_questions.jsonl")}
    held = {q["question"] for q in HELDOUT}
    assert not (held & calib)
    assert len(HELDOUT_IN) == 8
    assert len(HELDOUT_OUT) == 10


def test_heldout_in_corpus_questions_are_all_answerable():
    """Every held-out in-corpus question clears the floor; 0/8 false refusals."""
    import firesight.generation.synthesize as syn

    for q in HELDOUT_IN:
        best = max(h.score for h in search(q["question"], k=5, config="small"))
        assert best >= syn.MIN_SUPPORT_SCORE, f"{q['id']} wrongly refused ({best:.3f})"


def test_heldout_gate_refuses_at_least_nine_of_ten_out_of_corpus():
    """
    Out-of-sample the populations overlap, so this is 9/10 rather than 10/10.
    The admitted one is the adversarial NFPA question. Pinned so a regression
    below 9 is caught, and so the known failure is not quietly 'fixed' by
    moving the floor into the in-corpus range.
    """
    import firesight.generation.synthesize as syn

    refused = sum(
        1
        for q in HELDOUT_OUT
        if max(h.score for h in search(q["question"], k=5, config="small"))
        < syn.MIN_SUPPORT_SCORE
    )
    assert refused >= 9


def test_the_known_gate_failure_is_the_adversarial_nfpa_question():
    """Documents the specific weakness rather than leaving it as a bare count."""
    import firesight.generation.synthesize as syn

    admitted = [
        q["id"]
        for q in HELDOUT_OUT
        if max(h.score for h in search(q["question"], k=5, config="small"))
        >= syn.MIN_SUPPORT_SCORE
    ]
    assert admitted == ["h16"], f"gate failures moved: {admitted}"


def test_cross_encoder_is_unusable_as_an_absolute_gate():
    """
    The cross-encoder is a good reranker and a bad gate: it scores some
    out-of-corpus questions at ~1.0 and some genuine in-corpus questions near
    0. Pinned so nobody wires it into the refusal path on intuition.
    """
    out_max = max(
        max(h.score for h in search(q["question"], k=5, config="small", rerank=True))
        for q in HELDOUT_OUT
    )
    in_min = min(
        max(h.score for h in search(q["question"], k=5, config="small", rerank=True))
        for q in HELDOUT_IN
    )
    assert out_max > in_min, "cross-encoder populations no longer overlap; re-test it"


# ── self-reference audit (Fix 9 / Fix 11) ─────────────────────────────────
def test_origin_split_is_twelve_external_three_methodology():
    """
    Methodology questions are kept deliberately (a user asking how a figure was
    derived deserves a cited answer) but capped, because project-authored
    material is an easier retrieval target. Three of fifteen is 20%.
    """
    from firesight.eval.retrieval_suite import question_origin

    qs = _questions("document_questions.jsonl")
    origins = [question_origin(q) for q in qs]
    assert origins.count("external") == 12
    assert origins.count("methodology") == 3
    assert origins.count("methodology") / len(qs) <= 0.20
    # No question may be answered by a build artifact; those are out of the
    # corpus entirely, so such a label could never resolve.
    assert "project" not in origins


def test_no_question_is_answered_by_a_build_artifact():
    from firesight.ingest.documents import CORPUS_DENYLIST

    denied_titles = {"FireSight Data Profile", "FireSight Reconciliation Notes"}
    for name in ("document_questions.jsonl", "heldout_questions.jsonl"):
        for q in _questions(name):
            docs = {s["source_document"] for s in q.get("relevant_sections", [])}
            assert not (docs & denied_titles), f"{q['id']} labels a build artifact"
    assert "data/RECONCILIATION.md" in CORPUS_DENYLIST


# ── scope document lives outside the main index (Fix 10) ──────────────────
def test_scope_document_is_not_in_the_main_index():
    """
    It is fetched by name on the out_of_scope path, so its presence among
    ordinary retrieval candidates buys nothing and costs ranking precision.
    Measured when it shared the index: MRR 0.711 -> 0.644 on the best arm.
    """
    from firesight.retrieval.vector_store import SCOPE_DOCUMENT, _collection

    for cfg in CHUNK_CONFIGS.values():
        got = _collection(cfg.collection).get(include=["metadatas"], limit=6000)
        docs = {m["source_document"] for m in got["metadatas"]}
        assert SCOPE_DOCUMENT not in docs, f"scope doc leaked into {cfg.collection}"


def test_scope_collection_exists_and_holds_only_scope_chunks():
    from firesight.retrieval.vector_store import SCOPE_DOCUMENT, _collection

    for cfg in CHUNK_CONFIGS.values():
        coll = _collection(cfg.scope_collection)
        assert coll.count() > 0
        got = coll.get(include=["metadatas"], limit=100)
        assert {m["source_document"] for m in got["metadatas"]} == {SCOPE_DOCUMENT}
        assert all(m.get("exclude_from_scoring") for m in got["metadatas"])


def test_scope_lookup_returns_the_right_boundary_section():
    """Each exclusion mechanism must land on the section that explains it."""
    from firesight.retrieval.vector_store import scope_context

    cases = [
        ("What is the recommended pressure for a sprinkler system under NFPA 13?",
         "NFPA standards"),
        ("What does the Tennessee state fire code require?",
         "State and municipal fire codes"),
        ("What was the peer-group median turnout time in 2024?",
         "Turnout and travel time, outside the one local export"),
        ("How has our P90 trended since 2019?", "Years other than 2024"),
    ]
    for question, expected_section in cases:
        hits = scope_context(question, k=2, config="small")
        assert hits, f"no scope hit for {question!r}"
        assert hits[0].section == expected_section, (
            f"{question!r} -> {hits[0].section!r}, expected {expected_section!r}"
        )


def test_scope_document_contains_no_nfpa_thresholds():
    """
    The scope document names which standards govern which topics and must not
    reproduce any of their substance.
    """
    import re

    text = (REPO_ROOT / "data" / "corpus" / "SCOPE.md").read_text(encoding="utf-8")
    # No "<number> seconds/minutes" style thresholds anywhere near NFPA mentions.
    assert not re.search(r"\b\d+\s*(seconds|minutes)\b", text, re.IGNORECASE)
    # It must still name the standards, or a refusal cannot be specific.
    assert "NFPA 1710" in text and "1720" in text
