import os
import sys
import time
import requests
import math
import json
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# ==============================================================================
# ALIENEDGE CORNER ENGINE — STAGE 2 (REFINER)
# Version: 10.1 — Pure Math & Tactical Architecture
#
# CHANGES:
#   1. Wounded Beast logic surgically removed (relocated to Code 3 for separation of concerns).
#   2. Purely focused on Stage 1 + Stage 2 blending, venue persistence, and opponent influence.
#   3. Saves ultra-clean backend_2_output.json for the Catalyst Brain to consume.
# ==============================================================================

load_dotenv()

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")
DATA_DIR    = os.path.join(BASE_DIR, "data")

# ─────────────────────────── CONFIG ───────────────────────────
API_KEY               = os.getenv("SPORTMONKS_API_KEY")
BASE_URL              = "https://api.sportmonks.com/v3/football"
REQUEST_DELAY         = 0.12
MAX_RETRIES           = 4
RETRY_BACKOFF         = 1.5
HISTORICAL_MATCHES    = 8
LAST_N_GAMES          = 5
LOOKBACK_DAYS         = 365
NUM_PAST_FIXTURES     = 100
LEAGUE_SCALE          = 0.30
DEBUG_LOCAL_FIXTURES_PATH = None

# Stage 1 / Stage 2 blend weights
STAGE1_WEIGHT = 0.50
STAGE2_WEIGHT = 0.50

# ─────────────────────────── THRESHOLDS ───────────────────────
THRESH_HIGH           = 12.5
THRESH_STRONG         = 10.0
THRESH_MODERATE       = 8.5
MISSING_KEYS_THRESHOLD = 3
ROTATION_THRESHOLD    = 4
LINEUP_STABILITY_WARN = 0.6
GOALS_RECENT_WARN     = 7
LEAGUE_WEIGHT_GOOD    = 0.8

# ─────────────────────────── LOGGING ──────────────────────────
def log_info(*p):  print("[INFO]",  *p)
def log_warn(*p):  print("[WARN]",  *p)
def log_error(*p): print("[ERROR]", *p)
def log_debug(*p):
    if os.getenv("DEBUG") == "1": print("[DEBUG]", *p)

# ─────────────────────────── HELPERS ──────────────────────────
def safe_int(x, default=None):
    try:
        return default if x is None else int(str(x))
    except Exception:
        return default

def _safe_mean(lst):
    return float(sum(lst)) / len(lst) if lst else 0.0

def _safe_std(lst):
    if not lst or len(lst) == 1:
        return 0.0
    mean = _safe_mean(lst)
    return math.sqrt(sum((x - mean) ** 2 for x in lst) / (len(lst) - 1))

# ─────────────────────────── NETWORK ──────────────────────────
def _request_with_retries(url, params, retries=MAX_RETRIES):
    attempt = 0
    last_exc = None
    while attempt <= retries:
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = (RETRY_BACKOFF ** attempt) + 1
                log_warn(f"429 rate limit — sleeping {wait:.1f}s (attempt {attempt}/{retries})")
                time.sleep(wait)
                attempt += 1
                continue
            if r.status_code >= 500:
                wait = RETRY_BACKOFF ** attempt
                log_warn(f"{r.status_code} server error — sleeping {wait:.1f}s (attempt {attempt}/{retries})")
                time.sleep(wait)
                attempt += 1
                continue
            r.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return r.json()
        except requests.RequestException as e:
            last_exc = e
            wait = RETRY_BACKOFF ** attempt
            log_warn(f"Request error: {e}. Sleeping {wait:.1f}s (attempt {attempt}/{retries})")
            time.sleep(wait)
            attempt += 1
    raise RuntimeError(f"Failed to fetch {url} after {retries} retries. Last error: {last_exc}")

def GET(path, params=None):
    if params is None:
        params = {}
    params = dict(params)
    params.setdefault("api_token", API_KEY)
    log_debug("GET", f"{BASE_URL}{path}", params)
    return _request_with_retries(f"{BASE_URL}{path}", params)

def GET_ALL(path, params=None, per_page=50, max_pages=500):
    if DEBUG_LOCAL_FIXTURES_PATH:
        try:
            with open(DEBUG_LOCAL_FIXTURES_PATH, "r", encoding="utf-8") as fh:
                return {"data": json.load(fh), "meta": {}}
        except Exception as e:
            log_warn("Local debug file failed:", e)

    if params is None:
        params = {}
    params = dict(params)
    params.setdefault("api_token", API_KEY)
    params.setdefault("per_page", per_page)

    all_data  = []
    page      = 1
    last_meta = {}
    first_page = True

    while page <= max_pages:
        params["page"] = page
        try:
            payload = _request_with_retries(f"{BASE_URL}{path}", params)
        except Exception as e:
            if first_page:
                raise
            log_warn(f"Pagination interrupted at page {page} ({e}). "
                     f"Returning {len(all_data)} records collected so far.")
            break

        first_page = False
        data      = payload.get("data", []) if isinstance(payload, dict) else (payload or [])
        last_meta = payload.get("meta", {}) if isinstance(payload, dict) else {}

        if data:
            all_data.extend(data)

        pagination = last_meta.get("pagination") if isinstance(last_meta, dict) else None
        if pagination:
            next_page = pagination.get("next_page")
            if not next_page:
                break
            try:
                page = int(next_page)
                continue
            except Exception:
                page += 1
                continue

        if not data or len(data) < per_page:
            break
        page += 1

    return {"data": all_data, "meta": last_meta}

