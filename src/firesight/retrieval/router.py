"""
Question router: structured / unstructured / hybrid / out_of_scope.

An LLM classifier with a strict output schema. The model returns JSON, which is
validated against `RouterDecision` before anything acts on it -- a free-text
route name is a bug, not a thing to pattern-match.

## The excluded-material distinction

The hard case is not "weather in Nashville". It is a question that is squarely
about the fire service, shares every keyword with the corpus, and whose answer
lives in material the corpus deliberately excludes:

    "What turnout time does NFPA 1710 require?"
    "What was the peer-group median turnout time in 2024?"
    "What does the Tennessee fire code require for sprinklers?"

Embedding similarity cannot make this call. Measured: the held-out question
"What is the recommended pressure for a fire sprinkler system under NFPA 13?"
scores 0.740 against this corpus -- above the 0.70 support floor and above the
0.730 floor of genuine in-corpus questions. No threshold separates them, which
is why the distinction is given to the router explicitly instead.

These route `out_of_scope`, not `unstructured`, and they are scored as their own
category in the confusion matrix.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError

from firesight.generation.llm import LLMError, complete


class Route(StrEnum):
    STRUCTURED = "structured"
    UNSTRUCTURED = "unstructured"
    HYBRID = "hybrid"
    OUT_OF_SCOPE = "out_of_scope"


class ExclusionReason(StrEnum):
    """Why an in-domain question is nonetheless out of scope."""

    NONE = "none"
    NFPA_STANDARD = "nfpa_standard"
    STATE_OR_LOCAL_CODE = "state_or_local_code"
    TIMESTAMP_NOT_RECORDED = "timestamp_not_recorded"
    YEAR_NOT_COVERED = "year_not_covered"
    OUTSIDE_DOMAIN = "outside_domain"
    LIVE_OR_PERSONAL_DATA = "live_or_personal_data"


class RouterDecision(BaseModel):
    """Strict schema. Anything the model returns that does not fit is rejected."""

    model_config = {"extra": "forbid"}

    route: Route
    exclusion_reason: ExclusionReason = ExclusionReason.NONE
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=400)

    def model_post_init(self, _ctx) -> None:
        # An out_of_scope verdict must say why; an in-scope one must not claim a
        # reason. Catches the model hedging its way between the two.
        if self.route is Route.OUT_OF_SCOPE and self.exclusion_reason is ExclusionReason.NONE:
            raise ValueError("out_of_scope requires a non-none exclusion_reason")
        if (
            self.route is not Route.OUT_OF_SCOPE
            and self.exclusion_reason is not ExclusionReason.NONE
        ):
            raise ValueError(f"{self.route.value} must have exclusion_reason 'none'")


@dataclass
class RoutingResult:
    question: str
    decision: RouterDecision | None
    raw: str = ""
    error: str | None = None
    attempts: int = 0
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    schema_violations: list[str] = field(default_factory=list)

    @property
    def route(self) -> Route | None:
        return self.decision.route if self.decision else None


PROMPT = """You classify questions about fire-service data into exactly one of \
four routes.

## THE DATA THIS SYSTEM HAS

A. STRUCTURED TABLES (SQL)
   - 33.3M NFIRS incident records, calendar year 2024 only, for a 1,568-department
     peer cohort. Per-incident: date, incident type code, alarm time, arrival
     time, property loss, casualties, station.
   - Pre-aggregated per-department metrics: incident counts, response-time
     percentiles (p50/p90/p95), 8-minute and 4-minute compliance rates, peer
     rankings.
   - A registry of 37,122 US fire departments: name, state, staffing counts,
     station count.
   - ONE department's own export, 2025-09 to 2026-03, 197 incidents, with
     dispatch, en-route and on-scene timestamps.

B. DOCUMENTS (vector search)
   - NFIRS 5.0 Complete Reference Guide, Design Documentation, Fire Data
     Analysis Guidelines, and the NFIRS code dictionary. Definitions, field
     semantics, incident type codes, module structure, reporting rules.
   - This project's own methodology notes.

## ROUTES

"structured"   - answerable by querying the tables. Counts, rates, percentiles,
                 rankings, trends, comparisons between departments.
"unstructured" - answerable from the documents. Definitions, what a code means,
                 which module to file, how a field is meant to be used.
"hybrid"       - genuinely needs BOTH: a number from the tables AND a definition,
                 rule or standard from the documents, together in one answer.
"out_of_scope" - cannot be answered from either, including questions that are
                 about the fire service but whose answer is in excluded material.

## OUT_OF_SCOPE IS NOT ONLY FOR OFF-TOPIC QUESTIONS

Route out_of_scope, with the matching exclusion_reason, when:

- "nfpa_standard" - the question asks what an NFPA standard REQUIRES or
  RECOMMENDS (1710, 1720, 1221, 1500, 13, any other). NFPA text is copyrighted
  and deliberately absent. Naming which standard governs a topic is fine;
  stating its thresholds is not.
- "state_or_local_code" - the question asks about a state fire marshal
  regulation, municipal ordinance, or locally adopted code.
