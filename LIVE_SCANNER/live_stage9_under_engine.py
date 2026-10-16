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
from datetime import datetime, timedelta, timezone

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
# Persistent finished-results layer (written continuously by live_cache
# and nightly by the archiver) — the timing-independent source of truth
# for "did this fixture finish?" (see _finished_fixture_ids).
FT_SNAPSHOT_FILE = os.path.join(DATA_DIR, "ft_result_snapshot.json")

# ── Stage 9's OWN light per-team history cache ──────────────────────────────
# The form gates and lambda need each team's last-5 completed fixtures, which
# live in Stage 4's danger_history_cache.json — but that cache only holds the
# teams Stage 4 happened to fetch, so on a quiet afternoon every incoming
# fixture failed the gates with "no completed match history" (data missing,
# not bad form — the exact dishonesty Stage 4's own comments refuse to make).
# Stage 9 therefore backfills the missing teams itself, bounded per cycle,
# through the SAME paced/429-aware GET Stage 3 uses. The rows land in a
# SEPARATE file on purpose: this cache carries only scores/participants/
# state_id, while Stage 4's reader needs lineups/statistics payloads that a
# light entry would silently break.
S9_HISTORY_FILE = os.path.join(DATA_DIR, "stage9_history_cache.json")
S9_HISTORY_TTL = 6 * 3600       # same refresh cadence as Stage 4's HISTORY_TTL
S9_BACKFILL_MAX_PER_RUN = 30    # a full incoming slate (~78 teams) warms in ~3 cycles, quota-safe
LIVE_UNDERS_SAVE_KEY = "live_unders"  # dated snapshots via output_store, same as pre-match "unders"

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


def _has_history_entry(history_cache, team_id):
    """True when the cache holds an entry for the team at all.

    Distinguishes 'never fetched' (gates cannot be evaluated yet) from
    'fetched, nothing usable in it' (gates legitimately see no history).
    """
    tid = str(team_id)
    entry = history_cache.get(tid) or history_cache.get(_safe_int(team_id))
    return isinstance(entry, dict)


def _load_s9_history():
    """Load Stage 9's own light history cache, dropping expired entries."""
    data = _load_json(S9_HISTORY_FILE, {})
    if not isinstance(data, dict):
        return {}
    now = time.time()
    return {
        k: v for k, v in data.items()
        if isinstance(v, dict) and (now - v.get("at", 0)) < S9_HISTORY_TTL
    }


def _save_s9_history(cache):
    """Atomically persist Stage 9's light history cache."""
    tmp = S9_HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, default=str)
    os.replace(tmp, S9_HISTORY_FILE)


def _missing_history_teams(candidates, danger_rows, prematch_audit, history_cache):
    """Team ids among the scored candidates that have no cached history.

    Uses the same danger/prematch resolution as _score_fixture so it never
    asks for teams whose fixture would not be scored anyway. Falls back to
    the prematch audit's team ids when Stage 4 never audited the fixture
    (no danger row) — those teams otherwise sat in "pending" forever because
    they were never even queued for backfill.
    """
    missing = set()
    for fixture in candidates:
        if not isinstance(fixture, dict) or fixture.get("is_finished"):
            continue
        fid = str(fixture.get("id") or fixture.get("fixture_id") or "")
        danger_row = next(
            (r for r in danger_rows if str(r.get("fixture_id")) == fid), None)
        pm_row = prematch_audit.get(fid) if isinstance(prematch_audit, dict) else None
        if danger_row is not None:
            d_home = danger_row.get("home_team") or {}
            d_away = danger_row.get("away_team") or {}
        else:
            d_home, d_away = {}, {}
        home_id = d_home.get("id") or (pm_row or {}).get("home", {}).get("team_id")
        away_id = d_away.get("id") or (pm_row or {}).get("away", {}).get("team_id")
        for tid in (home_id, away_id):
            if tid is not None and not _has_history_entry(history_cache, tid):
                missing.add(str(tid))
    return missing


