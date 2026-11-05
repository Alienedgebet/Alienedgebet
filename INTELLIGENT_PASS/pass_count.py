"""
INTELLIGENT PASS — per-market evaluator.
=====================================

ARCHITECTURE (user spec, all binding):

    TEAM + FIXTURE + DATE + MARKET
            ↓
    ONE SPECIFIC PICK
            ↓
    ONLY THAT MARKET'S INTELLIGENT PASS CHECKS
            ↓
    PASS / FAIL / N/A
            ↓
    INTELLIGENT PASS COUNT

Every sidebar market/pick carries its own Intelligent Pass Count. Clicking a
count carries the market identity to /team/{team}?date=&market=, and the
report shows ONLY that market — never a generic every-market report.

DATA SOURCE RULES
-----------------
Each check reads ONE pre-existing field/verdict produced by an existing engine
cache file (win_raw / win_forecast / win_apex, psychology,
corners_aggregator, draw_engine, unders_engine, u2s_psychology,
fhvi_engine, shvi_engine). No new mathematics, no new SportMonks calls, no
new prediction engine, and no change to existing predictions.

When an engine cache file is absent (engine data is supplied separately), the
check honestly reports N/A — never a fabricated PASS/FAIL.

CROSS-DAY SOURCE WINDOW
-----------------------
The WIN Apex aggregator reads the latest merged state with no date argument,
so its supporting engine rows can live a day off the requested date. Every
source join resolves in a bounded window: the requested date FIRST, then
±1..±MAX_SOURCE_LOOKBACK_DAYS days, matching by fixture_id and, for id-less
sources, by the label that date's own id-bearing engines confirm. The date
that supplied each value is reported on the check (`source`) for full
traceability.

PROVENANCE
----------
Every check is {name, result, value, threshold, source, field, mapping}:
  source  — engine key (cache file) + the date the row was read from
  field   — the exact source field inside that engine's row
  mapping — the team/side mapping used (e.g. "predicted=AtNe side=FAV")
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Cache files are looked up under data/intelligent_pass_cache/<engine>/<date>.json
ENGINE_CACHE_SUBDIR = "intelligent_pass_cache"

# ── Rule constants (verified against the producing engines) ──────────────
INTELLIGENT_PASS_RULES: Dict[str, Any] = {
    # ── WIN ────────────────────────────────────────────────────────────
    # win_raw / win_forecast parity_score is signed per side. PASS when the
    # predicted team's parity_score > +10 (clean edge).
    "WIN_PARITY_THRESHOLD": 10,
    # WIN draw probability — a WIN pick is clean when the fixture's draw
    # probability stays BELOW 20%. mc_draw_prob is 0-1 MC float; the WIN apex
    # row's Monte_Draw_Prob is the same quantity as a 0-100 number.
    "WIN_DRAW_PROB_MAX": 0.20,
    "WIN_DRAW_PROB_MAX_PCT": 20,
    # WIN underdog longshot gate — PASS below 50% (0-100 "%" scale).
    "WIN_UNDERDOG_SCORE_PROB_MAX": 50,
    # Cross-day source window: requested date first, then ±N days.
    "MAX_SOURCE_LOOKBACK_DAYS": 3,
    # SOT diamond token (Engine/sot_engine.py Verdict).
    "SOT_DIAMOND_TOKEN": "DIAMOND",
    # ── GG ─────────────────────────────────────────────────────────────
    # psychology Psych_Score / Audit_Score are SIGNED NET scores. PASS > 0.
    "GG_PSYCH_NET_MIN": 0,
    # ── O2.5 ───────────────────────────────────────────────────────────
    "O25_PSYCH_NET_MIN": 0,
    # ── Corners ────────────────────────────────────────────────────────
    # corner4_aggregator Friction labels: PERFECT/STABLE support; DEAD/AVOID/UNDER oppose.
    "CORNERS_SUPPORT_LABELS": ("PERFECT", "STABLE", "\u26a1 PERFECT", "\ud83d\udccb STABLE"),
    "CORNERS_OPPOSE_LABELS": ("DEAD", "AVOID", "UNDER", "\ud83d\udca0 DEAD", "\ud83d\udd18 AVOID", "\u2b07 UNDER"),
    # ── Draw ───────────────────────────────────────────────────────────
    # draw_engine TIER2 gate mc_draw >= 0.22. A DRAW pick PASSES when AT or
    # above the engine's draw-candidate floor.
    "DRAW_MC_DRAW_MIN": 0.22,
    # ── Unders ─────────────────────────────────────────────────────────
    # unders_engine u25_score / tier gates — PASS when tier in (TIER1, TIER2).
    "UNDERS_TIER_PASS": ("TIER1", "TIER2", "1", "2"),
    # ── U2S ────────────────────────────────────────────────────────────
    # u2s_psychology Psych_Score signed net (>0 supports the dog scoring).
    "U2S_PSYCH_NET_MIN": 0,
    "U2S_LONGSHOT_PROB_MAX": 50,
    # ── FHVI ───────────────────────────────────────────────────────────
    "FHVI_SCORE_MIN": 0,
    # ── SHVI ───────────────────────────────────────────────────────────
    "SHVI_SCORE_MIN": 0,
}

# WIN check name → authoritative source field (provenance for rows that
# resolve with no pickable side, so even N/A says where it looked).
_WIN_FIELDS = {
    "SOT": "u2s_psychology Dog_Venue_SOT / Fav_Venue_SOT",
    "Corners": "corners_aggregator True_Corner_Fav",
    "Psychology": "win_psychology H_Base / A_Base",
    "DrawProb": "win_apex Monte_Draw_Prob / draw_engine mc_draw_prob",
    "Underdog": "u2s_psychology dog_score_prob",
    "Parity": "win_raw / win_forecast parity_score",
}


# ════════════════════════════════════════════════════════════════════════
# DATE WINDOW & FILE RESOLUTION
# ════════════════════════════════════════════════════════════════════════

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(d: Optional[str]) -> bool:
    if not d or not _DATE_RE.match(d):
        return False
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _engine_path(engine_key: str, date: str) -> str:
    """Path to an engine cache file: data/<engine_key>/<date>.json

    Engine data is supplied separately (Option 1). When a file is missing the
    evaluator reports N/A rather than inventing a result.
    """
    return os.path.join(DATA_DIR, ENGINE_CACHE_SUBDIR, engine_key, f"{date}.json")


def _load_json(path: str) -> Optional[Any]:
    """Load a JSON file, returning None if absent or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError,
            PermissionError, OSError):
        return None


