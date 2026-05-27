import os
import requests
import time
import math
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
import re
import random
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# NOTE: Code 4 (Aggregator) looks for "incoming_predictions.json", so we map it correctly here!
PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
CACHE_FILE = os.path.join(DATA_DIR, "squad_cache.json")

# ==============================================================================
# ⚙️ SYSTEM CONFIGURATION (WORLD STANDARD)
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football"

# Verified Sportmonks V3 Type IDs
RATING_ID = 118
MINUTES_ID = 119
STAR_FACTOR_ID = 211
MARKET_ID_1X2 = 1
MARKET_ID_O25 = 12

# Positional Weights (The Structural Monument)
PERSONNEL_WEIGHTS = {
    "Goalkeeper": 50.0, 
    "Defender": 9.0, 
    "Midfielder": 4.5, 
    "Attacker": 1.5, 
    "Unknown": 3.0
}

REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.2
MAX_RETRIES = 5
HISTORICAL_RECALL_DAYS = 150 
CHAOS_THRESHOLD = 4  

SQUAD_CACHE = {}
FINAL_PREDICTIONS_FEED = {}

_session = requests.Session()

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

# ------------------------------------------------------------------------------
# 🛠️ CORE UTILITY FUNCTIONS
# ------------------------------------------------------------------------------
def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur

def safe_int(x: Any, default: Optional[int] = 0) -> int:
    try: return int(float(str(x).strip().replace(",", "")))
    except: return default

def safe_float(x: Any, default: float = 0.0) -> float:
    try: return float(str(x).strip().replace(",", "").rstrip("%"))
    except: return default

def GET(path: str, params: Optional[Dict[str,Any]] = None) -> Dict[str,Any]:
    if params is None: params = {}
    params = dict(params); params.setdefault("api_token", API_TOKEN)
    if not path.startswith("/"): path = "/" + path
    url = BASE_URL.rstrip("/") + path
    backoff = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200: return r.json()
            if r.status_code == 429:
                time.sleep(backoff * attempt); continue
            return {"data":[]}
        except:
            if attempt == MAX_RETRIES: return {"data":[]}
            time.sleep(backoff); backoff *= 1.5
    return {"data":[]}

def normalize_odd_value(value):
    try:
        val = float(value)
        if 1.01 <= val <= 30.0: return val
        if val > 100: return (val / 100) + 1
        return None
    except: return None

def extract_goals_v3(scores: Any) -> Tuple[Optional[int], Optional[int]]:
    home = away = None
    for entry in (scores or[]):
        if not isinstance(entry, dict): continue
        s_obj = entry.get("score") or entry
        p, g = s_obj.get("participant"), s_obj.get("goals")
        if g is not None:
            if p == "home": home = int(g)
            elif p == "away": away = int(g)
    return home, away

# ------------------------------------------------------------------------------
# 🎯 SNIPER ODDS ENGINE
# ------------------------------------------------------------------------------
def get_fixture_odds_strict(fixture_id):
    raw_data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    odds_list = raw_data.get("data",[])
    res = {"home": 0.0, "away": 0.0, "o25": 0.0}
    for o in odds_list:
        mid = o.get("market_id")
        if mid == MARKET_ID_1X2:
            label = str(o.get("label", "")).lower()
            val = normalize_odd_value(o.get("value"))
            if not val: continue
            if "1" in label or "home" in label:
                if res["home"] == 0 or o.get("bookmaker_id") == 20: res["home"] = val
            elif "2" in label or "away" in label:
                if res["away"] == 0 or o.get("bookmaker_id") == 20: res["away"] = val
        elif mid == MARKET_ID_O25:
            lbl, tot = str(o.get("label", "")).lower(), str(o.get("total", ""))
            if "over" in lbl and "2.5" in tot:
                val = normalize_odd_value(o.get("value"))
                if val: res["o25"] = val
    return res