# ─────────────────────────── STAT EXTRACTION ──────────────────
def extract_stat_entries_for_participant(fx, participant_id):
    stats   = fx.get("statistics", []) or []
    result  = {}
    entries = []

    if isinstance(stats, dict):
        pid_str = str(participant_id)
        if pid_str in stats:
            maybe = stats.get(pid_str) or []
            if isinstance(maybe, dict) and "statistics" in maybe:
                entries = maybe.get("statistics", [])
            elif isinstance(maybe, list):
                entries = maybe
            else:
                entries = [maybe]
        else:
            for v in stats.values():
                if isinstance(v, list):
                    entries.extend(v)
                elif isinstance(v, dict) and "statistics" in v:
                    entries.extend(v.get("statistics", []))
                else:
                    entries.append(v)
    elif isinstance(stats, list):
        entries = stats

    for s in entries or []:
        if not isinstance(s, dict):
            continue
        stat_type = (
            s.get("type", {}).get("name")
            if isinstance(s.get("type"), dict)
            else s.get("name") or s.get("stat") or s.get("type")
        )
        if not stat_type:
            continue
        pid = (
            s.get("participant_id") or s.get("team_id")
            or s.get("participantId") or s.get("teamId")
        )
        if pid is None and isinstance(s.get("data"), dict):
            pid = s["data"].get("participant_id") or s["data"].get("team_id")
        if pid is None or safe_int(pid) != safe_int(participant_id):
            continue
        val = (
            s["data"].get("value")
            if isinstance(s.get("data"), dict)
            else s.get("value")
        )
        if val is None and isinstance(s.get("data"), dict):
            val = s.get("data", {}).get("value")
        if val is None or val == "":
            continue
        if isinstance(val, str) and val.endswith("%"):
            val = val.rstrip("%").strip()
        try:
            result[str(stat_type)] = float(str(val).replace(",", "").strip())
        except Exception:
            continue
    return result

def extract_corners_from_fixture(fx, team_id):
    entries = extract_stat_entries_for_participant(fx, team_id)
    if entries.get("Corners") is not None:
        try:
            return int(round(float(entries["Corners"])))
        except Exception:
            pass
    for k, v in entries.items():
        if isinstance(k, str) and "corner" in k.lower():
            try:
                return int(round(float(v)))
            except Exception:
                continue
    return 0

def extract_final_goals_from_scores(scores):
    home, away = None, None
    for entry in (scores or []):
        if not isinstance(entry, dict):
            continue
        s    = entry.get("score") or entry
        part = s.get("participant")
        g    = s.get("goals")
        if isinstance(g, str):
            try:
                g = int(g)
            except Exception:
                g = None
        if isinstance(g, (int, float)):
            g = int(g)
            if part == "home":
                home = g if home is None else max(home, g)
            elif part == "away":
                away = g if away is None else max(away, g)
    return home, away

def extract_formation_from_fixture(fx, team_id):
    for f in fx.get("formations", []) or []:
        if safe_int(f.get("participant_id") or f.get("participantId")) == safe_int(team_id):
            return f.get("formation")
    return None

def extract_starters_from_fixture(fx, team_id):
    starters = []
    for l in fx.get("lineups", []) or []:
        tid   = safe_int(l.get("team_id") or l.get("teamId"))
        ttype = safe_int(l.get("type_id") or l.get("typeId"))
        if tid == safe_int(team_id) and (ttype is None or ttype == 11):
            starters.append({
                "player_id":   l.get("player_id")   or l.get("playerId"),
                "player_name": l.get("player_name") or l.get("playerName"),
            })
    return starters

# ─────────────────────────── FORMATION ────────────────────────
def parse_formation(formation_str):
    if not formation_str or not isinstance(formation_str, str):
        return None
    parts  = formation_str.replace(":", "-").replace(" ", "-").split("-")
    digits = [int(x) for x in parts if x.isdigit()]
    if not digits:
        return None
    defenders   = digits[0]
    forwards    = digits[-1]
    midfielders = sum(digits[1:-1]) if len(digits) > 2 else max(0, 10 - defenders - forwards)
    return {"defenders": defenders, "midfielders": midfielders,
            "forwards": forwards, "parts": digits}

