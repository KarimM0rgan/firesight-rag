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

    def sql_predicate(self, alias: str = "") -> str:
        """The same rule as SQL, for use against the raw caret-delimited files."""
        p = f"{alias}." if alias else ""
        states = ", ".join(f"'{s}'" for s in sorted(self.states))
        paid = f"TRY_CAST({p}NO_PD_FF AS INTEGER)"
        paid_ok = (
            f"coalesce({paid}, 0) <= {self.max_paid_ff}"
            if self.blank_staffing_as_zero
            else f"{paid} <= {self.max_paid_ff}"
        )
        return (
            f"{p}STATE IN ({states})"
            f" AND {paid_ok}"
            f" AND TRY_CAST({p}NO_VOL_FF AS INTEGER)"
            f" BETWEEN {self.min_vol_ff} AND {self.max_vol_ff}"
            f" AND TRY_CAST({p}NO_STATION AS INTEGER) = {self.stations}"
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