# ------------------------------------------------------------------------------
# 🛡️ V3 KEEPER SKILL GAP AUDIT (RECTIFIED FOR ROOKIE PROXY)
# ------------------------------------------------------------------------------
def calculate_gk_vulnerability_pro(master_gk, today_ids, all_lineup_data, squad_map, team_avg_leak):
    starting_gk_id = None
    for pid_str in today_ids:
        pid = safe_int(pid_str)
        if squad_map.get(pid, {}).get('pos') == "Goalkeeper":
            starting_gk_id = pid
            break

    if not starting_gk_id:
        return 65.0, True, "UNLISTED GK (Proxy Risk)", 1.5

    starter = squad_map[starting_gk_id]
    
    on_bench = False
    if master_gk and safe_int(master_gk.get('id')) != starting_gk_id:
        target_master_id = safe_int(master_gk.get('id'))
        for l in all_lineup_data:
            l_pid = safe_int(l.get('player_id'))
            if l_pid == target_master_id and safe_int(l.get('type_id')) == 12:
                on_bench = True
                break

    apps = starter.get('apps', 0)
    c_p90 = starter.get('c_p90', 0.0)
    
    if apps == 0:
        c_p90 = team_avg_leak
        status_note = f"Solid Form ({c_p90:.1f} per 90)"
        is_liability = c_p90 >= 1.50
        vuln_score = 45.0 if is_liability else 10.0
    else:
        is_liability = c_p90 >= 1.50
        status_note = f"Proven Liability ({c_p90:.1f} per 90)" if is_liability else f"Solid Form ({c_p90:.1f} per 90)"
        vuln_score = min(100.0, (c_p90 * 25))

    if c_p90 >= 2.0:
        status_note = f"⚠️ CRITICAL LEAK ({c_p90:.1f} per 90)"
        vuln_score = max(80.0, vuln_score)
        is_liability = True

    if on_bench and is_liability:
        status_note = f"Proven Liability ({c_p90:.1f} per 90)"
        vuln_score = min(100.0, vuln_score + 15.0)

    return vuln_score, is_liability, status_note, c_p90