def _resolve_date(engine_key: str, requested_date: str,
                  lookback: int) -> Tuple[Optional[str], Optional[Any]]:
    """Resolve the best available date for an engine cache.

    Tries the requested date first, then ±1..±lookback days (nearest first).
    Returns (date_used, payload) or (None, None) when no cache exists in the
    window.
    """
    if not _valid_date(requested_date):
        return None, None
    base = datetime.strptime(requested_date, "%Y-%m-%d")
    # Order: requested date, then +/-1, +/-2, ... (nearest first)
    candidates: List[str] = [requested_date]
    for offset in range(1, lookback + 1):
        for sign in (-1, 1):
            d = base + timedelta(days=sign * offset)
            candidates.append(d.strftime("%Y-%m-%d"))
    for cand in candidates:
        path = _engine_path(engine_key, cand)
        payload = _load_json(path)
        if payload is not None:
            return cand, payload
    return None, None


def _load_engine(engine_key: str, requested_date: str,
                 lookback: int = 3) -> Tuple[Optional[str], Optional[Any]]:
    """Public wrapper around _resolve_date."""
    return _resolve_date(engine_key, requested_date, lookback)


# ════════════════════════════════════════════════════════════════════════
# ROW LOCATION (by fixture_id, then by label/team name)
# ════════════════════════════════════════════════════════════════════════

