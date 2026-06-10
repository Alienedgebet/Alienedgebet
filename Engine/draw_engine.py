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
# CONFIGURATION & VS CODE PATHS
# ==============================================================================
API_KEY = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
BASE_URL = "https://api.sportmonks.com/v3/football"

# --- 🚨 FIXED FOR GOOGLE COLAB & VS CODE COMPATIBILITY 🚨 ---
try:
    # If running in VS Code / Local Machine
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "output")
    DATA_DIR   = os.path.join(os.path.dirname(BASE_DIR), "data")
except NameError:
    # If running in Google Colab / Phone / Jupyter Notebook
    BASE_DIR   = os.path.abspath("")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

TEAM_LOOKBACK_DAYS = 365
REQUEST_DELAY_SEC = 0.18
LAST_N_GAMES = 5
FATIGUE_WINDOW_DAYS = 30
TARGET_DATE = None

# Poisson / MC
SIMULATION_SIZE = 5000           
MAX_GOALS_DISPLAY = 6
POISSON_MAX_GOALS = 8

# Tier thresholds & league scale
TIER1_COMPOSITE = 0.78
TIER2_COMPOSITE = 0.60
LEAGUE_SCALE = 0.30

# Limits & caps
MAX_KEY_PLAYERS = 16
CORE_START_RATE = 0.6
MAX_MISSING_PENALTY = 0.05

# Market IDs for Accurate Odds Sniper
MARKET_1X2 = 1

# Section-1 criteria
SECTION1_POISSON_MIN = 0.40
SECTION1_TOTAL_DRAWS_MIN = 5

# ==============================================================================
# TITANIUM HTTP HELPER (ANTI-CRASH & ANTI-RATE LIMIT)
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
                # Rate limit hit! Pause and wait before trying again.
                time.sleep(backoff * (attempt + 1))
                continue
            else:
                # Other API errors (like 500 server error)
                return {"data": []}
        except Exception:
            # Network failure or timeout
            time.sleep(backoff)
            continue
            
    # If it fails all 5 times, return empty data safely
    return {"data": []}

def sleep_short():
    time.sleep(REQUEST_DELAY_SEC)

# ==============================================================================
# PAGINATION (🚨 IMPORTED FROM OLD CODE: Anti-loop memory added)
# ==============================================================================
def fetch_fixtures_for_date(date_str):
    all_fx = []
    seen = set()
    page = 1
    while True:
        data = GET(f"/fixtures/date/{date_str}", params={"include":"participants;scores;lineups;formations;statistics","per_page":50,"page":page})
        fx = data.get("data",[])
        if not fx:
            break

        added_new = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True

        if not added_new: break 
        page += 1
        sleep_short()
    return all_fx

def fetch_last_finished_fixtures_for_team(team_id, max_needed=200):
    end_dt = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=TEAM_LOOKBACK_DAYS)
    all_fx = []
    seen = set()
    page = 1
    while True:
        params = {
            "include": "participants;scores;state;lineups;formations;statistics",
            "filters": "fixtureStates:5",
            "sortBy": "starting_at",
            "order": "desc",
            "per_page": 50,
            "page": page
        }
        data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params)
        fx = data.get("data",[])
        if not fx:
            break

        added_new = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True

        if not added_new or len(all_fx) >= max_needed:
            break
        page += 1
        sleep_short()
    return (all_fx or [])[:max_needed]

def fetch_last_h2h(team1, team2, n=LAST_N_GAMES):
    all_fx = []
    seen = set()
    page = 1
    while True:
        params = {"include":"scores;participants", "filters":"fixtureStates:5", "sortBy":"starting_at","order":"desc","per_page":50,"page":page}
        data = GET(f"/fixtures/head-to-head/{team1}/{team2}", params=params)
        fx = data.get("data",[])
        if not fx:
            break

        added_new = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True

        if not added_new or len(all_fx) >= n:
            break
        page += 1
        sleep_short()
    return (all_fx or [])[:n]

def fetch_team_standing(league_id, season_id):
    try:
        url = f"/standings?filter=standingLeagues:{league_id}&filter=standingSeasons:{season_id}"
        data = GET(url)
        return data.get("data",[])
    except Exception:
        pass
    return []

# ==============================================================================
# SAFE helpers & Odds Sniper
# ==============================================================================
def safe_int(x, default=None):
    try:
        if x is None: return default
        return int(x)
    except Exception:
        return default

