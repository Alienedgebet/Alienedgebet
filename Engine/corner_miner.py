import os
import sys
import time
import json
import math
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (VS ARCHITECTURE STANDARD) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ----------------- CONFIG -----------------
API_KEY = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"
REQUEST_DELAY = 0.12
MAX_RETRIES = 4
RETRY_BACKOFF = 1.5
BOOKMAKER_ID = 2
HISTORICAL_MATCHES = 8        # use last 8 for hist corners list
LAST_N_GAMES = 5              # last-N used in many places (also printed)
LOOKBACK_DAYS = 365
NUM_PAST_FIXTURES = 100
LEAGUE_SCALE = 0.30
DEBUG_LOCAL_FIXTURES_PATH = None

# ----------------- THRESHOLDS -----------------
THRESH_HIGH = 12.5
THRESH_STRONG = 10.0
THRESH_MODERATE = 8.5
MISSING_KEYS_THRESHOLD = 3
ROTATION_THRESHOLD = 4
LINEUP_STABILITY_WARN = 0.6
GOALS_RECENT_WARN = 7
LEAGUE_WEIGHT_GOOD = 0.8

# ----------------- UTIL / LOG -----------------
def log_error(*parts):
    print("[ERROR]", *parts)

def log_info(*parts):
    print("[INFO]", *parts)

def log_warn(*parts):
    print("[WARN]", *parts)

def log_debug(*parts):
    if os.getenv("DEBUG") == "1":
        print("[DEBUG]", *parts)

def safe_int(x, default=None):
    try:
        if x is None:
            return default
        return int(str(x))
    except Exception:
        return default

# ----------------- NETWORK WITH RETRIES -----------------
def _request_with_retries(url, params, retries=MAX_RETRIES):
    attempt = 0
    last_exc = None
    while attempt <= retries:
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = (RETRY_BACKOFF ** attempt) + 1
                log_warn(f"429 rate limit, sleeping {wait:.1f}s (attempt {attempt}/{retries})")
                time.sleep(wait)
                attempt += 1
                continue
            if r.status_code >= 500:
                wait = (RETRY_BACKOFF ** attempt)
                log_warn(f"{r.status_code} server error, sleeping {wait:.1f}s (attempt {attempt}/{retries})")
                time.sleep(wait)
                attempt += 1
                continue
            r.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return r.json()
        except requests.RequestException as e:
            last_exc = e
            wait = (RETRY_BACKOFF ** attempt)
            log_warn(f"Request error: {e}. sleeping {wait:.1f}s (attempt {attempt}/{retries})")
            time.sleep(wait)
            attempt += 1
    raise RuntimeError(f"Failed to fetch {url} after {retries} retries; last_exc={last_exc}")

def GET(path, params=None):
    if params is None:
        params = {}
    params = dict(params)
    params.setdefault("api_token", API_KEY)
    url = f"{BASE_URL}{path}"
    log_debug("GET", url, params)
    return _request_with_retries(url, params)

