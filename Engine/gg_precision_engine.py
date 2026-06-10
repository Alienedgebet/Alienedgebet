import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta, timezone
import math
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

# ==============================================================================
# CONFIGURATION
# ==============================================================================
API_KEY  = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
BASE_URL = "https://api.sportmonks.com/v3/football"

# --- 🚨 FIXED FOR GOOGLE COLAB & VS CODE COMPATIBILITY 🚨 ---
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
TARGET_DATE            = None

SIMULATION_SIZE        = 10_000  
MAX_GOALS_DISPLAY      = 6
POISSON_MAX_GOALS      = 8

LEAGUE_SCALE           = 0.30
MAX_KEY_PLAYERS        = 16
CORE_START_RATE        = 0.6

MARKET_1X2             = 1

# ── GG TIER THRESHOLDS ───────────────────────────────────────────────────────
GG_TIER1_SCORE         = 68    
GG_TIER2_SCORE         = 50    
GG_TIER3_SCORE         = 35    

# ── OVER 1.5 TIER THRESHOLDS ─────────────────────────────────────────────────
O15_TIER1_SCORE        = 70
O15_TIER2_SCORE        = 52
O15_TIER3_SCORE        = 38

# ── KEEPER LIABILITY THRESHOLD ──────────────────────────────────────────────
GK_LIABILITY_CPG       = 1.50   
GK_CRITICAL_CPG        = 2.00   

# ==============================================================================
# HTTP HELPER
# ==============================================================================
def GET(path, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_KEY)
    url = f"{BASE_URL}{path}"
    r   = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    return r.json()

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

