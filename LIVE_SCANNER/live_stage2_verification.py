import os
import sys
import time
import json
import random
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# SHARED FIXTURE-STATE CLASSIFIER — the single definition of finished / live
# used by Stage 1, Stage 2 and the API, so no two components can disagree about
# whether a match is finished.
try:
    from LIVE_SCANNER.live_state_classifier import (
        classify_fixture, admit_to_prematch_board, parse_kickoff_utc,
    )
except ImportError:  # executed as a plain script from the backend root
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "LIVE_SCANNER"))
    from live_state_classifier import (
        classify_fixture, admit_to_prematch_board, parse_kickoff_utc,
    )

# ── SHARED 429 COOLDOWN GATE (live-stage side) ───────────────────────────────
# Mirrors live_stage1_prematch: the archiver/stages broadcast cooldown windows
# into data/api_429_cooldown.lock; GET() paces itself through them so the
# components stop re-triggering each other's burst limits.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATE_FILE = os.path.join(_BASE_DIR, "data", "api_429_cooldown.lock")


def _api_gate_pace(tag=""):
    """Sleep while a shared 429 cooldown is active (cheap no-op otherwise).
    A few seconds of JITTER stagger the wake-up so siblings stop firing in
    lockstep and re-triggering the burst limit (the cooling circle)."""
    try:
        with open(_GATE_FILE, "r") as f:
            gate = json.load(f)
        until = float(gate.get("until", 0)) if isinstance(gate, dict) else 0.0
        remaining = until - time.time()
        if remaining > 0:
            sleep_s = min(remaining, 15.0) + random.random() * 3.0
            print(f"[API GATE] {tag}: shared cooldown active — pacing {sleep_s:.1f}s",
                  file=sys.stderr)
            time.sleep(sleep_s)
    except Exception:
        pass


def _api_gate_broadcast(wait_s, tag=""):
    """Record a shared cooldown so sibling processes also back off."""
    try:
        os.makedirs(os.path.dirname(_GATE_FILE), exist_ok=True)
        with open(_GATE_FILE + ".tmp", "w") as f:
            json.dump({"until": time.time() + wait_s, "by": tag or "live-stage"}, f)
        os.replace(_GATE_FILE + ".tmp", _GATE_FILE)
    except Exception:
        pass


def _api_gate_clear(tag=""):
    """A 200 just came back from the provider — the burst window is clearly
    over, so DISARM the shared cooldown instead of letting every sibling keep
    pacing until the old expiry (gate hygiene)."""
    try:
        os.makedirs(os.path.dirname(_GATE_FILE), exist_ok=True)
        with open(_GATE_FILE + ".tmp", "w") as f:
            json.dump({"until": 0, "by": f"cleared:{tag or 'live-stage'}"}, f)
        os.replace(_GATE_FILE + ".tmp", _GATE_FILE)
    except Exception:
        pass


# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

PREDICTIONS_FILE     = os.path.join(DATA_DIR, "live_predictions.json")
INCOMING_PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
VALIDATED_OUTPUT_FILE = os.path.join(DATA_DIR, "validated_picks.json")
# NOTE: stage 2 keeps its own FLAT squad cache ({pid: {...}}) and must not
# read the shared squad_cache.json written by stages 1/3/6 in the NEW
# {"players": {...}, "team_avg_leak": ...} format — loading that here makes
# extract_live_context()'s get_k() raise KeyError('pos') on every fixture.
CACHE_FILE           = os.path.join(DATA_DIR, "squad_cache_stage2_validator.json")
STATE_FILE           = os.path.join(DATA_DIR, "validation_state.json")
ALERT_FILE           = os.path.join(DATA_DIR, "alert_history.json")
# Persisted cycle board so /api/live/validation can return real `matches`
# and `total_live` (the console print_cycle_board output was never saved).
BOARD_FILE           = os.path.join(DATA_DIR, "validation_board.json")

# ==============================================================================
# CONFIGURATION
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
BASE_URL  = "https://api.sportmonks.com/v3/football/livescores/inplay"
HISTORY_URL = "https://api.sportmonks.com/v3/football"

# ── VALIDATION THRESHOLDS ───────────────────────────────────────────────────
# Raised from the 50%-era values on request: a single weak signal must not be
# able to carry a prediction. Engine 1's combined-SOT bar was set to 5 and then
# relaxed to 3 on request, because >5 suppressed almost every alert (1 of 28
# predictions reached SUPPORTED on the first cycle after tightening).
MIN_DA_RATIO        = 0.60   # was 0.50
MIN_SOT_RATIO       = 0.60   # was 0.50
MIN_BOX_TOUCH_DIFF  = 4      # was 2
MIN_MOMENTUM_FACTOR = 1.10   # was 1.30
MIN_CORNER_DIFF     = 2

# Engine 1 — combined shots on target required; passes when total > this value,
# i.e. 4 or more. THIS IS AN OVER THRESHOLD. It means "4+ is a lot of pressure".
ENGINE1_MIN_COMBINED_SOT = 3
# Engine 3 — recent key events inside the lookback window.
MIN_RECENT_KEY_EVENTS = 4

# ── UNDER-DIRECTION THRESHOLDS (derived, not invented) ────────────────────────
# The UNDER gate used to borrow the OVER constants and one hardcoded value:
#   Engine 1  total <= 1                       (unreachable in practice)
#   Engine 2  tot_sot <= ENGINE1_MIN_COMBINED_SOT  and  tot_box <= the same
# Neither was ever derived for the UNDER direction. The `1` fails almost every
# ordinary first half, and comparing BOX ENTRIES against a SHOTS-ON-TARGET
# threshold is a unit error.
#
# These values come from 752 finished matches already in
# data/danger_history_cache.json (measured, not guessed):
#
#   combined shots on target, full match : p10=3  p25=6  med=8  p75=10 p90=13
#   combined box entries,  full match     : p10=0  p25=4  med=12 p75=16 p90=21
#   combined goals,       full match      : p10=1  p25=1  med=2  p75=3  p90=4
#
# Roughly 45% of a match's shots land in the first half, so a 45' reading with
# a combined SOT of 3-4 is a completely NORMAL first half. "SOT <= 1" therefore
# rejected the majority of healthy 0-0 half-times, which is how a goalless match
# at 84' ended up locked as FINAL_REJECTED.
#
# UNDER_SOT_MAX_MEDIAN  — at or below the 45' median, the under is ON TRACK.
# UNDER_SOT_MAX_STRONG — at or below the 45' p25, it is STRONGLY on track.
UNDER_SOT_MAX_MEDIAN = 4
UNDER_SOT_MAX_STRONG = 2
# Box entries are judged on the box distribution, not the SOT one. The 45'
# p25 for combined box entries is ~2 and the median ~6.
UNDER_BOX_MAX_SUPPORT = 4

# The provider does not emit "touches-in-opposition-box" or "attacks-in-box",
# so the previous box source was permanently 0 and the box signal could never
# contribute to Engine 2. "shots-insidebox" is a real, available stat.
BOX_STAT_CODES = ("shots-insidebox", "attacks-in-box", "touches-in-opposition-box")
# NO FALLBACK. The old fallback mapped "shots-total" into the box slot, then
# compared it against a box threshold — two different units. Combined shots-total
# has a median of ~8 per match against a box threshold of 3, so the fallback
# could never pass and silently dragged Engine 2 down with it. A genuinely
# absent box is reported as unavailable and judged on SOT alone, which
# _opt_box() and Engine 2 already support.
BOX_STAT_FALLBACK = None

# ── MARKET DIRECTION ───────────────────────────────────────────────────────
# Engines 2 and 3 and the forensic engine previously read the SAME evidence
# (shots on target, box entries, recent key events) without ever being told
# which direction the market runs in. That is precisely how one fixture could
# open the gate for UNDER 2.5 and OVER 2.5 at the same time. Every engine now
# receives the direction and scores in it: an UNDER gate can no longer be
# opened by "lots of shots on target", and GG stays direction-neutral.
# These live up here (not beside their helper) because they are used as default
# argument values in the engine signatures below.
DIRECTION_OVER    = "OVER"
DIRECTION_UNDER   = "UNDER"
DIRECTION_NEUTRAL = "NEUTRAL"

# ── VALIDATION GATE POLICY ───────────────────────────────────────────────────
# Validators no longer return a loose boolean. Each one reports one of four
# states so that "nothing bad happened" can never be counted as positive
# predictive evidence (it used to return True for MAINTAINED / STABLE).
V_SUPPORTED    = "SUPPORTED"
V_CONTRADICTED = "CONTRADICTED"
V_NEUTRAL      = "NEUTRAL"
V_INSUFFICIENT = "INSUFFICIENT_DATA"
# A settled prediction is not "unknown" — it has a definitive outcome, so its
# gate verdict is no longer on display.
V_SETTLED      = "SETTLED"

# A standard alert requires genuine agreement across the three statistical
# engines. This replaces the old `passed_count >= 1` rule, which let a single
# weak signal (reported as STATS_1/3) pass the whole validator.
STATS_MIN_ENGINES_FOR_PASS = 2
# A single engine out of three is not a rejection either — it is explicitly
# "not enough evidence yet" so the board can say so honestly.
STATS_PARTIAL_ENGINES = 1

SQUAD_CACHE           = {}
MATCH_CONTEXT_CACHE   = {}
MATCH_VALIDATION_STATE = {}
ALERT_HISTORY_CACHE   = set()
VALIDATED_ALERTS      = {}

# ==============================================================================
# PERSISTENT MEMORY MANAGERS
# ==============================================================================
def load_memory():
    global SQUAD_CACHE, MATCH_VALIDATION_STATE, ALERT_HISTORY_CACHE, VALIDATED_ALERTS
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f: SQUAD_CACHE = json.load(f)
        except: SQUAD_CACHE = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: MATCH_VALIDATION_STATE = json.load(f)
        except: MATCH_VALIDATION_STATE = {}
    if os.path.exists(ALERT_FILE):
        try:
            with open(ALERT_FILE, 'r') as f: ALERT_HISTORY_CACHE = set(json.load(f))
        except: ALERT_HISTORY_CACHE = set()
    if os.path.exists(VALIDATED_OUTPUT_FILE):
        try:
            with open(VALIDATED_OUTPUT_FILE, 'r') as f: VALIDATED_ALERTS = json.load(f)
        except: VALIDATED_ALERTS = {}

def save_memory():
    try:
        with open(CACHE_FILE,            'w') as f: json.dump(SQUAD_CACHE, f)
        with open(STATE_FILE,            'w') as f: json.dump(MATCH_VALIDATION_STATE, f)
        with open(ALERT_FILE,            'w') as f: json.dump(list(ALERT_HISTORY_CACHE), f)
        with open(VALIDATED_OUTPUT_FILE, 'w') as f: json.dump(VALIDATED_ALERTS, f)
    except Exception as e:
        print(f"Error saving memory: {e}", file=sys.stderr)

# ==============================================================================
# UTILITIES
# ==============================================================================
def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur


# ── CANONICAL MARKET IDENTITY ───────────────────────────────────────────────
# The Stage 1 and Stage 3 feeds each spell the same market differently
# ("O2.5" vs "OVER_2.5"), and both attach a free-text `reason`. Deduping on
# the raw object therefore treated one market as several. Every market now
# resolves to exactly one canonical key so a fixture can never track the same
# market twice and validation state stays stable across cycles.
MARKET_ALIASES = {
    "O2.5":        "OVER_2.5",
    "OVER2.5":     "OVER_2.5",
    "OVER":        "OVER_2.5",
    "U2.5":        "UNDER_2.5",
    "UNDER2.5":    "UNDER_2.5",
    "UNDER":       "UNDER_2.5",
    "GG":          "GG",
    "BTTS":        "GG",
    "GG_OVER_2.5": "GG_OVER_2.5",
    "TO_SCORE":    "TO_SCORE",
    "SCORE":       "TO_SCORE",
}


def normalize_pick(pick):
    """
    Return (canonical_key, normalized_pick) for a feed pick.

    canonical_key identifies the MARKET only: (market, target). The `reason`
    text is deliberately excluded so two spellings of one market collapse into
    a single tracked prediction.
    """
    if not isinstance(pick, dict):
        return None, None
    raw_type = str(pick.get("type", "")).strip().upper().replace(" ", "")
    market = MARKET_ALIASES.get(raw_type, raw_type or "UNKNOWN")
    target = pick.get("target_loc") or "match"
    key = f"{market}:{target}"
    normalized = dict(pick)
    normalized["type"] = market
    normalized["target_loc"] = target
    normalized["market"] = market
    normalized["canonical_key"] = key
    return key, normalized


