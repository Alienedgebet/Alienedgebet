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
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# NOTE: Code 9 (Aggregator) reads incoming_predictions.json
PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
CACHE_FILE       = os.path.join(DATA_DIR, "squad_cache.json")

# ==============================================================================
# SYSTEM CONFIGURATION
# ==============================================================================
API_TOKEN = os.getenv("SPORTMONKS_API_KEY")
BASE_URL  = "https://api.sportmonks.com/v3/football"

RATING_ID      = 118
MINUTES_ID     = 119
STAR_FACTOR_ID = 211
MARKET_ID_1X2  = 1
MARKET_ID_O25  = 12

PERSONNEL_WEIGHTS = {
    "Goalkeeper": 50.0,
    "Defender":    9.0,
    "Midfielder":  4.5,
    "Attacker":    1.5,
    "Unknown":     3.0
}

REQUEST_TIMEOUT = 30
REQUEST_DELAY   = 0.2
MAX_RETRIES     = 5
HISTORICAL_RECALL_DAYS = 150

# ── FIX 1: LINEUP THRESHOLD ──────────────────────────────────────────────────
# Original was 16 — blocked almost every match because many leagues
# return fewer lineup entries at the time this engine runs (early day,
# smaller leagues, partial lineups). Any match with at least 2 entries
# (one per team) is now accepted. The prediction rules handle thin data.
MIN_LINEUP_ENTRIES = 2

# How many missing key players trigger "chaos" status
CHAOS_THRESHOLD = 4

SQUAD_CACHE          = {}
FINAL_PREDICTIONS_FEED = {}
_session             = requests.Session()

# ==============================================================================
# PERSISTENT CACHE MANAGERS
# ==============================================================================
def load_cache():
    global SQUAD_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                SQUAD_CACHE = json.load(f)
            print(f"--- MEMORY RESTORED: {len(SQUAD_CACHE)} teams ---")
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
# UTILITIES
# ==============================================================================
def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur

def safe_int(x, default=0):
    try: return int(float(str(x).strip().replace(",", "")))
    except: return default

def safe_float(x, default=0.0):
    try: return float(str(x).strip().replace(",", "").rstrip("%"))
    except: return default

def GET(path, params=None):
    if params is None: params = {}
    params = dict(params)
    params.setdefault("api_token", API_TOKEN)
    if not path.startswith("/"): path = "/" + path
    url = BASE_URL.rstrip("/") + path
    backoff = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200: return r.json()
            if r.status_code == 429:
                time.sleep(backoff * attempt); continue
            return {"data": []}
        except:
            if attempt == MAX_RETRIES: return {"data": []}
            time.sleep(backoff); backoff *= 1.5
    return {"data": []}

def normalize_odd_value(value):
    try:
        val = float(value)
        if 1.01 <= val <= 30.0: return val
        if val > 100: return (val / 100) + 1
        return None
    except: return None

def extract_goals_v3(scores):
    home = away = None
    for entry in (scores or []):
        if not isinstance(entry, dict): continue
        s_obj = entry.get("score") or entry
        p = s_obj.get("participant")
        g = s_obj.get("goals")
        if g is not None:
            if p == "home": home = int(g)
            elif p == "away": away = int(g)
    return home, away

# ==============================================================================
# ODDS ENGINE
# ==============================================================================
def get_fixture_odds_strict(fixture_id):
    raw_data  = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    odds_list = raw_data.get("data", [])
    res       = {"home": 0.0, "away": 0.0, "o25": 0.0}

    for o in odds_list:
        mid = o.get("market_id")
        if mid == MARKET_ID_1X2:
            label = str(o.get("label", "")).lower()
            val   = normalize_odd_value(o.get("value"))
            if not val: continue
            if "1" in label or "home" in label:
                if res["home"] == 0 or o.get("bookmaker_id") == 20:
                    res["home"] = val
            elif "2" in label or "away" in label:
                if res["away"] == 0 or o.get("bookmaker_id") == 20:
                    res["away"] = val
        elif mid == MARKET_ID_O25:
            lbl = str(o.get("label", "")).lower()
            tot = str(o.get("total", ""))
            if "over" in lbl and "2.5" in tot:
                val = normalize_odd_value(o.get("value"))
                if val: res["o25"] = val

    return res