def sniper_fetch_odds(fixture_id):
    """Guarantees odds accuracy via dedicated pre-match endpoint."""
    try:
        data = GET(f"/odds/pre-match/fixtures/{fixture_id}")
    except Exception:
        return {"h": None, "d": None, "a": None}

    odds_list = data.get("data",[])
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
# Score extraction helpers (PERFECT DRAW COUNTING)
# ==============================================================================
def is_team_home(fx, team_id):
    """Explicitly checks venue to prevent missing matches when metadata is empty."""
    for p in fx.get("participants",[]):
        if safe_int(p.get("id")) == safe_int(team_id):
            loc = (p.get("meta") or {}).get("location")
            if loc == "home": return True
            if loc == "away": return False

    # Fallback to list order if location metadata is missing entirely
    parts = fx.get("participants",[])
    if len(parts) >= 2:
        if safe_int(parts[0].get("id")) == safe_int(team_id): return True
        if safe_int(parts[1].get("id")) == safe_int(team_id): return False
    return False

def extract_final_goals_from_scores(scores):
    """Accurately parses goals and ignores Penalties/Aggregate scores so Draws stay Draws."""
    home, away = None, None
    for entry in (scores or []):
        if not isinstance(entry, dict):
            continue
        s = entry.get("score") or entry
        desc = str(entry.get("description", s.get("description", ""))).upper()

        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]): continue

        part = s.get("participant") or entry.get("participant")
        g = s.get("goals") if isinstance(s, dict) else entry.get("goals")
        try:
            if isinstance(g, str) and g.isdigit():
                g = int(g)
        except:
            pass
        if isinstance(g, int):
            if part == "home":
                home = g if home is None else max(home, g)
            elif part == "away":
                away = g if away is None else max(away, g)
    return home, away

def get_team_and_opponent_goals_from_fixture(fx, team_id):
    hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
    if hg is None or ag is None:
        return None, None

    team_is_home = is_team_home(fx, team_id)
    if team_is_home:
        return hg, ag
    else:
        return ag, hg

def is_btts(fx):
    hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
    return hg is not None and ag is not None and hg > 0 and ag > 0

# ==============================================================================
# Formation / lineup helpers
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
        t_id = safe_int(l.get("team_id") or l.get("teamId"))
        t_type = safe_int(l.get("type_id") or l.get("typeId"))
        if (t_id is not None and safe_int(team_id) is not None and t_id == safe_int(team_id)
                and (t_type is None or t_type == 11)):
            starters.append({
                "player_id": l.get("player_id") or l.get("playerId"),
                "player_name": l.get("player_name") or l.get("playerName"),
                "jersey_number": l.get("jersey_number") or l.get("jerseyNumber"),
                "position_id": l.get("position_id") or l.get("positionId")
            })
    return starters

def parse_formation(formation_str):
    if not formation_str or not isinstance(formation_str, str):
        return None
    parts = formation_str.replace(":", "-").replace(" ", "-").split("-")
    digits = [int(x) for x in parts if x.isdigit()]
    if not digits:
        return None
    defenders = digits[0]
    forwards = digits[-1]
    midfielders = sum(digits[1:-1]) if len(digits) > 2 else max(0, 10 - defenders - forwards)
    return {"defenders": defenders, "midfielders": midfielders, "forwards": forwards, "parts": digits}

def formation_offense_score(form):
    if not form:
        return 0, "Unknown"
    d, m, f = form["defenders"], form["midfielders"], form["forwards"]
    score = 0
    if f >= 3: score += 2
    elif f == 2: score += 1
    if m >= 5: score += 1
    if m >= 3 and f >= 1: score += 1
    if d >= 5: score = max(0, score - 1)
    score = min(5, score)
    return score, "Offensive" if score >= 4 else "Neutral" if score >= 2 else "Defensive"

def formation_defense_score(form):
    if not form: return 0
    d, m = form["defenders"], form["midfielders"]
    score = 0
    if d >= 5: score += 2
    elif d == 4: score += 1
    if m >= 5: score += 1
    return min(5, score)

def calc_formation_consistency(recent, current):
    cleaned = [f for f in recent if f]
    if not cleaned:
        return 0.0, []
    same = sum(1 for f in cleaned if f == current)
    return round(100 * same / len(cleaned), 1), cleaned