def is_btts(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and hg > 0 and ag > 0

def is_o15(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
    return hg is not None and ag is not None and (hg + ag) >= 2

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

def parse_formation(formation_str):
    if not formation_str or not isinstance(formation_str, str): return None
    parts  = formation_str.replace(":", "-").replace(" ", "-").split("-")
    digits = [int(x) for x in parts if x.isdigit()]
    if not digits: return None
    defenders   = digits[0]
    forwards    = digits[-1]
    midfielders = (sum(digits[1:-1]) if len(digits) > 2
                   else max(0, 10 - defenders - forwards))
    return {
        "defenders":   defenders,
        "midfielders": midfielders,
        "forwards":    forwards,
        "parts":       digits
    }

def formation_offense_score(form):
    if not form: return 0, "Unknown"
    d, m, f = form["defenders"], form["midfielders"], form["forwards"]
    score = 0
    if f >= 3:  score += 2
    elif f == 2: score += 1
    if m >= 5:  score += 1
    if m >= 3 and f >= 1: score += 1
    if d >= 5:  score = max(0, score - 1)
    score = min(5, score)
    return score, ("Offensive" if score >= 4 else
                   "Neutral"   if score >= 2 else "Defensive")

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
# POISSON & MONTE CARLO
# ==============================================================================
def poisson_pmf(k, lam):
    if lam < 0: return 0.0
    try: return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except Exception: return 0.0

def poisson_draw_probability(lh, la, max_goals=POISSON_MAX_GOALS):
    prob = 0.0
    for k in range(0, max_goals + 1):
        prob += poisson_pmf(k, lh) * poisson_pmf(k, la)
    return min(1.0, prob)

def generate_scoreline_predictions(lh, la,
                                   n_sim=SIMULATION_SIZE,
                                   max_display=MAX_GOALS_DISPLAY):
    if n_sim <= 0:
        return {}, {
            "draw_prob": 0.0, "home_win_prob": 0.0, "away_win_prob": 0.0,
            "over25_prob": 0.0, "btts_prob": 0.0,
            "over15_prob": 0.0,   
            "sim_count": 0
        }
    np.random.seed(None)
    hg = np.random.poisson(lh, size=n_sim)
    ag = np.random.poisson(la, size=n_sim)

    counts               = {}
    over25 = btts = over15 = hom = draw = aw = 0

    for h, a in zip(hg, ag):
        key = (h, a) if h <= max_display and a <= max_display else ("Other",)
        counts[key] = counts.get(key, 0) + 1
        total = h + a
        if total >= 3:  over25  += 1
        if total >= 2:  over15  += 1   
        if h > 0 and a > 0: btts += 1
        if h > a: hom  += 1
        elif h == a: draw += 1
        else: aw += 1

    score_probs  = {k: v / n_sim for k, v in counts.items()}
    sorted_sc    = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)
    top1 = sorted_sc[0] if sorted_sc       else (None, 0.0)
    top2 = sorted_sc[1] if len(sorted_sc) > 1 else (None, 0.0)

    summary = {
        "draw_prob":      draw   / n_sim,
        "home_win_prob":  hom    / n_sim,
        "away_win_prob":  aw     / n_sim,
        "over25_prob":    over25 / n_sim,
        "over15_prob":    over15 / n_sim,
        "btts_prob":      btts   / n_sim,
        "sim_count":      n_sim
    }
    return {
        "score_probs": score_probs,
        "top1": top1,
        "top2": top2
    }, summary

def fmt_score_key(k):
    if k is None or k == ("Other",): return "Other"
    return f"{k[0]}–{k[1]}"

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
# LEAGUE OVER 2.5 WEIGHT (TTL CACHED)
# ==============================================================================
def compute_league_over25_weight(league_id, days_lookback=365):
    cache_file = os.path.join(DATA_DIR, "league_weights_over25_cache.json")
    cache_data = {}
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    now_utc = datetime.now(timezone.utc)
    lid_str = str(league_id)

    if lid_str in cache_data:
        try:
            last_updated = datetime.fromisoformat(cache_data[lid_str]["last_updated"])
            if (now_utc - last_updated).days < 7:
                return cache_data[lid_str]["weight"]
        except Exception:
            pass

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
        
    total = over = 0
    for fx in all_fx:
        hg, ag = extract_final_goals_from_scores(fx.get("scores", []))
        if hg is None or ag is None: continue
        total += 1
        if hg + ag >= 3: over += 1
        
    weight = 0.0
    if total > 0:
        weight = round((over / total) * LEAGUE_SCALE, 4)

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
# DRAW ENGINE HELPERS
# ==============================================================================
def draw_magnet_index(home_draws, away_draws, h2h_draws, total_h2h_played):
    def norm(x, t): return min(1.0, float(x) / float(t)) if t > 0 else 0.0
    home_score = norm(home_draws, LAST_N_GAMES)
    away_score = norm(away_draws, LAST_N_GAMES)
    h2h_score  = norm(h2h_draws, total_h2h_played) if total_h2h_played > 0 else 0.0
    if total_h2h_played == 0:
        return (home_score + away_score) / 2.0
    return (home_score + away_score + h2h_score) / 3.0

def parity_score(hpg, apg, hca, aca):
    try: gdiff = abs(float(hpg) - float(apg))
    except: gdiff = 999.0
    try: cdiff = abs(float(hca) - float(aca))
    except: cdiff = 999.0
    denom = max(1.0, max(hpg, apg, 1.0))
    gpar  = max(0.0, 1.0 - (gdiff / denom))
    cpar  = max(0.0, 1.0 - (cdiff / 3.0))
    return round(0.6 * gpar + 0.4 * cpar, 3)

def composite_draw_score(poisson_prob, dmi, league_balance,
                         league_weight, parity):
    score = (0.25 * poisson_prob + 0.35 * dmi + 0.30 * parity +
             0.06 * league_balance + 0.04 * league_weight)
    return float(min(1.0, max(0.0, score)))

# ==============================================================================
# KEEPER VULNERABILITY ENGINE (SQUAD CACHED)
# ==============================================================================
GK_SQUAD_CACHE = {}

def get_squad_data_for_gk(team_id, check_date_str):
    tid_str = str(team_id)
    if tid_str in GK_SQUAD_CACHE:
        cached = GK_SQUAD_CACHE[tid_str]
        if isinstance(cached, dict) and "players" in cached and \
           len(cached["players"]) > 0:
            return cached

    end_dt   = (datetime.strptime(check_date_str, "%Y-%m-%d")
                - timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = (datetime.strptime(check_date_str, "%Y-%m-%d")
                - timedelta(days=GK_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    try:
        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "lineups.details.type;lineups.player.position;"
                            "scores;participants",
                "filter":   "fixtureStates:5",
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
            if pt.get("meta", {}).get("location") == "home":
                hid = str(pt["id"])
            else:
                aid = str(pt["id"])

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
                try:
                    tid_d = int(d.get("type_id", 0))
                except: tid_d = 0
                raw_v = (d.get("data", {}).get("value")
                         if isinstance(d.get("data"), dict)
                         else d.get("value"))
                try: v = float(raw_v)
                except: v = 0
                if   tid_d == MINUTES_ID:     m_val = int(v)
                elif tid_d == RATING_ID:      r_val = v
                elif tid_d == STAR_FACTOR_ID: star  = 1
                elif "conceded" in str(
                    d.get("type", {}).get("name", "")
                ).lower():
                    c_val = v

            if m_val == 0 and str(l.get("formation_position")) == "1":
                m_val = 90
            if c_val == -1.0 and hg is not None and ag is not None:
                c_val = ag if str(team_id) == hid else hg

            pos_name = "Unknown"
            if p_obj.get("position") and isinstance(p_obj["position"], dict):
                pos_name = p_obj["position"].get("name", "Unknown")

            if pid not in player_stats:
                player_stats[pid] = {
                    "name":     p_obj.get("display_name", "Unknown"),
                    "pos":      pos_name,
                    "mins":     0, "ratings": [], "star": 0,
                    "apps":     0, "conceded": 0
                }
            player_stats[pid]["mins"]     += m_val
            player_stats[pid]["apps"]     += 1
            player_stats[pid]["star"]     += star
            if r_val > 0: player_stats[pid]["ratings"].append(r_val)
            if c_val >= 0: player_stats[pid]["conceded"] += c_val

    team_avg_leak = (team_total_conceded / max(1, valid_fixtures)
                     if valid_fixtures > 0 else 1.2)

    processed = {}
    for pid, d in player_stats.items():
        avg_r  = (sum(d["ratings"]) / len(d["ratings"])
                  if d["ratings"] else 6.0)
        worth  = (d["apps"] * 8000) + (d["mins"] * avg_r) + (d["star"] * 5000)
        c_p90  = (d["conceded"] / max(1, d["mins"])) * 90 if d["mins"] > 0 else 0
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
    GK_SQUAD_CACHE[tid_str] = result
    return result

def calculate_gk_vulnerability(team_id, today_fixture, check_date_str):
    sq_data   = get_squad_data_for_gk(team_id, check_date_str)
    squad_map = sq_data.get("players", {})
    avg_leak  = sq_data.get("team_avg_leak", 1.2)

    if not squad_map:
        return 65.0, True, "No squad data (proxy risk)", 1.5

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
        return 65.0, True, "Unlisted GK (proxy risk)", avg_leak

    starter = squad_map[starting_gk_id]
    apps    = starter.get("apps", 0)
    c_p90   = starter.get("c_p90", 0.0)

    prefix = "[Exp #1] " if is_expected_gk else ""

    if apps == 0:
        c_p90        = avg_leak
        is_liability = c_p90 >= GK_LIABILITY_CPG
        status_note  = f"{prefix}No data — team avg {c_p90:.2f}/90"
        vuln_score   = 45.0 if is_liability else 10.0

    elif c_p90 >= GK_CRITICAL_CPG:
        is_liability = True
        status_note  = f"⚠️ {prefix}CRITICAL LEAK ({c_p90:.2f}/90)"
        vuln_score   = max(80.0, min(100.0, c_p90 * 25))

    elif c_p90 >= GK_LIABILITY_CPG:
        is_liability = True
        status_note  = f"{prefix}Proven liability ({c_p90:.2f}/90)"
        vuln_score   = min(100.0, c_p90 * 25)

    else:
        is_liability = False
        status_note  = f"{prefix}Solid form ({c_p90:.2f}/90)"
        vuln_score   = max(0.0, c_p90 * 25)

    return round(vuln_score, 1), is_liability, status_note, round(c_p90, 2)

# ==============================================================================
# GG COMPOSITE SCORER
# ==============================================================================
def calculate_gg_score(
    btts_prob,             # float 0-1, from Monte Carlo
    venue_btts_home,       # float 0-1, home BTTS rate at home venue
    venue_btts_away,       # float 0-1, away BTTS rate at away venue
    home_gk_is_liability,  # bool
    away_gk_is_liability,  # bool
    home_gk_cpg,           # float, home GK goals conceded per 90
    away_gk_cpg,           # float, away GK goals conceded per 90
    h2h_btts_rate,         # float 0-1
    lambda_home,           # float, expected home goals
    lambda_away,           # float, expected away goals
):
    sig1_raw   = min(1.0, btts_prob / 0.60)   
    sig1_score = sig1_raw * 30
    sig1_fired = btts_prob >= 0.40

    venue_btts_combined = (venue_btts_home + venue_btts_away) / 2.0
    sig2_raw   = min(1.0, venue_btts_combined / 0.60)  
    sig2_score = sig2_raw * 25
    sig2_fired = venue_btts_combined >= 0.40

    if home_gk_is_liability and away_gk_is_liability:
        sig3_score = 20.0
        sig3_fired = True
    elif home_gk_is_liability or away_gk_is_liability:
        sig3_score = 12.0
        sig3_fired = True
    else:
        avg_cpg    = (home_gk_cpg + away_gk_cpg) / 2.0
        sig3_raw   = min(1.0, avg_cpg / GK_LIABILITY_CPG)
        sig3_score = sig3_raw * 8.0   
        sig3_fired = avg_cpg >= 1.0

    sig4_raw   = min(1.0, h2h_btts_rate / 0.60)  
    sig4_score = sig4_raw * 15
    sig4_fired = h2h_btts_rate >= 0.40

    home_gap  = max(0.0, lambda_home - 1.0)
    away_gap  = max(0.0, lambda_away - 1.0)
    dir_score = min(1.0, (home_gap + away_gap) / 1.5)  
    sig5_score = dir_score * 10
    sig5_fired = lambda_home >= 1.0 and lambda_away >= 1.0

    total_score  = sig1_score + sig2_score + sig3_score + sig4_score + sig5_score
    signals_fired = sum([sig1_fired, sig2_fired, sig3_fired,
                         sig4_fired, sig5_fired])

    breakdown = {
        "sig1_mc_btts":          round(sig1_score, 1),
        "sig2_venue_btts":       round(sig2_score, 1),
        "sig3_gk_vuln":          round(sig3_score, 1),
        "sig4_h2h_btts":         round(sig4_score, 1),
        "sig5_directional":      round(sig5_score, 1),
        "signals_fired":         signals_fired,
        "venue_btts_combined":   round(venue_btts_combined, 3),
        "h2h_btts_rate":         round(h2h_btts_rate, 3),
    }
    return round(total_score, 1), signals_fired, breakdown

def get_gg_tier(gg_score, signals_fired):
    if gg_score >= GG_TIER1_SCORE and signals_fired >= 4:
        return "💎 GG TIER 1 — LOCK"
    elif gg_score >= GG_TIER1_SCORE and signals_fired == 3:
        return "🔥 GG TIER 1 — HIGH CONFIDENCE"
    elif gg_score >= GG_TIER2_SCORE:
        return "✅ GG TIER 2 — SOLID"
    elif gg_score >= GG_TIER3_SCORE:
        return "📊 GG TIER 3 — LEAN"
    else:
        return "⚪ GG BELOW THRESHOLD"

# ==============================================================================
# OVER 1.5 COMPOSITE SCORER
# ==============================================================================
def calculate_o15_score(
    lambda_home,           
    lambda_away,           
    mc_over15_prob,        
    venue_goals_avg_home,  
    venue_goals_avg_away,  
    league_weight,         
    fatigue_home,          
    fatigue_away,
    home_scored_total,
    away_scored_total,
    home_conceded_total,
    away_conceded_total,
    home_gk_cpg,
    away_gk_cpg,
    home_gk_liable,
    away_gk_liable,
    h2h_o15_rate
):
    """
    100-Point Over 1.5 Precision Scoring Engine.
    Fully integrated with:
    - User's Goal Form thresholds (Scoring >= 6 & Conceding >= 5)
    - Goalkeeper Wall vs Liability leaks
    - H2H over 1.5 history ratios
    - Direct double attacking intent
    """
    combined_lambda = lambda_home + lambda_away
    sig1_raw   = min(1.0, combined_lambda / 2.5)
    sig1_score = sig1_raw * 30

    sig2_raw   = min(1.0, mc_over15_prob / 0.75)
    sig2_score = sig2_raw * 20

    combined_venue_avg = (venue_goals_avg_home + venue_goals_avg_away) / 2.0
    sig3_raw   = min(1.0, combined_venue_avg / 2.5)
    sig3_score = sig3_raw * 15

    sig4_score = min(5.0, league_weight * 33.3)

    max_fatigue   = max(fatigue_home, fatigue_away)
    fatigue_deduct = max_fatigue * 5.0
    sig5_score    = -round(fatigue_deduct, 1)

    if home_gk_liable and away_gk_liable:
        gk_bonus = 10.0  
    elif home_gk_liable or away_gk_liable:
        gk_bonus = 5.0
    elif home_gk_cpg <= 1.10 and away_gk_cpg <= 1.10:
        gk_bonus = -5.0  
    else:
        gk_bonus = 0.0

    h2h_bonus = h2h_o15_rate * 10.0

    if lambda_home >= 1.00 and lambda_away >= 1.00:
        intent_bonus = 5.0
    elif lambda_home < 0.40 or lambda_away < 0.40:
        intent_bonus = -5.0  
    else:
        intent_bonus = 0.0

    if home_scored_total >= 6.0 and away_scored_total >= 6.0:
        form_scored_bonus = 10.0  
    elif home_scored_total >= 5.0 and away_scored_total >= 5.0:
        form_scored_bonus = 5.0
    elif home_scored_total < 4.0 or away_scored_total < 4.0:
        form_scored_bonus = -10.0  
    else:
        form_scored_bonus = 0.0

    if home_conceded_total >= 5.0 and away_conceded_total >= 5.0:
        form_conceded_bonus = 10.0  
    elif home_conceded_total < 4.0 or away_conceded_total < 4.0:
        form_conceded_bonus = -10.0  
    else:
        form_conceded_bonus = 0.0

    total_score = (sig1_score + sig2_score + sig3_score + sig4_score + sig5_score + 
                   gk_bonus + h2h_bonus + intent_bonus + form_scored_bonus + form_conceded_bonus)
    total_score = max(0.0, min(100.0, total_score))

    breakdown = {
        "sig1_combined_lambda":   round(sig1_score, 1),
        "sig2_mc_over15":         round(sig2_score, 1),
        "sig3_venue_goals_avg":   round(sig3_score, 1),
        "sig4_league_weight":     round(sig4_score, 1),
        "sig5_fatigue_penalty":   round(sig5_score, 1),
        "gk_leak_bonus":          round(gk_bonus, 1),
        "h2h_matchup_bonus":      round(h2h_bonus, 1),
        "intent_ratio_bonus":     round(intent_bonus, 1),
        "user_form_scoring":      round(form_scored_bonus, 1),
        "user_form_conceding":    round(form_conceded_bonus, 1),
        "combined_lambda":        round(combined_lambda, 3),
        "combined_venue_goals_avg": round(combined_venue_avg, 3),
        "h2h_o15_rate":           round(h2h_o15_rate, 3)
    }
    return round(total_score, 1), breakdown

def get_o15_tier(o15_score):
    if o15_score >= O15_TIER1_SCORE:
        return "💎 O1.5 TIER 1 — LOCK"
    elif o15_score >= O15_TIER2_SCORE:
        return "✅ O1.5 TIER 2 — SOLID"
    elif o15_score >= O15_TIER3_SCORE:
        return "📊 O1.5 TIER 3 — LEAN"
    else:
        return "⚪ O1.5 BELOW THRESHOLD"

# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def run_gg_o15_engine(target_date=None, verbose=False):
    global TARGET_DATE
    TARGET_DATE = target_date or TARGET_DATE

    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("Set API_KEY and re-run.")
        return [], []

    if TARGET_DATE is None:
        TARGET_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n{'='*100}")
        print(f"  🔬 ALIENEDGE GG & OVER 1.5 PRECISION ENGINE — {TARGET_DATE}")
        print(f"  MC Trials: {SIMULATION_SIZE:,} | GK Lookback: {GK_LOOKBACK_DAYS}d")
        print(f"{'='*100}\n")

    fixtures = fetch_fixtures_for_date(TARGET_DATE)
    if verbose:
        print(f"  Found {len(fixtures)} fixtures.\n")
    if not fixtures: return [], []

    # League cache
    league_cache = {}
    league_ids   = {fx.get("league_id") for fx in fixtures
                    if fx.get("league_id")}
    for lid in league_ids:
        try:
            league_cache[lid] = {
                "league_weight": compute_league_over25_weight(lid)
            }
        except Exception:
            league_cache[lid] = {"league_weight": 0.0}
        sleep_short()

    # Team fixture cache
    team_cache = {}

    gg_picks  = []
    o15_picks = []

    for fx in fixtures:
        try:
            parts = fx.get("participants", []) or []
            if len(parts) < 2: continue

            home_p = next(
                (p for p in parts
                 if (p.get("meta") or {}).get("location") == "home"),
                parts[0]
            )
            away_p = next(
                (p for p in parts
                 if (p.get("meta") or {}).get("location") == "away"),
                parts[1] if len(parts) > 1 else None
            )
            if away_p is None: continue

            home_id   = safe_int(home_p.get("id"))
            away_id   = safe_int(away_p.get("id"))
            home_name = home_p.get("name") or f"Team {home_id}"
            away_name = away_p.get("name") or f"Team {away_id}"
            league_id = fx.get("league_id")

            # ── TEAM FIXTURE CACHE ────────────────────────────────────────
            for tid in (home_id, away_id):
                if tid not in team_cache:
                    try:
                        team_cache[tid] = \
                            fetch_last_finished_fixtures_for_team(tid)
                    except Exception:
                        team_cache[tid] = []
                    sleep_short()

            # ── VENUE-SPECIFIC LAST N ─────────────────────────────────────
            lastN_home = [
                f for f in team_cache.get(home_id, [])
                if is_team_home(f, home_id)
            ][:LAST_N_GAMES]

            lastN_away = [
                f for f in team_cache.get(away_id, [])
                if not is_team_home(f, away_id)
            ][:LAST_N_GAMES]

            # ── H2H ──────────────────────────────────────────────────────
            try:
                h2h = fetch_last_h2h(home_id, away_id, n=LAST_N_GAMES)
            except Exception:
                h2h = []

            # ── LAMBDA CALCULATION (from draw engine, unchanged) ──────────
            def personal_goals_total(fixtures_list, tid):
                s = c = 0
                for f in fixtures_list or []:
                    tg, _ = get_team_and_opponent_goals_from_fixture(f, tid)
                    if tg is not None: s += tg; c += 1
                return float(s), int(c)

            def personal_conceded_total(fixtures_list, tid):
                s = c = 0
                for f in fixtures_list or []:
                    _, og = get_team_and_opponent_goals_from_fixture(f, tid)
                    if og is not None: s += og; c += 1
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

            home_scored_total, _ = personal_goals_total(lastN_home, home_id)
            away_scored_total, _ = personal_goals_total(lastN_away, away_id)
            home_conceded_total, _ = personal_conceded_total(lastN_home, home_id)
            away_conceded_total, _ = personal_conceded_total(lastN_away, away_id)

            raw_home_attack = hpg / max(1, len(lastN_home))
            raw_away_attack = apg / max(1, len(lastN_away))
            lambda_home     = max(0.05, (raw_home_attack + aca) / 2.0)
            lambda_away     = max(0.05, (raw_away_attack + hca) / 2.0)

            # ── MONTE CARLO ───────────────────────────────────────────────
            _, mc_summary = generate_scoreline_predictions(
                lambda_home, lambda_away, n_sim=SIMULATION_SIZE
            )
            btts_prob    = mc_summary.get("btts_prob",    0.0)
            over15_prob  = mc_summary.get("over15_prob",  0.0)
            mc_draw_prob = mc_summary.get("draw_prob",    0.0)

            # ── VENUE BTTS RATES ──────────────────────────────────────────
            def btts_rate(fixtures_list):
                if not fixtures_list: return 0.0
                return round(
                    sum(1 for f in fixtures_list if is_btts(f)) /
                    len(fixtures_list), 3
                )

            venue_btts_home = btts_rate(lastN_home)
            venue_btts_away = btts_rate(lastN_away)

            # ── H2H BTTS RATE ─────────────────────────────────────────────
            h2h_btts_rate = btts_rate(h2h)

            def o15_rate(fixtures_list):
                if not fixtures_list: return 0.0
                return round(sum(1 for f in fixtures_list if is_o15(f)) / len(fixtures_list), 3)

            h2h_o15_rate = o15_rate(h2h)

            # ── VENUE GOALS AVERAGE ───────────────────────────────────────
            def venue_goals_avg(fixtures_list, tid):
                vals = []
                for f in fixtures_list or []:
                    tg, og = get_team_and_opponent_goals_from_fixture(f, tid)
                    if tg is not None and og is not None:
                        vals.append(tg + og)
                return float(np.mean(vals)) if vals else 0.0

            vga_home = venue_goals_avg(lastN_home, home_id)
            vga_away = venue_goals_avg(lastN_away, away_id)

            # ── KEEPER VULNERABILITY ──────────────────────────────────────
            if verbose:
                print(
                    f"  🔎 {home_name} vs {away_name} — "
                    f"fetching GK data..."
                )
            (h_gk_vuln, h_gk_liable,
             h_gk_note, h_gk_cpg) = calculate_gk_vulnerability(
                home_id, fx, TARGET_DATE
            )
            (a_gk_vuln, a_gk_liable,
             a_gk_note, a_gk_cpg) = calculate_gk_vulnerability(
                away_id, fx, TARGET_DATE
            )
            sleep_short()

            # ── FATIGUE ───────────────────────────────────────────────────
            h_recent_lin = [
                extract_starters_from_fixture(f, home_id)
                for f in lastN_home
            ]
            a_recent_lin = [
                extract_starters_from_fixture(f, away_id)
                for f in lastN_away
            ]
            h_core = identify_key_players_from_history(h_recent_lin)
            a_core = identify_key_players_from_history(a_recent_lin)
            h_today = [
                p.get("player_id")
                for p in extract_starters_from_fixture(fx, home_id)
            ]
            a_today = [
                p.get("player_id")
                for p in extract_starters_from_fixture(fx, away_id)
            ]
            h_rot = compute_rotation_score(
                {k: v["starts"] for k, v in h_core.items()}, h_today
            )
            a_rot = compute_rotation_score(
                {k: v["starts"] for k, v in a_core.items()}, a_today
            )
            fatigue_home = estimate_fatigue_from_schedules(
                team_cache.get(home_id, []), home_id, h_rot
            )
            fatigue_away = estimate_fatigue_from_schedules(
                team_cache.get(away_id, []), away_id, a_rot
            )

            league_weight = league_cache.get(
                league_id, {}
            ).get("league_weight", 0.0)

            # ── ODDS ──────────────────────────────────────────────────────
            try:
                odds = sniper_fetch_odds(fx.get("id"))
            except Exception:
                odds = {"h": None, "d": None, "a": None}

            # ─────────────────────────────────────────────────────────────
            # GG SCORE
            # ─────────────────────────────────────────────────────────────
            gg_score, signals_fired, gg_breakdown = calculate_gg_score(
                btts_prob            = btts_prob,
                venue_btts_home      = venue_btts_home,
                venue_btts_away      = venue_btts_away,
                home_gk_is_liability = h_gk_liable,
                away_gk_is_liability = a_gk_liable,
                home_gk_cpg          = h_gk_cpg,
                away_gk_cpg          = a_gk_cpg,
                h2h_btts_rate        = h2h_btts_rate,
                lambda_home          = lambda_home,
                lambda_away          = lambda_away,
            )
            gg_tier = get_gg_tier(gg_score, signals_fired)

            # ─────────────────────────────────────────────────────────────
            # OVER 1.5 SCORE
            # ─────────────────────────────────────────────────────────────
            o15_score, o15_breakdown = calculate_o15_score(
                lambda_home          = lambda_home,
                lambda_away          = lambda_away,
                mc_over15_prob       = over15_prob,
                venue_goals_avg_home = vga_home,
                venue_goals_avg_away = vga_away,
                league_weight        = league_weight,
                fatigue_home         = fatigue_home,
                fatigue_away         = fatigue_away,
                home_scored_total    = home_scored_total,
                away_scored_total    = away_scored_total,
                home_conceded_total  = home_conceded_total,
                away_conceded_total  = away_conceded_total,
                home_gk_cpg          = h_gk_cpg,
                away_gk_cpg          = a_gk_cpg,
                home_gk_liable       = h_gk_liable,
                away_gk_liable       = a_gk_liable,
                h2h_o15_rate         = h2h_o15_rate
            )
            o15_tier = get_o15_tier(o15_score)

            # ── DRAW SCORE (preserved) ────────────────────────────────────
            def count_draws(fx_list, tid):
                return sum(
                    1 for f in fx_list or []
                    if (lambda ab: ab[0] == ab[1] if ab[0] is not None
                        else False)(
                        get_team_and_opponent_goals_from_fixture(f, tid)
                    )
                )

            home_draws = count_draws(lastN_home, home_id)
            away_draws = count_draws(lastN_away, away_id)
            h2h_draws  = sum(
                1 for m in h2h
                if (lambda s: s[0] == s[1] if s[0] is not None else False)(
                    extract_final_goals_from_scores(m.get("scores", []))
                )
            )
            total_h2h_played = len(h2h)
            dmi    = draw_magnet_index(
                home_draws, away_draws, h2h_draws, total_h2h_played
            )
            parity = parity_score(hpg, apg, hca, aca)
            poisson_draw = poisson_draw_probability(lambda_home, lambda_away)
            home_analysis_tempo = (
                "High" if (
                    formation_offense_score(
                        parse_formation(
                            extract_formation_from_fixture(fx, home_id)
                        )
                    )[0] >= 3 and
                    raw_home_attack >= 1.2
                ) else "Moderate"
            )
            away_analysis_tempo = (
                "High" if (
                    formation_offense_score(
                        parse_formation(
                            extract_formation_from_fixture(fx, away_id)
                        )
                    )[0] >= 3 and
                    raw_away_attack >= 1.2
                ) else "Moderate"
            )
            if home_analysis_tempo != away_analysis_tempo:
                parity = round(parity * 0.80, 3)

            league_balance = 0
            comp_draw = composite_draw_score(
                poisson_draw, dmi, league_balance, league_weight, parity
            )

            # ── PRINT SUMMARY ─────────────────────────────────────────────
            if verbose:
                print(
                    f"  [{gg_tier}] [{o15_tier}] "
                    f"{home_name} vs {away_name}"
                )
                print(
                    f"    GG:  Score={gg_score} | Signals={signals_fired}/5 | "
                    f"BTTS_MC={btts_prob:.1%} | "
                    f"VenBTTS_H={venue_btts_home:.1%} "
                    f"VenBTTS_A={venue_btts_away:.1%} | "
                    f"H2H_BTTS={h2h_btts_rate:.1%}"
                )
                print(
                    f"    GK:  Home={h_gk_note} | Away={a_gk_note}"
                )
                print(
                    f"    O15: Score={o15_score} | "
                    f"Lam={lambda_home:.2f}+{lambda_away:.2f}="
                    f"{lambda_home+lambda_away:.2f} | "
                    f"MC_O15={over15_prob:.1%} | "
                    f"VenGoals={vga_home:.2f}/{vga_away:.2f}"
                )

            base_record = {
                "date":              TARGET_DATE,
                "fixture_id":        fx.get("id"),
                "fixture":           f"{home_name} vs {away_name}",
                "league_id":         league_id,
                "home_team":         home_name,
                "away_team":         away_name,
                "lambda_home":       round(lambda_home,  3),
                "lambda_away":       round(lambda_away,  3),
                "combined_lambda":   round(lambda_home + lambda_away, 3),
                "mc_btts_prob":      round(btts_prob,    4),
                "mc_over15_prob":    round(over15_prob,  4),
                "mc_draw_prob":      round(mc_draw_prob, 4),
                "venue_btts_home":   venue_btts_home,
                "venue_btts_away":   venue_btts_away,
                "h2h_btts_rate":     h2h_btts_rate,
                "home_gk_cpg":       h_gk_cpg,
                "away_gk_cpg":       a_gk_cpg,
                "home_gk_liable":    h_gk_liable,
                "away_gk_liable":    a_gk_liable,
                "home_gk_note":      h_gk_note,
                "away_gk_note":      a_gk_note,
                "fatigue_home":      round(fatigue_home, 3),
                "fatigue_away":      round(fatigue_away, 3),
                "league_weight":     league_weight,
                "draw_odds":         odds.get("d"),
                "home_odds":         odds.get("h"),
                "away_odds":         odds.get("a"),
            }

            gg_row = {
                **base_record,
                "gg_score":          gg_score,
                "gg_signals_fired":  signals_fired,
                "gg_tier":           gg_tier,
                "sig1_mc_btts":      gg_breakdown["sig1_mc_btts"],
                "sig2_venue_btts":   gg_breakdown["sig2_venue_btts"],
                "sig3_gk_vuln":      gg_breakdown["sig3_gk_vuln"],
                "sig4_h2h_btts":     gg_breakdown["sig4_h2h_btts"],
                "sig5_directional":  gg_breakdown["sig5_directional"],
                "venue_btts_combined": gg_breakdown["venue_btts_combined"],
                "composite_draw_score": round(comp_draw, 4),
                "dmi":               round(dmi,    3),
                "parity":            parity,
            }

            o15_row = {
                **base_record,
                "o15_score":              o15_score,
                "o15_tier":               o15_tier,
                "sig1_combined_lambda":   o15_breakdown["sig1_combined_lambda"],
                "sig2_mc_over15":         o15_breakdown["sig2_mc_over15"],
                "sig3_venue_goals_avg":   o15_breakdown["sig3_venue_goals_avg"],
                "sig4_league_weight":     o15_breakdown["sig4_league_weight"],
                "sig5_fatigue_penalty":   o15_breakdown["sig5_fatigue_penalty"],
                "combined_venue_goals_avg": o15_breakdown["combined_venue_goals_avg"],
                "venue_goals_avg_home":   round(vga_home, 3),
                "venue_goals_avg_away":   round(vga_away, 3),
                "composite_draw_score":   round(comp_draw, 4),
            }

            gg_picks.append(gg_row)
            o15_picks.append(o15_row)

        except Exception as e:
            if verbose:
                print(
                    f"  ⚠️  Error on {fx.get('id','?')}: {e}"
                )
            continue

    # ──────────────────────────────────────────────────────────────────────
    # OUTPUT
    # ──────────────────────────────────────────────────────────────────────
    if not gg_picks:
        if verbose:
            print("\n  No picks generated.")
        return [], []

    tier_order_gg = {
        "💎 GG TIER 1 — LOCK":            1,
        "🔥 GG TIER 1 — HIGH CONFIDENCE": 2,
        "✅ GG TIER 2 — SOLID":           3,
        "📊 GG TIER 3 — LEAN":            4,
        "⚪ GG BELOW THRESHOLD":          5,
    }
    tier_order_o15 = {
        "💎 O1.5 TIER 1 — LOCK":   1,
        "✅ O1.5 TIER 2 — SOLID":  2,
        "📊 O1.5 TIER 3 — LEAN":   3,
        "⚪ O1.5 BELOW THRESHOLD": 4,
    }

    df_gg  = pd.DataFrame(gg_picks)
    df_o15 = pd.DataFrame(o15_picks)

    df_gg["tier_rank"]  = df_gg["gg_tier"].map(tier_order_gg).fillna(99)
    df_gg  = df_gg.sort_values(
        ["tier_rank", "gg_score", "gg_signals_fired"],
        ascending=[True, False, False]
    ).reset_index(drop=True)

    df_o15["tier_rank"] = df_o15["o15_tier"].map(tier_order_o15).fillna(99)
    df_o15 = df_o15.sort_values(
        ["tier_rank", "o15_score"],
        ascending=[True, False]
    ).reset_index(drop=True)

    # ── GG PRINT ──────────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'💎'*50}")
        print(f"  GG PRECISION BOARD — {TARGET_DATE}")
        print(f"{'💎'*50}")
    gg_show_cols = [
        "fixture", "gg_tier", "gg_score", "gg_signals_fired",
        "mc_btts_prob", "venue_btts_combined", "h2h_btts_rate",
        "home_gk_liable", "away_gk_liable",
        "sig1_mc_btts", "sig2_venue_btts", "sig3_gk_vuln",
        "sig4_h2h_btts", "sig5_directional",
        "home_gk_note", "away_gk_note",
        "lambda_home", "lambda_away",
    ]
    for c in gg_show_cols:
        if c not in df_gg.columns: df_gg[c] = None

    pd.set_option("display.max_rows",    None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width",       240)

    if verbose:
        for tier_name, group in df_gg.groupby("gg_tier", sort=False):
            print(f"\n  ── {tier_name} ──")
            print(group[gg_show_cols].to_string(index=False))

    # ── OVER 1.5 PRINT ────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'🔥'*50}")
        print(f"  OVER 1.5 PRECISION BOARD — {TARGET_DATE}")
        print(f"{'🔥'*50}")
    o15_show_cols = [
        "fixture", "o15_tier", "o15_score",
        "combined_lambda", "mc_over15_prob",
        "combined_venue_goals_avg", "league_weight",
        "sig1_combined_lambda", "sig2_mc_over15",
        "sig3_venue_goals_avg", "sig4_league_weight",
        "sig5_fatigue_penalty",
        "fatigue_home", "fatigue_away",
    ]
    for c in o15_show_cols:
        if c not in df_o15.columns: df_o15[c] = None

    if verbose:
        for tier_name, group in df_o15.groupby("o15_tier", sort=False):
            print(f"\n  ── {tier_name} ──")
            print(group[o15_show_cols].to_string(index=False))

    # ── SAVE CSVs ─────────────────────────────────────────────────────────
    gg_csv_path  = os.path.join(
        OUTPUT_DIR, f"ALIENEDGE_GG_PICKS_{TARGET_DATE}.csv"
    )
    o15_csv_path = os.path.join(
        OUTPUT_DIR, f"ALIENEDGE_O15_PICKS_{TARGET_DATE}.csv"
    )
    df_gg.drop(columns=["tier_rank"],  errors="ignore").to_csv(
        gg_csv_path,  index=False
    )
    df_o15.drop(columns=["tier_rank"], errors="ignore").to_csv(
        o15_csv_path, index=False
    )

    # ── SAVE JSON FEED ─────────────────────
    feed = []
    for _, row in df_gg.iterrows():
        feed.append({
            "fixture_id":         row.get("fixture_id"),
            "fixture":            row.get("fixture"),
            "gg_score":           row.get("gg_score"),
            "gg_tier":            row.get("gg_tier"),
            "gg_signals_fired":   row.get("gg_signals_fired"),
            "mc_btts_prob":       row.get("mc_btts_prob"),
            "venue_btts_combined": row.get("venue_btts_combined"),
            "h2h_btts_rate":      row.get("h2h_btts_rate"),
            "home_gk_liable":     bool(row.get("home_gk_liable", False)),
            "away_gk_liable":     bool(row.get("away_gk_liable", False)),
            "home_gk_cpg":        row.get("home_gk_cpg"),
            "away_gk_cpg":        row.get("away_gk_cpg"),
            "o15_score":          df_o15.loc[
                df_o15["fixture_id"] == row.get("fixture_id"),
                "o15_score"
            ].values[0] if len(
                df_o15[df_o15["fixture_id"] == row.get("fixture_id")]
            ) > 0 else None,
            "o15_tier":           df_o15.loc[
                df_o15["fixture_id"] == row.get("fixture_id"),
                "o15_tier"
            ].values[0] if len(
                df_o15[df_o15["fixture_id"] == row.get("fixture_id")]
            ) > 0 else None,
        })

    json_path = os.path.join(
        OUTPUT_DIR, f"gg_o15_feed_{TARGET_DATE}.json"
    )
    with open(json_path, "w", encoding="utf-8") as f:
        import json
        json.dump(feed, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"\n  💾 GG picks saved  : {gg_csv_path}")
        print(f"  💾 O1.5 picks saved: {o15_csv_path}")
        print(f"  💾 JSON feed saved : {json_path}")
        print(f"\n  Tier 1 GG  locks : {len(df_gg[df_gg['gg_tier'].str.contains('TIER 1', na=False)])}")
        print(f"  Tier 1 O1.5 locks: {len(df_o15[df_o15['o15_tier'].str.contains('TIER 1', na=False)])}")

    return df_gg.to_dict(orient="records"), df_o15.to_dict(orient="records")

if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_gg_o15_engine(target if target else None, verbose=True)