def _read_pick_feed(path):
    """Read either the Stage 1 or Stage 3 fixture-keyed pick feed."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    for fid, value in raw.items():
        if isinstance(value, list):
            picks = value
        elif isinstance(value, dict):
            picks = value.get("picks", [])
        else:
            picks = []
        if isinstance(picks, list) and picks:
            result[str(fid)] = picks
    return result


def _load_pick_feeds():
    """
    Merge Stage 1 and Stage 3 picks into ONE canonical list per fixture.

    Stage 1 is the older strategic feed; Stage 3 is the lineup/forensic feed.
    Both can legitimately contain the same fixture, and an empty Stage 1 file
    must not make the validator blind to current Stage 3 picks.

    Dedup is by canonical MARKET key rather than the raw pick object, so the
    same market is never tracked twice regardless of which feed spelled it
    differently or what justification text it carried.
    """
    merged = {}
    for path in (PREDICTIONS_FILE, INCOMING_PREDICTIONS_FILE):
        for fid, picks in _read_pick_feed(path).items():
            existing = merged.setdefault(fid, [])
            seen = {p.get("canonical_key") for p in existing}
            for pick in picks:
                key, normalized = normalize_pick(pick)
                if normalized is None or key in seen:
                    continue
                existing.append(normalized)
                seen.add(key)
    for fid, picks in merged.items():
        suppress_contradictory_markets(picks)
    return merged


# ── ONE DIRECTION PER FIXTURE ────────────────────────────────────────────────
# WHY THIS EXISTS
# A fixture was being validated and alerted on UNDER_2.5 and OVER_2.5 at the
# same time. Code 1 handed the validator an under; the incoming feed also
# carried two over markets for the same fixture, and both fired Supreme Alerts
# at 45'. They cannot both be honest readings of one scoreline, and the board
# ended up contradicting itself: the per-match list said UNLIKELY while Code 3C
# displayed two fired over alerts.
#
# A suppressed pick is KEPT and stays visible with its reason attached, so the
# audit trail survives, but it is never alertable and never receives a new
# verdict. The UNDER side is always the one that survives, because it is the
# market Code 1 committed to in the prematch feed.
SUPPRESSED_REASON = "Suppressed — contradictory market (fixture is tracked on an UNDER market)"


def suppress_contradictory_markets(picks):
    """
    Mark every OVER-market pick on a fixture that is also tracked UNDER.

    Returns the same list for convenience. Mutates in place: the caller merges
    these dicts straight into the board, so the suppression flag has to travel
    with the pick rather than be reported separately.
    """
    if not picks:
        return picks
    try:
        directions = {
            market_direction(p.get("market") or p.get("type"))
            for p in picks if isinstance(p, dict)
        }
    except Exception:
        return picks
    if DIRECTION_UNDER not in directions or DIRECTION_OVER not in directions:
        return picks
    for p in picks:
        if not isinstance(p, dict):
            continue
        if market_direction(p.get("market") or p.get("type")) == DIRECTION_OVER:
            p["suppressed"] = True
            p["suppressed_reason"] = SUPPRESSED_REASON
    return picks


def _pick_from_canonical_key(canonical_key):
    """
    Rebuild a minimal pick from a state key so an orphaned prediction can stay
    on the board. Only the market and target are recoverable — the original
    justification text is gone with the feed — so the pick is marked orphaned
    and never re-judged.
    """
    text = str(canonical_key or "")
    if ":" not in text:
        return None
    market, target = text.split(":", 1)
    if not market or not target:
        return None
    return {
        "type": market,
        "market": market,
        "target_loc": target,
        "canonical_key": text,
        "orphaned": True,
        "orphaned_reason": (
            "No longer in the Code 1 / incoming feed — kept so a prediction "
            "that already alerted can still be settled rather than vanishing"
        ),
    }


def carry_forward_orphans(feed):
    """
    Keep a prediction that alerted or reached a verdict after its feed row
    disappears.

    THE BUG THIS FIXES
    `live_predictions.json` and the incoming feed are rewritten every cycle from
    whatever Code 1 and Stage 3 currently hold. A market that is present in
    cycle N and absent in cycle N+1 simply disappeared from the tracked set —
    even though it had already fired a Supreme Alert and was sitting in the
    Code 3C confirmations table. It could never be validated again and never
    settled, so it was stranded in 3C indefinitely showing the verdict it had
    at the moment it fired.

    A state entry qualifies as an orphan when it carries real history (a
    verdict at any checkpoint, or an alert) and has no corresponding feed row.
    It is marked `orphaned`, is never re-judged, and is settled normally, so it
    reaches a terminal WON/LOST instead of hanging.
    """
    for fid, entries in list(MATCH_VALIDATION_STATE.items()):
        if not isinstance(entries, dict):
            continue
        # setdefault, not `feed.get(fid) or []`: a fixture that has dropped out
        # of the feed entirely is absent from the mapping, and `or []` produced a
        # throwaway list that was never written back — so the carried pick was
        # appended to nothing and the orphan was still silently dropped.
        present = feed.setdefault(fid, [])
        live_keys = {
            p.get("canonical_key") for p in present if isinstance(p, dict)
        }
        for state_key, state in entries.items():
            if not isinstance(state, dict):
                continue                      # "DONE" or legacy scalar
            if state_key in live_keys:
                continue
            has_history = bool(
                state.get("verdict_30")
                or state.get("verdict_45")
                or state.get("verdict_60")
                or state.get("alerted")
            )
            if not has_history:
                continue                      # never judged — nothing to keep
            carried = _pick_from_canonical_key(state_key)
            if carried is None:
                continue
            carried["suppressed"] = True
            carried["suppressed_reason"] = carried["orphaned_reason"]
            present.append(carried)
            state["orphaned"] = True
            state["orphaned_at"] = datetime.now().isoformat()
    return feed


def _stat_int(stats, key):
    """Provider stats arrive as floats (or occasionally strings/None)."""
    try:
        return int(float(stats.get(key, 0) or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def _opt_box(stats):
    """
    Box entries, or None when the feed did not supply them.

    None means "unavailable" and is deliberately distinct from 0. The engine
    must not convert missing box data into "zero box pressure" and then judge
    against it as though the team genuinely had no presence in the box.
    """
    value = stats.get("box")
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _fixture_state_code(fixture):
    state = fixture.get("state")
    if isinstance(state, dict):
        return str(state.get("state") or state.get("short_name") or "").upper()
    return str(state or "").upper()


def _fixture_is_finished(fixture):
    """
    Delegates to the SHARED classifier so Stage 1, Stage 2 and the API cannot
    disagree. The old local list knew only short codes (FT/AET/AP/PEN/...) and
    missed the longer in-play strings the provider actually emits, so a match
    finished as MATCH_ENDED or after a shootout was not recognised as finished
    here. The local token check is kept as a fallback for the abbreviated
    `state.state` shape.
    """
    token = _fixture_state_code(fixture)
    if token in {"FT", "AET", "AP", "FT_PEN", "PEN", "FINISHED", "ENDED",
                 "FULL-TIME", "FULL TIME", "FULL_TIME"} or token.startswith("FT_"):
        return True
    try:
        return classify_fixture(fixture).get("is_finished", False)
    except Exception:
        return False


def _fixture_is_scheduled(fixture):
    token = _fixture_state_code(fixture)
    return token in {"NS", "TBD", "POSTPONED", "CANCELLED", "CANCELED"}


def _fixture_minute_for_board(fixture):
    """
    The elapsed MATCH minute, for board display.

    This previously took max() across every period, every event, the state
    block and the wall clock. A live fixture's periods are labelled PER HALF, so
    a 2nd-half period carries the elapsed time of that half, not of the match.
    Peñarol vs Boston River reported "1st-half: 46" and "2nd-half: 56", and
    max() reported 56 for a match that was really around minute 56 — which is
    correct by luck there, but on any match whose second half has run longer
    than its first it over-reports, and the board then fires checkpoints the
    match has not reached. It now shares the single resolution used by
    extract_live_context so the board and the engine can never disagree.
    """
    return _resolve_match_minute(fixture)


def _resolve_match_minute(fixture):
    """
    THE MATCH MINUTE — the single most important number in this module.

    Resolved in strict priority order. Periods are interpreted by WHICH HALF
    they represent rather than by taking the largest number, because a
    per-half elapsed time is not a match time.
    """
    current_minute = 0
    state_obj = fixture.get("state")
    state_token = ""
    if isinstance(state_obj, dict):
        state_token = str(state_obj.get("state") or state_obj.get("short_name") or "")

    # Period semantics, established against the live feed:
    #   `minutes` on a period is CUMULATIVE MATCH TIME, not the elapsed time of
    #   that half. A 2nd-half period reading 56 means the match is at 56', and a
    #   completed 1st half reading 46 means 46'. Verified on the live fixtures:
    #   Peñarol 1st=46 (ended), 2nd=56 (ticking) -> match minute 56.
    #   St. Vincent 1st=47 (ended), 2nd=85 (ticking) -> match minute 85.
    #   Goiás 1st=49 (ended), 2nd=55 (ticking) -> match minute 55.
    #
    # So the correct reading is simply the TICKING period's `minutes` — the one
    # currently in progress. The earlier bug took max() across every period AND
    # every event, so a late goal event (e.g. minute 70 in a match at 48')
    # could push the board past a checkpoint the match had not reached.
    periods = [p for p in (fixture.get("periods") or []) if isinstance(p, dict)]
    ordered = sorted(periods, key=lambda p: str(p.get("sort_order") or 0))
    running = None
    widest_complete = 0
    for p in ordered:
        desc = str(p.get("description") or "").lower()
        try:
            mins = int(p.get("minutes") or 0)
        except (TypeError, ValueError):
            mins = 0
        if p.get("ended") is None and p.get("ticking"):
            running = mins
        else:
            # A completed period still tells us how far the match got, but it
            # must never outrank the period actually in progress.
            widest_complete = max(widest_complete, mins)
    if running:
        current_minute = running
    elif widest_complete:
        current_minute = widest_complete
    if current_minute == 0 and fixture.get("events"):
        emins = [int(e.get("minute", 0)) for e in fixture["events"]
                 if e.get("minute")]
        if emins:
            current_minute = max(emins)
    if current_minute == 0:
        current_minute = safe_get(fixture, "time", "minute", default=0)
    if current_minute == 0 and isinstance(state_obj, dict):
        current_minute = safe_get(fixture, "state", "minute", default=0)
    if current_minute == 0 and fixture.get("starting_at_timestamp"):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        elapsed = (now_ts - int(fixture["starting_at_timestamp"])) // 60
        # Halftime sits around 50-60 minutes of wall clock; the 15-minute
        # break is not match time, so it is subtracted for the second half.
        if 0 < elapsed <= 50:      current_minute = elapsed
        elif 50 < elapsed <= 60:  current_minute = 45   # halftime
        elif 60 < elapsed <= 110: current_minute = elapsed - 15
        elif elapsed > 110:       current_minute = 90
    if current_minute == 0 and "FULL" in state_token.upper():
        current_minute = 90
    return current_minute


def _score_for_board(fixture):
    goals = {"home": 0, "away": 0}
    for entry in fixture.get("scores", []) or []:
        if not isinstance(entry, dict): continue
        desc = str(entry.get("description") or "").upper()
        if "CURRENT" not in desc and "FULL_TIME" not in desc and desc != "FT":
            continue
        score = entry.get("score") if isinstance(entry.get("score"), dict) else entry
        side = str(score.get("participant") or "").lower()
        try: value = int(float(score.get("goals", 0) or 0))
        except (TypeError, ValueError): value = 0
        if side in goals: goals[side] = max(goals[side], value)
    return f"{goals['home']}-{goals['away']}"


def _empty_statistics():
    """Same statistics shape as a live row, so the frontend renders uniformly.

    `box_entries` is None (not 0) because the provider frequently omits the box
    stat entirely; a zero there would read as "no box pressure" rather than
    "unknown".
    """
    def side():
        return {
            "possession": 0, "shots_on_target": 0, "dangerous_attacks": 0,
            "corners": 0, "box_entries": None, "box_available": False,
        }
    return {"home": side(), "away": side()}


def _statistics_from_snapshot(std):
    """
    Real final box statistics for a FINISHED fixture, from the standardized FT
    snapshot.

    This is the fix for the "No live statistics for this fixture yet — pressure
    cannot be assessed" message on completed matches. Both board entry points
    hard-coded `_empty_statistics()` and `"predictions": []` for a finished
    match, even though the snapshot carries real shots-on-target and corners, so
    the completed match displayed as if it had never been played. Settlement
    bookkeeping for finished rows stays internal to the board — only what is
    DISPLAYED changes.
    """
    def num(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def side(prefix):
        return {
            # Possession and dangerous attacks are not in the FT snapshot. They
            # stay 0 rather than being invented, and `box_available` stays
            # False because box entries genuinely are not recorded at FT.
            "possession":        0,
            "shots_on_target":   num(std.get(f"{prefix}_sot")),
            "dangerous_attacks": 0,
            "corners":           num(std.get(f"{prefix}_corners")),
            "box_entries":       None,
            "box_available":     False,
        }

    return {"home": side("h"), "away": side("a")}


def _period_label(minute):
    if minute >= 90: return "FULL TIME"
    if minute > 45:  return "SECOND HALF"
    if minute > 0:   return "FIRST HALF"
    return "PRE-MATCH"


def _score_parts(display):
    try:
        home, away = str(display).split("-", 1)
        return {"home": int(home), "away": int(away), "display": display}
    except (ValueError, AttributeError):
        return {"home": 0, "away": 0, "display": display}


def _summary_board_entry(fixture, retained_finished=False):
    """
    Create a visible board row without requiring an attached prediction.

    A FINISHED fixture that is still present in the live feed keeps its real
    statistics here too (the same fix as _finished_snapshot_board_entry), so a
    match never displays "no live statistics" merely because it is over. The
    provider does send final statistics on the finished fixture, so reading them
    is strictly better than blanking them.
    """
    finished = _fixture_is_finished(fixture)
    scheduled = _fixture_is_scheduled(fixture)
    if finished:
        lines = ["🏁 FINISHED RESULT RETAINED — final statistics and verdicts shown."]
    elif scheduled:
        lines = ["⏳ SCHEDULED — retained in the live verification universe; awaiting kickoff."]
    else:
        lines = ["👁️ LIVE — retained in the live verification universe; no actionable pick attached."]
    f_id = str(fixture.get("id", ""))
    minute = _fixture_minute_for_board(fixture)
    score = _score_for_board(fixture)

    if finished:
        stats_block = _statistics_from_fixture(fixture)
    else:
        stats_block = _empty_statistics()

    return {
        "name": fixture.get("name") or str(fixture.get("id", "Unknown")),
        "id": f_id,
        "fixture_id": f_id,
        "minute": minute,
        "score": score,
        "score_parts": _score_parts(score),
        "lines": lines,
        "status": "FINISHED" if finished else "SCHEDULED" if scheduled else "LIVE",
        "period": _period_label(minute),
        "is_finished": finished,
        "retained_finished": retained_finished,
        "updated_at": datetime.now().isoformat(),
        "statistics": stats_block,
        "predictions": [],
    }


def _statistics_from_fixture(fixture):
    """
    Real statistics read straight off a fixture the provider still lists.

    Used for FINISHED rows. The provider does return final statistics for a
    completed match; the previous code ignored them and rendered zeros, which
    is what produced the misleading "no live statistics" text.
    """
    # participant_id is a NUMERIC team id, never the literal "home"/"away", so
    # the side has to be resolved through the participants meta.location. The
    # first version of this function compared the id to "home" and therefore
    # always produced zeros — exactly the bug it was written to fix.
    side_of = {}
    for participant in fixture.get("participants", []) or []:
        if not isinstance(participant, dict):
            continue
        loc = safe_get(participant, "meta", "location", default="")
        if loc in ("home", "away"):
            side_of[str(participant.get("id"))] = loc

    def num(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    totals = {"home": {"shots-on-target": 0, "corners": 0},
              "away": {"shots-on-target": 0, "corners": 0}}
    for entry in fixture.get("statistics", []) or []:
        if not isinstance(entry, dict):
            continue
        loc = side_of.get(str(entry.get("participant_id")))
        if loc is None:
            continue
        code = str(safe_get(entry, "type", "code", default="") or "").lower()
        data = entry.get("data")
        raw = data.get("value") if isinstance(data, dict) else entry.get("value")
        if code in ("shots-on-target", "corners"):
            totals[loc][code] = num(raw)

    def side(loc):
        return {
            "possession":        0,
            "shots_on_target":   totals[loc]["shots-on-target"],
            "dangerous_attacks": 0,
            "corners":           totals[loc]["corners"],
            "box_entries":       None,
            "box_available":     False,
        }

    return {"home": side("home"), "away": side("away")}


def GET(url, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_TOKEN)
    _api_gate_pace("stage2")
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200:
                _api_gate_clear("stage2")
                return r.json()
            if r.status_code == 429:
                try:
                    gate_wait = float(r.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    gate_wait = 0.0
                gate_wait = max(gate_wait, min(5 * (2 ** attempt), 60.0))
                # CAP the shared window (see stage3): giant Retry-After values
                # (~20 min) must not freeze every sibling process.
                _api_gate_broadcast(min(gate_wait, 120.0), "stage2")
                time.sleep(min(gate_wait, 30.0))
                continue
            print(f"[WARN] HTTP {r.status_code} from {url}", file=sys.stderr)
            return {"data": []}
        except Exception as e:
            print(f"[ERR] Connection: {e}", file=sys.stderr)
            time.sleep(2)
    print(f"[ERR] Retries exhausted after repeated 429s: {url}", file=sys.stderr)
    return {"data": []}

# ==============================================================================
# SQUAD DATA
# ==============================================================================
def get_squad_data_standardized(team_id):
    tid_str = str(team_id)
    if tid_str in SQUAD_CACHE: return SQUAD_CACHE[tid_str]

    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=150)).isoformat()
    end_dt   = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    url      = f"{HISTORY_URL}/fixtures/between/{start_dt}/{end_dt}/{team_id}"
    resp     = GET(url, params={
        "include":  "lineups.details.type;lineups.player.position;scores;participants",
        "per_page": 25
    })

    squad_stats = {}
    for fx in resp.get("data", []):
        hid = str(safe_get(fx, "participants", 0, "id"))
        is_home = (str(team_id) == hid)
        h_g = safe_get(fx, "scores", 0, "score", "goals", default=0)
        a_g = safe_get(fx, "scores", 1, "score", "goals", default=0)
        opp_goals = a_g if is_home else h_g

        for l in fx.get("lineups", []):
            if str(l.get("team_id")) == str(team_id):
                pid = str(l.get("player_id"))
                if not l.get("player"): continue
                m_val = r_val = 0.0; c_val = -1.0
                for d in l.get("details", []):
                    t_name  = str(d.get('type', {}).get('name', '')).lower()
                    raw_val = d.get("data", {}).get("value") or d.get("value")
                    try: val = float(str(raw_val).replace('%', ''))
                    except: val = 0.0
                    if "minutes"  in t_name: m_val = val
                    elif "rating" in t_name: r_val = val
                    elif "conceded" in t_name: c_val = val

                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                if c_val == -1.0: c_val = float(opp_goals)
                if pid not in squad_stats:
                    squad_stats[pid] = {
                        "name": l["player"].get("display_name"),
                        "pos":  safe_get(l["player"], "position", "name"),
                        "ratings": [], "apps": 0, "mins": 0,
                        "conceded": 0, "clean_sheets": 0
                    }
                squad_stats[pid]["mins"] += m_val
                squad_stats[pid]["apps"] += 1
                if r_val > 0: squad_stats[pid]["ratings"].append(r_val)
                if m_val > 0:
                    squad_stats[pid]["conceded"] += c_val
                    if c_val == 0: squad_stats[pid]["clean_sheets"] += 1

    processed = {}
    for pid, d in squad_stats.items():
        avg_r  = sum(d["ratings"]) / len(d["ratings"]) if d["ratings"] else 6.0
        worth  = (d["apps"] * 5000) + (d["mins"] * avg_r)
        c_p90  = (d["conceded"] / d["mins"]) * 90 if d["mins"] > 0 else 0.0
        vuln   = (c_p90 * 0.6) + ((1 - (d["clean_sheets"] / d["apps"] if d["apps"] > 0 else 0)) * 2)
        processed[pid] = {"id": pid, "name": d["name"], "pos": d["pos"],
                          "worth": worth, "vuln": vuln}

    SQUAD_CACHE[tid_str] = processed
    return processed

# ==============================================================================
# ENGINE 1 — RULE VALIDATOR (threshold lowered to 50%)
# ==============================================================================
def engine_1_rule_validator(data, pick):
    h_s    = data['home']['stats']
    a_s    = data['away']['stats']
    target = "home" if pick.get('target_loc') == "home" else "away"
    exp    = h_s if target == "home" else a_s
    opp    = a_s if target == "home" else h_s
    ptype  = str(pick.get('type', '')).upper()

    def get_s(d, k): return int(d.get(k, 0))

    if "OVER" in ptype or "GG" in ptype:
        total = get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')
        result = total > ENGINE1_MIN_COMBINED_SOT
        return result, (
            f"SOT combined {total} > {ENGINE1_MIN_COMBINED_SOT}: "
            f"{'✅' if result else '❌'}"
        )

    if "UNDER" in ptype:
        total = get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')
        # WAS `total <= 1` — a hardcoded value never derived from anything.
        # Measured against 752 finished matches, a NORMAL first half carries a
        # combined 3-4 shots on target, so `<= 1` failed almost every healthy
        # half. That is how a goalless 84' match was locked as rejected.
        # The bar is now the derived 45' median (see UNDER_SOT_MAX_*).
        result = total <= UNDER_SOT_MAX_MEDIAN
        if total <= UNDER_SOT_MAX_STRONG:
            detail = "strongly on track"
        elif result:
            detail = "on track"
        else:
            detail = "above the 45' median"
        return result, f"SOT combined {total} ≤ {UNDER_SOT_MAX_MEDIAN}: {'✅' if result else '❌'} ({detail})"

    if "WIN" in ptype or "SCORE" in ptype:
        sot_ok = get_s(exp, 'shots-on-target') >= 1
        da_ok  = get_s(exp, 'dangerous-attacks') > get_s(opp, 'dangerous-attacks')
        result = sot_ok and da_ok
        return result, (
            f"SOT {get_s(exp,'shots-on-target')} ≥ 1: {'✅' if sot_ok else '❌'} | "
            f"DA {get_s(exp,'dangerous-attacks')} > {get_s(opp,'dangerous-attacks')}: {'✅' if da_ok else '❌'}"
        )

    return False, "Unknown pick type"

# ==============================================================================
# ENGINE 2 — STRUCTURAL STACKER (thresholds at 50%)
# ==============================================================================
def engine_2_structural_stacker(data, target_loc, direction=DIRECTION_NEUTRAL):
    """
    Direction-aware. The old version judged only "lots of SOT / box entries",
    which is OVER evidence and therefore opened the gate for UNDER too.

    For a match-level UNDER market the polarity of every signal is inverted
    before it is scored, so the same table can only ever be evidence in the
    direction the market actually runs.
    """
    def get_s(d, k): return int(d.get(k, 0))

    # Match-level markets (O2.5 / U2.5 / GG) have no single target side.
    # Evaluate BOTH teams using their combined two-team match data instead
    # of a home/away dominance split. Do NOT map None → "home".
    if target_loc is None or target_loc == "match":
        h = data['home']['stats']
        a = data['away']['stats']
        tot_sot = get_s(h, 'shots-on-target') + get_s(a, 'shots-on-target')
        box_vals = [_opt_box(h), _opt_box(a)]
        if all(v is not None for v in box_vals):
            tot_box = int(box_vals[0]) + int(box_vals[1])
            if direction == DIRECTION_UNDER:
                # UNDER: high SOT / high box entries are evidence AGAINST it.
                # Each signal is judged against ITS OWN derived distribution.
                # The old code compared BOTH against ENGINE1_MIN_COMBINED_SOT,
                # a shots-on-target constant — a unit error for box entries.
                sot_ok  = tot_sot <= UNDER_SOT_MAX_MEDIAN
                box_ok  = tot_box <= UNDER_BOX_MAX_SUPPORT
                return (sot_ok or box_ok), (
                    f"[UNDER] Combined SOT {tot_sot} ≤ {UNDER_SOT_MAX_MEDIAN}: "
                    f"{'✅' if sot_ok else '❌'} | "
                    f"Combined box entries {tot_box} ≤ {UNDER_BOX_MAX_SUPPORT}: "
                    f"{'✅' if box_ok else '❌'}"
                )
            sot_ok  = tot_sot > ENGINE1_MIN_COMBINED_SOT
            box_ok  = tot_box > ENGINE1_MIN_COMBINED_SOT
            return (sot_ok or box_ok), (
                f"Combined SOT {tot_sot} > {ENGINE1_MIN_COMBINED_SOT}: {'✅' if sot_ok else '❌'} | "
                f"Combined box entries {tot_box} > {ENGINE1_MIN_COMBINED_SOT}: {'✅' if box_ok else '❌'}"
            )
        # Box entries genuinely unavailable — judge on SOT alone and say so
        # rather than silently treating missing data as zero pressure.
        if direction == DIRECTION_UNDER:
            sot_ok = tot_sot <= UNDER_SOT_MAX_MEDIAN
            return sot_ok, (
                f"[UNDER] Combined SOT {tot_sot} ≤ {UNDER_SOT_MAX_MEDIAN}: "
                f"{'✅' if sot_ok else '❌'} | box entries unavailable"
            )
        sot_ok = tot_sot > ENGINE1_MIN_COMBINED_SOT
        return sot_ok, (
            f"Combined SOT {tot_sot} > {ENGINE1_MIN_COMBINED_SOT}: "
            f"{'✅' if sot_ok else '❌'} | box entries unavailable"
        )

    if target_loc == "match": target_loc = "home"
    opp_loc = "away" if target_loc == "home" else "home"
    exp = data[target_loc]['stats']
    opp = data[opp_loc]['stats']

    signals     = []
    signal_pass = []

    total_da = get_s(exp, 'dangerous-attacks') + get_s(opp, 'dangerous-attacks')
    da_ratio = (get_s(exp, 'dangerous-attacks') / total_da) if total_da > 0 else 0
    da_ok    = da_ratio >= MIN_DA_RATIO
    signals.append(f"DA ratio {da_ratio:.0%} ≥ {MIN_DA_RATIO:.0%}: {'✅' if da_ok else '❌'}")
    if da_ok: signal_pass.append(True)

    total_sot = get_s(exp, 'shots-on-target') + get_s(opp, 'shots-on-target')
    sot_ratio = (get_s(exp, 'shots-on-target') / total_sot) if total_sot > 0 else 0
    sot_ok    = sot_ratio >= MIN_SOT_RATIO
    signals.append(f"SOT ratio {sot_ratio:.0%} ≥ {MIN_SOT_RATIO:.0%}: {'✅' if sot_ok else '❌'}")
    if sot_ok: signal_pass.append(True)

    box_exp = _opt_box(exp)
    box_opp = _opt_box(opp)
    if box_exp is not None and box_opp is not None:
        box_diff = box_exp - box_opp
        box_ok   = box_diff >= MIN_BOX_TOUCH_DIFF
        signals.append(
            f"Box entry diff {box_diff} ≥ {MIN_BOX_TOUCH_DIFF}: {'✅' if box_ok else '❌'}"
        )
        if box_ok: signal_pass.append(True)
    else:
        signals.append("Box entries unavailable — signal not scored")

    corn_diff = get_s(exp, 'corners') - get_s(opp, 'corners')
    corn_ok   = corn_diff >= MIN_CORNER_DIFF
    signals.append(f"Corner diff {corn_diff} ≥ {MIN_CORNER_DIFF}: {'✅' if corn_ok else '❌'}")
    if corn_ok: signal_pass.append(True)

    passed = len(signal_pass) >= 2
    return passed, " | ".join(signals)

# ==============================================================================
# ENGINE 3 — MOMENTUM ESCALATOR
# ==============================================================================
def engine_3_momentum_escalator(data, target_id, direction=DIRECTION_NEUTRAL):
    """
    Direction-aware. For an UNDER market, a burst of recent key events (corners,
    shots on target, goals) is evidence AGAINST the under, not for it. The old
    version counted "lots of attacking activity" as support regardless of which
    side of 2.5 the market sat on.

    MATCH-LEVEL FIX. The old guard was:
        if not target_id or now < 15:
            return False, f"Minute {now} < 15 — too early"
    `target_id` is None for every match-level market (UNDER 2.5 / OVER 2.5),
    so the engine returned False unconditionally and could NEVER pass. The
    message it printed was also a lie: it claimed a minute problem while the
    match could be at 72'. That is why the board was permanently stuck at
    1-2 of 3 engines. For a match-level market the correct scope is BOTH
    teams' key events, which is what is counted when target_id is absent.
    """
    now = data['minute']
    if now < 15:
        # Too early to have momentum at all. This is genuine "not yet", not a
        # judgement about the match, so the engine abstains rather than
        # recording a FAIL that would drag the tally down.
        return None, f"Minute {now} < 15 — too early to read momentum"

    # No target_id means a match-level market: both teams' momentum counts,
    # because the market is about the match total, not one side.
    scope = None if not target_id else str(target_id)
    if scope is None:
        label = "[match-level] "
    else:
        label = ""

    recent = 0
    saw_events = False
    for e in data.get('events', []):
        if scope is not None and str(e.get("participant_id")) != scope:
            continue
        saw_events = True
        if (e.get("minute") or 0) > (now - 12):
            if safe_get(e, "type", "code") in ["corner", "shot-on-target", "goal"]:
                recent += 1

    # HONESTY FIX. Several fixtures arrive with NO event feed at all (2 of the
    # 10 currently live carried zero events). Counting zero events on an empty
    # feed scored a free PASS, which inflated the engine tally and could carry
    # a verdict on no evidence whatsoever. An absent feed is not a quiet match;
    # it is missing data, so the engine abstains and says so. The other two
    # engines still judge, and a genuinely quiet match — a real feed with no
    # recent key events — still passes exactly as before.
    if not saw_events:
        return None, (
            f"{label}no event feed available — Engine 3 abstained "
            f"(missing data, not a quiet match)"
        )

    if direction == DIRECTION_UNDER:
        # Escalating attacking pressure is evidence the under is in trouble.
        passed = recent < MIN_RECENT_KEY_EVENTS
        return passed, (
            f"{label}[UNDER] Recent key events in last 12 min: {recent} < "
            f"{MIN_RECENT_KEY_EVENTS}: {'✅' if passed else '❌'}"
        )

    passed = recent >= MIN_RECENT_KEY_EVENTS
    return passed, (
        f"{label}Recent key events in last 12 min: {recent} ≥ "
        f"{MIN_RECENT_KEY_EVENTS}: {'✅' if passed else '❌'}"
    )

# ==============================================================================
# FORENSIC INVESTIGATION ENGINE
# ==============================================================================
def new_engine_forensic_investigation(ctx, pick):
    """
    Returns (state, note) where state is one of the four V_* values.

    The previous version returned True for "nothing bad happened"
    (MAINTAINED / STABLE), which made a quiet match look like positive
    predictive evidence. Those cases are now NEUTRAL: explicitly not support.
    """
    target_side   = "home" if pick.get('target_loc') == "home" else "away"
    opponent_side = "away" if target_side == "home" else "home"

    has_red      = ctx["impact"][target_side]["reds"] > 0
    gk_liability = ctx["impact"][target_side]["gk_risk"]
    personnel_gap = ctx["impact"][target_side]["key_sub_off"] >= 1
    opp_stats    = ctx[opponent_side]['stats']

    opp_sot = int(opp_stats.get('shots-on-target', 0))
    opp_da  = int(opp_stats.get('dangerous-attacks', 0))
    # Box may be None (provider omits the source codes) — only count it when the
    # feed actually gave us a number, otherwise the SOT/DA branches still judge.
    opp_box = _opt_box(opp_stats)

    if has_red or gk_liability:
        # A real exploitable gap. `opp_box` is None when the feed omits the box
        # source codes, so it must not be compared numerically in that case —
        # the SOT/DA branches still carry the verdict on their own.
        box_signal = opp_box is not None and opp_box >= 3
        if opp_sot >= 1 or opp_da >= 10 or box_signal:
            return V_SUPPORTED, "EXPLOITED (Opponent utilizing structural gap)"
        return V_CONTRADICTED, "PROTECTED (Team covering the structural gap)"
    elif personnel_gap:
        if opp_da >= 8 or opp_sot >= 1:   # was da≥15, sot≥1
            return V_SUPPORTED, "WEAKENED (Substitution impact detected)"
        # A managed personnel change is not evidence that a team will score.
        return V_NEUTRAL, "STABLE (Personnel change managed — not evidence)"
    return V_NEUTRAL, "MAINTAINED (No structural fracture — not evidence)"

# ==============================================================================
# COMBINED STATISTICAL JUDGE
# ==============================================================================
def old_engine_statistical_judge(ctx, pick):
    """
    Returns (state, label, detail).

    THRESHOLD POLICY CHANGE: the old rule was `passed_count >= 1`, so a single
    weak engine out of three produced an overall pass (surfaced as STATS_1/3).
    A standard pass now requires STATS_MIN_ENGINES_FOR_PASS genuine engines;
    exactly one engine is reported as INSUFFICIENT_DATA rather than a pass.
    """
    e1_pass, e1_note = engine_1_rule_validator(ctx, pick)
    direction = market_direction(pick.get("market") or pick.get("type"))
    e2_pass, e2_note = engine_2_structural_stacker(
        ctx, pick.get('target_loc'), direction)
    e3_pass, e3_note = engine_3_momentum_escalator(
        ctx, pick.get('target_id'), direction)

    # Engine 3 may ABSTAIN (return None) when the fixture carries no event
    # feed at all. An abstention is missing data, not a fail and not a pass, so
    # it must not be counted as either. The bar is expressed against the
    # engines that actually reported: 2 of 2 reporting engines is still a
    # genuine majority, and 1 of 2 is genuinely inconclusive.
    e3_abstained = e3_pass is None
    votes = [bool(e1_pass), bool(e2_pass)]
    if not e3_abstained:
        votes.append(bool(e3_pass))
    passed_count = sum(votes)
    reported = len(votes)

    # Required passes scale with how many engines actually reported, but never
    # fall below 2 — a single engine must never carry a verdict.
    required = min(STATS_MIN_ENGINES_FOR_PASS, reported)
    if reported < 2:
        state = V_INSUFFICIENT
    elif passed_count >= required:
        state = V_SUPPORTED
    elif passed_count == STATS_PARTIAL_ENGINES:
        state = V_INSUFFICIENT
    else:
        state = V_CONTRADICTED

    def _mark(passed, note):
        if passed is None:
            return f"⏸️ N/A  → {note}"
        return f"{'✅ PASS' if passed else '❌ FAIL'} → {note}"

    # The label is `STATS_<passed>/<reported>` — two numbers only. The fixed
    # judge count used to be emitted as a THIRD number ("STATS_1/3/3"), which
    # read as three separate quantities on the board and could not be parsed
    # by anyone who had not seen the source. The total judge count is already
    # implied by the denominator; it is stated in prose below instead.
    suffix = " (Engine 3 abstained)" if e3_abstained else ""
    detail = (
        f"\n         Engine 1 (Rule)       : {_mark(e1_pass, e1_note)}"
        f"\n         Engine 2 (Structure)  : {_mark(e2_pass, e2_note)}"
        f"\n         Engine 3 (Momentum)   : {_mark(e3_pass, e3_note)}"
        f"\n         Combined              : {passed_count} of {reported} judges "
        f"passed (need {required} for a standard pass)"
    )
    return state, f"STATS_{passed_count}/{reported}{suffix}", detail


def prediction_lifecycle_step(pick, status, combined_state, minute, settled):
    """
    Describe WHERE this prediction currently sits in its live lifecycle.

    Code 2 validates predictions one at a time, so each card must state plainly
    what stage it has reached and why, instead of leaving the reader to infer
    it from a verdict chip. Returns (stage_label, explanation).
    """
    if settled:
        return "SETTLED", "Outcome decided"
    if status == "TRIGGERED":
        return "TRIGGERED", f"Alert fired at {minute}'"
    if combined_state == V_SUPPORTED:
        return "SUPPORTED", "Both validators agree — awaiting confirmation"
    if combined_state == V_CONTRADICTED:
        return "UNLIKELY", "Live evidence weighs against this prediction"
    if combined_state == V_INSUFFICIENT:
        return "MONITORING", "Partial evidence — still accumulating"
    return "MONITORING", "No exploitable condition yet"


def combine_validation_states(forensic_state, stats_state, direction=DIRECTION_NEUTRAL):
    """
    Combine the forensic and statistical verdicts into one gate state.

    An alert is only SUPPORTED when BOTH dimensions agree. Anything short of
    that is reported honestly as monitoring rather than as a pass.

    MATCH-LEVEL FIX — WHY CODE 2 COULD NEVER APPROVE ANYTHING.
    The forensic engine asks "is a team structurally weakened?" — a red card,
    a shaky keeper, a key substitution. On a healthy match it returns NEUTRAL
    ("no fracture — not evidence"), and NEUTRAL can never satisfy
    `forensic == SUPPORTED`. So for a match-level market such as UNDER 2.5 the
    gate demanded a red card before it could ever open, even though the market
    is about the MATCH TOTAL and has no target team at all.

    The recorded production board proved it: forensic returned SUPPORTED once
    in 47 predictions and the combined gate was never SUPPORTED even once.
    Code 2 had literally never approved a prediction.

    Fix: for a directional match-level market (UNDER / OVER) the forensic
    dimension is not applicable, so the statistical engines decide alone. The
    forensic requirement is RETAINED for team-side markets (TO_SCORE, WIN,
    GG) where a weakened side is genuinely the mechanism being traded.
    """
    # A directional match-level market has no target side, so "is a team
    # weakened" is not a question about this market. Judge on the engines.
    if direction in (DIRECTION_UNDER, DIRECTION_OVER):
        return stats_state
    if forensic_state == V_SUPPORTED and stats_state == V_SUPPORTED:
        return V_SUPPORTED
    if forensic_state == V_CONTRADICTED or stats_state == V_CONTRADICTED:
        return V_CONTRADICTED
    if forensic_state == V_INSUFFICIENT or stats_state == V_INSUFFICIENT:
        return V_INSUFFICIENT
    return V_NEUTRAL


# State → short board glyph. Kept here so the console board, the persisted
# board and the frontend all describe the same verdict the same way.
STATE_GLYPH = {
    V_SUPPORTED:    "✅",
    V_CONTRADICTED: "❌",
    V_NEUTRAL:      "➖",
    V_INSUFFICIENT: "⏳",
    V_SETTLED:      "🏁",
}

# ==============================================================================
# MARKET DIRECTION
# ==============================================================================
# The constants live beside the other module configuration (see the top of this
# file) because they are default argument values in the engine signatures.

def market_direction(market):
    """Which way does this market run? NEVER None — unknown is NEUTRAL."""
    token = str(market or "").strip().upper()
    if "UNDER" in token or token in {"U2.5", "U25"}:
        return DIRECTION_UNDER
    if "OVER" in token or token in {"O2.5", "O25"}:
        return DIRECTION_OVER
    # GG / GG_OVER_2.5 / TO_SCORE carry no single goal-volume direction.
    return DIRECTION_NEUTRAL


# ==============================================================================
# PER-PREDICTION VERDICT LEDGER
# ==============================================================================
# The old board had only "status" strings (QUEUED / MONITORING / TRIGGERED /
# STRIKE_WINDOW) and no notion of a final, honest answer. These are the
# verdicts. UNCERTAIN is deliberately NOT a rejection: it means the evidence
# available at the decision minute supported neither answer, and the board
# says so rather than guessing.
VERDICT_PRE_APPROVED  = "PRE_APPROVED"      # 30' pre-verdict, still reversible
VERDICT_PRE_REJECTED   = "PRE_REJECTED"      # 30' pre-verdict said no
VERDICT_APPROVED_WATCH = "APPROVED_WATCH"   # approved, may still be overruled
VERDICT_TRIGGERED      = "TRIGGERED"        # the alert actually fired
VERDICT_FINAL_APPROVED = "FINAL_APPROVED"   # locked final YES
VERDICT_FINAL_REJECTED = "FINAL_REJECTED"   # locked final NO
VERDICT_UNCERTAIN      = "UNCERTAIN"        # neither: not enough evidence
VERDICT_WON            = "WON"
VERDICT_LOST           = "LOST"

# ── HONEST 45' VOCABULARY (replaces REJECTED) ────────────────────────────────
# The user's objection was specifically the WORD "rejected". Football is
# probabilistic: a 45' reading is a probability, not a refutation, and calling
# it "REJECTED" asserted a certainty the engine does not have. Worse, the old
# chain reached FINAL_REJECTED from a *weak engine reading* — "the engines
# cannot confirm it" is not "the market is wrong".
#
# The new words separate JUDGEMENT from ARITHMETIC:
#   LIKELY    — the evidence supports the pick; it is on track
#   UNLIKELY  — the evidence works against it, but it can STILL come in
#   VOID      — dead. Arithmetic, not opinion: 3 goals already scored
#   UNCLEAR   — genuinely insufficient evidence; no verdict claimed
VERDICT_LIKELY        = "LIKELY"
VERDICT_UNLIKELY      = "UNLIKELY"
VERDICT_VOID          = "VOID"

# THE 30' OBSERVATION. Code 2's first checkpoint is an observation, not a
# judgement: the judges have looked, and this is what they saw. It is recorded
# separately from the verdict vocabulary precisely so it can never be read as
# an approval — the old PRE_APPROVED / PRE_REJECTED words did exactly that,
# and "UNDER_2.5 APPROVED" appeared on a match at 16'.
OBSERVATION_SUPPORTING = "SUPPORTING"
OBSERVATION_AGAINST    = "AGAINST"

# THE 30' OBSERVATION. Code 2's first checkpoint is an observation, not a
# judgement: the judges have looked, and this is what they saw. It is recorded
# separately from the verdict vocabulary precisely so it can never be read as
# an approval — the old PRE_APPROVED / PRE_REJECTED words did exactly that,
# and "UNDER_2.5 APPROVED" appeared on a match at 16'.
OBSERVATION_SUPPORTING = "SUPPORTING"
OBSERVATION_AGAINST    = "AGAINST"

# FINAL_APPROVED and FINAL_REJECTED are retained as readable aliases so the
# existing ledger vocabulary stays meaningful to the audit trail, but the
# LOCKED 45' path emits LIKELY / UNLIKELY / VOID / UNCLEAR from now on.
VERDICT_45_LIKELY   = VERDICT_FINAL_APPROVED   # same decision, honest word
VERDICT_45_UNLIKELY = VERDICT_UNLIKELY
VERDICT_45_VOID     = VERDICT_VOID

TERMINAL_VERDICTS = frozenset({
    VERDICT_FINAL_APPROVED, VERDICT_FINAL_REJECTED, VERDICT_UNCERTAIN,
    VERDICT_LIKELY, VERDICT_UNLIKELY, VERDICT_VOID,
})

# The gate minutes. 30' is a PRE-verdict only; 45' is the main verdict.
CHECKPOINT_PRE_MINUTE = 30
CHECKPOINT_MAIN_MINUTE = 45
# UNDER 2.5 is locked at 45' and may NOT be extended past it — this is the
# user's explicit rule: the 45th minute verdict is the main one, and UNDER must
# get its final verdict at 45' whatever data is available then.
LOCKED_AT_45_MARKETS = frozenset({"UNDER_2.5"})

# ── PHASE 2: CODE 2 VALIDATES EVERY LIVE MATCH ──────────────────────────────
# The user's instruction:
#   "i think its should give its validation to all live match the diffrence
#    will just be one is the one code 1 give prediction and all orther matches
#    that fail code 1 threshold should also be validated they will just be
#    without prematch prediction from code 1 there validation will be purely
#    from their live statistic"
#
# Code 2 previously only ran when Code 1 had sent at least one pick:
#     if picks and not _fixture_is_scheduled(fx):
# A match that failed Code 1's threshold was therefore never validated at all
# and showed an empty board — which is why "a lot of team[s] do the same".
#
# A LIVE-ONLY READ is what Code 2 produces for those matches. It is:
#   * the SAME three engines, evaluated against the same live statistics —
#     no new mathematics, no new SportMonks calls, no new prediction engine
#   * an OBSERVATION, never a bet. It never becomes a prematch prediction
#   * labelled READ, never LIKELY, so it can never be mistaken for a verdict
#     on a Code 1 pick
LIVE_ONLY_MARKET = "LIVE_READ"
# Only from this minute does a live-only read carry any weight; before it
# there is not enough of the match to read.
LIVE_ONLY_MIN_MINUTE = 30
# The only market a live-only read ever considers. Under 2.5 is the market
# Code 1's rotation rule produces, so a live-only read is the same question
# asked without the prematch condition. No other market is inferred.
LIVE_ONLY_MARKETS = ("UNDER_2.5",)
# The read's own vocabulary. Deliberately NOT LIKELY/UNLIKELY: those words
# belong to a validated Code 1 pick. A read states what the live picture is.
READ_ON_TRACK = "ON_TRACK"
READ_AT_RISK  = "AT_RISK"
READ_DEAD     = "DEAD"
READ_UNCLEAR  = "UNCLEAR"


def combined_read_state(read_state):
    """
    Map a live-read outcome onto the board's existing state vocabulary so the
    UI colours it consistently. A live read is NOT a validation, so it never
    produces a verdict word — only the gate colour.
    """
    if read_state == READ_ON_TRACK:
        return V_SUPPORTED
    if read_state == READ_AT_RISK:
        return V_CONTRADICTED
    if read_state == READ_DEAD:
        return V_SETTLED
    return V_INSUFFICIENT
# TO_SCORE can be called any time from 30' to 90' because a team that can still
# score can still be called. The old 60-70 cap made a 78' or 82' TO_SCORE
# structurally incapable of triggering.
TO_SCORE_OPEN_MINUTE  = 30
TO_SCORE_CLOSE_MINUTE = 90
FINAL_STRIKE_OPEN  = 60
FINAL_STRIKE_CLOSE = 70

# ── PHASE 1: THE 60' FINAL VALIDATION ───────────────────────────────────────
# The user's rule, in their words:
#   "at 45 its should give final judgement to under if code 1 make the
#    prediction, then at 60th its shold also give its final validation for
#    all prediction from code 1, then after 60th its can only trigger if
#    its see any opportunity"
#
# So there are three distinct phases and each ends at a fixed point:
#   up to 45'  — the 45' verdict (Under is locked here; others provisional)
#   45'-60'    — monitoring, alerts may still fire
#   AT 60'     — final validation for EVERY Code 1 market, once, then locked
#   after 60'  — TRIGGER-ONLY. No further verdicts are ever written, because
#                past 60' a verdict is no longer a judgement about the match,
#                it is a prediction about the remaining minutes. Only genuine
#                opportunities may still fire.
CHECKPOINT_FINAL_MINUTE = 60
# Every Code 1 market receives a final validation at 60'. Under 2.5 already
# locks at 45' and is NOT re-decided at 60' — a 45' lock that could be
# overwritten at 60' would not be a lock.
LOCKED_AT_60_MARKETS = frozenset({"UNDER_2.5", "OVER_2.5", "GG",
                                  "GG_OVER_2.5", "TO_SCORE"})
# After this minute a market may only TRIGGER, never be re-verdicted.
TRIGGER_ONLY_AFTER_MINUTE = 60


def verdict_from_gate(gate_state):
    """
    Map a gate state onto the ledger vocabulary for a NON-locked market.

    The old mapping returned APPROVED_WATCH / PRE_REJECTED, which is where the
    board's "APPROVED" chip came from for every non-Under market: OVER 2.5,
    GG and TO_SCORE all flowed through here at 45'. Those are the old
    pre-verdict words, and "approved" is not a word this engine is entitled to
    use — a 45' reading is a probability.

    The honest vocabulary is the same one the 45' UNDER lock and the 60' final
    validation already use: LIKELY / UNLIKELY / UNCLEAR.
    """
    if gate_state == V_SUPPORTED:
        return VERDICT_LIKELY
    if gate_state == V_CONTRADICTED:
        return VERDICT_UNLIKELY
    return VERDICT_UNCERTAIN


def _verdict_family(verdict):
    """
    Collapse a verdict to the decision it actually represents.

    PRE_APPROVED at 30' and FINAL_APPROVED at 45' are the SAME decision taken
    at two different checkpoints, not two conflicting opinions. Comparing them
    literally made every ordinary approval look like an overrule, which would
    have made the `overruled` flag meaningless. The same applies to
    PRE_REJECTED / FINAL_REJECTED and to UNCERTAIN at either checkpoint.
    """
    if verdict in (VERDICT_PRE_APPROVED, VERDICT_APPROVED_WATCH,
                   VERDICT_FINAL_APPROVED, VERDICT_TRIGGERED,
                   VERDICT_LIKELY, OBSERVATION_SUPPORTING):
        return "APPROVE"
    if verdict in (VERDICT_PRE_REJECTED, VERDICT_FINAL_REJECTED,
                   VERDICT_UNLIKELY, VERDICT_VOID, OBSERVATION_AGAINST):
        return "REJECT"
    if verdict in (VERDICT_UNCERTAIN, VERDICT_LOST, VERDICT_WON):
        return "UNCERTAIN"
    return None


def reconcile_pre_and_main(pre_verdict, main_verdict):
    """
    Tally the 30' pre-verdict against the 45' main verdict.

    45' is the main verdict and always wins, but the comparison is recorded
    rather than discarded: a pick that was APPROVED at 30' and REJECTED at 45'
    is flagged `overruled` with both values kept, which is the audit trail the
    user asked for. The comparison is made on decision families, so the same
    decision reached at both checkpoints is not reported as a conflict.
    Returns (authoritative_verdict, overruled_bool, note).
    """
    if pre_verdict is None:
        return main_verdict, False, "No 30' pre-verdict was recorded"
    pre_family = _verdict_family(pre_verdict)
    main_family = _verdict_family(main_verdict)
    if pre_family is not None and pre_family == main_family:
        return main_verdict, False, f"30' and 45' agree ({main_family})"
    return main_verdict, True, (
        f"45' verdict ({main_verdict}) overrules the 30' pre-verdict "
        f"({pre_verdict})"
    )


# ==============================================================================
# THE 30' -> 45' COMPARISON
# ==============================================================================
# The user described Code 2's original function as having "a function that
# compare what happen at 30th minute to the 45th". reconcile_pre_and_main
# only compared the two verdict WORDS. What is actually wanted is a
# measurement of how the match MOVED between the two checkpoints: did the
# evidence for the pick strengthen, hold, or collapse?
#
# This compares the live statistics captured at 30' against those at 45'. It
# introduces no new mathematics — it reports the DELTA between two readings
# that the same three engines already produced.
COMPARE_STRENGTHENED = "STRENGTHENED"
COMPARE_HELD         = "HELD"
COMPARE_WEAKENED     = "WEAKENED"
COMPARE_COLLAPSED    = "COLLAPSED"
COMPARE_NO_BASELINE  = "NO_BASELINE"


def _live_snapshot(ctx, stats_label=None, verdict=None):
    """
    Capture the live picture at a checkpoint so two readings can be compared.

    Records only facts already on the board — goals, combined shots on target
    and how many of the three engines passed. No new statistics are invented.
    `engines_passed` is parsed from the engine label ("STATS_2/3") so the
    snapshot cannot disagree with what the board already displays.
    """
    goals = 0
    sot = 0
    for side in ("home", "away"):
        try:
            goals += int(ctx[side]["goals"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            sot += int(ctx[side]["stats"].get("shots-on-target", 0) or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    passed = 0
    text = str(stats_label or "")
    if "STATS_" in text:
        try:
            passed = int(text.split("STATS_")[1].split("/")[0])
        except (IndexError, ValueError):
            passed = 0
    return {"goals": goals, "sot": sot, "engines_passed": passed,
            "verdict": verdict, "label": stats_label}


def compare_observation_to_verdict(snap30, snap45):
    """
    Compare the 30' observation against the 45' verdict.

    `snap30` and `snap45` are the same shape:
        {"goals": int, "sot": int, "engines_passed": int, "verdict": str}

    Returns (comparison, note) where comparison is one of STRENGTHENED / HELD /
    WEAKENED / COLLAPSED / NO_BASELINE. This is a description of how the match
    developed, never a new verdict — the 45' verdict remains authoritative.
    """
    if not snap30 or not snap45:
        return COMPARE_NO_BASELINE, (
            "No 30' observation was recorded, so nothing to compare against")
    try:
        g30, g45 = int(snap30.get("goals", 0)), int(snap45.get("goals", 0))
        s30, s45 = int(snap30.get("sot", 0)), int(snap45.get("sot", 0))
        e30 = int(snap30.get("engines_passed", 0))
        e45 = int(snap45.get("engines_passed", 0))
    except (TypeError, ValueError):
        return COMPARE_NO_BASELINE, "Insufficient recorded data to compare"

    new_goals = g45 - g30
    new_sot = s45 - s30
    engine_move = e45 - e30

    # Arithmetic collapse: the market died between the two checkpoints.
    token = str(snap45.get("verdict") or "").upper()
    if token == VERDICT_VOID or new_goals >= 2:
        return COMPARE_COLLAPSED, (
            f"30'→45': {new_goals} goal(s) and {new_sot} more shot(s) on "
            f"target — the market collapsed after the 30' read"
        )
    # The engines moved, which is the primary signal.
    if engine_move > 0:
        return COMPARE_STRENGTHENED, (
            f"30'→45': engines {e30}/3 → {e45}/3 — the evidence strengthened "
            f"({new_goals} goal(s), {new_sot} more shot(s) on target)"
        )
    if engine_move < 0:
        return COMPARE_WEAKENED, (
            f"30'→45': engines {e30}/3 → {e45}/3 — the evidence weakened "
            f"({new_goals} goal(s), {new_sot} more shot(s) on target)"
        )
    # Engines unchanged: the match itself still moved, so say so honestly.
    if new_goals or new_sot:
        return COMPARE_HELD, (
            f"30'→45': engines held at {e45}/3 while the match moved on "
            f"({new_goals} goal(s), {new_sot} more shot(s) on target)"
        )
    return COMPARE_HELD, (
        f"30'→45': engines held at {e45}/3 and nothing changed on the pitch")


def locked_verdict_at_45(gate_state, data, stats_state=None):
    """
    THE UNDER 2.5 RULE — a decision is produced at 45' every single time.

    THE USER'S RULE: the ENGINE decides. The scoreline only breaks ties.

    Order of authority, highest first:
      1. ARITHMETIC — 3+ goals already scored means VOID. A fact about the
         scoreline, not a judgement, so no engine is consulted.
      2. THE ENGINES — 2 of 3 agreeing is LIKELY; 0 of 3 (the engines
         actively reading pressure against the under) is UNLIKELY. This is
         the engine's own intelligence and it is what decides.
      3. TIEBREAK — at 1 of 3 the engines are split and cannot decide, so
         only then does the scoreline speak: 0-1 goals LIKELY, 2 UNCLEAR.

    The scoreline must NOT override a clear engine read. A first pass got
    this wrong and returned LIKELY for 0 goals before consulting the
    engines, so a goalless half under 20 shots on target still printed
    LIKELY. That is exactly the "Code 2 ignores its own intelligence"
    behaviour under investigation, so it is now impossible: an engine
    verdict is checked before any goal count.

    WHY "REJECTED" IS GONE. The old chain returned FINAL_REJECTED whenever
    the engines did not confirm the pick. That is a category error twice over:
    "the engines cannot confirm it" is not "the market is wrong", and a weak
    reading treated as refutation is how an ordinary 0-0 half got locked as
    rejected and stayed wrong for the rest of the match. A 45' reading is a
    probability; the honest words are LIKELY, UNLIKELY, VOID and UNCLEAR.

    `stats_state` is the statistical judge's own state, passed in so the
    "2 of 3 engines" condition can be honoured directly. It is optional so
    existing callers and tests that pass only the gate state keep working.
    """
    total_goals = 0
    sot = 0
    for side in ("home", "away"):
        try:
            total_goals += int(data[side]["goals"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            sot += int(data[side]["stats"].get("shots-on-target", 0) or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

    # ══════════════════════════════════════════════════════════════════════
    # THE ENGINE DECIDES. THE SCORELINE ONLY BREAKS TIES.
    # ══════════════════════════════════════════════════════════════════════
    # The user's instruction: "I hope the team score at 45 wasn't the thing
    # that determine[s] likely/unlikely/void, but the ENGINE itself tells me
    # how it all works."
    #
    # A first pass got this wrong: it returned LIKELY for 0 goals BEFORE
    # looking at the engines, so a goalless half under relentless pressure
    # (engines 0 of 3, CONTRADICTED) still printed LIKELY. That is precisely
    # the "Code 2 ignores its own intelligence" behaviour being complained
    # about, and it is a bug, not a design choice.
    #
    # The order below is therefore: ARITHMETIC, then the three engines, then
    # the scoreline ONLY as a tiebreak between the engines.

    # ── 1. ARITHMETIC — the one thing that outranks the engines ───────────
    # 3+ goals means the market is mathematically dead. This is a fact about
    # the scoreline, not a judgement, so it needs no engine agreement.
    if total_goals >= 3:
        return VERDICT_VOID, (
            f"VOID at 45': UNDER 2.5 already lost ({total_goals} goals scored) "
            f"— arithmetic, not a prediction"
        )

    # ── 2. THE ENGINES ARE THE VERDICT ────────────────────────────────────
    # 2 of 3 engines agreeing is a real, independent read of the match: shots
    # on target, box entries, and recent momentum. It decides the verdict.
    if stats_state == V_SUPPORTED or gate_state == V_SUPPORTED:
        return VERDICT_LIKELY, (
            f"LIKELY at 45': the engines agree, 2 of 3 — "
            f"{total_goals} goal(s) scored, combined SOT {sot}"
        )

    # 0 of 3 engines agreeing is the engine actively reading pressure AGAINST
    # the under. This is evidence, so it is UNLIKELY — never "rejected", and
    # never overridden by a low goal count. A goalless half under 20 shots is
    # a match running away from the under, and the board must say so.
    if stats_state == V_CONTRADICTED or gate_state == V_CONTRADICTED:
        return VERDICT_UNLIKELY, (
            f"UNLIKELY at 45': the engines read pressure against the under, "
            f"0 of 3 — {total_goals} goal(s) scored, combined SOT {sot}. "
            f"It can still come in"
        )

    # ── 3. TIEBREAK — 1 of 3 engines: the engines are split ───────────────
    # Only here, with the engines unable to decide, does the scoreline speak.
    if total_goals == 0:
        if sot <= UNDER_SOT_MAX_STRONG:
            return VERDICT_LIKELY, (
                f"LIKELY at 45': engines split 1 of 3, but 0 goals and combined "
                f"SOT {sot} (≤ {UNDER_SOT_MAX_STRONG}) — strongly on track"
            )
        return VERDICT_LIKELY, (
            f"LIKELY at 45': engines split 1 of 3, but 0 goals with combined "
            f"SOT {sot} — up to 2 more still allowed"
        )
    if total_goals == 1:
        return VERDICT_LIKELY, (
            f"LIKELY at 45': engines split 1 of 3, but 1 goal with combined "
            f"SOT {sot} — up to 1 more still allowed"
        )
    if total_goals == 2:
        return VERDICT_UNCERTAIN, (
            f"UNCLEAR at 45': engines split 1 of 3 and 2 goals already — the "
            f"under survives only if no further goal is scored (SOT {sot})"
        )

    if sot == 0:
        return VERDICT_UNCERTAIN, (
            "UNCLEAR at 45': no shots on target recorded and no box data — "
            "the available evidence supports neither direction"
        )
    return VERDICT_UNCERTAIN, (
        f"UNCLEAR at 45': evidence incomplete (combined SOT {sot}, "
        f"{total_goals} goals) — no verdict in either direction"
    )


# ==============================================================================
# PHASE 1 — THE 60' FINAL VALIDATION (every Code 1 market)
# ==============================================================================
def final_verdict_at_60(gate_state, data, ptype, stats_state=None, target=None):
    """
    THE 60' RULE — every Code 1 prediction gets a FINAL validation at 60'.

    Until now only UNDER 2.5 was locked, and only at 45'. Every other Code 1
    pick (TO_SCORE, GG, OVER 2.5) could sit unresolved all match and simply
    settle at full time with no validation ever recorded — which is exactly
    the "it acts as if it was meant to give predictions instead of validation"
    complaint. A validation board that never validates is not a validator.

    UNDER 2.5 is deliberately NOT re-decided here. It locked at 45'; a lock
    that can be overwritten at 60' is not a lock, and the 45' verdict stays
    the authoritative one for that market.

    The same vocabulary is used — LIKELY / UNLIKELY / UNCLEAR — and "REJECTED"
    stays retired. After 60' this function is never called again; the market
    may only TRIGGER on a genuine opportunity.
    """
    total_goals = 0
    sot = 0
    for side in ("home", "away"):
        try:
            total_goals += int(data[side]["goals"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            sot += int(data[side]["stats"].get("shots-on-target", 0) or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

    token = str(ptype or "").upper()
    direction = market_direction(token)
    is_under = direction == DIRECTION_UNDER or "UNDER" in token or "U2.5" in token
    is_over = direction == DIRECTION_OVER or "OVER" in token or "O2.5" in token

    # Arithmetic still outranks everything, at any minute.
    if is_under and total_goals >= 3:
        return VERDICT_VOID, (
            f"VOID at 60': {total_goals} goals already scored — the under is "
            f"arithmetically dead"
        )
    if is_over and total_goals >= 4:
        return VERDICT_VOID, (
            f"VOID at 60': {total_goals} goals already scored — the over is "
            f"arithmetically dead"
        )

    # The engines decide, exactly as at 45'. The scoreline only breaks a tie.
    if stats_state == V_SUPPORTED or gate_state == V_SUPPORTED:
        return VERDICT_LIKELY, (
            f"LIKELY at 60': the engines agree, 2 of 3 — {total_goals} goal(s) "
            f"scored, combined SOT {sot}"
        )
    if stats_state == V_CONTRADICTED or gate_state == V_CONTRADICTED:
        return VERDICT_UNLIKELY, (
            f"UNLIKELY at 60': the engines read against this pick, 0 of 3 — "
            f"{total_goals} goal(s) scored, combined SOT {sot}. It can still come in"
        )

    # Split engines: the scoreline breaks the tie.
    if is_under and total_goals >= 3:
        return VERDICT_VOID, f"VOID at 60': {total_goals} goals already scored"
    if is_under and total_goals == 2:
        return VERDICT_UNCERTAIN, (
            f"UNCLEAR at 60': engines split 1 of 3 and 2 goals already — no "
            f"further goal allowed (SOT {sot})"
        )
    if is_under and total_goals <= 1:
        return VERDICT_LIKELY, (
            f"LIKELY at 60': engines split 1 of 3, but only {total_goals} goal(s) "
            f"scored (SOT {sot})"
        )
    if is_over and total_goals >= 3:
        return VERDICT_LIKELY, (
            f"LIKELY at 60': engines split 1 of 3, but {total_goals} goals "
            f"already scored and 1 more is still possible (SOT {sot})"
        )
    if is_over and total_goals <= 1:
        return VERDICT_UNLIKELY, (
            f"UNLIKELY at 60': engines split 1 of 3 and only {total_goals} "
            f"goal(s) scored in 60 minutes (SOT {sot})"
        )

    # TO_SCORE / GG and anything else: report the engine read honestly.
    if total_goals == 0 and sot == 0:
        return VERDICT_UNCERTAIN, (
            "UNCLEAR at 60': no goals and no shots on target recorded — the "
            "available evidence supports neither direction"
        )
    return VERDICT_UNCERTAIN, (
        f"UNCLEAR at 60': engines split 1 of 3 — {total_goals} goal(s) scored, "
        f"combined SOT {sot}"
    )


# ==============================================================================
# PHASE 2 — THE LIVE-ONLY READ (Code 2 validates every live match)
# ==============================================================================
def live_only_read(ctx):
    """
    The user's requirement, in their words:

      "i think its should give its validation to all live match the diffrence
       will just be one is the one code 1 give prediction and all orther
       matches that fail code 1 threshold should also be validated they will
       just be without prematch prediction from code 1 there validation will
       be purely from their live statistic"

    So for a match Code 1 did NOT pick, Code 2 still reads the match from its
    live statistics. Previously these fixtures were skipped entirely and the
    board was empty, which is why whole fixtures looked "lost".

    DELIBERATE RESTRICTIONS, because this is the riskiest part of the rebuild:
      * It uses the SAME three engines on the SAME live statistics. No new
        mathematics, no new SportMonks calls, no new prediction engine.
      * It is an OBSERVATION, never a bet. It is never written to a prematch
        feed and never becomes a prediction.
      * It is reported with its own vocabulary — ON_TRACK / AT_RISK / DEAD /
        UNCLEAR — and NEVER as LIKELY/UNLIKELY. Those words belong to a
        validated Code 1 pick, and reusing them here would make a live read
        indistinguishable from a real verdict.

    Returns None when the match is too early to read, or (read, note).
    """
    minute = int(ctx.get("minute") or 0)
    if minute < LIVE_ONLY_MIN_MINUTE:
        return None

    total_goals = 0
    sot = 0
    for side in ("home", "away"):
        try:
            total_goals += int(ctx[side]["goals"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            sot += int(ctx[side]["stats"].get("shots-on-target", 0) or 0)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

    # The same engines, run exactly as they run for a Code 1 Under 2.5 pick.
    synthetic_pick = {"type": "UNDER 2.5", "market": "UNDER 2.5",
                      "target_loc": "match", "target_id": None}
    f_state, f_note = new_engine_forensic_investigation(ctx, synthetic_pick)
    s_state, s_label, _ = old_engine_statistical_judge(ctx, synthetic_pick)
    direction = market_direction("UNDER_2.5")
    combined = combine_validation_states(f_state, s_state, direction)

    # Arithmetic: 3+ goals and the under is dead, whatever the engines say.
    if total_goals >= 3:
        return READ_DEAD, (
            f"Live read: {total_goals} goals already — the under is "
            f"arithmetically dead. {s_label}. No prematch pick."
        )
    # The engines decide, as everywhere else.
    if s_state == V_SUPPORTED or combined == V_SUPPORTED:
        return READ_ON_TRACK, (
            f"Live read: engines agree {s_label} — the under is on track "
            f"({total_goals} goal(s), combined SOT {sot}). No prematch pick."
        )
    if s_state == V_CONTRADICTED or combined == V_CONTRADICTED:
        return READ_AT_RISK, (
            f"Live read: engines read against the under {s_label} — pressure "
            f"is building ({total_goals} goal(s), combined SOT {sot}). "
            f"No prematch pick."
        )
    # Split engines: the scoreline is the tiebreak, as at 45' and 60'.
    if total_goals <= 1:
        return READ_ON_TRACK, (
            f"Live read: engines split {s_label}, but only {total_goals} "
            f"goal(s) scored (combined SOT {sot}). No prematch pick."
        )
    return READ_UNCLEAR, (
        f"Live read: engines split {s_label} and 2 goals already — no further "
        f"goal allowed (combined SOT {sot}). No prematch pick."
    )

# ==============================================================================
# DONE CHECK
# ==============================================================================
def check_if_done(ctx, pick, is_finished=False):
    """
    Settlement. Returns (done, note, outcome) where outcome is one of
    WON / LOST / "" (not yet settled).

    The previous version returned (done, note) and had NO branch at all for a
    losing UNDER, a failed GG, or a failed TO_SCORE. Those picks could never
    settle — they simply vanished when the feed dropped them, which is exactly
    the "neither approve nor reject" symptom. Every prematch pick now reaches a
    terminal WON/LOST.
    """
    h_g   = ctx["home"]["goals"]
    a_g   = ctx["away"]["goals"]
    h_c   = int(ctx["home"]["stats"].get("corners", 0))
    a_c   = int(ctx["away"]["stats"].get("corners", 0))
    ptype = str(pick.get('type', '')).upper()
    side  = pick.get('target_loc')
    total = h_g + a_g

    # GG_OVER_2.5 is a compound market: 1-1 satisfies GG but does not settle
    # Over 2.5. Check the compound condition before the single-market branches.
    is_gg = "GG" in ptype
    is_over25 = "OVER_2.5" in ptype or "OVER2.5" in ptype
    is_under25 = "UNDER_2.5" in ptype or "UNDER2.5" in ptype or "U2.5" in ptype

    if is_under25:
        # UNDER 2.5 — the market the user now locks at 45'. Settlement is
        # independent of the validation verdict: the verdict is a judgement
        # about the match, the settlement is the fact of the scoreline.
        if total >= 3:
            return True, f"UNDER 2.5 lost — {total} goals ❌", VERDICT_LOST
        if is_finished:
            return True, f"UNDER 2.5 won — {total} goals at FT ✅", VERDICT_WON
        return False, "", ""

    if is_gg and is_over25:
        if h_g > 0 and a_g > 0 and total >= 3:
            return True, "GG + Over 2.5 settled ✅", VERDICT_WON
        if is_finished:
            return True, f"GG + Over 2.5 failed at FT ({h_g}-{a_g}) ❌", VERDICT_LOST
        return False, "", ""

    if is_gg:
        if h_g > 0 and a_g > 0:
            return True, "GG settled ✅", VERDICT_WON
        # The missing GG LOSE branch. Once a side is 0-0 and the match is over,
        # GG can never be satisfied and the pick must be marked lost.
        if is_finished and (h_g == 0 or a_g == 0):
            return True, f"GG failed at FT ({h_g}-{a_g}) ❌", VERDICT_LOST
        return False, "", ""

    if "TO_SCORE" in ptype:
        scored = (side == "home" and h_g > 0) or (side == "away" and a_g > 0)
        if scored:
            return True, "Scored ✅", VERDICT_WON
        # The missing TO_SCORE LOSE branch. At FT with the target side on 0
        # goals the pick can never be met and must settle as lost.
        if is_finished:
            label = "Home" if side == "home" else "Away"
            return True, f"{label} did not score — TO_SCORE lost ❌", VERDICT_LOST
        return False, "", ""

    if is_over25 and total >= 3:
        return True, "Over 2.5 settled ✅", VERDICT_WON
    if is_over25 and is_finished:
        return True, f"Over 2.5 failed at FT ({h_g}-{a_g}) ❌", VERDICT_LOST

    if "OVER" in ptype and "CORNER" in ptype:
        if (h_c + a_c) >= 10:
            return True, "Corner over settled ✅", VERDICT_WON
        if is_finished:
            return True, f"Corner over failed at FT ({h_c}+{a_c}) ❌", VERDICT_LOST

    # Generic FT resolver: any market still open when the whistle goes is
    # settled as lost rather than left hanging forever.
    if is_finished:
        return True, f"Resolved at FT ({h_g}-{a_g}) ❌", VERDICT_LOST

    return False, "", ""

# ==============================================================================
# ════════════════════════════════════════════════════════════════════════════
# 🔥 TRIPLE PHASE AUDIT — FULL VISIBLE OUTPUT PER MATCH PER PICK
# ════════════════════════════════════════════════════════════════════════════
# ==============================================================================
def _notify_triggered(ctx, label, ptype, target, minute, score_at_trigger):
    """
    Record a TRIGGERED notification event.

    Wrapped so a notification problem can never raise into the live audit
    loop, which would otherwise abandon the remaining predictions for this
    fixture. SUPPORTED is intentionally not emitted - it is reversible.
    """
    try:
        from notifications import emit_event
        emit_event(
            "TRIGGERED",
            ctx["id"], ctx.get("name"),
            ptype, target,
            minute=minute, trigger_minute=minute,
            score_at_trigger=score_at_trigger,
        )
    except Exception:
        pass


def _notify_settled(ctx, label, ptype, target, settlement):
    """Record a SETTLED notification event (final result). Never raises."""
    try:
        from notifications import emit_event
        emit_event(
            "SETTLED",
            ctx["id"], ctx.get("name"),
            ptype, target,
            settlement=settlement,
            final_score=f"{ctx['home']['goals']}-{ctx['away']['goals']}",
        )
    except Exception:
        pass


def process_triple_phase_audit(ctx, picks, cycle_log):
    """
    Full visible validation board for every pick in every tracked match.
    cycle_log: list that collects per-match summary lines for the end-of-cycle board.
    """
    global VALIDATED_ALERTS

    f_id   = ctx["id"]
    minute = ctx["minute"]
    name   = ctx["name"]

    if f_id not in MATCH_VALIDATION_STATE:
        MATCH_VALIDATION_STATE[f_id] = {}

    match_summary_lines = []
    prediction_rows = []

    for idx, pick in enumerate(picks):
        # ── HARDENING: never let a malformed/non-actionable entry kill ──
        # ── the remaining valid picks for this fixture.             ──
        # Killer rules used to append raw strings here, which crashed
        # pick['type'] below with TypeError and aborted the whole fixture.
        if not isinstance(pick, dict):
            match_summary_lines.append(
                f"   ⏭️  [{idx}] SKIPPED non-actionable feed entry: {str(pick)[:80]}"
            )
            continue
        if pick.get('type') == "KILLER_NOTE":
            # Informational killer-rule note (Stage 1). Not a prediction —
            # excluded from verification but preserved on the board.
            match_summary_lines.append(
                f"   📝 [{idx}] KILLER NOTE: {str(pick.get('note', ''))[:80]}"
            )
            continue

        # State is keyed on the canonical MARKET, not the list index. Index
        # keys meant a reordered or deduped feed reset every prediction's
        # history, and duplicates at different indices tracked separately.
        p_key  = pick.get("canonical_key") or normalize_pick(pick)[0] or f"{idx}_{pick['type']}"
        ptype  = pick.get('market') or pick.get('type', 'UNKNOWN')
        target = pick.get('target_loc', 'match')
        label  = f"{ptype} ({target})" if target != 'match' else ptype
        # Once a pick is settled its gate verdict is history — the settlement
        # is the answer, so the raw counters must not be shown as UNKNOWN.
        # The canonical label is already the market name, so the U2.5/O2.5
        # aliases are kept only for backward compatibility with old feeds.
        if ptype in ("U2.5", "O2.5", "UNDER_2.5", "OVER_2.5"):
            label = ptype

        # ── DONE CHECK ──────────────────────────────────────────────────────
        # ctx["is_finished"] is set once by extract_live_context from the shared
        # state classifier, so settlement uses the SAME finished definition the
        # board uses rather than a second, possibly disagreeing one.
        done, done_reason, settlement_outcome = check_if_done(
            ctx, pick, is_finished=bool(ctx.get("is_finished")))
        if done:
            if MATCH_VALIDATION_STATE[f_id].get(p_key) != "DONE":
                MATCH_VALIDATION_STATE[f_id][p_key] = "DONE"
                line = f"   ✅ [{label}] SETTLED → {done_reason}"
                match_summary_lines.append(line)
                print(f"\n🏁 PICK SETTLED | {name} | Min {minute}'")
                print(f"   Pick   : {label}")
                print(f"   Result : {done_reason}")
            # A settled prediction has a definitive answer. The gate verdicts are
            # no longer meaningful, so they are recorded as SETTLED rather than
            # left missing for the UI to render as UNKNOWN.
            #
            # BUG FIXED: this branch used to append a bare dict and `continue`,
            # which DISCARDED the whole validation history for that pick. The
            # 30' observation, the 45' verdict, the 60' final validation and the
            # 30'->45' comparison all lived in the ledger entry, and none of it
            # reached the board — so a settled prediction showed "SETTLED" with
            # no evidence of the work Code 2 had actually done, and the per-match
            # monitor list appeared empty. The ledger is the record; a settled
            # pick must still show how it got there.
            stage, stage_note = prediction_lifecycle_step(
                pick, "SETTLED", V_SETTLED, minute, True)
            _notify_settled(ctx, label, ptype, target, done_reason)
            settled_entry = MATCH_VALIDATION_STATE[f_id].get(p_key)
            settled_entry = settled_entry if isinstance(settled_entry, dict) else {}
            prediction_rows.append({
                "key":         p_key,
                "label":       label,
                "type":        ptype,
                "target":      target,
                "status":      "SETTLED",
                "stage":       stage,
                "stage_note":  stage_note,
                "signal":      V_SETTLED,
                "forensic":    V_SETTLED,
                "statistics":  V_SETTLED,
                "stats_label": "SETTLED",
                "settlement":  done_reason,
                "triggered":   True,
                "minute":      minute,
                "final_score": f"{ctx['home']['goals']}-{ctx['away']['goals']}",
                # The full validation trail, preserved on settlement.
                "verdict_30":  settled_entry.get("verdict_30"),
                "verdict_45":  settled_entry.get("verdict_45"),
                "verdict_60":  settled_entry.get("verdict_60"),
                "verdict_30_minute": settled_entry.get("verdict_30_minute"),
                "verdict_45_minute": settled_entry.get("verdict_45_minute"),
                "verdict_60_minute": settled_entry.get("verdict_60_minute"),
                "late_30":     bool(settled_entry.get("late_30")),
                "late_45":     bool(settled_entry.get("late_45")),
                "late_60":     bool(settled_entry.get("late_60")),
                "backfilled":  bool(settled_entry.get("backfilled")),
                "comparison_30_45": settled_entry.get("comparison_30_45"),
                "comparison_note": settled_entry.get("comparison_note"),
                "verdict_note": (settled_entry.get("verdict_60_note")
                                 or settled_entry.get("verdict_note")),
            })
            continue

        if MATCH_VALIDATION_STATE[f_id].get(p_key) == "DONE":
            match_summary_lines.append(f"   ✅ [{label}] Previously settled")
            done_entry = MATCH_VALIDATION_STATE[f_id].get(p_key)
            done_entry = done_entry if isinstance(done_entry, dict) else {}
            prediction_rows.append({
                "key":         p_key,
                "label":       label,
                "type":        ptype,
                "target":      target,
                "status":      "SETTLED",
                "stage":       "SETTLED",
                "stage_note":  "Outcome decided in an earlier cycle",
                "settlement":  "Settled in an earlier cycle",
                "triggered":   True,
                "minute":      minute,
                "final_score": f"{ctx['home']['goals']}-{ctx['away']['goals']}",
                # Same rule: a settled pick keeps its validation trail.
                "verdict_30":  done_entry.get("verdict_30"),
                "verdict_45":  done_entry.get("verdict_45"),
                "verdict_60":  done_entry.get("verdict_60"),
                "verdict_30_minute": done_entry.get("verdict_30_minute"),
                "verdict_45_minute": done_entry.get("verdict_45_minute"),
                "verdict_60_minute": done_entry.get("verdict_60_minute"),
                "comparison_30_45": done_entry.get("comparison_30_45"),
                "comparison_note": done_entry.get("comparison_note"),
            })
            continue

        # ── RUN BOTH ENGINES ────────────────────────────────────────────────
        pick_direction = market_direction(ptype)
        forensic_state, n_note   = new_engine_forensic_investigation(ctx, pick)
        stats_state, o_note, engine_detail = old_engine_statistical_judge(ctx, pick)
        # `direction` is passed so a match-level UNDER/OVER market is judged by
        # the statistical engines alone. Without it the forensic requirement
        # made every Under 2.5 verdict unreachable (see
        # combine_validation_states).
        combined_state = combine_validation_states(
            forensic_state, stats_state, pick_direction)
        # The gate opens only when the applicable dimensions say SUPPORTED.
        # A single weak signal (the old STATS_1/3 case) can no longer pass.
        gate_open = combined_state == V_SUPPORTED
        new_ok = forensic_state == V_SUPPORTED
        old_ok = stats_state == V_SUPPORTED

        def _state_text():
            return (
                f"Forensic {STATE_GLYPH[forensic_state]}{forensic_state} | "
                f"Stats {STATE_GLYPH[stats_state]}{stats_state}"
            )

        # ══════════════════════════════════════════════════════════════════
        # CHECKPOINT LEDGER — replaces the three ad-hoc phases
        # ══════════════════════════════════════════════════════════════════
        # WHY THIS REPLACEMENT EXISTS
        # The old PHASE 1 wrote `pass_30` ONLY when 30 <= minute < 45, and
        # PHASE 2 was gated on that key existing. A fixture whose first cycle
        # sighting landed at 45' or later could therefore never enter PHASE 2,
        # fell through to the `else` branch and printed "Monitoring" until the
        # match died — the permanent stall. The ledger records the pre-verdict
        # on the FIRST cycle at or past 30' wherever that happens, and flags it
        # `late_30` when the 30-45 window was genuinely missed.
        entry = MATCH_VALIDATION_STATE[f_id].get(p_key)
        if not isinstance(entry, dict):
            # A settled pick stores the string "DONE"; any other legacy shape is
            # replaced rather than trusted, so state can never wedge a market.
            entry = {}
            MATCH_VALIDATION_STATE[f_id][p_key] = entry

        def _record_checkpoint(minute_at, gate, note):
            """Append one immutable checkpoint record (capped at 3)."""
            cps = entry.setdefault("checkpoints", [])
            cps.append({
                "minute": minute_at,
                "gate": gate,
                "forensic": forensic_state,
                "statistics": stats_state,
                "combined": combined_state,
                "note": note,
            })
            del cps[:-3]
            return cps

        is_locked_market = ptype in LOCKED_AT_45_MARKETS
        pre_verdict = entry.get("verdict_30")
        main_verdict = entry.get("verdict_45")
        final60_verdict = entry.get("verdict_60")
        alerted = bool(entry.get("alerted"))

        # ── CHECKPOINT 1 — 30' PRE-VERDICT (never final) ──────────────────
        # ── CHECKPOINT 1 — 30' OBSERVATION (never a verdict) ───────────────
        # The user described this as Code 2's "first observation with its 4 or
        # 3 judges". It was recorded as PRE_APPROVED / PRE_REJECTED, which are
        # the old pre-verdict words and read on the board as an approval. At 30'
        # the engine has observed, it has not judged — so it now says what the
        # observation was: SUPPORTING, AGAINST or UNCLEAR.
        if minute >= CHECKPOINT_PRE_MINUTE and pre_verdict is None:
            if combined_state in (V_INSUFFICIENT, V_NEUTRAL):
                pre_verdict = VERDICT_UNCERTAIN
            elif gate_open:
                pre_verdict = OBSERVATION_SUPPORTING
            else:
                pre_verdict = OBSERVATION_AGAINST
            entry["verdict_30"] = pre_verdict
            entry["verdict_30_minute"] = minute
            # Capture the live picture at 30' so the 45' checkpoint can compare
            # what actually happened on the pitch between the two readings. This
            # is the "function that compares 30' to 45'" — without a recorded
            # baseline there is nothing to compare against.
            entry["snapshot_30"] = _live_snapshot(ctx, o_note)
            # `late_30` is a permanent, honest record that the 30-45 window was
            # missed. It is never used to skip the pre-verdict.
            entry["late_30"] = bool(minute >= CHECKPOINT_MAIN_MINUTE)
            _record_checkpoint(minute, combined_state,
                               f"30' pre-verdict: {pre_verdict}")
            match_summary_lines.append(
                f"   🤝 [{label}] 30' PRE-VERDICT: {pre_verdict}"
                + (" (late — window missed)" if entry["late_30"] else "")
            )
            print(f"\n🤝 30' PRE-VERDICT | {name} | Min {minute}' | {label}")
            print(f"   Pre-verdict : {pre_verdict}"
                  + (" (late)" if entry["late_30"] else ""))
            print(f"   Forensic    : {n_note}")
            print(f"   Stats       : {o_note}")

        # ── CHECKPOINT 2 — 45' MAIN VERDICT (ALWAYS DELIVERED) ────────────
        # THE USER'S MAIN RULE: 45' is the main verdict. For UNDER 2.5 it is
        # LOCKED and final.
        #
        # PHASE 1 FIX: the verdict is delivered on the FIRST cycle at or past
        # 45', whatever that minute is. A pick whose first sighting lands at
        # 61' or later still receives its 45' verdict here rather than falling
        # through to monitoring and settling at full time with no validation on
        # record. `late_45` states honestly that the 45' window itself was
        # missed; it never suppresses the verdict.
        if minute >= CHECKPOINT_MAIN_MINUTE and main_verdict is None:
            late_45 = bool(minute > CHECKPOINT_MAIN_MINUTE)
            if is_locked_market:
                main_verdict, verdict_note = locked_verdict_at_45(
                    combined_state, ctx, stats_state)
                entry["locked"] = True
            else:
                main_verdict = verdict_from_gate(combined_state)
                verdict_note = f"45' main verdict: {main_verdict}"

            reconciled, overruled, tally_note = reconcile_pre_and_main(
                pre_verdict, main_verdict)
            main_verdict = reconciled
            entry["verdict_45"] = main_verdict
            entry["verdict_45_minute"] = minute
            entry["late_45"] = late_45
            entry["overruled"] = overruled
            entry["final"] = bool(is_locked_market)
            entry["verdict_note"] = verdict_note
            # THE 30' -> 45' COMPARISON. This is the function the user
            # described: it measures how the match actually MOVED between the
            # two checkpoints, rather than only comparing two verdict words.
            snap30 = entry.get("snapshot_30")
            snap45 = _live_snapshot(ctx, o_note, main_verdict)
            entry["snapshot_45"] = snap45
            comparison, compare_note = compare_observation_to_verdict(
                snap30, snap45)
            entry["comparison_30_45"] = comparison
            entry["comparison_note"] = compare_note
            _record_checkpoint(minute, combined_state,
                               f"45' main verdict: {main_verdict} ({verdict_note})")

            match_summary_lines.append(
                f"   🎯 [{label}] 45' MAIN VERDICT: {main_verdict}"
                f"{' [LOCKED]' if is_locked_market else ''}"
                + (" (late — window missed)" if late_45 else "")
            )
            if overruled:
                match_summary_lines.append(f"      ↳ {tally_note}")
            print(f"\n🎯 45' MAIN VERDICT | {name} | Min {minute}' | {label}")
            print(f"   Verdict  : {main_verdict} — {verdict_note}"
                  + (" (LATE — 45' window was missed)" if late_45 else ""))
            print(f"   Tally    : {tally_note}")

        # ── CHECKPOINT 3 — 60' FINAL VALIDATION (every Code 1 market) ──────
        # PHASE 1: previously ONLY Under 2.5 was locked, and only at 45'. Every
        # other Code 1 market (TO_SCORE, GG, OVER 2.5) could sit unresolved
        # for the whole match and settle at FT with no validation ever
        # recorded. Code 2 is a VALIDATOR, so every pick it carries must get a
        # final, honest judgement.
        #
        # Two rules are enforced here:
        #   * Under 2.5 is NOT re-decided. It locked at 45'; a lock that can be
        #     overwritten at 60' would not be a lock.
        #   * After 60' this never runs again — the market is trigger-only.
        if (minute >= CHECKPOINT_FINAL_MINUTE
                and final60_verdict is None
                and ptype in LOCKED_AT_60_MARKETS
                and not is_locked_market):
            late_60 = bool(minute > CHECKPOINT_FINAL_MINUTE)
            final60_verdict, verdict60_note = final_verdict_at_60(
                combined_state, ctx, ptype, stats_state, target)
            entry["verdict_60"] = final60_verdict
            entry["verdict_60_minute"] = minute
            entry["late_60"] = late_60
            entry["backfilled"] = bool(late_60)
            entry["final_60"] = True
            entry["verdict_60_note"] = verdict60_note
            _record_checkpoint(
                minute, combined_state,
                f"60' FINAL VALIDATION: {final60_verdict} ({verdict60_note})")
            match_summary_lines.append(
                f"   🔒 [{label}] 60' FINAL VALIDATION: {final60_verdict}"
                + (" (late — window missed)" if late_60 else "")
            )
            print(f"\n🔒 60' FINAL VALIDATION | {name} | Min {minute}' | {label}")
            print(f"   Verdict  : {final60_verdict} — {verdict60_note}"
                  + (" (LATE — 60' window was missed)" if late_60 else ""))
            print(f"   Engines  : {o_note}")

        # ── BACKFILL: first seen after 60' with no 60' verdict ─────────────
        # PHASE 1 item 4. A fixture first spotted at 75' can never have had a
        # live 60' checkpoint. Rather than leave it permanently unvalidated,
        # record an explicit backfilled read so the board is never silently
        # empty. It is always flagged, never disguised as a live 60' read.
        if (minute > TRIGGER_ONLY_AFTER_MINUTE
                and final60_verdict is None
                and ptype in LOCKED_AT_60_MARKETS
                and main_verdict is not None):
            final60_verdict, verdict60_note = final_verdict_at_60(
                combined_state, ctx, ptype, stats_state, target)
            entry["verdict_60"] = final60_verdict
            entry["verdict_60_minute"] = minute
            entry["late_60"] = True
            entry["backfilled"] = True
            entry["verdict_60_note"] = (
                f"Backfilled after the 60' window: {verdict60_note}")
            _record_checkpoint(
                minute, combined_state,
                f"60' validation BACKFILLED: {final60_verdict}")
            match_summary_lines.append(
                f"   🔒 [{label}] 60' VALIDATION BACKFILLED (seen at {minute}'): "
                f"{final60_verdict}"
            )
            print(f"\n🔒 60' BACKFILL | {name} | Min {minute}' | {label}")
            print(f"   Verdict  : {final60_verdict} (backfilled, not a live 60' read)")

        # ── ALERT FIRING (decoupled from the 30' handshake) ─────────────
        # Previously `elif minute >= 45 and ...get("pass_30")` meant a pick that
        # never passed the 30' gate could NEVER alert, even at 78'. The alert
        # is now decided on the main verdict and the market's own open window.
        market_open = (
            CHECKPOINT_PRE_MINUTE <= minute <= TO_SCORE_CLOSE_MINUTE
            if ptype == "TO_SCORE" or target != "match"
            else minute >= CHECKPOINT_MAIN_MINUTE
        )
        alert_key = f"{f_id}_{p_key}_ALERT"
        # A suppressed pick — a contradictory market on an UNDER fixture, or an
        # orphan carried forward after its feed row vanished — is never
        # alertable. It stays on the board with its reason so the audit trail
        # survives, but it can never fire a fresh Supreme Alert and contradict
        # the market the fixture is actually tracked on.
        if pick.get("suppressed"):
            if not entry.get("suppression_logged"):
                entry["suppression_logged"] = True
                match_summary_lines.append(
                    f"   ⛔ [{label}] {pick.get('suppressed_reason') or SUPPRESSED_REASON}"
                )
        if (gate_open and market_open and minute >= CHECKPOINT_PRE_MINUTE
                and not alerted and alert_key not in ALERT_HISTORY_CACHE
                and ptype not in LOCKED_AT_45_MARKETS
                and not pick.get("suppressed")):
            entry["alerted"] = True
            alerted = True
            # Capture the score at the instant the alert fires. Settlement
            # compares against this, so it must be recorded at trigger time
            # and never recomputed from a later cycle.
            score_at_trigger = f"{ctx['home']['goals']}-{ctx['away']['goals']}"

            # ════════════════════════════════════════════════════════════
            # 🔥 SUPREME ALERT FIRED
            # ════════════════════════════════════════════════════════════
            print(f"\n{'🔥'*60}")
            print(f"🔥 SUPREME ALERT @ {minute}' | {name}")
            print(f"{'🔥'*60}")
            print(f"   Pick       : {label}")
            print(f"   Forensic   : ✅ {n_note}")
            print(f"   Stats      : ✅ {o_note}")
            print(f"   Engines    : {engine_detail}")
            print(f"   Scores     : Home {ctx['home']['goals']} - {ctx['away']['goals']} Away")
            print(f"   Time       : {datetime.now().strftime('%H:%M:%S')} UTC")
            print(f"{'🔥'*60}\n")

            ALERT_HISTORY_CACHE.add(alert_key)
            VALIDATED_ALERTS[alert_key] = {
                "fixture_id":        f_id,
                "match_name":        name,
                "prediction_type":   ptype,
                "target":            target,
                "forensic_note":     n_note,
                "stats_note":        o_note,
                "forensic_state":    forensic_state,
                "statistics_state":  stats_state,
                "combined_state":    combined_state,
                "minute_triggered":  minute,
                "scores":            score_at_trigger,
                "score_at_trigger":  score_at_trigger,
                "timestamp":         datetime.now().isoformat()
            }

            line = f"   🔥 [{label}] SUPREME ALERT FIRED @ {minute}' (score {score_at_trigger})"
            match_summary_lines.append(line)
            _notify_triggered(ctx, label, ptype, target,
                              minute, score_at_trigger)

            stage, stage_note = prediction_lifecycle_step(
                pick, "TRIGGERED", combined_state, minute, False)
            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        "TRIGGERED",
                "stage":         stage,
                "stage_note":    stage_note,
                "signal":        combined_state,
                "forensic":      forensic_state,
                "statistics":    stats_state,
                "stats_label":   o_note,
                "forensic_note": n_note,
                "triggered":     True,
                "minute":        minute,
                "trigger_minute": minute,
                "score_at_trigger": score_at_trigger,
                "final_score":   None,
                "settlement":    None,
            })

        # ── CHECKPOINT 3 — 60-70 FINAL STRIKE WINDOW ──────────────────────
        # UNDER 2.5 is deliberately EXCLUDED: it is LOCKED at 45' by the user's
        # rule and must not be extended. Every other market keeps this window.
        elif (FINAL_STRIKE_OPEN <= minute <= FINAL_STRIKE_CLOSE
                and ptype in ("TO_SCORE", "OVER_2.5")):
            if new_ok:
                line = f"   ⚡ [{label}] FINAL STRIKE WINDOW @ {minute}' — Gap still exploited"
                match_summary_lines.append(line)
                print(f"\n⚡ FINAL STRIKE @ {minute}' | {name} | {label} — Gap still being exploited")
            else:
                match_summary_lines.append(f"   💤 [{label}] Final strike window — gap closed")

            stage, stage_note = prediction_lifecycle_step(
                pick, "STRIKE_WINDOW", combined_state, minute, False)
            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        "STRIKE_WINDOW",
                "stage":         stage,
                "stage_note":    stage_note,
                "signal":        combined_state,
                "forensic":      forensic_state,
                "statistics":    stats_state,
                "stats_label":   o_note,
                "forensic_note": n_note,
                "triggered":     False,
                "minute":        minute,
                "score_at_trigger": None,
                "final_score":   None,
                "settlement":    None,
            })

        # ── MONITORING (before 30', or no checkpoint applies) ───────────────
        # This branch also renders the recorded verdict for markets that
        # already HAVE one, so a locked UNDER 2.5 keeps showing its final
        # verdict on every later cycle instead of reverting to "Monitoring".
        else:
            if main_verdict:
                state_label = f"{main_verdict}"
            elif pre_verdict:
                state_label = f"{pre_verdict} (pre-verdict)"
            else:
                state_label = "Monitoring"
            line = f"   👁️  [{label}] {state_label} @ {minute}' | {_state_text()}"
            match_summary_lines.append(line)

            open_status = "QUEUED" if gate_open else "WAITING"
            stage, stage_note = prediction_lifecycle_step(
                pick, open_status, combined_state, minute, False)
            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        open_status,
                "stage":         stage,
                "stage_note":    stage_note,
                "signal":        combined_state,
                "forensic":      forensic_state,
                "statistics":    stats_state,
                "stats_label":   o_note,
                "forensic_note": n_note,
                "triggered":     False,
                "minute":        minute,
                "score_at_trigger": None,
                "final_score":   None,
                "settlement":    None,
            })

        # ── LEDGER FIELDS ON EVERY ROW ───────────────────────────────────
        # Applied to the row this cycle just appended, whatever branch built
        # it, so verdict / verdict_minute / final / checkpoints are uniformly
        # present for the UI and for Code 3C.
        if prediction_rows and prediction_rows[-1].get("key") == p_key:
            row = prediction_rows[-1]
            # Parenthesised deliberately: mixing `or` and a conditional
            # expression without brackets binds as
            # `(main or pre) or (APPROVED_WATCH if gate else UNCERTAIN)`,
            # which silently ignores the pre-verdict. This is explicit.
            #
            # BUG FIXED: the old fallback showed APPROVED_WATCH purely because
            # the gate happened to be open, at ANY minute. The board therefore
            # displayed "APPROVED" against a 16th-minute match, before a single
            # judge checkpoint had been reached — exactly the "approving under
            # at 10 minutes, on what ground?" complaint.
            #
            # Code 2's contract: the 30' observation, the 45' verdict and the
            # 60' final validation are the ONLY things that may be reported. An
            # open gate is an internal signal, never a verdict, so before 30'
            # the pick is simply MONITORING and says so.
            if final60_verdict and not entry.get("locked"):
                row["verdict"] = final60_verdict
                row["verdict_note"] = entry.get("verdict_60_note")
            elif main_verdict:
                row["verdict"] = main_verdict
            elif pre_verdict:
                row["verdict"] = pre_verdict
            elif minute < CHECKPOINT_PRE_MINUTE:
                # Before the 30' observation. Nothing has been judged yet.
                row["verdict"] = None
            else:
                # 30' has passed (or was missed) but no verdict was recorded
                # yet — genuinely undecided, not approved.
                row["verdict"] = VERDICT_UNCERTAIN
            # PHASE 1: the 60' final validation supersedes the 45' verdict for
            # every market that is not locked at 45'. Without this the board
            # kept showing the 45' read forever and the 60' judgement was
            # invisible, which is what made Code 2 look like it only settles.
            if final60_verdict and not entry.get("locked"):
                row["verdict"] = final60_verdict
                row["verdict_note"] = entry.get("verdict_60_note")
            row["verdict_30"] = pre_verdict
            row["verdict_45"] = main_verdict
            row["verdict_60"] = final60_verdict
            # A suppressed pick stays visible on the board with its reason, so
            # the market that was dropped is never silently hidden.
            row["suppressed"] = bool(pick.get("suppressed"))
            row["suppressed_reason"] = pick.get("suppressed_reason")
            row["orphaned"] = bool(pick.get("orphaned"))
            # The per-judge reasoning is already computed by
            # `old_engine_statistical_judge`. It was printed to the console and
            # then discarded, which is why the board could only ever show an
            # opaque "STATS_1/3" with no way to tell a user WHICH judge
            # dissented or why. Carried on the row so the UI can show the three
            # judges and their actual readings.
            row["engine_detail"] = engine_detail
            row["late_45"] = bool(entry.get("late_45"))
            row["late_60"] = bool(entry.get("late_60"))
            row["backfilled"] = bool(entry.get("backfilled"))
            # The 30' -> 45' comparison, so the board shows how the match moved
            # between the two checkpoints rather than only the final word.
            row["comparison_30_45"] = entry.get("comparison_30_45")
            row["comparison_note"] = entry.get("comparison_note")
            row["trigger_only"] = bool(
                minute > TRIGGER_ONLY_AFTER_MINUTE
                and (final60_verdict or entry.get("locked")))
            row["verdict_minute"] = (entry.get("verdict_60_minute")
                                     or entry.get("verdict_45_minute")
                                     or entry.get("verdict_30_minute"))
            row["verdict_note"] = row.get("verdict_note") or entry.get("verdict_note")
            row["final"] = bool(entry.get("final") or entry.get("final_60"))
            row["locked"] = bool(entry.get("locked"))
            row["overruled"] = bool(entry.get("overruled"))
            row["late_30"] = bool(entry.get("late_30"))
            row["checkpoints"] = list(entry.get("checkpoints") or [])
            row["direction"] = market_direction(ptype)
            if row.get("status") == "TRIGGERED" and not row.get("verdict"):
                row["verdict"] = VERDICT_TRIGGERED
            if entry.get("verdict_note") and not row.get("stage_note"):
                row["stage_note"] = entry["verdict_note"]
            # A locked market keeps its verdict on the board even when this
            # cycle's branch wrote a generic status string.
            if main_verdict and row.get("status") in ("QUEUED", "WAITING",
                                                       "MONITORING"):
                row["status"] = main_verdict
            elif pre_verdict and row.get("status") in ("QUEUED", "WAITING",
                                                       "MONITORING"):
                row["status"] = pre_verdict

    # Collect this match's summary for the end-of-cycle board.
    # The entry is now a structured contract rather than a bag of text lines:
    # the frontend renders score / period / statistics / predictions directly
    # and no longer has to parse prose to show the live state.
    period_label = _period_label(minute)
    home_stats = ctx['home']['stats']
    away_stats = ctx['away']['stats']
    cycle_log.append({
        "name":         name,
        "minute":       minute,
        "id":           f_id,
        "fixture_id":   f_id,
        "lines":        match_summary_lines,
        "score":        f"{ctx['home']['goals']}-{ctx['away']['goals']}",
        "score_parts": {
            "home":    ctx['home']['goals'],
            "away":    ctx['away']['goals'],
            "display": f"{ctx['home']['goals']}-{ctx['away']['goals']}",
        },
        "status":       "LIVE",
        "period":       period_label,
        "is_finished":  False,
        "updated_at":   datetime.now().isoformat(),
        "statistics": {
            "home": {
                "possession":        _stat_int(home_stats, 'ball-possession'),
                "shots_on_target":   _stat_int(home_stats, 'shots-on-target'),
                "dangerous_attacks": _stat_int(home_stats, 'dangerous-attacks'),
                "corners":           _stat_int(home_stats, 'corners'),
                "box_entries":       _opt_box(home_stats),
                "box_available":     _opt_box(home_stats) is not None,
            },
            "away": {
                "possession":        _stat_int(away_stats, 'ball-possession'),
                "shots_on_target":   _stat_int(away_stats, 'shots-on-target'),
                "dangerous_attacks": _stat_int(away_stats, 'dangerous-attacks'),
                "corners":           _stat_int(away_stats, 'corners'),
                "box_entries":       _opt_box(away_stats),
                "box_available":     _opt_box(away_stats) is not None,
            },
        },
        "predictions":   prediction_rows,
    })

# ==============================================================================
# LIVE CONTEXT EXTRACTOR
# ==============================================================================
def extract_live_context(fixture):
    f_id = str(fixture["id"])

    h_id = a_id = None
    h_name = a_name = "Unknown"
    for p in fixture.get("participants", []):
        loc = p.get("meta", {}).get("location")
        if loc == "home": h_id = str(p.get("id")); h_name = p.get("name")
        elif loc == "away": a_id = str(p.get("id")); a_name = p.get("name")

    stats = {
        "home": {"ball-possession": 0, "attacks": 0, "dangerous-attacks": 0,
                 "shots-on-target": 0, "corners": 0, "box": None,
                 "box_source": None},
        "away": {"ball-possession": 0, "attacks": 0, "dangerous-attacks": 0,
                 "shots-on-target": 0, "corners": 0, "box": None,
                 "box_source": None}
    }
    for s in fixture.get("statistics", []):
        pid  = str(s.get("participant_id"))
        code = str(s.get("type", {}).get("code", "")).lower()
        val  = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value", 0)
        try: val = float(val)
        except: val = 0.0
        side = "home" if pid == h_id else ("away" if pid == a_id else None)
        if not side or not code: continue
        stats[side][code] = val

    # Box entries: prefer a code the feed actually carries and record which
    # source was used. `None` means genuinely unavailable, which is NOT the
    # same as a real 0 — the engine must not read it as zero pressure.
    # There is deliberately NO shots-total fallback: shots-total is a different
    # unit, and judging it against a box threshold made Engine 2 fail on every
    # match whose feed omitted shots-insidebox.
    for side in ("home", "away"):
        for candidate in BOX_STAT_CODES:
            if candidate in stats[side]:
                stats[side]["box"] = float(stats[side][candidate])
                stats[side]["box_source"] = candidate
                break
        else:
            if BOX_STAT_FALLBACK and BOX_STAT_FALLBACK in stats[side]:
                stats[side]["box"] = float(stats[side][BOX_STAT_FALLBACK])
                stats[side]["box_source"] = BOX_STAT_FALLBACK

    scores = {"home": 0, "away": 0}
    for s in fixture.get("scores", []):
        if "CURRENT" in (s.get("description") or "").upper():
            g    = safe_get(s, "score", "goals", default=0)
            side = safe_get(s, "score", "participant", default="").lower()
            if side in scores: scores[side] = int(g)

    # The match minute is resolved in ONE place so the engine and the board can
    # never disagree about what minute a match is on.
    current_minute = _resolve_match_minute(fixture)

    if f_id not in MATCH_CONTEXT_CACHE:
        h_sq = get_squad_data_standardized(h_id)
        a_sq = get_squad_data_standardized(a_id)
        def get_k(sq):
            l   = list(sq.values())
            gk  = sorted([p for p in l if p['pos'] == "Goalkeeper"],  key=lambda x: x['worth'], reverse=True)[:1]
            out = sorted([p for p in l if p['pos'] != "Goalkeeper"],  key=lambda x: x['worth'], reverse=True)[:10]
            return {p['id'] for p in (gk + out)}
        MATCH_CONTEXT_CACHE[f_id] = {
            "h_sq": h_sq, "a_sq": a_sq,
            "h_key": get_k(h_sq), "a_key": get_k(a_sq)
        }

    cache  = MATCH_CONTEXT_CACHE[f_id]
    impact = {
        "home": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0},
        "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0}
    }
    for e in fixture.get("events", []):
        code = safe_get(e, "type", "code")
        loc = ("home" if h_id and str(e.get("participant_id")) == h_id
               else "away" if a_id and str(e.get("participant_id")) == a_id
               else None)
        if not loc:
            continue
        if code == "red-card" and loc in impact:
            impact[loc]["reds"] += 1
        if code == "substitution" and loc in impact:
            p_off = str(e.get("player_id"))
            if p_off in cache[f"{loc[0]}_key"]:
                impact[loc]["key_sub_off"] += 1
                impact[loc]["worth_lost"]  += cache[f"{loc[0]}_sq"].get(p_off, {"worth": 0})["worth"]

    return {
        "id":     f_id,
        "name":   fixture.get("name"),
        "minute": current_minute,
        "home":   {"goals": scores["home"], "stats": stats["home"]},
        "away":   {"goals": scores["away"], "stats": stats["away"]},
        "impact": impact,
        "events": fixture.get("events", []),
        # Settlement and the board MUST agree on what "finished" means, and
        # `_fixture_is_finished` is the single definition in this module. It is
        # surfaced here because check_if_done() and the FT snapshot both need
        # it; without it every LOST branch would have been unreachable.
        "is_finished":   _fixture_is_finished(fixture),
        "is_scheduled":  _fixture_is_scheduled(fixture),
        "state_code":    _fixture_state_code(fixture),
    }

# ==============================================================================
# ════════════════════════════════════════════════════════════════════════════
# 🖨️  END-OF-CYCLE VALIDATION BOARD
# Prints a clean per-match summary after every loop so you can see
# exactly what ran, what passed, and what fired.
# ════════════════════════════════════════════════════════════════════════════
# ==============================================================================
def print_cycle_board(cycle_log, total_live, total_tracked, cycle_number):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'═'*80}")
    print(f"  📋 VALIDATION BOARD — Cycle #{cycle_number} | {now} UTC")
    print(f"  Live matches: {total_live} | Tracked targets: {total_tracked}")
    print(f"{'═'*80}")

    if not cycle_log:
        print("  No tracked matches found in live feed this cycle.")
    else:
        for entry in cycle_log:
            print(f"\n  🏟️  {entry['name']}  |  Min {entry['minute']}'  |  Score {entry['score']}")
            if entry['lines']:
                for line in entry['lines']:
                    print(f"  {line}")
            else:
                print("  No picks active for this match.")

    if VALIDATED_ALERTS:
        print(f"\n  {'─'*78}")
        print(f"  🔥 TOTAL ALERTS FIRED THIS SESSION: {len(VALIDATED_ALERTS)}")
        for key, alert in list(VALIDATED_ALERTS.items())[-5:]:
            print(
                f"    → {alert['match_name']} | {alert['prediction_type']} "
                f"| Min {alert['minute_triggered']}' | {alert['scores']} | {alert['timestamp'][:19]}"
            )

    print(f"{'═'*80}\n")

# ==============================================================================
# 📦 MAIN ENGINE EXECUTION
# ==============================================================================
def _finished_snapshot_board_entry(std):
    """
    Render a retained standardized FT snapshot as a visible board row.

    The finished row KEEPS its real statistics and its terminal prediction
    verdicts (confirmed with the user). A completed match now shows what
    actually happened instead of "no live statistics ... pressure cannot be
    assessed". The board still tracks finished rows for bookkeeping — only the
    display changed.
    """
    fid = str(std.get("fixture_id") or "")
    if not fid:
        return None
    minute = int(std.get("minute", 0) or 0) or 90
    score = std.get("ft_score") or "—"

    # Terminal verdicts recorded for this fixture while it was live, so the
    # completed row shows the audit trail rather than an empty list.
    settled_rows = []
    state_entry = MATCH_VALIDATION_STATE.get(fid, {})
    if isinstance(state_entry, dict):
        for p_key, entry in state_entry.items():
            if not isinstance(entry, dict):
                continue
            # PHASE 1: a finished fixture must show its FULL audit trail. The
            # 60' final validation supersedes the 45' verdict for every market
            # that is not locked at 45', so this is the same precedence the
            # live rows use. Previously only verdict_45/verdict_30 were
            # surfaced here, so a pick that was properly validated at 60'
            # appeared on the completed row as if it had never been judged.
            is_locked = bool(entry.get("locked"))
            v60 = entry.get("verdict_60")
            v45 = entry.get("verdict_45")
            v30 = entry.get("verdict_30")
            authoritative = (v60 if (v60 and not is_locked) else None) \
                or v45 or v30
            settled_rows.append({
                "key":           p_key,
                "label":         p_key,
                "status":        authoritative,
                "verdict":       authoritative,
                "verdict_30":    v30,
                "verdict_45":    v45,
                "verdict_60":    v60,
                "verdict_minute": (entry.get("verdict_60_minute")
                                   or entry.get("verdict_45_minute")
                                   or entry.get("verdict_30_minute")),
                "verdict_note":  (entry.get("verdict_60_note")
                                  or entry.get("verdict_note")),
                "final":         bool(entry.get("final") or entry.get("final_60")),
                "locked":        is_locked,
                "overruled":     bool(entry.get("overruled")),
                "late_30":       bool(entry.get("late_30")),
                "late_45":       bool(entry.get("late_45")),
                "late_60":       bool(entry.get("late_60")),
                "backfilled":    bool(entry.get("backfilled")),
                # The 30'->45' comparison belongs on the completed row too:
                # it is the record of how the match moved between the two
                # checkpoints, and it was being dropped here.
                "comparison_30_45": entry.get("comparison_30_45"),
                "comparison_note":  entry.get("comparison_note"),
                "checkpoints":   list(entry.get("checkpoints") or []),
                "triggered":     bool(entry.get("alerted")),
                "settlement":    None,
                "minute":        minute,
                "final_score":   score,
            })

    return {
        "name": f"{std.get('home_team') or 'Home'} vs {std.get('away_team') or 'Away'}",
        "id": fid,
        "fixture_id": fid,
        "minute": minute,
        "score": score,
        "score_parts": _score_parts(score),
        "lines": ["🏁 FINISHED RESULT RETAINED — final statistics and verdicts shown."],
        "status": "FINISHED",
        "period": _period_label(minute),
        "is_finished": True,
        "retained_finished": True,
        "updated_at": datetime.now().isoformat(),
        # Real final box stats instead of _empty_statistics().
        "statistics": _statistics_from_snapshot(std),
        # The terminal verdicts instead of [].
        "predictions": settled_rows,
    }


def run_live_validator_once(cycle_number=1):
    """One validation cycle (no own loop).

    The 24/7 runner calls this once per scheduler cycle. The legacy
    run_live_validator_engine() owns an infinite while-True loop and would
    block every stage after it (stage 6 never ran, so orchestrator_board.json
    and ready_to_push.json were never produced). This returns the cycle board
    and persists it to validation_board.json so /api/live/validation can serve
    real `matches` + `total_live` instead of hardcoded empties.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    if not API_TOKEN:
        return {}

    load_memory()

    FEED_A = _load_pick_feeds()
    # A prediction that already alerted or reached a verdict must not vanish
    # when its feed row disappears — that is how two Over alerts ended up
    # stranded in Code 3C with no way to be validated or settled.
    carry_forward_orphans(FEED_A)

    cycle_log = []

    try:
        from backend.live_cache import get_live_scores_cached
    except ImportError:
        from live_cache import get_live_scores_cached

    live_matches = get_live_scores_cached() or []
    live_ids = {str(fx.get("id")) for fx in live_matches if isinstance(fx, dict)}
    live_finished_ids = {
        str(fx.get("id")) for fx in live_matches
        if isinstance(fx, dict) and _fixture_is_finished(fx)
    }
    # FIX 3: fixture-level processing errors used to vanish into stdout
    # (⚠️  Error processing …), leaving downstream consumers unable to
    # distinguish "no picks" / "pending" from "processing failed".
    # Collect them here and expose them additively on the board.
    fixture_errors = []

    retained_finished = 0
    for fx in live_matches:
        if not isinstance(fx, dict):
            continue
        f_id = str(fx.get("id") or "")
        picks = FEED_A.get(f_id, [])
        before = len(cycle_log)
        try:
            if not _fixture_is_scheduled(fx):
                ctx = extract_live_context(fx)
                if picks:
                    process_triple_phase_audit(ctx, picks, cycle_log)
                else:
                    # ── PHASE 2: no Code 1 pick, but Code 2 still reads it ──
                    # Previously `if picks and ...` meant a fixture that failed
                    # Code 1's threshold was never validated at all and showed an
                    # empty board. The user asked for every live match to be
                    # validated from its live statistics. The read is an
                    # OBSERVATION, clearly labelled, never a bet.
                    entry = _summary_board_entry(fx)
                    try:
                        read = live_only_read(ctx)
                    except Exception as read_err:
                        read = None
                        entry["lines"].append(
                            f"⚠️ live read unavailable: {read_err}")
                    if read:
                        read_state, read_note = read
                        entry["live_read"] = {
                            "key":          LIVE_ONLY_MARKET,
                            "label":        "UNDER 2.5 (live read)",
                            "type":         LIVE_ONLY_MARKET,
                            "target":       "match",
                            "status":       "READ",
                            "stage":        "READ",
                            "stage_note":   read_note,
                            "read":         read_state,
                            "read_label":   read_state.replace("_", " "),
                            "prematch_pick": False,
                            "signal":       combined_read_state(read_state),
                            "verdict":      None,
                            "stats_label":  read_note,
                            "minute":       int(ctx.get("minute") or 0),
                            "triggered":    False,
                        }
                        entry["lines"].append(
                            f"📖 LIVE READ (no Code 1 pick): {read_state}")
                    cycle_log.append(entry)
            else:
                entry = _summary_board_entry(fx)
                if picks:
                    entry["lines"].append(
                        f"📌 {len(picks)} actionable pick(s) queued for kickoff."
                    )
                cycle_log.append(entry)
        except Exception as e:
            print(f"  ⚠️  Error processing {f_id}: {e}")
            if len(cycle_log) == before:
                cycle_log.append(_summary_board_entry(fx))
            fixture_errors.append({
                "fixture_id": f_id,
                "error":      str(e),
                "timestamp":  datetime.now().isoformat()
            })

    # Finished results can disappear from /livescores/inplay before the next
    # request. Merge the same persistent FT snapshot used by settlement so the
    # verifier retains the result instead of reverting to an empty universe.
    try:
        from settlement_service import load_ft_snapshot
        snapshot_date = datetime.now().strftime("%Y-%m-%d")
        for fid, std in (load_ft_snapshot(snapshot_date) or {}).items():
            if str(fid) in live_finished_ids:
                continue
            entry = _finished_snapshot_board_entry(std)
            if entry:
                cycle_log.append(entry)
                retained_finished += 1
    except Exception as e:
        fixture_errors.append({
            "fixture_id": "FT_SNAPSHOT",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        })

    tracked_count = len(cycle_log)
    print_cycle_board(cycle_log, len(live_matches), tracked_count, cycle_number)

    board = {
        "cycle":        cycle_number,
        "total_live":   len(live_matches),
        "total_tracked": tracked_count,
        "retained_finished": retained_finished,
        "matches":      cycle_log,
        # Additive field: only populated when a fixture actually failed to
        # process. An empty list means every tracked fixture was processed.
        "errors":       fixture_errors,
    }
    try:
        with open(BOARD_FILE, 'w') as f:
            json.dump(board, f)
    except Exception as e:
        print(f"Error saving validation board: {e}", file=sys.stderr)

    save_memory()

    # ── PUSH NOTIFICATIONS (best effort) ──────────────────────────────────
    # Runs after the board is written so a notification problem can never
    # interfere with validation. Fully wrapped: delivery must never raise into
    # the live cycle. Set ALIENEDGE_PUSH=0 to disable without a code change.
    if os.getenv("ALIENEDGE_PUSH", "1") not in ("0", "false", "False"):
        try:
            import notifications as _notify
            summary = _notify.dispatch(_notify.pending_events(limit=50))
            if summary.get("sent"):
                print(f"   📲 push dispatched: {summary}")
        except Exception as exc:
            print(f"   📲 push dispatch skipped: {exc}", file=sys.stderr)

    return board


def run_live_validator_engine():
    """Legacy standalone entry point; use the same all-fixture cycle as the relay."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}
    cycle_number = 0
    while True:
        cycle_number += 1
        run_live_validator_once(cycle_number)
        time.sleep(40)


if __name__ == "__main__":
    print("--- ALIENEDGE LIVE VALIDATOR ENGINE STANDBY ---")
    run_live_validator_engine()