def formation_offense_score_from_parsed(parsed):
    """Returns an offensive score 0-5 based on formation shape."""
    if not parsed:
        return 0
    fwd, mid, d = parsed.get("forwards", 0), parsed.get("midfielders", 0), parsed.get("defenders", 0)
    score = 0
    if fwd >= 3:   score += 2
    elif fwd == 2: score += 1
    if mid >= 5:   score += 1
    if mid >= 3 and fwd >= 1: score += 1
    if d >= 5:     score = max(0, score - 1)
    return min(5, score)

# ─────────────────────────── STYLE ────────────────────────────
KEY_STATS = [
    "Attacks", "Dangerous Attacks", "Shots Total", "Shots On Target",
    "Shots Insidebox", "Big Chances Created", "Key Passes",
    "Total Crosses", "Accurate Crosses", "Tackles", "Duels Won",
    "Interceptions", "Goals", "Corners",
    "Successful Passes Percentage", "Passes",
    "Ball Possession", "ball-possession",
]

def assign_inplay_style_from_stats(stat_map):
    labels = []
    attacks         = stat_map.get("Attacks", 0.0)
    dang            = stat_map.get("Dangerous Attacks", 0.0)
    crosses         = stat_map.get("Total Crosses", 0.0)
    accurate_crosses = stat_map.get("Accurate Crosses", 0.0)
    passes_acc      = stat_map.get("Successful Passes Percentage", None)
    tackles         = stat_map.get("Tackles", 0.0)
    interceptions   = stat_map.get("Interceptions", 0.0)

    if attacks >= 75 and dang >= 45:         labels.append("Attacking")
    if crosses >= 16 and accurate_crosses >= 4: labels.append("Crossing/Counter")
    if tackles >= 14 and interceptions >= 6: labels.append("Defensive")
    if passes_acc is not None and passes_acc >= 75: labels.append("Possession-Oriented")
    return labels if labels else ["Balanced/Other"]

def assign_tactical_style_from_formation(formation_str):
    parsed = parse_formation(formation_str)
    if not parsed:
        return ["Unknown"]
    d, m, f = parsed["defenders"], parsed["midfielders"], parsed["forwards"]
    if f >= 3 and m >= 3: return ["Offensive"]
    if d >= 5:            return ["Defensive"]
    if m >= 5:            return ["Possession-Oriented"]
    return ["Neutral"]

def determine_style_alignment(h_style, a_style):
    aggressive = ["Attacking", "Crossing/Counter"]
    h_agg = any(s in aggressive for s in h_style)
    a_agg = any(s in aggressive for s in a_style)
    if h_agg and a_agg: return "OPEN"
    if h_agg or a_agg:  return "ONE_SIDE"
    return "TIGHT"

# ─────────────────────────── AVERAGES ─────────────────────────
def compute_team_averages(fx_list, team_id, limit=LAST_N_GAMES):
    used  = fx_list[:limit]
    if not used:
        return {}
    sums, counts = defaultdict(float), defaultdict(int)
    for f in used:
        for k, v in extract_stat_entries_for_participant(f, team_id).items():
            if k in KEY_STATS:
                try:
                    sums[k]   += float(v)
                    counts[k] += 1
                except Exception:
                    pass
    return {k: (round(sums[k] / counts[k], 2) if counts[k] > 0 else 0.0) for k in KEY_STATS}

def compute_league_corner_density(league_id, target_date, num_fixtures=NUM_PAST_FIXTURES):
    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    end_dt    = (target_dt - timedelta(days=1)).isoformat()
    start_dt  = (target_dt - timedelta(days=365 * 2)).isoformat()
    try:
        resp     = GET_ALL(f"/fixtures/between/{start_dt}/{end_dt}/{league_id}",
                           params={"include": "participants;statistics;statistics.type;scores"},
                           per_page=50, max_pages=6)
        fixtures = resp.get("data", []) or []
    except Exception:
        return 0.0
    totals = []
    for fx in fixtures[:num_fixtures]:
        t = sum(
            extract_corners_from_fixture(fx, safe_int(p.get("id")))
            for p in fx.get("participants", [])
            if safe_int(p.get("id"))
        )
        if t > 0:
            totals.append(t)
    if not totals:
        return 0.0
    avg    = float(sum(totals)) / len(totals)
    scaled = max(0.0, min(LEAGUE_SCALE, (avg - 4.0) / (18.0 - 4.0) * LEAGUE_SCALE))
    return round(scaled, 4)

