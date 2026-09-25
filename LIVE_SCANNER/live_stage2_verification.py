import os
import sys
import time
import json
import random
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

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

# ── THRESHOLDS (lowered to 50% so alerts trigger in real match conditions) ──
MIN_DA_RATIO        = 0.50   # was 0.62
MIN_SOT_RATIO       = 0.50   # was 0.60
MIN_BOX_TOUCH_DIFF  = 2      # was 4
MIN_MOMENTUM_FACTOR = 1.10   # was 1.30

# ── VALIDATION GATE POLICY ───────────────────────────────────────────────────
# Validators no longer return a loose boolean. Each one reports one of four
# states so that "nothing bad happened" can never be counted as positive
# predictive evidence (it used to return True for MAINTAINED / STABLE).
V_SUPPORTED    = "SUPPORTED"
V_CONTRADICTED = "CONTRADICTED"
V_NEUTRAL      = "NEUTRAL"
V_INSUFFICIENT = "INSUFFICIENT_DATA"

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
    """Merge Stage 1 and Stage 3 picks without making either feed authoritative.

    Stage 1 is the older strategic feed; Stage 3 is the lineup/forensic feed.
    Both can legitimately contain the same fixture, and an empty Stage 1 file
    must not make the validator blind to current Stage 3 picks.
    """
    merged = {}
    for path in (PREDICTIONS_FILE, INCOMING_PREDICTIONS_FILE):
        for fid, picks in _read_pick_feed(path).items():
            existing = merged.setdefault(fid, [])
            seen = {json.dumps(p, sort_keys=True, default=str) for p in existing
                    if isinstance(p, dict)}
            for pick in picks:
                if not isinstance(pick, dict):
                    continue
                key = json.dumps(pick, sort_keys=True, default=str)
                if key not in seen:
                    existing.append(pick)
                    seen.add(key)
    return merged


