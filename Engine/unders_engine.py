import os
import sys
import time
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import math
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# CONFIGURATION
# ==============================================================================
API_KEY  = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

# --- FIXED FOR GOOGLE COLAB & VS CODE COMPATIBILITY ---
try:
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "output")
    DATA_DIR   = os.path.join(os.path.dirname(BASE_DIR), "data")
except NameError:
    BASE_DIR   = os.path.abspath("")  
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

TEAM_LOOKBACK_DAYS     = 365
GK_LOOKBACK_DAYS       = 150    
REQUEST_DELAY_SEC      = 0.18
LAST_N_GAMES           = 5
FATIGUE_WINDOW_DAYS    = 30

SIMULATION_SIZE        = 10_000  
MAX_GOALS_DISPLAY      = 6
POISSON_MAX_GOALS      = 8

LEAGUE_SCALE           = 0.30
MAX_KEY_PLAYERS        = 16
CORE_START_RATE        = 0.6

MARKET_1X2             = 1

# ── UNDER 2.5 TIER THRESHOLDS ─────────────────────────────────────────────────
U25_TIER1_SCORE        = 70    
U25_TIER2_SCORE        = 55    
U25_TIER3_SCORE        = 40    

# ── UNDER 3.5 TIER THRESHOLDS ─────────────────────────────────────────────────
U35_TIER1_SCORE        = 75
U35_TIER2_SCORE        = 60
U35_TIER3_SCORE        = 45

# ── KEEPER WALL THRESHOLD ─────────────────────────────────────────────────────
GK_ELITE_CPG           = 1.10   
GK_AVERAGE_CPG         = 1.40   

# ==============================================================================
# TITANIUM HTTP HELPER 
# ==============================================================================
def GET(path, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_KEY)
    url = f"{BASE_URL}{path}"
    
    max_retries = 5
    backoff = 2.0
    
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                return {"data": []}
        except Exception:
            time.sleep(backoff)
            continue
            
    return {"data": []}

def sleep_short():
    time.sleep(REQUEST_DELAY_SEC)

# ==============================================================================
# PAGINATION HELPERS
# ==============================================================================
def fetch_fixtures_for_date(date_str):
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/date/{date_str}",
            params={
                "include":  "participants;scores;lineups;formations;statistics",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added: break
        page += 1; sleep_short()
    return all_fx

def fetch_last_finished_fixtures_for_team(team_id, max_needed=200):
    end_dt   = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=TEAM_LOOKBACK_DAYS)
    all_fx   = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "participants;scores;state;lineups;formations;statistics",
                "filters":  "fixtureStates:5",
                "sortBy":   "starting_at",
                "order":    "desc",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added or len(all_fx) >= max_needed: break
        page += 1; sleep_short()
    return (all_fx or [])[:max_needed]

def fetch_last_h2h(team1, team2, n=LAST_N_GAMES):
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/head-to-head/{team1}/{team2}",
            params={
                "include":  "scores;participants",
                "filters":  "fixtureStates:5",
                "sortBy":   "starting_at",
                "order":    "desc",
                "per_page": 50, "page": page
            }
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added or len(all_fx) >= n: break
        page += 1; sleep_short()
    return (all_fx or [])[:n]

# ==============================================================================
# SAFE HELPERS & ODDS SNIPER 
# ==============================================================================
def safe_int(x, default=None):
    try:
        if x is None: return default
        return int(x)
    except Exception: return default

def sniper_fetch_odds(fixture_id):
    try:
        data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    except Exception:
        return {"h": None, "d": None, "a": None}
    odds_list = data.get("data", [])
    res = {"h": None, "d": None, "a": None}
    for o in odds_list:
        if o.get("market_id") == MARKET_1X2:
            lbl = str(o.get("label", "")).lower()
            try: val = float(o.get("value"))
            except: continue
            if ("1" in lbl or "home" in lbl) and res["h"] is None:
                res["h"] = val
            elif ("x" in lbl or "draw" in lbl) and res["d"] is None:
                res["d"] = val
            elif ("2" in lbl or "away" in lbl) and res["a"] is None:
                res["a"] = val
    return res

# ==============================================================================
# SCORE EXTRACTION HELPERS 
# ==============================================================================
def is_team_home(fx, team_id):
    for p in fx.get("participants", []):
        if safe_int(p.get("id")) == safe_int(team_id):
            loc = (p.get("meta") or {}).get("location")
            if loc == "home": return True
            if loc == "away": return False
    parts = fx.get("participants", [])
    if len(parts) >= 2:
        if safe_int(parts[0].get("id")) == safe_int(team_id): return True
        if safe_int(parts[1].get("id")) == safe_int(team_id): return False
    return False

