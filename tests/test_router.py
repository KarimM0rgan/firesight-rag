"""
Router tests: the strict output schema, parsing, and the labelled set's shape.

None of these need an API key. The classifier call is mocked; what is being
tested is that a malformed or self-contradictory model reply is REJECTED rather
than coerced into a route.
"""

import json

import pytest
from pydantic import ValidationError

from firesight.config import REPO_ROOT
from firesight.retrieval.router import (
    ExclusionReason,
    Route,
    RouterDecision,
    _parse,
    route,
)


def _questions() -> list[dict]:
    path = REPO_ROOT / "eval" / "router_questions.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


QUESTIONS = _questions()


# ── the strict schema ─────────────────────────────────────────────────────
def test_four_routes_exactly():
    assert [r.value for r in Route] == [
        "structured",
        "unstructured",
        "hybrid",
        "out_of_scope",
    ]


def test_valid_decision_is_accepted():
    d = RouterDecision.model_validate(
        {
            "route": "hybrid",
            "exclusion_reason": "none",
            "confidence": 0.82,
            "reason": "needs a number and a definition",
        }
    )
    assert d.route is Route.HYBRID
    assert d.exclusion_reason is ExclusionReason.NONE


@pytest.mark.parametrize(
    "payload,why",
    [
        ({"route": "sql", "exclusion_reason": "none", "confidence": 0.9, "reason": "x"},
         "invented route name"),
        ({"route": "STRUCTURED", "exclusion_reason": "none", "confidence": 0.9, "reason": "x"},
         "wrong case"),
        ({"route": "structured", "exclusion_reason": "whatever", "confidence": 0.9, "reason": "x"},
         "invented exclusion reason"),
        ({"route": "structured", "exclusion_reason": "none", "confidence": 1.4, "reason": "x"},
         "confidence above 1"),
        ({"route": "structured", "exclusion_reason": "none", "confidence": -0.1, "reason": "x"},
         "confidence below 0"),
        ({"route": "structured", "exclusion_reason": "none", "confidence": 0.9, "reason": ""},
         "empty reason"),
        ({"route": "structured", "exclusion_reason": "none", "confidence": 0.9},
         "missing reason"),
        ({"exclusion_reason": "none", "confidence": 0.9, "reason": "x"},
         "missing route"),
        ({"route": "structured", "exclusion_reason": "none", "confidence": 0.9,
          "reason": "x", "notes": "extra"},
         "extra field"),
    ],
)
def test_malformed_decisions_are_rejected(payload, why):
    with pytest.raises((ValidationError, ValueError)):
        RouterDecision.model_validate(payload)


def test_out_of_scope_must_give_a_reason():
    """A refusal that cannot say why it refused is not usable."""
    with pytest.raises((ValidationError, ValueError)):
        RouterDecision.model_validate(
            {
                "route": "out_of_scope",
                "exclusion_reason": "none",
                "confidence": 0.9,
                "reason": "x",
            }
        )


def test_in_scope_route_must_not_claim_an_exclusion_reason():
    """Catches the model hedging between routing in and routing out."""
    with pytest.raises((ValidationError, ValueError)):
        RouterDecision.model_validate(
            {
                "route": "unstructured",
                "exclusion_reason": "nfpa_standard",
                "confidence": 0.9,
                "reason": "x",
            }
        )


# ── parsing the model's reply ─────────────────────────────────────────────
def test_parses_bare_json():
    d = _parse('{"route":"structured","exclusion_reason":"none","confidence":0.9,"reason":"ok"}')
    assert d.route is Route.STRUCTURED


def test_parses_json_inside_a_code_fence():
    raw = (
        '```json\n{"route":"hybrid","exclusion_reason":"none",'
        '"confidence":0.7,"reason":"ok"}\n```'
    )
    assert _parse(raw).route is Route.HYBRID


def test_parses_json_with_surrounding_prose():
    raw = (
        'Here you go:\n{"route":"unstructured","exclusion_reason":"none",'
        '"confidence":0.8,"reason":"ok"}\nHope that helps.'
    )
    assert _parse(raw).route is Route.UNSTRUCTURED


@pytest.mark.parametrize("raw", ["", "   ", "structured", "no json here", "{not json}"])
def test_unparseable_replies_raise(raw):
    with pytest.raises((ValueError, ValidationError)):
        _parse(raw)