# ------------------------------------------------------------------------------
# 🧠 MONUMENT ENGINE (150-DAY RECALL)
# ------------------------------------------------------------------------------
def get_squad_data_standardized(team_id):
    t_id = safe_int(team_id)
    t_id_str = str(t_id) # JSON safe key
    
    # 🧠 SMART CACHE CHECK (SELF-HEALING)
    if t_id_str in SQUAD_CACHE:
        cached_data = SQUAD_CACHE[t_id_str]
        # Only trust the cache if 'players' exists AND actually has data in it
        if "players" in cached_data and len(cached_data["players"]) > 0:
            return cached_data
        else:
            print(f"🔄 Cache incomplete for Team ID {t_id}. Forcing fresh Sportmonks API fetch...")
            # Automatically ignores the bad cache and moves down to fetch fresh data!

    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=HISTORICAL_RECALL_DAYS)).isoformat()
    resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{t_id}", params={
        "include": "lineups.details.type;lineups.player.position;scores;participants",
        "filter": "fixtureStates:5", "per_page": 40
    })

    player_stats = {}
    team_total_conceded = 0; valid_fixtures = 0
    for fx in resp.get("data",[]):
        hid = aid = None
        for pt in fx.get("participants",[]):
            if pt.get("meta", {}).get("location") == "home": hid = safe_int(pt["id"])
            else: aid = safe_int(pt["id"])

        h_g, a_g = extract_goals_v3(fx.get("scores",[]))
        if h_g is not None and a_g is not None:
            opp_goals = a_g if t_id == hid else h_g
            team_total_conceded += opp_goals; valid_fixtures += 1

        for l in fx.get("lineups",[]):
            if safe_int(l.get("team_id")) == t_id:
                if l.get("player_id") is None: continue
                pid = safe_int(l["player_id"])
                p_obj = l.get("player")
                if not p_obj: continue

                m_val, r_val, star, c_val = 0, 0.0, 0, -1.0 
                for d in l.get("details",[]):
                    tid = safe_int(d.get('type_id'))
                    raw_v = d.get('data', {}).get('value') or d.get('value')
                    try: v = float(raw_v)
                    except: v = 0
                    if tid == MINUTES_ID: m_val = int(v)
                    elif tid == RATING_ID: r_val = v
                    elif tid == STAR_FACTOR_ID: star = 1 
                    elif "conceded" in str(d.get('type', {}).get('name', '')).lower(): c_val = v

                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                if pid not in player_stats:
                    player_stats[pid] = {"name": p_obj.get("display_name"), "pos": safe_get(p_obj, "position", "name"), "mins": 0, "ratings":[], "star": 0, "apps": 0, "conceded": 0}
                player_stats[pid]["mins"] += m_val; player_stats[pid]["apps"] += 1; player_stats[pid]["star"] += star
                if r_val > 0: player_stats[pid]["ratings"].append(r_val)
                if c_val >= 0: player_stats[pid]["conceded"] += c_val

    team_avg_leak = (team_total_conceded / max(1, valid_fixtures)) if valid_fixtures > 0 else 1.2
    processed = {}
    for pid, d in player_stats.items():
        avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
        worth = (d["apps"] * 8000) + (d["mins"] * avg_r) + (d["star"] * 5000)
        c_p90 = (d["conceded"] / max(1, d["mins"])) * 90
        processed[pid] = {"id": pid, "name": d["name"], "pos": d["pos"], "worth": worth, "avg_rating": avg_r, "apps": d["apps"], "mins": d["mins"], "c_p90": round(c_p90, 2)}
    
    result = {"players": processed, "team_avg_leak": team_avg_leak}
    SQUAD_CACHE[t_id_str] = result
    return result

