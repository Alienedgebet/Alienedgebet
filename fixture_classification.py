"""
fixture_classification.py — CUP / FRIENDLY detection for EVERY fixture.

WHY
---
Every prematch market page, the Weekly pages and the team-intelligence report all
render fixtures, but nothing in the stack ever asked whether a fixture is a CUP
match or a FRIENDLY. Those fixtures are materially different: squads rotate,
lineups are experimental and the result is far less predictable — so they must
be labelled and warn the user, on EVERY page, from ONE decision.

WHERE THE FACTS ALREADY ARE (no new API calls)
-----------------------------------------------
`shared_fixture_window.py` acquires every prematch date once with
CANONICAL_INCLUDE = "participants;league;season;state;scores;..." and stores the
raw bodies. SportMonks returns, per fixture:

    league: { id, name, type, sub_type, country_id, ... }
    season: { id, name, is_current, ... }
    stage_id, round_id, group_id, venue_id, leg, ...

`league.sub_type` is the authoritative competition kind and is already present
for 100% of the window's fixtures. Measured over the live window (364 fixtures):
sub_type = domestic 167 | cup_international 143 | friendly 42 | domestic_cup 12.
Detection is therefore a field read, not a guess.

DECISION ORDER (deterministic; the evidence is always reported)
-------------------------------------------------------------
  1. league.sub_type  -> 'friendly' | 'domestic_cup' | 'cup_international' | ...
  2. league.type      -> 'cup' / 'friendly'
  3. name fallback    -> league.name / season.name keywords (only when 1+2 absent)
No inference beyond those rules and no fabrication: absent fields classify as
`unknown` and raise NO warning.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

try:                                   # the window is the acquisition source
    import shared_fixture_window as window
except Exception:                      # pragma: no cover
    window = None

# ── competition vocabulary ───────────────────────────────────────────────────
CUP_SUB_TYPES = {"domestic_cup", "cup_international", "cup", "cup_national",
                 "cup_continental", "cup_friendly", "playoff"}
FRIENDLY_SUB_TYPES = {"friendly", "club_friendly", "international_friendly"}
DOMESTIC_SUB_TYPES = {"domestic", "league", "domestic_league"}

CUP_TYPE_VALUES = {"cup"}
FRIENDLY_TYPE_VALUES = {"friendly"}

# Keyword fallback — used ONLY when sub_type/type are absent (older payloads).
CUP_WORDS = ("cup", "copa", "taça", "taca", "pok al", "pokal", "trofeo",
             "troféu", "playoff")
FRIENDLY_WORDS = ("friendly", "friendlies", "amistoso", "amichevol", "exhibition",
                  "club friendlies", "pre-season", "preseason", "mundial")

# Severity — drives the colour/label the UI paints.
RISK_HIGH = "high"          # friendly
RISK_ELEVATED = "elevated"  # cup
RISK_NORMAL = "normal"
RISK_UNKNOWN = "unknown"


def _text(value):
    return str(value or "").strip().lower()


def classify_competition(league, season=None):
    """Pure decision function: (league, season) -> flag dict.

    Split from the window I/O so it is unit-testable with no files, no network
    and no cache state.
    """
    league = league if isinstance(league, dict) else {}
    season = season if isinstance(season, dict) else {}
    sub_type = _text(league.get("sub_type"))
    kind = _text(league.get("type"))
    league_name = str(league.get("name") or "").strip()
    season_name = str(season.get("name") or "").strip()
    haystack = f"{league_name} {season_name}".lower()

    is_friendly = is_cup = False
    source = ""
    if sub_type in FRIENDLY_SUB_TYPES:
        is_friendly, source = True, f"league.sub_type={sub_type}"
    elif sub_type in CUP_SUB_TYPES:
        is_cup, source = True, f"league.sub_type={sub_type}"
    elif sub_type in DOMESTIC_SUB_TYPES:
        source = f"league.sub_type={sub_type}"
    elif kind in FRIENDLY_TYPE_VALUES:
        is_friendly, source = True, f"league.type={kind}"
    elif kind in CUP_TYPE_VALUES:
        is_cup, source = True, f"league.type={kind}"
    else:
        if any(word in haystack for word in FRIENDLY_WORDS):
            is_friendly, source = True, "league/season name keyword"
        elif any(word in haystack for word in CUP_WORDS):
            is_cup, source = True, "league/season name keyword"
        else:
            source = "unclassified league fields"

    if is_friendly:
        risk_level, risk_label = RISK_HIGH, "FRIENDLY"
    elif is_cup:
        risk_level, risk_label = RISK_ELEVATED, "CUP"
    elif source.startswith("unclassified"):
        risk_level, risk_label = RISK_UNKNOWN, ""
    else:
        risk_level, risk_label = RISK_NORMAL, ""

    return {
        "league_id": league.get("id"),
        "league_name": league_name or None,
        "season_id": season.get("id"),
        "season_name": season_name or None,
        "competition": sub_type or kind or None,
        "is_cup": bool(is_cup),
        "is_friendly": bool(is_friendly),
        "is_risk_fixture": bool(is_cup or is_friendly),
        "risk_level": risk_level,
        "risk_label": risk_label,
        "classification": ("friendly" if is_friendly else
                           "cup" if is_cup else
                           "league" if (source and not source.startswith("unclassified"))
                           else "unknown"),
        "source": source,
    }


# ── window I/O (read-only; never refetches, never bypasses the cache) ────────
def _window_day_entry(date):
    """One window day entry, using the window's own reader (memory-cached)."""
    if window is None:
        return None
    getter = getattr(window, "_day_entry", None)
    if callable(getter):
        try:
            return getter(date)
        except Exception:
            return None
    try:                                  # fallback: read the store directly
        store = window._load_store()
        return (store.get("days") or {}).get(date)
    except Exception:
        return None