# ── retry behaviour ───────────────────────────────────────────────────────
def test_schema_violation_triggers_one_retry_and_is_recorded(monkeypatch):
    import firesight.retrieval.router as R
    from firesight.generation.llm import Reply

    calls = {"n": 0}

    def fake(prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return Reply("route: structured", 10, 5, 0.0, "m")  # not JSON
        return Reply(
            '{"route":"structured","exclusion_reason":"none",'
            '"confidence":0.9,"reason":"recovered"}',
            10,
            5,
            0.0,
            "m",
        )

    monkeypatch.setattr(R, "complete", fake)
    r = route("How many fires in 2024?")
    assert calls["n"] == 2
    assert r.attempts == 2
    assert r.route is Route.STRUCTURED
    assert len(r.schema_violations) == 1
    assert r.error is None


def test_persistent_schema_violation_yields_no_decision(monkeypatch):
    import firesight.retrieval.router as R
    from firesight.generation.llm import Reply

    monkeypatch.setattr(R, "complete", lambda *a, **k: Reply("nope", 1, 1, 0.0, "m"))
    r = route("anything")
    assert r.decision is None
    assert r.route is None
    assert len(r.schema_violations) == 2  # initial + one retry


def test_retry_feedback_quotes_the_violation(monkeypatch):
    import firesight.retrieval.router as R
    from firesight.generation.llm import Reply

    seen = []

    def fake(prompt, **kw):
        seen.append(prompt)
        return Reply("still not json", 1, 1, 0.0, "m")

    monkeypatch.setattr(R, "complete", fake)
    route("anything")
    assert len(seen) == 2
    assert "rejected by the schema validator" in seen[1]


# ── the labelled set ──────────────────────────────────────────────────────
def test_labelled_set_covers_all_four_routes_with_at_least_40_questions():
    assert len(QUESTIONS) >= 40
    assert {q["expected_route"] for q in QUESTIONS} == {r.value for r in Route}


def test_every_label_is_a_valid_route():
    valid = {r.value for r in Route}
    assert all(q["expected_route"] in valid for q in QUESTIONS)


def test_at_least_five_adversarial_excluded_material_cases():
    """
    The cases that justify giving the router this distinction at all:
    similarity cannot separate them, so they must be labelled and scored.
    """
    excluded = [q for q in QUESTIONS if q.get("category") == "excluded_material"]
    assert len(excluded) >= 5
    assert all(q["expected_route"] == "out_of_scope" for q in excluded)
    # Spanning the three named kinds, not five variants of one.
    kinds = {q["excluded_reason"] for q in excluded}
    assert {"nfpa_standard", "state_or_local_code", "timestamp_not_recorded"} <= kinds


def test_every_out_of_scope_question_declares_an_exclusion_reason():
    valid = {r.value for r in ExclusionReason} - {"none"}
    for q in QUESTIONS:
        if q["expected_route"] == "out_of_scope":
            assert q.get("excluded_reason") in valid, q["id"]


def test_in_scope_questions_declare_no_exclusion_reason():
    for q in QUESTIONS:
        if q["expected_route"] != "out_of_scope":
            assert "excluded_reason" not in q, q["id"]


def test_question_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_the_nfpa_13_question_is_labelled_out_of_scope():
    """
    The held-out gate failure (h16, 0.740 similarity) is the reason the router
    needs this distinction. The same question must be labelled here.
    """
    match = [q for q in QUESTIONS if "NFPA 13" in q["question"]]
    assert match
    assert all(q["expected_route"] == "out_of_scope" for q in match)
    assert all(q["excluded_reason"] == "nfpa_standard" for q in match)


def test_turnout_is_in_scope_locally_but_out_of_scope_for_peers():
    """
    The subtle case: turnout exists in the local export and nowhere else, so
    the same metric is routable or not depending on who is being asked about.
    """
    local = [q for q in QUESTIONS if q["id"] == "r10"]
    peers = [q for q in QUESTIONS if q["id"] == "r40"]
    assert local and peers
    assert local[0]["expected_route"] == "structured"
    assert peers[0]["expected_route"] == "out_of_scope"
    assert peers[0]["excluded_reason"] == "timestamp_not_recorded"
