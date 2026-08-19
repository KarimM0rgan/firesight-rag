# Data Profile

**Generated:** 2026-08-19 · **Evidence:** [`profile_stats.json`](profile_stats.json)
· **Reproduce:** `uv run python scripts/profile_source_data.py` (~4 min)

Every number below comes from a full scan of the source files. Nothing is sampled
or estimated. Where a figure disagrees with the prior CS444 benchmarking work,
both numbers are shown and the cause is identified.

---

## 1. Sources

| # | Source | Size | Rows | Coverage |
|---|---|---|---|---|
| A | NFIRS 2024 Public Data Release — `basicincident.txt` | 6.67 GB | 33,312,139 | 52 states, 2024-01-01 → 2024-12-31 |
| B | NFIRS 2024 PDR — `fdheader.txt` (department registry) | 3.73 MB | 37,801 | 57 state codes |
| C | NFIRS 2024 PDR — `codelookup.txt` (code dictionary) | 269 KB | 6,614 | 244 coded fields |
| D | Local department export — `sewanee-incidents.json` | 504 KB | 197 | Sewanee FD, 2025-09-19 → 2026-03-19 |

The PDR ships fifteen more tables (`incidentaddress` 4.49 GB, `ems` 290 MB,
`fireincident` 168 MB, `basicaid`, `arson`, `wildlands`, casualty tables, hazmat
tables). None are used yet; `fireincident` and `incidentaddress` are the likely
M1 extensions.

**Obtaining A–C:** the NFIRS Public Data Release is distributed by the U.S. Fire
Administration at <https://www.usfa.fema.gov/nfirs/public-data-release/>. The
2024 archive is `nfirs_all_incident_pdr_2024.zip` (1.52 GB compressed, ~12 GB
extracted). It is public domain but far too large to commit; point
`FIRESIGHT_NFIRS_DIR` at your extracted copy.

**Obtaining D:** an export from the department's incident-reporting system. It is
**not redistributable** — see §7.

### File format

NFIRS flat files are **caret-delimited** (`^`), `latin-1` encoded, with a quoted
header row. Fields are inconsistently quoted: strings are quoted, numerics
usually are not, and empty numerics appear as bare `^^`. Read with
`delim='^', quote='"', all_varchar=true, encoding='latin-1'` and cast explicitly;
letting a reader infer types silently drops rows.

---

## 2. `fdheader` — department registry

18 columns. One row per department per reporting year, keyed by `(STATE, FDID)`.

| Column | Meaning | Notes |
|---|---|---|
| `STATE` | 2-letter code | 57 distinct values — includes territories and non-state codes |
| `FDID` | Fire department ID | **5-char string, unique only within a state.** Leading zeros are significant |
| `FD_NAME` | Department name | 5 blank |
| `FD_CITY`, `FD_ZIP`, `FD_STREET`… | Mailing address | |
| `FD_FIP_CTY` | County FIPS | 39.2% blank |
| `NO_STATION` | Station count | **63.0% blank** |
| `NO_PD_FF` | Career firefighters | **45.2% blank** |
| `NO_VOL_FF` | Volunteer firefighters | **41.7% blank** |
| `NO_VOL_PDC` | Paid-per-call volunteers | |

**Key cardinality:** 37,801 rows → 37,122 distinct `(STATE, FDID)` but only
**20,712 distinct `FDID`**. FDID alone is not a key. 677 `(STATE, FDID)` pairs
appear more than once (e.g. `RI/00200` ×3, `NH/71430` ×3) — deduplicate on
ingest.

Sewanee FD is `('TN', '26161')`: 1 station, 0 career, 19 volunteer.

---

## 3. `basicincident` — the incident table

42 columns, 33,312,139 rows, one row per incident.

**`INCIDENT_KEY` is a genuine primary key** — 33,312,139 distinct values, zero
duplicate groups. Format: `{STATE}_{FDID}_{MMDDYYYY}_{INC_NO}_{EXP_NO}`.

**Date coverage is exactly one year.** All 33.3M rows parse as `MMDDYYYY`, zero
malformed, min 2024-01-01, max 2024-12-31. There is no multi-year history here
(see §6, conflict 3).

**The file is sorted by `STATE`** (AK first, WY last). This matters — see §5.

### Blank rates on relevant columns

