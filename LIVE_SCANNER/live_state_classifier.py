"""
SHARED FIXTURE-STATE CLASSIFIER
==============================
One canonical implementation of "is this fixture live, finished, or still
waiting to start?", consumed by Stage 1 (pre-match), Stage 2 (the live
validation board) and the API layer. Before this module every stage carried
its own private copy of the rule and they disagreed, which is how a match that
had gone to extra time / penalties kept being displayed as LIVE forever.

Design rules (all deliberate, none are new mathematics):
  * The in-play feed's `state` STRING is authoritative when present, because
    that is the field the provider itself publishes for the running match.
  * Otherwise the numeric `state_id` is used.
  * A fixture that has not started but is long past its kickoff is treated as
    abandoned/postponed. This is the only staleness rule we allow, and it is
    deliberately NOT applied to fixtures the provider still reports as in-play,
    so a genuine 120' extra-time match can never be culled by the clock.
"""

from datetime import datetime, timezone

# ── Numeric state_id sets (from the fixture endpoint) ──────────────────────
# 2,3,4,12,13,21,22 are the genuine in-play states.
LIVE_STATE_IDS = frozenset({2, 3, 4, 12, 13, 21, 22})
# 5 = FT, 6 = AET (after extra time), 7 = after penalties.
# 6 and 7 were previously (wrongly) inside the LIVE list, which is exactly how a
# finished match stayed on the board labelled LIVE.
FINISHED_STATE_IDS = frozenset({5, 6, 7, 19})
NOT_STARTED_STATE_IDS = frozenset({1, 8, 9, 10, 11})

# ── In-play `state` string sets ───────────────────────────────────────────
INPLAY_LIVE_STATES = frozenset({
    "INPLAY_1ST_HALF",
    "INPLAY_HALFTIME",
    "INPLAY_2ND_HALF",
    "INPLAY_2ND_HALF_STOPPAGE_TIME",
    "INPLAY_EXTRA_TIME_1ST_HALF",
    "INPLAY_EXTRA_TIME_HALFTIME",
    "INPLAY_EXTRA_TIME_2ND_HALF",
})

# INPLAY_PENALTIES is deliberately FINISHED, not live: the shootout happens
# after the extra time the 2.5-goal line was already settled on.
INPLAY_FINISHED_STATES = frozenset({
    "FT", "AET", "PEN", "FT_AET", "FT_PEN",
    "MATCH_ENDED", "MATCH_AWAITING_RESULT", "MATCH_ABANDONED",
    "MATCH_CANCELLED", "MATCH_CANCELLED", "MATCH_POSTPONED",
    "MATCH_SUSPENDED", "INPLAY_PENALTIES",
})

INPLAY_NOT_STARTED_STATES = frozenset({"NOT_STARTED", "PRE", "SCHEDULED"})

# A fixture that never reached kickoff this long after its scheduled start is
# abandoned or postponed and must not sit on the board forever.
STALE_AFTER_MINUTES = 135


def parse_kickoff_utc(starting_at):
    """Parse a provider `starting_at` into an aware UTC datetime.

    The provider sends naive timestamps on the date endpoint. The old code
    called `.astimezone(timezone.utc)` on the naive result, and Python silently
    interprets a naive datetime as *machine-local* time. On this host (UTC+1)
    every kickoff was therefore shifted one hour early, which skewed both the
    printed kickoff time and the upcoming window.
    """
    if not starting_at:
        return None
    raw = str(starting_at).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_string(fixture):
    """Extract the in-play `state` string, if the provider included one."""
    state = fixture.get("state")
    if isinstance(state, dict):
        name = state.get("name")
        if name:
            return str(name).strip().upper()
    if isinstance(state, str) and state.strip():
        return state.strip().upper()
    return ""


def _state_id(fixture):
    try:
        return int(fixture.get("state_id"))
    except (TypeError, ValueError):
        return None