def GET_ALL(path, params=None, per_page=50, max_pages=500):
    if DEBUG_LOCAL_FIXTURES_PATH:
        try:
            with open(DEBUG_LOCAL_FIXTURES_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {"data": data, "meta": {}}
        except Exception as e:
            log_warn("Local debug file failed:", e)

    if params is None:
        params = {}
    params = dict(params)
    params.setdefault("api_token", API_KEY)
    params.setdefault("per_page", per_page)

    all_data =[]
    page = 1
    last_meta = {}

    while page <= max_pages:
        params["page"] = page
        url = f"{BASE_URL}{path}"
        try:
            payload = _request_with_retries(url, params)
        except Exception as e:
            log_warn(f"Pagination stopped at page {page} for {path}: {e}")
            break

        data = payload.get("data",[]) if isinstance(payload, dict) else (payload or[])
        if data:
            all_data.extend(data)

        last_meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        pagination = last_meta.get("pagination") if isinstance(last_meta, dict) else None

        if pagination and pagination.get("next_page"):
            try:
                page = int(pagination["next_page"])
                continue
            except Exception:
                page += 1
                continue

        if not data or len(data) < per_page:
            break

        page += 1

    return {"data": all_data, "meta": last_meta}

# ----------------- ODDS HELPERS -----------------
def extract_fixture_odds_map(fixtures):
    odds_map = {}
    for fx in fixtures:
        fid = fx.get("id")
        odds_map[fid] = {
            "home_win_odds": None,
            "over_2_5_odds": None
        }

        for market in fx.get("odds", []) or[]:
            if market.get("bookmaker_id") != BOOKMAKER_ID:
                continue

            market_name = (market.get("market_description") or "").lower()
            for o in market.get("odds", []) or[]:
                label = (o.get("label") or "").lower()
                try:
                    value = float(o.get("value"))
                except Exception:
                    continue

                if market_name in ("1x2", "match winner") and label == "home":
                    odds_map[fid]["home_win_odds"] = value

                if "over/under" in market_name and "2.5" in market_name and "over" in label:
                    odds_map[fid]["over_2_5_odds"] = value

    return odds_map


def assign_tier_1_priority(corner_tier, home_win_odds, over25_odds):
    if corner_tier not in ("High", "Strong"):
        return False
    if home_win_odds is None or over25_odds is None:
        return False
    return 1.40 <= home_win_odds <= 2.10 and 1.55 <= over25_odds <= 2.05

# ----------------- STATS / EXTRACT -----------------
def extract_final_goals_from_scores(scores):
    home = None
    away = None
    for entry in (scores or[]):
        if not isinstance(entry, dict):
            continue
        s = entry.get("score") or entry
        part = s.get("participant")
        g = s.get("goals")
        if isinstance(g, str):
            try:
                g = int(g)
            except:
                g = None
        if isinstance(g, (int, float)):
            g = int(g)
            if part == "home":
                home = g if home is None else max(home, g)
            elif part == "away":
                away = g if away is None else max(away, g)
    return home, away

def extract_stat_entries_for_participant(fx, participant_id):
    stats = fx.get("statistics", []) or[]
    result = {}
    entries =[]
    if isinstance(stats, dict):
        pid_str = str(participant_id)
        if pid_str in stats:
            maybe = stats.get(pid_str) or[]
            if isinstance(maybe, dict) and 'statistics' in maybe:
                entries = maybe.get('statistics',[])
            elif isinstance(maybe, list):
                entries = maybe
            else:
                entries = [maybe]
        else:
            for v in stats.values():
                if isinstance(v, list):
                    entries.extend(v)
                elif isinstance(v, dict) and 'statistics' in v:
                    entries.extend(v.get('statistics',[]))
                else:
                    entries.append(v)
    elif isinstance(stats, list):
        entries = stats
    else:
        entries = []

    for s in entries or[]:
        if not isinstance(s, dict):
            continue
        stat_type = None
        if isinstance(s.get("type"), dict):
            stat_type = s.get("type", {}).get("name")
        if not stat_type:
            stat_type = s.get("name") or s.get("stat") or s.get("type") or None
        if not stat_type:
            continue
        pid = s.get("participant_id") or s.get("team_id") or s.get("participantId") or s.get("teamId")
        if pid is None and isinstance(s.get("data"), dict):
            pid = s["data"].get("participant_id") or s["data"].get("team_id")
        if pid is None:
            continue
        if safe_int(pid) != safe_int(participant_id):
            continue
        val = None
        if isinstance(s.get("data"), dict):
            val = s["data"].get("value")
        else:
            val = s.get("value")
            if val is None and isinstance(s.get("data"), dict):
                val = s.get("data", {}).get("value")
        if val is None or val == "":
            continue
        if isinstance(val, str) and val.endswith('%'):
            val = val.rstrip('%').strip()
        try:
            num = float(str(val).replace(',', '').strip())
            result[str(stat_type)] = num
        except Exception:
            continue
    return result

def extract_corners_from_fixture(fx, team_id):
    entries = extract_stat_entries_for_participant(fx, team_id)
    if entries.get("Corners") is not None:
        try:
            return int(round(float(entries.get("Corners", 0))))
        except:
            pass
    for k, v in entries.items():
        if isinstance(k, str) and 'corner' in k.lower():
            try:
                return int(round(float(v)))
            except:
                continue
    return 0

def extract_formation_from_fixture(fx, team_id):
    for f in fx.get("formations", []) or[]:
        pid = safe_int(f.get("participant_id") or f.get("participantId"))
        if pid == safe_int(team_id):
            return f.get("formation")
    return None

def extract_starters_from_fixture(fx, team_id):
    starters =[]
    for l in fx.get("lineups", []) or[]:
        tid = safe_int(l.get("team_id") or l.get("teamId"))
        ttype = safe_int(l.get("type_id") or l.get("typeId"))
        if tid == safe_int(team_id) and (ttype is None or ttype == 11):
            starters.append({
                "player_id": l.get("player_id") or l.get("playerId"),
                "player_name": l.get("player_name") or l.get("playerName"),
            })
    return starters

def parse_formation(formation_str):
    if not formation_str or not isinstance(formation_str, str):
        return None
    parts = formation_str.replace(":", "-").replace(" ", "-").split("-")
    digits =[]
    for x in parts:
        try:
            if x.isdigit():
                digits.append(int(x))
        except:
            pass
    if not digits:
        return None
    defenders = digits[0]
    forwards = digits[-1]
    midfielders = sum(digits[1:-1]) if len(digits) > 2 else max(0, 10 - defenders - forwards)
    return {"defenders": defenders, "midfielders": midfielders, "forwards": forwards, "parts": digits}

def formation_is_defensive(parsed):
    if not parsed:
        return False
    return parsed.get("defenders", 0) >= 5 or parsed.get("midfielders", 0) >= 6

def assign_inplay_style_from_stats(stat_map):
    labels =[]
    attacks = stat_map.get("Attacks", 0.0)
    dang = stat_map.get("Dangerous Attacks", 0.0)
    crosses = stat_map.get("Total Crosses", 0.0)
    accurate_crosses = stat_map.get("Accurate Crosses", 0.0)
    passes_acc = stat_map.get("Successful Passes Percentage", None)
    tackles = stat_map.get("Tackles", 0.0)
    interceptions = stat_map.get("Interceptions", 0.0)

    if attacks >= 60 and dang >= 35:
        labels.append("Attacking")
    if crosses >= 12 and accurate_crosses >= 3:
        labels.append("Crossing/Counter")
    if tackles >= 14 and interceptions >= 6:
        labels.append("Defensive")
    if passes_acc is not None and passes_acc >= 75:
        labels.append("Possession-Oriented")
    if not labels:
        labels = ["Balanced/Other"]
    return labels

def assign_tactical_style_from_formation(formation_str):
    parsed = parse_formation(formation_str)
    if not parsed:
        return ["Unknown"]
    d, m, f = parsed["defenders"], parsed["midfielders"], parsed["forwards"]
    if f >= 3 and m >= 3:
        return["Offensive"]
    if d >= 5:
        return ["Defensive"]
    if m >= 5:
        return["Possession-Oriented"]
    return ["Neutral"]

def determine_style_alignment(h_style, a_style):
    aggressive =["Attacking", "Crossing/Counter"]
    h_agg = any(s in aggressive for s in h_style)
    a_agg = any(s in aggressive for s in a_style)
    if h_agg and a_agg: return "OPEN"
    if h_agg or a_agg:  return "ONE-SIDE"
    return "TIGHT"

# ----------------- TEAM AVERAGES & LEAGUE -----------------
KEY_STATS =[
    "Attacks", "Dangerous Attacks", "Shots Total", "Shots On Target", "Shots Insidebox",
    "Big Chances Created", "Key Passes", "Total Crosses", "Accurate Crosses",
    "Tackles", "Duels Won", "Interceptions", "Goals", "Corners", "Successful Passes Percentage", "Passes", "Ball Possession", "ball-possession"
]

def compute_team_averages_for_team_cached(team_id, target_date, limit=LAST_N_GAMES, team_cache=None):
    last_matches =[]
    if team_cache and team_id in team_cache:
        last_matches = team_cache[team_id][:limit]
    else:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        end_dt = (target_dt - timedelta(days=1)).isoformat()
        start_dt = (target_dt - timedelta(days=LOOKBACK_DAYS)).isoformat()
        try:
            resp = GET_ALL(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params={
                "include": "statistics;statistics.type;lineups;formations;participants;scores",
                "filters": "fixtureStates:5",
                "sortBy": "starting_at",
                "order": "desc"
            }, per_page=25, max_pages=3)
            last_matches = resp.get("data",[])[:limit]
        except Exception:
            last_matches =[]
    if not last_matches:
        return {}
    sums = defaultdict(float)
    counts = defaultdict(int)
    for fx in last_matches:
        stats = extract_stat_entries_for_participant(fx, team_id)
        for k, v in stats.items():
            if k in KEY_STATS:
                try:
                    sums[k] += float(v)
                    counts[k] += 1
                except Exception:
                    pass
    return {k: (round(sums[k]/counts[k],2) if counts[k] > 0 else 0.0) for k in KEY_STATS}

def compute_league_corner_density(league_id, target_date, num_fixtures=NUM_PAST_FIXTURES):
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    end_dt = (target_dt - timedelta(days=1)).isoformat()
    start_dt = (target_dt - timedelta(days=365*2)).isoformat()
    try:
        resp = GET_ALL(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}", params={"include":"participants;statistics;statistics.type;scores"}, per_page=50, max_pages=6)
        fixtures = resp.get("data", []) or[]
    except Exception:
        fixtures = []
    totals =[]
    for fx in fixtures[:num_fixtures]:
        parts = fx.get("participants", []) or[]
        t = 0
        for p in parts:
            pid = safe_int(p.get("id"))
            if pid:
                t += extract_corners_from_fixture(fx, pid)
        if t > 0:
            totals.append(t)
    if not totals:
        return 0.0
    avg = float(sum(totals))/len(totals)
    scaled = max(0.0, min(LEAGUE_SCALE, (avg - 4.0) / (18.0 - 4.0) * LEAGUE_SCALE))
    return round(scaled, 4)

# ----------------- OPPONENT INFLUENCE (VENUE AWARE) -----------------
def compute_opponent_influence_from_cache(team_id, team_cache, sample_limit=LAST_N_GAMES):
    resp = {
        "home": {"by_style": {}, "by_formation": {}, "samples": 0},
        "away": {"by_style": {}, "by_formation": {}, "samples": 0},
        "overall": {"by_style": {}, "by_formation": {}, "samples": 0}
    }

    fixtures = team_cache.get(team_id, [])[:NUM_PAST_FIXTURES]
    if not fixtures:
        return resp

    for fx in fixtures:
        participants = fx.get("participants",[]) or[]
        team_loc = None
        opp_id = None

        for p in participants:
            pid = safe_int(p.get("id"))
            if pid == safe_int(team_id):
                team_loc = (p.get("meta") or {}).get("location")
            elif pid and pid != safe_int(team_id):
                opp_id = pid

        if not opp_id or not team_loc:
            continue

        opp_stats = extract_stat_entries_for_participant(fx, opp_id)
        opp_style = assign_inplay_style_from_stats(opp_stats)
        opp_style_label = opp_style[0] if isinstance(opp_style, list) and opp_style else "Unknown"
        opp_formation = extract_formation_from_fixture(fx, opp_id) or "Unknown"
        team_corners = extract_corners_from_fixture(fx, team_id)

        def add_to_dict(target_dict):
            s = target_dict["by_style"].setdefault(opp_style_label, {"sum":0.0, "count":0})
            s["sum"] += team_corners
            s["count"] += 1
            f = target_dict["by_formation"].setdefault(opp_formation, {"sum":0.0, "count":0})
            f["sum"] += team_corners
            f["count"] += 1
            target_dict["samples"] += 1

        if team_loc in ["home", "away"] and resp[team_loc]["samples"] < sample_limit:
            add_to_dict(resp[team_loc])
        if resp["overall"]["samples"] < sample_limit:
            add_to_dict(resp["overall"])

        if resp["home"]["samples"] >= sample_limit and \
           resp["away"]["samples"] >= sample_limit and \
           resp["overall"]["samples"] >= sample_limit:
            break

    for loc in["home", "away", "overall"]:
        for k, v in list(resp[loc]["by_style"].items()):
            resp[loc]["by_style"][k] = {
                "avg_team_corners_when_opponent_played_this_style": round(v["sum"]/v["count"],2) if v["count"]>0 else 0.0,
                "samples": v["count"]
            }
        for k, v in list(resp[loc]["by_formation"].items()):
            resp[loc]["by_formation"][k] = {
                "avg_team_corners_when_opponent_used_formation": round(v["sum"]/v["count"],2) if v["count"]>0 else 0.0,
                "samples": v["count"]
            }

    return resp

# ----------------- PREDICTION (IMPROVED) -----------------
def _safe_mean(lst):
    if not lst:
        return 0.0
    try:
        return float(sum(lst))/len(lst)
    except:
        return 0.0

def _safe_std(lst):
    if not lst or len(lst) == 1:
        return 0.0
    try:
        mean = _safe_mean(lst)
        var = sum((x-mean)**2 for x in lst)/(len(lst)-1)
        return math.sqrt(var)
    except:
        return 0.0

def exponential_recency_weighted_mean(values, half_life=3.0):
    if not values:
        return 0.0
    weights =[]
    for i in range(len(values)):
        age = (len(values)-1 - i)
        w = 0.5 ** (age / half_life)
        weights.append(w)
    total_w = sum(weights)
    weighted = sum(v * w for v,w in zip(values, weights)) / (total_w or 1.0)
    return weighted

def predict_team_expected_corners(team_entry, opp_entry, league_corner_density=0.0):
    hist_list = list(team_entry.get("historical_corners") or [])[-HISTORICAL_MATCHES:]
    hist_list =[int(x) for x in hist_list if isinstance(x, (int,float,str)) and str(x).strip() != ""]
    hist_mean = _safe_mean(hist_list)
    hist_std = _safe_std(hist_list)

    recency_mean = exponential_recency_weighted_mean(hist_list, half_life=2.0)
    recent_avg = team_entry.get("recent_corners_avg") or recency_mean or hist_mean

    avg_stats = team_entry.get("avg_stats") or {}
    crosses = avg_stats.get("Total Crosses", 0.0)
    accurate = avg_stats.get("Accurate Crosses", 0.0)
    attacks = avg_stats.get("Attacks", 0.0)
    dangerous = avg_stats.get("Dangerous Attacks", 0.0)
    goals = avg_stats.get("Goals", 0.0)
    possession = avg_stats.get("Ball Possession", avg_stats.get("ball-possession", 50.0)) or 50.0

    baseline = 0.65 * recency_mean + 0.35 * hist_mean

    stat_boost = (min(crosses, 50) / 20.0) * 1.1 + (min(dangerous, 40) / 25.0) * 1.0 + (min(attacks, 120)/120.0) * 0.6
    form_bonus = (team_entry.get("formation_offense_score", 0) / 5.0) * 1.2

    inplay = team_entry.get("inplay_style", []) or[]
    style_bonus = 0.0
    if "Crossing/Counter" in inplay:
        style_bonus += 1.6
    if "Attacking" in inplay:
        style_bonus += 1.4
    if "Possession-Oriented" in inplay:
        style_bonus += 0.4

    opp_inf = team_entry.get("opponent_influence", {}) or {}
    opp_avg = 0.0
    opp_styles = (opp_entry or {}).get("inplay_style", []) or[]
    if opp_styles and opp_inf.get("by_style"):
        vals =[]
        for s in opp_styles:
            o = opp_inf["by_style"].get(s)
            if o and o.get("avg_team_corners_when_opponent_played_this_style") is not None:
                vals.append(o.get("avg_team_corners_when_opponent_played_this_style"))
        if vals:
            opp_avg = _safe_mean(vals)
    if opp_avg == 0.0 and opp_inf.get("by_formation"):
        o = opp_inf["by_formation"].get((opp_entry or {}).get("current_formation") or "Unknown")
        if o and o.get("avg_team_corners_when_opponent_used_formation") is not None:
            opp_avg = o.get("avg_team_corners_when_opponent_used_formation")
    if opp_avg == 0.0 and (opp_entry or {}).get("historical_corners_avg"):
        opp_avg = (opp_entry.get("historical_corners_avg") or 0.0) * 0.45

    opp_bonus = 0.0
    if opp_avg >= 6:
        opp_bonus += 1.1
    elif opp_avg >= 4:
        opp_bonus += 0.6
    else:
        opp_bonus += (opp_avg / 8.0) * 0.3

    h2h_list = team_entry.get("recent_h2h_values", []) or[]
    h2h_term = 0.0
    if h2h_list:
        h2h_mean = _safe_mean(h2h_list)
        if h2h_mean >= 6:
            h2h_term += 0.6
        elif h2h_mean >= 4:
            h2h_term += 0.3

    tmp = team_entry.get("predicted_tempo", "Low")
    tempo_index = 4.0 if tmp == "High" else (2.5 if tmp == "Moderate" else 1.0)
    tempo_term = (tempo_index / 5.0) * 0.9

    lineup_present = team_entry.get("today_starters_count", 0) >= 8 and (team_entry.get("current_formation") not in (None, "Unknown"))
    lineup_penalty = 1.0

    league_nudge = league_corner_density * 10.0

    raw_expected = baseline + stat_boost + form_bonus + style_bonus + opp_bonus + h2h_term + tempo_term + league_nudge
    expected = baseline * 0.6 + raw_expected * 0.4
    expected = expected * lineup_penalty

    opp_pos = (opp_entry or {}).get("avg_stats", {}).get("Ball Possession", (opp_entry or {}).get("avg_stats", {}).get("ball-possession", 50.0)) or 50.0
    possession_adj = 1.0 - (opp_pos / 160.0)
    expected *= possession_adj

    expected = max(0.0, min(expected, 20.0))

    hist_var = (hist_std ** 2) if hist_std else 1.5
    model_uncertainty = 2.0
    variance_estimate = hist_var + model_uncertainty

    coverage = min(1.0, len(hist_list) / max(1.0, float(HISTORICAL_MATCHES)))
    var_term = 1.0 - min(1.0, hist_std / (hist_mean + 1.0)) if hist_list else 0.35
    opp_samples = opp_inf.get("samples", 0)
    stability = team_entry.get("lineup_stability", 0.0)
    conf = 0.30 * var_term + 0.35 * coverage + 0.2 * min(1.0, opp_samples / float(max(1, LAST_N_GAMES))) + 0.15 * min(1.0, stability)
    if not lineup_present:
        conf -= 0.12
    if team_entry.get("rotation_count", 0) >= ROTATION_THRESHOLD:
        conf -= 0.08
    confidence = round(min(1.0, max(0.0, conf)), 2)

    return round(expected, 2), confidence, max(0.5, variance_estimate)

# ----------------- PRINT HELPERS / PROB -----------------
def normal_cdf(x, mu=0.0, sigma=1.0):
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    z = (x - mu) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))

