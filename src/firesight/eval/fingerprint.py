"""
A cheap signature of the structured store, used to detect stale references.

Reference answers are *values*, not queries, so they go stale the moment the ETL
changes. That happened in practice: the answers were generated while the
zero-artifact rule flagged 134 departments, the rule was later replaced with one
flagging 20, and the SQL suite then scored the model WRONG for returning the
new, correct figures — reporting 35% result accuracy when much of the gap was
the reference file, not the model.

The fingerprint lets a suite refuse to score against a stale file rather than
publish a bad number.
"""

from __future__ import annotations

from firesight.retrieval.sql_guard import execute

FINGERPRINT_SQL = """
SELECT
  (SELECT count(*) FROM metrics_department_year) AS n_metrics,
  (SELECT count(*) FROM incidents) AS n_incidents,
  (SELECT count(*) FROM departments WHERE is_peer) AS n_peers,
  (SELECT count(*) FROM metrics_department_year WHERE is_zero_artifact)
    AS n_artifact,
  (SELECT count(*) FROM metrics_department_year
     WHERE in_benchmark_pool AND n_with_response_time > 10
       AND response_p90_min IS NOT NULL) AS n_pool
"""


def current_fingerprint() -> dict:
    res = execute(FINGERPRINT_SQL, validate_first=False)
    return {k: int(v) for k, v in zip(res.columns, res.rows[0], strict=True)}


def check_against(stored: dict | None) -> dict:
    """Return the fields that drifted, as {field: (stored, live)}."""
    live = current_fingerprint()
    stored = stored or {}
    return {
        k: (stored.get(k), live[k]) for k in live if stored.get(k) != live[k]
    }
