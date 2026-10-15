"""
STAGE 9 — LIVE UNDER ENGINE.

WHAT THIS IS FOR
----------------
A dedicated under-engine that runs in the 24/7 live scanner cycle alongside
Stages 1-8. Unlike Stage 8 (which produces win/draw/overs/unders from market
prices), this engine produces dedicated under picks by combining:

  1. DNA signals         — team style, goal intent, box dominance, archetype
  2. Formation signals   — defensive formation shapes (5-x-x, 4-5-1, etc.)
  3. Keeper vulnerability — GK leak per 90, vulnerability percentage
  4. Key player missing   — attacker absences help the under, defender absences hurt
  5. Last-5-match gates   — neither team concedes >6 or scores >7 in last 5
  6. Style clash signals  — combined_goal_intent, combined_box_dominance, market_signals

ADMISSION RULE
---------------
Only fixtures that are currently LIVE OR INCOMING (about to start) with an
official lineup (type_id == 11) AND a full formation for both sides are
eligible. Admission is checked via the prematch_team_audit.json flags
(has_lineup, has_formation), which the live cycle populates from the
provider's lineup+formation payload — this is the same source
has_official_lineup/has_full_formation in live_state_classifier reads, but
accessed via the on-disk audit since board fixtures are summaries.

OUTPUT
-------
Writes stage9_live_unders.json containing a list of live under picks, using the
SAME row structure as the pre-match UndersPick. Each pick carries `is_live: true`
so the frontend can distinguish them from pre-match picks and badge them as LIVE.

This file is consumed by:
  - api/main.py  -> GET /api/live/unders
  - alienedge-frontend/app/unders/page.tsx (client-side merge with prematch picks)
"""
import json
import math
import os
import sys
import time

# ── Path setup so imports work whether run directly or from the scanner ──────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Reuse the formation_map helper from the state classifier
sys.path.insert(0, BASE_DIR)
from LIVE_SCANNER.live_state_classifier import formation_map  # noqa: E402

# ── File paths ────────────────────────────────────────────────────────────────
BOARD_FILE = os.path.join(OUTPUT_DIR, "orchestrator_board.json")
DANGER_FILE = os.path.join(DATA_DIR, "danger_audit.json")
PREMATCH_FILE = os.path.join(DATA_DIR, "prematch_team_audit.json")
DNA_PROFILES_FILE = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
STYLE_CLASHES_FILE = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
HISTORY_CACHE_FILE = os.path.join(DATA_DIR, "danger_history_cache.json")
# NOT "live_predictions.json" — that belongs to Code 1 / Stage 1.
OUTPUT_FILE = os.path.join(DATA_DIR, "stage9_live_unders.json")

# ── Configuration ───────────────────────────────────────────────────────────
LAST_N_GAMES = 5       # last N finished fixtures per team for form gates
GATE_MAX_CONCEDED = 6  # per team in last 5 (U3.5 window per user spec)
GATE_MAX_SCORED = 7    # per team in last 5 (U3.5 window per user spec)

# Tier thresholds — same spirit as the pre-match engine, adjusted for live
# where we have fewer signals (no venue, no league weight, no H2H).
U25_TIER1_SCORE = 65   # LOCK territory
U25_TIER2_SCORE = 50   # SOLID
U25_TIER3_SCORE = 35   # LEAN
U35_TIER1_SCORE = 70
U35_TIER2_SCORE = 55
U35_TIER3_SCORE = 40

# Defensive formation patterns — formations with 5 defenders or deep midfield
# shapes that are structurally defensive.
DEFENSIVE_FORMATION_PATTERNS = [
    "5-4-1", "5-3-2", "5-2-3", "5-2-2-1", "5-1-4-1",
    "4-5-1", "4-1-4-1", "4-2-3-1", "4-1-3-2", "4-4-2", "4-4-1-1",
    "3-5-1-1", "3-5-2", "3-4-3", "3-1-4-2",
    "1-4-5-1", "1-4-4-2",
]

# Archetype keywords that indicate a defensive / low-block / low-intent side.
DEFENSIVE_ARCHETYPE_KEYWORDS = [
    "defensive", "catenaccio", "low block", "park the bus",
    "deep block", "counter", "compact", "under", "draw",
    "possession controller",
]

