import os
import sys
import time
import random
import json
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
CACHE_FILE = os.path.join(DATA_DIR, "squad_cache.json")

# ==============================================================================
# CONFIGURATION & WORLD STANDARDS (100% UNTOUCHED)
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football"

MARKET_ID_1X2  = 1
MARKET_ID_OU   = 12

RATING_ID = 118
MINUTES_ID = 119
STAR_FACTOR_ID = 211
CORNER_TAKEN_ID = 34
CROSSES_ID = 98

SQUAD_CACHE = {}

PERSONNEL_WEIGHTS = {
    "Goalkeeper": 50.0, "Defender": 9.0, "Midfielder": 4.5, "Attacker": 1.5, "Unknown": 3.0
}

# ==============================================================================
# PERSISTENT CACHE MANAGERS
# ==============================================================================
def load_cache():
    global SQUAD_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                SQUAD_CACHE = json.load(f)
            print(f"--- MEMORY RESTORED: {len(SQUAD_CACHE)} teams loaded from squad_cache.json ---")
        except:
            SQUAD_CACHE = {}
    else:
        SQUAD_CACHE = {}

def save_cache():
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(SQUAD_CACHE, f)
    except Exception as e:
        print(f"Error saving cache: {e}")

# ==============================================================================
# UTILITIES & ENGINE ENGINE (100% UNTOUCHED)
# ==============================================================================
def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur

def GET(path, params=None, max_retries=3):
    if params is None: params = {}
    params.setdefault("api_token", API_TOKEN)
    url = f"{BASE_URL}{path}"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200: return r.json()
            if r.status_code == 429:
                time.sleep((2 ** attempt) + random.random()); continue
            return {"data":[]}
        except:
            time.sleep((2 ** attempt) + random.random())
    return {"data":[]}

def normalize_odd_value(value):
    try:
        val = float(value)
        if 1.01 <= val <= 30.0: return val
        if val > 100: return (val / 100) + 1
        if val < -100: return (100 / abs(val)) + 1
        return None
    except: return None

def get_fixture_odds_safe(fixture_id):
    raw_data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    odds_list = raw_data.get("data",[])
    result = {"home_win": None, "away_win": None, "o25": None}
    for o in odds_list:
        if o.get("market_id") == MARKET_ID_1X2:
            label = str(o.get("label", "")).lower()
            val = normalize_odd_value(o.get("value"))
            if not val: continue
            if "1" in label or "home" in label: result["home_win"] = val
            elif "2" in label or "away" in label: result["away_win"] = val
            
    for o in odds_list:
        mid, desc = o.get("market_id"), str(o.get("market_description", "")).lower()
        if not desc: desc = str(o.get("name", "")).lower()
        if mid == MARKET_ID_OU or (("goals" in desc or "over/under" in desc) and not any(x in desc for x in["corner", "card", "asian", "handicap"])):
            label, total = str(o.get("label", "")).lower(), str(o.get("total", ""))
            if "over" in label and "2.5" in total:
                val = normalize_odd_value(o.get("value"))
                if val: result["o25"] = val
    return result

def calculate_gk_vulnerability_pro(master_gk, today_ids, all_lineup_data, squad_map):
    starting_gk_id = None
    for pid in today_ids:
        if squad_map.get(pid, {}).get('pos') == "Goalkeeper":
            starting_gk_id = pid; break

    if not starting_gk_id: return 85.0, True, "DEBUT/UNKNOWN GK (Max Risk)"

    starter = squad_map[starting_gk_id]
    on_bench = False
    if master_gk and master_gk['id'] != starting_gk_id:
        on_bench = any(str(l.get('player_id')) == master_gk['id'] for l in all_lineup_data if l.get('type_id') == 12)

    apps, c_p90, vuln = starter.get('apps', 0), starter.get('c_p90', 0.0), starter.get('vuln', 0.0)
    is_liability = False
    status_note = ""
    vuln_score = 0.0

    if apps == 0:
        is_liability = True; status_note = "NO DATA (High Risk)"; vuln_score = 85.0
    elif apps < 3 and c_p90 >= 1.50:
        is_liability = True; status_note = f"Small Sample Leak ({c_p90:.1f} per 90)"; vuln_score = min(100.0, 50 + (vuln * 10))
    elif c_p90 > 1.50 or vuln > 2.50:
        is_liability = True; status_note = f"Proven Liability ({c_p90:.1f} per 90)"; vuln_score = min(100.0, 50 + (vuln * 10))
    else:
        is_liability = False; status_note = f"Solid Form ({c_p90:.1f} per 90)"; vuln_score = max(0.0, vuln * 10)

    if on_bench and is_liability:
        status_note = "🚨 DOWNGRADE: " + status_note
        vuln_score = min(100.0, vuln_score + 15.0)

    return vuln_score, is_liability, status_note

