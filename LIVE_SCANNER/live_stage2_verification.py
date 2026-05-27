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

PREDICTIONS_FILE = os.path.join(DATA_DIR, "live_predictions.json")
VALIDATED_OUTPUT_FILE = os.path.join(DATA_DIR, "validated_picks.json")  

CACHE_FILE = os.path.join(DATA_DIR, "squad_cache.json")
STATE_FILE = os.path.join(DATA_DIR, "validation_state.json")
ALERT_FILE = os.path.join(DATA_DIR, "alert_history.json")

# ==============================================================================
# CONFIGURATION & WORLD STANDARDS (100% UNTOUCHED)
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football/livescores/inplay"
HISTORY_URL = "https://api.sportmonks.com/v3/football"

MIN_DA_RATIO = 0.62
MIN_SOT_RATIO = 0.60
MIN_BOX_TOUCH_DIFF = 4
MIN_MOMENTUM_FACTOR = 1.30

SQUAD_CACHE = {}
MATCH_CONTEXT_CACHE = {} 
MATCH_VALIDATION_STATE = {} 
ALERT_HISTORY_CACHE = set()
VALIDATED_ALERTS = {}

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
        with open(CACHE_FILE, 'w') as f: json.dump(SQUAD_CACHE, f)
        with open(STATE_FILE, 'w') as f: json.dump(MATCH_VALIDATION_STATE, f)
        with open(ALERT_FILE, 'w') as f: json.dump(list(ALERT_HISTORY_CACHE), f)
        with open(VALIDATED_OUTPUT_FILE, 'w') as f: json.dump(VALIDATED_ALERTS, f)
    except Exception as e:
        print(f"Error saving memory: {e}", file=sys.stderr)

# ==============================================================================
# UTILITIES & ENGINE (100% UNTOUCHED LOGIC)
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
    except Exception as e:
        print(f"[ERR] Connection: {e}", file=sys.stderr)
    return {"data":[]}

def get_squad_data_standardized(team_id):
    tid_str = str(team_id)
    if tid_str in SQUAD_CACHE: return SQUAD_CACHE[tid_str]
    
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=150)).isoformat()
    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    url = f"{HISTORY_URL}/fixtures/between/{start_dt}/{end_dt}/{team_id}"
    resp = GET(url, params={"include": "lineups.details.type;lineups.player.position;scores;participants", "per_page": 25})
    
    squad_stats = {}
    for fx in resp.get("data",[]):
        hid = str(safe_get(fx, "participants", 0, "id"))
        is_home = (str(team_id) == hid)
        h_g = safe_get(fx, "scores", 0, "score", "goals", default=0)
        a_g = safe_get(fx, "scores", 1, "score", "goals", default=0)
        opp_goals = a_g if is_home else h_g

        for l in fx.get("lineups",[]):
            if str(l.get("team_id")) == str(team_id):
                pid = str(l.get("player_id"))
                if not l.get("player"): continue
                m_val = r_val = 0.0; c_val = -1.0
                for d in l.get("details",[]):
                    t_name = str(d.get('type', {}).get('name', '')).lower()
                    raw_val = d.get("data", {}).get("value") or d.get("value")
                    try: val = float(str(raw_val).replace('%', ''))
                    except: val = 0.0
                    if "minutes" in t_name: m_val = val
                    elif "rating" in t_name: r_val = val
                    elif "conceded" in t_name: c_val = val
                
                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                if c_val == -1.0: c_val = float(opp_goals)
                if pid not in squad_stats:
                    squad_stats[pid] = {"name": l["player"].get("display_name"), "pos": safe_get(l["player"], "position", "name"), "ratings":[], "apps": 0, "mins": 0, "conceded": 0, "clean_sheets": 0}
                squad_stats[pid]["mins"] += m_val
                squad_stats[pid]["apps"] += 1
                if r_val > 0: squad_stats[pid]["ratings"].append(r_val)
                if m_val > 0:
                    squad_stats[pid]["conceded"] += c_val
                    if c_val == 0: squad_stats[pid]["clean_sheets"] += 1

    processed = {}
    for pid, d in squad_stats.items():
        avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
        worth = (d["apps"] * 5000) + (d["mins"] * avg_r)
        c_p90 = (d["conceded"] / d["mins"]) * 90 if d["mins"] > 0 else 0.0
        vuln = (c_p90 * 0.6) + ((1 - (d["clean_sheets"]/d["apps"] if d["apps"]>0 else 0)) * 2)
        processed[pid] = {"id": pid, "name": d["name"], "pos": d["pos"], "worth": worth, "vuln": vuln}
        
    SQUAD_CACHE[tid_str] = processed
    return processed