def _iter_window_fixtures(date):
    """Yield raw fixture dicts for `date` from the shared window store."""
    entry = _window_day_entry(date)
    if not isinstance(entry, dict) or not entry.get("acquisition_ok"):
        return
    for page in (entry.get("pages") or {}).values():
        body = (page or {}).get("body") or {}
        for fixture in body.get("data") or []:
            if isinstance(fixture, dict):
                yield fixture


def _participant_names(fixture):
    """(home, away) from the canonical payload's participants, or (None, None)."""
    home = away = None
    for participant in fixture.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        name = participant.get("name")
        location = ((participant.get("meta") or {}).get("location") or "").lower()
        if location == "home":
            home = home or name
        elif location == "away":
            away = away or name
    if home and away:
        return home, away
    # Fall back to the provider's own fixture name ("Home vs Away").
    label = str(fixture.get("name") or "")
    if " vs " in label:
        left, right = label.split(" vs ", 1)
        return left.strip(), right.strip()
    return home, away


def flags_for_date(date):
    """{fixture_id: flags} for one date, read ONLY from the shared window.

    Returns {} when the date is not held by the window — an honest empty, never
    a fabricated "safe".
    """
    out = {}
    for fixture in _iter_window_fixtures(date):
        fid = fixture.get("id")
        if fid in (None, ""):
            continue
        flags = classify_competition(fixture.get("league"), fixture.get("season"))
        flags["fixture_id"] = str(fid)
        flags["date"] = date
        stage = fixture.get("stage_id")
        flags["stage_id"] = str(stage) if stage not in (None, "") else None
        venue = fixture.get("venue_id")
        flags["venue_id"] = str(venue) if venue not in (None, "") else None
        # Team identity: lets the API resolve engines whose rows carry a fixture
        # LABEL but no fixture id (exact-id join stays the first choice).
        home, away = _participant_names(fixture)
        flags["home_team"] = home
        flags["away_team"] = away
        flags["fixture_label"] = fixture.get("name") or (
            f"{home} vs {away}" if home and away else None)
        out[str(fid)] = flags
    return out


def build_window_flags(dates):
    """One output row per fixture across `dates` (pipeline persistence shape)."""
    rows = []
    for date in dates or []:
        for fid, flags in flags_for_date(date).items():
            row = dict(flags)
            row["fixture_id"] = fid
            row["date"] = date
            rows.append(row)
    return rows


def summary(rows):
    """Counts for the pipeline log (no behaviour impact)."""
    rows = rows or []
    return {
        "fixtures": len(rows),
        "cup": sum(1 for r in rows if r.get("is_cup")),
        "friendly": sum(1 for r in rows if r.get("is_friendly")),
        "unknown": sum(1 for r in rows if r.get("risk_level") == RISK_UNKNOWN),
    }