def extract_final_goals_from_scores(scores):
    home = away = None
    for entry in (scores or []):
        if not isinstance(entry, dict): continue
        s    = entry.get("score") or entry
        desc = str(entry.get("description", s.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]): continue
        part = s.get("participant") or entry.get("participant")
        g    = s.get("goals") if isinstance(s, dict) else entry.get("goals")
        try:
            if isinstance(g, str) and g.isdigit(): g = int(g)
        except: pass
        if isinstance(g, int):
            if part == "home":  home = g if home is None else max(home, g)
            elif part == "away": away = g if away is None else max(away, g)
    return home, away

def get_team_and_opponent_goals_from_fixture(fx, team_id):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    if hg is None or ag is None: return None, None
    return (hg, ag) if is_team_home(fx, team_id) else (ag, hg)

def is_u25(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and (hg + ag) < 3

def is_u35(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and (hg + ag) < 4

# ==============================================================================
# FORMATION / LINEUP HELPERS
# ==============================================================================
def extract_formation_from_fixture(fx, team_id):
    for f in fx.get("formations", []) or []:
        pid = safe_int(f.get("participant_id") or f.get("participantId"))
        if pid is not None and safe_int(team_id) is not None and pid == safe_int(team_id):
            return f.get("formation")
    return None

def extract_starters_from_fixture(fx, team_id):
    starters = []
    for l in fx.get("lineups", []) or []:
        t_id   = safe_int(l.get("team_id") or l.get("teamId"))
        t_type = safe_int(l.get("type_id") or l.get("typeId"))
        if (t_id is not None and safe_int(team_id) is not None and
                t_id == safe_int(team_id) and
                (t_type is None or t_type == 11)):
            starters.append({
                "player_id":     l.get("player_id") or l.get("playerId"),
                "player_name":   l.get("player_name") or l.get("playerName"),
                "jersey_number": l.get("jersey_number") or l.get("jerseyNumber"),
                "position_id":   l.get("position_id") or l.get("positionId")
            })
    return starters

def identify_key_players_from_history(recent_lineups, threshold_frac=CORE_START_RATE):
    counts, names = Counter(), {}
    valid = [l for l in recent_lineups if isinstance(l, list) and len(l) >= 8]
    for starters in valid:
        for p in starters:
            pid = p.get("player_id")
            if pid:
                counts[pid] += 1
                names[pid]   = p.get("player_name", names.get(pid))
    if not valid: return {}
    min_starts = math.ceil(len(valid) * threshold_frac)
    core = {
        pid: {"player_id": pid, "player_name": names.get(pid, "Unknown"),
              "starts": cnt}
        for pid, cnt in counts.items() if cnt >= min_starts
    }
    return dict(sorted(core.items(), key=lambda x: -x[1]["starts"])[:MAX_KEY_PLAYERS])

def compute_rotation_score(recent_starts, today_ids):
    if not recent_starts or not today_ids: return 0.0
    core_players = {pid for pid, c in recent_starts.items() if c >= 2}
    if not core_players: return 0.0
    overlap = len(core_players.intersection(set(today_ids)))
    return round(overlap / len(core_players), 2)

# ==============================================================================
# POISSON & MONTE CARLO (FLIPPED FOR UNDERS)
# ==============================================================================
def poisson_pmf(k, lam):
    if lam < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except Exception: return 0.0

def generate_scoreline_predictions(lh, la, n_sim=SIMULATION_SIZE):
    if n_sim <= 0:
        return {"u25_prob": 0.0, "u35_prob": 0.0, "sim_count": 0}
    np.random.seed(None)
    hg = np.random.poisson(lh, size=n_sim)
    ag = np.random.poisson(la, size=n_sim)

    u25 = u35 = 0

    for h, a in zip(hg, ag):
        total = h + a
        if total <= 2:  u25 += 1   
        if total <= 3:  u35 += 1   

    summary = {
        "u25_prob": u25 / n_sim,
        "u35_prob": u35 / n_sim,
        "sim_count": n_sim
    }
    return summary

# ==============================================================================
# FATIGUE ESTIMATOR 
# ==============================================================================
def parse_fixture_datetime(fx):
    dtcands = []
    if fx.get("starting_at"):                               dtcands.append(fx["starting_at"])
    if (fx.get("time") and isinstance(fx.get("time"), dict)
            and fx["time"].get("starting_at")):             dtcands.append(fx["time"]["starting_at"])
    if fx.get("date"):                                      dtcands.append(fx["date"])
    for s in dtcands:
        if not s: continue
        try:
            if isinstance(s, str):
                ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
                try: dt = datetime.fromisoformat(ss)
                except:
                    try: dt = datetime.strptime(ss, "%Y-%m-%d %H:%M:%S")
                    except:
                        try: dt = datetime.strptime(ss, "%Y-%m-%d")
                        except: dt = None
            elif isinstance(s, (int, float)):
                dt = datetime.fromtimestamp(int(s), tz=timezone.utc)
            else: dt = None
            if dt:
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                else:                 dt = dt.astimezone(timezone.utc)
                return dt
        except Exception: continue
    return None

def estimate_fatigue_from_schedules(recent_fixtures, team_id, rotation_score):
    now       = datetime.now(timezone.utc)
    played_14 = played_7 = 0
    cutoff    = now - timedelta(days=FATIGUE_WINDOW_DAYS)
    for f in recent_fixtures or []:
        if not any(p.get("id") == team_id for p in f.get("participants", [])): continue
        dt = parse_fixture_datetime(f)
        if not dt or dt < cutoff: continue
        days = (now - dt).days
        if days <= 14: played_14 += 1
        if days <= 7:  played_7  += 1
    s14  = min(1.0, played_14 / 6.0)
    s7   = min(1.0, played_7  / 4.0)
    try: rot = float(rotation_score)
    except: rot = 0.0
    eff_rot = 1.0 - min(1.0, max(0.0, rot))
    fatigue = (0.6 * s14 + 0.4 * s7) * (0.7 + 0.3 * eff_rot)
    return min(1.0, max(0.0, fatigue))

# ==============================================================================
# LEAGUE UNDER 2.5 WEIGHT (TTL CACHED FOR MASSIVE API SAVINGS)
# ==============================================================================
def compute_league_under25_weight(league_id, days_lookback=180):
    cache_file = os.path.join(DATA_DIR, "league_weights_cache.json")
    cache_data = {}
    
    # 1. Load existing cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc)
    lid_str = str(league_id)

    # 2. Check if league is in cache and less than 7 days old
    if lid_str in cache_data:
        try:
            last_updated = datetime.fromisoformat(cache_data[lid_str]["last_updated"])
            if (now_utc - last_updated).days < 7:
                return cache_data[lid_str]["weight"]
        except Exception:
            pass

    # 3. If missing or expired, fetch from API (Reduced lookback to 180 days to save API)
    end_dt   = now_utc.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, 180))
    
    all_fx = []; seen = set(); page = 1
    while True:
        data = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{league_id}",
            params={"include": "scores", "per_page": 50, "page": page}
        )
        fx = data.get("data", [])
        if not fx: break
        added = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid); all_fx.append(f); added = True
        if not added: break
        page += 1; sleep_short()
        
    total = under25 = 0
    for fx in all_fx:
        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is None or ag is None: continue
        total += 1
        if hg + ag < 3: under25 += 1
        
    weight = 0.0
    if total > 0:
        weight = round((under25 / total) * LEAGUE_SCALE, 4)

    # 4. Save to cache
    cache_data[lid_str] = {
        "weight": weight,
        "last_updated": now_utc.isoformat()
    }
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception:
        pass

    return weight