def _backfill_s9_histories(missing_ids, history_cache):
    """Fetch light last-N fixtures for teams lacking history, bounded per run.

    Goes through Stage 3's paced, 429-aware GET (shared provider gate) and
    stops early on any acquisition failure so a suspended provider window
    never gets hammered. Returns the updated cache (also persisted).
    """
    if not missing_ids:
        return history_cache
    try:
        from LIVE_SCANNER.live_stage3_incoming import GET as _GET
    except Exception as exc:
        print(f"[Stage 9] history backfill unavailable: {exc}")
        return history_cache
    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=150)).isoformat()
    fetched = 0
    for tid in sorted(missing_ids)[:S9_BACKFILL_MAX_PER_RUN]:
        resp = _GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{tid}",
            params={
                "include": "scores;participants",
                "filter": "fixtureStates:5",
                "per_page": 50,
            },
        )
        rows = resp.get("data") if isinstance(resp, dict) else None
        if not rows:
            # Empty or failed pull — do NOT cache it as "team has no history"
            # (Stage 4's principle). Skip to the NEXT team instead of stopping
            # the whole run, so one dead team no longer starves the other ~29.
            # The team retries next cycle.
            print(f"[Stage 9] history backfill: skipping team {tid} "
                  f"({'no data' if rows is None else 'empty'})")
            continue
        history_cache[str(tid)] = {"at": time.time(), "data": rows}
        fetched += 1
    if fetched:
        try:
            _save_s9_history(history_cache)
            print(f"[Stage 9] history backfill: cached {fetched} team(s) "
                  f"({len(missing_ids) - fetched} remaining)")
        except Exception as exc:
            print(f"[Stage 9] history cache save failed: {exc}")
    return history_cache


def _clear_gates(history_cache, home_id, away_id):
    """Apply the defensive-form gates.

    GATE 1: neither team scored more than GATE_MAX_SCORED in last 5
    GATE 2: neither team conceded more than GATE_MAX_CONCEDED in last 5

    Returns (passed, reasons, detail) where passed is:
      True  — gates evaluated and cleared
      False — gates evaluated and at least one hard condition failed
      None  — gates NOT evaluable yet (ZERO usable history on a side); the
              pick is neither promoted nor killed, and the UI shows "pending".

    THIN HISTORY: 1-4 usable games (instead of 5) are evaluated honestly on
    what exists, with "(thin history n=X)" appended to the reasons and n
    exposed in detail. Zero history stays None — we never fake confidence.
    """
    h_sc, h_cc, h_n = _compute_last5_form(history_cache, home_id)
    a_sc, a_cc, a_n = _compute_last5_form(history_cache, away_id)
    reasons = []
    detail = {}
    thin_flags = []
    if h_n == 0:
        if _has_history_entry(history_cache, home_id):
            reasons.append("home has no completed match history")
        else:
            reasons.append("home history pending — gates not yet evaluable")
    else:
        detail["gate_home_scored"] = h_sc
        detail["gate_home_conceded"] = h_cc
        detail["gate_home_n"] = h_n
        if h_n < LAST_N_GAMES:
            thin_flags.append(f"home thin history n={h_n}")
        if h_sc is not None and h_sc > GATE_MAX_SCORED:
            reasons.append(f"home scored {h_sc:.0f} > {GATE_MAX_SCORED}")
        if h_cc is not None and h_cc > GATE_MAX_CONCEDED:
            reasons.append(f"home conceded {h_cc:.0f} > {GATE_MAX_CONCEDED}")
    if a_n == 0:
        if _has_history_entry(history_cache, away_id):
            reasons.append("away has no completed match history")
        else:
            reasons.append("away history pending — gates not yet evaluable")
    else:
        detail["gate_away_scored"] = a_sc
        detail["gate_away_conceded"] = a_cc
        detail["gate_away_n"] = a_n
        if a_n < LAST_N_GAMES:
            thin_flags.append(f"away thin history n={a_n}")
        if a_sc is not None and a_sc > GATE_MAX_SCORED:
            reasons.append(f"away scored {a_sc:.0f} > {GATE_MAX_SCORED}")
        if a_cc is not None and a_cc > GATE_MAX_CONCEDED:
            reasons.append(f"away conceded {a_cc:.0f} > {GATE_MAX_CONCEDED}")
    if not reasons:
        if thin_flags:
            reasons.extend(thin_flags)
        return True, reasons, detail
    hard_fail = [r for r in reasons if "pending" not in r and "thin history" not in r]
    if thin_flags and not hard_fail:
        reasons.extend(thin_flags)
    return (False if hard_fail else None), reasons, detail


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


