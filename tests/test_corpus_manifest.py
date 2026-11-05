"""
The corpus is an explicit allowlist, and these tests are what make that true.

Root cause being fixed: ingest previously took its project-authored material
from a fixed pair of paths under `data/`, and those files were build artifacts
rewritten as the work proceeded. Editing one moved the retrieval metrics — a
circularity, since documenting a measurement changed the measurement. Traced:
one edit to RECONCILIATION.md displaced a labelled answer out of the top 5 and
moved Recall@5 by 0.033.

So: nothing is corpus because of where it sits on disk. A file becomes corpus
only by being added to CORPUS_MANIFEST, and these tests fail if that is bypassed.
"""

import pytest

from firesight.config import REPO_ROOT, settings
from firesight.ingest.documents import (
    CODE_SOURCES,
    CORPUS_DENYLIST,
    CORPUS_MANIFEST,
    MARKDOWN_SOURCES,
    PDF_SOURCES,
    SCOPE_SOURCES,
    frozen_hash,
)


def _manifest_paths() -> set[str]:
    """Manifest keys as repo-relative posix paths, with the NFIRS dir resolved."""
    out = set()
    for key in CORPUS_MANIFEST:
        if key.startswith("<nfirs_dir>"):
            out.add((settings.nfirs_dir / key.split("/", 1)[1]).as_posix())
        else:
            out.add((REPO_ROOT / key).as_posix())
    return out


def _ingested_paths() -> set[str]:
    srcs = [*PDF_SOURCES, *MARKDOWN_SOURCES, *SCOPE_SOURCES, *CODE_SOURCES]
    return {s.path.as_posix() for s in srcs}


# ── the allowlist is the only way in ──────────────────────────────────────
def test_every_ingested_source_is_in_the_manifest():
    """A file reaching ingest without a manifest entry is the bug this prevents."""
    unlisted = _ingested_paths() - _manifest_paths()
    assert not unlisted, f"ingested but not in CORPUS_MANIFEST: {sorted(unlisted)}"


def test_every_manifest_entry_is_actually_ingested():
    """A stale manifest entry is as misleading as a missing one."""
    orphaned = _manifest_paths() - _ingested_paths()
    assert not orphaned, f"in CORPUS_MANIFEST but never ingested: {sorted(orphaned)}"


def test_manifest_entries_declare_a_known_kind():
    assert all(
        e["kind"] in {"external", "project_frozen", "scope"}
        for e in CORPUS_MANIFEST.values()
    )


# ── build artifacts stay out ──────────────────────────────────────────────
def test_build_artifacts_are_not_in_the_corpus():
    """
    PROFILE.md, RECONCILIATION.md, the README and eval/results are rewritten as
    the work proceeds. In the corpus they made retrieval metrics a function of
    how much documentation had been written.
    """
    ingested = _ingested_paths()
    for denied in CORPUS_DENYLIST:
        denied_path = (REPO_ROOT / denied).as_posix()
        assert not any(
            p == denied_path or p.startswith(denied_path.rstrip("/") + "/")
            for p in ingested
        ), f"denylisted path reached ingest: {denied}"
        assert denied not in CORPUS_MANIFEST, f"denylisted path in manifest: {denied}"


def test_exactly_one_project_authored_corpus_document():
    """
    Methodology is consolidated into one frozen document. More than one means
    the split has drifted back apart.
    """
    project = [k for k, v in CORPUS_MANIFEST.items() if v["kind"] == "project_frozen"]
    assert project == ["data/corpus/METHODOLOGY.md"]


def test_no_markdown_under_data_root_is_ingested_implicitly():
    """
    Guards the original failure mode directly: dropping a .md file into data/
    must not make it corpus.
    """
    loose = {p.as_posix() for p in (REPO_ROOT / "data").glob("*.md")}
    assert loose, "expected PROFILE.md / RECONCILIATION.md to exist at data/"
    assert not (loose & _ingested_paths())


# ── the freeze ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "rel",
    [k for k, v in CORPUS_MANIFEST.items() if v.get("frozen_sha256")],
)
def test_frozen_documents_match_their_pinned_hash(rel):
    """
    These are corpus documents, so editing them shifts retrieval metrics. The
    pin makes that a deliberate act: edit, re-run the suites, then update the
    hash and the published numbers in one commit.
    """
    path = REPO_ROOT / rel
    actual = frozen_hash(path)
    expected = CORPUS_MANIFEST[rel]["frozen_sha256"]
    assert actual == expected, (
        f"{rel} changed.\n"
        f"  pinned: {expected}\n"
        f"  actual: {actual}\n"
        "This is a corpus document: re-run the retrieval suite and the held-out "
        "gate check, then update the pin and the published metrics together."
    )


def test_every_project_and_scope_document_is_pinned():
    """External PDFs need no pin; anything we author does."""
    for key, entry in CORPUS_MANIFEST.items():
        if entry["kind"] in {"project_frozen", "scope"}:
            assert entry.get("frozen_sha256"), f"{key} is unpinned"


def test_methodology_document_carries_rules_not_results():
    """
    The split is methodology in, build artifacts out. A reconciliation table or
    a measured metric landing in here would reintroduce the circularity.
    """
    text = (REPO_ROOT / "data" / "corpus" / "METHODOLOGY.md").read_text(encoding="utf-8")
    for banned in ("Recall@5", "MRR", "confusion matrix", "execution accuracy"):
        assert banned.lower() not in text.lower(), f"{banned!r} is a build result"