# ==============================================================================
# Key players & rotation
# ==============================================================================
def identify_key_players_from_history(recent_lineups, threshold_frac=CORE_START_RATE):
    counts, names = Counter(), {}
    valid_lineups = [l for l in recent_lineups if isinstance(l, list) and len(l) >= 8]
    for starters in valid_lineups:
        for p in starters:
            pid = p.get("player_id")
            if pid:
                counts[pid] += 1
                names[pid] = p.get("player_name", names.get(pid))
    if not valid_lineups:
        return {}
    min_starts = math.ceil(len(valid_lineups) * threshold_frac)
    core = {pid: {"player_id": pid, "player_name": names.get(pid, "Unknown"), "starts": cnt}
            for pid, cnt in counts.items() if cnt >= min_starts}
    core_limited = dict(sorted(core.items(), key=lambda x: -x[1]["starts"])[:MAX_KEY_PLAYERS])
    return core_limited

def compute_rotation_score(recent_starts, today_ids):
    if not recent_starts or not today_ids:
        return 0.0
    core_players = {pid for pid, c in recent_starts.items() if c >= 2}
    if not core_players:
        return 0.0
    overlap = len(core_players.intersection(set(today_ids)))
    return round(overlap / len(core_players), 2)

# ==============================================================================
# Poisson & Monte Carlo helpers
# ==============================================================================
def poisson_pmf(k, lam):
    if lam < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except Exception:
        return 0.0

def poisson_draw_probability(lambda_home, lambda_away, max_goals=POISSON_MAX_GOALS):
    prob = 0.0
    for k in range(0, max_goals + 1):
        prob += poisson_pmf(k, lambda_home) * poisson_pmf(k, lambda_away)
    return min(1.0, prob)

def generate_scoreline_predictions(lambda_home, lambda_away, n_sim=SIMULATION_SIZE, max_display=MAX_GOALS_DISPLAY):
    if n_sim <= 0:
        return {}, {"draw_prob":0.0, "home_win_prob":0.0, "away_win_prob":0.0, "over25_prob":0.0, "btts_prob":0.0, "sim_count":0}
    home_goals = np.random.poisson(lambda_home, size=n_sim)
    away_goals = np.random.poisson(lambda_away, size=n_sim)
    counts = {}
    over25 = btts = hom = draw = aw = 0
    for hg, ag in zip(home_goals, away_goals):
        key = (hg, ag) if hg <= max_display and ag <= max_display else ("Other",)
        counts[key] = counts.get(key, 0) + 1
        if (hg + ag) >= 3: over25 += 1
        if hg > 0 and ag > 0: btts += 1
        if hg > ag: hom += 1
        elif hg == ag: draw += 1
        else: aw += 1
    score_probs = {k: v / n_sim for k, v in counts.items()}
    sorted_scores = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)
    top1 = sorted_scores[0] if len(sorted_scores) > 0 else (None, 0.0)
    top2 = sorted_scores[1] if len(sorted_scores) > 1 else (None, 0.0)
    summary = {
        "draw_prob": draw / n_sim,
        "home_win_prob": hom / n_sim,
        "away_win_prob": aw / n_sim,
        "over25_prob": over25 / n_sim,
        "btts_prob": btts / n_sim,
        "sim_count": n_sim
    }
    return {"score_probs": score_probs, "top1": top1, "top2": top2}, summary

def fmt_score_key(k):
    if k is None or k == ("Other",):
        return "Other"
    return f"{k[0]}–{k[1]}"

