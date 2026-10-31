"""
ONE honest answer to "how far back does this engine's history window reach?"

THE BUG THIS EXISTS TO KILL (found 2026-10-05)
-----------------------------------------------
Nine engine modules anchored their history window to the WALL CLOCK:

    end_dt = datetime.now(timezone.utc).date() - timedelta(days=1)

That looks harmless and is not. The pipeline runs at 18:00 to predict TOMORROW,
so "the last 5 matches" were fetched up to yesterday -- which includes results
that did not exist when the prediction was made.

The damage is not a wrong number, it is a NON-REPRODUCIBLE one. The same fixture
produces different "last 5" form depending on WHEN the engine ran, which silently
moves Tier 1/2 assignment and every downstream pick. Re-running an old date would
also read matches played after that fixture, i.e. its own future.

CORRECT FORMS ALREADY IN THIS REPO
----------------------------------
    CORE/dna_engine_v2.py
        t_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        end_dt     = (t_date_obj - timedelta(days=1)).isoformat()

DNA is the path the user verified as accurate. This module exists so the other
engines stop hand-rolling the window and stop drifting apart again.

THE CONTRACT
------------
`history_window_end` is the EXCLUSIVE end of the window: the day BEFORE the
target date. A fixture's own kickoff is never inside its own history.

`target_date=None` falls back to the wall clock. That preserves every existing
caller that genuinely means "up to now", and it is the ONLY sanctioned way to
reach the wall clock from here -- a silent one is how this bug survived.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union


DateLike = Union[str, datetime, None]


def as_of_date(target_date: DateLike = None):
    """The TARGET date as a `date`, parsed from whatever form it arrived in.

    Falls back to today (UTC) only when no target date was supplied. Accepts a
    date, a datetime, or the "YYYY-MM-DD" string every engine already passes.
    """
    if target_date is None:
        return datetime.now(timezone.utc).date()
    if isinstance(target_date, datetime):
        return target_date.date()
    if isinstance(target_date, str):
        try:
            return datetime.strptime(target_date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    # A date object, or something unusable. `date()` has no `.date()`, so this
    # is only reached by the former.
    return target_date


def history_window_end(target_date: DateLike = None):
    """Exclusive end of the history window: the day BEFORE the target date."""
    return as_of_date(target_date) - timedelta(days=1)


def history_window(target_date: DateLike = None,
                   lookback_days: int = 365) -> Tuple[str, str]:
    """`(start, end)` as ISO date strings, ready to drop into a URL.

    `end` is the day before the target date, so the fixture under analysis is
    never part of its own history.
    """
    end = history_window_end(target_date)
    start = end - timedelta(days=lookback_days)
    return start.isoformat(), end.isoformat()