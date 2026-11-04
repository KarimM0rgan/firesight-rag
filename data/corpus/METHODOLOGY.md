# FireSight methodology

How every figure this system reports is derived. A user asking *why* a number is
what it is deserves a cited answer, so this document is part of the retrieval
corpus.

> **This document is frozen.** A test asserts its SHA-256 is unchanged
> (`tests/test_corpus_manifest.py`). It is a corpus document, so editing it moves
> retrieval metrics — the freeze exists so that can only happen deliberately, as
> part of a re-measurement, rather than as a side effect of writing
> documentation. To change it: edit, run the suites, update the pinned hash and
> the published metrics in the same commit.
>
> Build artifacts — reconciliation records, evaluation reports, the README — are
> deliberately **not** in the corpus. Only rules and definitions live here.

---

## 1. Data sources

**NFIRS 2024 Public Data Release** (U.S. Fire Administration). 33,312,139
incident records, all of calendar year 2024, and a registry of 37,122 US fire
departments. Caret-delimited, latin-1 encoded flat files.

**One department's local incident export.** 197 incidents, 2025-09-19 to
2026-03-19, carrying dispatch, en-route and on-scene timestamps that NFIRS does
not record.

NFIRS participation is voluntary, so the national file is not a census of US fire
activity.

---

## 2. Department identity

A department is keyed on **`(state, fdid)`**, never on `fdid` alone.

FDID is a five-character identifier assigned by each state, and is unique only
*within* a state. Nationally there are 20,712 distinct FDID values across 37,122
distinct `(state, fdid)` pairs. Joining on FDID alone merges unrelated
departments: for the peer cohort used here it draws in 3,088,042 incident rows
belonging to 2,390 departments in 43 other states — roughly twenty times the
legitimate row count.

The `fdheader` registry also contains duplicate rows for the same
`(state, fdid)`, and some disagree about staffing. Peer eligibility is therefore
decided by whether **any** source row for a pair satisfies the criteria, while
the displayed staffing attributes come from the most complete row. Deciding both
from one arbitrarily chosen row makes cohort membership depend on sort order.

---

## 3. Peer-group definition

A department is a peer of the subject department when all four hold:

| Criterion | Value |
|---|---|
| State | one of TN, GA, AL, KY, NC, VA, MS, AR |
| Career firefighters (`NO_PD_FF`) | fewer than 3 |
| Volunteer firefighters (`NO_VOL_FF`) | 10 to 40 inclusive |
| Stations (`NO_STATION`) | exactly 1 |

**Blank staffing counts.** `NO_PD_FF` is blank for 45% of departments. A blank
career count is read as zero rather than as unknown, which admits departments
that report volunteer and station counts but leave career staffing empty. The
alternative reading excludes them. Both are defensible; this choice is recorded
because it changes cohort size.

**Population served is not available.** NFIRS carries no population field, and
the county FIPS code is blank for 39% of departments. Peer comparison therefore
uses a **proxy**: incident-volume decile crossed with staffing type. That is a
proxy for community size, not a measurement of it.

**The cohort is not a random sample.** The peer criteria require station count
and both headcounts — fields blank for 42% to 63% of departments. Only the
roughly 37% that file complete administrative data can be evaluated at all, and
departments diligent about paperwork may differ systematically from those that
are not. Any ranking carries this caveat.

---

## 4. Response time

### Only alarm-to-arrival exists in NFIRS

The NFIRS incident table records four timestamps: alarm, arrival, incident
controlled, and last unit cleared. There is **no dispatch timestamp and no
en-route timestamp.**

Consequently **turnout time** (dispatch to en route) and **travel time** (en
route to on scene) cannot be computed from NFIRS for any department, in any
year. They are available only for the single department covered by the local
export, and only inside its 2025-09 to 2026-03 window. Total response time is
not a substitute for either; they measure different intervals.

### Parsing

Timestamps are `MMDDYYYYHHMM` and are parsed in full. Reading only the `HHMM`
tail and wrapping negative differences at midnight — a tempting shortcut —
silently converts genuine multi-day incidents into plausible-looking short
durations. Full parsing yields zero negative durations and a small number of
incidents legitimately exceeding 24 hours.

### The filter

```
response_min = arrival_ts - alarm_ts, in minutes
scored when:  0 <= response_min <= 90  AND  the incident is not a non-response type
```

**Zero-minute responses are kept.** A same-minute arrival is a real outcome for a
call adjacent to the station, and discarding zeros removes the fastest tail,
which biases the 90th percentile upward. Since P90 is the headline metric, that
bias would land directly on the main claim.

Supporting evidence for keeping them: incidents coded `111` (building fires) with
a same-minute arrival are spread thinly across many departments rather than
clustered in a few, and almost none carry a placeholder timestamp — the pattern
of genuine station-adjacent response, not of a reporting artifact.

The superseded rule, `response_min > 0`, is retained in parallel columns so every
report can carry a sensitivity row rather than asserting the choice was free.

**The 90-minute cap** excludes a small number of implausible intervals.

### Non-response incident types

Incidents of these NFIRS types never reached a scene, so an alarm-to-arrival
interval is undefined rather than fast, and they are excluded from response-time
statistics:

| Code | Meaning |
|---|---|
| 57, 571 | Cover assignment, standby at fire station, move-up |
| 61, 611 | Dispatched and cancelled en route |

Codes verified individually against the NFIRS code table, at both two- and
three-digit granularity.

Deliberately **not** excluded, because a unit did arrive and the interval is
real: `621`/`62` (wrong location), `622` (no incident found on arrival), and the
entire `7xx` false-alarm series.

### Departments excluded as reporting artifacts

A department's response times are treated as a reporting artifact, and the
department dropped from the benchmark pool, when either holds:

1. **Sentinel evidence.** Its same-minute arrivals are mostly backed by
   placeholder arrival times (`0000` or `9999`), in material quantity. A
   materiality floor is required: most departments holding any placeholder record
   hold only one or two, and condemning a department over a single corrupt row
   would be wrong.
2. **Plausibility floor.** Its same-minute-arrival rate exceeds 25%. One call in
   four arriving in the same clock minute as the alarm is not a credible response
   profile at any department size.

An earlier rule — "more than three times the cohort median rate" — was withdrawn
as unsatisfiable by construction: three times a low median falls below the
cohort's own 90th percentile, so any right-skewed distribution fails it
regardless of the data.

Rankings must be computed over the benchmark pool, not over all reporting
departments.

### Percentile ranks

Percentile ranks use **midpoint tie-handling**: ties contribute half their count.
Many departments share the same whole-minute P90, and a strict comparison would
place the subject department at the top of its own tie group, flattering it.

---

## 5. Local export exclusions

Three independently named rules, each counted at load time:

| Rule | Definition |
|---|---|
| Test records | `natureOfCall` is a test page or training entry |
| Non-finalized records | `reviewStatus` is `archived` |

Draft status is **not** an exclusion. The overwhelming majority of records are
drafts, which reflects workflow adoption rather than data quality; excluding them
would leave too few records to analyse.

---

## 6. What is not reported

**Property loss** is blank for 72% of incidents, so loss totals are not presented
as reliable. **Census tract** is blank for 92%, so no geographic breakdown is
offered. **Station** is blank for 26%, so per-station figures are unreliable.

**NFPA standards** are copyrighted. This project names which standard governs a
topic and never reproduces its thresholds.

**Incident-level personal and location data** from the local export — addresses,
building names, coordinates, personnel identifiers — are never published,
retrieved, or embedded. Aggregate metrics derived from that export may be
reported.