def _as_list(payload: Any) -> List[Dict[str, Any]]:
    """Normalise a cache payload into a list of row dicts."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        # Composite cache files may wrap rows under a known key.
        for key in ("rows", "picks", "data", "fixtures", "engine"):
            if isinstance(payload.get(key), list):
                return [r for r in payload[key] if isinstance(r, dict)]
        # Single-row dict.
        return [payload]
    return []


def _norm(s: Any) -> str:
    """Normalise a team/fixture label for comparison (case, accents, spaces)."""
    if s is None:
        return ""
    s = str(s)
    s = s.lower()
    # Strip common accents.
    repl = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "ñ": "n", "ü": "u", "ç": "c"}
    s = "".join(repl.get(ch, ch) for ch in s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _find_row(rows: List[Dict[str, Any]], fixture_id: Optional[str],
              label: Optional[str]) -> Optional[Dict[str, Any]]:
    """Locate a row: exact fixture_id match first, then label/team-name match."""
    if not rows:
        return None
    # 1) Exact fixture_id match (id-bearing engines).
    if fixture_id:
        fid = str(fixture_id)
        for r in rows:
            for k in ("fixture_id", "id", "Fixture_ID", "fixtureId"):
                if r.get(k) is not None and str(r.get(k)) == fid:
                    return r
    # 2) Label / team name match (id-less engines).
    if label:
        nl = _norm(label)
        for r in rows:
            for k in ("fixture", "match", "label", "Fixture", "Match"):
                v = r.get(k)
                if v and _norm(v) == nl:
                    return r
    return None


def _find_row_by_team(rows: List[Dict[str, Any]], team: str) -> Optional[Dict[str, Any]]:
    """Locate a side row whose team_name/team matches the given team."""
    if not rows or not team:
        return None
    nt = _norm(team)
    for r in rows:
        for k in ("team_name", "team", "Target", "Underdog", "home_team",
                  "away_team", "selected_team"):
            v = r.get(k)
            if v and _norm(v) == nt:
                return r
    return None


# ════════════════════════════════════════════════════════════════════════
# HELPERS — safe numeric extraction & check construction
# ════════════════════════════════════════════════════════════════════════

def _num(v: Any) -> Optional[float]:
    """Coerce a value to float; strip % signs and non-numeric noise."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    s = s.replace("%", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _check(name: str, result: str, value: Any, threshold: Any,
           source: str, field: str, mapping: str = "") -> Dict[str, Any]:
    """Build a standardised check record."""
    return {
        "name": name,
        "result": result,          # PASS / FAIL / N/A
        "value": value,
        "threshold": threshold,
        "source": source,
        "field": field,
        "mapping": mapping,
    }


def _na(name: str, source: str, field: str,
        reason: str = "engine cache not available",
        mapping: str = "", threshold: Any = None) -> Dict[str, Any]:
    return _check(name, "N/A", None, threshold, source, field, mapping)


# ════════════════════════════════════════════════════════════════════════
# MARKET CHECK SETS
# Each function receives (rows, engine_date, team, fixture_id, label) and
# returns a list of check dicts. Missing engine → single N/A check.
# ════════════════════════════════════════════════════════════════════════

def _checks_win(rows: List[Dict[str, Any]], engine_date: Optional[str],
                team: Optional[str], fixture_id: Optional[str],
                label: Optional[str]) -> List[Dict[str, Any]]:
    """WIN market checks."""
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na("WIN parity", "win_raw/win_forecast (no cache)",
                    _WIN_FIELDS["Parity"])]
    # Find the side row for the predicted/target team.
    side_row = _find_row_by_team(rows, team) if team else None
    row = side_row or _find_row(rows, fixture_id, label)
    if row is None:
        return [_na("WIN parity", "win_raw/win_forecast",
                    _WIN_FIELDS["Parity"], "no row for team/fixture")]

    checks: List[Dict[str, Any]] = []
    src = f"win_raw/win_forecast ({engine_date or '?'})"
    mapping = f"predicted={team} side={row.get('side','?')}" if team else f"fixture={label}"

    # 1) Parity (signed per side).
    parity = _num(row.get("parity_score"))
    thr = rules["WIN_PARITY_THRESHOLD"]
    if parity is None:
        checks.append(_check("WIN parity", "N/A", None, thr, src,
                             _WIN_FIELDS["Parity"], mapping))
    else:
        checks.append(_check("WIN parity", "PASS" if parity > thr else "FAIL",
                             parity, f"> {thr}", src, _WIN_FIELDS["Parity"], mapping))

    # 2) Draw probability (0-1 MC or 0-100 PCT).
    draw_p = _num(row.get("mc_draw_prob"))
    if draw_p is None:
        draw_p = _num(row.get("Monte_Draw_Prob"))
        draw_is_pct = True
    else:
        draw_is_pct = False
    if draw_p is None:
        checks.append(_check("WIN draw prob", "N/A", None,
                             rules["WIN_DRAW_PROB_MAX_PCT"], src,
                             _WIN_FIELDS["DrawProb"], mapping))
    else:
        val_pct = draw_p if draw_is_pct else draw_p * 100
        checks.append(_check("WIN draw prob",
                             "PASS" if val_pct < rules["WIN_DRAW_PROB_MAX_PCT"]
                             else "FAIL",
                             round(val_pct, 1),
                             f"< {rules['WIN_DRAW_PROB_MAX_PCT']}%", src,
                             _WIN_FIELDS["DrawProb"], mapping))

    # 3) Underdog longshot gate (0-100 %).
    ud = _num(row.get("dog_score_prob"))
    if ud is None:
        checks.append(_check("WIN underdog gate", "N/A", None,
                             rules["WIN_UNDERDOG_SCORE_PROB_MAX"], src,
                             _WIN_FIELDS["Underdog"], mapping))
    else:
        checks.append(_check("WIN underdog gate",
                             "PASS" if ud < rules["WIN_UNDERDOG_SCORE_PROB_MAX"]
                             else "FAIL",
                             round(ud, 1),
                             f"< {rules['WIN_UNDERDOG_SCORE_PROB_MAX']}%", src,
                             _WIN_FIELDS["Underdog"], mapping))

    return checks