def classify_fixture(fixture, now=None):
    """Classify a fixture as live / finished / not_started / upcoming.

    Returns a dict with:
        state      : 'LIVE' | 'FINISHED' | 'NOT_STARTED'
        is_live    : bool
        is_finished: bool
        is_upcoming: bool   (kickoff still in the future — no time cap)
        is_stale   : bool   (never started, long past kickoff)
        kickoff_utc: aware datetime or None
        reason     : short human-readable justification
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    kickoff = parse_kickoff_utc(fixture.get("starting_at"))
    mins_to_kickoff = None
    if kickoff is not None:
        mins_to_kickoff = (kickoff - now).total_seconds() / 60.0

    s_str = _state_string(fixture)
    s_id = _state_id(fixture)

    # 1) The in-play `state` string wins whenever the provider supplied one.
    if s_str:
        if s_str in INPLAY_LIVE_STATES:
            return _result("LIVE", True, False, False, False, kickoff,
                           f"in-play state {s_str}")
        if s_str in INPLAY_FINISHED_STATES:
            return _result("FINISHED", False, True, False, False, kickoff,
                           f"state {s_str}")
        if s_str in INPLAY_NOT_STARTED_STATES:
            return _not_started_result(kickoff, mins_to_kickoff, s_str)

    # 2) Otherwise fall back to the numeric state_id.
    if s_id in FINISHED_STATE_IDS:
        return _result("FINISHED", False, True, False, False, kickoff,
                       f"state_id {s_id}")
    if s_id in LIVE_STATE_IDS:
        return _result("LIVE", True, False, False, False, kickoff,
                       f"state_id {s_id}")
    if s_id in NOT_STARTED_STATE_IDS or s_id is None:
        return _not_started_result(kickoff, mins_to_kickoff,
                                   f"state_id {s_id}")

    # Unknown numeric state: if the kickoff is clearly in the past, treat the
    # fixture as finished so it can never linger unclassified.
    if mins_to_kickoff is not None and mins_to_kickoff < -STALE_AFTER_MINUTES:
        return _result("FINISHED", False, True, False, False, kickoff,
                       f"unknown state_id {s_id}, long past kickoff")
    return _not_started_result(kickoff, mins_to_kickoff, f"state_id {s_id}")


def _not_started_result(kickoff, mins_to_kickoff, label):
    """Not started. Stale when the kickoff is long past and it never began."""
    if kickoff is None:
        return _result("NOT_STARTED", False, False, False, False, kickoff, label)
    if mins_to_kickoff > 0:
        return _result("NOT_STARTED", False, False, True, False, kickoff,
                       f"{label}, starts in {int(mins_to_kickoff)}m")
    overdue = -mins_to_kickoff
    if overdue > STALE_AFTER_MINUTES:
        return _result("NOT_STARTED", False, False, False, True, kickoff,
                       f"{label}, {int(overdue)}m past kickoff without starting "
                       f"(abandoned/postponed)")
    return _result("NOT_STARTED", False, False, False, False, kickoff,
                   f"{label}, {int(overdue)}m past kickoff")


def _result(state, is_live, is_finished, is_upcoming, is_stale, kickoff, reason):
    return {
        "state": state,
        "is_live": is_live,
        "is_finished": is_finished,
        "is_upcoming": is_upcoming,
        "is_stale": is_stale,
        "kickoff_utc": kickoff,
        "reason": reason,
    }


# ── Lineup / formation availability ────────────────────────────────────────
_INVALID_FORMATIONS = {"", "N/A", "NA", "NONE", "-", "NULL", "UNKNOWN"}


def team_ids(fixture):
    return {
        str(p.get("id"))
        for p in (fixture.get("participants") or [])
        if isinstance(p, dict) and p.get("id") is not None
    }


def official_lineup_players(fixture):
    """The official (type_id == 11) lineup entries for a fixture."""
    return [
        l for l in (fixture.get("lineups") or [])
        if isinstance(l, dict) and l.get("type_id") == 11
    ]


def has_official_lineup(fixture):
    return bool(official_lineup_players(fixture))


def formation_map(fixture):
    """{participant_id: formation} for formations actually reported."""
    out = {}
    for entry in (fixture.get("formations") or []):
        if not isinstance(entry, dict):
            continue
        pid = entry.get("participant_id")
        if pid is None:
            continue
        value = str(entry.get("formation") or "").strip()
        if value.upper() in _INVALID_FORMATIONS:
            continue
        out[str(pid)] = value
    return out


def has_full_formation(fixture):
    """True when BOTH sides have a reported formation.

    A single-sided formation gives a half-complete read, and the pre-match
    audit reasons about both teams, so it is not enough for admission.
    """
    teams = team_ids(fixture)
    if not teams:
        return False
    return teams.issubset(set(formation_map(fixture).keys()))


def admit_to_prematch_board(fixture, now=None):
    """Decide whether a fixture belongs on the Code 1 board.

    Admission rule (confirmed by the user):
      * a LIVE fixture is admitted once it has an official lineup, and
      * a fixture that has not kicked off is admitted ONLY once it has BOTH
        an official lineup AND a formation for both sides — and it then stays
        for as long as it takes, with no upper time limit,
      * a FINISHED fixture is never admitted, so it disappears on the very
        next successful cycle.
    """
    info = classify_fixture(fixture, now=now)
    has_lineup = has_official_lineup(fixture)
    has_formation = has_full_formation(fixture)
    info["has_lineup"] = has_lineup
    info["has_formation"] = has_formation
    info["formations"] = formation_map(fixture)

    if info["is_finished"] or info["is_stale"]:
        info["admitted"] = False
        info["admit_reason"] = info["reason"]
        return info

    if info["is_live"]:
        info["admitted"] = has_lineup
        info["admit_reason"] = (
            "LIVE with official lineup" if has_lineup
            else "LIVE but official lineup not yet published"
        )
        return info

    # Not started — this is the "about to start" window the user wants kept.
    if has_lineup and has_formation:
        info["admitted"] = True
        info["admit_reason"] = "lineups + formation confirmed"
    else:
        info["admitted"] = False
        missing = []
        if not has_lineup:
            missing.append("official lineup")
        if not has_formation:
            missing.append("formation")
        info["admit_reason"] = "awaiting " + " + ".join(missing)
    return info

    """True when BOTH sides have a reported formation.

    A single-sided formation gives a half-complete read, and the pre-match
    audit reasons about both teams, so it is not enough for admission.
    """
    teams = team_ids(fixture)
    if not teams:
        return False
    return teams.issubset(set(formation_map(fixture).keys()))