# ─────────────────────────── OPPONENT INFLUENCE (VENUE-AWARE) ─
def compute_opponent_influence_venue_aware(team_id, team_cache, target_venue, sample_limit=LAST_N_GAMES):
    """
    Tracks influence separately for home / away / overall.
    Uses target_venue to pick the most relevant slice.
    Falls back to overall if venue slice has < 2 samples.
    """
    result = {
        "home":    {"by_style": {}, "by_formation": {}, "samples": 0},
        "away":    {"by_style": {}, "by_formation": {}, "samples": 0},
        "overall": {"by_style": {}, "by_formation": {}, "samples": 0},
    }

    fixtures = team_cache.get(team_id, [])[:NUM_PAST_FIXTURES]
    if not fixtures:
        return result

    for fx in fixtures:
        participants = fx.get("participants", []) or []
        team_loc = None
        opp_id   = None

        for p in participants:
            pid = safe_int(p.get("id"))
            if pid == safe_int(team_id):
                team_loc = (p.get("meta") or {}).get("location")
            elif pid:
                opp_id = pid

        if not opp_id or not team_loc:
            continue

        opp_stats      = extract_stat_entries_for_participant(fx, opp_id)
        opp_style      = assign_inplay_style_from_stats(opp_stats)
        opp_style_lbl  = opp_style[0] if opp_style else "Unknown"
        opp_formation  = extract_formation_from_fixture(fx, opp_id) or "Unknown"
        team_corners   = extract_corners_from_fixture(fx, team_id)

        def _add(bucket):
            s = bucket["by_style"].setdefault(opp_style_lbl, {"sum": 0.0, "count": 0})
            s["sum"] += team_corners; s["count"] += 1
            f = bucket["by_formation"].setdefault(opp_formation, {"sum": 0.0, "count": 0})
            f["sum"] += team_corners; f["count"] += 1
            bucket["samples"] += 1

        if team_loc in ("home", "away") and result[team_loc]["samples"] < sample_limit:
            _add(result[team_loc])
        if result["overall"]["samples"] < sample_limit:
            _add(result["overall"])

    # Average-ise
    for loc in ("home", "away", "overall"):
        for k, v in list(result[loc]["by_style"].items()):
            result[loc]["by_style"][k] = {
                "avg_corners": round(v["sum"] / v["count"], 2) if v["count"] else 0.0,
                "samples":     v["count"],
            }
        for k, v in list(result[loc]["by_formation"].items()):
            result[loc]["by_formation"][k] = {
                "avg_corners": round(v["sum"] / v["count"], 2) if v["count"] else 0.0,
                "samples":     v["count"],
            }

    specific = result.get(target_venue, {})
    if specific.get("samples", 0) >= 2:
        return specific
    log_debug(f"Opponent influence: venue '{target_venue}' only {specific.get('samples',0)} samples — using overall")
    return result["overall"]

