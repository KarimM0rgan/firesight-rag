"""Central configuration. Every tunable lives here or in .env — nothing hardcoded downstream."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key, default)
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _int(env_key: str, default: int) -> int:
    return int(os.getenv(env_key, str(default)))


def _float(env_key: str, default: float) -> float:
    return float(os.getenv(env_key, str(default)))


# ── Peer-group definition ──────────────────────────────────────────────────
# These four constants ARE the peer-group definition used throughout the
# project. They are reproduced verbatim from the prior CS444 benchmarking work
# so that rebuilt metrics can be reconciled against the original numbers.
# See data/PROFILE.md § "Peer-group definition" before changing any of them.
SEWANEE_STATE = "TN"
SEWANEE_FDID = "26161"
REGION_STATES: frozenset[str] = frozenset({"TN", "GA", "AL", "KY", "NC", "VA", "MS", "AR"})


# ── Response-time window ───────────────────────────────────────────────────
# Primary filter is 0 <= response_min <= RESPONSE_MIN_CAP. Zeros are KEPT:
# dropping them removes the fastest tail and biases P90 upward, and P90 is the
# headline metric. RESPONSE_MIN_STRICT_POSITIVE reproduces the inherited
# `0 < response_min` rule for the sensitivity row in every eval report.
RESPONSE_MIN_CAP = 90
RESPONSE_MIN_STRICT_POSITIVE = False


# ── Zero-artifact detection ────────────────────────────────────────────────
# A department is flagged when its same-minute-arrival rate marks its
# timestamps as a reporting artifact rather than genuinely fast response.
#
# Evidence path first, threshold second:
#
# (1) SENTINEL EVIDENCE. NFIRS arrival times ending '0000' or '9999' are
#     placeholder values, not clock readings. Where a department's zeros are
#     mostly sentinel-backed, that is direct evidence and no rate threshold is
#     needed. Materiality is required: 16 of the 17 departments holding
#     sentinel records hold only 1-4 of them, and condemning a whole
#     department over a single corrupt row would be wrong.
#
# (2) PLAUSIBILITY FLOOR. Where sentinel evidence is absent, flag a zero rate
#     above 25%. One call in four arriving in the same clock minute as the
#     alarm is not a credible response profile at any department size -- the
#     two worst offenders (KY/24116 at 60.9%, MS/34007 at 75.5%) carry no
#     sentinel records at all, so only a plausibility judgment catches them.
#
# This replaced a "3x the cohort median" rule, which was withdrawn: with a
# median of 1.82% the threshold fell to 5.45%, below the cohort's own P90 of
# 8.82%, so a right-skewed distribution failed it by construction.
ZERO_RATE_IMPLAUSIBLE = 0.25
SENTINEL_SHARE_OF_ZEROS = 0.50
SENTINEL_MIN_RECORDS = 10
# Departments below this many scored incidents cannot be distinguished from
# noise; they are reported as `testable = false`. The plausibility floor still
# applies to them, because its rationale is size-independent.
ZERO_RATE_MIN_SCORED = 30


# ── Exclusions ─────────────────────────────────────────────────────────────
# Three independently named rules. Each is counted and logged at ETL time so
# a shift in any headline number can be traced to one of them.

# (1) NFIRS incident types where no unit ever reached a scene, so an
# alarm-to-arrival interval is undefined rather than fast. Codes verified
# individually against the PDR's own codelookup table (fieldid='INC_TYPE'),
# not assumed from the series. NFIRS codes appear at 1-, 2- and 3-digit
# granularity, so both forms of each are listed.
#   57 / 571  Cover assignment, standby at fire station, move-up
#   61 / 611  Dispatched and cancelled en route
# Deliberately NOT included, because a unit did arrive and the interval is
# real: 621/62 wrong location, 622 no incident found on arrival, and the whole
# 7xx false-alarm series (Sewanee's single largest category).
NON_RESPONSE_INCIDENT_TYPES: frozenset[str] = frozenset({"57", "571", "61", "611"})

# Pre-positioned assignments: a unit is already on location when the alarm is
# recorded, so arrival can legitimately equal alarm. Held separately because
# whether these belong in response-time statistics is a reporting judgment,
# not a data-quality fact. Activated only if the zero-distribution check shows
# zeros concentrating here.
#   38 / 381  Rescue or EMS standby
#   462       Aircraft standby
#   815       Severe weather or natural disaster standby
PREPOSITIONED_INCIDENT_TYPES: frozenset[str] = frozenset({"38", "381", "462", "815"})

# (2) Test and training entries in the local export. The export has no test
# flag, so these are matched on the uncontrolled `natureOfCall` free-text
# field (50 distinct values across 197 records -- PROFILE.md issue 9).
TEST_RECORD_FLAGS: frozenset[str] = frozenset(
    {"TEST TEST CALL", "SATURDAY TEST PAGE", "TEST", "TEST CALL", "TEST PAGE"}
)

# (3) Records not finalized by the department, so their timestamps are not
# authoritative. `draft` is NOT here: 183 of 197 records are drafts, which is
# a workflow-adoption artifact rather than a data-quality signal -- excluding
# them would leave 14 records and no analysis.
NON_FINALIZED_RECORDS: frozenset[str] = frozenset({"archived"})

# The inherited exclusion, kept ONLY so the Sewanee reconciliation test can
# prove the new pipeline reproduces known-good output. Never used in reporting.
LEGACY_TEST_EXCLUSION: frozenset[str] = frozenset(
    {"TEST TEST CALL", "SATURDAY TEST PAGE", "CAD Incident"}
)


@dataclass(frozen=True)
class PeerCriteria:
    """A department is a Sewanee peer if it matches all of these."""

    states: frozenset[str] = REGION_STATES
    max_paid_ff: int = 2  # strictly fewer than 3 career firefighters
    min_vol_ff: int = 10
    max_vol_ff: int = 40
    stations: int = 1

    # NO_PD_FF (career firefighter count) is blank on 45% of NFIRS fdheader
    # rows. Reading blank as "zero career staff" admits 112 extra departments
    # to the peer pool; reading it as "unknown" excludes them. The prior CS444
    # work read blank as zero, so that is the default here -- flipping it
    # breaks reconciliation against the original published numbers.
    # See data/PROFILE.md, "Blank staffing counts".
    blank_staffing_as_zero: bool = True

    def matches(
        self,
        state: str,
        paid_ff: int | None,
        vol_ff: int | None,
        stations: int | None,
    ) -> bool:
        if paid_ff is None and self.blank_staffing_as_zero:
            paid_ff = 0
        if paid_ff is None or vol_ff is None or stations is None:
            return False
        return (
            state in self.states
            and paid_ff <= self.max_paid_ff
            and self.min_vol_ff <= vol_ff <= self.max_vol_ff
            and stations == self.stations
        )

    # Raw NFIRS fdheader column names, and the typed names used after ingest.
    RAW_COLUMNS = ("STATE", "NO_PD_FF", "NO_VOL_FF", "NO_STATION")
    TYPED_COLUMNS = ("state", "paid_ff", "vol_ff", "stations")

    def sql_predicate(
        self,
        alias: str = "",
        columns: tuple[str, str, str, str] = RAW_COLUMNS,
        cast: bool = True,
    ) -> str:
        """
        The same rule as SQL.

        Defaults target the raw caret-delimited fdheader columns. Pass
        ``columns=PeerCriteria.TYPED_COLUMNS, cast=False`` to apply it to the
        already-typed ``departments`` columns instead -- one rule, two
        renderings, so the Python and SQL paths cannot drift.
        """
        p = f"{alias}." if alias else ""
        state_col, paid_col, vol_col, station_col = columns

        def num(col: str) -> str:
            return f"TRY_CAST({p}{col} AS INTEGER)" if cast else f"{p}{col}"

        states = ", ".join(f"'{s}'" for s in sorted(self.states))
        paid = num(paid_col)
        paid_ok = (
            f"coalesce({paid}, 0) <= {self.max_paid_ff}"
            if self.blank_staffing_as_zero
            else f"{paid} <= {self.max_paid_ff}"
        )
        return (
            f"{p}{state_col} IN ({states})"
            f" AND {paid_ok}"
            f" AND {num(vol_col)} BETWEEN {self.min_vol_ff} AND {self.max_vol_ff}"
            f" AND {num(station_col)} = {self.stations}"
        )


@dataclass(frozen=True)
class Settings:
    # Source data (read-only inputs, never copied into the repo)
    nfirs_dir: Path = field(default_factory=lambda: _path("FIRESIGHT_NFIRS_DIR", "data/raw/nfirs"))
    local_incidents: Path = field(
        default_factory=lambda: _path("FIRESIGHT_LOCAL_INCIDENTS", "data/raw/incidents.json")
    )
    docs_path: Path = field(
        default_factory=lambda: _path("FIRESIGHT_DOCS_PATH", "data/raw/documents")
    )

    # Derived stores
    duckdb_path: Path = field(
        default_factory=lambda: _path("FIRESIGHT_DUCKDB_PATH", "data/processed/firesight.duckdb")
    )
    chroma_path: Path = field(
        default_factory=lambda: _path("FIRESIGHT_CHROMA_PATH", "data/processed/chroma")
    )

    # Models
    llm_provider: str = field(
        default_factory=lambda: os.getenv("FIRESIGHT_LLM_PROVIDER", "anthropic")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("FIRESIGHT_LLM_MODEL", "claude-sonnet-5")
    )
    embed_model: str = field(
        default_factory=lambda: os.getenv("FIRESIGHT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    )
    rerank_model: str = field(
        default_factory=lambda: os.getenv("FIRESIGHT_RERANK_MODEL", "BAAI/bge-reranker-base")
    )
    top_k: int = field(default_factory=lambda: _int("FIRESIGHT_TOP_K", 5))
    # Retrieval similarity below which a question is refused outright, before
    # any model call. CALIBRATED, not guessed: see
    # scripts/calibrate_support_floor.py and eval/support_floor_calibration.json.
    # On this corpus with bge-small-en-v1.5, labelled in-corpus questions score
    # >= 0.750 and out-of-corpus questions <= 0.662, so 0.70 sits in the gap.
    # The original guess of 0.45 admitted EVERY out-of-corpus question tested.
    # This value is model-specific -- re-run the calibration if you change
    # FIRESIGHT_EMBED_MODEL.
    min_support_score: float = field(
        default_factory=lambda: _float("FIRESIGHT_MIN_SUPPORT", 0.70)
    )
    # Reranking is OFF by default: it improves Recall@5 and MRR but costs
    # seconds per query on CPU. See eval/results/ and the README.
    rerank_enabled: bool = field(
        default_factory=lambda: os.getenv("FIRESIGHT_RERANK", "0") == "1"
    )
    # Candidates = top_k * this, re-scored by the cross-encoder.
    rerank_candidate_multiplier: int = field(
        default_factory=lambda: _int("FIRESIGHT_RERANK_MULT", 2)
    )
    # Truncation for the cross-encoder. MEASURED: truncating below the chunk
    # size destroys the reranker's benefit -- with 500-token chunks, dropping
    # from 512 to 256 took Recall@5 from 0.667 back to 0.600, the same as no
    # reranking at all. Keep this >= the chunk target. See eval/results/.
    rerank_max_length: int = field(
        default_factory=lambda: _int("FIRESIGHT_RERANK_MAX_LEN", 512)
    )

    # Guardrails
    sql_timeout_s: int = field(default_factory=lambda: _int("FIRESIGHT_SQL_TIMEOUT_S", 15))
    sql_row_limit: int = field(default_factory=lambda: _int("FIRESIGHT_SQL_ROW_LIMIT", 1000))
    eval_max_questions: int = field(
        default_factory=lambda: _int("FIRESIGHT_EVAL_MAX_QUESTIONS", 60)
    )
    eval_max_usd: float = field(default_factory=lambda: _float("FIRESIGHT_EVAL_MAX_USD", 2.00))

    peers: PeerCriteria = field(default_factory=PeerCriteria)

    # NFIRS source tables actually used (filename -> purpose)
    @property
    def fdheader_file(self) -> Path:
        return self.nfirs_dir / "fdheader.txt"

    @property
    def basicincident_file(self) -> Path:
        return self.nfirs_dir / "basicincident.txt"

    @property
    def codelookup_file(self) -> Path:
        return self.nfirs_dir / "codelookup.txt"


settings = Settings()
