"""
The schema description injected into the text-to-SQL prompt.

Bad schema descriptions cause most text-to-SQL failures, so this is written
out by hand rather than generated from ``DESCRIBE``: it carries units, the
filter conventions a correct query must apply, and the three things the model
must refuse to do. Keep it in sync with ingest/structured.py.
"""

from __future__ import annotations

from firesight.config import (
    NON_RESPONSE_INCIDENT_TYPES,
    RESPONSE_MIN_CAP,
    settings,
)

SCHEMA = f"""
DATABASE: DuckDB. Four tables. All of them are read-only.

### departments  (37,122 rows -- every US fire department in the NFIRS registry)
  state                          VARCHAR  2-letter postal code
  fdid                           VARCHAR  NFIRS department id, 5 chars, LEADING ZEROS
                                          MATTER. Unique only WITHIN a state.
  fd_name, city, zip             VARCHAR
  county_fips                    VARCHAR  39% NULL
  stations                       INTEGER  station count, 63% NULL
  paid_ff                        INTEGER  career firefighters, 45% NULL
  vol_ff                         INTEGER  volunteer firefighters, 42% NULL
  vol_paid_per_call              INTEGER
  staffing_type                  VARCHAR  'career' | 'volunteer' | 'combination' | 'unknown'
  reports_staffing               BOOLEAN  staffing fields populated at all
  has_conflicting_staffing_rows  BOOLEAN  duplicate source rows disagreed
  is_peer                        BOOLEAN  in Sewanee's comparison cohort (1,568 depts)
  is_sewanee                     BOOLEAN  exactly one row is true

### incidents  (151,759 rows -- 2024 incidents for the PEER COHORT ONLY)
  incident_key           VARCHAR    primary key, globally unique
  state, fdid            VARCHAR    join to departments on BOTH columns
  inc_date               DATE       2024-01-01 .. 2024-12-31 (one calendar year)
  inc_no                 VARCHAR    department's own incident number
  inc_type               VARCHAR    NFIRS code, 1-3 digits. Join incident_type_codes.
                                    Series: '1%'=fire, '3%'=EMS/rescue, '5%'=service,
                                    '6%'=good intent, '7%'=false alarm
  station                VARCHAR    26% NULL
  aid_code               VARCHAR    mutual-aid given/received
  alarm_raw/arrival_raw  VARCHAR    original MMDDYYYYHHMM strings, for auditing
  alarm_ts               TIMESTAMP  time the alarm was received
  arrival_ts             TIMESTAMP  time the first unit arrived. 6% NULL nationally.
  last_unit_cleared_ts   TIMESTAMP
  response_min           DOUBLE     MINUTES, (arrival_ts - alarm_ts). *** UNFILTERED ***
                                    May be NULL, 0, negative, or multi-day.
                                    ALWAYS filter it -- see RESPONSE TIME below.
  property_loss_usd      BIGINT     72% NULL -- do NOT report loss totals as reliable
  content_loss_usd       BIGINT
  ff_injuries, other_injuries, ff_deaths, other_deaths  INTEGER
  property_use           VARCHAR
  is_non_response        BOOLEAN    TRUE for incident types where no unit reached a
                                    scene ({", ".join(sorted(NON_RESPONSE_INCIDENT_TYPES))}:
                                    cancelled en route, station cover assignment).
                                    EXCLUDE these from response-time statistics.

### metrics_department_year  (936 rows -- ONE ROW PER DEPARTMENT PER YEAR)
Pre-aggregated. Prefer this over recomputing percentiles from `incidents`.
  state, fdid, year               year is 2024 for every row (the PDR is one year)
  fd_name, city, staffing_type, stations, paid_ff, vol_ff, is_sewanee
  n_incidents                     INTEGER  all incidents
  n_response_incidents            INTEGER  excluding is_non_response
  n_non_response_incidents        INTEGER
  n_with_response_time            INTEGER  rows scoring a usable response time
  n_fire, n_ems_rescue, n_service, n_false_alarm   INTEGER  by NFIRS series
  response_p50_min                DOUBLE   MINUTES
  response_p90_min                DOUBLE   MINUTES  <- the headline metric
  response_p95_min                DOUBLE   MINUTES
  response_mean_min               DOUBLE   MINUTES
  pct_within_8min                 DOUBLE   PERCENT 0-100, share arriving <= 8 min
  pct_within_4min                 DOUBLE   PERCENT 0-100
  volume_decile                   INTEGER  1-10, incident-volume decile in the cohort
  peer_group                      VARCHAR  staffing_type + volume decile, e.g.
                                           'volunteer_d07'. This is the PROXY for
                                           population served, which NFIRS lacks.
  is_zero_artifact                BOOLEAN  same-minute-arrival rate > 3x cohort median
  zero_rate                       DOUBLE   0-1
  in_benchmark_pool               BOOLEAN  *** FILTER ON THIS for any ranking or
                                           peer comparison *** (= NOT is_zero_artifact)
  response_p50_min_legacy         DOUBLE   superseded definition, sensitivity only
  response_p90_min_legacy         DOUBLE   superseded definition, sensitivity only
  pct_within_8min_legacy          DOUBLE   superseded definition, sensitivity only

### incident_type_codes  (245 rows -- the NFIRS code dictionary)
  inc_type     VARCHAR  join to incidents.inc_type
  description  VARCHAR  e.g. '111' -> 'Building fires'
  code_digits  INTEGER  1, 2 or 3
  series       VARCHAR  first digit

### local_incidents  (197 rows -- Sewanee's OWN export, 2025-09-19 .. 2026-03-19)
Different grain and a different time window from `incidents`. It is the ONLY
source with the full dispatch -> en-route -> on-scene chain.
  local_id, external_incident_id, nature_of_call, nature_normalized, source
  review_status        VARCHAR    'draft' | 'ready_for_review' | 'approved' | 'archived'
  received_ts, dispatched_ts, en_route_ts, on_scene_ts   TIMESTAMP
  n_apparatus, n_personnel   INTEGER
  has_coordinates            BOOLEAN
  is_test_record             BOOLEAN  test pages / training entries -- EXCLUDE
  is_non_finalized           BOOLEAN  archived -- EXCLUDE
  is_legacy_excluded         BOOLEAN  superseded rule, reconciliation only
  total_response_min   DOUBLE   MINUTES  on_scene - dispatched
  turnout_min          DOUBLE   MINUTES  en_route  - dispatched
  travel_min           DOUBLE   MINUTES  on_scene  - en_route

## RESPONSE TIME -- the filter every response-time query must apply

  WHERE NOT is_non_response
    AND response_min BETWEEN 0 AND {RESPONSE_MIN_CAP}

Zero-minute responses are KEPT: they are same-minute arrivals, and dropping
them removes the fastest tail and biases P90 upward. The `*_legacy` columns
hold the superseded `response_min > 0` definition for sensitivity reporting
only -- never use them to answer a question unless explicitly asked to compare
the two definitions.

## HARD CONSTRAINTS

1. NFIRS records ONLY alarm-to-arrival. There is no dispatch timestamp and no
   en-route timestamp in `incidents`, so turnout time and travel time CANNOT be
   computed from it, for any department or any year. If a question asks for
   turnout, travel, or a breakdown of response into components, the only data
   that supports it is `local_incidents` -- one department, six months, outside
   the 2024 window. Say so. Do not substitute total response time and do not
   invent a decomposition.
2. Join departments and incidents on BOTH state AND fdid. `fdid` alone is not
   unique and joining on it alone silently merges unrelated departments.
3. Any ranking or peer comparison must filter `in_benchmark_pool`.
4. `incidents` covers the peer cohort only. It cannot answer national questions
   about incident counts. `departments` does cover all US departments.
5. The benchmarkable cohort is the ~37% of departments that file complete
   staffing data, not a random sample of US fire departments.
"""