def new_engine_forensic_investigation(ctx, pick):
    target_side = "home" if pick.get('target_loc') == "home" else "away"
    opponent_side = "away" if target_side == "home" else "home"
    has_red = ctx["impact"][target_side]["reds"] > 0
    gk_liability = ctx["impact"][target_side]["gk_risk"]
    personnel_gap = ctx["impact"][target_side]["key_sub_off"] >= 1
    opp_stats = ctx[opponent_side]['stats']
    opp_sot, opp_da, opp_box = int(opp_stats.get('shots-on-target', 0)), int(opp_stats.get('dangerous-attacks', 0)), int(opp_stats.get('box', 0))
    
    is_exploited = False; investigation_note = "NO GAP"

    if has_red or gk_liability:
        if opp_sot >= 2 or opp_da >= 20 or opp_box >= 5:
            is_exploited = True; investigation_note = "EXPLOITED (Opponent utilizing structural gap)"
        else:
            is_exploited = False; investigation_note = "PROTECTED (Team covering the structural gap)"
    elif personnel_gap:
        if opp_da >= 15 or opp_sot >= 1:
            is_exploited = True; investigation_note = "WEAKENED (Substitution impact detected)"
        else:
            is_exploited = True; investigation_note = "STABLE (Personnel change managed)"
    else:
        is_exploited = True; investigation_note = "MAINTAINED (No structural fracture detected)"

    return is_exploited, investigation_note