# ==============================================================================
# Fatigue estimator
# ==============================================================================
def parse_fixture_datetime(fx):
    dtcands = []
    if fx.get("starting_at"): dtcands.append(fx.get("starting_at"))
    if fx.get("time") and isinstance(fx.get("time"), dict) and fx["time"].get("starting_at"):
        dtcands.append(fx["time"].get("starting_at"))
    if fx.get("date"): dtcands.append(fx.get("date"))
    for s in dtcands:
        if not s: continue
        try:
            if isinstance(s, str):
                ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
                try:
                    dt = datetime.fromisoformat(ss)
                except Exception:
                    try:
                        dt = datetime.strptime(ss, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        try:
                            dt = datetime.strptime(ss, "%Y-%m-%d")
                        except Exception:
                            dt = None
            elif isinstance(s, (int, float)):
                dt = datetime.fromtimestamp(int(s), tz=timezone.utc)
            else:
                dt = None
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                return dt
        except Exception:
            continue
    return None

def estimate_fatigue_from_schedules(recent_fixtures, team_id, rotation_score):
    now = datetime.now(timezone.utc)
    played_14 = 0
    played_7 = 0
    cutoff = now - timedelta(days=FATIGUE_WINDOW_DAYS)
    for f in recent_fixtures or []:
        parts = f.get("participants", []) or []
        if not any(p.get("id") == team_id for p in parts):
            continue
        dt = parse_fixture_datetime(f)
        if not dt: continue
        if dt < cutoff: continue
        days = (now - dt).days
        if days <= 14: played_14 += 1
        if days <= 7: played_7 += 1
    score_14 = min(1.0, played_14 / 6.0)
    score_7 = min(1.0, played_7 / 4.0)
    try:
        rot = float(rotation_score)
    except:
        rot = 0.0
    eff_rot = 1.0 - min(1.0, max(0.0, rot))
    fatigue = (0.6 * score_14 + 0.4 * score_7) * (0.7 + 0.3 * eff_rot)
    return min(1.0, max(0.0, fatigue))

# ==============================================================================
# LEAGUE TEMPO / WEIGHT (TTL CACHED FOR MASSIVE API SAVINGS)
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

    end_dt = now_utc.date() - timedelta(days=1)
    start_dt = end_dt - timedelta(days=min(days_lookback, 180)) # Reduced to 180 to save payload
    all_fx = []
    seen = set()
    page = 1
    while True:
        data = GET(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}", params={"include":"scores","per_page":50,"page":page})
        fx = data.get("data",[])
        if not fx:
            break

        added_new = False
        for f in fx:
            fid = f.get("id")
            if fid not in seen:
                seen.add(fid)
                all_fx.append(f)
                added_new = True

        if not added_new: break
        page += 1
        sleep_short()

    total = 0
    over = 0
    for fx in all_fx:
        hg, ag = extract_final_goals_from_scores(fx.get("scores",[]))
        if hg is None or ag is None:
            continue
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
# Draw Magnet Index (DMI) & Parity helpers
# ==============================================================================
def draw_magnet_index(home_draws, away_draws, h2h_draws, total_h2h_played):
    def norm(x, total_played):
        return min(1.0, float(x) / float(total_played)) if total_played > 0 else 0.0

    home_score = norm(home_draws, LAST_N_GAMES)
    away_score = norm(away_draws, LAST_N_GAMES)
    h2h_score = norm(h2h_draws, total_h2h_played) if total_h2h_played > 0 else 0.0

    if total_h2h_played == 0:
        return (home_score + away_score) / 2.0
    return (home_score + away_score + h2h_score) / 3.0

def parity_score(home_personal_goals, away_personal_goals, home_concede_avg, away_concede_avg):
    try:
        gdiff = abs(float(home_personal_goals) - float(away_personal_goals))
    except:
        gdiff = 999.0
    try:
        cdiff = abs(float(home_concede_avg) - float(away_concede_avg))
    except:
        cdiff = 999.0
    denom = max(1.0, max(home_personal_goals, away_personal_goals, 1.0))
    gpar = max(0.0, 1.0 - (gdiff / denom))
    cpar = max(0.0, 1.0 - (cdiff / 3.0))
    return round((0.6 * gpar + 0.4 * cpar), 3)

def composite_draw_score(poisson_prob, dmi, league_balance, league_weight, parity):
    score = (
        0.25 * poisson_prob +
        0.35 * dmi +
        0.30 * parity +
        0.06 * league_balance +
        0.04 * league_weight
    )
    return float(min(1.0, max(0.0, score)))

# ==============================================================================
# MAIN ENGINE - FULLY WRAPPED
# ==============================================================================
def run_draw_engine(target_date=None, verbose=False):
    """
    Executes the Draw Engine with renamed Perfect/Weak/Amateur lists.
    Fully wrapped for the VS Code Pipeline.
    verbose=False keeps it silent for API/Aggregator calls.
    """
    global TARGET_DATE
    TARGET_DATE = target_date or TARGET_DATE

    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        raise ValueError("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")

    if TARGET_DATE is None:
        TARGET_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if verbose:
        print(f"\n{'='*100}")
        print(f"  ⚖️ ALIENEDGE DRAW ENGINE — {TARGET_DATE}")
        print(f"{'='*100}\n")
        print(f"Fetching fixtures for {TARGET_DATE} ...")
        
    fixtures = fetch_fixtures_for_date(TARGET_DATE)

    if verbose:
        print(f"Found {len(fixtures)} fixtures.\n")
    if not fixtures:
        return [], [], []

    # league cache: tempo & standings & league weight
    league_cache = {}
    standings_cache = {}
    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}
    for lid in league_ids:
        try:
            league_cache[lid] = {"league_weight": compute_league_over25_weight(lid)}
        except Exception:
            league_cache[lid] = {"league_weight": 0.0}
        standings_cache[lid] = {}
        sleep_short()

    # team history cache
    team_cache = {}
    picks = []

    for fx in fixtures:
        try:
            parts = fx.get("participants", []) or []
            if len(parts) < 2:
                continue
            home_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), parts[0])
            away_p = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), parts[1] if len(parts) > 1 else None)
            if away_p is None:
                continue

            home_id = safe_int(home_p.get("id"))
            away_id = safe_int(away_p.get("id"))
            home_name = home_p.get("name") or f"Team {home_id}"
            away_name = away_p.get("name") or f"Team {away_id}"
            league_id = fx.get("league_id")
            season_id = fx.get("season_id")

            # cache team fixtures
            for tid in (home_id, away_id):
                if tid not in team_cache:
                    try:
                        team_cache[tid] = fetch_last_finished_fixtures_for_team(tid)
                    except Exception:
                        team_cache[tid] = []
                    sleep_short()

            # Build lastN using explicit venue logic for perfect context
            lastN_home = [f for f in team_cache.get(home_id, []) if is_team_home(f, home_id)][:LAST_N_GAMES]
            lastN_away = [f for f in team_cache.get(away_id, []) if not is_team_home(f, away_id)][:LAST_N_GAMES]

            # H2H
            try:
                h2h = fetch_last_h2h(home_id, away_id, n=LAST_N_GAMES)
            except Exception:
                h2h = []

            # standings (cached)
            if league_id not in standings_cache or not standings_cache.get(league_id):
                try:
                    standings_raw = fetch_team_standing(league_id, season_id)
                    pos_map = {}
                    for s in standings_raw or []:
                        try:
                            pid = s.get("participant_id") or s.get("team_id") or s.get("team")
                            pos = s.get("position")
                            if pid is not None and pos is not None:
                                pos_map[int(pid)] = int(pos)
                        except:
                            continue
                    standings_cache[league_id] = pos_map
                except Exception:
                    standings_cache[league_id] = {}
                sleep_short()
            pos_map = standings_cache.get(league_id, {})

            home_position = pos_map.get(home_id)
            away_position = pos_map.get(away_id)
            league_balance = 1 if (home_position and away_position and abs(home_position - away_position) <= 5) else 0

            # compute draws and personal goals totals
            def count_draws(fixtures_list, team_id):
                draws = 0
                for f in fixtures_list or []:
                    tg, og = get_team_and_opponent_goals_from_fixture(f, team_id)
                    if tg is None or og is None: continue
                    if tg == og: draws += 1
                return draws

            home_draws = count_draws(lastN_home, home_id)
            away_draws = count_draws(lastN_away, away_id)
            h2h_draws = 0
            total_h2h_played = len(h2h)
            for m in h2h or []:
                hg, ag = extract_final_goals_from_scores(m.get("scores",[]))
                if hg is None or ag is None: continue
                if hg == ag: h2h_draws += 1

            total_draws = home_draws + away_draws + h2h_draws

            # personal goals totals (sum last N)
            def personal_goals_total(fixtures_list, team_id):
                s = 0
                count = 0
                for f in fixtures_list or []:
                    tg, _ = get_team_and_opponent_goals_from_fixture(f, team_id)
                    if tg is None: continue
                    s += tg
                    count += 1
                return float(s), int(count)
            home_personal_goals_total, home_cnt = personal_goals_total(lastN_home, home_id)
            away_personal_goals_total, away_cnt = personal_goals_total(lastN_away, away_id)

            # conceded average for parity
            def avg_conceded(fixtures_list, team_id):
                vals = []
                for f in fixtures_list or []:
                    _, og = get_team_and_opponent_goals_from_fixture(f, team_id)
                    if og is not None: vals.append(og)
                return float(np.mean(vals)) if vals else 0.0
            home_concede_avg = avg_conceded(lastN_home, home_id)
            away_concede_avg = avg_conceded(lastN_away, away_id)

            dmi = draw_magnet_index(home_draws, away_draws, h2h_draws, total_h2h_played)

            # formation/lineup analysis (Only keeping Tempo for Parity check)
            def analyze_team(team_id, lastN):
                current_formation = extract_formation_from_fixture(fx, team_id)
                recent_fx = team_cache.get(team_id, [])[:LAST_N_GAMES]
                recent_goals = []
                for past in recent_fx:
                    g, og = get_team_and_opponent_goals_from_fixture(past, team_id)
                    recent_goals.append(int(g) if g is not None else 0)

                parsed = parse_formation(current_formation)
                form_score, _ = formation_offense_score(parsed)
                goals_avg = round(sum(recent_goals)/len(recent_goals), 2) if recent_goals else 0.0

                try:
                    if form_score >= 3 and goals_avg >= 1.2:
                        tempo = "High"
                    elif form_score >= 2 or goals_avg >= 0.8:
                        tempo = "Moderate"
                    else:
                        tempo = "Low"
                except:
                    tempo = "Moderate"

                return {"tempo": tempo}

            home_analysis = analyze_team(home_id, lastN_home)
            away_analysis = analyze_team(away_id, lastN_away)

            raw_home_attack = (home_personal_goals_total / max(1, len(lastN_home)))
            raw_away_attack = (away_personal_goals_total / max(1, len(lastN_away)))
            lambda_home = max(0.05, (raw_home_attack + away_concede_avg) / 2.0)
            lambda_away = max(0.05, (raw_away_attack + home_concede_avg) / 2.0)

            poisson_prob = poisson_draw_probability(lambda_home, lambda_away)

            parity = parity_score(home_personal_goals_total, away_personal_goals_total, home_concede_avg, away_concede_avg)
            if home_analysis["tempo"] != away_analysis["tempo"]:
                parity = round(parity * 0.80, 3) 

            h_recent_lineups = [extract_starters_from_fixture(f, home_id) for f in lastN_home]
            a_recent_lineups = [extract_starters_from_fixture(f, away_id) for f in lastN_away]

            h_core = identify_key_players_from_history(h_recent_lineups)
            a_core = identify_key_players_from_history(a_recent_lineups)

            h_today_starters = [p.get("player_id") for p in extract_starters_from_fixture(fx, home_id)]
            a_today_starters = [p.get("player_id") for p in extract_starters_from_fixture(fx, away_id)]

            h_rot = compute_rotation_score({k: v["starts"] for k, v in h_core.items()}, h_today_starters)
            a_rot = compute_rotation_score({k: v["starts"] for k, v in a_core.items()}, a_today_starters)

            fatigue_home = estimate_fatigue_from_schedules(team_cache.get(home_id,[]), home_id, rotation_score=h_rot)
            fatigue_away = estimate_fatigue_from_schedules(team_cache.get(away_id,[]), away_id, rotation_score=a_rot)
            fatigue_score = max(fatigue_home, fatigue_away)

            veto_reason = ""
            if fatigue_score >= 0.75:
                veto_reason = "🚨 LATE COLLAPSE RISK (Fatigue >= 75%)"

            league_weight = league_cache.get(league_id, {}).get("league_weight", 0.0)

            composite = composite_draw_score(
                poisson_prob=poisson_prob,
                dmi=dmi,
                league_balance=league_balance,
                league_weight=league_weight,
                parity=parity
            )

            mc_result, mc_summary = generate_scoreline_predictions(lambda_home, lambda_away, n_sim=SIMULATION_SIZE, max_display=MAX_GOALS_DISPLAY)
            mc_draw = mc_summary.get("draw_prob", 0.0)

            odds = sniper_fetch_odds(fx.get("id"))
            draw_odds = odds.get("d")
            implied_draw_prob = (1 / draw_odds) if draw_odds else 0.0
            value_edge = round(mc_draw - implied_draw_prob, 4) if draw_odds else 0.0

            top_draw_score = None
            top_draw_prob = 0.0
            sorted_scores = sorted(mc_result.get("score_probs", {}).items(), key=lambda x: x[1], reverse=True)

            top1_prob = sorted_scores[0][1] if len(sorted_scores) > 0 else 0.0
            top2_prob = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
            mc_spread = round(top1_prob - top2_prob, 4)
            mc_stability = "Chaotic" if mc_spread < 0.01 else "Stable"

            draws_found = []
            for (k, p) in sorted_scores[:12]:
                if k == ("Other",): continue
                if isinstance(k, tuple) and k[0] == k[1]:
                    draws_found.append((k, p))
            if draws_found:
                top_draw_score, top_draw_prob = draws_found[0]

            most_likely_draw = None
            if top_draw_score:
                most_likely_draw = fmt_score_key(top_draw_score)
            else:
                if abs(lambda_home - lambda_away) <= 0.4:
                    avg_goals = int(round((lambda_home + lambda_away) / 2.0))
                    most_likely_draw = f"{avg_goals}–{avg_goals}"
                else:
                    most_likely_draw = "1–1"

            # ── RENAMED TIERING LOGIC ──
            tier = "Below Threshold"
            if composite >= TIER1_COMPOSITE or (composite >= 0.70 and mc_draw >= 0.30 and parity >= 0.6 and dmi >= 0.45):
                tier = "Perfect Draw List"
            elif composite >= TIER2_COMPOSITE or (composite >= 0.58 and mc_draw >= 0.22):
                tier = "Perfect Draw List"
            else:
                tier = "Weak Draw List"

            if home_personal_goals_total <= 5 and away_personal_goals_total <= 5 and parity >= 0.7 and composite >= 0.6:
                tier = "Perfect Draw List"

            if veto_reason:
                tier = "🛑 VETOED"

            section = "Section 1" if (poisson_prob >= SECTION1_POISSON_MIN and total_draws >= SECTION1_TOTAL_DRAWS_MIN) else ""

            pick = {
                "date": TARGET_DATE,
                "fixture_id": fx.get("id"),
                "fixture": f"{home_name} vs {away_name}",
                "league_id": league_id,
                "home_team": home_name,
                "away_team": away_name,
                "home_position": home_position,
                "away_position": away_position,
                "home_personal_goals_total": home_personal_goals_total,
                "away_personal_goals_total": away_personal_goals_total,
                "home_concede_avg": round(home_concede_avg, 3),
                "away_concede_avg": round(away_concede_avg, 3),
                "home_draws": home_draws,
                "away_draws": away_draws,
                "h2h_draws": h2h_draws,
                "total_draws": total_draws,
                "dmi": round(dmi, 3),
                "parity": parity,
                "poisson_draw_prob": round(poisson_prob, 4),
                "mc_draw_prob": round(mc_draw, 4),
                "composite_draw_score": round(composite, 4),
                "fatigue_score": round(fatigue_score, 3),
                "draw_odds": draw_odds,
                "value_edge": value_edge,
                "mc_spread": mc_spread,
                "mc_stability": mc_stability,
                "veto_reason": veto_reason,
                "league_weight": league_weight,
                "most_likely_draw_score": most_likely_draw,
                "most_likely_draw_pct": round(top_draw_prob, 4) if top_draw_prob else None,
                "mc_top1": fmt_score_key(mc_result.get("top1", (None, 0.0))[0]),
                "mc_top1_pct": round(mc_result.get("top1", (None, 0.0))[1], 4),
                "mc_top2": fmt_score_key(mc_result.get("top2", (None, 0.0))[0]),
                "mc_top2_pct": round(mc_result.get("top2", (None, 0.0))[1], 4),
                "tier": tier,
                "section": section
            }

            picks.append(pick)

            if verbose:
                sec_mark = f" / {section}" if section else ""
                print(f"[{tier}{sec_mark}] {home_name} vs {away_name} | DMI: {dmi:.3f} | Edge: {value_edge:.2f} | M-Spread: {mc_spread:.2f} ({mc_stability})")

        except Exception as e:
            if verbose:
                print(f"Error processing fixture {fx.get('id')}: {e}")
            continue

    df = pd.DataFrame(picks)
    if df.empty:
        if verbose: print("No picks generated.")
        return [], [], []

    # ── TIER ORDER RENAMED ──
    tier_order = {
        "Perfect Draw List": 1, 
        "Weak Draw List": 2, 
        "🛑 VETOED": 3, 
        "Below Threshold": 99
    }
    
    df["tier_rank"] = df["tier"].map(tier_order).fillna(99)
    df["section_rank"] = df["section"].map(lambda s: 0 if s == "Section 1" else 1)
    df = df.sort_values(by=["tier_rank", "section_rank", "composite_draw_score", "mc_draw_prob"], ascending=[True, True, False, False]).reset_index(drop=True)

    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)

    show_cols = [
        "fixture", "tier", "section", "draw_odds", "value_edge", "mc_spread", "mc_stability",
        "composite_draw_score", "poisson_draw_prob", "mc_draw_prob",
        "dmi", "parity", "home_personal_goals_total", "away_personal_goals_total",
        "home_concede_avg", "away_concede_avg", "home_draws", "away_draws", "h2h_draws", "total_draws",
        "fatigue_score", "veto_reason",
        "most_likely_draw_score", "most_likely_draw_pct", "mc_top1", "mc_top1_pct"
    ]

    for c in show_cols:
        if c not in df.columns:
            df[c] = None

    if verbose:
        print("\n=== Upgraded Draw Ranking (Tiered, Section 1 highlighted) ===\n")
        grouped = df.groupby("tier", sort=False)
        for tier_name, group in grouped:
            print(f"--- {tier_name} ---")
            sec1 = group[group["section"] == "Section 1"]
            if not sec1.empty:
                print("\n  >> Section 1 (Poisson >= {:.0%} & Total Draws >= {})\n".format(SECTION1_POISSON_MIN, SECTION1_TOTAL_DRAWS_MIN))
                print(sec1[show_cols].to_string(index=False))
            rem = group[group["section"] != "Section 1"]
            if not rem.empty:
                print("\n  Other picks in this tier:\n")
                print(rem[show_cols].to_string(index=False))
            print("\n")

    parity_threshold = 0.9
    draws_threshold = 5  

    df["parity"] = pd.to_numeric(df["parity"], errors="coerce").fillna(0.0)
    df["total_draws"] = pd.to_numeric(df["total_draws"], errors="coerce").fillna(0).astype(int)

    parity_df = df[df["parity"] >= parity_threshold].copy()
    draws_df = df[df["total_draws"] > draws_threshold].copy()

    if verbose:
        print(f"\n=== PARITY TEAM LIST (Parity >= {parity_threshold}) ===\n")
        if parity_df.empty:
            print("No fixtures meet parity >= {:.2f}.".format(parity_threshold))
        else:
            cols_show = ["fixture", "tier", "section", "parity", "composite_draw_score", "poisson_draw_prob", "mc_draw_prob", "total_draws", "most_likely_draw_score"]
            for c in cols_show:
                if c not in parity_df.columns: parity_df[c] = None
            print(parity_df[cols_show].to_string(index=False))

        print(f"\n=== AMATEURS DRAW LIST (Total Draws > {draws_threshold}) ===\n")
        if draws_df.empty:
            print("No fixtures have total_draws > {}.".format(draws_threshold))
        else:
            cols_show2 = ["fixture", "tier", "section", "total_draws", "home_draws", "away_draws", "h2h_draws", "parity", "composite_draw_score", "poisson_draw_prob"]
            for c in cols_show2:
                if c not in draws_df.columns: draws_df[c] = None
            print(draws_df[cols_show2].to_string(index=False))

    out_fn     = os.path.join(OUTPUT_DIR, f"ALIENEDGE_DRAW_PICKS_{TARGET_DATE}.csv")
    out_parity = os.path.join(OUTPUT_DIR, f"ALIENEDGE_PARITY_TEAM_LIST_{TARGET_DATE}.csv")
    out_draws  = os.path.join(OUTPUT_DIR, f"ALIENEDGE_AMATEURS_DRAW_LIST_{TARGET_DATE}.csv")
    
    try:
        df.to_csv(out_fn, index=False)
        if verbose: print(f"\nSaved full ranked results to: {out_fn}")
    except Exception as e:
        if verbose: print(f"Failed to save CSV {out_fn}: {e}")

    try:
        parity_df.to_csv(out_parity, index=False)
        if verbose: print(f"Saved parity >= {parity_threshold} list to: {out_parity}")
    except Exception as e:
        if verbose: print(f"Failed to save CSV {out_parity}: {e}")

    try:
        draws_df.to_csv(out_draws, index=False)
        if verbose: print(f"Saved total_draws > {draws_threshold} list to: {out_draws}")
    except Exception as e:
        if verbose: print(f"Failed to save CSV {out_draws}: {e}")

    return df.to_dict(orient="records"), parity_df.to_dict(orient="records"), draws_df.to_dict(orient="records")


def get_draw_predictions(target_date=None, verbose=False):
    """Call this from your aggregator to instantly receive the Draw picks."""
    draw_data, _, _ = run_draw_engine(target_date, verbose)
    return draw_data

# ==============================================================================
# LOCAL TESTING
# ==============================================================================
if __name__ == "__main__":
    target = input("\nEnter target date (YYYY-MM-DD) or leave empty for today: ").strip()
    run_draw_engine(target if target else None, verbose=True)