# ==============================================================================
# KEEPER WALL ENGINE (FLIPPED FROM VULNERABILITY TO SOLIDITY)
# ==============================================================================
GK_SQUAD_CACHE = {}    

def get_squad_data_for_gk(team_id, check_date_str):
    tid_str = str(team_id)
    if tid_str in GK_SQUAD_CACHE:
        cached = GK_SQUAD_CACHE[tid_str]
        if isinstance(cached, dict) and "players" in cached and len(cached["players"]) > 0:
            return cached

    end_dt   = (datetime.strptime(check_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = (datetime.strptime(check_date_str, "%Y-%m-%d") - timedelta(days=GK_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include": "lineups.details.type;lineups.player.position;scores;participants",
                "filter": "fixtureStates:5",
                "per_page": 40
            }
        )
    except Exception:
        return {"players": {}, "team_avg_leak": 1.2}

    player_stats        = {}
    team_total_conceded = 0
    valid_fixtures      = 0

    RATING_ID      = 118
    MINUTES_ID     = 119
    STAR_FACTOR_ID = 211

    for fx in resp.get("data", []):
        hid = aid = None
        for pt in fx.get("participants", []):
            if pt.get("meta", {}).get("location") == "home": hid = str(pt["id"])
            else: aid = str(pt["id"])

        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is not None and ag is not None:
            opp_goals = ag if str(team_id) == hid else hg
            team_total_conceded += opp_goals
            valid_fixtures      += 1

        for l in fx.get("lineups", []):
            if str(l.get("team_id")) != str(team_id): continue
            if l.get("player_id") is None:            continue
            p_obj = l.get("player")
            if not p_obj:                             continue

            pid   = str(l["player_id"])
            m_val = r_val = star = 0
            c_val = -1.0

            for d in l.get("details", []):
                try: tid_d = int(d.get("type_id", 0))
                except: tid_d = 0
                raw_v = (d.get("data", {}).get("value") if isinstance(d.get("data"), dict) else d.get("value"))
                try: v = float(raw_v)
                except: v = 0
                
                if tid_d == MINUTES_ID: m_val = int(v)
                elif tid_d == RATING_ID: r_val = v
                elif tid_d == STAR_FACTOR_ID: star = 1
                elif "conceded" in str(d.get("type", {}).get("name", "")).lower(): c_val = v

            if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
            if c_val == -1.0 and hg is not None and ag is not None:
                c_val = ag if str(team_id) == hid else hg

            pos_name = "Unknown"
            if p_obj.get("position") and isinstance(p_obj["position"], dict):
                pos_name = p_obj["position"].get("name", "Unknown")

            if pid not in player_stats:
                player_stats[pid] = {
                    "name": p_obj.get("display_name", "Unknown"), "pos": pos_name,
                    "mins": 0, "ratings": [], "star": 0, "apps": 0, "conceded": 0
                }
            player_stats[pid]["mins"]     += m_val
            player_stats[pid]["apps"]     += 1
            player_stats[pid]["star"]     += star
            if r_val > 0: player_stats[pid]["ratings"].append(r_val)
            if c_val >= 0: player_stats[pid]["conceded"] += c_val

    team_avg_leak = (team_total_conceded / max(1, valid_fixtures) if valid_fixtures > 0 else 1.2)

    processed = {}
    for pid, d in player_stats.items():
        c_p90 = (d["conceded"] / max(1, d["mins"])) * 90 if d["mins"] > 0 else 0
        processed[pid] = {
            "id": pid, "name": d["name"], "pos": d["pos"],
            "apps": d["apps"], "mins": d["mins"], "c_p90": round(c_p90, 2)
        }

    result = {"players": processed, "team_avg_leak": team_avg_leak}
    GK_SQUAD_CACHE[tid_str] = result
    return result

def evaluate_gk_wall(team_id, today_fixture, check_date_str):
    sq_data   = get_squad_data_for_gk(team_id, check_date_str)
    squad_map = sq_data.get("players", {})
    avg_leak  = sq_data.get("team_avg_leak", 1.2)

    if not squad_map:
        return False, True, 1.5, "No squad data (proxy risk)"

    starting_gk_id = None
    is_expected_gk = False 

    for l in today_fixture.get("lineups", []) or []:
        if str(l.get("team_id")) != str(team_id): continue
        t_type = safe_int(l.get("type_id"))
        if t_type not in [11, None]: continue
        pid    = str(l.get("player_id", ""))
        if not pid: continue
        p_data = squad_map.get(pid, {})
        if p_data.get("pos") == "Goalkeeper":
            starting_gk_id = pid
            break

    if not starting_gk_id:
        for l in today_fixture.get("lineups", []) or []:
            if str(l.get("team_id")) != str(team_id): continue
            if str(l.get("formation_position", "")) == "1":
                pid    = str(l.get("player_id", ""))
                if pid and pid in squad_map:
                    starting_gk_id = pid
                    break

    if not starting_gk_id:
        gks = [p for p in squad_map.values() if p['pos'] == "Goalkeeper"]
        if gks:
            number_1_gk = sorted(gks, key=lambda x: x['mins'], reverse=True)[0]
            if number_1_gk['mins'] > 0:
                starting_gk_id = number_1_gk['id']
                is_expected_gk = True 

    if not starting_gk_id:
        return False, True, avg_leak, "Unlisted GK"

    starter = squad_map[starting_gk_id]
    apps    = starter.get("apps", 0)
    c_p90   = starter.get("c_p90", 0.0)
    
    prefix = "[Exp #1] " if is_expected_gk else ""

    if apps == 0:
        c_p90 = avg_leak
        
    is_elite = c_p90 <= GK_ELITE_CPG
    is_avg   = c_p90 <= GK_AVERAGE_CPG

    if is_elite:
        note = f"🧱 {prefix}ELITE WALL ({c_p90:.2f}/90)"
    elif is_avg:
        note = f"🛡️ {prefix}Solid Guard ({c_p90:.2f}/90)"
    else:
        note = f"⚠️ {prefix}Leaky ({c_p90:.2f}/90)"

    return is_elite, is_avg, round(c_p90, 2), note

# ==============================================================================
# UNDER 2.5 COMPOSITE SCORER
# ==============================================================================
def calculate_u25_score(
    u25_prob,              
    venue_u25_home,        
    venue_u25_away,        
    home_gk_cpg,           
    away_gk_cpg,           
    h2h_u25_rate,          
    combined_lambda,       
    fatigue_home,          
    fatigue_away,          
):
    sig1_raw   = min(1.0, u25_prob / 0.65)   
    sig1_score = sig1_raw * 30
    sig1_fired = u25_prob >= 0.50

    if combined_lambda <= 2.0:
        sig2_score, sig2_fired = 25.0, True
    elif combined_lambda >= 2.8:
        sig2_score, sig2_fired = 0.0, False
    else:
        sig2_raw = (2.8 - combined_lambda) / 0.8  
        sig2_score = sig2_raw * 25.0
        sig2_fired = combined_lambda <= 2.4

    if home_gk_cpg <= GK_ELITE_CPG and away_gk_cpg <= GK_ELITE_CPG:
        sig3_score, sig3_fired = 20.0, True
    elif home_gk_cpg <= GK_AVERAGE_CPG and away_gk_cpg <= GK_AVERAGE_CPG:
        sig3_score, sig3_fired = 12.0, True
    else:
        avg_cpg = (home_gk_cpg + away_gk_cpg) / 2.0
        if avg_cpg > 1.8: sig3_score = 0.0
        else:
            sig3_raw = max(0.0, (1.8 - avg_cpg) / 0.7) 
            sig3_score = sig3_raw * 10.0
        sig3_fired = avg_cpg <= 1.4

    venue_u25_combined = (venue_u25_home + venue_u25_away) / 2.0
    sig4_raw   = min(1.0, venue_u25_combined / 0.60)  
    sig4_score = sig4_raw * 15
    sig4_fired = venue_u25_combined >= 0.50

    avg_fatigue = (fatigue_home + fatigue_away) / 2.0
    sig5_score = avg_fatigue * 10.0
    sig5_fired = avg_fatigue >= 0.60

    total_score  = sig1_score + sig2_score + sig3_score + sig4_score + sig5_score
    signals_fired = sum([sig1_fired, sig2_fired, sig3_fired, sig4_fired, sig5_fired])

    breakdown = {
        "sig1_mc_u25":           round(sig1_score, 1),
        "sig2_lambda":           round(sig2_score, 1),
        "sig3_gk_wall":          round(sig3_score, 1),
        "sig4_venue_u25":        round(sig4_score, 1),
        "sig5_fatigue_boost":    round(sig5_score, 1),
        "signals_fired":         signals_fired,
        "venue_u25_combined":    round(venue_u25_combined, 3),
    }
    return round(total_score, 1), signals_fired, breakdown

def get_u25_tier(score, signals_fired):
    if score >= U25_TIER1_SCORE and signals_fired >= 4:
        return "🛡️ U2.5 TIER 1 — LOCK"
    elif score >= U25_TIER2_SCORE:
        return "✅ U2.5 TIER 2 — SOLID"
    elif score >= U25_TIER3_SCORE:
        return "📊 U2.5 TIER 3 — LEAN"
    else:
        return "⚪ U2.5 BELOW THRESHOLD"

# ==============================================================================
# UNDER 3.5 COMPOSITE SCORER
# ==============================================================================
def calculate_u35_score(
    u35_prob,              
    combined_lambda,       
    venue_u35_home,        
    venue_u35_away,        
    league_weight,         
    fatigue_home,          
    fatigue_away,          
    home_gk_cpg,           
    away_gk_cpg
):
    sig1_raw   = min(1.0, u35_prob / 0.85)
    sig1_score = sig1_raw * 35

    if combined_lambda <= 2.6: sig2_score = 25.0
    elif combined_lambda >= 3.3: sig2_score = 0.0
    else:
        sig2_raw = (3.3 - combined_lambda) / 0.7
        sig2_score = sig2_raw * 25.0

    venue_u35_combined = (venue_u35_home + venue_u35_away) / 2.0
    sig3_raw   = min(1.0, venue_u35_combined / 0.85)
    sig3_score = sig3_raw * 20

    sig4_score = min(10.0, league_weight * 33.3)

    avg_fatigue = (fatigue_home + fatigue_away) / 2.0
    avg_cpg = (home_gk_cpg + away_gk_cpg) / 2.0
    
    cpg_bonus = max(0.0, (1.8 - avg_cpg) / 0.7) * 5.0  
    fatigue_bonus = avg_fatigue * 5.0                  
    sig5_score = cpg_bonus + fatigue_bonus

    total_score = sig1_score + sig2_score + sig3_score + sig4_score + sig5_score
    total_score = max(0.0, min(100.0, total_score))

    breakdown = {
        "sig1_mc_u35":         round(sig1_score, 1),
        "sig2_lambda":         round(sig2_score, 1),
        "sig3_venue_u35":      round(sig3_score, 1),
        "sig4_league_weight":  round(sig4_score, 1),
        "sig5_fortress_boost": round(sig5_score, 1),
        "venue_u35_combined":  round(venue_u35_combined, 3),
    }
    return round(total_score, 1), breakdown

def get_u35_tier(score):
    if score >= U35_TIER1_SCORE:
        return "🧱 U3.5 TIER 1 — LOCK"
    elif score >= U35_TIER2_SCORE:
        return "✅ U3.5 TIER 2 — SOLID"
    elif score >= U35_TIER3_SCORE:
        return "📊 U3.5 TIER 3 — LEAN"
    else:
        return "⚪ U3.5 BELOW THRESHOLD"

# ==============================================================================
# 📦 WRAPPED CALLABLE ENGINE (UNDER 2.5 & UNDER 3.5)
# ==============================================================================
def run_unders_engine(target_date=None, verbose=False):
    """
    Executes the Flipped Under 2.5 & Under 3.5 Engine.
    Fully wrapped for the VS Code Pipeline.
    verbose=False keeps it silent for API/Aggregator calls.
    """
    if not API_KEY:
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n{'='*100}")
        print(f"  🛑 ALIENEDGE UNDER 2.5 & UNDER 3.5 DEFENSIVE ENGINE — {target_date}")
        print(f"  MC Trials: {SIMULATION_SIZE:,} | GK Lookback: {GK_LOOKBACK_DAYS}d")
        print(f"{'='*100}\n")

    fixtures = fetch_fixtures_for_date(target_date)
    if verbose: print(f"  Found {len(fixtures)} fixtures.\n")
    if not fixtures: return [], []

    league_cache = {}
    league_ids   = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    for lid in league_ids:
        try: league_cache[lid] = {"league_weight": compute_league_under25_weight(lid)}
        except Exception: league_cache[lid] = {"league_weight": 0.0}
        sleep_short()

    team_cache = {}
    u25_picks  = []
    u35_picks  = []

    for fx in fixtures:
        try:
            parts = fx.get("participants", []) or []
            if len(parts) < 2: continue

            home_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), parts[0])
            away_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), parts[1] if len(parts) > 1 else None)
            if away_p is None: continue

            home_id   = safe_int(home_p.get("id"))
            away_id   = safe_int(away_p.get("id"))
            home_name = home_p.get("name") or f"Team {home_id}"
            away_name = away_p.get("name") or f"Team {away_id}"
            league_id = fx.get("league_id")

            for tid in (home_id, away_id):
                if tid not in team_cache:
                    try: team_cache[tid] = fetch_last_finished_fixtures_for_team(tid)
                    except Exception: team_cache[tid] = []
                    sleep_short()

            lastN_home = [f for f in team_cache.get(home_id, []) if is_team_home(f, home_id)][:LAST_N_GAMES]
            lastN_away = [f for f in team_cache.get(away_id, []) if not is_team_home(f, away_id)][:LAST_N_GAMES]

            try: h2h = fetch_last_h2h(home_id, away_id, n=LAST_N_GAMES)
            except Exception: h2h = []

            def personal_goals_total(fixtures_list, tid):
                s = c = 0
                for f in fixtures_list or []:
                    tg, _ = get_team_and_opponent_goals_from_fixture(f, tid)
                    if tg is not None: s += tg; c += 1
                return float(s), int(c)

            def avg_conceded(fixtures_list, tid):
                vals = []
                for f in fixtures_list or []:
                    _, og = get_team_and_opponent_goals_from_fixture(f, tid)
                    if og is not None: vals.append(og)
                return float(np.mean(vals)) if vals else 0.0

            hpg, _  = personal_goals_total(lastN_home, home_id)
            apg, _  = personal_goals_total(lastN_away, away_id)
            hca     = avg_conceded(lastN_home, home_id)
            aca     = avg_conceded(lastN_away, away_id)

            raw_home_attack = hpg / max(1, len(lastN_home))
            raw_away_attack = apg / max(1, len(lastN_away))
            lambda_home     = max(0.05, (raw_home_attack + aca) / 2.0)
            lambda_away     = max(0.05, (raw_away_attack + hca) / 2.0)
            combined_lambda = lambda_home + lambda_away

            mc_summary = generate_scoreline_predictions(lambda_home, lambda_away, n_sim=SIMULATION_SIZE)
            u25_prob   = mc_summary.get("u25_prob", 0.0)
            u35_prob   = mc_summary.get("u35_prob", 0.0)

            def u_rate(fixtures_list, target):
                if not fixtures_list: return 0.0
                if target == 2.5: return round(sum(1 for f in fixtures_list if is_u25(f)) / len(fixtures_list), 3)
                if target == 3.5: return round(sum(1 for f in fixtures_list if is_u35(f)) / len(fixtures_list), 3)

            venue_u25_home = u_rate(lastN_home, 2.5)
            venue_u25_away = u_rate(lastN_away, 2.5)
            venue_u35_home = u_rate(lastN_home, 3.5)
            venue_u35_away = u_rate(lastN_away, 3.5)
            h2h_u25_rate   = u_rate(h2h, 2.5)

            _, _, h_gk_cpg, h_gk_note = evaluate_gk_wall(home_id, fx, target_date)
            _, _, a_gk_cpg, a_gk_note = evaluate_gk_wall(away_id, fx, target_date)
            sleep_short()

            h_recent_lin = [extract_starters_from_fixture(f, home_id) for f in lastN_home]
            a_recent_lin = [extract_starters_from_fixture(f, away_id) for f in lastN_away]
            h_core = identify_key_players_from_history(h_recent_lin)
            a_core = identify_key_players_from_history(a_recent_lin)
            h_today = [p.get("player_id") for p in extract_starters_from_fixture(fx, home_id)]
            a_today = [p.get("player_id") for p in extract_starters_from_fixture(fx, away_id)]
            h_rot = compute_rotation_score({k: v["starts"] for k, v in h_core.items()}, h_today)
            a_rot = compute_rotation_score({k: v["starts"] for k, v in a_core.items()}, a_today)
            
            fatigue_home = estimate_fatigue_from_schedules(team_cache.get(home_id, []), home_id, h_rot)
            fatigue_away = estimate_fatigue_from_schedules(team_cache.get(away_id, []), away_id, a_rot)
            league_weight = league_cache.get(league_id, {}).get("league_weight", 0.0)

            try: odds = sniper_fetch_odds(fx.get("id"))
            except Exception: odds = {"h": None, "d": None, "a": None}

            u25_score, signals_fired, u25_breakdown = calculate_u25_score(
                u25_prob        = u25_prob,
                venue_u25_home  = venue_u25_home,
                venue_u25_away  = venue_u25_away,
                home_gk_cpg     = h_gk_cpg,
                away_gk_cpg     = a_gk_cpg,
                h2h_u25_rate    = h2h_u25_rate,
                combined_lambda = combined_lambda,
                fatigue_home    = fatigue_home,
                fatigue_away    = fatigue_away,
            )
            u25_tier = get_u25_tier(u25_score, signals_fired)

            u35_score, u35_breakdown = calculate_u35_score(
                u35_prob        = u35_prob,
                combined_lambda = combined_lambda,
                venue_u35_home  = venue_u35_home,
                venue_u35_away  = venue_u35_away,
                league_weight   = league_weight,
                fatigue_home    = fatigue_home,
                fatigue_away    = fatigue_away,
                home_gk_cpg     = h_gk_cpg,
                away_gk_cpg     = a_gk_cpg,
            )
            u35_tier = get_u35_tier(u35_score)

            base_record = {
                "date":              target_date,
                "fixture_id":        fx.get("id"),
                "fixture":           f"{home_name} vs {away_name}",
                "league_id":         league_id,
                "home_team":         home_name,
                "away_team":         away_name,
                "combined_lambda":   round(combined_lambda, 3),
                "mc_u25_prob":       round(u25_prob, 4),
                "mc_u35_prob":       round(u35_prob, 4),
                "home_gk_cpg":       h_gk_cpg,
                "away_gk_cpg":       a_gk_cpg,
                "home_gk_note":      h_gk_note,
                "away_gk_note":      a_gk_note,
                "fatigue_home":      round(fatigue_home, 3),
                "fatigue_away":      round(fatigue_away, 3),
                "draw_odds":         odds.get("d"),
            }

            u25_picks.append({**base_record, "u25_score": u25_score, "u25_signals_fired": signals_fired, "u25_tier": u25_tier})
            u35_picks.append({**base_record, "u35_score": u35_score, "u35_tier": u35_tier})

        except Exception:
            continue

    if not u25_picks:
        if verbose: print("\n  No picks generated.")
        return [], []

    tier_order_u25 = {"🛡️ U2.5 TIER 1 — LOCK": 1, "✅ U2.5 TIER 2 — SOLID": 2, "📊 U2.5 TIER 3 — LEAN": 3, "⚪ U2.5 BELOW THRESHOLD": 4}
    tier_order_u35 = {"🧱 U3.5 TIER 1 — LOCK": 1, "✅ U3.5 TIER 2 — SOLID": 2, "📊 U3.5 TIER 3 — LEAN": 3, "⚪ U3.5 BELOW THRESHOLD": 4}

    df_u25 = pd.DataFrame(u25_picks)
    df_u35 = pd.DataFrame(u35_picks)

    df_u25["tier_rank"] = df_u25["u25_tier"].map(tier_order_u25).fillna(99)
    df_u25 = df_u25.sort_values(["tier_rank", "u25_score", "u25_signals_fired"], ascending=[True, False, False]).reset_index(drop=True)

    df_u35["tier_rank"] = df_u35["u35_tier"].map(tier_order_u35).fillna(99)
    df_u35 = df_u35.sort_values(["tier_rank", "u35_score"], ascending=[True, False]).reset_index(drop=True)

    u25_csv_path  = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U25_PICKS_{target_date}.csv")
    u35_csv_path  = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U35_PICKS_{target_date}.csv")
    df_u25.drop(columns=["tier_rank"], errors="ignore").to_csv(u25_csv_path, index=False)
    df_u35.drop(columns=["tier_rank"], errors="ignore").to_csv(u35_csv_path, index=False)

    if verbose:
        print(f"\n{'🛡️'*50}\n  UNDER 2.5 DEFENSIVE BOARD — {target_date}\n{'🛡️'*50}")
        u25_show_cols = ["fixture", "u25_tier", "u25_score", "u25_signals_fired", "mc_u25_prob", "combined_lambda", "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away"]
        pd.set_option("display.max_rows", None); pd.set_option("display.max_columns", None); pd.set_option("display.width", 240)
        
        for tier_name, group in df_u25.groupby("u25_tier", sort=False):
            print(f"\n  ── {tier_name} ──\n{group[u25_show_cols].to_string(index=False)}")

        print(f"\n{'🧱'*50}\n  UNDER 3.5 FORTRESS BOARD — {target_date}\n{'🧱'*50}")
        u35_show_cols = ["fixture", "u35_tier", "u35_score", "mc_u35_prob", "combined_lambda", "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away"]
        for tier_name, group in df_u35.groupby("u35_tier", sort=False):
            print(f"\n  ── {tier_name} ──\n{group[u35_show_cols].to_string(index=False)}")

        print(f"\n  💾 U2.5 picks saved: {u25_csv_path}")
        print(f"  💾 U3.5 picks saved: {u35_csv_path}")

    return df_u25.to_dict(orient="records"), df_u35.to_dict(orient="records")

if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_unders_engine(target if target else None, verbose=True)