def get_squad_data_standardized(team_id):
    tid_str = str(team_id)
    if tid_str in SQUAD_CACHE: return SQUAD_CACHE[tid_str]
    now_ts = datetime.now(timezone.utc).timestamp()
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=150)).isoformat()
    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={
        "include": "lineups.details.type;lineups.player.position;lineups.player.detailedPosition;scores;participants",
        "filter": "fixtureStates:5", "per_page": 25
    })

    squad_stats = {}
    for fx in resp.get("data",[]):
        raw_at = fx['starting_at'].replace('Z', '+00:00')
        fx_date = datetime.fromisoformat(raw_at).astimezone(timezone.utc)
        days_ago = int((now_ts - fx_date.timestamp()) / 86400)
        weight = 1.0 if days_ago <= 30 else (0.4 if days_ago <= 75 else 0.1)
        
        hid, aid = None, None
        for pt in fx.get("participants",[]):
            loc = pt.get("meta", {}).get("location")
            if loc == "home": hid = str(pt.get("id"))
            if loc == "away": aid = str(pt.get("id"))

        h_g, a_g = 0, 0
        for entry in fx.get("scores",[]):
            s_obj = entry.get("score") or entry
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
            if g is not None:
                try: val = int(g)
                except: continue
                pid = str(entry.get("participant_id"))
                part_str = str(s_obj.get("participant") or entry.get("participant")).lower()
                if pid == hid or part_str == "home": h_g = max(h_g, val)
                elif pid == aid or part_str == "away": a_g = max(a_g, val)
                    
        is_home = (str(team_id) == hid)
        opp_goals = a_g if is_home else h_g

        for l in fx.get("lineups",[]):
            if str(l.get("team_id")) == str(team_id):
                pid = str(l.get("player_id"))
                if not l.get("player"): continue
                m_val = r_val = 0.0; c_val = -1.0
                
                for d in l.get("details",[]):
                    type_name = str(d.get('type', {}).get('name', '')).lower()
                    val_data = d.get("data", {}).get("value") if isinstance(d.get("data"), dict) else None
                    raw_val = val_data if val_data is not None else d.get("value")
                    try:
                        if isinstance(raw_val, dict): val = float(list(raw_val.values())[0])
                        else: val = float(str(raw_val).replace('%', '').strip())
                    except: continue

                    if "minutes" in type_name: m_val = val
                    elif "rating" in type_name: r_val = val
                    elif "conceded" in type_name: c_val = val
                
                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90.0
                if c_val == -1.0: c_val = float(opp_goals)

                if pid not in squad_stats:
                    p_obj = l["player"]
                    pos_name = safe_get(p_obj, "position", "name", default="Unknown")
                    squad_stats[pid] = {
                        "name": p_obj.get("display_name", "Unknown"), "pos": pos_name, 
                        "det_pos": safe_get(p_obj, "detailedPosition", "name", default=pos_name),
                        "weighted_mins": 0, "monthly_apps": 0, "ratings":[], "apps": 0, "mins": 0, "conceded": 0, "clean_sheets": 0
                    }
                    
                if days_ago <= 30: squad_stats[pid]["monthly_apps"] += 1
                squad_stats[pid]["weighted_mins"] += (m_val * weight)
                squad_stats[pid]["mins"] += m_val
                squad_stats[pid]["apps"] += 1
                if r_val > 0: squad_stats[pid]["ratings"].append(r_val)
                if m_val > 0:
                    squad_stats[pid]["conceded"] += c_val
                    if c_val == 0: squad_stats[pid]["clean_sheets"] += 1

    processed = {}
    for pid, d in squad_stats.items():
        avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
        worth = (d["monthly_apps"] * 8000) + (d["weighted_mins"] * avg_r)
        c_p90 = (d["conceded"] / d["mins"]) * 90 if d["mins"] > 0 else 0.0
        c_ratio = d["clean_sheets"] / d["apps"] if d["apps"] > 0 else 0.0
        vuln = (c_p90 * 0.6) + ((1 - c_ratio) * 2) + ((6.5 - avg_r) * 0.4)
        processed[pid] = {"id": pid, "name": d["name"], "pos": d["pos"], "det_pos": d["det_pos"], "worth": worth, "avg_rating": avg_r, "apps": d["apps"], "mins": d["mins"], "c_p90": c_p90, "vuln": vuln}
        
    SQUAD_CACHE[tid_str] = processed
    return processed