def _checks_psych(rows: List[Dict[str, Any]], engine_date: Optional[str],
                  team: Optional[str], fixture_id: Optional[str],
                  label: Optional[str], psych_min: float,
                  check_name: str, field: str, source_key: str) -> List[Dict[str, Any]]:
    """Generic psychology signed-net check (GG / O2.5 / U2S)."""
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na(check_name, f"{source_key} (no cache)", field)]
    row = _find_row_by_team(rows, team) if team else None
    row = row or _find_row(rows, fixture_id, label)
    if row is None:
        return [_na(check_name, f"{source_key}", field,
                    "no row for team/fixture")]
    src = f"{source_key} ({engine_date or '?'})"
    mapping = f"team={team} fixture={label}" if team else f"fixture={label}"
    val = _num(row.get(field))
    if val is None:
        return [_check(check_name, "N/A", None, psych_min, src, field, mapping)]
    return [_check(check_name, "PASS" if val > psych_min else "FAIL",
                   round(val, 1), f"> {psych_min}", src, field, mapping)]


def _checks_gg(rows, engine_date, team, fixture_id, label):
    return _checks_psych(rows, engine_date, team, fixture_id, label,
                         INTELLIGENT_PASS_RULES["GG_PSYCH_NET_MIN"],
                         "GG psychology", "Psych_Score", "win_psychology/gg_psychology")


def _checks_o25(rows, engine_date, team, fixture_id, label):
    return _checks_psych(rows, engine_date, team, fixture_id, label,
                         INTELLIGENT_PASS_RULES["O25_PSYCH_NET_MIN"],
                         "O2.5 psychology", "Psych_Score", "over25_psychology")


def _checks_u2s(rows, engine_date, team, fixture_id, label):
    """U2S market checks (underdog psychology + longshot gate)."""
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na("U2S psychology", "u2s_psychology (no cache)", "Psych_Score"),
                _na("U2S longshot gate", "u2s_psychology", "dog_score_prob")]
    row = _find_row_by_team(rows, team) if team else None
    row = row or _find_row(rows, fixture_id, label)
    if row is None:
        return [_na("U2S psychology", "u2s_psychology", "Psych_Score",
                    "no row for team/fixture"),
                _na("U2S longshot gate", "u2s_psychology", "dog_score_prob",
                    "no row for team/fixture")]
    src = f"u2s_psychology ({engine_date or '?'})"
    mapping = f"underdog={team} fixture={label}" if team else f"fixture={label}"
    checks = []
    psych = _num(row.get("Psych_Score"))
    if psych is None:
        checks.append(_check("U2S psychology", "N/A", None,
                             rules["U2S_PSYCH_NET_MIN"], src, "Psych_Score", mapping))
    else:
        checks.append(_check("U2S psychology",
                             "PASS" if psych > rules["U2S_PSYCH_NET_MIN"] else "FAIL",
                             round(psych, 1), f"> {rules['U2S_PSYCH_NET_MIN']}",
                             src, "Psych_Score", mapping))
    udp = _num(row.get("dog_score_prob"))
    if udp is None:
        checks.append(_check("U2S longshot gate", "N/A", None,
                             rules["U2S_LONGSHOT_PROB_MAX"], src,
                             "dog_score_prob", mapping))
    else:
        checks.append(_check("U2S longshot gate",
                             "PASS" if udp < rules["U2S_LONGSHOT_PROB_MAX"] else "FAIL",
                             round(udp, 1),
                             f"< {rules['U2S_LONGSHOT_PROB_MAX']}%", src,
                             "dog_score_prob", mapping))
    return checks