| Column | Blank | % | Consequence |
|---|---:|---:|---|
| `ALARM` (alarm time) | 0 | 0.00% | always present |
| `INC_TYPE` | 0 | 0.00% | always present |
| `AID` (mutual-aid flag) | 0 | 0.00% | always present |
| `LU_CLEAR` (last unit cleared) | 4,121 | 0.01% | usable |
| `PROP_USE` | 1,992,928 | 5.98% | usable |
| `ARRIVAL` | 2,000,784 | 6.01% | **no response time for these** |
| `DEPT_STA` (station) | 8,694,933 | 26.10% | per-station breakdown unreliable |
| `PROP_LOSS` (dollar loss) | 24,069,650 | 72.26% | **loss totals are not trustworthy** |
| `CENSUS` (census tract) | 30,579,784 | 91.80% | no geographic joins |
| `INC_CONT` (contained time) | 31,748,600 | 95.31% | **effectively unusable** |

### Timestamps available

`ALARM`, `ARRIVAL`, `INC_CONT`, `LU_CLEAR` — all `MMDDYYYYHHMM`.

There is **no dispatch time and no en-route time** in this table. Only *total*
response (`ARRIVAL − ALARM`) can be computed from NFIRS; turnout and travel
cannot. See §6, conflict 1.

### Incident mix (national, top 10 of 246 `INC_TYPE` codes)

| Code | Count | % | Description |
|---|---:|---:|---|
| 321 | 15,262,430 | 45.8% | EMS call, excluding vehicle accident with injury |
| 311 | 2,818,060 | 8.5% | Medical assist, assist EMS crew |
| 611 | 2,518,693 | 7.6% | Dispatched & cancelled en route |
| 322 | 1,030,524 | 3.1% | Vehicle accident with injuries |
| 554 | 840,896 | 2.5% | Assist invalid |
| 320 | 753,779 | 2.3% | Emergency medical service, other |
| 324 | 751,262 | 2.3% | Motor vehicle accident with no injuries |
| 300 | 700,002 | 2.1% | Rescue, emergency medical call, other |
| 745 | 687,475 | 2.1% | Alarm system sounded, no fire — unintentional |
| 622 | 621,885 | 1.9% | No incident found on arrival at dispatch address |

Fire is a small minority of "fire department" activity — code `111` (building
fires) does not reach the top 10. Any question phrased as "how many fires" needs
the router to disambiguate *fire* from *incident*.

---

## 4. Peer-group definition and reconciliation

The prior work benchmarks Sewanee against similar departments. That definition
is now pinned in [`src/firesight/config.py`](../src/firesight/config.py):

```
STATE ∈ {TN, GA, AL, KY, NC, VA, MS, AR}
NO_PD_FF  < 3          (not career-staffed)
NO_VOL_FF ∈ [10, 40]   (comparable size)
NO_STATION = 1         (single station)
```

Applying it to `fdheader` on the correct `(STATE, FDID)` key yields **1,568 peer
departments**:

| TN | NC | AL | MS | KY | VA | AR | GA |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 373 | 342 | 224 | 172 | 149 | 134 | 132 | 42 |

Of those, **936 reported at least one 2024 incident**, contributing 151,759
incident rows.

### Blank staffing counts

`NO_PD_FF` is blank for 45.2% of all departments. For 112 departments that
otherwise qualify, career staffing is blank while volunteer count and station
count are populated. Reading blank as *zero career staff* admits them (1,568
peers); reading it as *unknown* excludes them (1,456 peers).

The prior work read blank as zero — `int(x or 0)` — so that is the default here
(`PeerCriteria.blank_staffing_as_zero = True`), because flipping it breaks
reconciliation. It is defensible independently: 76 of the 112 have "Volunteer" or
"VFD" in the department name. The flag exists so the alternative can be measured
rather than argued about.

### Sewanee reconciles exactly

| Metric | This profile | `nfirs_dept_summary_v2.csv` | Notebook output |
|---|---:|---:|---:|
| 2024 incidents | 283 | 283 | 283 |
| With usable response time | 272 | 272 | 272 |
| Median response (min) | 6.0 | 6.0 | 6.0 |
| P90 response (min) | 13.0 | 13.0 | 13.0 |
| P95 response (min) | 18.9 | 18.9 | — |
| % ≤ 8 min | 72.4% | 72.4% | — |

Sewanee's own figures survive because FDID `26161` happens to be unique
nationally. The *peer* figures do not — see §5.

### The peer-pool count does not reconcile

`sewanee_dashboards.ipynb` reports **"Peer pool: 1138 depts | TN: 255"**. The
correct figure is **779** departments with more than 10 usable response times
(935 with at least one). The 1,138 is inflated by the FDID collision described in
§5: incidents belonging to unrelated departments were added to peer buckets,
pushing low-volume departments over the `> 10` threshold.

**Consequence:** the published rankings — *"Sewanee P90 rank: top 29% regionally,
top 13% in TN"* and *"compliance rank: top 22% regionally, top 9% in TN"* — were
computed against a contaminated pool and must be recomputed in M1 before they are
quoted anywhere. The resume framing in the spec (§6, "1,100+ departments") should
become **~780** or **1,568**, depending on whether the count is
*benchmarkable* or *identified*.

