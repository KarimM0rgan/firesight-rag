"""
Reconciliation against known-good prior output.

This is the only proof that the rebuilt pipeline reproduces the numbers the
prior CS444 work published for Sewanee. Those numbers are trustworthy for
Sewanee specifically because FDID 26161 is unique nationally, so the
state-blind-join defect that contaminated every peer figure missed it.

Peer figures are deliberately NOT pinned here -- they are expected to differ,
and `data/RECONCILIATION.md` records why.
"""

import duckdb
import pytest

from firesight.config import settings

pytestmark = pytest.mark.skipif(
    not settings.duckdb_path.exists(),
    reason="no database; run `python -m firesight.ingest.structured`",
)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(settings.duckdb_path), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def sewanee(con):
    return con.execute("""
        SELECT n_incidents, n_non_response_incidents,
               n_with_response_time, response_p50_min, response_p90_min,
               response_p95_min, pct_within_8min,
               n_with_response_time_legacy, response_p50_min_legacy,
               response_p90_min_legacy, pct_within_8min_legacy,
               n_fire, n_ems_rescue, n_service, n_false_alarm
        FROM metrics_department_year WHERE is_sewanee AND year = 2024
    """).fetchone()


# ── figures that must match the prior work exactly ────────────────────────
def test_incident_count_matches_prior_work(sewanee):
    assert sewanee[0] == 283


def test_median_and_p90_match_prior_work(sewanee):
    """P50 and P90 are stable under the filter change -- the headline holds."""
    assert sewanee[3] == 6.0
    assert sewanee[4] == 13.0
    assert sewanee[8] == 6.0
    assert sewanee[9] == 13.0


def test_call_mix_matches_prior_work(sewanee):
    # nfirs_dept_summary_v2.csv: fire 24, ems 45, service 28, false alarm 169
    assert (sewanee[11], sewanee[12], sewanee[13], sewanee[14]) == (24, 45, 28, 169)


# ── the documented delta ──────────────────────────────────────────────────
def test_legacy_count_is_one_below_prior_work(sewanee):
    """
    The prior work scored 272 incidents. We score 271 under the same
    `response_min > 0` rule.

    The missing one is TN_26161_02262024_2400624_0, incident type 611
    "Dispatched & canceled en route", which the prior work counted as a
    1-minute response. No unit reached a scene, so it has no alarm-to-arrival
    interval. Excluding it is the intended behaviour of
    NON_RESPONSE_INCIDENT_TYPES, not drift.
    """
    assert sewanee[7] == 271
    assert sewanee[1] == 1


def test_the_delta_is_exactly_the_cancelled_en_route_incident(con):
    rows = con.execute("""
        SELECT i.incident_key, i.inc_type
        FROM incidents i JOIN departments d
          ON d.state = i.state AND d.fdid = i.fdid
        WHERE d.is_sewanee AND i.is_non_response
    """).fetchall()
    assert rows == [("TN_26161_02262024_2400624_0", "611")]


def test_reconciliation_arithmetic_closes(con, sewanee):
    """283 total = 1 cancelled + 1 over-cap + 10 zeros + 271 legacy-scored."""
    n_over_cap, n_zero = con.execute("""
        SELECT count(*) FILTER (WHERE response_min > 90 OR response_min < 0
                                   OR response_min IS NULL),
               count(*) FILTER (WHERE response_min = 0)
        FROM incidents i JOIN departments d
          ON d.state = i.state AND d.fdid = i.fdid
        WHERE d.is_sewanee AND NOT i.is_non_response
    """).fetchone()
    assert n_over_cap == 1
    assert n_zero == 10
    assert sewanee[1] + n_over_cap + n_zero + sewanee[7] == sewanee[0]


# ── the filter change, measured ────────────────────────────────────────────
def test_keeping_zeros_adds_exactly_ten_scored_incidents(sewanee):
    assert sewanee[2] == 281
    assert sewanee[2] - sewanee[7] == 10


def test_keeping_zeros_improves_compliance_and_lowers_p95(sewanee):
    """
    The stated rationale for keeping zeros is that dropping them biases the
    distribution. Measured for Sewanee: compliance +1.0pp, P95 -0.9 min, and
    P90 unchanged. Small, but in the predicted direction.
    """
    assert sewanee[6] == 73.3  # new
    assert sewanee[10] == 72.3  # legacy
    assert sewanee[5] == 18.0  # new P95; prior work published 18.9


# ── structural guarantees ─────────────────────────────────────────────────
def test_sewanee_is_not_a_zero_artifact_department(con):
    (flagged,) = con.execute(
        "SELECT is_zero_artifact FROM metrics_department_year WHERE is_sewanee"
    ).fetchone()
    assert flagged is False


def test_peer_cohort_matches_the_m0_profile(con):
    """1,568 peers and 151,759 peer incidents, per data/profile_stats.json."""
    (peers,) = con.execute("SELECT count(*) FROM departments WHERE is_peer").fetchone()
    (rows,) = con.execute("SELECT count(*) FROM incidents").fetchone()
    assert peers == 1568
    assert rows == 151759


def test_fdid_is_not_unique_so_joins_need_both_columns(con):
    """Guards against anyone reintroducing a state-blind join."""
    n_pairs, n_fdids = con.execute(
        "SELECT count(*), count(DISTINCT fdid) FROM departments"
    ).fetchone()
    assert n_fdids < n_pairs


def test_nfirs_incidents_carry_no_dispatch_or_enroute_timestamp(con):
    """The constraint the prompt asserts must actually hold in the schema."""
    cols = {r[0] for r in con.execute("DESCRIBE incidents").fetchall()}
    assert not {"dispatched_ts", "en_route_ts"} & cols
    local = {r[0] for r in con.execute("DESCRIBE local_incidents").fetchall()}
    assert {"dispatched_ts", "en_route_ts", "turnout_min"} <= local