def _checks_corners(rows, engine_date, team, fixture_id, label):
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na("Corners friction", "corners_aggregator (no cache)",
                    "True_Corner_Fav / Friction")]
    row = _find_row_by_team(rows, team) if team else None
    row = row or _find_row(rows, fixture_id, label)
    if row is None:
        return [_na("Corners friction", "corners_aggregator",
                    "True_Corner_Fav / Friction", "no row for team/fixture")]
    src = f"corners_aggregator ({engine_date or '?'})"
    mapping = f"team={team} fixture={label}" if team else f"fixture={label}"
    friction = str(row.get("Friction", row.get("true_corner_fav", "")))
    support = set(s.upper() for s in rules["CORNERS_SUPPORT_LABELS"])
    oppose = set(o.upper() for o in rules["CORNERS_OPPOSE_LABELS"])
    f_up = friction.upper()
    if not friction:
        result = "N/A"
    elif any(slab in f_up for slab in support):
        result = "PASS"
    elif any(olab in f_up for olab in oppose):
        result = "FAIL"
    else:
        result = "N/A"
    return [_check("Corners friction", result, friction,
                   "PERFECT/STABLE support", src, "Friction / True_Corner_Fav",
                   mapping)]


def _checks_draw(rows, engine_date, team, fixture_id, label):
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na("Draw mc_draw", "draw_engine (no cache)", "mc_draw")]
    row = _find_row(rows, fixture_id, label)
    if row is None:
        return [_na("Draw mc_draw", "draw_engine", "mc_draw", "no row for fixture")]
    src = f"draw_engine ({engine_date or '?'})"
    mapping = f"fixture={label}"
    val = _num(row.get("mc_draw", row.get("mc_draw_prob")))
    if val is None:
        return [_check("Draw mc_draw", "N/A", None,
                       rules["DRAW_MC_DRAW_MIN"], src, "mc_draw", mapping)]
    # draw_engine mc_draw is 0-1; PASS when AT or ABOVE the candidate floor.
    return [_check("Draw mc_draw",
                   "PASS" if val >= rules["DRAW_MC_DRAW_MIN"] else "FAIL",
                   round(val, 3), f">= {rules['DRAW_MC_DRAW_MIN']}",
                   src, "mc_draw", mapping)]


def _checks_unders(rows, engine_date, team, fixture_id, label):
    rules = INTELLIGENT_PASS_RULES
    if not rows:
        return [_na("Unders tier", "unders_engine (no cache)", "u25_tier / u25_score")]
    row = _find_row(rows, fixture_id, label)
    if row is None:
        return [_na("Unders tier", "unders_engine", "u25_tier / u25_score",
                    "no row for fixture")]
    src = f"unders_engine ({engine_date or '?'})"
    mapping = f"fixture={label}"
    tier = str(row.get("u25_tier", row.get("tier", "")))
    pass_tiers = set(t.upper() for t in rules["UNDERS_TIER_PASS"])
    if not tier:
        result = "N/A"
    elif tier.upper() in pass_tiers:
        result = "PASS"
    else:
        result = "FAIL"
    score = _num(row.get("u25_score", row.get("score")))
    return [_check("Unders tier", result, tier,
                   f"in {tuple(rules['UNDERS_TIER_PASS'])}", src,
                   "u25_tier", mapping),
            _check("Unders score", "PASS" if (score is not None and score > 0)
                   else ("FAIL" if score is not None else "N/A"),
                   score, "> 0", src, "u25_score", mapping)]