def _stat_int(stats, key):
    """Provider stats arrive as floats (or occasionally strings/None)."""
    try:
        return int(float(stats.get(key, 0) or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def _fixture_state_code(fixture):
    state = fixture.get("state")
    if isinstance(state, dict):
        return str(state.get("state") or state.get("short_name") or "").upper()
    return str(state or "").upper()


def _fixture_is_finished(fixture):
    token = _fixture_state_code(fixture)
    return token in {"FT", "AET", "AP", "FT_PEN", "PEN", "FINISHED", "ENDED",
                     "FULL-TIME", "FULL TIME", "FULL_TIME"} or token.startswith("FT_")


def _fixture_is_scheduled(fixture):
    token = _fixture_state_code(fixture)
    return token in {"NS", "TBD", "POSTPONED", "CANCELLED", "CANCELED"}


def _fixture_minute_for_board(fixture):
    found = []
    time_obj = fixture.get("time")
    if isinstance(time_obj, dict):
        try: found.append(int(time_obj.get("minute", 0) or 0))
        except (TypeError, ValueError): pass
    state_obj = fixture.get("state")
    if isinstance(state_obj, dict):
        try: found.append(int(state_obj.get("minute", 0) or 0))
        except (TypeError, ValueError): pass
    for period in fixture.get("periods", []) or []:
        if not isinstance(period, dict): continue
        value = (period.get("minute") or period.get("minutes")
                 or period.get("length"))
        try:
            if value is not None: found.append(int(value))
        except (TypeError, ValueError): pass
    for event in fixture.get("events", []) or []:
        try:
            value = event.get("minute")
            if value is not None: found.append(int(value))
        except (AttributeError, TypeError, ValueError): pass
    return max(found or [0])


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
    """Same statistics shape as a live row, so the frontend renders uniformly."""
    blank = {
        "possession": 0, "shots_on_target": 0, "dangerous_attacks": 0,
        "corners": 0, "box_entries": 0,
    }
    return {"home": dict(blank), "away": dict(blank)}


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
    """Create a visible board row without requiring an attached prediction."""
    finished = _fixture_is_finished(fixture)
    scheduled = _fixture_is_scheduled(fixture)
    if finished:
        lines = ["🏁 FINISHED RESULT RETAINED — settlement snapshot is available."]
    elif scheduled:
        lines = ["⏳ SCHEDULED — retained in the live verification universe; awaiting kickoff."]
    else:
        lines = ["👁️ LIVE — retained in the live verification universe; no actionable pick attached."]
    f_id = str(fixture.get("id", ""))
    minute = _fixture_minute_for_board(fixture)
    score = _score_for_board(fixture)
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
        "statistics": _empty_statistics(),
        "predictions": [],
    }


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
        result = (get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')) >= 2  # was 3
        return result, f"SOT combined {get_s(h_s,'shots-on-target')+get_s(a_s,'shots-on-target')} ≥ 2"

    if "UNDER" in ptype:
        result = (get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')) <= 1
        return result, f"SOT combined {get_s(h_s,'shots-on-target')+get_s(a_s,'shots-on-target')} ≤ 1"

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
def engine_2_structural_stacker(data, target_loc):
    def get_s(d, k): return int(d.get(k, 0))

    # Match-level markets (O2.5 / U2.5 / GG) have no single target side.
    # Evaluate BOTH teams using their combined two-team match data instead
    # of a home/away dominance split. Do NOT map None → "home".
    if target_loc is None:
        h = data['home']['stats']
        a = data['away']['stats']
        tot_sot = get_s(h, 'shots-on-target') + get_s(a, 'shots-on-target')
        tot_box = get_s(h, 'box') + get_s(a, 'box')
        sot_ok  = tot_sot >= 2
        box_ok  = tot_box >= 2
        return (sot_ok or box_ok), (
            f"Combined SOT {tot_sot} ≥ 2: {'✅' if sot_ok else '❌'} | "
            f"Combined box touches {tot_box} ≥ 2: {'✅' if box_ok else '❌'}"
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

    box_diff = int(exp.get('box', 0)) - int(opp.get('box', 0))
    box_ok   = box_diff >= MIN_BOX_TOUCH_DIFF
    signals.append(f"Box touch diff {box_diff} ≥ {MIN_BOX_TOUCH_DIFF}: {'✅' if box_ok else '❌'}")
    if box_ok: signal_pass.append(True)

    corn_diff = get_s(exp, 'corners') - get_s(opp, 'corners')
    corn_ok   = corn_diff >= 2
    signals.append(f"Corner diff {corn_diff} ≥ 2: {'✅' if corn_ok else '❌'}")
    if corn_ok: signal_pass.append(True)

    passed = len(signal_pass) >= 2
    return passed, " | ".join(signals)

# ==============================================================================
# ENGINE 3 — MOMENTUM ESCALATOR
# ==============================================================================
def engine_3_momentum_escalator(data, target_id):
    now = data['minute']
    if not target_id or now < 15:
        return False, f"Minute {now} < 15 — too early"

    recent = 0
    for e in data.get('events', []):
        if str(e.get("participant_id")) == str(target_id):
            if (e.get("minute") or 0) > (now - 12):
                if safe_get(e, "type", "code") in ["corner", "shot-on-target", "goal"]:
                    recent += 1

    passed = recent >= 2
    return passed, f"Recent key events in last 12 min: {recent} ≥ 2: {'✅' if passed else '❌'}"

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
    opp_box = int(opp_stats.get('box', 0))

    if has_red or gk_liability:
        # Lowered thresholds: was sot≥2, da≥20, box≥5
        if opp_sot >= 1 or opp_da >= 10 or opp_box >= 3:
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
    e2_pass, e2_note = engine_2_structural_stacker(ctx, pick.get('target_loc'))
    e3_pass, e3_note = engine_3_momentum_escalator(ctx, pick.get('target_id'))

    passed_count = sum([bool(e1_pass), bool(e2_pass), bool(e3_pass)])

    if passed_count >= STATS_MIN_ENGINES_FOR_PASS:
        state = V_SUPPORTED
    elif passed_count == STATS_PARTIAL_ENGINES:
        state = V_INSUFFICIENT
    else:
        state = V_CONTRADICTED

    detail = (
        f"\n         Engine 1 (Rule)       : {'✅ PASS' if e1_pass else '❌ FAIL'} → {e1_note}"
        f"\n         Engine 2 (Structure)  : {'✅ PASS' if e2_pass else '❌ FAIL'} → {e2_note}"
        f"\n         Engine 3 (Momentum)   : {'✅ PASS' if e3_pass else '❌ FAIL'} → {e3_note}"
        f"\n         Combined              : {passed_count}/3 engines passed"
        f" (need {STATS_MIN_ENGINES_FOR_PASS}/3 for a standard pass)"
    )
    return state, f"STATS_{passed_count}/3", detail


def combine_validation_states(forensic_state, stats_state):
    """
    Combine the forensic and statistical verdicts into one gate state.

    An alert is only SUPPORTED when BOTH dimensions agree. Anything short of
    that is reported honestly as monitoring rather than as a pass.
    """
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
}

# ==============================================================================
# DONE CHECK
# ==============================================================================
def check_if_done(ctx, pick):
    h_g   = ctx["home"]["goals"]
    a_g   = ctx["away"]["goals"]
    h_c   = int(ctx["home"]["stats"].get("corners", 0))
    a_c   = int(ctx["away"]["stats"].get("corners", 0))
    ptype = str(pick.get('type', '')).upper()
    side  = pick.get('target_loc')

    # GG_OVER_2.5 is a compound market: 1-1 satisfies GG but does not settle
    # Over 2.5. Check the compound condition before the single-market branches.
    is_gg = "GG" in ptype
    is_over25 = "OVER_2.5" in ptype or "OVER2.5" in ptype
    if is_gg and is_over25:
        if h_g > 0 and a_g > 0 and (h_g + a_g) >= 3:
            return True, "GG + Over 2.5 settled ✅"
        return False, ""
    if is_gg and h_g > 0 and a_g > 0:
        return True, "GG settled ✅"
    if "TO_SCORE" in ptype:
        if side == "home" and h_g > 0:                           return True, "Home scored ✅"
        if side == "away" and a_g > 0:                           return True, "Away scored ✅"
    if is_over25 and (h_g + a_g) >= 3:                       return True, "Over 2.5 settled ✅"
    if "OVER"     in ptype and "CORNER" in ptype and (h_c + a_c) >= 10: return True, "Corner over settled ✅"
    return False, ""

# ==============================================================================
# ════════════════════════════════════════════════════════════════════════════
# 🔥 TRIPLE PHASE AUDIT — FULL VISIBLE OUTPUT PER MATCH PER PICK
# ════════════════════════════════════════════════════════════════════════════
# ==============================================================================
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

        p_key  = f"{idx}_{pick['type']}"
        ptype  = pick.get('type', 'UNKNOWN')
        target = pick.get('target_loc', 'match')
        label  = f"{ptype} ({target})" if target != 'match' else ptype

        # ── DONE CHECK ──────────────────────────────────────────────────────
        done, done_reason = check_if_done(ctx, pick)
        if done:
            if MATCH_VALIDATION_STATE[f_id].get(p_key) != "DONE":
                MATCH_VALIDATION_STATE[f_id][p_key] = "DONE"
                line = f"   ✅ [{label}] SETTLED → {done_reason}"
                match_summary_lines.append(line)
                print(f"\n🏁 PICK SETTLED | {name} | Min {minute}'")
                print(f"   Pick   : {label}")
                print(f"   Result : {done_reason}")
            else:
                match_summary_lines.append(f"   ✅ [{label}] Already settled")
            prediction_rows.append({
                "key":         p_key,
                "label":       label,
                "type":        ptype,
                "target":      target,
                "status":      "SETTLED",
                "settlement":  done_reason,
                "triggered":   True,
                "minute":      minute,
                "final_score": f"{ctx['home']['goals']}-{ctx['away']['goals']}",
            })
            continue

        if MATCH_VALIDATION_STATE[f_id].get(p_key) == "DONE":
            match_summary_lines.append(f"   ✅ [{label}] Previously settled")
            prediction_rows.append({
                "key":         p_key,
                "label":       label,
                "type":        ptype,
                "target":      target,
                "status":      "SETTLED",
                "settlement":  "Settled in an earlier cycle",
                "triggered":   True,
                "minute":      minute,
                "final_score": f"{ctx['home']['goals']}-{ctx['away']['goals']}",
            })
            continue

        # ── RUN BOTH ENGINES ────────────────────────────────────────────────
        forensic_state, n_note   = new_engine_forensic_investigation(ctx, pick)
        stats_state, o_note, engine_detail = old_engine_statistical_judge(ctx, pick)
        combined_state = combine_validation_states(forensic_state, stats_state)
        # The gate opens only when BOTH dimensions independently say SUPPORTED.
        # A single weak signal (the old STATS_1/3 case) can no longer pass.
        gate_open = combined_state == V_SUPPORTED
        new_ok = forensic_state == V_SUPPORTED
        old_ok = stats_state == V_SUPPORTED

        def _state_text():
            return (
                f"Forensic {STATE_GLYPH[forensic_state]}{forensic_state} | "
                f"Stats {STATE_GLYPH[stats_state]}{stats_state}"
            )

        # ── PHASE 1: 30-MINUTE HANDSHAKE ────────────────────────────────────
        if 30 <= minute < 45 and p_key not in MATCH_VALIDATION_STATE[f_id]:
            if gate_open:
                MATCH_VALIDATION_STATE[f_id][p_key] = {"pass_30": True}
                line = f"   🤝 [{label}] 30' HANDSHAKE PASSED — Saved to state"
                match_summary_lines.append(line)
                print(f"\n🤝 30-MINUTE HANDSHAKE | {name} | Min {minute}'")
                print(f"   Pick       : {label}")
                print(f"   Forensic   : {n_note}")
                print(f"   Stats      : {o_note}{engine_detail}")
                print(f"   Status     : ✅ Both engines passed — pick queued for 45' confirmation")
            else:
                line = f"   ⏳ [{label}] 30' check: {_state_text()}"
                match_summary_lines.append(line)

            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        "QUEUED" if gate_open else "MONITORING",
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

        # ── PHASE 2: 45-MINUTE SUPREME ALERT ────────────────────────────────
        elif minute >= 45 and MATCH_VALIDATION_STATE[f_id].get(p_key, {}).get("pass_30"):
            alert_key = f"{f_id}_{p_key}_ALERT"
            if gate_open and alert_key not in ALERT_HISTORY_CACHE:

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

                prediction_rows.append({
                    "key":           p_key,
                    "label":         label,
                    "type":          ptype,
                    "target":        target,
                    "status":        "TRIGGERED",
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

            elif alert_key in ALERT_HISTORY_CACHE:
                match_summary_lines.append(f"   🔥 [{label}] Alert already fired — monitoring")
            else:
                line = f"   ⏳ [{label}] 45'+ waiting: {_state_text()}"
                match_summary_lines.append(line)

            # A pick that already fired keeps a row on the board with its
            # trigger facts preserved, even on later cycles.
            if not prediction_rows or prediction_rows[-1].get("key") != p_key:
                prior = VALIDATED_ALERTS.get(alert_key, {})
                prediction_rows.append({
                    "key":              p_key,
                    "label":            label,
                    "type":             ptype,
                    "target":           target,
                    "status":           "TRIGGERED" if prior else "MONITORING",
                    "signal":           combined_state,
                    "forensic":         forensic_state,
                    "statistics":       stats_state,
                    "stats_label":      o_note,
                    "forensic_note":    n_note,
                    "triggered":        bool(prior),
                    "minute":           minute,
                    "trigger_minute":   prior.get("minute_triggered"),
                    "score_at_trigger": prior.get("score_at_trigger") or prior.get("scores"),
                    "final_score":      None,
                    "settlement":       None,
                })

        # ── PHASE 3: 60-70 FINAL STRIKE WINDOW ──────────────────────────────
        elif 60 <= minute <= 70 and pick['type'] in ["TO_SCORE", "OVER_2.5"]:
            if new_ok:
                line = f"   ⚡ [{label}] FINAL STRIKE WINDOW @ {minute}' — Gap still exploited"
                match_summary_lines.append(line)
                print(f"\n⚡ FINAL STRIKE @ {minute}' | {name} | {label} — Gap still being exploited")
            else:
                match_summary_lines.append(f"   💤 [{label}] Final strike window — gap closed")

            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        "STRIKE_WINDOW",
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

        # ── PRE-30 MONITORING ────────────────────────────────────────────────
        else:
            state_label = "Queued for 45'" if MATCH_VALIDATION_STATE[f_id].get(p_key, {}).get("pass_30") else "Monitoring"
            line = f"   👁️  [{label}] {state_label} @ {minute}' | {_state_text()}"
            match_summary_lines.append(line)

            prediction_rows.append({
                "key":           p_key,
                "label":         label,
                "type":          ptype,
                "target":        target,
                "status":        "QUEUED" if state_label.startswith("Queued") else "WAITING",
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

    # Collect this match's summary for the end-of-cycle board.
    # The entry is now a structured contract rather than a bag of text lines:
    # the frontend renders score / period / statistics / predictions directly
    # and no longer has to parse prose to show the live state.
    period_label = "FULL TIME" if minute >= 90 else (
        "SECOND HALF" if minute > 45 else "FIRST HALF"
    )
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
                "possession":        _stat_int(ctx['home']['stats'], 'ball-possession'),
                "shots_on_target":   _stat_int(ctx['home']['stats'], 'shots-on-target'),
                "dangerous_attacks": _stat_int(ctx['home']['stats'], 'dangerous-attacks'),
                "corners":           _stat_int(ctx['home']['stats'], 'corners'),
                "box_entries":       _stat_int(ctx['home']['stats'], 'box'),
            },
            "away": {
                "possession":        _stat_int(ctx['away']['stats'], 'ball-possession'),
                "shots_on_target":   _stat_int(ctx['away']['stats'], 'shots-on-target'),
                "dangerous_attacks": _stat_int(ctx['away']['stats'], 'dangerous-attacks'),
                "corners":           _stat_int(ctx['away']['stats'], 'corners'),
                "box_entries":       _stat_int(ctx['away']['stats'], 'box'),
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
                 "shots-on-target": 0, "corners": 0, "box": 0},
        "away": {"ball-possession": 0, "attacks": 0, "dangerous-attacks": 0,
                 "shots-on-target": 0, "corners": 0, "box": 0}
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
        if code in ["touches-in-opposition-box", "attacks-in-box"]:
            stats[side]["box"] += val

    scores = {"home": 0, "away": 0}
    for s in fixture.get("scores", []):
        if "CURRENT" in (s.get("description") or "").upper():
            g    = safe_get(s, "score", "goals", default=0)
            side = safe_get(s, "score", "participant", default="").lower()
            if side in scores: scores[side] = int(g)

    current_minute = 0
    for p in fixture.get("periods", []):
        # SportMonks in-play periods expose elapsed match time as `minutes`.
        m = (p.get("time", {}).get("minute") if isinstance(p.get("time"), dict) else None)
        m = m or p.get("minute") or p.get("minutes") or p.get("length")
        if m:
            try: current_minute = max(current_minute, int(m))
            except (TypeError, ValueError): pass
    if current_minute == 0 and fixture.get("events"):
        emins = [int(e.get("minute", 0)) for e in fixture["events"] if e.get("minute")]
        if emins: current_minute = max(emins)
    if current_minute == 0:
        current_minute = safe_get(fixture, "time", "minute", default=0)
    if current_minute == 0 and isinstance(fixture.get("state"), dict):
        current_minute = safe_get(fixture, "state", "minute", default=0)
    if current_minute == 0 and fixture.get("starting_at_timestamp"):
        now_ts  = int(datetime.now(timezone.utc).timestamp())
        elapsed = (now_ts - int(fixture["starting_at_timestamp"])) // 60
        if 0 < elapsed <= 50:    current_minute = elapsed
        elif 60 < elapsed <= 110: current_minute = elapsed - 15
        elif elapsed > 110:       current_minute = 90

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
        "events": fixture.get("events", [])
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
    """Render a retained standardized FT snapshot as a visible board row."""
    fid = str(std.get("fixture_id") or "")
    if not fid:
        return None
    minute = int(std.get("minute", 0) or 0) or 90
    score = std.get("ft_score") or "—"
    return {
        "name": f"{std.get('home_team') or 'Home'} vs {std.get('away_team') or 'Away'}",
        "id": fid,
        "fixture_id": fid,
        "minute": minute,
        "score": score,
        "score_parts": _score_parts(score),
        "lines": ["🏁 FINISHED RESULT RETAINED — settlement snapshot is available."],
        "status": "FINISHED",
        "period": _period_label(minute),
        "is_finished": True,
        "retained_finished": True,
        "updated_at": datetime.now().isoformat(),
        "statistics": _empty_statistics(),
        "predictions": [],
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
            if picks and not _fixture_is_scheduled(fx):
                ctx = extract_live_context(fx)
                process_triple_phase_audit(ctx, picks, cycle_log)
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
