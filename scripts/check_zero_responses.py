"""
Zero-minute response-time distribution check.

Answers one question: are same-minute arrivals spread thinly across the peer
cohort, or are a handful of departments producing them as a reporting artifact?

HISTORY. This originally scored a pre-committed rule whose second test --
"no department's zero rate exceeds 3x the cohort median" -- was unsatisfiable
by construction: with a median of 1.82% the threshold fell to 5.45%, below the
cohort's own P90 of 8.82%, so any right-skewed distribution failed it. That
test has been WITHDRAWN. The replacement is evidence-first:

  (1) SENTINEL EVIDENCE -- a department whose zeros are mostly placeholder
      arrival times ('0000'/'9999'), in material quantity, is flagged on that
      evidence directly, with no rate threshold.
  (2) PLAUSIBILITY FLOOR -- otherwise, flag a zero rate above 25%. One call in
      four arriving in the same clock minute as the alarm is not a credible
      response profile at any department size.

Thresholds live in config.py (ZERO_RATE_IMPLAUSIBLE, SENTINEL_*).

    uv run python scripts/check_zero_responses.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import (  # noqa: E402
    RESPONSE_MIN_CAP,
    ZERO_RATE_IMPLAUSIBLE,
    settings,
)

CAP = RESPONSE_MIN_CAP

# The cohort under test: peer incidents that actually dispatched a response.
# Verified non-response codes are already flagged at ingest.
PEER_VIEW = """
CREATE OR REPLACE TEMP VIEW peer_incidents AS
SELECT state, fdid, inc_type, alarm_ts, arrival_ts, arrival_raw, response_min
FROM incidents
WHERE NOT is_non_response
"""

DEPT_RT = f"""
WITH dept_rt AS (
  SELECT state, fdid,
         COUNT(*) AS n_incidents,
         COUNT(*) FILTER (WHERE response_min = 0) AS n_zero,
         COUNT(*) FILTER (WHERE response_min = 0) * 1.0 / COUNT(*) AS zero_rate
  FROM peer_incidents
  WHERE response_min IS NOT NULL AND response_min <= {CAP}
  GROUP BY state, fdid
  HAVING COUNT(*) >= 30
)
"""

Q1 = (
    DEPT_RT
    + """
SELECT COUNT(*) AS n_depts,
       ROUND(MEDIAN(zero_rate), 4) AS median_zero_rate,
       ROUND(QUANTILE_CONT(zero_rate, 0.90), 4) AS p90_zero_rate,
       ROUND(MAX(zero_rate), 4) AS max_zero_rate,
       SUM(n_zero) AS total_zeros
FROM dept_rt
"""
)

Q2 = (
    DEPT_RT
    + """
SELECT state, fdid, n_incidents, n_zero, ROUND(zero_rate, 3) AS zero_rate,
       ROUND(SUM(n_zero) OVER (ORDER BY n_zero DESC
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 1.0
             / SUM(n_zero) OVER (), 3) AS cum_share_of_all_zeros
FROM dept_rt
ORDER BY n_zero DESC
LIMIT 25
"""
)

Q3 = """
SELECT COUNT(*) FILTER (WHERE alarm_ts = arrival_ts) AS exact_equal,
       COUNT(*) FILTER (WHERE arrival_ts IS NULL)    AS null_arrival,
       COUNT(*) FILTER (WHERE substr(arrival_raw, 9, 4) IN ('0000', '9999')
                           OR arrival_raw IN ('0000', '9999')) AS suspicious_literal
FROM peer_incidents
WHERE response_min = 0
"""

Q4 = """
SELECT p.inc_type,
       COUNT(*) AS n_zero,
       ROUND(COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (), 4) AS share,
       any_value(c.description) AS description
FROM peer_incidents p
LEFT JOIN incident_type_codes c ON c.inc_type = p.inc_type
WHERE p.response_min = 0
GROUP BY p.inc_type
ORDER BY n_zero DESC
LIMIT 15
"""

# Query 5 -- does sentinel evidence explain the high-zero departments?
Q5 = """
SELECT state, fdid, n_scored, n_zero, round(zero_rate, 3) AS zero_rate,
       n_sentinel_zero, sentinel_share_of_zeros,
       flagged_by_sentinel, flagged_by_rate, testable
FROM zero_response_artifacts
WHERE n_sentinel_zero > 0 OR is_zero_artifact
ORDER BY n_zero DESC
LIMIT 25
"""

# What the live rule actually flags.
RULE = f"""
SELECT
  count(*) FILTER (WHERE is_zero_artifact) AS flagged_total,
  count(*) FILTER (WHERE flagged_by_sentinel) AS by_sentinel_evidence,
  count(*) FILTER (WHERE flagged_by_rate) AS by_plausibility_floor,
  count(*) FILTER (WHERE is_zero_artifact AND NOT testable) AS flagged_but_untestable,
  count(*) FILTER (WHERE is_zero_artifact AND n_scored > 10)
    AS flagged_and_in_ranking_pool,
  sum(n_zero) FILTER (WHERE is_zero_artifact) AS zeros_removed,
  sum(n_zero) AS zeros_total,
  {ZERO_RATE_IMPLAUSIBLE} AS floor_threshold
FROM zero_response_artifacts
"""


def show(con, title: str, sql: str) -> list:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    rel = con.sql(sql)
    rel.show(max_rows=30, max_width=200)
    return rel.fetchall()


def main() -> None:
    if not settings.duckdb_path.exists():
        sys.exit(f"No database at {settings.duckdb_path}. Run firesight.ingest.structured first.")
    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    con.execute(PEER_VIEW)

    show(con, "QUERY 1 - Concentration across departments (>=30 incidents)", Q1)
    show(con, "QUERY 2 - Which departments carry the zeros (top 25)", Q2)
    show(con, "QUERY 3 - Real same-minute arrivals or sentinel values", Q3)
    show(con, "QUERY 4 - Incident-type composition of zeros", Q4)
    show(con, "QUERY 5 - Sentinel evidence vs the high-zero departments", Q5)

    (n_flag, n_sent, n_rate, n_untest, n_pool, z_rm, z_tot, thr) = show(
        con, "WHAT THE LIVE RULE FLAGS", RULE
    )[0]

    print(f"\n{'=' * 78}\nOUTCOME\n{'=' * 78}")
    print(f"  flagged departments            : {n_flag}")
    print(f"    by sentinel evidence         : {n_sent}")
    print(f"    by the {thr:.0%} plausibility floor : {n_rate}")
    print(f"  of those, below the testability bar : {n_untest}")
    print(f"  of those, inside the ranking pool   : {n_pool}")
    print(f"  zeros removed from the cohort   : {z_rm:,} of {z_tot:,}")
    con.close()


if __name__ == "__main__":
    main()