# ==============================================================================
# GK VULNERABILITY
# ==============================================================================
def calculate_gk_vulnerability_pro(master_gk, today_ids, all_lineup_data,
                                    squad_map, team_avg_leak):
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
        target_id = safe_int(master_gk.get('id'))
        for l in all_lineup_data:
            if safe_int(l.get('player_id')) == target_id and \
               safe_int(l.get('type_id')) == 12:
                on_bench = True
                break

    apps  = starter.get('apps', 0)
    c_p90 = starter.get('c_p90', 0.0)

    if apps == 0:
        c_p90       = team_avg_leak
        status_note = f"No Data — using team avg ({c_p90:.1f} per 90)"
        is_liability = c_p90 >= 1.50
        vuln_score   = 45.0 if is_liability else 10.0
    else:
        is_liability = c_p90 >= 1.50
        status_note  = (f"Proven Liability ({c_p90:.1f}/90)"
                        if is_liability else f"Solid Form ({c_p90:.1f}/90)")
        vuln_score   = min(100.0, c_p90 * 25)

    if c_p90 >= 2.0:
        status_note  = f"⚠️ CRITICAL LEAK ({c_p90:.1f}/90)"
        vuln_score   = max(80.0, vuln_score)
        is_liability = True

    if on_bench and is_liability:
        status_note = "Proven Liability (Master GK on bench)"
        vuln_score  = min(100.0, vuln_score + 15.0)

    return vuln_score, is_liability, status_note, c_p90

