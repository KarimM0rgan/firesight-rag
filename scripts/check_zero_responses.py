"""
Zero-minute response-time distribution check (M1 gate).

Answers one question: are same-minute arrivals spread thinly across the peer
cohort, or are a handful of departments producing them as a reporting artifact?

The decision rule was fixed BEFORE this was run:

  * Top 10 departments hold <25% of all zeros AND no department's zero rate
    exceeds 3x the cohort median  -> diffuse  -> keep zeros everywhere.
  * Otherwise -> concentrated -> exclude the departments whose zero rate
    exceeds 3x the cohort median from the peer pool as a reporting artifact,
    and keep zeros everywhere else.

Either way the primary filter becomes 0 <= response_min <= 90.

    uv run python scripts/check_zero_responses.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import RESPONSE_MIN_CAP, settings  # noqa: E402

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

# Decision-rule inputs, computed separately from the display queries.
RULE = (
    DEPT_RT
    + """
, totals AS (SELECT SUM(n_zero) AS all_zeros, MEDIAN(zero_rate) AS med FROM dept_rt),
  top10 AS (SELECT SUM(n_zero) AS z FROM (
      SELECT n_zero FROM dept_rt ORDER BY n_zero DESC LIMIT 10))
SELECT
  (SELECT z FROM top10) AS top10_zeros,
  (SELECT all_zeros FROM totals) AS all_zeros,
  ROUND((SELECT z FROM top10) * 1.0 / (SELECT all_zeros FROM totals), 4) AS top10_share,
  ROUND((SELECT med FROM totals), 4) AS median_zero_rate,
  ROUND(3 * (SELECT med FROM totals), 4) AS threshold_3x,
  (SELECT COUNT(*) FROM dept_rt WHERE zero_rate > 3 * (SELECT med FROM totals))
    AS n_depts_over_3x,
  (SELECT SUM(n_zero) FROM dept_rt WHERE zero_rate > 3 * (SELECT med FROM totals))
    AS zeros_in_depts_over_3x
FROM totals
"""
)


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

    (t10, allz, share, med, thr, n_over, z_over) = show(
        con, "DECISION RULE INPUTS", RULE
    )[0]

    diffuse_a = share < 0.25
    diffuse_b = n_over == 0
    verdict = "DIFFUSE -> keep zeros" if (diffuse_a and diffuse_b) else "CONCENTRATED"
    print(f"\n{'=' * 78}\nVERDICT\n{'=' * 78}")
    print(f"  (a) top-10 share of all zeros = {share:.1%}  < 25%?  {diffuse_a}")
    print(f"  (b) depts with zero_rate > 3x median ({thr:.4f}) = {n_over}  == 0?  {diffuse_b}")
    print(f"  -> {verdict}")
    if not (diffuse_a and diffuse_b):
        print(
            f"  Artifact departments to exclude from the peer pool: {n_over} "
            f"(holding {z_over:,} of {allz:,} zeros)"
        )
    con.close()


if __name__ == "__main__":
    main()