FEW_SHOT: list[tuple[str, str]] = [
    (
        "What was Sewanee's P90 response time in 2024?",
        """SELECT response_p90_min, n_with_response_time
FROM metrics_department_year
WHERE is_sewanee AND year = 2024""",
    ),
    (
        "How does Sewanee's P90 response time compare to its peer departments?",
        """WITH pool AS (
  SELECT response_p90_min, is_sewanee
  FROM metrics_department_year
  WHERE year = 2024
    AND in_benchmark_pool
    AND n_with_response_time > 10
    AND response_p90_min IS NOT NULL
)
SELECT
  (SELECT response_p90_min FROM pool WHERE is_sewanee) AS sewanee_p90_min,
  round(median(response_p90_min), 2) AS peer_median_p90_min,
  count(*) AS peer_pool_size,
  round(100.0 * (count(*) FILTER (
          WHERE response_p90_min < (SELECT response_p90_min FROM pool WHERE is_sewanee))
        + 0.5 * count(*) FILTER (
          WHERE response_p90_min = (SELECT response_p90_min FROM pool WHERE is_sewanee)))
        / count(*), 1) AS sewanee_percentile
FROM pool""",
    ),
    (
        "How many building fires did peer departments report in 2024?",
        """SELECT count(*) AS n_building_fires
FROM incidents
WHERE inc_type = '111' AND year(inc_date) = 2024""",
    ),
    (
        "Which five peer departments in Tennessee had the fastest P90 response times?",
        """SELECT fd_name, city, response_p90_min, n_with_response_time
FROM metrics_department_year
WHERE state = 'TN'
  AND year = 2024
  AND in_benchmark_pool
  AND n_with_response_time > 10
  AND response_p90_min IS NOT NULL
ORDER BY response_p90_min ASC
LIMIT 5""",
    ),
    (
        "What share of Sewanee's 2024 calls were false alarms?",
        """SELECT n_false_alarm, n_incidents,
       round(100.0 * n_false_alarm / nullif(n_incidents, 0), 1) AS pct_false_alarm
FROM metrics_department_year
WHERE is_sewanee AND year = 2024""",
    ),
    (
        "What are the ten most common incident types among peer departments?",
        """SELECT i.inc_type, any_value(c.description) AS description, count(*) AS n
FROM incidents i
LEFT JOIN incident_type_codes c ON c.inc_type = i.inc_type
GROUP BY i.inc_type
ORDER BY n DESC
LIMIT 10""",
    ),
    (
        "What was Sewanee's median response time by month in 2024?",
        """SELECT date_trunc('month', i.inc_date) AS month,
       count(*) AS n_scored,
       round(median(i.response_min), 2) AS median_response_min
FROM incidents i
JOIN departments d ON d.state = i.state AND d.fdid = i.fdid
WHERE d.is_sewanee
  AND NOT i.is_non_response
  AND i.response_min BETWEEN 0 AND 90
GROUP BY month
ORDER BY month""",
    ),
    (
        "What is Sewanee's turnout time?",
        """-- NFIRS cannot answer this: `incidents` has no dispatch or en-route
-- timestamp. Only the local export carries the full chain, and it covers
-- 2025-09 to 2026-03 rather than 2024.
SELECT count(*) AS n_scored,
       round(median(turnout_min), 2) AS median_turnout_min,
       round(quantile_cont(turnout_min, 0.90), 2) AS p90_turnout_min,
       min(dispatched_ts)::DATE AS window_start,
       max(dispatched_ts)::DATE AS window_end
FROM local_incidents
WHERE NOT is_test_record
  AND NOT is_non_finalized
  AND turnout_min BETWEEN 0 AND 90""",
    ),
]


def build_prompt(question: str, error_feedback: str | None = None) -> str:
    """Assemble the text-to-SQL prompt. One retry appends `error_feedback`."""
    shots = "\n\n".join(
        f"Question: {q}\nSQL:\n```sql\n{s}\n```" for q, s in FEW_SHOT
    )
    retry = ""
    if error_feedback:
        retry = (
            "\n\nYour previous attempt failed. Fix it.\n"
            f"Error:\n{error_feedback}\n"
            "Return corrected SQL only.\n"
        )
    return f"""{SCHEMA}

## EXAMPLES

{shots}

## YOUR TASK

Write ONE DuckDB SELECT statement answering the question below.

Rules:
- Output only SQL, in a single ```sql fenced block. No prose outside it.
- SELECT only. No INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/ATTACH, no multiple
  statements, no reading files.
- Queries are capped at {settings.sql_row_limit} rows; add your own tighter
  LIMIT when the question implies one.
- If the schema genuinely cannot answer the question, return a SELECT that
  returns the closest supportable fact, with a leading SQL comment saying what
  is missing. Never invent a column.

Question: {question}{retry}
SQL:"""
