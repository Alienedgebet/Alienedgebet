import os
import sys
import time
import json
import random
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

PREDICTIONS_FILE     = os.path.join(DATA_DIR, "live_predictions.json")
VALIDATED_OUTPUT_FILE = os.path.join(DATA_DIR, "validated_picks.json")
CACHE_FILE           = os.path.join(DATA_DIR, "squad_cache.json")
STATE_FILE           = os.path.join(DATA_DIR, "validation_state.json")
ALERT_FILE           = os.path.join(DATA_DIR, "alert_history.json")

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

def GET(url, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_TOKEN)
    try:
        r = requests.get(url, params=params, timeout=25)
        if r.status_code == 200: return r.json()
        if r.status_code == 429:
            time.sleep(5)
            return GET(url, params)
    except Exception as e:
        print(f"[ERR] Connection: {e}", file=sys.stderr)
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
    if target_loc == "match": target_loc = "home"
    opp_loc = "away" if target_loc == "home" else "home"
    exp = data[target_loc]['stats']
    opp = data[opp_loc]['stats']

    def get_s(d, k): return int(d.get(k, 0))

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
            return True,  "EXPLOITED (Opponent utilizing structural gap)"
        else:
            return False, "PROTECTED (Team covering the structural gap)"
    elif personnel_gap:
        if opp_da >= 8 or opp_sot >= 1:   # was da≥15, sot≥1
            return True,  "WEAKENED (Substitution impact detected)"
        else:
            return True,  "STABLE (Personnel change managed)"
    else:
        return True, "MAINTAINED (No structural fracture detected)"