# ==============================================================================
# SQUAD DATA (150-DAY MONUMENT ENGINE)
# ==============================================================================
def get_squad_data_standardized(team_id):
    t_id     = safe_int(team_id)
    t_id_str = str(t_id)

    # Smart cache check — only use if players dict is populated
    if t_id_str in SQUAD_CACHE:
        cached = SQUAD_CACHE[t_id_str]
        if isinstance(cached, dict) and "players" in cached and \
           len(cached["players"]) > 0:
            return cached
        print(f"🔄 Cache incomplete for {t_id} — re-fetching...")

    end_dt   = (datetime.now(timezone.utc).date()
                - timedelta(days=1)).isoformat()
    start_dt = (datetime.now(timezone.utc).date()
                - timedelta(days=HISTORICAL_RECALL_DAYS)).isoformat()

    resp = GET(
        f"/fixtures/between/{start_dt}/{end_dt}/{t_id}",
        params={
            "include":  "lineups.details.type;lineups.player.position;scores;participants",
            "filter":   "fixtureStates:5",
            "per_page": 40
        }
    )

    player_stats         = {}
    team_total_conceded  = 0
    valid_fixtures       = 0

    for fx in resp.get("data", []):
        hid = aid = None
        for pt in fx.get("participants", []):
            if pt.get("meta", {}).get("location") == "home":
                hid = safe_int(pt["id"])
            else:
                aid = safe_int(pt["id"])

        h_g, a_g = extract_goals_v3(fx.get("scores", []))
        if h_g is not None and a_g is not None:
            opp_goals = a_g if t_id == hid else h_g
            team_total_conceded += opp_goals
            valid_fixtures      += 1

        for l in fx.get("lineups", []):
            if safe_int(l.get("team_id")) == t_id:
                if l.get("player_id") is None: continue
                pid   = safe_int(l["player_id"])
                p_obj = l.get("player")
                if not p_obj: continue

                m_val = r_val = star = 0
                c_val = -1.0

                for d in l.get("details", []):
                    tid_d = safe_int(d.get('type_id'))
                    raw_v = (d.get('data', {}).get('value')
                             if isinstance(d.get('data'), dict)
                             else d.get('value'))
                    try: v = float(raw_v)
                    except: v = 0
                    if tid_d == MINUTES_ID:     m_val = int(v)
                    elif tid_d == RATING_ID:    r_val = v
                    elif tid_d == STAR_FACTOR_ID: star = 1
                    elif "conceded" in str(
                        d.get('type', {}).get('name', '')
                    ).lower():
                        c_val = v

                if m_val == 0 and str(l.get("formation_position")) == "1":
                    m_val = 90
                if c_val == -1.0 and h_g is not None and a_g is not None:
                    c_val = a_g if t_id == hid else h_g

                if pid not in player_stats:
                    player_stats[pid] = {
                        "name": p_obj.get("display_name"),
                        "pos":  safe_get(p_obj, "position", "name",
                                         default="Unknown"),
                        "mins": 0, "ratings": [], "star": 0,
                        "apps": 0, "conceded": 0
                    }

                player_stats[pid]["mins"] += m_val
                player_stats[pid]["apps"] += 1
                player_stats[pid]["star"] += star
                if r_val > 0: player_stats[pid]["ratings"].append(r_val)
                if c_val >= 0: player_stats[pid]["conceded"] += c_val

    team_avg_leak = (
        team_total_conceded / max(1, valid_fixtures)
        if valid_fixtures > 0 else 1.2
    )

    processed = {}
    for pid, d in player_stats.items():
        avg_r = (sum(d["ratings"]) / len(d["ratings"])
                 if d["ratings"] else 6.0)
        worth  = (d["apps"] * 8000) + (d["mins"] * avg_r) + (d["star"] * 5000)
        c_p90  = (d["conceded"] / max(1, d["mins"])) * 90
        processed[pid] = {
            "id":         pid,
            "name":       d["name"],
            "pos":        d["pos"],
            "worth":      worth,
            "avg_rating": avg_r,
            "apps":       d["apps"],
            "mins":       d["mins"],
            "c_p90":      round(c_p90, 2)
        }

    result = {"players": processed, "team_avg_leak": team_avg_leak}
    SQUAD_CACHE[t_id_str] = result
    return result