# ------------------------------------------------------------------------------
# 🚀 MAIN PIPELINE (WRAPPED FOR ARCHITECTURE)
# ------------------------------------------------------------------------------
def run_incoming_forensic_engine():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}

    load_cache()
    global FINAL_PREDICTIONS_FEED
    FINAL_PREDICTIONS_FEED = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\nSUPREME FORENSIC INCOMING ENGINE - {today}")
    print("="*115)

    current_page = 1
    has_more_pages = True
    match_index = 0

    while has_more_pages:
        resp = GET(f"/fixtures/date/{today}", params={"include": "participants;lineups.details.type;lineups.player.position", "page": current_page})
        data = resp.get("data",[])
        if not data: break

        for fx in data:
            # NS, Live, or HT
            if fx.get('state_id') not in[1, 2, 3, 4, 6]: continue
            lineups_raw = fx.get("lineups",[])
            if len(lineups_raw) < 16: continue 

            f_id = str(fx["id"]); match_index += 1
            odds = get_fixture_odds_strict(f_id)
            is_fav_home = (odds['home'] > 0 and odds['home'] < odds['away']) if (odds['home'] > 0 and odds['away'] > 0) else None

            print(f"\nMATCH #{match_index}: {fx['name']} (ID: {f_id})")
            print("="*120)
            print(f"ODDS SCAN > Home: {odds['home']} | Away: {odds['away']} | O2.5: {odds['o25']}")

            m_stats =[]
            for team in fx.get("participants",[]):
                tid, loc = safe_int(team['id']), team.get('meta', {}).get('location')
                sq_data = get_squad_data_standardized(tid)
                
                # 🛡️ SAFETY FIX: Safely grab 'players', default to empty dict if missing entirely
                squad_map = sq_data.get("players", {})
                
                # If squad_map is STILL completely empty after fetching, skip the team safely
                if not squad_map:
                    print(f"⚠️ SKIPPING: Sportmonks has no historical player data for {team.get('name', 'Unknown')}.")
                    continue 
                
                # Identify Key 11 (Monument)
                worth_list = list(squad_map.values())
                key_11 = sorted([p for p in worth_list if p['pos'] == "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:1] + \
                         sorted([p for p in worth_list if p['pos'] != "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:10]
                
                today_ids = {safe_int(l['player_id']) for l in lineups_raw if safe_int(l.get('team_id', 0)) == tid and safe_int(l.get('type_id', 0)) == 11}
                master_gk = next((p for p in key_11 if p['pos'] == "Goalkeeper"), None)
                
                gk_p, gk_m, gk_status, gk_leak = calculate_gk_vulnerability_pro(master_gk, today_ids, lineups_raw, squad_map, sq_data["team_avg_leak"])

                print(f"\n--- {team['name'].upper()} ({loc.upper()}) ---")
                print(f"{'Player Name':<28} | {'Pos':<12} | {'Apps':<4} | {'Mins':<6} | {'Rating':<6} | {'Status'}")
                print("-" * 115)

                km_w = tot_w = m_c = w_l = 0
                gk_out_flag = False
                for p in key_11:
                    w = PERSONNEL_WEIGHTS.get(p['pos'], 3.0); tot_w += w
                    is_playing = safe_int(p['id']) in today_ids
                    status = "STARTING"
                    if is_playing and p['pos'] == "Goalkeeper": status = gk_status
                    if not is_playing:
                        if p['pos'] == "Goalkeeper":
                            if gk_m: status = f"MISSING ({gk_status})"; km_w += gk_p; m_c += 1; gk_out_flag = True
                            else: status = f"MISSING (Covered by: {gk_status})"; km_w += 0.0; gk_out_flag = False
                        else: status = "MISSING !!!"; km_w += w; m_c += 1; w_l += p['worth']
                    print(f"{p['name'][:28]:<28} | {p['pos']:<12} | {p['apps']:<4} | {p['mins']:<6.0f} | {p['avg_rating']:<6.2f} | {status}")

                kmv = (km_w / tot_w * 100) if tot_w > 0 else 0
                rep_w = sum(squad_map.get(rid, {'worth': 10})['worth'] for rid in[p for p in today_ids if p not in [x['id'] for x in key_11]])
                rv = max(kmv, kmv * (1 + ((w_l - rep_w) / max(1, w_l)))) if w_l > 0 else 0

                m_stats.append({
                    "id": tid, "name": team['name'], "loc": loc, "miss": m_c, "kmv": kmv, "rv": rv, 
                    "gk_out": gk_out_flag, "leak": gk_leak, "breach": (m_c >= CHAOS_THRESHOLD or gk_out_flag),
                    "is_fav": (loc == 'home' and is_fav_home) or (loc == 'away' and is_fav_home is False),
                    "gk_solid": gk_leak < 1.3
                })
                print(f"\n>> KEY MISSING VULNERABILITY (The Hole): {kmv:.1f}%")
                print(f">> REPLACEMENT VULNERABILITY (The Doom): {rv:.1f}%")
                print(f">> ADJUSTED MISSING COUNT: {m_c}")

            # If a team was skipped due to missing data, len(m_stats) will be 1 instead of 2.
            # This safely prevents the match logic below from crashing!
            if len(m_stats) == 2:
                h, a = m_stats[0], m_stats[1]
                print(f"\n[PRE-MATCH STRATEGIC PREDICTIONS]")

                # ==============================================================
                # FIX: match_picks is now initialised and populated for every
                # rule that fires. At the end of the block it is stored into
                # FINAL_PREDICTIONS_FEED so the aggregator (Doc 13) actually
                # receives real data instead of an always-empty dict.
                # Previously the rules were only printed — the feed was never
                # written, causing every downstream file to run on empty input.
                # ==============================================================
                match_picks = []

                fav = h if h['is_fav'] else a
                dog = a if h['is_fav'] else h
                f_label = "[WEAK]" if fav['miss'] >= 4 else "[STRONG]"
                print(f"FAVORITE STATUS: {fav['name']} {f_label}")

                # Rule 2: Multi-Leak Conflict
                if (h['miss'] >= 4 and h['leak'] > 1.3 and a['leak'] > 1.5) or (a['miss'] >= 4 and a['leak'] > 1.3 and h['leak'] > 1.5):
                    print("-[PICK] OVER / GG: Critical Keeper Leak Handshake.")
                    match_picks.append({"type": "OVER_GG", "reason": "Critical Keeper Leak Handshake"})

                # Rule 3: Dog Leak > 1.5 + 3 Missing
                if not dog['is_fav'] and dog['leak'] > 1.5 and dog['miss'] >= 3:
                    print(f"- [PICK] {fav['name'].upper()} TO SCORE: Underdog structural failure.")
                    match_picks.append({"type": "TO_SCORE", "target_loc": fav['loc'], "target_name": fav['name'], "reason": "Underdog structural failure"})

                # Rule 4: Fav WEAK but solid GK vs leaky dog
                if fav['miss'] >= 4 and fav['gk_solid'] and dog['leak'] > 1.5:
                    print(f"- [PICK] {fav['name'].upper()} WIN/DRAW: Professional Game Management.")
                    match_picks.append({"type": "WIN_DRAW", "target_loc": fav['loc'], "target_name": fav['name'], "reason": "Professional Game Management"})

                # Rule 5: Fav WEAK with leaky GK vs stable dog
                if fav['miss'] >= 4 and not fav['gk_solid'] and not dog['breach']:
                    print(f"- [PICK] {dog['name'].upper()} TO SCORE: Favorite defense collapsing.")
                    match_picks.append({"type": "TO_SCORE", "target_loc": dog['loc'], "target_name": dog['name'], "reason": "Favorite defense collapsing"})

                # Rule 6: Symmetric Leak > 1.3 + Fav Doom > 40
                if h['leak'] >= 1.3 and a['leak'] >= 1.3 and fav['rv'] > 40:
                    print("- [PICK] OVER 2.5: High Volatility structural state.")
                    match_picks.append({"type": "OVER_2.5", "reason": "High Volatility structural state"})

                # Rule 7: Both Doom > 50
                if h['rv'] > 50 and a['rv'] > 50:
                    print("- [PICK] GG / OVER 2.5: Total Defensive Collapse.")
                    match_picks.append({"type": "GG_OVER_2.5", "reason": "Total Defensive Collapse"})

                # Rule 8: Fav Strong & Solid GK vs broken dog
                if fav['miss'] < 4 and fav['gk_solid'] and (dog['leak'] > 1.5 or dog['rv'] > 40):
                    print(f"- [PICK] {fav['name'].upper()} TO WIN: Titan Lock Alignment.")
                    match_picks.append({"type": "WIN", "target_loc": fav['loc'], "target_name": fav['name'], "reason": "Titan Lock Alignment"})

                # Store picks into the feed so the aggregator receives real data
                if match_picks:
                    FINAL_PREDICTIONS_FEED[f_id] = match_picks

        pagination = resp.get("pagination", {}) or resp.get("meta", {}).get("pagination", {})
        has_more_pages = pagination.get("has_more", False); current_page += 1

    # --- SAVE OUTPUTS FOR THE AGGREGATOR ---
    with open(PREDICTIONS_FILE, 'w') as f:
        json.dump(FINAL_PREDICTIONS_FEED, f)
        
    save_cache()
    print(f"\n--- SCAN COMPLETE: STRATEGIC FEED SYNCED TO {PREDICTIONS_FILE} ---")
    print(f"--- {len(FINAL_PREDICTIONS_FEED)} matches with picks written to feed ---")
    
    return FINAL_PREDICTIONS_FEED

if __name__ == "__main__":
    run_incoming_forensic_engine()