# ── Signal point allocations ──────────────────────────────────────────────────
PT_FORMATION_DEFENSIVE = 12     # either side starts in a defensive formation
PT_ARCHETYPE_DEFENSIVE = 12     # either side has a defensive archetype
PT_LOW_GOAL_INTENT = 10         # combined_goal_intent < 50 (both sides low intent)
PT_LOW_BOX_DOMINANCE = 8        # combined_box_dominance < 50 (few box entries)
PT_HIGH_BTTS_FRICTION = 6       # both sides BTTS_Friction > 60 (hard to break down)
PT_MARKET_LEANS_UNDER = 15      # market_signals says LEAN/STRONG UNDER
PT_KEEPER_SOLID = 10            # both keepers GK_AVERAGE_CPG or better (<= 1.40)
PT_KEEPER_ELITE = 5             # bonus if both keepers are GK_ELITE_CPG (<= 1.10)
PT_KEEPER_VULNERABLE = -15      # either keeper is a DANGER/liability
PT_ATTACKER_MISSING = 10        # key attacker (FWD/MID) missing from either side
PT_DEFENDER_MISSING = -8        # key defender missing (creates goal risk)
PT_ATTACK_INDEX_LOW = 8         # both teams attack_index < 0.4 (low attacking output)
PT_ATTACK_INDEX_VERY_LOW = 5    # both teams attack_index < 0.3

# ── Keeper thresholds (reused from unders_engine.py) ─────────────────────────
GK_ELITE_CPG = 1.10
GK_AVERAGE_CPG = 1.40


def _load_json(path, default=None):
    """Load a JSON file, returning default on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def _as_rows(data):
    """Normalize data into a list of rows (handles dict-keyed or list payloads)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=None):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ── LAST-5-MATCH FORM GATES ────────────────────────────────────────────────────