def _checks_fhvi(rows, engine_date, team, fixture_id, label):
    return _checks_psych(rows, engine_date, team, fixture_id, label,
                         INTELLIGENT_PASS_RULES["FHVI_SCORE_MIN"],
                         "FHVI score", "fhvi_score", "fhvi_engine")


def _checks_shvi(rows, engine_date, team, fixture_id, label):
    return _checks_psych(rows, engine_date, team, fixture_id, label,
                         INTELLIGENT_PASS_RULES["SHVI_SCORE_MIN"],
                         "SHVI score", "shvi_score", "shvi_engine")


# Market → (engine_key, check_fn)
MARKET_REGISTRY: Dict[str, Tuple[str, Callable]] = {
    "WIN": ("win_raw", _checks_win),
    "GG": ("gg_psychology", _checks_gg),
    "O2.5": ("o25_psychology", _checks_o25),
    "OVER25": ("o25_psychology", _checks_o25),
    "O1.5": ("o15_psychology", _checks_o25),
    "OVER15": ("o15_psychology", _checks_o25),
    "CORNERS": ("corners_aggregator", _checks_corners),
    "DRAW": ("draw_engine", _checks_draw),
    "UNDERS": ("unders_engine", _checks_unders),
    "UNDER25": ("unders_engine", _checks_unders),
    "U25": ("unders_engine", _checks_unders),
    "U2S": ("u2s_psychology", _checks_u2s),
    "UNDERDOG": ("u2s_psychology", _checks_u2s),
    "FHVI": ("fhvi_engine", _checks_fhvi),
    "SHVI": ("shvi_engine", _checks_shvi),
}


# ════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════════

def normalise_market(market: str) -> str:
    """Normalise a market string to a registry key."""
    m = market.strip().upper()
    m = m.replace("OVER 2.5", "O2.5").replace("OVER2.5", "O2.5")
    m = m.replace("OVER 1.5", "O1.5").replace("OVER1.5", "O1.5")
    m = m.replace("UNDER 2.5", "UNDER25").replace("UNDER2.5", "UNDER25")
    return m


def evaluate(team: str, date: str, market: str,
             fixture_id: Optional[str] = None,
             label: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate the Intelligent Pass checks for ONE team + fixture + market.

    Returns:
        {
          "team": str,
          "date": str,
          "market": str,
          "fixture_id": str|None,
          "label": str|None,
          "checks": [ {name,result,value,threshold,source,field,mapping}, ... ],
          "pass_count": int,
          "total": int,
          "source_date": str|None   # date that supplied the engine row
        }
    """
    market_key = normalise_market(market)
    engine_key, check_fn = MARKET_REGISTRY.get(market_key, (None, None))

    result: Dict[str, Any] = {
        "team": team,
        "date": date,
        "market": market_key or market,
        "fixture_id": fixture_id,
        "label": label or fixture_id,
        "checks": [],
        "pass_count": 0,
        "total": 0,
        "source_date": None,
    }

    if engine_key is None or check_fn is None:
        result["checks"] = [_check(
            f"{market} market", "N/A", None, "unsupported market",
            "intelligent_pass", "market", f"market={market}")]
        return result

    # Resolve the engine cache date (requested date first, then ±lookback).
    lookback = int(INTELLIGENT_PASS_RULES["MAX_SOURCE_LOOKBACK_DAYS"])
    engine_date, payload = _load_engine(engine_key, date, lookback)
    result["source_date"] = engine_date

    rows = _as_list(payload)
    checks = check_fn(rows, engine_date, team, fixture_id, label)
    result["checks"] = checks
    result["total"] = len(checks)
    result["pass_count"] = sum(1 for c in checks if c["result"] == "PASS")
    return result


# Convenience: evaluate every supported market for a team/fixture.
def evaluate_all(team: str, date: str, fixture_id: Optional[str] = None,
                 label: Optional[str] = None) -> List[Dict[str, Any]]:
    """Evaluate every registered market for one team+fixture."""
    out = []
    for market_key in MARKET_REGISTRY:
        out.append(evaluate(team, date, market_key, fixture_id, label))
    return out