def prob_home_beats_away(mu_h, var_h, mu_a, var_a):
    mu_d = mu_h - mu_a
    var_d = var_h + var_a
    sigma_d = math.sqrt(var_d) if var_d > 0 else 0.0001
    return round(1.0 - normal_cdf(0.0, mu=mu_d, sigma=sigma_d), 2)

# ----------------- DANGER LAYERS -----------------
def layer_danger_mark(value, kind):
    mark = "✅"
    if kind == "missing_keys":
        if value >= MISSING_KEYS_THRESHOLD:
            mark = "⚠️"
        elif value >= 2:
            mark = "⚡"
    elif kind == "rotation":
        if value >= ROTATION_THRESHOLD:
            mark = "⚠️"
        elif value >= 2:
            mark = "⚡"
    elif kind == "stability":
        if value < 0.5:
            mark = "⚠️"
        elif value < LINEUP_STABILITY_WARN:
            mark = "⚡"
    elif kind == "tempo":
        if value == "Low":
            mark = "⚠️"
        elif value == "Moderate":
            mark = "⚡"
    elif kind == "recent_goals":
        if value < GOALS_RECENT_WARN:
            mark = "⚠️"
        elif value < (GOALS_RECENT_WARN + 2):
            mark = "⚡"
    elif kind == "league_weight":
        if value < LEAGUE_WEIGHT_GOOD:
            mark = "⚠️"
        elif value < (LEAGUE_WEIGHT_GOOD + 0.2):
            mark = "⚡"
    return mark