# ==============================================================================
# 🚀 MAIN PIPELINE
# ==============================================================================
def run_incoming_forensic_engine():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    if not API_TOKEN:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return {}

    load_cache()

    global FINAL_PREDICTIONS_FEED
    FINAL_PREDICTIONS_FEED = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\nSUPREME FORENSIC INCOMING ENGINE — {today}")
    print("=" * 115)
    print(f"Lineup threshold: {MIN_LINEUP_ENTRIES} entries minimum")

    current_page  = 1
    has_more      = True
    match_index   = 0
    skipped_thin  = 0   # counter so you can see how many were skipped

    while has_more:
        resp = GET(
            f"/fixtures/date/{today}",
            params={
                "include":  "participants;lineups.details.type;lineups.player.position",
                "page":     current_page
            }
        )
        data = resp.get("data", [])
        if not data: break

        for fx in data:
            # ── FIX 1: ACCEPT ANY MATCH WITH ≥ MIN_LINEUP_ENTRIES ────────
            # Original code skipped if len(lineups_raw) < 16.
            # That threshold was the root cause of the empty feed.
            # Now we only skip if there are literally no lineups at all.
            lineups_raw = fx.get("lineups", [])
            if len(lineups_raw) < MIN_LINEUP_ENTRIES:
                skipped_thin += 1
                continue

            # Only process scheduled, live, or HT states
            if fx.get('state_id') not in [1, 2, 3, 4, 6]:
                continue

            f_id       = str(fx["id"])
            match_index += 1
            odds        = get_fixture_odds_strict(f_id)
            is_fav_home = (
                (odds['home'] > 0 and odds['home'] < odds['away'])
                if (odds['home'] > 0 and odds['away'] > 0)
                else None
            )

            print(f"\nMATCH #{match_index}: {fx['name']} (ID: {f_id})")
            print("=" * 120)
            print(
                f"ODDS → Home: {odds['home']} | "
                f"Away: {odds['away']} | O2.5: {odds['o25']}"
            )
            print(f"Lineups found: {len(lineups_raw)}")

            m_stats = []

            for team in fx.get("participants", []):
                tid = safe_int(team['id'])
                loc = team.get('meta', {}).get('location')

                sq_data   = get_squad_data_standardized(tid)
                squad_map = sq_data.get("players", {})

                if not squad_map:
                    print(
                        f"⚠️  No historical data for "
                        f"{team.get('name','Unknown')} — skipping team."
                    )
                    continue

                worth_list = list(squad_map.values())

                # Key 11: top GK + top 10 outfield by worth
                key_11 = (
                    sorted(
                        [p for p in worth_list if p['pos'] == "Goalkeeper"],
                        key=lambda x: x['worth'], reverse=True
                    )[:1] +
                    sorted(
                        [p for p in worth_list if p['pos'] != "Goalkeeper"],
                        key=lambda x: x['worth'], reverse=True
                    )[:10]
                )

                today_ids = {
                    safe_int(l['player_id'])
                    for l in lineups_raw
                    if safe_int(l.get('team_id', 0)) == tid and
                       safe_int(l.get('type_id', 0)) == 11
                }

                # ── FIX: if official lineups (type_id=11) are empty, ────
                # fall back to ALL lineup entries for this team so we
                # still get some data rather than an empty set
                if not today_ids:
                    today_ids = {
                        safe_int(l['player_id'])
                        for l in lineups_raw
                        if safe_int(l.get('team_id', 0)) == tid
                    }

                master_gk = next(
                    (p for p in key_11 if p['pos'] == "Goalkeeper"), None
                )
                gk_p, gk_m, gk_status, gk_leak = \
                    calculate_gk_vulnerability_pro(
                        master_gk, today_ids, lineups_raw,
                        squad_map, sq_data["team_avg_leak"]
                    )

                print(f"\n--- {team['name'].upper()} ({loc.upper()}) ---")
                print(
                    f"{'Player Name':<28} | {'Pos':<12} | "
                    f"{'Apps':<4} | {'Mins':<6} | "
                    f"{'Rating':<6} | Status"
                )
                print("-" * 115)

                km_w = tot_w = m_c = w_l = 0
                gk_out_flag = False
                def_miss = mid_miss = att_miss = 0

                for p in key_11:
                    w          = PERSONNEL_WEIGHTS.get(p['pos'], 3.0)
                    tot_w     += w
                    pid_int    = safe_int(p['id'])
                    is_playing = pid_int in today_ids
                    status     = "STARTING"

                    if is_playing and p['pos'] == "Goalkeeper":
                        status = gk_status

                    if not is_playing:
                        if p['pos'] == "Goalkeeper":
                            if gk_m:
                                status      = f"MISSING ({gk_status})"
                                km_w       += gk_p
                                gk_out_flag = True
                            else:
                                status = f"MISSING (Covered: {gk_status})"
                        else:
                            status   = "MISSING !!!"
                            km_w    += w
                            w_l     += p['worth']
                            if p['pos'] == "Defender":   def_miss  += 1
                            elif p['pos'] == "Midfielder": mid_miss += 1
                            elif p['pos'] == "Attacker":  att_miss  += 1
                        m_c += 1

                    print(
                        f"{str(p['name'])[:28]:<28} | "
                        f"{p['pos']:<12} | "
                        f"{p['apps']:<4} | "
                        f"{p['mins']:<6.0f} | "
                        f"{p['avg_rating']:<6.2f} | "
                        f"{status}"
                    )

                kmv = (km_w / tot_w * 100) if tot_w > 0 else 0
                rep_w = sum(
                    squad_map.get(rid, {'worth': 10})['worth']
                    for rid in today_ids
                    if rid not in [safe_int(x['id']) for x in key_11]
                )
                rv = (
                    max(kmv, kmv * (1 + ((w_l - rep_w) / max(1, w_l))))
                    if w_l > 0 else 0
                )

                m_stats.append({
                    "id":        tid,
                    "name":      team['name'],
                    "loc":       loc,
                    "miss":      m_c,
                    "kmv":       kmv,
                    "rv":        rv,
                    "gk_out":    gk_out_flag,
                    "leak":      gk_leak,
                    "breach":    (m_c >= CHAOS_THRESHOLD or gk_out_flag),
                    "is_fav":    (
                        (loc == 'home' and is_fav_home) or
                        (loc == 'away' and is_fav_home is False)
                    ),
                    "gk_solid":  gk_leak < 1.3,
                    "def_miss":  def_miss,
                    "mid_miss":  mid_miss,
                    "att_miss":  att_miss,
                })
                print(f"\n>> KEY MISSING VULNERABILITY: {kmv:.1f}%")
                print(f">> REPLACEMENT VULNERABILITY: {rv:.1f}%")
                print(f">> MISSING COUNT: {m_c}")

            if len(m_stats) != 2:
                print(
                    f"  ⚠️  Only {len(m_stats)} team(s) processed — "
                    f"skipping prediction rules."
                )
                continue

            h = next((t for t in m_stats if t['loc'] == 'home'), m_stats[0])
            a = next((t for t in m_stats if t['loc'] == 'away'), m_stats[1])

            fav = h if h['is_fav'] else a
            dog = a if h['is_fav'] else h

            # ==============================================================
            # PREDICTION RULES
            # Every rule that fires adds a pick dict to match_picks.
            # match_picks is then written to FINAL_PREDICTIONS_FEED.
            # This was the original bug — picks were printed but never saved.
            # Now every rule write is explicit and always executed.
            # ==============================================================
            match_picks = []

            print(f"\n[PRE-MATCH STRATEGIC PREDICTIONS] — {fx['name']}")
            print(f"FAVORITE: {fav['name']} | UNDERDOG: {dog['name']}")

            # ── Rule 1: Multi-Leak Conflict (GG / Over) ──────────────────
            if ((h['miss'] >= 4 and h['leak'] > 1.3 and a['leak'] > 1.5) or
                    (a['miss'] >= 4 and a['leak'] > 1.3 and h['leak'] > 1.5)):
                pick = {
                    "type":   "OVER_GG",
                    "reason": "Critical Keeper Leak Handshake"
                }
                print(f"  ✅ RULE 1 — {pick['type']}: {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 2: Dog structural failure → Fav to score ────────────
            if not dog['is_fav'] and dog['leak'] > 1.5 and dog['miss'] >= 3:
                pick = {
                    "type":        "TO_SCORE",
                    "target_loc":  fav['loc'],
                    "target_name": fav['name'],
                    "reason":      "Underdog structural failure"
                }
                print(f"  ✅ RULE 2 — {pick['type']}: {fav['name']} | {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 3: Weak fav but solid GK vs leaky dog ───────────────
            if fav['miss'] >= 4 and fav['gk_solid'] and dog['leak'] > 1.5:
                pick = {
                    "type":        "WIN_DRAW",
                    "target_loc":  fav['loc'],
                    "target_name": fav['name'],
                    "reason":      "Professional Game Management"
                }
                print(f"  ✅ RULE 3 — {pick['type']}: {fav['name']} | {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 4: Weak fav with leaky GK vs stable dog ─────────────
            if (fav['miss'] >= 4 and not fav['gk_solid'] and
                    not dog['breach']):
                pick = {
                    "type":        "TO_SCORE",
                    "target_loc":  dog['loc'],
                    "target_name": dog['name'],
                    "reason":      "Favorite defense collapsing"
                }
                print(f"  ✅ RULE 4 — {pick['type']}: {dog['name']} | {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 5: Symmetric leak + Fav doom > 40 → Over 2.5 ────────
            if h['leak'] >= 1.3 and a['leak'] >= 1.3 and fav['rv'] > 40:
                pick = {
                    "type":   "OVER_2.5",
                    "reason": "High Volatility structural state"
                }
                print(f"  ✅ RULE 5 — {pick['type']}: {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 6: Both doom > 50 → GG / Over 2.5 ───────────────────
            if h['rv'] > 50 and a['rv'] > 50:
                pick = {
                    "type":   "GG_OVER_2.5",
                    "reason": "Total Defensive Collapse"
                }
                print(f"  ✅ RULE 6 — {pick['type']}: {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 7: Strong fav vs broken dog ─────────────────────────
            if (fav['miss'] < 4 and fav['gk_solid'] and
                    (dog['leak'] > 1.5 or dog['rv'] > 40)):
                pick = {
                    "type":        "WIN",
                    "target_loc":  fav['loc'],
                    "target_name": fav['name'],
                    "reason":      "Titan Lock Alignment"
                }
                print(f"  ✅ RULE 7 — {pick['type']}: {fav['name']} | {pick['reason']}")
                match_picks.append(pick)

            # ── Rule 8: GK liability on either side ──────────────────────
            if h['gk_out']:
                pick = {
                    "type":        "TO_SCORE",
                    "target_loc":  "away",
                    "target_name": a['name'],
                    "reason":      f"Home GK liability: {h['name']}"
                }
                print(f"  ✅ RULE 8H — {pick['type']}: {a['name']} | {pick['reason']}")
                match_picks.append(pick)

            if a['gk_out']:
                pick = {
                    "type":        "TO_SCORE",
                    "target_loc":  "home",
                    "target_name": h['name'],
                    "reason":      f"Away GK liability: {a['name']}"
                }
                print(f"  ✅ RULE 8A — {pick['type']}: {h['name']} | {pick['reason']}")
                match_picks.append(pick)

            if h['gk_out'] and a['gk_out']:
                pick = {"type": "GG", "reason": "Both GKs are liabilities"}
                print(f"  ✅ RULE 8GG — {pick['type']}: {pick['reason']}")
                match_picks.append(pick)

            # ── GUARANTEE: even if no rule fired, save a base entry ──────
            # This ensures Code 9 always has something to match against
            # for every match that made it through the lineup check.
            if not match_picks:
                print("  ℹ️  No structural rules triggered — saving base entry.")
                match_picks.append({
                    "type":   "MONITOR",
                    "reason": "No structural damage detected — monitoring only"
                })

            # ── WRITE TO FEED — always, for every match ───────────────────
            FINAL_PREDICTIONS_FEED[f_id] = match_picks
            print(
                f"  💾 {len(match_picks)} pick(s) saved to feed "
                f"for fixture {f_id}"
            )

        pagination    = resp.get("pagination", {}) or \
                        resp.get("meta", {}).get("pagination", {})
        has_more      = pagination.get("has_more", False)
        current_page += 1

    # ── SAVE TO FILE ─────────────────────────────────────────────────────
    with open(PREDICTIONS_FILE, 'w') as f:
        json.dump(FINAL_PREDICTIONS_FEED, f, indent=2)

    save_cache()

    print(f"\n{'='*115}")
    print(
        f"SCAN COMPLETE: {len(FINAL_PREDICTIONS_FEED)} matches written to feed"
    )
    if skipped_thin > 0:
        print(
            f"  ⚪ {skipped_thin} matches skipped "
            f"(fewer than {MIN_LINEUP_ENTRIES} lineup entries)"
        )
    print(f"Feed saved: {PREDICTIONS_FILE}")
    print(f"{'='*115}\n")

    return FINAL_PREDICTIONS_FEED


if __name__ == "__main__":
    run_incoming_forensic_engine()