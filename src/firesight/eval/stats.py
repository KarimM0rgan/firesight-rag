"""
Wilson score intervals for every reported proportion.

Every metric in this project rests on between 8 and 20 observations. A bare
point estimate at that size invites a reader to treat 8/8 as "100%" and 11/13
as "84.6%", when the honest statements are "8/8, 95% CI [67.6%, 100%]" and
"11/13, 95% CI [57.8%, 95.7%]" -- the second of which overlaps almost
everything.

The Wilson score interval is used rather than the normal approximation because
it stays inside [0, 1] and does not collapse to zero width at 0/n or n/n, which
is exactly where these samples sit.

`proportion()` returns the interval alongside the estimate so a harness cannot
emit one without the other, and `fmt()` renders them together for a report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 95% two-sided.
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    """A measured proportion that carries its own uncertainty."""

    successes: int
    n: int
    estimate: float | None
    low: float | None
    high: float | None
    confidence: float = 0.95

    @property
    def width(self) -> float | None:
        if self.low is None or self.high is None:
            return None
        return self.high - self.low

    def as_dict(self) -> dict:
        return {
            "successes": self.successes,
            "n": self.n,
            "estimate": self.estimate,
            "ci_low": self.low,
            "ci_high": self.high,
            "ci_confidence": self.confidence,
            "ci_method": "wilson",
        }

    def fmt(self, digits: int = 1) -> str:
        """'8/8 = 100.0% [67.6, 100.0]' -- never an estimate on its own."""
        if self.n == 0 or self.estimate is None:
            return "n/a (no observations)"
        pct = f"{self.estimate * 100:.{digits}f}%"
        lo = f"{(self.low or 0) * 100:.{digits}f}"
        hi = f"{(self.high or 0) * 100:.{digits}f}"
        return f"{self.successes}/{self.n} = {pct} [{lo}, {hi}]"

    def fmt_short(self, digits: int = 1) -> str:
        if self.n == 0 or self.estimate is None:
            return "n/a"
        return (
            f"{self.estimate * 100:.{digits}f}% "
            f"[{(self.low or 0) * 100:.{digits}f}–{(self.high or 0) * 100:.{digits}f}]"
        )


def proportion(successes: int, n: int, z: float = Z_95) -> Proportion:
    """
    Wilson score interval.

        centre = (p + z^2/2n) / (1 + z^2/n)
        margin = z/(1 + z^2/n) * sqrt(p(1-p)/n + z^2/4n^2)

    At n=0 the estimate is None rather than 0.0; absence of data is not a
    measurement of zero.
    """
    if n <= 0:
        return Proportion(successes, n, None, None, None)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Proportion(
        successes=successes,
        n=n,
        estimate=round(p, 4),
        low=round(max(0.0, centre - margin), 4),
        high=round(min(1.0, centre + margin), 4),
    )


def from_bools(flags) -> Proportion:
    flags = list(flags)
    return proportion(sum(1 for f in flags if f), len(flags))


def too_small_to_claim_a_rate(p: Proportion, max_width: float = 0.25) -> bool:
    """
    True when the interval is so wide that quoting the point estimate as a
    'rate' would overstate what was measured. 8/8 spans 32 points; 11/13 spans
    38. Both are evidence; neither is a rate.
    """
    w = p.width
    return w is None or w > max_width
