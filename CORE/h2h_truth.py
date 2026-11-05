"""
ONE honest H2H primitive, shared by every engine.

THE BUG THIS EXISTS TO KILL (reported 2026-10-05)
-------------------------------------------------
The user set an H2H threshold on the Weekly Tipster board and picked kept
appearing for team pairs that have almost no history -- or none at all.

The cause was not a wrong endpoint. Every engine hit the SAME correct endpoint
with the SAME parameters. The cause was that the SAMPLE SIZE was thrown away at
the first step and then re-invented as a literal:

    AGGREGATOR/gg_forensics_audit.py:338
        "H2H_GG": f"{h2h_gg}/5"        <-- denominator HARDCODED to 5

get_h2h_forensics() returned only a numerator, so the real number of meetings
sampled was never carried anywhere. Two meetings that both had BTTS became the
string "2/5" -- indistinguishable from two meetings out of a possible five that
did not. A pair that has NEVER met became "0/5", a confident-looking figure that
reads as real evidence.

So the board could not do the one thing the user asked of it. A threshold of
"3 GG in H2H" was checked against a number whose denominator did not exist, and
a pair with 1 or 2 real meetings was displayed with the same authority as a pair
with a full five.

THE USER'S SPEC, IMPLEMENTED HERE
---------------------------------
A. A pair with NO history must not qualify for a threshold at all.
B. A pair with fewer than five meetings must still be usable, but the real
   sample must be visible -- never dressed up as a full one.
C. A pair with more than five must be capped at five, over a bounded date range.
D. Every engine must derive the number it SHOWS from the same sample it SCORED
   with. One primitive, no per-engine re-invention.

HONESTY CONTRACT
----------------
`H2HTruth.sample` is the ONLY denominator any caller may use, and it is the
denominator that gets displayed. A rate and its sample travel together, so a
caller cannot compute with five and display with two. `usable` is False when
there is no history, so "no meetings" can never be silently scored as 0.0 --
the exact failure that graded three never-met fixtures on today's slate as
"0.0 BTTS rate".

No network access here. Pure logic over fixtures an engine has already fetched,
so it is fully testable and costs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# The window a "last N" sample is drawn from. H2H is capped at H2H_CAP
# meetings, and those meetings are additionally bounded to this many days so a
# pair that met ten years ago cannot supply today's number.
H2H_CAP = 5
H2H_MAX_AGE_DAYS = 1095  # 3 years; matches DNA's widened display window.


@dataclass(frozen=True)
class H2HTruth:
    """One pair's H2H evidence, with the sample size attached.

    `count` and `total` are the numbers that MUST be displayed together.
    `usable` is False only when there is no history at all.
    """

    count: int                      # meetings meeting the predicate
    total: int                      # meetings actually sampled (<= H2H_CAP)
    truncated: bool = False         # more existed than H2H_CAP
    reason: Optional[str] = None    # why it is unusable, when it is
    detail: dict = field(default_factory=dict)

    # ── Honesty helpers ────────────────────────────────────────────────────
    @property
    def usable(self) -> bool:
        """False when these two teams have no usable history.

        A threshold must refuse an unusable pair rather than treat the empty
        sample as a score of zero.
        """
        return self.total > 0

    @property
    def rate(self) -> Optional[float]:
        """True fraction, or None when there is nothing to measure.

        Returning None rather than 0.0 is the whole point: "never met" and
        "met five times and never scored" must not be the same number.
        """
        if not self.usable:
            return None
        return self.count / self.total

    @property
    def display(self) -> str:
        """e.g. "2/2 (thin)" — the REAL denominator, never a padded one."""
        if not self.usable:
            return "no H2H"
        base = f"{self.count}/{self.total}"
        if self.total < H2H_CAP:
            base += f" (thin: {self.total} of {H2H_CAP})"
        if self.truncated:
            base += " (capped)"
        return base

    def meets_count(self, minimum: Optional[int]) -> bool:
        """Threshold test that refuses to score an empty sample.

        `minimum` is the user's H2H threshold. With no threshold set, any
        usable pair qualifies; with one set, the pair must have that many
        qualifying meetings AND enough meetings to be worth judging.
        """
        if not self.usable:
            return False
        if minimum is None:
            return True
        return self.count >= int(minimum)

    def as_dict(self) -> dict:
        return {
            "count": self.count,
            "total": self.total,
            "usable": self.usable,
            "rate": self.rate,
            "display": self.display,
            "truncated": self.truncated,
            "reason": self.reason,
            **({"detail": dict(self.detail)} if self.detail else {}),
        }


def build_h2h_truth(
    fixtures: Optional[Iterable[dict]],
    predicate: Callable[[dict], bool],
    *,
    cap: int = H2H_CAP,
    max_age_days: Optional[int] = H2H_MAX_AGE_DAYS,
    exclude_fixture_id=None,
    reference_date: Optional[str] = None,
    detail: Optional[dict] = None,
) -> H2HTruth:
    """Turn already-fetched H2H fixtures into an honest, capped sample.

    `predicate` decides whether a meeting counts (BTTS, Over 2.5, ...). Fixtures
    without a readable scoreline are skipped rather than counted as failures --
    an unreadable result is missing data, not a 0-0.

    `exclude_fixture_id` drops the fixture under analysis, so a re-run of a match
    that has already been played cannot read its own result as history.

    `reference_date` bounds the window; it must be the TARGET date, never the
    wall clock, or a fixture sees matches from its own future.
    """
    rows = [f for f in (fixtures or []) if isinstance(f, dict)]

    if exclude_fixture_id is not None:
        rows = [f for f in rows if str(f.get("id")) != str(exclude_fixture_id)]

    # Sort newest-first ourselves. The provider's order is not guaranteed to
    # survive every wrapper, and "last N" is only meaningful if it really is.
    rows.sort(key=lambda f: str(f.get("starting_at") or f.get("starting_at_timestamp") or ""),
              reverse=True)

    if reference_date and max_age_days:
        from datetime import datetime, timedelta
        try:
            cutoff = (datetime.strptime(reference_date, "%Y-%m-%d")
                      - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            cutoff = None
        if cutoff:
            rows = [f for f in rows
                    if str(f.get("starting_at") or "")[:10] >= cutoff]

    truncated = len(rows) > cap
    sampled = rows[:cap]

    if not sampled:
        return H2HTruth(0, 0, False, reason="no_h2h_history",
                        detail=detail or {})

    # A meeting whose scoreline cannot be read is MISSING DATA, not a failure.
    # Counting it as a non-BTTS result would quietly bias every rate downward,
    # so it leaves the sample entirely and shrinks the denominator honestly.
    readable = []
    for f in sampled:
        try:
            verdict = predicate(f)
        except Exception:
            continue
        if verdict is None:
            continue
        readable.append(bool(verdict))

    if not readable:
        return H2HTruth(0, 0, False, reason="no_readable_h2h_history",
                        detail=detail or {})

    return H2HTruth(sum(readable), len(readable), truncated, None, detail or {})