# ==============================================================================
# 📦 MAIN EXECUTION (WRAPPED FOR ARCHITECTURE)
# ==============================================================================
def run_prematch_engine():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}

    load_cache()
    FINAL_PREDICTIONS_FEED = {} 
    
    now_aware = datetime.now(timezone.utc)
    dates_to_check =[
        (now_aware - timedelta(days=1)).strftime("%Y-%m-%d"),
        now_aware.strftime("%Y-%m-%d")
    ]

    print(f"\nMASTER ENGINE A: STRATEGIC AUDIT - {now_aware.strftime('%Y-%m-%d %H:%M')} UTC\n")
    processed_fixtures = set()

    for target_date in dates_to_check:
        current_page = 1; has_more_pages = True
        while has_more_pages:
            resp = GET(f"/fixtures/date/{target_date}", params={"include": "participants;lineups.details.type;lineups.player.position;lineups.player.detailedPosition", "page": current_page})
            fixtures = resp.get("data",[])
            if not fixtures: break

            for fx in fixtures:
                f_id = str(fx.get("id"))
                if f_id in processed_fixtures: continue
                
                raw_start = fx['starting_at'].replace('Z', '+00:00')
                start_dt = datetime.fromisoformat(raw_start).astimezone(timezone.utc)
                time_diff_mins = (start_dt - now_aware).total_seconds() / 60
                
                state_id = fx.get('state_id')
                is_live = state_id in[2, 3, 4, 6, 7, 12, 13, 21, 22]
                is_upcoming = (0 <= time_diff_mins <= 65)

                if not (is_live or is_upcoming): continue
                
                lineups_raw = fx.get("lineups", [])
                official_lineups =[l for l in lineups_raw if l.get('type_id') == 11]
                if not official_lineups: continue 

                processed_fixtures.add(f_id)
                status_text = "LIVE" if is_live else f"Starts in {int(time_diff_mins)}m"
                print(f"\n{'='*120}\nMATCH: {fx['name']} | KICKOFF: {start_dt.strftime('%H:%M')} UTC ({status_text})\n{'='*120}")
                
                odds_data = get_fixture_odds_safe(f_id)
                print(f"ODDS SCAN > Home: {odds_data['home_win']} | Away: {odds_data['away_win']} | O2.5: {odds_data['o25']}")

                m_stats =[]
                for team in fx.get("participants",[]):
                    tid, loc = team['id'], team.get('meta', {}).get('location')
                    squad_map = get_squad_data_standardized(tid)
                    worth_list = list(squad_map.values())
                    
                    gks = sorted([p for p in worth_list if p['pos'] == "Goalkeeper"], key=lambda x: x['worth'], reverse=True)
                    master_gk = gks[0] if gks else None
                    key_11 = (gks[:1] if gks else[]) + sorted([p for p in worth_list if p['pos'] != "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:10]
                    today_team_ids =[str(l.get('player_id')) for l in official_lineups if str(l.get('team_id')) == str(tid)]

                    gk_p, gk_m, gk_n = calculate_gk_vulnerability_pro(master_gk, today_team_ids, lineups_raw, squad_map)
                    
                    print(f"\n--- {team['name'].upper()} ({loc.upper()}) ---\n{'Player Name':<28} | {'Pos':<12} | {'Apps':<4} | {'Mins':<6} | {'Rating':<6} | {'Status'}\n" + "-"*115)
                    km_w = tot_w = m_c = w_l = def_miss = mid_miss = att_miss = 0; l_w_m = r_w_m = False
                    
                    for p in key_11:
                        base_w = PERSONNEL_WEIGHTS.get(p['pos'], 3.0); tot_w += base_w
                        is_playing = p['id'] in today_team_ids
                        status = "STARTING"
                        
                        if is_playing and p['pos'] == "Goalkeeper": status = gk_n
                        if not is_playing:
                            if p['pos'] == "Goalkeeper":
                                if gk_m: km_w += gk_p; status = f"MISSING ({gk_n})"
                                else: km_w += 0.0; status = f"MISSING (Covered by: {gk_n})"
                            else:
                                km_w += base_w; status = "MISSING !!!"
                                
                            m_c += 1; w_l += p['worth']
                            if p['pos'] == "Defender": def_miss += 1
                            elif p['pos'] == "Midfielder": mid_miss += 1
                            elif p['pos'] == "Attacker": att_miss += 1
                            if p['det_pos'] in["Left Wing", "Left Midfielder", "Left Winger"]: l_w_m = True
                            if p['det_pos'] in["Right Wing", "Right Midfielder", "Right Winger"]: r_w_m = True
                            
                        print(f"{p['name'][:28]:<28} | {p['pos']:<12} | {p['apps']:<4} | {p['mins']:<6} | {p['avg_rating']:<6.2f} | {status}")

                    kmv = (km_w / tot_w * 100) if tot_w > 0 else 0
                    rep_w = sum(squad_map.get(rid, {'worth': 10})['worth'] for rid in[p for p in today_team_ids if p not in[x['id'] for x in key_11]])
                    rv = max(kmv, kmv * (1 + ((w_l - rep_w) / max(1, w_l)))) if w_l > 0 else 0
                    
                    m_stats.append({
                        "id": tid, "name": team['name'], "loc": loc, "miss": m_c, "kmv": kmv, "rv": rv, 
                        "gk_out": gk_m, "def_miss": def_miss, "mid_miss": mid_miss, "att_miss": att_miss,
                        "l_wing_miss": l_w_m, "r_wing_miss": r_w_m
                    })
                    print(f"\n>> KEY MISSING VULNERABILITY (The Hole): {kmv:.1f}%")
                    print(f">> REPLACEMENT VULNERABILITY (The Doom): {rv:.1f}%")

                if len(m_stats) == 2:
                    h, a = (m_stats[0], m_stats[1]) if m_stats[0]['loc'] == 'home' else (m_stats[1], m_stats[0])
                    match_picks =[]
                    print(f"\n[PRE-MATCH STRATEGIC PREDICTIONS]")
                    
                    if (h['miss'] + a['miss']) >= 9:
                        print("- [PICK] UNDER 2.5 or OVER 2.5: High structural rotation.")
                        match_picks.extend([{"type": "U2.5"}, {"type": "O2.5"}])
                    if h['gk_out']:
                        print(f"-[PICK] {a['name'].upper()} TO SCORE: {h['name']} Keeper Liability.")
                        match_picks.append({"type": "TO_SCORE", "target_loc": "away"})
                    if a['gk_out']:
                        print(f"- [PICK] {h['name'].upper()} TO SCORE: {a['name']} Keeper Liability.")
                        match_picks.append({"type": "TO_SCORE", "target_loc": "home"})
                    if h['gk_out'] and a['gk_out']:
                        print("- [PICK] GG: Both teams starting vulnerable keepers.")
                        match_picks.append({"type": "GG"})

                    h_odd, o25, kp = odds_data['home_win'], odds_data['o25'],[]
                    if h_odd and 1.40 <= h_odd <= 1.65 and h['gk_out'] and h['def_miss'] >= 1: 
                        kp.append(f"FALSE FAVORITE: {a['name']} TO SCORE/DRAW")
                    if h_odd and 1.20 <= h_odd <= 1.60 and h['miss'] <= 2 and a['miss'] >= 4 and (a['gk_out'] or a['def_miss'] >= 2) and a['kmv'] > 30.0:
                        kp.append(f"TITAN LOCK: {h['name']} -1.5 HANDICAP")
                    if o25 and 1.60 <= o25 <= 1.90 and h['gk_out'] and a['gk_out'] and (h['miss'] + a['miss']) > 4: 
                        kp.append("BROKEN SHIELD: OVER 2.5 GOALS")
                    
                    if kp:
                        print("\n[ADVANCED KILLER RULES TRIGGERED]")
                        for r in kp: print(f"*** {r}")
                        match_picks.extend(kp)
                    if match_picks: FINAL_PREDICTIONS_FEED[f_id] = match_picks

            pagination = resp.get("pagination", {})
            has_more_pages = pagination.get("has_more", False); current_page += 1

    with open(PREDICTIONS_FILE, 'w') as f: 
        json.dump(FINAL_PREDICTIONS_FEED, f)
        
    save_cache()
    print(f"\n--- SCAN COMPLETE: {len(FINAL_PREDICTIONS_FEED)} FEED SYNCED IN DATA DIR ---")
    return FINAL_PREDICTIONS_FEED

if __name__ == "__main__":
    run_prematch_engine()