---

## 5. Known data-quality issues

**① FDID is not unique nationally — the prior extracts are contaminated.**
FDID is unique only within a state, but `filter_nfirs.py`, `nfirs_summarize_v2.py`
and `nfirs_monthly_agg.py` all match with `if fdid in peers`, ignoring `STATE`.
3,885 departments across 43 states share an FDID with a peer. Matching state-blind
pulls in **3,088,042 extra incident rows from 2,390 unrelated departments** —
20× the 151,759 legitimate peer rows.
*Fix:* always join on `(STATE, FDID)`. Enforced by `PeerCriteria.sql_predicate()`.

**② `nfirs_incidents_raw.csv` is a truncated scan and must not be reused.**
Its 780,864 rows cover only 8 states — AK, AL, AR, AZ, CA, CO, CT, FL — with
**no TN rows at all**, meaning it contains none of Sewanee's own incidents. Since
`basicincident` is sorted by `STATE`, this is consistent with a scan that stopped
around the FL block, roughly a quarter of the way through the file. (DC and DE are
absent legitimately: neither has any FDID overlapping the peer set.) Every state
present except AL and AR is outside the 8-state peer region, which is issue ①
showing through.
*Fix:* regenerate from source in M1; do not import this file.

**③ Response time was computed from the time-of-day only.**
`parse_datetime()` in the prior scripts reads just the `HHMM` tail of the
12-character timestamp and wraps negatives by adding 1,440 minutes. A call
alarmed 23:50 on one day and arrived 00:10 the next gives the right answer by
luck; a genuine multi-day incident is silently converted to a plausible-looking
short duration. Parsing the full `MMDDYYYYHHMM`: **zero negative durations** and
**36 incidents genuinely exceeding 24 hours** in the peer set.
*Fix:* parse the full timestamp (`TRY_STRPTIME(..., '%m%d%Y%H%M')`).

**④ 10.2% of peer `ARRIVAL` timestamps do not parse.**
15,547 of 151,759 peer rows. These are blanks and malformed values, not a parser
defect — `ALARM` has zero parse failures on the same rows.

**⑤ Zero-minute responses are dropped by the inherited filter.**
The `0 < rt <= 90` window excludes 5,229 peer incidents (3.4%) recorded as
arriving in the same minute as the alarm. That is plausible for a call at the
station and implausible as a blanket rule. Retaining them lowers median response.
*Decision needed in M1:* keep the inherited filter for continuity, or switch to
`0 <= rt <= 90` and re-baseline. Either way, state it.

**⑥ The 90-minute cap is doing real work.**
268 peer incidents exceed 90 minutes and 36 exceed a full day. After all filters,
130,715 of 151,759 peer rows (86.1%) yield a usable response time.

**⑦ Staffing and station counts are mostly absent.**
`NO_STATION` blank 63.0%, `NO_PD_FF` blank 45.2%, `NO_VOL_FF` blank 41.7%. The
peer filter requires all three, so it silently restricts to the ~37% of
departments that report staffing at all. This is a **selection effect, not a
random sample** — departments that file complete administrative data plausibly
also respond faster. Name this in the M6 failure analysis.

**⑧ 677 duplicate `(STATE, FDID)` rows in `fdheader`.**
Deduplicate on ingest; picking an arbitrary row changes staffing values and can
move a department in or out of the peer set.

**⑨ The local export has an uncontrolled call-type vocabulary.**
197 records carry **50 distinct `natureOfCall` values**, including near-duplicates
(`Automatic Alarm` 49, `FIRE ALARM` 47, `72A FIRE ALARM` 6) and non-incidents
(`TEST TEST CALL` 6, `SATURDAY TEST PAGE` 6). There is no mapping to NFIRS
`INC_TYPE` codes.
*Fix:* build an explicit crosswalk in M1; do not let the LLM infer it per query.

---

## 6. Conflicts between the spec and the data

**Conflict 1 — spec §3.2 expects `incidents` to carry "alarm / dispatch / en route
/ arrival" timestamps.** NFIRS `basicincident` has alarm and arrival only. Turnout
(`enRoute − dispatched`) and travel (`onScene − enRoute`) cannot be derived from
it at all.
*Proposal:* NFIRS supports **total response time only**. Turnout and travel come
from source D, which has the full chain but covers one department and six months.
Keep them in separate tables with different grains rather than forcing one schema;
the router must not compare a NFIRS P90 against a local-export P90 as though they
measured the same interval.

