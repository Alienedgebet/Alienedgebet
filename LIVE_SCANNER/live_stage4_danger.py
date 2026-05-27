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
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

OUTPUT_FILE = os.path.join(DATA_DIR, "danger_audit.json")

# ==============================================================================
# ⚙️ SYSTEM CONFIGURATION (WORLD STANDARD)
# ==============================================================================
API_KEY = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football"

# Stat IDs for Forensic Worth Calculation
RATING_ID = 118       
MINUTES_ID = 119      
STAR_FACTOR_ID = 211  

# Positional Weights for Vulnerability Calculation
POS_WEIGHTS = {
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
CHAOS_THRESHOLD = 4  # 4+ Star players missing = Red Danger

_session = requests.Session()

# ------------------------------------------------------------------------------
# 🛠️ CORE UTILITY FUNCTIONS
# ------------------------------------------------------------------------------
def GET(path: str, params: Optional[Dict[str,Any]] = None) -> Dict[str,Any]:
    if params is None: params = {}
    params = dict(params); params.setdefault("api_token", API_KEY)
    if not path.startswith("/"): path = "/" + path
    url = BASE_URL.rstrip("/") + path
    backoff = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                time.sleep(backoff * attempt); continue
            r.raise_for_status()
            return r.json()
        except:
            if attempt == MAX_RETRIES: return {"data":[]}
            time.sleep(backoff); backoff *= 1.5
    return {"data":[]}

def safe_int(x: Any, default: Optional[int] = 0) -> int:
    try: return int(float(str(x).strip().replace(",", "")))
    except: return default

def safe_float(x: Any, default: float = 0.0) -> float:
    try: return float(str(x).strip().replace(",", "").rstrip("%"))
    except: return default

def extract_stat_entries(fx: Dict[str,Any], team_id: int) -> Dict[str, float]:
    """🚨 FIX: Bulletproof Participant Mapping! No more blind spots. 🚨"""
    stats_raw = fx.get("statistics") or[]
    result = {}
    t_id = int(team_id)
    
    # Sometimes SportMonks groups by ID as keys, sometimes as a flat list
    entries =[]
    if isinstance(stats_raw, dict):
        entries = stats_raw.get(str(t_id),[])
    else:
        entries =[s for s in stats_raw if int(s.get('participant_id', 0)) == t_id]
        
    for s in entries:
        t_obj = s.get("type", {})
        stat_name = t_obj.get("name") if isinstance(t_obj, dict) else s.get("name")
        val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
        if stat_name and val is not None: result[str(stat_name)] = safe_float(val)
    return result

# ------------------------------------------------------------------------------
# 🧠 FORENSIC SQUAD ENGINES (FULL IMPLEMENTATION)
# ------------------------------------------------------------------------------
def get_key_players_forensics(team_id: int):
    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=HISTORICAL_RECALL_DAYS)).isoformat()
    t_id = int(team_id)
    
    resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{t_id}", params={
        "include": "lineups.details.type;lineups.player.position;scores;participants",
        "filter": "fixtureStates:5", 
        "per_page": 50 
    })
    
    player_stats = {}
    history = resp.get("data",[])
    for fx in history:
        # Keeper Conceded Calculation Fallback
        hid, aid = None, None
        for pt in fx.get("participants",[]):
            loc = pt.get("meta", {}).get("location")
            if loc == "home": hid = str(pt.get("id"))
            elif loc == "away": aid = str(pt.get("id"))
        
        h_g, a_g = 0, 0
        for entry in fx.get("scores",[]):
            s_obj = entry.get("score") or entry
            g = s_obj.get("goals")
            if g is not None:
                if str(entry.get("participant_id")) == hid: h_g = int(g)
                else: a_g = int(g)
        
        opp_goals = a_g if str(t_id) == hid else h_g

        for l in fx.get("lineups",[]):
            if int(l.get("team_id", 0)) == t_id:
                p_obj = l.get("player")
                if not p_obj or not isinstance(p_obj, dict): continue
                pid = int(l.get("player_id"))
                
                m_val, r_val, star_val, c_val = 0, 0.0, 0, -1.0
                for d in l.get("details",[]):
                    tid = int(d.get('type_id', 0))
                    val = d.get('data', {}).get('value', 0) if isinstance(d.get('data'), dict) else d.get('value', 0)
                    if tid == MINUTES_ID: m_val = int(safe_float(val))
                    elif tid == RATING_ID: r_val = safe_float(val)
                    elif tid == STAR_FACTOR_ID: star_val = 1 
                    elif "conceded" in str(d.get('type', {}).get('name', '')).lower(): c_val = safe_float(val)

                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                if c_val == -1.0: c_val = float(opp_goals)

                if pid not in player_stats:
                    pos = p_obj.get("position", {}).get("name", "Unknown") if p_obj.get("position") else "Unknown"
                    player_stats[pid] = {"name": p_obj.get("display_name"), "pos": pos, "mins": 0, "ratings":[], "star": 0, "conceded": 0}
                
                player_stats[pid]["mins"] += m_val
                player_stats[pid]["star"] += star_val
                if r_val > 0: player_stats[pid]["ratings"].append(r_val)
                if m_val > 0: player_stats[pid]["conceded"] += c_val

    worth_list =[]
    for pid, d in player_stats.items():
        avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
        worth = (d["mins"] * avg_r) + (d["star"] * 1000)
        c_p90 = (d["conceded"] / d["mins"] * 90) if d["mins"] > 0 else 0.0
        worth_list.append({"id": pid, "name": d["name"], "pos": d["pos"], "worth": worth, "c_p90": c_p90})

    key_gks = sorted([p for p in worth_list if p['pos'] == "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:1]
    key_others = sorted([p for p in worth_list if p['pos'] != "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:10]
    
    return {int(p['id']): p for p in (key_gks + key_others)}, history

def compute_style_analysis(history, team_id: int):
    """🚨 FIX: Calibrated Tactical Thresholds to Market Reality! 🚨"""
    recent = history[:8]
    metrics = defaultdict(list)
    t_id = int(team_id)
    for r in recent:
        ent = extract_stat_entries(r, t_id)
        metrics["da"].append(ent.get("Dangerous Attacks", 0))
    
    avg_da = sum(metrics["da"])/len(metrics["da"]) if metrics["da"] else 0.0
    
    # Lowered from >45 to >36 so it actually catches attacking teams!
    label = "Attacking" if avg_da > 36 else "Defensive" if avg_da < 28 else "Balanced"
    return {"label": label, "score": round(avg_da/10, 2), "da": avg_da}

# ------------------------------------------------------------------------------
# 🚀 MAIN PIPELINE (WRAPPED FOR ARCHITECTURE)
# ------------------------------------------------------------------------------
def run_danger_forensic_aggregator():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return[]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n{'='*120}")
    print(f"{'ALIENEDGE SUPREME DANGER FORENSIC AGGREGATOR':^120}")
    print(f"{today:^120}")
    print(f"{'='*120}\n")

    all_fixtures =[]
    current_page = 1
    has_more_pages = True
    
    while has_more_pages:
        # 🚨 FIX: Added 'statistics' to include array so we actually get DA!
        resp = GET(f"/fixtures/date/{today}", params={
            "include": "participants;lineups.player;metadata;formations;statistics;statistics.type;scores",
            "page": current_page
        })
        data = resp.get("data",[])
        if not data: break
        
        all_fixtures.extend(data)
        print(f"   [PAGINATION] Captured Page {current_page} ({len(data)} fixtures)...")
        
        pagination = resp.get("pagination", {})
        if not pagination: pagination = resp.get("meta", {}).get("pagination", {})
        has_more_pages = pagination.get("has_more", False)
        current_page += 1
        time.sleep(REQUEST_DELAY)

    print(f"\n[INFO] Successfully recovered {len(all_fixtures)} total fixtures. Starting Deep Forensics...\n")

    output_pool =[]
    processed_count = 0

    for fx in all_fixtures:
        try:
            lineups = fx.get("lineups", [])
            starters_all =[l for l in lineups if int(l.get('type_id', 0)) == 11]
            if not starters_all: continue 

            parts = fx.get("participants",[])
            if len(parts) < 2: continue
            h_p, a_p = parts[0], parts[1]
            
            def audit_side(team_id, team_name):
                t_id = int(team_id)
                key_monument, history = get_key_players_forensics(t_id)
                current_starters = {int(l['player_id']) for l in starters_all if int(l.get('team_id', 0)) == t_id}
                
                starting_gk_leak = 0.0
                for pid in current_starters:
                    if key_monument.get(pid, {}).get('pos') == "Goalkeeper":
                        starting_gk_leak = key_monument[pid]['c_p90']
                        break
                
                missing_details =[]
                m_weight, t_weight, gk_hole = 0, 0, False
                for pid, info in key_monument.items():
                    w = POS_WEIGHTS.get(info['pos'], 3.0)
                    t_weight += w
                    if pid not in current_starters:
                        missing_details.append({"name": info['name'], "pos": info['pos']})
                        m_weight += w
                        if info['pos'] == "Goalkeeper": gk_hole = True
                
                v_pct = (m_weight / t_weight * 100) if t_weight > 0 else 0
                breached = (len(missing_details) >= CHAOS_THRESHOLD) or gk_hole
                style = compute_style_analysis(history, t_id)
                
                return {
                    "team_name": team_name, "id": t_id, "breach": breached,
                    "danger_level": "🔴 DANGER" if breached else "✅ SAFE",
                    "vulnerability_pct": round(v_pct, 1),
                    "gk_leak": starting_gk_leak,
                    "missing_details": missing_details,
                    "formation": next((f['formation'] for f in fx.get('formations',[]) if int(f['participant_id']) == t_id), "N/A"),
                    "style": style
                }

            home_audit = audit_side(h_p['id'], h_p['name'])
            away_audit = audit_side(a_p['id'], a_p['name'])

            # 🚨 FIX: Tactical Alignment Handshake (Lowered to > 35 to catch open matches)
            style_align = "🔥 OPEN" if home_audit['style']['da'] > 35 and away_audit['style']['da'] > 35 else "⚠️ TIGHT"
            
            # --- DYNAMIC SYMMETRIC BTTS (GG) LOGIC ---
            h_leak = home_audit['gk_leak']
            a_leak = away_audit['gk_leak']
            
            gg_label = "Weak"
            if h_leak >= 1.50 and a_leak >= 1.50:
                gg_label = "Excellent"
            elif (h_leak >= 1.40 and a_leak >= 1.50 and home_audit['breach']) or \
                 (a_leak >= 1.40 and h_leak >= 1.50 and away_audit['breach']):
                gg_label = "Very Strong"
            elif (h_leak >= 1.40 and a_leak >= 1.50) or (a_leak >= 1.40 and h_leak >= 1.50):
                gg_label = "Strong"
            elif style_align == "🔥 OPEN" and (home_audit['breach'] or away_audit['breach']):
                gg_label = "Strong"

            # Construct the final data card
            match_card = {
                "fixture": fx['name'], "fixture_id": fx['id'],
                "home_team": home_audit, "away_team": away_audit,
                "style_alignment": style_align,
                "match_chemistry_list": {
                    "Corner": "Elite" if home_audit['style']['da'] > 65 or away_audit['style']['da'] > 65 else "Strong",
                    "Gg": gg_label
                }
            }

            # ==================================================================
            # 📋 TACTICAL INTELLIGENCE PRINTOUT
            # ==================================================================
            print(f"MATCH: {match_card['fixture']} (ID: {match_card['fixture_id']})")
            print(f"Handshake: [ Alignment: {match_card['style_alignment']} | GG: {gg_label} ]")
            for side, data in[("HOME", home_audit), ("AWAY", away_audit)]:
                print(f"  [{side}] {data['team_name']} -> {data['danger_level']} ({data['vulnerability_pct']}% Damage | GK Leak: {data['gk_leak']:.2f})")
                if data['missing_details']:
                    missing_str = ", ".join([f"{p['name']} ({p['pos']})" for p in data['missing_details']])
                    print(f"    MISSING: {missing_str}")
            print("-" * 120)

            output_pool.append(match_card)
            processed_count += 1
            time.sleep(REQUEST_DELAY)
            
        except Exception as e: continue

    # 💾 SAVE TO JSON FOR THE MASTER AGGREGATOR
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_pool, f, indent=4, ensure_ascii=False)
    
    print(f"\n[🏆] SUPREME AUDIT COMPLETE: {processed_count} PROFILES SAVED TO DATA DIR")
    
    return output_pool

if __name__ == "__main__":
    run_danger_forensic_aggregator()