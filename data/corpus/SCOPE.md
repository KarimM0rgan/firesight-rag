# What this corpus covers, and what it deliberately does not

This document exists so that a refusal can be **cited rather than bare**. When
FireSight declines a question, it should be able to point at a statement of scope
instead of simply failing.

It is part of the retrieval corpus. It is excluded from retrieval scoring, because
a document written to be found by refusal-triggering questions would inflate any
metric measured over those questions.

---

## In scope

**Structured — NFIRS 2024 Public Data Release.** 33,312,139 incident records
covering calendar year 2024, and a registry of 37,122 US fire departments.
Response-time analysis is restricted to the 1,568-department peer cohort and to
**alarm-to-arrival** intervals.

**Structured — one department's local incident export.** 197 incidents,
2025-09-19 to 2026-03-19, carrying the full dispatch → en-route → on-scene chain.
Covers a single department over six months.

**Unstructured — NFIRS documentation.** The NFIRS 5.0 Complete Reference Guide,
Design Documentation, Fire Data Analysis Guidelines and Issues, and the code
dictionary shipped with the Public Data Release. All are US Fire Administration
publications.

**Unstructured — this project's own methodology notes.** How the figures were
computed, which prior numbers reconcile, and which do not.

---

## Out of scope, and why

### NFPA standards

NFPA standards — including 1710 (career department deployment), 1720 (volunteer
department deployment), 1221, 1500 and 13 — are **copyrighted works of the
National Fire Protection Association.** Their text, tables and numeric thresholds
are not reproduced in this corpus and never will be.

FireSight can tell you *which* standard governs a topic. It cannot tell you what
the standard requires. A question of the form "what does NFPA *n* require" is out
of scope: obtain the standard from NFPA directly.

This matters because such questions look, to a similarity search, almost exactly
like in-scope questions. They share the vocabulary of the corpus — fire,
response, staffing, standards, compliance — while their answers sit entirely
outside it. Embedding similarity cannot make that distinction, so it is drawn
here explicitly.

### State and municipal fire codes

State fire marshal regulations, municipal ordinances, and locally adopted code
amendments are not in the corpus. Requirements vary by jurisdiction and are not
derivable from NFIRS.

### Turnout and travel time, outside the one local export

NFIRS records **only two** incident timestamps usable for response analysis:
alarm and arrival. There is no dispatch timestamp and no en-route timestamp in
the NFIRS incident table. Therefore:

- **Turnout time** (dispatch → en route) and **travel time** (en route → on
  scene) **cannot be computed from NFIRS for any department, in any year.**
- They can be computed only for the single department covered by the local
  export, and only within its 2025-09 to 2026-03 window.
- Any question asking for turnout or travel time across the peer cohort, or for
  2024, or for a department other than that one, is out of scope. It is not a
  slow query or a missing join; the data does not exist.

Total response time must not be substituted for either. They measure different
intervals.

### Years other than 2024

The Public Data Release is published one year at a time. This corpus holds the
2024 release only. Multi-year trend questions over NFIRS are out of scope until
further releases are ingested.

### Live, operational and personal data

No current incident status, no staffing rosters, no apparatus availability, no
weather, no dispatch feeds. Nothing outside the fire-service domain.

Incident-level addresses, building names, coordinates and personnel identifiers
from the local export are deliberately **not** in this corpus, even though the
project holds them. Aggregate metrics derived from that export may be reported;
the underlying records may not be retrieved or quoted.

---

## How a refusal should read

A refusal should name the boundary it hit and cite this document. "I don't know"
is weaker than "that figure comes from NFPA 1710, whose text is copyrighted and
outside this corpus — you'll need the standard itself."