**Conflict 2 — spec §3.2 expects `departments.population_served`.** No such column
exists in `fdheader`, and `FD_FIP_CTY` is 39.2% blank, so even a county-level
Census join would cover ~61% of departments.
*Proposal:* drop `population_served`. The peer group is defined by staffing,
station count, and region — which is what the prior work actually used.

**Conflict 3 — spec §3.2 expects `metrics_department_year`.** The 2024 PDR is a
single year, so the `year` dimension has exactly one value and the table is not
usefully a time series.
*Proposal:* build `metrics_department` for the cross-sectional 2024 benchmark and
`metrics_department_month` from the monthly grain (which does vary and supports
trend questions). Add earlier PDR years later if multi-year trend matters — each
is a separate ~1.5 GB download.

**Conflict 4 — spec §6 resume framing says "1,100+ departments".** See §4: the
supportable figures are 1,568 identified peers or 779 benchmarkable ones.

---

## 7. Local export (source D) — schema and privacy

197 records, 2025-09-19 → 2026-03-19. Fields: `id`, `externalIncidentId`,
`address`, `buildingName`, `coordinates`, `receivedTime`, `dispatchedTime`,
`enRouteTime`, `onSceneTime`, `natureOfCall`, `source`, `reviewStatus`,
`apparatus[]` (with per-unit `dispatchTime`/`enRouteTime`/`onSceneTime` and
`personnel[]`), `povPersonnel`, `actionsTaken`, `createdAt`, `updatedAt`.

| Field | Present | Notes |
|---|---:|---|
| `receivedTime` | 183 / 197 | |
| `dispatchedTime` | 180 / 197 | |
| `onSceneTime` | 167 / 197 | |
| `enRouteTime` | 161 / 197 | scarcest link in the chain |
| `coordinates` | 173 / 197 | |
| `apparatus[]` non-empty | 152 / 197 | |
| any personnel recorded | 136 / 197 | |

`reviewStatus`: draft 183, ready_for_review 12, approved 1, archived 1.
`source`: manual 113, cad_email 84.

Derived (all records, no test-call exclusion, 0–90 min window):

| Interval | n | P50 | P90 |
|---|---:|---:|---:|
| Total response (`onScene − dispatched`) | 139 | 5.0 min | 11.0 min |
| Turnout (`enRoute − dispatched`) | 158 | 1.0 min | 4.0 min |
| Travel (`onScene − enRoute`) | 152 | 2.0 min | 8.0 min |

The prior notebook reports 182 records after excluding 15 test/archived, n=130,
median 4.0, P90 11.0. **P90 matches; the median differs** because this profile has
not yet applied the test-call exclusion. That filter (≥12 identifiable test pages
plus archived records) must be reimplemented explicitly in M1 — it is currently
undocumented outside the notebook.

> **Privacy — this data must not go into the public repo or the vector index.**
> Records carry street addresses, named campus buildings, GPS coordinates, and
> personnel identifiers for real incidents at a real department. `data/raw/` is
> gitignored, but the constraint is stronger than that: aggregate metrics derived
> from source D may be published; individual records, addresses, and personnel
> references may not be embedded into Chroma or surfaced by the demo UI. M2 must
> enforce this at ingest, not by prompt instruction.

---

## 8. Unstructured corpus — current status

**Nothing has been acquired yet.** On hand and usable:

- `codelookup.txt` — 6,614 NFIRS code definitions across 244 fields (USFA, public
  domain). Directly answers definitional questions like *"how does NFIRS define a
  structure fire?"* and doubles as the crosswalk for issue ⑨.
- The prior project's `documentation.md` — the author's own methodology notes on
  metric definitions and their limitations. Own work, freely usable.

Still to acquire in M2 (all public domain / publicly posted): the NFIRS Complete
Reference Guide and Design Documentation, USFA topical research reports, state
fire marshal reporting guidance, and municipal annual reports.

NFPA 1710/1720 remain **off limits** as text. The 8-minute and 4-minute thresholds
used throughout are cited by standard number and section, never quoted.

---

## 9. What M1 inherits

1. Join on `(STATE, FDID)`. Never on FDID alone.
2. Parse full `MMDDYYYYHHMM` timestamps, not the `HHMM` tail.
3. Rebuild from `basicincident.txt`; treat `nfirs_incidents_raw.csv` and
   `nfirs_dept_summary_v2.csv` as suspect prior output, useful only for
   reconciliation.
4. Reconcile every rebuilt metric against §4's table. Sewanee's six figures must
   match exactly; the peer-pool count is expected *not* to, and 779 is the target.
5. Decide and document the zero-minute-response question (issue ⑤).
6. Build the `natureOfCall` → `INC_TYPE` crosswalk explicitly.
7. Recompute the peer rankings — the published "top 29% / top 13%" figures are
   not currently defensible.
