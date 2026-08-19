"""
Profile the raw source data behind FireSight (M0 deliverable).

Reads the NFIRS 2024 Public Data Release and the local department incident
export, computes row counts / null rates / date coverage / data-quality
checks, and writes the raw numbers to data/profile_stats.json -- the evidence
behind every figure quoted in data/PROFILE.md.

Nothing here is estimated. Every number is a full scan or an exact count.

    uv run python scripts/profile_source_data.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firesight.config import (  # noqa: E402
    REGION_STATES,
    REPO_ROOT,
    SEWANEE_FDID,
    SEWANEE_STATE,
    settings,
)

OUT = REPO_ROOT / "data" / "profile_stats.json"

# NFIRS flat files are caret-delimited, latin-1, with a quoted header row.
READ_OPTS = "delim='^', quote='\"', header=true, all_varchar=true, encoding='latin-1'"

STATES_SQL = ", ".join(f"'{s}'" for s in sorted(REGION_STATES))


def fd(path: Path) -> str:
    return f"read_csv('{path.as_posix()}', {READ_OPTS})"


def q1(con, sql: str):
    """Run a query expected to return one row; return it as a plain tuple."""
    return con.execute(sql).fetchone()


def qall(con, sql: str):
    return con.execute(sql).fetchall()


def peer_cte(blank_staffing_as_zero: bool | None = None) -> str:
    """
    The peer set, matched on (STATE, FDID) -- the correct key.

    FDID is only unique WITHIN a state, so matching on FDID alone pulls in
    unrelated departments nationwide. See data/PROFILE.md.
    """
    crit = settings.peers
    if blank_staffing_as_zero is not None:
        crit = replace(crit, blank_staffing_as_zero=blank_staffing_as_zero)
    return f"""
    WITH peers AS (
      SELECT DISTINCT STATE, FDID FROM {fd(settings.fdheader_file)}
      WHERE {crit.sql_predicate()}
      UNION
      SELECT '{SEWANEE_STATE}', '{SEWANEE_FDID}'
    )
    """


def profile_fdheader(con) -> dict:
    src = fd(settings.fdheader_file)

    rows, n_state, n_fdid, n_pair = q1(
        con,
        f"""
        SELECT count(*), count(DISTINCT STATE), count(DISTINCT FDID),
               count(DISTINCT (STATE, FDID))
        FROM {src}
        """,
    )

    # Blank rates on the columns the peer filter depends on.
    blanks = q1(
        con,
        f"""
        SELECT
          sum(CASE WHEN NO_STATION IS NULL OR trim(NO_STATION)='' THEN 1 ELSE 0 END),
          sum(CASE WHEN NO_PD_FF   IS NULL OR trim(NO_PD_FF)='' THEN 1 ELSE 0 END),
          sum(CASE WHEN NO_VOL_FF  IS NULL OR trim(NO_VOL_FF)='' THEN 1 ELSE 0 END),
          sum(CASE WHEN FD_NAME    IS NULL OR trim(FD_NAME)='' THEN 1 ELSE 0 END),
          sum(CASE WHEN FD_FIP_CTY IS NULL OR trim(FD_FIP_CTY)='' THEN 1 ELSE 0 END)
        FROM {src}
        """,
    )

    cte = peer_cte()
    (n_peers,) = q1(con, cte + " SELECT count(*) FROM peers")
    (n_peer_fdids,) = q1(con, cte + " SELECT count(DISTINCT FDID) FROM peers")

    # The blank-NO_PD_FF decision, quantified both ways.
    (n_peers_lenient,) = q1(con, peer_cte(True) + " SELECT count(*) FROM peers")
    (n_peers_strict,) = q1(con, peer_cte(False) + " SELECT count(*) FROM peers")
    disputed = q1(
        con,
        f"""
        SELECT count(*),
               sum(CASE WHEN upper(FD_NAME) LIKE '%VOL%' OR upper(FD_NAME) LIKE '%VFD%'
                        THEN 1 ELSE 0 END)
        FROM {src}
        WHERE STATE IN ({STATES_SQL})
          AND (NO_PD_FF IS NULL OR trim(NO_PD_FF) = '')
          AND TRY_CAST(NO_VOL_FF AS INTEGER) BETWEEN 10 AND 40
          AND TRY_CAST(NO_STATION AS INTEGER) = 1
        """,
    )

    # How much damage does state-blind FDID matching do?
    n_collide, n_collide_states = q1(
        con,
        cte
        + f"""
        SELECT count(*), count(DISTINCT STATE) FROM (
          SELECT DISTINCT STATE, FDID FROM {src}
          WHERE FDID IN (SELECT FDID FROM peers)
        ) x
        WHERE (x.STATE, x.FDID) NOT IN (SELECT (STATE, FDID) FROM peers)
        """,
    )

    per_state = qall(con, cte + " SELECT STATE, count(*) FROM peers GROUP BY 1 ORDER BY 2 DESC")

    (n_dupe_pairs,) = q1(
        con,
        f"SELECT count(*) FROM (SELECT STATE, FDID FROM {src} GROUP BY 1,2 HAVING count(*) > 1)",
    )
    dupe_examples = qall(
        con,
        f"""
        SELECT STATE, FDID, count(*) c FROM {src}
        GROUP BY 1,2 HAVING count(*) > 1 ORDER BY c DESC LIMIT 5
        """,
    )

    return {
        "rows": rows,
        "distinct_state": n_state,
        "distinct_fdid": n_fdid,
        "distinct_state_fdid": n_pair,
        "duplicate_state_fdid_groups": n_dupe_pairs,
        "duplicate_examples": [list(r) for r in dupe_examples],
        "blank_no_station": blanks[0],
        "blank_no_pd_ff": blanks[1],
        "blank_no_vol_ff": blanks[2],
        "blank_fd_name": blanks[3],
        "blank_county_fips": blanks[4],
        "peer_pairs": n_peers,
        "peer_distinct_fdids": n_peer_fdids,
        "peer_pairs_blank_paid_as_zero": n_peers_lenient,
        "peer_pairs_blank_paid_excluded": n_peers_strict,
        "disputed_blank_paid_depts": disputed[0],
        "disputed_named_volunteer": disputed[1],
        "state_blind_extra_depts": n_collide,
        "state_blind_extra_states": n_collide_states,
        "peers_per_state": [list(r) for r in per_state],
    }


def profile_basicincident(con) -> dict:
    src = fd(settings.basicincident_file)

    rows, n_pair, n_key, n_state = q1(
        con,
        f"""
        SELECT count(*), count(DISTINCT (STATE, FDID)),
               count(DISTINCT INCIDENT_KEY), count(DISTINCT STATE)
        FROM {src}
        """,
    )

    # INC_DATE is MMDDYYYY. Anything else is malformed.
    date_stats = q1(
        con,
        f"""
        SELECT
          sum(CASE WHEN TRY_STRPTIME(trim(INC_DATE), '%m%d%Y') IS NULL THEN 1 ELSE 0 END),
          min(TRY_STRPTIME(trim(INC_DATE), '%m%d%Y')),
          max(TRY_STRPTIME(trim(INC_DATE), '%m%d%Y'))
        FROM {src}
        """,
    )

    year_hist = qall(
        con,
        f"""
        SELECT year(TRY_STRPTIME(trim(INC_DATE), '%m%d%Y')) y, count(*) c
        FROM {src} GROUP BY 1 ORDER BY 1
        """,
    )

    cols = [
        "ALARM",
        "ARRIVAL",
        "INC_CONT",
        "LU_CLEAR",
        "INC_TYPE",
        "PROP_LOSS",
        "PROP_USE",
        "CENSUS",
        "DEPT_STA",
        "AID",
    ]
    blank_sql = ", ".join(
        f"sum(CASE WHEN {c} IS NULL OR trim({c})='' THEN 1 ELSE 0 END) AS {c}" for c in cols
    )
    blank_row = q1(con, f"SELECT {blank_sql} FROM {src}")

    (dupe_keys,) = q1(
        con,
        f"SELECT count(*) FROM (SELECT INCIDENT_KEY FROM {src} GROUP BY 1 HAVING count(*) > 1)",
    )

    top_types = qall(
        con,
        f"""
        SELECT trim(INC_TYPE) t, count(*) c FROM {src}
        GROUP BY 1 ORDER BY c DESC LIMIT 10
        """,
    )

    return {
        "rows": rows,
        "distinct_state_fdid": n_pair,
        "distinct_incident_key": n_key,
        "distinct_state": n_state,
        "duplicate_incident_key_groups": dupe_keys,
        "unparseable_inc_date": date_stats[0],
        "min_inc_date": str(date_stats[1]),
        "max_inc_date": str(date_stats[2]),
        "year_histogram": [[r[0], r[1]] for r in year_hist],
        "blank_counts": dict(zip(cols, blank_row, strict=True)),
        "top_incident_types": [list(r) for r in top_types],
    }


def profile_response_times(con) -> dict:
    """
    Response time = ARRIVAL - ALARM, both MMDDYYYYHHMM.

    The prior CS444 scripts parsed only the HH:MM tail and wrapped negatives at
    midnight, which silently mangles multi-day and cross-midnight incidents.
    Here the FULL timestamp is parsed so the two methods can be compared.
    """
    src = fd(settings.basicincident_file)

    base = (
        peer_cte()
        + f"""
      , inc AS (
        SELECT b.STATE, b.FDID, b.INC_TYPE,
               TRY_STRPTIME(trim(b.ALARM),   '%m%d%Y%H%M') AS t_alarm,
               TRY_STRPTIME(trim(b.ARRIVAL), '%m%d%Y%H%M') AS t_arrive
        FROM {src} b
        JOIN peers p ON p.STATE = b.STATE AND p.FDID = b.FDID
      ),
      rt AS (
        SELECT *, date_diff('second', t_alarm, t_arrive) / 60.0 AS mins FROM inc
      )
    """
    )

    total, depts, bad_alarm, bad_arrive = q1(
        con,
        base
        + """
        SELECT count(*), count(DISTINCT (STATE, FDID)),
               sum(CASE WHEN t_alarm  IS NULL THEN 1 ELSE 0 END),
               sum(CASE WHEN t_arrive IS NULL THEN 1 ELSE 0 END)
        FROM rt
        """,
    )

    neg, zero, over90, over1day, usable = q1(
        con,
        base
        + """
        SELECT sum(CASE WHEN mins < 0 THEN 1 ELSE 0 END),
               sum(CASE WHEN mins = 0 THEN 1 ELSE 0 END),
               sum(CASE WHEN mins > 90 THEN 1 ELSE 0 END),
               sum(CASE WHEN mins > 1440 THEN 1 ELSE 0 END),
               sum(CASE WHEN mins > 0 AND mins <= 90 THEN 1 ELSE 0 END)
        FROM rt
        """,
    )

    sew = q1(
        con,
        base
        + f"""
        SELECT count(*),
               sum(CASE WHEN mins > 0 AND mins <= 90 THEN 1 ELSE 0 END),
               median(CASE WHEN mins > 0 AND mins <= 90 THEN mins END),
               quantile_cont(CASE WHEN mins > 0 AND mins <= 90 THEN mins END, 0.90),
               quantile_cont(CASE WHEN mins > 0 AND mins <= 90 THEN mins END, 0.95),
               100.0 * sum(CASE WHEN mins > 0 AND mins <= 8 THEN 1 ELSE 0 END)
                     / nullif(sum(CASE WHEN mins > 0 AND mins <= 90 THEN 1 ELSE 0 END), 0)
        FROM rt WHERE STATE = '{SEWANEE_STATE}' AND FDID = '{SEWANEE_FDID}'
        """,
    )

    # Departments with enough volume to benchmark. The prior work's ">10 valid
    # response times" cut is what produced its 1,138-department peer pool.
    (depts_gt10,) = q1(
        con,
        base
        + """
        SELECT count(*) FROM (
          SELECT STATE, FDID FROM rt WHERE mins > 0 AND mins <= 90
          GROUP BY 1,2 HAVING count(*) > 10
        )
        """,
    )
    (depts_any,) = q1(
        con,
        base
        + """
        SELECT count(*) FROM (
          SELECT STATE, FDID FROM rt WHERE mins > 0 AND mins <= 90 GROUP BY 1,2
        )
        """,
    )

    # Contamination check: how many incident rows does the state-blind FDID
    # match wrongly attribute to the peer pool? This is the size of the bug in
    # the prior CS444 extract.
    blind_rows, blind_depts, blind_states = q1(
        con,
        peer_cte()
        + f"""
        SELECT count(*), count(DISTINCT (b.STATE, b.FDID)), count(DISTINCT b.STATE)
        FROM {src} b
        WHERE b.FDID IN (SELECT FDID FROM peers)
          AND (b.STATE, b.FDID) NOT IN (SELECT (STATE, FDID) FROM peers)
        """,
    )

    return {
        "peer_incident_rows": total,
        "peer_departments_reporting": depts,
        "state_blind_extra_rows": blind_rows,
        "state_blind_extra_depts_reporting": blind_depts,
        "state_blind_extra_states_reporting": blind_states,
        "unparseable_alarm": bad_alarm,
        "unparseable_arrival": bad_arrive,
        "rt_negative": neg,
        "rt_zero": zero,
        "rt_over_90min": over90,
        "rt_over_1day": over1day,
        "rt_usable": usable,
        "peer_depts_with_any_rt": depts_any,
        "peer_depts_with_gt10_rt": depts_gt10,
        "sewanee": {
            "incidents": sew[0],
            "with_rt": sew[1],
            "median_min": round(sew[2], 2) if sew[2] is not None else None,
            "p90_min": round(sew[3], 2) if sew[3] is not None else None,
            "p95_min": round(sew[4], 2) if sew[4] is not None else None,
            "pct_under_8min": round(sew[5], 1) if sew[5] is not None else None,
        },
    }


def _parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def profile_local_incidents() -> dict:
    path = settings.local_incidents
    if not path.exists():
        return {"error": f"not found: {path}"}

    data = json.loads(path.read_text(encoding="utf-8"))
    ts_fields = ["receivedTime", "dispatchedTime", "enRouteTime", "onSceneTime"]
    present = dict.fromkeys(ts_fields, 0)
    statuses: dict[str, int] = {}
    natures: dict[str, int] = {}
    sources: dict[str, int] = {}
    coords = with_apparatus = with_personnel = 0
    dates: list[str] = []

    for r in data:
        for f in ts_fields:
            if r.get(f):
                present[f] += 1
        for bucket, key in (
            (statuses, "reviewStatus"),
            (natures, "natureOfCall"),
            (sources, "source"),
        ):
            v = r.get(key) or "(none)"
            bucket[v] = bucket.get(v, 0) + 1
        c = r.get("coordinates") or {}
        if c.get("latitude") and c.get("longitude"):
            coords += 1
        app = r.get("apparatus") or []
        if app:
            with_apparatus += 1
        if any(a.get("personnel") for a in app) or r.get("povPersonnel"):
            with_personnel += 1
        if r.get("receivedTime"):
            dates.append(r["receivedTime"][:10])

    rts: list[float] = []
    turnouts: list[float] = []
    travels: list[float] = []
    for r in data:
        d = _parse_iso(r.get("dispatchedTime"))
        e = _parse_iso(r.get("enRouteTime"))
        o = _parse_iso(r.get("onSceneTime"))
        if d and o and 0 < (m := (o - d).total_seconds() / 60) <= 90:
            rts.append(m)
        if d and e and 0 <= (m := (e - d).total_seconds() / 60) <= 90:
            turnouts.append(m)
        if e and o and 0 <= (m := (o - e).total_seconds() / 60) <= 90:
            travels.append(m)

    return {
        "records": len(data),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "timestamp_present": present,
        "review_status": dict(sorted(statuses.items(), key=lambda x: -x[1])),
        "distinct_nature_values": len(natures),
        "nature_of_call_top": dict(sorted(natures.items(), key=lambda x: -x[1])[:12]),
        "source": sources,
        "with_coordinates": coords,
        "with_apparatus": with_apparatus,
        "with_personnel": with_personnel,
        "total_response": {"n": len(rts), "p50": _pct(rts, 50), "p90": _pct(rts, 90)},
        "turnout": {"n": len(turnouts), "p50": _pct(turnouts, 50), "p90": _pct(turnouts, 90)},
        "travel": {"n": len(travels), "p50": _pct(travels, 50), "p90": _pct(travels, 90)},
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")

    stats: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sources": {}}
    for name, path in [
        ("fdheader", settings.fdheader_file),
        ("basicincident", settings.basicincident_file),
        ("local_incidents", settings.local_incidents),
    ]:
        stats["sources"][name] = {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else None,
        }

    steps = [
        ("fdheader", lambda: profile_fdheader(con)),
        ("local_incidents", profile_local_incidents),
        ("basicincident", lambda: profile_basicincident(con)),
        ("response_times", lambda: profile_response_times(con)),
    ]
    for name, fn in steps:
        t0 = time.time()
        print(f"[{name}] scanning ...", flush=True)
        stats[name] = fn()
        print(f"[{name}] done in {time.time() - t0:.1f}s", flush=True)
        OUT.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
