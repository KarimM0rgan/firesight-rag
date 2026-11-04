"""
Build the DuckDB structured store from the NFIRS 2024 PDR + the local export.

    uv run python -m firesight.ingest.structured

Design decisions that matter, all forced by findings in data/PROFILE.md:

* Departments are keyed on ``(state, fdid)``. FDID alone is not unique
  nationally; matching on it pulls 3.1M incident rows from 2,390 unrelated
  departments into the peer pool (PROFILE.md issue 1).
* Timestamps are parsed from the full ``MMDDYYYYHHMM``, never the HHMM tail
  (PROFILE.md issue 3).
* ``incidents.response_min`` is stored RAW and UNFILTERED, including zeros,
  negatives and multi-day values, alongside the raw source strings. Every
  filter is applied at query time so the inherited and current definitions can
  both be reported from one ingest.
* ``incidents`` covers the peer cohort only (~152k rows). ``departments``
  covers all US departments. See ``docs`` in schema.py for the scope note.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import duckdb

from firesight.config import (
    LEGACY_TEST_EXCLUSION,
    NON_FINALIZED_RECORDS,
    NON_RESPONSE_INCIDENT_TYPES,
    RESPONSE_MIN_CAP,
    SEWANEE_FDID,
    SEWANEE_STATE,
    TEST_RECORD_FLAGS,
    PeerCriteria,
    settings,
)

READ_OPTS = "delim='^', quote='\"', header=true, all_varchar=true, encoding='latin-1'"


def _src(path) -> str:
    return f"read_csv('{path.as_posix()}', {READ_OPTS})"


def _sql_list(values) -> str:
    return ", ".join(f"'{v}'" for v in sorted(values))


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


# ──────────────────────────────────────────────────────────────────────────
# departments
# ──────────────────────────────────────────────────────────────────────────
def build_departments(con: duckdb.DuckDBPyConnection) -> None:
    """
    One row per (state, fdid).

    fdheader has 677 duplicate pairs and some of them disagree about staffing:
    NC/00713 reports vol_ff as both 0 and 38. That makes peer eligibility
    sensitive to an arbitrary row choice -- picking the lower row drops the
    department, picking the higher drops others whose larger row falls outside
    the 10-40 band. Either tie-break silently changes the cohort.

    So eligibility and attributes are decoupled: `is_peer` is true if ANY
    fdheader row for the pair satisfies the criteria (matching how the M0
    profiler counted, which is the reconciliation target), while the displayed
    staffing attributes come from the most complete row.
    `has_conflicting_staffing_rows` makes the ambiguity visible rather than
    burying it in a sort order.
    """
    con.execute(f"""
    CREATE OR REPLACE TABLE departments AS
    WITH raw AS (
      SELECT
        STATE AS state,
        FDID  AS fdid,
        nullif(trim(FD_NAME), '')    AS fd_name,
        nullif(trim(FD_CITY), '')    AS city,
        nullif(trim(FD_ZIP), '')     AS zip,
        nullif(trim(FD_FIP_CTY), '') AS county_fips,
        TRY_CAST(NO_STATION AS INTEGER) AS stations,
        TRY_CAST(NO_PD_FF   AS INTEGER) AS paid_ff,
        TRY_CAST(NO_VOL_FF  AS INTEGER) AS vol_ff,
        TRY_CAST(NO_VOL_PDC AS INTEGER) AS vol_paid_per_call
      FROM {_src(settings.fdheader_file)}
    ),
    -- Eligibility: does ANY row for this pair qualify?
    eligible AS (
      SELECT DISTINCT state, fdid, true AS qualifies
      FROM raw
      WHERE {settings.peers.sql_predicate(columns=PeerCriteria.TYPED_COLUMNS, cast=False)}
    ),
    conflicts AS (
      SELECT state, fdid
      FROM raw
      GROUP BY state, fdid
      HAVING count(DISTINCT coalesce(vol_ff, -1)) > 1
          OR count(DISTINCT coalesce(paid_ff, -1)) > 1
          OR count(DISTINCT coalesce(stations, -1)) > 1
    ),
    -- Attributes: the most complete row, deterministically chosen.
    ranked AS (
      SELECT *, row_number() OVER (
        PARTITION BY state, fdid
        ORDER BY (stations IS NULL)::INT + (paid_ff IS NULL)::INT + (vol_ff IS NULL)::INT,
                 coalesce(vol_ff, 0) + coalesce(paid_ff, 0) DESC,
                 coalesce(stations, 0) DESC,
                 fd_name NULLS LAST
      ) AS rn
      FROM raw
    )
    SELECT
      r.state, r.fdid, r.fd_name, r.city, r.zip, r.county_fips,
      r.stations, r.paid_ff, r.vol_ff, r.vol_paid_per_call,
      CASE
        WHEN r.paid_ff IS NULL AND r.vol_ff IS NULL THEN 'unknown'
        WHEN coalesce(r.vol_ff, 0) = 0 AND coalesce(r.paid_ff, 0) > 0 THEN 'career'
        WHEN coalesce(r.paid_ff, 0) = 0 AND coalesce(r.vol_ff, 0) > 0 THEN 'volunteer'
        WHEN coalesce(r.paid_ff, 0) > 0 AND coalesce(r.vol_ff, 0) > 0 THEN 'combination'
        ELSE 'unknown'
      END AS staffing_type,
      -- Peer-filter inputs are 42-63% blank; this flags whether a department
      -- could even be evaluated. See PROFILE.md issue 7.
      (r.stations IS NOT NULL AND r.vol_ff IS NOT NULL) AS reports_staffing,
      (c.state IS NOT NULL) AS has_conflicting_staffing_rows,
      (coalesce(e.qualifies, false)
        OR (r.state = '{SEWANEE_STATE}' AND r.fdid = '{SEWANEE_FDID}')) AS is_peer,
      (r.state = '{SEWANEE_STATE}' AND r.fdid = '{SEWANEE_FDID}') AS is_sewanee
    FROM ranked r
    LEFT JOIN eligible  e ON e.state = r.state AND e.fdid = r.fdid
    LEFT JOIN conflicts c ON c.state = r.state AND c.fdid = r.fdid
    WHERE r.rn = 1
    """)
    n, peers, sew = con.execute(
        "SELECT count(*), sum(is_peer::INT), sum(is_sewanee::INT) FROM departments"
    ).fetchone()
    log(f"departments: {n:,} rows | {peers:,} peers | sewanee present={bool(sew)}")


# ──────────────────────────────────────────────────────────────────────────
# incident_type_codes
# ──────────────────────────────────────────────────────────────────────────
def build_incident_type_codes(con: duckdb.DuckDBPyConnection) -> None:
    """NFIRS INC_TYPE dictionary straight from the PDR's own code table."""
    con.execute(f"""
    CREATE OR REPLACE TABLE incident_type_codes AS
    SELECT trim(code_value) AS inc_type,
           trim(code_descr) AS description,
           length(trim(code_value)) AS code_digits,
           -- NFIRS series: 1=fire, 2=overpressure, 3=EMS/rescue, 4=hazcon,
           -- 5=service, 6=good intent, 7=false alarm, 8=severe weather, 9=special
           substr(trim(code_value), 1, 1) AS series
    FROM {_src(settings.codelookup_file)}
    WHERE fieldid = 'INC_TYPE' AND nullif(trim(code_value), '') IS NOT NULL
    """)
    (n,) = con.execute("SELECT count(*) FROM incident_type_codes").fetchone()
    log(f"incident_type_codes: {n:,} rows")