# ─────────────────────────── FIXTURES ─────────────────────────
def fetch_fixtures_for_date(date_str):
    includes = "participants;statistics;statistics.type;lineups;formations;scores"
    params   = {"include": includes}

    try:
        resp = GET_ALL(f"/fixtures/date/{date_str}", params=params,
                       per_page=50, max_pages=200)
        if resp.get("data"):
            return resp["data"]
    except Exception as e:
        log_warn(f"/fixtures/date failed: {e}")

    try:
        resp = GET_ALL(f"/fixtures/between/{date_str}/{date_str}", params=params,
                       per_page=50, max_pages=200)
        if resp.get("data"):
            return resp["data"]
    except Exception as e:
        log_warn(f"/fixtures/between same-day failed: {e}")

    d = datetime.strptime(date_str, "%Y-%m-%d")
    d0 = (d - timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (d + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        resp = GET_ALL(f"/fixtures/between/{d0}/{d1}", params=params,
                       per_page=50, max_pages=200)
        return resp.get("data", []) or []
    except Exception as e:
        log_warn(f"Final fixture fallback failed: {e}")
        return []

def get_last_finished_fixtures_cached(team_id, target_date, team_cache, limit=HISTORICAL_MATCHES):
    if team_id in team_cache:
        return team_cache[team_id][:limit]

    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    start_dt  = (target_dt - timedelta(days=LOOKBACK_DAYS)).isoformat()
    end_dt    = (target_dt - timedelta(days=1)).isoformat()

    try:
        resp = GET_ALL(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "statistics;statistics.type;lineups;formations;participants;scores",
                "filters":  "fixtureStates:5",
                "sortBy":   "starting_at",
                "order":    "desc",
            },
            per_page=50, max_pages=6,
        )
        team_cache[team_id] = resp.get("data", []) or []
    except Exception as e:
        log_warn(f"Could not fetch history for team {team_id}: {e}")
        team_cache[team_id] = []

    return team_cache[team_id][:limit]

# ─────────────────────────── PREDICTION ───────────────────────
def predict_team_expected_corners_stage2(team_entry, opp_entry, league_corner_density=0.0):
    hist        = team_entry.get("historical_corners") or []
    hist_mean   = _safe_mean(hist)
    hist_std    = _safe_std(hist)
    recent_mean = team_entry.get("recent_corners_avg") or hist_mean
    avg_stats   = team_entry.get("avg_stats") or {}
    crosses     = avg_stats.get("Total Crosses", 0.0)
    accurate    = avg_stats.get("Accurate Crosses", 0.0)
    goals       = avg_stats.get("Goals", 0.0)

    points = 0.0

    if hist_mean >= 6:   points += 2.0
    elif hist_mean >= 4: points += 1.0
    else:                points += 0.25 * (hist_mean / 4.0)

    if recent_mean >= 6:   points += 1.8
    elif recent_mean >= 4: points += 1.0
    else:                   points += 0.25 * (recent_mean / 4.0)

    inplay = team_entry.get("inplay_style", []) or []
    if "Crossing/Counter" in inplay: points += 1.6
    if "Attacking"        in inplay: points += 1.4
    if "Possession-Oriented" in inplay: points += 0.4

    points += (team_entry.get("formation_offense_score", 0) / 5.0) * 1.5
    tempo_index = (4.0 if team_entry.get("predicted_tempo") == "High"
                   else 2.5 if team_entry.get("predicted_tempo") == "Moderate" else 1.0)
    points += (tempo_index / 5.0) * 1.5

    points += team_entry.get("lineup_stability", 0.0) * 1.2

    opp_inf  = team_entry.get("opponent_influence", {}) or {}
    opp_avg  = 0.0
    opp_stls = (opp_entry or {}).get("inplay_style", []) or []
    if opp_stls and opp_inf.get("by_style"):
        vals = [
            opp_inf["by_style"][s].get("avg_corners")
            for s in opp_stls
            if opp_inf["by_style"].get(s) and opp_inf["by_style"][s].get("avg_corners") is not None
        ]
        if vals:
            opp_avg = _safe_mean(vals)
    if opp_avg == 0.0 and opp_inf.get("by_formation"):
        o = opp_inf["by_formation"].get((opp_entry or {}).get("current_formation") or "Unknown")
        if o and o.get("avg_corners") is not None:
            opp_avg = o["avg_corners"]
    if opp_avg == 0.0 and (opp_entry or {}).get("historical_corners_avg"):
        opp_avg = (opp_entry["historical_corners_avg"] or 0.0) * 0.5

    if opp_avg >= 6:   points += 1.2
    elif opp_avg >= 4: points += 0.6
    else:               points += (opp_avg / 8.0) * 0.4

    h2h_list = team_entry.get("recent_h2h_values", []) or []
    if h2h_list:
        weights  = [0.6 ** i for i in range(len(h2h_list))]
        weighted = sum(w * v for w, v in zip(weights, h2h_list)) / (sum(weights) or 1.0)
        if weighted >= 6:   points += 0.8
        elif weighted >= 4: points += 0.4

    expected = (
        points * 0.9
        + (crosses / 20.0) * 1.2
        + (accurate / 8.0) * 0.8
        + goals * 0.5
        + league_corner_density * 10.0
    )

    opp_pos = (
        (opp_entry or {}).get("avg_stats", {}).get("Ball Possession")
        or (opp_entry or {}).get("avg_stats", {}).get("ball-possession")
        or 50.0
    ) or 50.0
    expected *= 1.0 - (opp_pos / 150.0)

    lineup_present = (
        team_entry.get("today_starters_count", 0) >= 8
        and team_entry.get("current_formation") not in (None, "Unknown")
    )
    expected = max(0.0, min(expected * 0.90, 18.0))

    conf = (
        0.30 * (1.0 - min(1.0, hist_std / (hist_mean + 1.0)) if hist else 0.5)
        + 0.30 * min(1.0, len(hist) / max(1.0, float(HISTORICAL_MATCHES)))
        + 0.20 * min(1.0, opp_inf.get("samples", 0) / float(max(1, LAST_N_GAMES)))
        + 0.15 * min(1.0, team_entry.get("lineup_stability", 0.0))
    )
    if not lineup_present:
        conf -= 0.15
    if team_entry.get("rotation_count", 0) >= ROTATION_THRESHOLD:
        conf -= 0.10

    var = (hist_std ** 2) if hist_std > 0 else 1.5
    return round(expected, 2), round(min(1.0, max(0.0, conf)), 2), var

# ─────────────────────────── MAIN WRAPPER ─────────────────────
def run_corner_engine_stage2(target_date=None):
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        log_error("CRITICAL: SPORTMONKS_API_KEY missing!")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    input_file       = os.path.join(OUTPUT_DIR, "corner3_qualified.json")
    qualified_matches = {}
    stage1_predictions = {}

    try:
        if os.path.exists(input_file):
            with open(input_file, "r", encoding="utf-8") as f:
                for item in json.load(f):
                    hid = safe_int(item.get("home_team", {}).get("team_id"))
                    aid = safe_int(item.get("away_team", {}).get("team_id"))
                    if hid and aid:
                        qualified_matches[(hid, aid)] = True
                        stage1_predictions[(hid, aid)] = float(
                            item.get("expected_total_corners", 0.0) or 0.0
                        )
        log_info(f"Loaded {len(qualified_matches)} qualified matches from Stage 1.")
    except Exception as e:
        log_warn(f"Failed to load {input_file}: {e}")

    log_info(f"Fetching fixtures for {target_date}...")
    fixtures = fetch_fixtures_for_date(target_date)
    if not fixtures:
        log_warn("No fixtures found for this date.")
        return

    log_info(f"{len(fixtures)} fixtures found. Filtering against Stage 1 list...")

    league_corner_density = {}
    league_ids = {fx.get("league_id") for fx in fixtures if fx.get("league_id") is not None}
    for lid in league_ids:
        try:
            league_corner_density[lid] = compute_league_corner_density(lid, target_date)
        except Exception:
            league_corner_density[lid] = 0.0

    output     = []
    team_cache = {}
    total      = len(fixtures)

    for idx, fx in enumerate(fixtures, start=1):
        try:
            fixture_id   = fx.get("id")
            participants = fx.get("participants", []) or []
            if len(participants) < 2:
                continue

            home_p = next((p for p in participants if (p.get("meta") or {}).get("location") == "home"), participants[0])
            away_p = next((p for p in participants if (p.get("meta") or {}).get("location") == "away"),
                          participants[1] if len(participants) > 1 else participants[0])

            home_id   = safe_int(home_p.get("id"))
            away_id   = safe_int(away_p.get("id"))
            home_name = home_p.get("name") or f"Team {home_id}"
            away_name = away_p.get("name") or f"Team {away_id}"
            league_id = fx.get("league_id")

            if qualified_matches and (home_id, away_id) not in qualified_matches:
                continue

            corner_density = league_corner_density.get(league_id, 0.0)
            log_info(f"[{idx}/{total}] {home_name} vs {away_name}")

            get_last_finished_fixtures_cached(home_id, target_date, team_cache, limit=50)
            get_last_finished_fixtures_cached(away_id, target_date, team_cache, limit=50)

            def analyze_team(team_id, team_name):
                target_venue = "home" if team_id == home_id else "away"
                all_hist     = team_cache.get(team_id, [])

                home_hist, away_hist = [], []
                for hh in all_hist:
                    for p in hh.get("participants", []) or []:
                        if safe_int(p.get("id")) == safe_int(team_id):
                            loc = (p.get("meta") or {}).get("location")
                            if loc == "home":
                                home_hist.append(hh)
                            elif loc == "away":
                                away_hist.append(hh)
                            break

                venue_hist = home_hist if target_venue == "home" else away_hist

                if len(venue_hist) < 4:
                    log_debug(f"  {team_name}: only {len(venue_hist)} {target_venue} games — using all history")
                    venue_hist = all_hist

                last_hist  = venue_hist[:HISTORICAL_MATCHES]
                recent     = venue_hist[:LAST_N_GAMES]

                overall_hist     = all_hist[:HISTORICAL_MATCHES]
                overall_corners  = [
                    c for c in (extract_corners_from_fixture(hh, team_id) for hh in overall_hist)
                    if c is not None
                ]
                overall_lastN    = overall_corners[:LAST_N_GAMES]
                overall_over4    = sum(1 for c in overall_lastN if c > 4)
                is_overall_pers  = overall_over4 >= 4 and len(overall_lastN) >= 4

                venue_corners    = [
                    c for c in (extract_corners_from_fixture(hh, team_id) for hh in last_hist)
                    if c is not None
                ]
                venue_lastN      = venue_corners[:LAST_N_GAMES]
                venue_over4      = sum(1 for c in venue_lastN if c > 4)
                is_venue_pers    = venue_over4 >= 4 and len(venue_lastN) >= 4

                recent_corner_vals = [extract_corners_from_fixture(r, team_id) for r in recent]

                today_starters = extract_starters_from_fixture(fx, team_id)
                today_ids      = [safe_int(p.get("player_id")) for p in today_starters if p.get("player_id")]

                recent_lineups = [extract_starters_from_fixture(r, team_id) for r in recent]
                valid_lineups  = [l for l in recent_lineups if isinstance(l, list) and len(l) >= 8]

                key_players     = {}
                missing_keys    = 0
                rotation_count  = 0
                lineup_stability = 0.0

                if valid_lineups:
                    counts, names = Counter(), {}
                    for lp in valid_lineups:
                        for p in lp:
                            pid = p.get("player_id")
                            if pid:
                                counts[pid] += 1
                                names[pid]   = p.get("player_name") or names.get(pid)
                    thresh      = math.ceil(len(valid_lineups) * 0.6)
                    key_players = {
                        pid: {"player_id": pid, "player_name": names.get(pid, "Unknown"), "starts": cnt}
                        for pid, cnt in counts.items()
                        if cnt >= thresh
                    }
                    today_set      = set(today_ids)
                    key_set        = set(key_players.keys())
                    missing_keys   = sum(1 for pid in key_set if pid not in today_set)
                    unique_recent  = {p.get("player_id") for lp in valid_lineups for p in lp if p.get("player_id")}
                    rotation_count = min(sum(1 for pid in unique_recent if pid not in today_set), 11)
                    if key_set:
                        lineup_stability = round(len(key_set & today_set) / len(key_set), 2)

                current_formation = extract_formation_from_fixture(fx, team_id) or "Unknown"
                parsed            = parse_formation(current_formation) if current_formation != "Unknown" else None
                form_off_score    = formation_offense_score_from_parsed(parsed)

                avg_stats   = compute_team_averages(venue_hist, team_id, limit=LAST_N_GAMES)
                inplay_style = assign_inplay_style_from_stats(avg_stats)
                tactical_style = assign_tactical_style_from_formation(current_formation)

                tempo_raw = (
                    (min(avg_stats.get("Attacks", 0.0), 120) / 120.0) * 2.0
                    + (min(avg_stats.get("Dangerous Attacks", 0.0), 50) / 50.0) * 1.2
                    + (min(avg_stats.get("Shots On Target", 0.0), 10) / 10.0) * 1.0
                    + (min(avg_stats.get("Total Crosses", 0.0), 25) / 25.0) * 0.8
                )
                predicted_tempo = (
                    "High"     if tempo_raw >= 3.7
                    else "Moderate" if tempo_raw >= 2.0
                    else "Low"
                )

                opp_influence = compute_opponent_influence_venue_aware(
                    team_id, team_cache, target_venue, sample_limit=LAST_N_GAMES
                )

                return {
                    "team_id":              team_id,
                    "team_name":            team_name,

                    "historical_corners":   venue_corners,
                    "historical_corners_avg": round(_safe_mean(venue_corners), 2) if venue_corners else 0.0,
                    "recent_corners_avg":   round(_safe_mean(recent_corner_vals), 2) if recent_corner_vals else 0.0,
                    "lastN_corners_list":   venue_lastN,
                    "overall_lastN_corners_list": overall_lastN,

                    "over_4_count_venue":   venue_over4,
                    "is_persistent_venue":  is_venue_pers,
                    "over_4_count_overall": overall_over4,
                    "is_persistent_overall": is_overall_pers,

                    "today_starters_count": len(today_starters),
                    "missing_key_players":  missing_keys,
                    "rotation_count":       rotation_count,
                    "lineup_stability":     lineup_stability,

                    "current_formation":    current_formation,
                    "parsed_formation":     parsed,
                    "formation_offense_score": form_off_score,
                    "inplay_style":         inplay_style,
                    "tactical_style":       tactical_style,
                    "predicted_tempo":      predicted_tempo,

                    "avg_stats":            avg_stats,
                    "opponent_influence":   opp_influence,
                }

            home_team = analyze_team(home_id, home_name)
            away_team = analyze_team(away_id, away_name)

            home_team["opponent_influence"] = compute_opponent_influence_venue_aware(
                home_id, team_cache, "home", sample_limit=LAST_N_GAMES)
            away_team["opponent_influence"] = compute_opponent_influence_venue_aware(
                away_id, team_cache, "away", sample_limit=LAST_N_GAMES)

            e_home, conf_home, var_home = predict_team_expected_corners_stage2(home_team, away_team, corner_density)
            e_away, conf_away, var_away = predict_team_expected_corners_stage2(away_team, home_team, corner_density)
            stage2_total = round(max(0.0, min(e_home + e_away, 18.0)), 2)

            stage1_total = stage1_predictions.get((home_id, away_id), stage2_total)
            blended_total = round(
                STAGE1_WEIGHT * stage1_total + STAGE2_WEIGHT * stage2_total, 2
            )
            blended_total = max(0.0, min(blended_total, 18.0))

            diff = round(e_home - e_away, 2)

            if blended_total >= THRESH_HIGH:     corner_tier = "High"
            elif blended_total >= THRESH_STRONG: corner_tier = "Strong"
            elif blended_total >= THRESH_MODERATE: corner_tier = "Moderate"
            else:                                corner_tier = "Low"

            log_info(
                f"  Result: Stage1={stage1_total:.1f} | Stage2={stage2_total:.1f} "
                f"| Blended={blended_total:.1f} [{corner_tier}]"
            )

            output.append({
                "fixture_id":    fixture_id,
                "fixture":       f"{home_name} vs {away_name}",
                "home_team":     home_team,
                "away_team":     away_team,

                "stage1_predicted_corners":  stage1_total,
                "stage2_predicted_corners":  stage2_total,
                "expected_total_corners":    blended_total,
                "corner_tier":               corner_tier,

                "style_alignment": determine_style_alignment(
                    home_team.get("inplay_style", []),
                    away_team.get("inplay_style", [])
                ),
                "expected_difference":  diff,
                "avg_confidence":       round((conf_home + conf_away) / 2, 2),
            })

        except Exception as e:
            log_warn(f"Error processing fixture {fx.get('id')}: {e}")
            continue

    if not output:
        log_warn("No output produced. Check Stage 1 qualified list and API connectivity.")
        return

    # ── Save output for Catalyst (Stage 3) ──────────────────────
    aggregator_data = []
    for item in output:
        aggregator_data.append({
            "fixture_id":      item["fixture_id"],
            "fixture_name":    item["fixture"],

            "stage1_predicted_corners": item["stage1_predicted_corners"],
            "stage2_predicted_corners": item["stage2_predicted_corners"],
            "predicted_corners":        item["expected_total_corners"],
            "corner_tier":              item["corner_tier"],

            "prob":            0.5,
            "diff":            item["expected_difference"],
            "style_alignment": item["style_alignment"],
            "avg_confidence":  item["avg_confidence"],

            "home_is_persistent_venue":   item["home_team"].get("is_persistent_venue",   False),
            "away_is_persistent_venue":   item["away_team"].get("is_persistent_venue",   False),
            "home_is_persistent_overall": item["home_team"].get("is_persistent_overall", False),
            "away_is_persistent_overall": item["away_team"].get("is_persistent_overall", False),
            "home_count_venue":    item["home_team"].get("over_4_count_venue",   0),
            "away_count_venue":    item["away_team"].get("over_4_count_venue",   0),
            "home_count_overall":  item["home_team"].get("over_4_count_overall", 0),
            "away_count_overall":  item["away_team"].get("over_4_count_overall", 0),

            "home_team_id": safe_int(item["home_team"].get("team_id")),
            "away_team_id": safe_int(item["away_team"].get("team_id")),
        })

    output_path = os.path.join(OUTPUT_DIR, "backend_2_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(aggregator_data, f, ensure_ascii=False, indent=2)
    log_info(f"[SUCCESS] Saved {len(aggregator_data)} matches → {output_path}")

    # ── Console Tables ───────────────────────────────────────────
    ranked = sorted(output, key=lambda x: x["expected_total_corners"], reverse=True)

    print("\n" + "=" * 100)
    print("📊 TABLE 1: RANKED BY BLENDED EXPECTED CORNERS")
    print("=" * 100)
    print(f"{'Rk':>3}  {'Fixture':55}  {'S1':>5}  {'S2':>5}  {'Blend':>6}  {'Tier':>7}  {'Align':>9}  {'Diff':>5}")
    for i, fx in enumerate(ranked, start=1):
        print(
            f"{i:>3}  {fx['fixture'][:55]:55}  "
            f"{fx['stage1_predicted_corners']:5.1f}  "
            f"{fx['stage2_predicted_corners']:5.1f}  "
            f"{fx['expected_total_corners']:6.2f}  "
            f"{fx['corner_tier']:>7}  "
            f"{fx['style_alignment']:>9}  "
            f"{fx['expected_difference']:5.2f}"
        )

    pers_venue = sorted(
        [fx for fx in output if fx["home_team"].get("is_persistent_venue") or fx["away_team"].get("is_persistent_venue")],
        key=lambda x: (
            int(x["home_team"].get("is_persistent_venue", False)) + int(x["away_team"].get("is_persistent_venue", False)),
            x["expected_total_corners"]
        ),
        reverse=True
    )

    print("\n" + "=" * 100)
    print("🏟️ TABLE 2: VENUE-AWARE PERSISTENT CORNER KINGS")
    print("=" * 100)
    if not pers_venue:
        print("  [!] No venue-persistent matches today.")
    else:
        for i, fx in enumerate(pers_venue, start=1):
            both = fx["home_team"].get("is_persistent_venue") and fx["away_team"].get("is_persistent_venue")
            print(f"{i:>3}  {fx['fixture']:55}  {'⭐⭐ BOTH' if both else '⭐ ONE':>9}  "
                  f"Blend={fx['expected_total_corners']:.2f}  "
                  f"H:{fx['home_team'].get('over_4_count_venue',0)}/5  "
                  f"A:{fx['away_team'].get('over_4_count_venue',0)}/5")

if __name__ == "__main__":
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_corner_engine_stage2(today)