def _get_u25_tier(score, signals_fired, gates_passed, gate_reasons=""):
    """Assign U2.5 tier using the same structure as the pre-match engine.

    gates_passed=False kills the pick (existing behaviour). gates_passed=None
    means the form gates are not evaluable yet (history still backfilling):
    the score tier is kept but marked provisional instead of being killed for
    data the engine simply does not have yet. Thin history (1-4 games) is
    evaluated honestly and marked "(thin history)".
    """
    if gates_passed is False:
        return "🚫 U2.5 GATE FAIL"
    suffix = "" if gates_passed else " (gates pending)"
    if gates_passed and isinstance(gate_reasons, str) and "thin history" in gate_reasons:
        suffix = " (thin history)"
    if score >= U25_TIER1_SCORE and signals_fired >= 4:
        tier = "🛡️ U2.5 TIER 1 — LOCK"
    elif score >= U25_TIER2_SCORE:
        tier = "✅ U2.5 TIER 2 — SOLID"
    elif score >= U25_TIER3_SCORE:
        tier = "📊 U2.5 TIER 3 — LEAN"
    else:
        tier = "⚪ U2.5 BELOW THRESHOLD"
    return tier + suffix


def _get_u35_tier(score, gates_passed, gate_reasons=""):
    """Assign U3.5 tier using the same structure as the pre-match engine.

    Same three-state contract as _get_u25_tier (see above), including the
    "(thin history)" mark for 1-4 game evaluations.
    """
    if gates_passed is False:
        return "🚫 U3.5 GATE FAIL"
    suffix = "" if gates_passed else " (gates pending)"
    if gates_passed and isinstance(gate_reasons, str) and "thin history" in gate_reasons:
        suffix = " (thin history)"
    if score >= U35_TIER1_SCORE:
        tier = "🧱 U3.5 TIER 1 — LOCK"
    elif score >= U35_TIER2_SCORE:
        tier = "✅ U3.5 TIER 2 — SOLID"
    elif score >= U35_TIER3_SCORE:
        tier = "📊 U3.5 TIER 3 — LEAN"
    else:
        tier = "⚪ U3.5 BELOW THRESHOLD"
    return tier + suffix


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
    gate_reasons_preview = "; ".join(gate_reasons) if gate_reasons else ""
    u25_tier = _get_u25_tier(u25_score, u25_signals_fired, gates_passed, gate_reasons_preview)
    u35_tier = _get_u35_tier(u35_score, gates_passed, gate_reasons_preview)

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
        # is_live is now the REAL match state: the frontend LIVE badge reads
        # this field, and incoming (not-started) picks must not show it.
        "is_live": fixture_status == "live",
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