def engine_1_rule_validator(data, pick):
    h_s, a_s = data['home']['stats'], data['away']['stats']
    target = "home" if pick.get('target_loc') == "home" else "away"
    exp = h_s if target == "home" else a_s
    opp = a_s if target == "home" else h_s
    ptype = str(pick.get('type', '')).upper()
    def get_s(d, k): return int(d.get(k, 0))
    
    if "OVER" in ptype or "GG" in ptype: return (get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')) >= 3
    if "UNDER" in ptype: return (get_s(h_s, 'shots-on-target') + get_s(a_s, 'shots-on-target')) <= 1
    if "WIN" in ptype or "SCORE" in ptype: return get_s(exp, 'shots-on-target') >= 1 and get_s(exp, 'dangerous-attacks') > get_s(opp, 'dangerous-attacks')
    return False

def engine_2_structural_stacker(data, target_loc):
    if target_loc == "match": target_loc = "home"
    exp, opp_loc = data[target_loc]['stats'], ("away" if target_loc == "home" else "home")
    opp = data[opp_loc]['stats']
    def get_s(d, k): return int(d.get(k, 0))
    sig = 0
    total_da = get_s(exp, 'dangerous-attacks') + get_s(opp, 'dangerous-attacks')
    if (get_s(exp, 'dangerous-attacks') / total_da if total_da > 0 else 0) >= MIN_DA_RATIO: sig += 1
    total_sot = get_s(exp, 'shots-on-target') + get_s(opp, 'shots-on-target')
    if (get_s(exp, 'shots-on-target') / total_sot if total_sot > 0 else 0) >= MIN_SOT_RATIO: sig += 1
    if int(exp.get('box', 0)) >= int(opp.get('box', 0)) + MIN_BOX_TOUCH_DIFF: sig += 1
    if get_s(exp, 'corners') >= get_s(opp, 'corners') + 2: sig += 1
    return sig >= 2

def engine_3_momentum_escalator(data, target_id):
    now = data['minute']
    if not target_id or now < 15: return False
    recent = 0
    for e in data.get('events',[]):
        if str(e.get("participant_id")) == str(target_id):
            if (e.get("minute") or 0) > (now - 12):
                if safe_get(e, "type", "code") in["corner", "shot-on-target", "goal"]: recent += 1
    return recent >= 2

def old_engine_statistical_judge(ctx, pick):
    passed =[engine_1_rule_validator(ctx, pick), engine_2_structural_stacker(ctx, pick.get('target_loc')), engine_3_momentum_escalator(ctx, pick.get('target_id'))].count(True)
    return passed >= 2, f"STATS_{passed}/3"

def check_if_done(ctx, pick):
    h_g, a_g = ctx["home"]["goals"], ctx["away"]["goals"]
    h_c, a_c = int(ctx["home"]["stats"].get("corners", 0)), int(ctx["away"]["stats"].get("corners", 0))
    ptype = str(pick.get('type', '')).upper()
    side = pick.get('target_loc')
    if "GG" in ptype and h_g > 0 and a_g > 0: return True
    if "TO_SCORE" in ptype:
        if side == "home" and h_g > 0: return True
        if side == "away" and a_g > 0: return True
    if "OVER_2.5" in ptype and (h_g + a_g) >= 3: return True
    if "OVER" in ptype and "CORNER" in ptype and (h_c + a_c) >= 10: return True
    return False

def process_triple_phase_audit(ctx, picks):
    global VALIDATED_ALERTS
    f_id = ctx["id"]
    minute = ctx["minute"]
    if f_id not in MATCH_VALIDATION_STATE: MATCH_VALIDATION_STATE[f_id] = {}

    for idx, pick in enumerate(picks):
        p_key = f"{idx}_{pick['type']}"
        if check_if_done(ctx, pick):
            MATCH_VALIDATION_STATE[f_id][p_key] = "DONE"
            continue
        if MATCH_VALIDATION_STATE[f_id].get(p_key) == "DONE": continue

        if 30 <= minute < 45 and p_key not in MATCH_VALIDATION_STATE[f_id]:
            new_ok, _ = new_engine_forensic_investigation(ctx, pick)
            old_ok, _ = old_engine_statistical_judge(ctx, pick)
            if new_ok and old_ok:
                MATCH_VALIDATION_STATE[f_id][p_key] = {"pass_30": True}
                print(f"[30' VALIDATED] {ctx['name']} > {pick['type']} saved to temporary state.")

        if minute >= 45 and MATCH_VALIDATION_STATE[f_id].get(p_key, {}).get("pass_30"):
            new_ok, n_note = new_engine_forensic_investigation(ctx, pick)
            old_ok, o_note = old_engine_statistical_judge(ctx, pick)
            
            alert_key = f"{f_id}_{p_key}_ALERT"
            if new_ok and old_ok and alert_key not in ALERT_HISTORY_CACHE:
                print(f"\n🔥[SUPREME ALERT @ 45'] {ctx['name']}")
                print(f"✅ Prediction: {pick['type']} Verified by Forensic Detective & Statistical Engine.")
                print(f"🕵️ Forensic: {n_note} | 📊 Stats: {o_note}")
                
                ALERT_HISTORY_CACHE.add(alert_key)
                VALIDATED_ALERTS[alert_key] = {
                    "fixture_id": f_id, "match_name": ctx['name'], "prediction_type": pick['type'], "forensic_note": n_note, "stats_note": o_note, "minute_triggered": minute
                }

        if 60 <= minute <= 70 and pick['type'] in["TO_SCORE", "OVER_2.5"]:
            new_ok, _ = new_engine_forensic_investigation(ctx, pick)
            if new_ok: print(f"[60' FINAL STRIKE] {ctx['name']} > {pick['type']} Gaps still being exploited.")

# ==============================================================================
# 🚨 SURGICAL UPGRADE: BULLETPROOF ID MAPPING & STATS EXTRACTOR
# ==============================================================================
def extract_live_context(fixture):
    f_id = str(fixture["id"])
    
    # 1. BULLETPROOF ID MAPPING
    h_id, a_id = None, None
    h_name, a_name = "Unknown", "Unknown"

    for p in fixture.get("participants",[]):
        loc = p.get("meta", {}).get("location")
        if loc == "home":
            h_id = str(p.get("id"))
            h_name = p.get("name")
        elif loc == "away":
            a_id = str(p.get("id"))
            a_name = p.get("name")
            
    teams = {"home": {"id": h_id, "name": h_name}, "away": {"id": a_id, "name": a_name}}

    # 2. BULLETPROOF STATS EXTRACTION (Mapped by participant_id)
    stats = {"home": {}, "away": {}}
    expected_metrics =["ball-possession", "attacks", "dangerous-attacks", "shots-on-target", "shots-off-target", "corners", "fouls", "passes", "touches-in-opposition-box", "attacks-in-box"]
    
    # Prebuild to force defaults
    for metric in expected_metrics:
        stats["home"][metric] = 0.0
        stats["away"][metric] = 0.0
    stats["home"]["box"] = 0.0
    stats["away"]["box"] = 0.0

    for s in fixture.get("statistics",[]):
        pid = str(s.get("participant_id"))
        code = str(s.get("type", {}).get("code", "")).lower()
        val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value", 0)
        try: val = float(val)
        except: val = 0.0

        if pid == h_id:
            stats["home"][code] = val
            if code in ["touches-in-opposition-box", "attacks-in-box"]:
                stats["home"]["box"] += val
        elif pid == a_id:
            stats["away"][code] = val
            if code in["touches-in-opposition-box", "attacks-in-box"]:
                stats["away"]["box"] += val

    # 3. SCORES
    scores = {"home": 0, "away": 0}
    for s in fixture.get("scores",[]):
        if "CURRENT" in (s.get("description") or "").upper():
            goals = safe_get(s, "score", "goals", default=0)
            side = safe_get(s, "score", "participant", default="").lower()
            if side in scores: scores[side] = int(goals)

    # 4. QUADRUPLE-LAYER MINUTE EXTRACTOR
    current_minute = 0

    for p in fixture.get("periods",[]):
        m = p.get("time", {}).get("minute") or p.get("minute") or p.get("length")
        if m and int(m) > current_minute:
            current_minute = int(m)

    if current_minute == 0 and fixture.get("events"):
        emins =[int(e.get("minute", 0)) for e in fixture["events"] if e.get("minute")]
        if emins: current_minute = max(emins)

    if current_minute == 0:
        current_minute = safe_get(fixture, "time", "minute", default=0)
    if current_minute == 0 and isinstance(fixture.get("state"), dict):
        current_minute = safe_get(fixture, "state", "minute", default=0)

    if current_minute == 0 and fixture.get("starting_at_timestamp"):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        elapsed = (now_ts - int(fixture["starting_at_timestamp"])) // 60
        if 0 < elapsed <= 50:
            current_minute = elapsed
        elif 60 < elapsed <= 110:
            current_minute = elapsed - 15
        elif elapsed > 110:
            current_minute = 90

    # 5. CONTEXT CACHE & IMPACT
    if f_id not in MATCH_CONTEXT_CACHE:
        h_sq = get_squad_data_standardized(teams["home"]["id"])
        a_sq = get_squad_data_standardized(teams["away"]["id"])
        def get_k(sq):
            l = list(sq.values()); gk = sorted([p for p in l if p['pos'] == "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:1]
            out = sorted([p for p in l if p['pos'] != "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:10]
            return {p['id'] for p in (gk + out)}
        MATCH_CONTEXT_CACHE[f_id] = {"h_sq": h_sq, "a_sq": a_sq, "h_key": get_k(h_sq), "a_key": get_k(a_sq)}

    cache = MATCH_CONTEXT_CACHE[f_id]
    impact = {"home": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0}, "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0}}
    
    for e in fixture.get("events",[]):
        code = safe_get(e, "type", "code")
        loc = "home" if str(e.get("participant_id")) == teams["home"]["id"] else "away"
        if code == "red-card": impact[loc]["reds"] += 1
        if code == "substitution":
            p_off = str(e.get("player_id"))
            if p_off in cache[f"{loc[0]}_key"]:
                impact[loc]["key_sub_off"] += 1
                impact[loc]["worth_lost"] += cache[f"{loc}_sq"].get(p_off, {"worth": 0})["worth"]
                
    return {
        "id": f_id, 
        "name": fixture.get("name"), 
        "minute": current_minute,
        "home": {"goals": scores["home"], "stats": stats["home"]}, 
        "away": {"goals": scores["away"], "stats": stats["away"]}, 
        "impact": impact, 
        "events": fixture.get("events",[])
    }

# ==============================================================================
# 📦 MAIN ENGINE EXECUTION (WRAPPED FOR ARCHITECTURE)
# ==============================================================================
def run_live_validator_engine():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}

    load_memory()
    
    try:
        with open(PREDICTIONS_FILE, 'r') as f: FEED_A = json.load(f)
    except: 
        FEED_A = {}
        
    # 🚨 SURGICAL UPGRADE: Added 'periods' to ensure API delivers the clock!
    live_data = GET(f"{BASE_URL}?include=participants;scores;statistics.type;events.type;state;periods")
    
    live_matches_count = len(live_data.get("data",[]))
    tracked_count = 0
    
    for fx in live_data.get("data",[]):
        f_id = str(fx.get("id"))
        if f_id in FEED_A:
            tracked_count += 1
            ctx = extract_live_context(fx)
            process_triple_phase_audit(ctx, FEED_A[f_id])
            
    # 🟢 THE HEARTBEAT INJECTION 🟢
    current_time = datetime.now().strftime("%H:%M:%S")
    print(f"[{current_time}] 🛡️ Validator Engine Active | Tracking {tracked_count}/{len(FEED_A)} targets across {live_matches_count} global live matches.")
            
    save_memory()
    return VALIDATED_ALERTS

if __name__ == "__main__":
    print("--- ULTIMATE FORENSIC DETECTIVE CODE B STANDBY (DATA ARCHITECTURE LOADED) ---")
    while True:
        run_live_validator_engine()
        time.sleep(40)