# ──────────────────────────────────────────────────────────────────────────
# incidents (peer cohort)
# ──────────────────────────────────────────────────────────────────────────
def build_incidents(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
    CREATE OR REPLACE TABLE incidents AS
    SELECT
      b.INCIDENT_KEY AS incident_key,
      b.STATE AS state,
      b.FDID  AS fdid,
      TRY_STRPTIME(trim(b.INC_DATE), '%m%d%Y')::DATE AS inc_date,
      trim(b.INC_NO)   AS inc_no,
      trim(b.INC_TYPE) AS inc_type,
      nullif(trim(b.DEPT_STA), '') AS station,
      trim(b.AID) AS aid_code,
      -- raw source strings retained so parse failures stay auditable
      nullif(trim(b.ALARM), '')   AS alarm_raw,
      nullif(trim(b.ARRIVAL), '') AS arrival_raw,
      TRY_STRPTIME(trim(b.ALARM),    '%m%d%Y%H%M') AS alarm_ts,
      TRY_STRPTIME(trim(b.ARRIVAL),  '%m%d%Y%H%M') AS arrival_ts,
      TRY_STRPTIME(trim(b.LU_CLEAR), '%m%d%Y%H%M') AS last_unit_cleared_ts,
      -- UNFILTERED: may be negative, zero, or multi-day. Filter at query time.
      date_diff('second',
                TRY_STRPTIME(trim(b.ALARM),   '%m%d%Y%H%M'),
                TRY_STRPTIME(trim(b.ARRIVAL), '%m%d%Y%H%M')) / 60.0 AS response_min,
      TRY_CAST(nullif(trim(b.PROP_LOSS), '') AS BIGINT) AS property_loss_usd,
      TRY_CAST(nullif(trim(b.CONT_LOSS), '') AS BIGINT) AS content_loss_usd,
      TRY_CAST(nullif(trim(b.FF_INJ),    '') AS INTEGER) AS ff_injuries,
      TRY_CAST(nullif(trim(b.OTH_INJ),   '') AS INTEGER) AS other_injuries,
      TRY_CAST(nullif(trim(b.FF_DEATH),  '') AS INTEGER) AS ff_deaths,
      TRY_CAST(nullif(trim(b.OTH_DEATH), '') AS INTEGER) AS other_deaths,
      nullif(trim(b.PROP_USE), '') AS property_use,
      -- Verified non-response codes: dispatched-and-cancelled, and station
      -- cover/move-up assignments. Never reached a scene, so an alarm-to-
      -- arrival interval is not defined for them.
      (trim(b.INC_TYPE) IN ({_sql_list(NON_RESPONSE_INCIDENT_TYPES)})) AS is_non_response
    FROM {_src(settings.basicincident_file)} b
    JOIN departments d ON d.state = b.STATE AND d.fdid = b.FDID
    WHERE d.is_peer
    """)
    n, depts = con.execute(
        "SELECT count(*), count(DISTINCT (state, fdid)) FROM incidents"
    ).fetchone()
    log(f"incidents: {n:,} rows across {depts:,} departments")


# ──────────────────────────────────────────────────────────────────────────
# zero_response_artifacts
# ──────────────────────────────────────────────────────────────────────────
def build_zero_artifacts(con: duckdb.DuckDBPyConnection) -> None:
    """
    Flag departments whose same-minute-arrival rate marks their timestamps as a
    reporting artifact rather than fast response.

    Rule fixed BEFORE the distribution was examined (see
    scripts/check_zero_responses.py). The check returned CONCENTRATED:
    top-10 departments held 21.6% of zeros (< 25%, passes), but 134
    departments exceeded 3x the cohort median zero rate of 1.82% (fails).
    The pre-committed consequence is to drop those specific departments from
    the benchmark pool and keep zeros everywhere else.

    Only departments with >= 30 scored incidents are testable; smaller ones
    cannot be distinguished from noise and are left in, flagged `untestable`.
    """
    cap = RESPONSE_MIN_CAP
    con.execute(f"""
    CREATE OR REPLACE TABLE zero_response_artifacts AS
    WITH dept_rt AS (
      SELECT state, fdid,
             count(*) AS n_scored,
             count(*) FILTER (WHERE response_min = 0) AS n_zero,
             count(*) FILTER (WHERE response_min = 0) * 1.0 / count(*) AS zero_rate
      FROM incidents
      WHERE NOT is_non_response
        AND response_min IS NOT NULL AND response_min <= {cap}
      GROUP BY state, fdid
    ),
    cohort AS (SELECT median(zero_rate) AS med FROM dept_rt WHERE n_scored >= 30)
    SELECT d.state, d.fdid, d.n_scored, d.n_zero, round(d.zero_rate, 4) AS zero_rate,
           round((SELECT med FROM cohort), 4) AS cohort_median_zero_rate,
           round(3 * (SELECT med FROM cohort), 4) AS threshold,
           d.n_scored >= 30 AS testable,
           (d.n_scored >= 30 AND d.zero_rate > 3 * (SELECT med FROM cohort))
             AS is_zero_artifact
    FROM dept_rt d
    """)
    n_art, n_test, sew_art = con.execute("""
      SELECT sum(is_zero_artifact::INT), sum(testable::INT),
             max(CASE WHEN state='TN' AND fdid='26161' THEN is_zero_artifact::INT END)
      FROM zero_response_artifacts
    """).fetchone()
    log(
        f"zero_response_artifacts: {n_art} artifact departments of {n_test} testable "
        f"| sewanee flagged={bool(sew_art)}"
    )


# ──────────────────────────────────────────────────────────────────────────
# metrics_department_year
# ──────────────────────────────────────────────────────────────────────────
def build_metrics(con: duckdb.DuckDBPyConnection) -> None:
    """
    Pre-aggregated per-department-per-year metrics so the SQL agent never
    recomputes percentiles over the incident table.

    The `year` dimension currently holds a single value (2024) because the PDR
    is one year per release. The column stays so another year can land without
    a schema change.

    Response-time metrics use the primary filter 0 <= response_min <= 90 and
    exclude verified non-response incident types. `_legacy` columns reproduce
    the inherited 0 < response_min definition for the sensitivity row.
    """
    cap = RESPONSE_MIN_CAP
    con.execute(f"""
    CREATE OR REPLACE TABLE metrics_department_year AS
    WITH base AS (
      SELECT i.state, i.fdid, year(i.inc_date) AS year, i.inc_type, i.response_min,
             NOT i.is_non_response AS responded,
             CASE WHEN NOT i.is_non_response
                       AND i.response_min BETWEEN 0 AND {cap}
                  THEN i.response_min END AS rt,
             CASE WHEN NOT i.is_non_response
                       AND i.response_min > 0 AND i.response_min <= {cap}
                  THEN i.response_min END AS rt_legacy
      FROM incidents i
    ),
    agg AS (
      SELECT
        state, fdid, year,
        count(*) AS n_incidents,
        count(*) FILTER (WHERE responded) AS n_response_incidents,
        count(*) FILTER (WHERE NOT responded) AS n_non_response_incidents,
        count(rt) AS n_with_response_time,
        count(rt_legacy) AS n_with_response_time_legacy,
        count(*) FILTER (WHERE inc_type LIKE '1%') AS n_fire,
        count(*) FILTER (WHERE inc_type LIKE '3%') AS n_ems_rescue,
        count(*) FILTER (WHERE inc_type LIKE '5%') AS n_service,
        count(*) FILTER (WHERE inc_type LIKE '7%') AS n_false_alarm,
        round(median(rt), 2) AS response_p50_min,
        round(quantile_cont(rt, 0.90), 2) AS response_p90_min,
        round(quantile_cont(rt, 0.95), 2) AS response_p95_min,
        round(avg(rt), 2) AS response_mean_min,
        round(100.0 * count(*) FILTER (WHERE rt <= 8) / nullif(count(rt), 0), 1)
          AS pct_within_8min,
        round(100.0 * count(*) FILTER (WHERE rt <= 4) / nullif(count(rt), 0), 1)
          AS pct_within_4min,
        round(median(rt_legacy), 2) AS response_p50_min_legacy,
        round(quantile_cont(rt_legacy, 0.90), 2) AS response_p90_min_legacy,
        round(100.0 * count(*) FILTER (WHERE rt_legacy <= 8)
              / nullif(count(rt_legacy), 0), 1) AS pct_within_8min_legacy
      FROM base
      GROUP BY state, fdid, year
    )
    SELECT
      a.*,
      d.fd_name, d.city, d.staffing_type, d.stations, d.paid_ff, d.vol_ff,
      d.is_sewanee,
      coalesce(z.is_zero_artifact, false) AS is_zero_artifact,
      z.zero_rate,
      -- The benchmark pool. Peer rankings MUST filter on this column, not on
      -- departments.is_peer: zero-artifact departments are excluded here as a
      -- reporting artifact, per the pre-committed rule.
      NOT coalesce(z.is_zero_artifact, false) AS in_benchmark_pool,
      -- Peer proxy standing in for the population-served column NFIRS lacks:
      -- incident-volume decile within the cohort, crossed with staffing type.
      ntile(10) OVER (PARTITION BY a.year ORDER BY a.n_incidents)
        AS volume_decile,
      d.staffing_type || '_d' ||
        lpad((ntile(10) OVER (PARTITION BY a.year ORDER BY a.n_incidents))::VARCHAR, 2, '0')
        AS peer_group
    FROM agg a
    JOIN departments d ON d.state = a.state AND d.fdid = a.fdid
    LEFT JOIN zero_response_artifacts z ON z.state = a.state AND z.fdid = a.fdid
    """)
    n, yrs = con.execute(
        "SELECT count(*), count(DISTINCT year) FROM metrics_department_year"
    ).fetchone()
    log(f"metrics_department_year: {n:,} rows | {yrs} distinct year(s)")


# ──────────────────────────────────────────────────────────────────────────
# local export
# ──────────────────────────────────────────────────────────────────────────
def _iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None) if s else None


def build_local_incidents(con: duckdb.DuckDBPyConnection) -> None:
    """
    The department's own export. Separate grain from `incidents`: it has the
    full dispatch -> en-route -> on-scene chain that NFIRS lacks, but covers
    one department for six months.

    Addresses, building names, coordinates and personnel identifiers are NOT
    loaded. PROFILE.md section 7 forbids them leaving the raw file; the metrics
    this project reports never need them.
    """
    path = settings.local_incidents
    if not path.exists():
        log(f"local_incidents: SKIPPED (not found: {path})")
        return

    records = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for r in records:
        nature = (r.get("natureOfCall") or "").strip()
        status = (r.get("reviewStatus") or "").strip()
        rows.append(
            {
                "local_id": r.get("id"),
                "external_incident_id": r.get("externalIncidentId"),
                "nature_of_call": nature or None,
                "nature_normalized": nature.upper() or None,
                "source": r.get("source"),
                "review_status": status or None,
                "received_ts": _iso(r.get("receivedTime")),
                "dispatched_ts": _iso(r.get("dispatchedTime")),
                "en_route_ts": _iso(r.get("enRouteTime")),
                "on_scene_ts": _iso(r.get("onSceneTime")),
                "n_apparatus": len(r.get("apparatus") or []),
                "n_personnel": sum(
                    len(a.get("personnel") or []) for a in (r.get("apparatus") or [])
                )
                + len(r.get("povPersonnel") or []),
                "has_coordinates": bool((r.get("coordinates") or {}).get("latitude")),
                # Exclusion flags, each independently named and auditable.
                "is_test_record": nature.upper() in TEST_RECORD_FLAGS,
                "is_non_finalized": status in NON_FINALIZED_RECORDS,
                "is_legacy_excluded": (
                    nature.upper() in LEGACY_TEST_EXCLUSION or status in NON_FINALIZED_RECORDS
                ),
            }
        )

    columns = [
        ("local_id", "VARCHAR"),
        ("external_incident_id", "VARCHAR"),
        ("nature_of_call", "VARCHAR"),
        ("nature_normalized", "VARCHAR"),
        ("source", "VARCHAR"),
        ("review_status", "VARCHAR"),
        ("received_ts", "TIMESTAMP"),
        ("dispatched_ts", "TIMESTAMP"),
        ("en_route_ts", "TIMESTAMP"),
        ("on_scene_ts", "TIMESTAMP"),
        ("n_apparatus", "INTEGER"),
        ("n_personnel", "INTEGER"),
        ("has_coordinates", "BOOLEAN"),
        ("is_test_record", "BOOLEAN"),
        ("is_non_finalized", "BOOLEAN"),
        ("is_legacy_excluded", "BOOLEAN"),
    ]
    coldefs = ", ".join(f"{name} {dtype}" for name, dtype in columns)
    placeholders = ", ".join("?" * len(columns))
    con.execute("DROP TABLE IF EXISTS local_incidents_raw")
    con.execute(f"CREATE TABLE local_incidents_raw ({coldefs})")
    con.executemany(
        f"INSERT INTO local_incidents_raw VALUES ({placeholders})",
        [tuple(r[name] for name, _ in columns) for r in rows],
    )
    con.execute("""
    CREATE OR REPLACE TABLE local_incidents AS
    SELECT *,
      date_diff('second', dispatched_ts, on_scene_ts) / 60.0 AS total_response_min,
      date_diff('second', dispatched_ts, en_route_ts)  / 60.0 AS turnout_min,
      date_diff('second', en_route_ts,   on_scene_ts)  / 60.0 AS travel_min
    FROM local_incidents_raw
    """)
    con.execute("DROP TABLE local_incidents_raw")

    n, test, nonfinal = con.execute("""
      SELECT count(*), sum(is_test_record::INT), sum(is_non_finalized::INT)
      FROM local_incidents
    """).fetchone()
    log(f"local_incidents: {n:,} rows | {test} test records | {nonfinal} non-finalized")


# ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"Building {settings.duckdb_path}", flush=True)
    con = duckdb.connect(str(settings.duckdb_path))
    con.execute("SET preserve_insertion_order=false")

    for step in (
        build_departments,
        build_incident_type_codes,
        build_incidents,
        build_zero_artifacts,
        build_metrics,
        build_local_incidents,
    ):
        step(con)

    con.execute("CREATE INDEX IF NOT EXISTS idx_inc_dept ON incidents(state, fdid)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_inc_type ON incidents(inc_type)")
    con.close()
    print(f"\nDone in {time.time() - t0:.1f}s -> {settings.duckdb_path}")


if __name__ == "__main__":
    main()