# ==============================================================================
# COMBINED STATISTICAL JUDGE
# ==============================================================================
def old_engine_statistical_judge(ctx, pick):
    e1_pass, e1_note = engine_1_rule_validator(ctx, pick)
    e2_pass, e2_note = engine_2_structural_stacker(ctx, pick.get('target_loc'))
    e3_pass, e3_note = engine_3_momentum_escalator(ctx, pick.get('target_id'))

    passed_count = sum([e1_pass, e2_pass, e3_pass])
    # Lowered from 2/3 to 1/3 so partial evidence still surfaces
    overall_pass = passed_count >= 1

    detail = (
        f"\n         Engine 1 (Rule)       : {'✅ PASS' if e1_pass else '❌ FAIL'} → {e1_note}"
        f"\n         Engine 2 (Structure)  : {'✅ PASS' if e2_pass else '❌ FAIL'} → {e2_note}"
        f"\n         Engine 3 (Momentum)   : {'✅ PASS' if e3_pass else '❌ FAIL'} → {e3_note}"
        f"\n         Combined              : {passed_count}/3 engines passed"
    )
    return overall_pass, f"STATS_{passed_count}/3", detail

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

    if "GG"      in ptype and h_g > 0 and a_g > 0:              return True, "GG settled ✅"
    if "TO_SCORE" in ptype:
        if side == "home" and h_g > 0:                           return True, "Home scored ✅"
        if side == "away" and a_g > 0:                           return True, "Away scored ✅"
    if "OVER_2.5" in ptype and (h_g + a_g) >= 3:                return True, "Over 2.5 settled ✅"
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

    for idx, pick in enumerate(picks):
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
            continue

        if MATCH_VALIDATION_STATE[f_id].get(p_key) == "DONE":
            match_summary_lines.append(f"   ✅ [{label}] Previously settled")
            continue

        # ── RUN BOTH ENGINES ────────────────────────────────────────────────
        new_ok, n_note   = new_engine_forensic_investigation(ctx, pick)
        old_ok, o_note, engine_detail = old_engine_statistical_judge(ctx, pick)

        # ── PHASE 1: 30-MINUTE HANDSHAKE ────────────────────────────────────
        if 30 <= minute < 45 and p_key not in MATCH_VALIDATION_STATE[f_id]:
            if new_ok and old_ok:
                MATCH_VALIDATION_STATE[f_id][p_key] = {"pass_30": True}
                line = f"   🤝 [{label}] 30' HANDSHAKE PASSED — Saved to state"
                match_summary_lines.append(line)
                print(f"\n🤝 30-MINUTE HANDSHAKE | {name} | Min {minute}'")
                print(f"   Pick       : {label}")
                print(f"   Forensic   : {n_note}")
                print(f"   Stats      : {o_note}{engine_detail}")
                print(f"   Status     : ✅ Both engines passed — pick queued for 45' confirmation")
            else:
                line = (
                    f"   ⏳ [{label}] 30' check: "
                    f"Forensic {'✅' if new_ok else '❌'} | Stats {'✅' if old_ok else '❌'}"
                )
                match_summary_lines.append(line)

        # ── PHASE 2: 45-MINUTE SUPREME ALERT ────────────────────────────────
        elif minute >= 45 and MATCH_VALIDATION_STATE[f_id].get(p_key, {}).get("pass_30"):
            alert_key = f"{f_id}_{p_key}_ALERT"
            if new_ok and old_ok and alert_key not in ALERT_HISTORY_CACHE:

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
                    "minute_triggered":  minute,
                    "scores":            f"{ctx['home']['goals']}-{ctx['away']['goals']}",
                    "timestamp":         datetime.now().isoformat()
                }

                line = f"   🔥 [{label}] SUPREME ALERT FIRED @ {minute}'"
                match_summary_lines.append(line)

            elif alert_key in ALERT_HISTORY_CACHE:
                match_summary_lines.append(f"   🔥 [{label}] Alert already fired — monitoring")
            else:
                line = (
                    f"   ⏳ [{label}] 45'+ waiting: "
                    f"Forensic {'✅' if new_ok else '❌'} | Stats {'✅' if old_ok else '❌'}"
                )
                match_summary_lines.append(line)

        # ── PHASE 3: 60-70 FINAL STRIKE WINDOW ──────────────────────────────
        elif 60 <= minute <= 70 and pick['type'] in ["TO_SCORE", "OVER_2.5"]:
            if new_ok:
                line = f"   ⚡ [{label}] FINAL STRIKE WINDOW @ {minute}' — Gap still exploited"
                match_summary_lines.append(line)
                print(f"\n⚡ FINAL STRIKE @ {minute}' | {name} | {label} — Gap still being exploited")
            else:
                match_summary_lines.append(f"   💤 [{label}] Final strike window — gap closed")

        # ── PRE-30 MONITORING ────────────────────────────────────────────────
        else:
            state_label = "Queued for 45'" if MATCH_VALIDATION_STATE[f_id].get(p_key, {}).get("pass_30") else "Monitoring"
            line = (
                f"   👁️  [{label}] {state_label} @ {minute}' | "
                f"Forensic {'✅' if new_ok else '❌'} | Stats {'✅' if old_ok else '❌'}"
            )
            match_summary_lines.append(line)

    # Collect this match's summary for the end-of-cycle board
    cycle_log.append({
        "name":   name,
        "minute": minute,
        "id":     f_id,
        "lines":  match_summary_lines,
        "score":  f"{ctx['home']['goals']}-{ctx['away']['goals']}"
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
        m = p.get("time", {}).get("minute") or p.get("minute") or p.get("length")
        if m and int(m) > current_minute: current_minute = int(m)
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
        loc  = "home" if str(e.get("participant_id")) == h_id else "away"
        if code == "red-card":    impact[loc]["reds"] += 1
        if code == "substitution":
            p_off = str(e.get("player_id"))
            if p_off in cache[f"{loc[0]}_key"]:
                impact[loc]["key_sub_off"] += 1
                impact[loc]["worth_lost"]  += cache[f"{loc}_sq"].get(p_off, {"worth": 0})["worth"]

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
def run_live_validator_engine():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}

    load_memory()

    try:
        with open(PREDICTIONS_FILE, 'r') as f: FEED_A = json.load(f)
    except:
        FEED_A = {}

    cycle_number  = 0
    print(f"\n{'─'*80}")
    print(f"  🛡️  LIVE VALIDATOR ENGINE ONLINE")
    print(f"  Tracking {len(FEED_A)} pre-match targets")
    print(f"  Thresholds: DA≥{MIN_DA_RATIO:.0%} | SOT≥{MIN_SOT_RATIO:.0%} | Box diff≥{MIN_BOX_TOUCH_DIFF}")
    print(f"{'─'*80}\n")

    while True:
        cycle_number += 1
        cycle_log = []

        try:
            from backend.live_cache import get_live_scores_cached
        except ImportError:
            from live_cache import get_live_scores_cached

        live_matches = get_live_scores_cached()
        tracked_count = 0
    

        for fx in live_matches:
            f_id = str(fx.get("id"))
            if f_id in FEED_A:
                tracked_count += 1
                try:
                    ctx = extract_live_context(fx)
                    process_triple_phase_audit(ctx, FEED_A[f_id], cycle_log)
                except Exception as e:
                    print(f"  ⚠️  Error processing {f_id}: {e}")

        # ── END-OF-CYCLE BOARD ───────────────────────────────────────────────
        print_cycle_board(cycle_log, len(live_matches), tracked_count, cycle_number)

        save_memory()
        time.sleep(40)


if __name__ == "__main__":
    print("--- ALIENEDGE LIVE VALIDATOR ENGINE STANDBY ---")
    run_live_validator_engine()