def test_methodology_document_covers_the_four_required_topics():
    text = (REPO_ROOT / "data" / "corpus" / "METHODOLOGY.md").read_text(encoding="utf-8")
    assert "Peer-group definition" in text
    assert "response_min <= 90" in text  # response-time filter rule
    assert "no dispatch timestamp and no" in text  # alarm-to-arrival constraint
    assert "Non-response incident types" in text  # incident-type exclusions


# ── Wilson intervals and metric pre-commitment ────────────────────────────
def test_wilson_intervals_match_published_values():
    from firesight.eval.stats import proportion

    # Standard reference values for the Wilson score interval at 95%.
    for s, n, lo, hi in [(8, 8, 0.676, 1.000), (11, 13, 0.578, 0.957),
                         (20, 20, 0.839, 1.000), (9, 20, 0.258, 0.658)]:
        p = proportion(s, n)
        assert abs(p.low - lo) < 0.002, f"{s}/{n} low {p.low} != {lo}"
        assert abs(p.high - hi) < 0.002, f"{s}/{n} high {p.high} != {hi}"


def test_wilson_interval_does_not_collapse_at_the_extremes():
    """
    The reason for Wilson over the normal approximation: 8/8 must not report a
    zero-width interval, or a reader will read it as a measured rate.
    """
    from firesight.eval.stats import proportion

    assert proportion(8, 8).width > 0.3
    assert proportion(0, 10).width > 0.2
    assert proportion(0, 10).high > 0.0


def test_no_observations_is_not_a_measurement_of_zero():
    from firesight.eval.stats import proportion

    p = proportion(0, 0)
    assert p.estimate is None and p.low is None
    assert "n/a" in p.fmt()


def test_formatted_proportion_always_carries_its_interval():
    """A harness must not be able to emit an estimate without its CI."""
    from firesight.eval.stats import proportion

    out = proportion(8, 8).fmt()
    assert "8/8" in out and "[" in out and "]" in out


def test_small_samples_are_flagged_as_not_a_rate():
    from firesight.eval.stats import proportion, too_small_to_claim_a_rate

    assert too_small_to_claim_a_rate(proportion(8, 8))
    assert too_small_to_claim_a_rate(proportion(11, 13))
    assert not too_small_to_claim_a_rate(proportion(440, 460))


def test_sql_primary_metric_is_pre_committed_to_exact_match():
    """
    Containment was defined after seeing exact match score 45%. The primary
    metric is pinned in code so it cannot be selected after an M4 result.
    """
    from firesight.eval.sql_suite import PRIMARY_METRIC, SECONDARY_METRIC

    assert PRIMARY_METRIC == "result_accuracy"
    assert SECONDARY_METRIC == "answer_containment_accuracy"


# ── M4 golden set: written and frozen before any model run ────────────────
def _jsonl(name: str) -> list[dict]:
    path = REPO_ROOT / "eval" / name
    return [
        __import__("json").loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_golden_set_is_fifty_questions():
    assert len(_jsonl("document_questions.jsonl")) == 50


def test_golden_set_methodology_share_is_at_most_twenty_percent():
    from firesight.eval.retrieval_suite import question_origin

    qs = _jsonl("document_questions.jsonl")
    origins = [question_origin(q) for q in qs]
    meth = origins.count("methodology")
    assert meth / len(qs) <= 0.20, f"{meth}/{len(qs)} methodology-origin"
    assert origins.count("external") + meth == len(qs)
    assert "project" not in origins  # build artifacts are out of the corpus


def test_every_golden_question_has_a_label_and_a_distinctive_needle():
    for q in _jsonl("document_questions.jsonl"):
        assert q.get("relevant_sections"), q["id"]
        needles = q.get("answer_must_contain") or []
        assert needles, q["id"]
        # A short needle invites accidental matches; these are hand-picked
        # phrases, not keywords.
        assert all(len(n) >= 20 for n in needles), q["id"]


def test_golden_set_ids_are_unique():
    ids = [q["id"] for q in _jsonl("document_questions.jsonl")]
    assert len(ids) == len(set(ids))


# ── M4 SQL set ────────────────────────────────────────────────────────────
def test_sql_set_is_at_least_forty_questions():
    """20 questions gave exact-match [25.8, 65.8] -- too wide to be useful."""
    assert len(_jsonl("structured_questions.jsonl")) >= 40


def test_sql_set_probes_percentile_versus_rank():
    """
    s18 showed the model substituting a rank for a percentile and choosing the
    wrong tie rule. One question could not distinguish that from noise.
    """
    qs = _jsonl("structured_questions.jsonl")
    pvr = [q for q in qs if q.get("category") == "percentile_vs_rank"]
    assert len(pvr) >= 3, f"only {len(pvr)} percentile-vs-rank questions"


def test_every_sql_question_has_reference_sql():
    for q in _jsonl("structured_questions.jsonl"):
        assert q.get("reference_sql", "").strip().upper().startswith(("SELECT", "WITH")), q["id"]


def test_known_sql_failures_stay_unfixed_through_m4():
    """
    s10, s17, s18, s19 and s20 are characterized and deliberately NOT fixed, so
    the M4 re-measurement is clean. This pins the questions as still present
    and unchanged in intent; it does not assert they pass.
    """
    ids = {q["id"] for q in _jsonl("structured_questions.jsonl")}
    assert {"s10", "s17", "s18", "s19", "s20"} <= ids
