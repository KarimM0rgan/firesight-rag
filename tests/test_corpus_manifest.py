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

import hashlib

import pytest

from firesight.config import REPO_ROOT, settings
from firesight.ingest.documents import (
    CODE_SOURCES,
    CORPUS_DENYLIST,
    CORPUS_MANIFEST,
    MARKDOWN_SOURCES,
    PDF_SOURCES,
    SCOPE_SOURCES,
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
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
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