def danger_level_from_score(score):
    if score <= 40:
        return "✅ SAFE"
    if score <= 65:
        return "⚡ MODERATE"
    return "🔴 DANGER"

# ----------------- FETCH FIXTURES -----------------
def fetch_fixtures_for_date(date_str):
    path_date = f"/fixtures/date/{date_str}"
    log_info(f"[INFO] fetch_fixtures_for_date: trying {path_date}")
    try:
        resp = GET_ALL(path_date, params={"include":"participants;statistics;statistics.type;lineups;formations;scores"}, per_page=50, max_pages=200)
        if resp.get("data"):
            return resp.get("data")
    except Exception as e:
        log_warn(f"[WARN] /fixtures/date failed: {e}")

    path_between = f"/fixtures/between/{date_str}/{date_str}"
    log_info(f"[INFO] fallback: {path_between}")
    try:
        resp = GET_ALL(path_between, params={"include":"participants;statistics;statistics.type;lineups;formations;scores"}, per_page=50, max_pages=200)
        if resp.get("data"):
            return resp.get("data")
    except Exception as e:
        log_warn(f"[WARN] /fixtures/between failed: {e}")

    d = datetime.strptime(date_str, "%Y-%m-%d")
    d0 = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (d + timedelta(days=1)).strftime("%Y-%m-%d")
    path_between2 = f"/fixtures/between/{d0}/{d1}"
    log_info(f"[INFO] final fallback: {path_between2}")
    try:
        resp = GET_ALL(path_between2, params={"include":"participants;statistics;statistics.type;lineups;formations;scores"}, per_page=50, max_pages=200)
        return resp.get("data", []) or[]
    except Exception as e:
        log_warn(f"[WARN] final fallback failed: {e}")
        return[]