def _extract_final_goals_from_scores(scores):
    """Extract (home_goals, away_goals) from a fixture's scores list.

    Replicates the exact logic from unders_engine.py:extract_final_goals_from_scores
    to ensure consistency.
    """
    home = away = None
    for entry in (scores or []):
        if not isinstance(entry, dict):
            continue
        s = entry.get("score") or entry
        desc = str(entry.get("description", s.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
            continue
        part = s.get("participant") or entry.get("participant")
        g = s.get("goals") if isinstance(s, dict) else entry.get("goals")
        try:
            if isinstance(g, str) and g.isdigit():
                g = int(g)
        except Exception:
            pass
        if isinstance(g, int):
            if part == "home":
                home = g if home is None else max(home, g)
            elif part == "away":
                away = g if away is None else max(away, g)
    return home, away


def _is_team_home(fx, team_id):
    """Check if team_id is the home team in fixture fx."""
    for p in fx.get("participants", []):
        if _safe_int(p.get("id")) == _safe_int(team_id):
            loc = (p.get("meta") or {}).get("location")
            if loc == "home":
                return True
            if loc == "away":
                return False
    parts = fx.get("participants", [])
    if len(parts) >= 2:
        if _safe_int(parts[0].get("id")) == _safe_int(team_id):
            return True
        if _safe_int(parts[1].get("id")) == _safe_int(team_id):
            return False
    return False


def _get_team_goals_from_fixture(fx, team_id):
    """Return (team_goals, opponent_goals) for team_id in fixture fx."""
    hg, ag = _extract_final_goals_from_scores(fx.get("scores", []))
    if hg is None or ag is None:
        return None, None
    if _is_team_home(fx, team_id):
        return hg, ag
    else:
        return ag, hg


def _compute_last5_form(history_cache, team_id):
    """Compute last-5-match goals scored/conceded for a team.

    Reads from danger_history_cache.json, which stores each team's recent
    fixtures (400-day window, but we take the last 5 completed).

    Returns (scored_total, conceded_total, matches_count).
    """
    tid = str(team_id)
    entry = history_cache.get(tid) or history_cache.get(_safe_int(team_id))
    if not isinstance(entry, dict):
        return None, None, 0
    fixtures = entry.get("data") or []
    # Filter to completed fixtures only (state_id == 5 per the provider)
    completed = [f for f in fixtures if isinstance(f, dict)
                 and f.get("state_id") == 5]
    # Take the last LAST_N_GAMES completed fixtures
    recent = completed[-LAST_N_GAMES:] if completed else []
    scored_total = 0.0
    conceded_total = 0.0
    count = 0
    for fx in recent:
        tg, og = _get_team_goals_from_fixture(fx, team_id)
        if tg is None or og is None:
            continue
        scored_total += tg
        conceded_total += og
        count += 1
    return scored_total, conceded_total, count


def _clear_gates(history_cache, home_id, away_id):
    """Apply the defensive-form gates.

    GATE 1: neither team scored more than GATE_MAX_SCORED in last 5
    GATE 2: neither team conceded more than GATE_MAX_CONCEDED in last 5

    Returns (passed: bool, reasons: list, detail: dict).
    """
    h_sc, h_cc, h_n = _compute_last5_form(history_cache, home_id)
    a_sc, a_cc, a_n = _compute_last5_form(history_cache, away_id)
    reasons = []
    detail = {}
    if h_n == 0:
        reasons.append("home has no completed match history")
    else:
        detail["gate_home_scored"] = h_sc
        detail["gate_home_conceded"] = h_cc
        detail["gate_home_n"] = h_n
        if h_sc is not None and h_sc > GATE_MAX_SCORED:
            reasons.append(f"home scored {h_sc:.0f} > {GATE_MAX_SCORED}")
        if h_cc is not None and h_cc > GATE_MAX_CONCEDED:
            reasons.append(f"home conceded {h_cc:.0f} > {GATE_MAX_CONCEDED}")
    if a_n == 0:
        reasons.append("away has no completed match history")
    else:
        detail["gate_away_scored"] = a_sc
        detail["gate_away_conceded"] = a_cc
        detail["gate_away_n"] = a_n
        if a_sc is not None and a_sc > GATE_MAX_SCORED:
            reasons.append(f"away scored {a_sc:.0f} > {GATE_MAX_SCORED}")
        if a_cc is not None and a_cc > GATE_MAX_CONCEDED:
            reasons.append(f"away conceded {a_cc:.0f} > {GATE_MAX_CONCEDED}")
    return (len(reasons) == 0, reasons, detail)


# ── FORMATION & ARCHETYPE DETECTION ────────────────────────────────────────────

def _parse_formation(formation_str):
    """Parse a formation string like '4-2-3-1' into a list of ints.
    Returns None if unparseable.
    """
    if not formation_str or not isinstance(formation_str, str):
        return None
    parts = formation_str.strip().split("-")
    try:
        nums = [int(p) for p in parts]
    except (ValueError, TypeError):
        return None
    if len(nums) < 2:
        return None
    return nums


def _formation_is_defensive(formation_str, tactical_dna=None):
    """Determine if a formation indicates a defensive setup.

    Checks:
      1. Formation string matches known defensive patterns (5-x-x, 4-5-1, etc.)
      2. Sum of defenders is 5 or more
      3. Line_Height is 'Low' (deep defensive line)
    """
    if formation_str is None:
        return False
    fs = formation_str.strip().upper()
    # Direct pattern match
    for pattern in DEFENSIVE_FORMATION_PATTERNS:
        if pattern.upper() in fs:
            return True
    # Parse formation numbers
    nums = _parse_formation(fs)
    if nums is None:
        return False
    # 5-back formations are defensive
    if nums[0] >= 5:
        return True
    # 4-at-back with a deep/mid-heavy midfield (4-5-1, 4-1-4-1, 4-2-3-1, etc.)
    if nums[0] == 4 and len(nums) >= 2 and nums[1] >= 5:
        return True
    if nums[0] == 4 and len(nums) >= 3 and nums[1] == 1:
        return True  # 4-1-4-1 or 4-1-3-2, etc.
    # Check tactical DNA for low line height
    if tactical_dna:
        lh = str(tactical_dna.get("Line_Height", "")).lower()
        if lh == "low":
            return True
    return False


def _archetype_is_defensive(archetype_str):
    """Check if an archetype string indicates a defensive/under-oriented team."""
    if not archetype_str:
        return False
    lower = archetype_str.lower()
    return any(kw in lower for kw in DEFENSIVE_ARCHETYPE_KEYWORDS)


# ── KEEPERS ────────────────────────────────────────────────────────────────────

def _keeper_score(home_gk_cpg, away_gk_cpg):
    """Score keeper signal for the under.

    Solid keepers (+10/+5), vulnerable keepers (-15).
    Returns (score, detail_str).
    """
    if home_gk_cpg is None or away_gk_cpg is None:
        return 0.0, "no reliable GK grades"
    h = _safe_float(home_gk_cpg)
    a = _safe_float(away_gk_cpg)
    if h is None or a is None:
        return 0.0, "GK CPG not available"
    score = 0.0
    detail_parts = []
    # Both keepers solid
    if h <= GK_AVERAGE_CPG and a <= GK_AVERAGE_CPG:
        score += PT_KEEPER_SOLID
        if h <= GK_ELITE_CPG and a <= GK_ELITE_CPG:
            score += PT_KEEPER_ELITE
            detail_parts.append("both elite wall")
        else:
            detail_parts.append("both solid guard")
    # Any keeper vulnerable
    if h > GK_AVERAGE_CPG or a > GK_AVERAGE_CPG:
        score += PT_KEEPER_VULNERABLE
        detail_parts.append("keeper liability (CPG > 1.40)")
    return score, " + ".join(detail_parts) if detail_parts else "keepers neutral"


def _gk_note(verdict, cpg):
    """Generate a keeper note string matching the unders_engine style."""
    if verdict == "DANGER" or (cpg is not None and cpg > GK_AVERAGE_CPG):
        return "⚠️ LEAK" if cpg is not None else "⚠️ Liability"
    if cpg is not None and cpg <= GK_ELITE_CPG:
        return "🧱 ELITE WALL"
    if cpg is not None and cpg <= GK_AVERAGE_CPG:
        return "🛡️ Solid"
    return "Unknown"


# ── MISSING PLAYERS ────────────────────────────────────────────────────────────

def _missing_player_signal(danger_home, danger_away):
    """Score the missing-player signal.

    Attacker (FWD/MID) missing → +10 (fewer goals)
    Defender (DEF) missing → -8 (more goals conceded)
    """
    score = 0.0
    detail_parts = []
    for side_name, team in (("home", danger_home), ("away", danger_away)):
        if not isinstance(team, dict):
            continue
        missing = team.get("missing_details") or []
        if not missing:
            continue
        for player in missing:
            pos = (player.get("pos") or "").upper()
            worth = player.get("worth") or 0
            # Only count significant absences (worth > 500 to avoid noise)
            if worth < 500:
                continue
            if "FWD" in pos or "FW" in pos or "ST" in pos or "CF" in pos:
                score += PT_ATTACKER_MISSING
                detail_parts.append(f"{side_name}: key attacker missing ({player.get('name', '?')})")
            elif "DEF" in pos or "DF" in pos or "CB" in pos or "LB" in pos or "RB" in pos:
                score -= PT_DEFENDER_MISSING
                detail_parts.append(f"{side_name}: key defender missing ({player.get('name', '?')})")
    return score, "; ".join(detail_parts) if detail_parts else "no significant absences"


# ── DNA SIGNALS ────────────────────────────────────────────────────────────────

def _dna_signal(dna_home, dna_away, clash):
    """Score the DNA signals for the under.

    Returns (score, signals_fired, detail).
    """
    score = 0.0
    fired = 0
    details = []

    if not dna_home and not dna_away:
        return 0.0, 0, "no DNA profiles available"

    # ── Style clash signals (fixture-level) ────────────────────────────────
    if clash and isinstance(clash, dict):
        # Combined Goal Intent — lower = both sides have low scoring intent = good for under
        cbi = clash.get("combined_goal_intent")
        cbi_f = _safe_float(cbi)
        if cbi_f is not None:
            if cbi_f < 50:
                score += PT_LOW_GOAL_INTENT
                fired += 1
                details.append(f"combined_goal_intent={cbi_f:.0f} (<50)")
            elif cbi_f < 65:
                score += PT_LOW_GOAL_INTENT * 0.6
                fired += 1
                details.append(f"combined_goal_intent={cbi_f:.0f} (<65, partial)")

        # Combined Box Dominance — lower = fewer attacks in the box = fewer goals
        cbd = clash.get("combined_box_dominance")
        cbd_f = _safe_float(cbd)
        if cbd_f is not None and cbd_f < 50:
            score += PT_LOW_BOX_DOMINANCE
            fired += 1
            details.append(f"combined_box_dominance={cbd_f:.0f} (<50)")

        # BTTS Friction — high friction = both teams hard to break down = fewer goals
        edges = clash.get("edges", {})
        bf = edges.get("BTTS_Friction", {})
        h_bf = _safe_float(bf.get("home"))
        a_bf = _safe_float(bf.get("away"))
        if h_bf is not None and a_bf is not None:
            if h_bf > 60 and a_bf > 60:
                score += PT_HIGH_BTTS_FRICTION
                fired += 1
                details.append(f"high BTTS friction ({h_bf:.0f}-{a_bf:.0f})")

        # Market signals — the DNA engine's own under read
        ms = clash.get("market_signals", {})
        ou = (ms.get("Over_Under") or "").upper()
        if "UNDER" in ou:
            score += PT_MARKET_LEANS_UNDER
            fired += 1
            details.append(f"market signal: {ou}")

    # ── Archetype defense signals (team-level) ─────────────────────────────
    for side, name in ((dna_home, "home"), (dna_away, "away")):
        if not isinstance(side, dict):
            continue
        arch = side.get("archetype") or ""
        if _archetype_is_defensive(arch):
            score += PT_ARCHETYPE_DEFENSIVE
            fired += 1
            details.append(f"{name} archetype: {arch}")

    # ── Individual team pillar signals ───────────────────────────────────────
    h_pillars = (dna_home or {}).get("pillars") or {}
    a_pillars = (dna_away or {}).get("pillars") or {}
    h_gi = _safe_float(h_pillars.get("Goal_Intent"))
    a_gi = _safe_float(a_pillars.get("Goal_Intent"))
    if h_gi is not None and a_gi is not None:
        if h_gi < 45 and a_gi < 45:
            score += PT_LOW_GOAL_INTENT * 0.5
            fired += 1
            details.append(f"both goal_intent < 45 ({h_gi:.0f}-{a_gi:.0f})")
    h_bd = _safe_float(h_pillars.get("Box_Dominance"))
    a_bd = _safe_float(a_pillars.get("Box_Dominance"))
    if h_bd is not None and a_bd is not None:
        if h_bd < 50 and a_bd < 50:
            score += PT_LOW_BOX_DOMINANCE * 0.5
            fired += 1
            details.append(f"both box_dominance < 50 ({h_bd:.0f}-{a_bd:.0f})")

    return max(0.0, score), fired, "; ".join(details) if details else "no DNA signals"


# ── ATTACK INDEX ───────────────────────────────────────────────────────────────

def _attack_index_signal(danger_home, danger_away):
    """Score based on team attack indices.

    Low attack index = fewer goals = better for under.
    """
    score = 0.0
    details = []
    h_ai = _safe_float((danger_home or {}).get("attack_index"))
    a_ai = _safe_float((danger_away or {}).get("attack_index"))
    if h_ai is not None and a_ai is not None:
        if h_ai < 0.3 and a_ai < 0.3:
            score += PT_ATTACK_INDEX_VERY_LOW
            details.append(f"both attack_index < 0.3 ({h_ai:.2f}-{a_ai:.2f})")
        elif h_ai < 0.4 and a_ai < 0.4:
            score += PT_ATTACK_INDEX_LOW
            details.append(f"both attack_index < 0.4 ({h_ai:.2f}-{a_ai:.2f})")
    return score, "; ".join(details) if details else "attack_index not available"


# ── COMBINED LAMBDA ────────────────────────────────────────────────────────────

def _compute_combined_lambda(history_cache, home_id, away_id, league_avg_per_team=1.35):
    """Compute combined_lambda (expected total goals) from last-5-match data.

    Uses empirical-Bayes shrinkage (same approach as unders_engine.py's
    build_lambdas), but simplified for the live context: no league weight,
    no H2H. The combined lambda = lambda_home + lambda_away.

    For UNDERS, LOWER lambda is better (fewer expected goals).
    """
    h_sc, h_cc, h_n = _compute_last5_form(history_cache, home_id)
    a_sc, a_cc, a_n = _compute_last5_form(history_cache, away_id)

    prior_strength = 2.5  # LAMBDA_PRIOR_STRENGTH from unders_engine.py
    prior_mean = league_avg_per_team

    if h_n > 0 and a_n > 0:
        # Home attack blended with away defence
        h_raw_att = (h_sc / h_n) if h_n > 0 else prior_mean
        h_raw_def = (a_cc / a_n) if a_n > 0 else prior_mean
        a_raw_att = (a_sc / a_n) if a_n > 0 else prior_mean
        a_raw_def = (h_cc / h_n) if h_n > 0 else prior_mean

        # Shrink once (per the 2026-10-04 fix)
        h_blend = (h_raw_att + h_raw_def) / 2.0
        a_blend = (a_raw_att + a_raw_def) / 2.0
        n = min(h_n, a_n)
        lambda_home = (h_blend * n + prior_strength * prior_mean) / (n + prior_strength)
        lambda_away = (a_blend * n + prior_strength * prior_mean) / (n + prior_strength)
    else:
        lambda_home = lambda_away = prior_mean

    lambda_home = max(0.3, min(5.0, lambda_home))
    lambda_away = max(0.3, min(5.0, lambda_away))
    return lambda_home, lambda_away, lambda_home + lambda_away


def _poisson_u25_prob(lam):
    """Poisson probability of under 2.5 goals given lambda."""
    if lam is None:
        return None
    p = 0.0
    for k in range(3):  # 0, 1, 2
        p += math.exp(-lam) * (lam ** k) / math.factorial(k)
    return p


def _poisson_u35_prob(lam):
    """Poisson probability of under 3.5 goals given lambda."""
    if lam is None:
        return None
    p = 0.0
    for k in range(4):  # 0, 1, 2, 3
        p += math.exp(-lam) * (lam ** k) / math.factorial(k)
    return p


def _get_u25_tier(score, signals_fired, gates_passed):
    """Assign U2.5 tier using the same structure as the pre-match engine."""
    if not gates_passed:
        return "🚫 U2.5 GATE FAIL"
    if score >= U25_TIER1_SCORE and signals_fired >= 4:
        return "🛡️ U2.5 TIER 1 — LOCK"
    elif score >= U25_TIER2_SCORE:
        return "✅ U2.5 TIER 2 — SOLID"
    elif score >= U25_TIER3_SCORE:
        return "📊 U2.5 TIER 3 — LEAN"
    else:
        return "⚪ U2.5 BELOW THRESHOLD"


def _get_u35_tier(score, gates_passed):
    """Assign U3.5 tier using the same structure as the pre-match engine."""
    if not gates_passed:
        return "🚫 U3.5 GATE FAIL"
    if score >= U35_TIER1_SCORE:
        return "🧱 U3.5 TIER 1 — LOCK"
    elif score >= U35_TIER2_SCORE:
        return "✅ U3.5 TIER 2 — SOLID"
    elif score >= U35_TIER3_SCORE:
        return "📊 U3.5 TIER 3 — LEAN"
    else:
        return "⚪ U3.5 BELOW THRESHOLD"


# ── MAIN SCORING ───────────────────────────────────────────────────────────────

def _score_fixture(fixture, danger_rows, prematch_audit, dna_cache, clash_cache, history_cache):
    """Score one live fixture for the under.

    Returns a pick dict matching the UndersPick structure (with is_live: true),
    or None if the fixture doesn't qualify for admission.
    """
    fixture_id = str(fixture.get("id") or fixture.get("fixture_id"))
    if not fixture_id:
        return None

    # ── Match danger audit row ─────────────────────────────────────────────────
    danger_row = next(
        (r for r in danger_rows if str(r.get("fixture_id")) == fixture_id),
        None,
    )
    if not danger_row:
        return None  # no danger audit = no keeper/absence data

    # ── Match prematch audit ───────────────────────────────────────────────────
    # prematch_team_audit.json is a dict keyed by fixture_id
    pm_row = prematch_audit.get(fixture_id) if isinstance(prematch_audit, dict) else None
    if pm_row is None and isinstance(prematch_audit, list):
        pm_row = next(
            (r for r in prematch_audit if str(r.get("fixture_id")) == fixture_id),
            None,
        )

    # ── ADMISSION GATE: official lineup + full formation ──────────────────────
    # The board fixtures don't carry lineups/formation fields directly —
    # those live in prematch_team_audit.json, keyed by fixture_id.
    # Admission: the fixture must have both has_lineup and has_formation=True,
    # AND must be live or in the incoming window (about to start).
    if not pm_row:
        return None  # no prematch audit = no lineup/formation context
    if not pm_row.get("has_lineup"):
        return None
    if not pm_row.get("has_formation"):
        return None  # neither live nor incoming — skip
    fixture_status = "live" if fixture.get("is_live") else "incoming"
    if fixture_status == "incoming" and not fixture.get("is_not_started"):
        return None

    # ── Resolve team IDs ──────────────────────────────────────────────────────
    d_home = danger_row.get("home_team") or {}
    d_away = danger_row.get("away_team") or {}
    home_id = d_home.get("id") or (pm_row or {}).get("home", {}).get("team_id")
    away_id = d_away.get("id") or (pm_row or {}).get("away", {}).get("team_id")
    if home_id is None or away_id is None:
        return None

    # ── Resolve DNA profiles ──────────────────────────────────────────────────
    home_dna = dna_cache.get(str(home_id)) or dna_cache.get(home_id)
    away_dna = dna_cache.get(str(away_id)) or dna_cache.get(away_id)

    # ── Resolve style clash ───────────────────────────────────────────────────
    clash = next(
        (c for c in clash_cache if str(c.get("fixture_id")) == fixture_id),
        None,
    )

    # ── Resolve formations ────────────────────────────────────────────────────
    # 1. Try the prematch audit's formations dict (participant_id → formation)
    # 2. Fall back to danger_audit's home_team/away_team formation field
    formations = {}
    pm_forms = (pm_row or {}).get("formations") or {}
    if isinstance(pm_forms, dict):
        formations = pm_forms
    # Also check the board fixture's formations (in case they're present)
    board_forms = formation_map(fixture)
    if board_forms:
        formations = {**board_forms, **formations}
    # Also check the board fixture's formations (in case they're present)
    board_forms = formation_map(fixture)
    if board_forms:
        formations = {**board_forms, **formations}

    home_formation = formations.get(str(home_id)) or formations.get(home_id)
    away_formation = formations.get(str(away_id)) or formations.get(away_id)

    # Fall back to danger_audit's embedded formation
    if not home_formation:
        home_formation = d_home.get("formation")
    if not away_formation:
        away_formation = d_away.get("formation")

    # ── DEFENSIVE FORM GATES ──────────────────────────────────────────────────
    gates_passed, gate_reasons, gate_detail = _clear_gates(
        history_cache, home_id, away_id
    )

    # ── COMPUTE COMBINED LAMBDA ──────────────────────────────────────────────
    lambda_home, lambda_away, combined_lambda = _compute_combined_lambda(
        history_cache, home_id, away_id
    )

    # ── MC PROBABILITIES (from Poisson) ──────────────────────────────────────
    mc_u25_prob = _poisson_u25_prob(combined_lambda)
    mc_u35_prob = _poisson_u35_prob(combined_lambda)

    # ── SCORING ──────────────────────────────────────────────────────────────
    # Formation defensive signals
    h_tactical = (home_dna or {}).get("tactical") if isinstance(home_dna, dict) else None
    a_tactical = (away_dna or {}).get("tactical") if isinstance(away_dna, dict) else None
    h_form_def = _formation_is_defensive(home_formation, h_tactical)
    a_form_def = _formation_is_defensive(away_formation, a_tactical)
    formation_score = 0.0
    formation_fired = 0
    formation_details = []
    if h_form_def:
        formation_score += PT_FORMATION_DEFENSIVE * 0.6
        formation_fired += 1
        formation_details.append(f"home formation {home_formation} is defensive")
    if a_form_def:
        formation_score += PT_FORMATION_DEFENSIVE * 0.6
        formation_fired += 1
        formation_details.append(f"away formation {away_formation} is defensive")

    # Keeper signals
    h_gk_cpg = _safe_float(d_home.get("gk_leak")) if d_home else None
    a_gk_cpg = _safe_float(d_away.get("gk_leak")) if d_away else None
    gk_score, gk_detail = _keeper_score(h_gk_cpg, a_gk_cpg)

    # Missing players
    miss_score, miss_detail = _missing_player_signal(d_home, d_away)

    # DNA signals
    dna_score, dna_fired, dna_detail = _dna_signal(home_dna, away_dna, clash)

    # Attack index
    ai_score, ai_detail = _attack_index_signal(d_home, d_away)

    # ── U25 SCORE ────────────────────────────────────────────────────────────
    u25_raw = formation_score + gk_score + miss_score + dna_score + ai_score
    # Bonus for low lambda (fewer expected goals = better for under)
    u25_lambda_bonus = False
    if combined_lambda <= 2.0:
        u25_raw += 15
        u25_lambda_bonus = True
    elif combined_lambda <= 2.4:
        u25_raw += 10
        u25_lambda_bonus = True
    # Penalty if lambda is high (against the under)
    if combined_lambda >= 3.0:
        u25_raw -= 15
    elif combined_lambda >= 2.6:
        u25_raw -= 8

    u25_score = max(0.0, min(100.0, u25_raw))
    u25_signals_fired = formation_fired + dna_fired + (1 if u25_lambda_bonus else 0)

    # ── U35 SCORE ────────────────────────────────────────────────────────────
    u35_raw = (formation_score * 0.7 + gk_score * 0.7
               + miss_score * 0.7 + dna_score + ai_score)
    if combined_lambda <= 2.6:
        u35_raw += 12
    elif combined_lambda <= 3.0:
        u35_raw += 8
    if combined_lambda >= 3.5:
        u35_raw -= 12
    elif combined_lambda >= 3.2:
        u35_raw -= 6

    u35_score = max(0.0, min(100.0, u35_raw))
    u35_signals_fired = formation_fired + dna_fired

    # ── TIERS ────────────────────────────────────────────────────────────────
    u25_tier = _get_u25_tier(u25_score, u25_signals_fired, gates_passed)
    u35_tier = _get_u35_tier(u35_score, gates_passed)

    # ── BUILD PICK ROW (same structure as UndersPick) ──────────────────────
    home_name = (d_home.get("team_name")
                 or (pm_row or {}).get("home", {}).get("team_name"))
    away_name = (d_away.get("team_name")
                 or (pm_row or {}).get("away", {}).get("team_name"))

    # Fallback for names from board fixture name
    if not home_name or not away_name:
        name_str = fixture.get("name", "")
        for sep in (" vs ", " v ", " - "):
            if sep in name_str:
                h, _, a = name_str.partition(sep)
                home_name = home_name or h.strip()
                away_name = away_name or a.strip()
                break

    gate_reasons_str = "; ".join(gate_reasons) if gate_reasons else ""

    pick = {
        "fixture_id": fixture_id,
        "fixture": fixture.get("name", ""),
        "home_team": home_name or "?",
        "away_team": away_name or "?",
        "combined_lambda": round(combined_lambda, 2),
        "mc_u25_prob": round(mc_u25_prob or 0, 3) if mc_u25_prob else None,
        "mc_u35_prob": round(mc_u35_prob or 0, 3) if mc_u35_prob else None,
        "u25_score": round(u25_score, 1),
        "u25_tier": u25_tier,
        "u25_signals_fired": u25_signals_fired,
        "u35_score": round(u35_score, 1),
        "u35_tier": u35_tier,
        "u35_signals_fired": u35_signals_fired,
        "home_gk_cpg": round(h_gk_cpg, 2) if h_gk_cpg is not None else None,
        "away_gk_cpg": round(a_gk_cpg, 2) if a_gk_cpg is not None else None,
        "home_gk_note": _gk_note(d_home.get("gk_verdict"), h_gk_cpg),
        "away_gk_note": _gk_note(d_away.get("gk_verdict"), a_gk_cpg),
        "fatigue_home": 0.0,
        "fatigue_away": 0.0,
        "gates_passed": gates_passed,
        "gate_reasons": gate_reasons_str,
        "gate_home_scored": gate_detail.get("gate_home_scored"),
        "gate_away_scored": gate_detail.get("gate_away_scored"),
        "gate_home_conceded": gate_detail.get("gate_home_conceded"),
        "gate_away_conceded": gate_detail.get("gate_away_conceded"),
        "gate_h2h": gate_detail.get("gate_h2h", "n/a"),
        # Live-specific fields (extra context on the same row)
        "is_live": True,
        "fixture_status": fixture_status,
        "formation_home": home_formation or None,
        "formation_away": away_formation or None,
        "home_archetype": ((home_dna or {}).get("archetype")
                           if isinstance(home_dna, dict) else None),
        "away_archetype": ((away_dna or {}).get("archetype")
                           if isinstance(away_dna, dict) else None),
        "home_goal_intent": (_safe_float((home_dna or {}).get("pillars", {}).get("Goal_Intent"))
                             if isinstance(home_dna, dict) else None),
        "away_goal_intent": (_safe_float((away_dna or {}).get("pillars", {}).get("Goal_Intent"))
                             if isinstance(away_dna, dict) else None),
        "combined_goal_intent": _safe_float((clash or {}).get("combined_goal_intent")),
        "combined_box_dominance": _safe_float((clash or {}).get("combined_box_dominance")),
        "market_signal": ((clash or {}).get("market_signals", {}).get("Over_Under")
                          if isinstance(clash, dict) else None),
        "home_attack_index": _safe_float(d_home.get("attack_index")),
        "away_attack_index": _safe_float(d_away.get("attack_index")),
        "minute": fixture.get("minute"),
        "score": fixture.get("score"),
        "live_signals_detail": {
            "formation": "; ".join(formation_details) if formation_details
                         else "no defensive formation detected",
            "keeper": gk_detail,
            "missing_players": miss_detail,
            "dna": dna_detail,
            "attack_index": ai_detail,
            "lambda": f"combined_lambda={combined_lambda:.2f}",
        },
    }
    return pick


# ── RUN FUNCTION ───────────────────────────────────────────────────────────────

def run_live_under_engine():
    """
    Run the Stage 9 live under engine.

    Scans all fixtures on the orchestrator board, admits only those with
    official lineup + full formation that are LIVE or INCOMING (about to
    start), scores each for under potential using DNA/formation/GK/missing-
    player/defensive-form signals, and writes the results to
    stage9_live_unders.json.

    Each pick carries fixture_status = "live" | "incoming" so the frontend
    can group them in a dedicated "Incoming Match Under List" section.

    Runs on zero API calls — reads only files the live cycle already maintains.
    """
    board_doc = _load_json(BOARD_FILE, {})
    matches = _as_rows(board_doc.get("matches", [])
                       if isinstance(board_doc, dict) else board_doc)

    danger_rows = _as_rows(_load_json(DANGER_FILE, []))
    prematch_audit = _load_json(PREMATCH_FILE, {})  # dict keyed by fixture_id
    dna_cache = _load_json(DNA_PROFILES_FILE, {})
    clash_cache = _as_rows(_load_json(STYLE_CLASHES_FILE, []))
    history_cache = _load_json(HISTORY_CACHE_FILE, {})

    picks = []
    for fixture in matches:
        if not isinstance(fixture, dict):
            continue
        # Skip finished fixtures
        if fixture.get("is_finished"):
            continue
        try:
            pick = _score_fixture(
                fixture, danger_rows, prematch_audit,
                dna_cache, clash_cache, history_cache,
            )
            if pick:
                picks.append(pick)
        except Exception as exc:
            # One bad fixture must not break the cycle
            fixture_id = fixture.get("id") or fixture.get("fixture_id")
            print(f"[Stage 9] fixture {fixture_id}: skipped ({exc})")

    # Sort by best score (u35 first, then u25, since U3.5 is softer)
    picks.sort(key=lambda p: (p.get("u35_score") or 0, p.get("u25_score") or 0),
               reverse=True)

    payload = {
        "generated_at": time.time(),
        "engines": len(picks),
        "picks": picks,
    }

    # Atomic write
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, OUTPUT_FILE)

    print(f"[Stage 9] Live Under Engine: {len(picks)} under picks written to {OUTPUT_FILE}")
    return payload


if __name__ == "__main__":
    run_live_under_engine()
