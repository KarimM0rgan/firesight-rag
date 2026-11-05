"""
The published metrics describe specific code. This asserts that code is unchanged.

Every figure in the README was produced by a particular router prompt, schema
description, set of few-shot examples, chunking configuration, similarity floor,
and set of frozen questions and references. Edit any of them and the numbers
stop describing the system — silently, because nothing else would fail.

The demo UI added in M7 is a read-only consumer of these modules. This test is
what makes "read-only" checkable rather than a claim in a commit message.

To change a measured file deliberately: make the change, re-run the affected
suites, update `eval/measured_surface.json` and the README numbers in the same
commit. The failure message says so.
"""

from __future__ import annotations

import json

import pytest

from firesight.config import REPO_ROOT
from firesight.ingest.documents import frozen_hash

MANIFEST = REPO_ROOT / "eval" / "measured_surface.json"


def _manifest() -> dict[str, str]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]


def test_manifest_exists_and_is_populated():
    files = _manifest()
    assert len(files) >= 14
    assert "src/firesight/retrieval/schema.py" in files
    assert "eval/structured_questions.jsonl" in files


@pytest.mark.parametrize("rel", sorted(_manifest()))
def test_measured_file_is_unchanged(rel):
    actual = frozen_hash(REPO_ROOT / rel)
    expected = _manifest()[rel]
    assert actual == expected, (
        f"\n{rel} has changed since the metrics were measured."
        f"\n  pinned: {expected}"
        f"\n  actual: {actual}\n"
        "\nThe README's numbers were produced by the previous content, so they "
        "no longer describe this code. Either revert the change, or re-run the "
        "affected suites and update eval/measured_surface.json together with "
        "the published figures in one commit."
    )


def test_the_app_does_not_import_its_way_around_the_freeze():
    """
    The demo is allowed to CALL the measured modules. It is not allowed to
    mutate their module-level state, which would change behaviour without
    changing a hash.
    """
    app = (REPO_ROOT / "src" / "firesight" / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "PROMPT =",
        "SCHEMA =",
        "FEW_SHOT =",
        "FEW_SHOT.append",
        "FEW_SHOT +=",
        "MIN_SUPPORT_SCORE =",
        "CHUNK_CONFIGS[",
        "object.__setattr__",
        "monkeypatch",
    ):
        assert forbidden not in app, f"app mutates measured state: {forbidden!r}"


def test_app_never_reads_the_credential_value():
    """
    The SDK reads the key from the environment. The app must never read its
    VALUE -- naming the variable in a "set this in .env" message is fine and
    useful; pulling the value into Python is where it can reach session state,
    a log line, or the browser.
    """
    app = (REPO_ROOT / "src" / "firesight" / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        'os.getenv("ANTHROPIC_API_KEY")',
        'os.getenv("OPENAI_API_KEY")',
        'os.environ["ANTHROPIC_API_KEY"]',
        'os.environ["OPENAI_API_KEY"]',
        "os.environ.get(\"ANTHROPIC",
        "api_key=",
    ):
        assert forbidden not in app, f"app reads the credential value: {forbidden!r}"


def test_app_checks_availability_as_a_boolean():
    """It should ask `available()`, which returns True/False and never the key."""
    app = (REPO_ROOT / "src" / "firesight" / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "llm_available()" in app