- "timestamp_not_recorded" - the question asks for TURNOUT time (dispatch to
  en route) or TRAVEL time (en route to on scene) for the peer cohort, for
  2024, or for any department other than the one local export. NFIRS records
  only alarm and arrival. These intervals do not exist in the data.
  EXCEPTION: turnout or travel for THAT ONE department, within 2025-09 to
  2026-03, IS answerable -> route "structured".
- "year_not_covered" - the question needs NFIRS data from a year other than
  2024, or a multi-year trend across releases.
- "live_or_personal_data" - current incident status, rosters, apparatus
  availability, weather, or an identifiable person or address.
- "outside_domain" - nothing to do with the fire service.

A question that merely SOUNDS like the corpus is not in scope. "What sprinkler
pressure does NFPA 13 require" shares every keyword with these documents and is
still out_of_scope.

## OUTPUT

Return ONLY a JSON object, no prose, no code fence:

{{"route": "...", "exclusion_reason": "...", "confidence": 0.0-1.0, "reason": "..."}}

- "route" is one of: structured, unstructured, hybrid, out_of_scope
- "exclusion_reason" is one of: none, nfpa_standard, state_or_local_code,
  timestamp_not_recorded, year_not_covered, live_or_personal_data,
  outside_domain
- Use "none" for every route except out_of_scope. out_of_scope must NOT use
  "none".
- "reason" is one short sentence.

## EXAMPLES

Question: What was our p90 response time in 2023?
{{"route": "out_of_scope", "exclusion_reason": "year_not_covered",
 "confidence": 0.95, "reason": "NFIRS coverage is 2024 only."}}

Question: How does NFIRS define a structure fire?
{{"route": "unstructured", "exclusion_reason": "none",
 "confidence": 0.96, "reason": "A definition from the reference guide."}}

Question: How many building fires did peer departments report in 2024?
{{"route": "structured", "exclusion_reason": "none",
 "confidence": 0.95, "reason": "A count from the incident table."}}

Question: How does our p90 response time compare to peers, and does it meet the applicable standard?
{{"route": "hybrid", "exclusion_reason": "none", "confidence": 0.88,
 "reason": "Needs a percentile from the tables plus the applicable standard."}}

Question: What turnout time does NFPA 1710 require?
{{"route": "out_of_scope", "exclusion_reason": "nfpa_standard",
 "confidence": 0.94, "reason": "NFPA thresholds are copyrighted."}}

Question: What is our median turnout time?
{{"route": "structured", "exclusion_reason": "none", "confidence": 0.85,
 "reason": "The local export has dispatch and en-route timestamps."}}

Question: What's the weather in Nashville?
{{"route": "out_of_scope", "exclusion_reason": "outside_domain",
 "confidence": 0.99, "reason": "Not fire-service data."}}

## QUESTION

{question}

JSON:"""

JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def _parse(raw: str) -> RouterDecision:
    """Extract and validate the JSON object. Tolerates a stray code fence."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    match = JSON_OBJ.search(text)
    if not match:
        raise ValueError(f"no JSON object in reply: {text[:160]!r}")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    return RouterDecision.model_validate(payload)


def route(question: str, *, max_retries: int = 1) -> RoutingResult:
    """
    Classify `question`. One retry if the model breaks the schema.

    A schema violation is recorded rather than silently coerced -- how often the
    model fails to produce valid output is itself a reported metric.
    """
    t0 = time.perf_counter()
    res = RoutingResult(question=question, decision=None)
    feedback = ""

    for _ in range(max_retries + 1):
        res.attempts += 1
        try:
            reply = complete(PROMPT.format(question=question) + feedback, max_tokens=300)
        except LLMError as e:
            res.error = f"model call failed: {e}"
            res.latency_ms = (time.perf_counter() - t0) * 1000
            return res

        res.input_tokens += reply.input_tokens
        res.output_tokens += reply.output_tokens
        res.cost_usd += reply.cost_usd
        res.raw = reply.text

        try:
            res.decision = _parse(reply.text)
            res.error = None
            break
        except (ValueError, ValidationError) as e:
            msg = str(e).splitlines()[0][:200]
            res.schema_violations.append(msg)
            res.error = msg
            feedback = (
                "\n\nYour previous reply was rejected by the schema validator:\n"
                f"{msg}\nReturn ONLY the JSON object, with valid enum values.\n"
            )

    res.latency_ms = (time.perf_counter() - t0) * 1000
    return res


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        sys.exit('usage: python -m firesight.retrieval.router "question"')
    r = route(" ".join(sys.argv[1:]))
    print(f"\nQ: {r.question}")
    if r.decision:
        d = r.decision
        print(f"   route            : {d.route.value}")
        print(f"   exclusion_reason : {d.exclusion_reason.value}")
        print(f"   confidence       : {d.confidence:.2f}")
        print(f"   reason           : {d.reason}")
    else:
        print(f"   FAILED: {r.error}")
    print(f"\n{r.latency_ms:.0f} ms | {r.attempts} attempt(s) | ${r.cost_usd:.5f}")


if __name__ == "__main__":
    main()
