"""Smoke tests for configuration and the peer-group definition.

The peer criteria are the single most load-bearing constants in the project --
every benchmarking number depends on them -- so they get pinned here.
"""

from firesight.config import REGION_STATES, SEWANEE_FDID, SEWANEE_STATE, PeerCriteria, settings


def test_settings_load():
    assert settings.top_k > 0
    assert settings.sql_row_limit > 0
    assert settings.llm_provider in {"anthropic", "openai"}


def test_paths_are_absolute():
    assert settings.duckdb_path.is_absolute()
    assert settings.chroma_path.is_absolute()


def test_sewanee_identity_pinned():
    assert (SEWANEE_STATE, SEWANEE_FDID) == ("TN", "26161")
    assert SEWANEE_STATE in REGION_STATES


def test_region_is_the_eight_state_footprint():
    expected = frozenset({"TN", "GA", "AL", "KY", "NC", "VA", "MS", "AR"})
    assert REGION_STATES == expected


def test_peer_criteria_accepts_sewanee_profile():
    # Sewanee FD as recorded in NFIRS fdheader: 1 station, 0 career, 19 volunteer.
    assert PeerCriteria().matches(state="TN", paid_ff=0, vol_ff=19, stations=1)


def test_peer_criteria_rejects_out_of_profile_departments():
    c = PeerCriteria()
    assert not c.matches(state="CA", paid_ff=0, vol_ff=19, stations=1)  # outside region
    assert not c.matches(state="TN", paid_ff=5, vol_ff=19, stations=1)  # career staffed
    assert not c.matches(state="TN", paid_ff=0, vol_ff=4, stations=1)  # too small
    assert not c.matches(state="TN", paid_ff=0, vol_ff=60, stations=1)  # too large
    assert not c.matches(state="TN", paid_ff=0, vol_ff=19, stations=3)  # multi-station