def _finished_fixture_ids(board_rows, prematch_audit, today_str):
    """Every fixture known-finished from the on-disk sources, as a set of str ids.

    Sources (all read-only, zero provider calls):
      * the orchestrator board rows with is_finished=True
      * the prematch audit rows with is_finished=True
      * data/ft_result_snapshot.json fixtures for today_str — settlement's own
        persistent record, written continuously by live_cache the moment a
        finish is observed, INDEPENDENT of the stage order below.

    The FT snapshot is what breaks the timing deadlock the old retention had:
    Stage 1 culls finished fixtures from the audit BEFORE this engine runs, and
    Stage 6 (which writes the board's finished rows) runs AFTER it — so at the
    cycle a pick left the list, neither the audit nor the board could confirm
    finished-ness, and the row was dropped forever (measured 2026-10-16: 0
    retained in EVERY cycle; the day's list decayed 19 → 2).
    """
    finished = set()
    for m in board_rows or []:
        if isinstance(m, dict) and m.get("is_finished"):
            fid = m.get("id") or m.get("fixture_id")
            if fid not in (None, ""):
                finished.add(str(fid))
    if isinstance(prematch_audit, dict):
        for fid, row in prematch_audit.items():
            if isinstance(row, dict) and row.get("is_finished"):
                if fid not in (None, ""):
                    finished.add(str(fid))
    try:
        with open(FT_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            ft = json.load(f)
        day = (ft.get("fixtures") or {}).get(today_str) or {}
        for fid in day.keys():
            finished.add(str(fid))
    except Exception:
        pass  # snapshot absent/unreadable — the other two sources still apply
    return finished


def _merge_snapshot_rows(picks, prev_rows, finished_ids, today_str):
    """Merge this cycle's picks into the day's dated snapshot — STICKY FINISHED.

    Returns (merged_rows, retained_count).

    Rules:
      * Current live/incoming picks always win (a fixture still in the list is
        never duplicated by its older row).
      * A previous row already marked fixture_status="finished" is kept
        UNCONDITIONALLY — finished is a terminal state and needs no
        re-confirmation. This is the stickiness the old code lacked: it
        re-checked the audit/board every cycle, and one missed confirmation
        (guaranteed by the stage order, see _finished_fixture_ids) dropped the
        row forever.
      * A previous live/incoming row whose fixture_id is in `finished_ids` is
        promoted to finished and kept (the moment a fixture settles, it stays
        in the day's history for Verify and study).
      * A previous row that left the list WITHOUT finishing (e.g. its lineup
        was withdrawn) is still dropped — freezing a stale never-played pick
        into history would be dishonest.
    """
    picks = [p for p in picks if isinstance(p, dict)]
    current_ids = {str(p.get("fixture_id")) for p in picks
                   if p.get("fixture_id") not in (None, "")}
    kept = []
    seen_kept = set()
    for old in prev_rows or []:
        if not isinstance(old, dict):
            continue
        fid = str(old.get("fixture_id") or "")
        if not fid or fid in current_ids or fid in seen_kept:
            continue  # current row wins; duplicate ids collapse to one
        row = dict(old)
        if row.get("fixture_status") != "finished":
            if fid not in finished_ids:
                continue  # vanished for a real reason — stays out of history
            row["fixture_status"] = "finished"
            row["is_live"] = False
            row.setdefault("finished_date", today_str)
        kept.append(row)
        seen_kept.add(fid)
    return picks + kept, len(kept)


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
    # Form gates + lambda read this merged view: Stage 4's heavy cache wins on
    # overlap, Stage 9's own light cache covers the teams Stage 4 never fetched
    # (backfilled below, bounded per run).
    s9_history = _load_s9_history()
    stage4_history = _load_json(HISTORY_CACHE_FILE, {})
    if isinstance(stage4_history, dict):
        history_cache = {**s9_history, **stage4_history}
    else:
        history_cache = s9_history

    # ── CANDIDATE SET: board ∪ prematch-audit upcoming ──────────────────────
    # The orchestrator board only ever carries IN-PLAY matches — plus retained
    # finished rows on idle cycles. On an idle afternoon this engine therefore
    # saw ZERO candidates and the "incoming" half of the feature could never
    # fire, even with official lineups already published for the evening slate.
    # prematch_team_audit.json (the same cycle-maintained file the admission
    # gate below already reads) also tracks today's NOT_STARTED fixtures with
    # state/lineup/formation, so merge them into the candidate set:
    #   - board rows win on fixture_id collision;
    #   - each audit-only row is synthesised into the minimal fixture shape
    #     _score_fixture consumes (id / name / is_live / is_not_started).
    # Still zero provider calls — both files are already on disk.
    candidates = []
    seen_ids = set()
    for fixture in matches:
        if not isinstance(fixture, dict):
            continue
        fid = fixture.get("id") or fixture.get("fixture_id")
        if fid is not None:
            seen_ids.add(str(fid))
        candidates.append(fixture)
    if isinstance(prematch_audit, dict):
        for fid, row in prematch_audit.items():
            if not isinstance(row, dict) or str(fid) in seen_ids:
                continue
            if row.get("is_finished"):
                continue  # settled — never a live-under candidate
            candidates.append({
                "id": str(fid),
                "name": row.get("fixture", ""),
                "is_live": bool(row.get("is_live")),
                "is_not_started": bool(
                    row.get("is_upcoming") or row.get("state") == "NOT_STARTED"
                ),
            })

    # ── HISTORY BACKFILL (bounded, paced) ────────────────────────────────────
    # Warm the light per-team history cache for candidates the merged view
    # cannot evaluate yet, so the form gates and lambda flip from "pending" to
    # real reads over the next few cycles instead of failing every pick.
    # Backfill writes into Stage 9's LIGHT cache only — never into the merged
    # view — so Stage 4's heavy entries are never duplicated to disk here.
    missing = _missing_history_teams(candidates, danger_rows, prematch_audit,
                                     history_cache)
    if missing:
        s9_history = _backfill_s9_histories(missing, s9_history)
        if isinstance(stage4_history, dict):
            history_cache = {**s9_history, **stage4_history}
        else:
            history_cache = s9_history

    picks = []
    for fixture in candidates:
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

    # Atomic write (live file — current live/incoming only, same as before)
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, OUTPUT_FILE)

    # ── DATED SNAPSHOT (5-day history, same as pre-match "unders") ──────────
    # The live file above is overwritten every cycle and finished fixtures
    # vanish the next cycle. Pre-match solves this with dated snapshots:
    # output_store.save("unders", date, ...) -> output/cache/unders__{date}.json,
    # one file per date that the date picker reads back. Live mirrors it:
    # output/cache/live_unders__{date}.json accumulates the day's universe —
    # current picks upserted, previously-seen fixtures that have since finished
    # retained with fixture_status="finished" + finished_date. Same collapse
    # guard as pre-match so a thin cycle can never wipe a good snapshot.
    try:
        sys.path.insert(0, BASE_DIR) if BASE_DIR not in sys.path else None
        import output_store as _live_store
        today_str = datetime.now(timezone.utc).date().isoformat()
        prev_data, _ = _live_store.load(LIVE_UNDERS_SAVE_KEY, today_str, default=[])
        prev_rows = prev_data if isinstance(prev_data, list) else []
        # STICKY FINISHED retention (see _merge_snapshot_rows): finished rows
        # stay in the day's snapshot unconditionally; newly-finished picks are
        # promoted from board + audit + the FT result snapshot, so the stage
        # order (1 culls the audit before us, 6 writes the board after us)
        # can never silently drop the day's history again.
        finished_ids = _finished_fixture_ids(matches, prematch_audit, today_str)
        merged, retained = _merge_snapshot_rows(
            picks, prev_rows, finished_ids, today_str)
        _live_store.save(LIVE_UNDERS_SAVE_KEY, today_str, merged, guard=True)
        print(f"[Stage 9] dated snapshot: {len(merged)} rows "
              f"({len(picks)} current + {retained} retained finished) "
              f"-> {LIVE_UNDERS_SAVE_KEY}__{today_str}")
    except Exception as exc:
        print(f"[Stage 9] dated snapshot failed (live file still written): {exc}")

    print(f"[Stage 9] Live Under Engine: {len(picks)} under picks written to {OUTPUT_FILE}")
    return payload


if __name__ == "__main__":
    run_live_under_engine()