# ----------------- MAIN PIPELINE -----------------

def get_last_finished_fixtures_cached(team_id, target_date, team_cache, limit=HISTORICAL_MATCHES):
    if team_id in team_cache:
        return team_cache[team_id][:limit]

    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    end_dt = (target_dt - timedelta(days=1)).isoformat()
    start_dt = (target_dt - timedelta(days=LOOKBACK_DAYS)).isoformat()

    try:
        resp = GET_ALL(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include": "statistics;statistics.type;lineups;formations;participants;scores",
                "filters": "fixtureStates:5",
                "sortBy": "starting_at",
                "order": "desc"
            },
            per_page=50,
            max_pages=6
        )
        team_cache[team_id] = resp.get("data", []) or []
    except Exception as e:
        log_warn(f"History fetch failed for team {team_id}: {e}")
        team_cache[team_id] =[]

    return team_cache[team_id][:limit]

# ==============================================================================
# 📦 ALIENEDGE BLACK BOX WRAPPER
# ==============================================================================
def run_corner_engine_stage1(target_date=None):
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        log_warn("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_info(f"Fetching fixtures for date (pagination enabled)... [{target_date}]")
    fixtures = fetch_fixtures_for_date(target_date)

    # ---------- BUILD ODDS MAP ----------
    odds_map = extract_fixture_odds_map(fixtures)

    if not fixtures:
        log_warn("No fixtures found.")
        return

    # ---------- LEAGUE DENSITY ----------
    league_corner_density = {}
    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id")}

    for lid in league_ids:
        try:
            league_corner_density[lid] = compute_league_corner_density(lid, target_date)
        except Exception:
            league_corner_density[lid] = 0.0

    team_cache = {}
    output =[]
    total_fixtures = len(fixtures)

    for idx, fx in enumerate(fixtures, start=1):
        # =========================================================
        # FIX 1: CRASH PROTECTION
        # Previously a single bad API call or malformed fixture
        # raised an unhandled exception that killed ALL remaining
        # fixtures. Now we log the failure and continue gracefully
        # so the rest of the pipeline always gets an output file.
        # =========================================================
        home_name = "Unknown"
        away_name = "Unknown"
        try:
            fixture_id = fx.get("id")

            odds = odds_map.get(fixture_id, {})
            home_win_odds = odds.get("home_win_odds")
            over25_odds = odds.get("over_2_5_odds")

            participants = fx.get("participants", []) or[]
            if len(participants) < 2:
                continue

            home_p = next(
                (p for p in participants if (p.get("meta") or {}).get("location") == "home"),
                participants[0]
            )
            away_p = next(
                (p for p in participants if (p.get("meta") or {}).get("location") == "away"),
                participants[1]
            )

            home_id = safe_int(home_p.get("id"))
            away_id = safe_int(away_p.get("id"))
            home_name = home_p.get("name")
            away_name = away_p.get("name")

            league_id = fx.get("league_id")
            corner_density = league_corner_density.get(league_id, 0.0)

            # ================= TEAM ANALYSIS =================
            def analyze_team(team_id, team_name):

                # --- Determine Target Venue for the current fixture ---
                target_venue = "home" if team_id == home_id else "away"

                # --- Fetch a larger pool of cached fixtures to allow for venue filtering ---
                all_hist = get_last_finished_fixtures_cached(team_id, target_date, team_cache, limit=50)

                # --- Separate into Home and Away histories ---
                home_hist = []
                away_hist =[]
                for hh in all_hist:
                    part_loc = None
                    for p in hh.get("participants",[]) or[]:
                        if safe_int(p.get("id")) == safe_int(team_id):
                            part_loc = (p.get("meta") or {}).get("location")
                            break
                    if part_loc == "home":
                        home_hist.append(hh)
                    elif part_loc == "away":
                        away_hist.append(hh)

                venue_hist = home_hist if target_venue == "home" else away_hist

                # --- Fallback Mechanism ---
                if len(venue_hist) < 4:
                    log_info(f"  [{team_name}] Venue history short ({len(venue_hist)} at {target_venue}), using all-venue fallback ({len(all_hist)} matches).")
                    venue_hist = all_hist

                last_hist = venue_hist[:HISTORICAL_MATCHES]
                recent = venue_hist[:LAST_N_GAMES]

                # ---------- HISTORICAL CORNERS ----------
                hist =[]
                try:
                    for hh in last_hist:
                        c = extract_corners_from_fixture(hh, team_id)
                        if c is not None:
                            hist.append(c)
                except Exception:
                    pass

                lastN_list = hist[:LAST_N_GAMES]
                lastN_avg = round(_safe_mean(lastN_list), 2) if lastN_list else 0.0

                # --- Persistence Metric (Over 4 corners in last 4 or 5 matches) ---
                over_4_count = sum(1 for c in lastN_list if c > 4)
                is_persistent = (over_4_count >= 4 and len(lastN_list) >= 4)

                # ---------- RECENT FIXTURES ----------
                recent_lineups = []
                recent_corners =[]

                for r in recent:
                    s = extract_starters_from_fixture(r, team_id)
                    recent_lineups.append(s)
                    recent_corners.append(
                        extract_corners_from_fixture(r, team_id)
                    )

                # ---------- TODAY LINEUP ----------
                today_starters = extract_starters_from_fixture(fx, team_id)
                today_ids =[
                    safe_int(p.get("player_id"))
                    for p in today_starters if p.get("player_id")
                ]

                valid_lineups =[
                    l for l in recent_lineups
                    if isinstance(l, list) and len(l) >= 8
                ]

                # ---------- KEY PLAYER / ROTATION ----------
                missing_key_players = 0
                rotation_count = 0
                lineup_stability = 0.0

                if valid_lineups:
                    counts = Counter()
                    for lp in valid_lineups:
                        for p in lp:
                            pid = p.get("player_id")
                            if pid:
                                counts[pid] += 1

                    thresh = math.ceil(len(valid_lineups) * 0.6)
                    key_players = {pid for pid, cnt in counts.items() if cnt >= thresh}

                    today_set = set(today_ids)

                    missing_key_players = sum(
                        1 for pid in key_players if pid not in today_set
                    )

                    unique_recent_starters = {
                        pid for lp in valid_lineups
                        for pid in[p.get("player_id") for p in lp if p.get("player_id")]
                    }

                    rotation_count = min(
                        sum(1 for pid in unique_recent_starters if pid not in today_set),
                        11
                    )

                    if key_players:
                        lineup_stability = round(
                            len(key_players.intersection(today_set)) / len(key_players),
                            2
                        )

                # ---------- FORMATION ----------
                current_formation = extract_formation_from_fixture(
                    fx, team_id
                ) or "Unknown"

                parsed = (
                    parse_formation(current_formation)
                    if current_formation != "Unknown"
                    else None
                )

                # --- Venue-Aware Team Averages ---
                def calc_averages(fx_list):
                    used = fx_list[:LAST_N_GAMES]
                    if not used: return {}
                    sums = defaultdict(float)
                    counts = defaultdict(int)
                    for f in used:
                        sts = extract_stat_entries_for_participant(f, team_id)
                        for k, v in sts.items():
                            if k in KEY_STATS:
                                try:
                                    sums[k] += float(v)
                                    counts[k] += 1
                                except Exception:
                                    pass
                    return {k: (round(sums[k]/counts[k],2) if counts[k] > 0 else 0.0) for k in KEY_STATS}

                home_avg_stats = calc_averages(home_hist)
                away_avg_stats = calc_averages(away_hist)

                # Context-aware stats used for main prediction logic
                avg_stats = calc_averages(venue_hist)

                # --- Venue-Aware Opponent Influence ---
                full_opp_inf = compute_opponent_influence_from_cache(team_id, team_cache)

                # Pick specific venue influence, fallback to overall if empty
                opponent_influence = full_opp_inf.get(target_venue, full_opp_inf.get("overall", {}))

                # Double-check if the specific venue had enough samples, fallback if not
                if opponent_influence.get("samples", 0) < 2:
                    opponent_influence = full_opp_inf.get("overall", {})

                # ---------- IN-PLAY STYLE ----------
                shots_total = avg_stats.get("Shots Total", 0.0)
                if shots_total >= 14:
                    inplay_style = ["Attacking"]
                elif shots_total >= 9:
                    inplay_style = ["Balanced"]
                else:
                    inplay_style =["Passive"]

                # ---------- FORMATION OFFENSE SCORE ----------
                formation_offense_score = 0.0
                if parsed:
                    formation_offense_score = round(
                        parsed.get("forwards", 0) +
                        parsed.get("midfielders", 0) * 0.5,
                        2
                    )

                # ---------- PREDICTED TEMPO ----------
                tempo_raw = (
                    avg_stats.get("Shots Total", 0.0) * 0.4 +
                    avg_stats.get("Corners", 0.0) * 0.35 +
                    formation_offense_score * 0.25
                )

                if tempo_raw >= 7.0:
                    predicted_tempo = "High"
                elif tempo_raw >= 4.0:
                    predicted_tempo = "Moderate"
                else:
                    predicted_tempo = "Low"

                # ---------- FINAL TEAM PACKAGE ----------
                return {
                    "team_id": team_id,
                    "team_name": team_name,

                    "historical_corners": hist,
                    "historical_corners_avg": round(_safe_mean(hist), 2) if hist else 0.0,
                    "recent_corners_avg": round(_safe_mean(recent_corners), 2) if recent_corners else 0.0,
                    "lastN_corners_list": lastN_list,
                    "lastN_corners_avg": lastN_avg,

                    "over_4_corners_count": over_4_count,
                    "is_persistent_over_4": is_persistent,

                    "today_starters_count": len(today_starters),
                    "today_player_ids": today_ids,
                    "missing_key_players": missing_key_players,
                    "rotation_count": rotation_count,
                    "lineup_stability": lineup_stability,

                    "current_formation": current_formation,
                    "parsed_formation": parsed,
                    "formation_offense_score": formation_offense_score,
                    "inplay_style": inplay_style,
                    "predicted_tempo": predicted_tempo,

                    "opponent_influence": opponent_influence,
                    "full_opponent_influence": full_opp_inf,

                    "avg_stats": avg_stats,
                    "home_avg_stats": home_avg_stats,
                    "away_avg_stats": away_avg_stats,
                }

            home_team = analyze_team(home_id, home_name)
            away_team = analyze_team(away_id, away_name)

            e_home, conf_home, var_home = predict_team_expected_corners(
                home_team, away_team, corner_density
            )
            e_away, conf_away, var_away = predict_team_expected_corners(
                away_team, home_team, corner_density
            )

            expected_difference = round(e_home - e_away, 2)

            team_more_corners = (
                home_name if expected_difference > 0.5
                else away_name if expected_difference < -0.5
                else "Tight"
            )

            team_more_corners_probability_like = prob_home_beats_away(
                e_home, var_home, e_away, var_away
            )

            # ---------- TOTAL CORNERS & TIER ----------
            expected_total = round(e_home + e_away, 2)

            if expected_total >= THRESH_HIGH:
                corner_tier = "High"
            elif expected_total >= THRESH_STRONG:
                corner_tier = "Strong"
            elif expected_total >= THRESH_MODERATE:
                corner_tier = "Moderate"
            else:
                corner_tier = "Low"

            # ---------- TIER 1A / 1B ----------
            tier_1_priority = assign_tier_1_priority(
                corner_tier,
                home_win_odds,
                over25_odds
            )

            out_item = {
                # =======================================================
                # FIX 2: fixture_id is now included in every output item.
                # Stage 2 maps by (home_id, away_id) but carrying the
                # fixture_id avoids any ambiguity and lets Catalyst and
                # the Aggregator link back to the raw fixture directly.
                # =======================================================
                "fixture_id": fixture_id,
                "fixture": f"{home_name} vs {away_name}",
                "expected_total_corners": expected_total,
                "corner_tier": corner_tier,
                "expected_difference": expected_difference,
                "team_more_corners": team_more_corners,
                "team_more_corners_probability_like": team_more_corners_probability_like,
                "avg_confidence": round((conf_home + conf_away) / 2, 2),
                "home_win_odds": home_win_odds,
                "over_2_5_odds": over25_odds,
                "tier_1_priority": tier_1_priority,
                "home_team": home_team,
                "away_team": away_team,
            }

            output.append(out_item)

        except Exception as e:
            # FIX 1 CONTINUED: Log which fixture failed and skip it.
            # The pipeline continues and remaining fixtures are processed.
            log_error(f"Fixture [{home_name} vs {away_name}] (idx={idx}) failed and was skipped: {e}")
            continue

    # ---------- OUTPUT ----------
    ranked = sorted(output, key=lambda x: x.get("expected_total_corners", 0.0), reverse=True)
    print("\n=== Ranked Fixtures by Expected Total Corners (v6 - Venue Filtered) ===")

    header = f"{'Rk':>3}  {'Fixture':50}  {'Total':>6}  {'Tier':>7}  {'MoreCorners':>18}  {'Diff':>6}  {'Prob':>5}  {'HomeLastN(avg)':>16}  {'AwayLastN(avg)':>16}"
    print(header)

    for i, fx in enumerate(ranked, start=1):
        total = fx.get("expected_total_corners", 0.0)
        tier = fx.get("corner_tier", "Unknown")
        more = fx.get("team_more_corners", "Tight")
        diff = fx.get("expected_difference", 0.0)
        prob = fx.get("team_more_corners_probability_like", 0.5)
        h = fx.get("home_team", {})
        a = fx.get("away_team", {})
        home_lastN_list = h.get("lastN_corners_list", [])[:LAST_N_GAMES]
        away_lastN_list = a.get("lastN_corners_list", [])[:LAST_N_GAMES]
        home_lastN_avg = h.get("lastN_corners_avg", 0.0)
        away_lastN_avg = a.get("lastN_corners_avg", 0.0)
        name = (fx.get("fixture") or "")[:50]

        print(f"{i:>3}  {name:50}  {total:6.2f}  {tier:>7}  {more:>18}  {diff:6.2f}  {prob:5.2f}  {str(home_lastN_list):>16}  {str(away_lastN_list):>16}")
        print(f"      HomeLastN_avg: {home_lastN_avg:.2f} | AwayLastN_avg: {away_lastN_avg:.2f}\n")

    # ---------- NEW: PERSISTENT CORNER KINGS OUTPUT ----------
    persistent_matches =[]
    for fx in output:
        h_pers = fx["home_team"].get("is_persistent_over_4", False)
        a_pers = fx["away_team"].get("is_persistent_over_4", False)
        h_count = fx["home_team"].get("over_4_corners_count", 0)
        a_count = fx["away_team"].get("over_4_corners_count", 0)

        if h_pers or a_pers:
            score = 2 if (h_pers and a_pers) else 1
            persistent_matches.append({
                "fixture": fx["fixture"],
                "score": score,
                "total": fx["expected_total_corners"],
                "h_count": h_count,
                "a_count": a_count,
                "h_list": fx["home_team"].get("lastN_corners_list",[]),
                "a_list": fx["away_team"].get("lastN_corners_list",[])
            })

    persistent_matches.sort(key=lambda x: (x["score"], x["total"]), reverse=True)

    print("\n" + "="*95)
    print("🔄 THE PERSISTENT CORNER KINGS (Home/Away Filtered)")
    print("Teams with at least 4 out of last 5 matches generating > 4 corners (Filtered by exact Match Venue).")
    print("="*95)
    print(f"{'Rk':>3}  {'Fixture':50}  {'Rating':>10}  {'Exp Total':>9}  {'Home >4 Cnt':>12}  {'Away >4 Cnt':>12}")

    if not persistent_matches:
        print("    [!] No persistent matches found today.")
    else:
        for i, p in enumerate(persistent_matches, start=1):
            rating = "⭐⭐ BOTH" if p["score"] == 2 else "⭐ ONE"
            print(f"{i:>3}  {p['fixture']:50}  {rating:>10}  {p['total']:9.2f}  {str(p['h_count'])+'/5':>12}  {str(p['a_count'])+'/5':>12}")
            print(f"      Home Corners: {p['h_list']} | Away Corners: {p['a_list']}\n")

    # ---------- FILTER & SAVE FOR CODE 2 ----------
    qualified_matches =[]
    for item in output:
        if item["corner_tier"] in ["Moderate", "Strong", "High"] and item["avg_confidence"] > 0.45:
            qualified_matches.append(item)

    output_path = os.path.join(OUTPUT_DIR, "corner3_qualified.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(qualified_matches, f, ensure_ascii=False, indent=2)

    log_info(f"Saved {len(qualified_matches)} qualified matches to {output_path} for processing by Code 2.")
    log_info(f"Stage 1 complete. Processed {len(output)}/{total_fixtures} fixtures successfully.")

if __name__ == "__main__":
    today_test = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_corner_engine_stage1(today_test)