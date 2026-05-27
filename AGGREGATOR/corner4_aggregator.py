import os
import sys
import time
import json
import logging
import requests
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (VS ARCHITECTURE STANDARD) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# --- 3. CONFIGURATION & SETUP ---
API_KEY = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [SUPREME V8.2] - %(message)s')


# ==============================================================================
#  UTILITY FUNCTIONS
# ==============================================================================

def clean_n(name):
    """
    Normalise a team name to a bare alphanumeric string for fuzzy matching.
    Strips common suffixes/prefixes that differ between data sources.
    """
    n = str(name).lower()
    noise = [
        "u19", "u21", "u23", "fc", "sc", "united", "city", "club",
        "afc", "rc", "as", "deportivo", "atletico", "athletic",
        "sporting", "real", "cf", "cd", "sd", "ud", "rcd",
        "the", "de", "la", "el", "los"
    ]
    for word in noise:
        n = re.sub(r'\b' + re.escape(word) + r'\b', '', n)
    return re.sub(r'[^a-z0-9]', '', n).strip()


def get_match_key(name):
    """
    Build a canonical, order-independent key for a fixture string.
    Works whether the input is "Team A vs Team B" or just a team name.
    """
    n = str(name).lower()
    if 'vs' in n:
        parts = n.split('vs')
    elif ' - ' in n:
        parts = n.split(' - ')
    else:
        parts = [n]
    parts = [clean_n(p) for p in parts]
    parts = [p for p in parts if p]   
    parts.sort()
    return "".join(parts)


# ==============================================================================
#  MULTI-ALIAS CATALOGUE BUILDER (WITH PROPER ID MAPPING)
# ==============================================================================

def build_cat_db_with_aliases(df, prob_col, fix_col):
    """
    Index every row in the underdog CSV by multiple key variants.
    """
    cat_db = {}
    for _, row in df.iterrows():
        try:
            raw_fixture = str(row[fix_col]).strip()
            prob_val = float(str(row[prob_col]).replace('%', '').strip())
        except (ValueError, KeyError):
            continue

        # Variant 1: raw fixture string lowercased
        cat_db[raw_fixture.lower()] = prob_val

        # Variant 2: canonical hash
        cat_db[get_match_key(raw_fixture)] = prob_val

        # Variant 3: canonical hash of each team name independently
        if 'vs' in raw_fixture.lower():
            parts = re.split(r'\s+vs\s+', raw_fixture, flags=re.IGNORECASE)
            if len(parts) == 2:
                home_key = clean_n(parts[0])
                away_key = clean_n(parts[1])
                cat_db[home_key + away_key] = prob_val
                cat_db[away_key + home_key] = prob_val

        # Variant 4: Explicit Fixture ID Mapping (Bulletproof)
        if 'fixture_id' in row.index:
            try:
                cat_db[str(row['fixture_id']).strip()] = prob_val
            except Exception:
                pass

    return cat_db


# ==============================================================================
#  SAFE UD PROB LOOKUP WITH EXACT ID CHECKING
# ==============================================================================

def lookup_ud_prob(fixture_name, fixture_id, cat_db):
    """
    Try every key variant, prioritizing the exact Fixture ID first!
    """
    candidates = []

    if fixture_id:
        candidates.append(str(fixture_id).strip())

    candidates.append(fixture_name.lower().strip())
    candidates.append(get_match_key(fixture_name))

    if 'vs' in fixture_name.lower():
        parts = re.split(r'\s+vs\s+', fixture_name, flags=re.IGNORECASE)
        if len(parts) == 2:
            h = clean_n(parts[0])
            a = clean_n(parts[1])
            candidates.append(h + a)
            candidates.append(a + h)

    for c in candidates:
        if c in cat_db:
            return float(cat_db[c]), True

    # Diagnostic
    sample_keys = list(cat_db.keys())[:6]
    print(
        f"  [WARN] UD lookup FAILED for '{fixture_name}' (ID: {fixture_id})\n"
        f"         Tried keys: {candidates}\n"
        f"         cat_db sample: {sample_keys}"
    )
    return 0.0, False


# ==============================================================================
#  SCORE & STAT HELPERS
# ==============================================================================

def extract_final_score(scores_list):
    home, away = 0, 0
    found = False
    for entry in (scores_list or []):
        if not isinstance(entry, dict):
            continue
        s_obj = entry.get("score") or entry
        desc = str(s_obj.get("description", "")).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
            continue
        p = s_obj.get("participant") or entry.get("participant")
        g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
        if g is not None:
            try:
                val = int(g)
                if p == "home":
                    home = max(home, val)
                    found = True
                elif p == "away":
                    away = max(away, val)
                    found = True
            except Exception:
                pass
    if not found:
        return None, None
    return home, away


def calculate_u25_poisson(h_scored, h_conc, a_scored, a_conc, sims=5000):
    h_xg = max(0.1, (h_scored + a_conc) / 2.0)
    a_xg = max(0.1, (a_scored + h_conc) / 2.0)
    h_sim = np.random.poisson(h_xg, sims)
    a_sim = np.random.poisson(a_xg, sims)
    total_goals = h_sim + a_sim
    u25_prob = np.mean(total_goals < 3) * 100
    return round(u25_prob, 1)


def run_negative_binomial_siege(expected_corners, wide_pressure_score, is_chasing_game):
    if is_chasing_game:
        expected_corners *= 1.15
    expected_corners += (wide_pressure_score * 0.5)
    if expected_corners < 1.0:
        expected_corners = 1.0
    variance = expected_corners * 1.6
    if variance <= expected_corners:
        variance = expected_corners + 0.1
    p = expected_corners / variance
    r = (expected_corners ** 2) / (variance - expected_corners)
    if p <= 0 or p >= 1 or r <= 0:
        return 0.0, expected_corners
    try:
        simulated_totals = np.random.negative_binomial(n=r, p=p, size=5000)
        m_prob = (np.sum(simulated_totals >= 10) / 5000) * 100
        return round(m_prob, 2), round(expected_corners, 2)
    except Exception:
        return 0.0, expected_corners


def GET(path, params=None):
    if params is None:
        params = {}
    params.setdefault("api_token", API_KEY)
    max_attempts = 5
    backoff = 2.0
    for attempt in range(max_attempts):
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                wait = backoff * (attempt + 1)
                print(f"  [WARN] 429 rate limit — attempt {attempt+1}/{max_attempts}. Sleeping {wait:.1f}s")
                time.sleep(wait)
            else:
                print(f"  [WARN] HTTP {r.status_code} — attempt {attempt+1}/{max_attempts} for {path}")
                time.sleep(backoff)
        except Exception as e:
            print(f"  [WARN] Request exception — attempt {attempt+1}/{max_attempts}: {e}")
            time.sleep(backoff)
    print(f"  [ERROR] All {max_attempts} attempts failed for {path}. Returning empty data.")
    return {"data": []}

def extract_stat_entries(fx, team_id):
    stats_raw = fx.get("statistics", [])
    result = {}
    if not stats_raw:
        return result
    entries = (
        stats_raw.get(str(team_id), [])
        if isinstance(stats_raw, dict)
        else [s for s in stats_raw if int(s.get("participant_id", 0)) == int(team_id)]
    )
    for s in entries:
        t_obj = s.get("type", {})
        name = t_obj.get("name") if isinstance(t_obj, dict) else s.get("name")
        val = (
            s.get("data", {}).get("value")
            if isinstance(s.get("data"), dict)
            else s.get("value")
        )
        if name and val is not None:
            try:
                result[str(name)] = float(val)
            except Exception:
                pass
    return result

def extract_sh_corners(fx, team_id):
    sh_corners = 0
    found_sh_data = False
    stats_raw = fx.get("statistics", [])
    entries = (
        stats_raw.get(str(team_id), [])
        if isinstance(stats_raw, dict)
        else [s for s in stats_raw if int(s.get("participant_id", 0)) == int(team_id)]
    )
    for s in entries:
        t_obj = s.get("type", {})
        name = str(t_obj.get("name", s.get("name", "")))
        if "Corner" in name or "corner" in name.lower():
            period_id = str(s.get("period_id", ""))
            if period_id == "2" or "2nd Half" in str(s):
                val = (
                    s.get("data", {}).get("value")
                    if isinstance(s.get("data"), dict)
                    else s.get("value")
                )
                try:
                    sh_corners += float(val)
                    found_sh_data = True
                except Exception:
                    pass
    return sh_corners, found_sh_data

def assign_inplay_style(stat_map):
    atk = stat_map.get("Attacks", 0.0)
    dang = stat_map.get("Dangerous Attacks", 0.0)
    cross = stat_map.get("Total Crosses", 0.0)
    acc = stat_map.get("Accurate Crosses", 0.0)
    labels = []
    if atk >= 75 and dang >= 45:
        labels.append("Attacking")
    if cross >= 16 and acc >= 4:
        labels.append("Crossing/Counter")
    return labels if labels else ["Balanced"]

def compute_opponent_influence(team_id, history):
    resp = {"by_style": {}, "samples": 0}
    for fx in history[:20]:
        parts = fx.get("participants", [])
        opp_id = next(
            (int(p["id"]) for p in parts if int(p["id"]) != int(team_id)), None
        )
        if not opp_id:
            continue
        opp_style = assign_inplay_style(extract_stat_entries(fx, opp_id))[0]
        team_corners = extract_stat_entries(fx, team_id).get("Corners", 0)
        s = resp["by_style"].setdefault(opp_style, {"sum": 0.0, "count": 0})
        s["sum"] += team_corners
        s["count"] += 1
        resp["samples"] += 1
    for k, v in resp["by_style"].items():
        resp["by_style"][k] = round(v["sum"] / v["count"], 2) if v["count"] > 0 else 0.0
    return resp

def fetch_team_forensics(team_id, target_date):
    end_dt = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    start_dt = (
        datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=90)
    ).strftime("%Y-%m-%d")
    resp = GET(
        f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
        params={
            "include": "statistics.type;participants;scores;periods",
            "per_page": 10,
            "filter": "fixtureStates:5",
        },
    )
    history = resp.get("data", [])
    if not history:
        return {
            "wide_score": 0.0,
            "wide_label": "Standard",
            "avg_da": 0,
            "opp_inf": {"by_style": {}},
            "style": "Balanced",
            "recency": 0.0,
            "avg_scored": 1.0,
            "avg_conc": 1.0,
            "sh_corner_ratio": 50.0,
        }

    total_crosses, total_da, total_corners = [], [], []
    sh_corners_list = []
    scored_list, conc_list = [], []

    for fx in history:
        stats = extract_stat_entries(fx, team_id)
        total_crosses.append(stats.get("Total Crosses", 0))
        total_da.append(stats.get("Dangerous Attacks", 0))
        tc = stats.get("Corners", 0)
        total_corners.append(tc)

        sh_c, found_sh = extract_sh_corners(fx, team_id)
        if found_sh:
            sh_corners_list.append(sh_c)
        else:
            sh_corners_list.append(tc * 0.55)

        h_g, a_g = extract_final_score(fx.get("scores", []))
        if h_g is not None and a_g is not None:
            is_home = True
            for p in fx.get("participants", []):
                if str(p.get("id")) == str(team_id):
                    is_home = p.get("meta", {}).get("location") == "home"
                    break
            if is_home:
                scored_list.append(h_g)
                conc_list.append(a_g)
            else:
                scored_list.append(a_g)
                conc_list.append(h_g)

    avg_cross = sum(total_crosses) / len(total_crosses) if total_crosses else 0
    avg_da = sum(total_da) / len(total_da) if total_da else 0
    avg_tc = sum(total_corners) / len(total_corners) if total_corners else 0
    avg_sh = sum(sh_corners_list) / len(sh_corners_list) if sh_corners_list else 0
    sh_corner_ratio = (avg_sh / avg_tc * 100) if avg_tc > 0 else 50.0
    avg_scored = sum(scored_list) / len(scored_list) if scored_list else 1.0
    avg_conc = sum(conc_list) / len(conc_list) if conc_list else 1.0

    wide_score = 2.0 if avg_cross >= 18.0 else 1.0 if avg_cross >= 14.0 else 0.0
    if avg_da > 0 and (avg_cross / avg_da) > 0.45:
        wide_score += 1.5

    return {
        "wide_score": wide_score,
        "wide_label": (
            "WING STORM 🌪️" if wide_score >= 2.0
            else "Wide Bias" if wide_score >= 1.0
            else "Standard"
        ),
        "avg_da": avg_da,
        "opp_inf": compute_opponent_influence(team_id, history),
        "style": assign_inplay_style(
            {"Dangerous Attacks": avg_da, "Total Crosses": avg_cross}
        )[0],
        "recency": avg_tc,
        "sh_corner_ratio": round(sh_corner_ratio, 1),
        "avg_scored": avg_scored,
        "avg_conc": avg_conc,
    }


# ==============================================================================
# 🧠 SUPREME HANDSHAKE AGGREGATOR V8.2
# ==============================================================================

class CornerAggregator:
    def __init__(self, stage3_file, dna_file, catalyst_file, output_csv, target_date):
        self.input_file = stage3_file
        self.dna_file = dna_file
        self.catalyst_file = catalyst_file
        self.output_csv = output_csv
        self.target_date = target_date

    # --------------------------------------------------------------------------
    def load_data(self):
        """
        Load Stage 3 JSON, DNA profiles, and the underdog CSV.
        Strictly targets the OUTPUT_DIR for VS Code architecture.
        """
        raw_data, cat_db, dna_db = [], {}, {}

        # --- Stage 3 JSON ---
        if os.path.exists(self.input_file):
            with open(self.input_file, "r", encoding='utf-8') as f:
                raw_data = json.load(f)
                if isinstance(raw_data, dict):
                    raw_data = raw_data.get("data", raw_data.get("matches", [raw_data]))
        else:
            print(f"  [WARNING] {self.input_file} not found. Ensure Stage 3 ran correctly.")

        # --- DNA Profiles ---
        if os.path.exists(self.dna_file):
            try:
                with open(self.dna_file, "r") as f:
                    dna_db = json.load(f)
            except Exception:
                pass

        # --- Underdog CSV (STRICT VS CODE SEARCH) ---
        catalyst_path = self.catalyst_file

        if os.path.exists(catalyst_path):
            try:
                df = pd.read_csv(catalyst_path,
                encoding='utf-8')

                # Resolve column names flexibly
                prob_col = next(
                    (c for c in df.columns if "prob" in c.lower()),
                    "dog_score_prob"
                )
                fix_col = next(
                    (c for c in df.columns if "fixture" in c.lower() or "match" in c.lower()),
                    "fixture"
                )

                print(f"  [INFO] Underdog CSV loaded from OUTPUT_DIR: {len(df)} rows")
                
                # Multi-alias indexing WITH FIXTURE ID
                cat_db = build_cat_db_with_aliases(df, prob_col, fix_col)
                print(f"  [INFO] cat_db built with {len(cat_db)} key aliases")

            except Exception as e:
                print(f"  [ERROR] Failed to parse catalyst file: {e}")
        else:
            print(
                f"  [WARNING] Catalyst file not found: {catalyst_path}\n"
                f"            UD Probabilities will be 0.0 — VIP/Special List will be empty.\n"
                f"            Ensure the Underdog Engine ran before Stage 4."
            )

        return raw_data, dna_db, cat_db

    # --------------------------------------------------------------------------
    def calculate_syndicate_score(
        self, intel, dna_label, match_flow, ud_prob, u25_prob,
        is_pers_v, is_pers_o, is_home,
        is_wounded, wound_intensity,
        monte_prob, table_friction
    ):
        """
        100-Point Syndicate Trust Index Engine.
        """
        score = 0

        # 1. TACTICS & DNA (Max 35)
        if intel["wide_label"] == "Wide Bias":
            score += 20
        elif intel["wide_label"] == "WING STORM 🌪️":
            score -= 15

        if dna_label == "SUPREME_SIEGE":
            score += 15

        # 2. GAME STATE & DESPERATION (Max 35)
        if u25_prob >= 60.0 and ud_prob >= 65.0:
            score += 20   # VIP Lock
        elif u25_prob > 44.0 and ud_prob >= 60.0:
            score += 10   # Special List

        if is_wounded:
            if wound_intensity == "CRITICAL":
                score += 20
            elif wound_intensity == "ACTIVE":
                score += 15
            else:
                score += 8   # MINOR
            if is_home:
                score += 5

        # Only reached when ud_data_available=True
        if match_flow == "🚨 BLOWOUT TRAP":
            score -= 15

        # 3. TABLE INTELLIGENCE
        if "💎 PERFECT" in table_friction:
            score += 5
        elif "DEAD" in table_friction or "AVOID" in table_friction:
            score -= 15

        # 4. CONSISTENCY & ENVIRONMENT (Max 30)
        if is_pers_v:
            score += 15
        elif is_pers_o:
            score += 5

        if is_home:
            score += 10

        if monte_prob >= 85.0:
            score += 5

        return max(0, min(100, int(score)))

    # --------------------------------------------------------------------------
    def run(self):
        print(
            f"\n>> [Supreme Aggregator V8.2] Initialising 100-Point Syndicate & "
            f"Table Friction Engine... (Target Date: {self.target_date})"
        )
        raw_data, dna_db, cat_db = self.load_data()

        if not raw_data:
            print("  [FATAL ERROR] Stage 3 JSON is missing or empty. Aborting.")
            return

        # ──────────────────────────────────────────────────────────────────────
        # DIAGNOSTIC BLOCK
        # ──────────────────────────────────────────────────────────────────────
        print("\n" + "─" * 80)
        print("  🔍 DIAGNOSTIC: KEY ALIGNMENT CHECK")
        print("─" * 80)
        print(f"  Stage 3 matches loaded : {len(raw_data)}")
        print(f"  cat_db aliases loaded  : {len(cat_db)}")

        processed_list = []
        ud_miss_count = 0
        ud_hit_count = 0

        for match in raw_data:
            try:
                fix_name = str(match.get("fixture_name", "Unknown vs Unknown"))
                home_name = fix_name.split(" vs ")[0] if " vs " in fix_name else "Home"
                away_name = fix_name.split(" vs ")[1] if " vs " in fix_name else "Away"
                home_id = match.get("home_id", 0)
                away_id = match.get("away_id", 0)
                fid_str = str(match.get("fixture_id", ""))

                # --- TABLE POSITIONS & FRICTION ---
                h_pos = match.get("home_position", 99)
                a_pos = match.get("away_position", 99)
                table_friction = str(match.get("friction_grade", "Unknown"))

                # --- PERSISTENCE FLAGS ---
                h_pers_v = match.get("home_is_persistent_venue", False)
                a_pers_v = match.get("away_is_persistent_venue", False)
                h_pers_o = match.get("home_is_persistent_overall", False)
                a_pers_o = match.get("away_is_persistent_overall", False)

                h_king = "👑" if h_pers_v else ("⭐" if h_pers_o else "❌")
                a_king = "👑" if a_pers_v else ("⭐" if a_pers_o else "❌")

                # --- WOUND DATA (BOTH TEAMS) ---
                home_is_wounded   = match.get("home_is_wounded_beast", False)
                home_wound_int    = match.get("home_wounded_intensity", "NONE")
                home_wound_reason = match.get("home_wounded_reason", "None")

                away_is_wounded   = match.get("away_is_wounded_beast", False)
                away_wound_int    = match.get("away_wounded_intensity", "NONE")
                away_wound_reason = match.get("away_wounded_reason", "None")

                # Legacy fields for backward compatibility
                either_wounded  = match.get("is_wounded_beast", (home_is_wounded or away_is_wounded))
                wounded_team    = match.get("wounded_team_name", "None")
                wounded_reason  = match.get("wounded_reason", "None")

                # --- CORNER EXPECTATIONS ---
                total_corners = float(match.get("predicted_corners", 9.0) or 9.0)
                diff = float(match.get("diff", 0.0) or 0.0)
                home_exp = max(0.0, (total_corners + diff) / 2.0)
                away_exp = max(0.0, (total_corners - diff) / 2.0)

                # --- FORENSIC FETCH ---
                h_intel = fetch_team_forensics(home_id, self.target_date)
                a_intel = fetch_team_forensics(away_id, self.target_date)

                # --- U2.5 POISSON ---
                u25_prob = calculate_u25_poisson(
                    h_intel["avg_scored"], h_intel["avg_conc"],
                    a_intel["avg_scored"], a_intel["avg_conc"],
                )

                # ──────────────────────────────────────────────────────────────
                # SAFE UD PROB LOOKUP
                # ──────────────────────────────────────────────────────────────
                ud_prob, ud_data_available = lookup_ud_prob(fix_name, fid_str, cat_db)

                if ud_data_available:
                    ud_hit_count += 1
                else:
                    ud_miss_count += 1

                is_chasing = ud_data_available and (ud_prob > 50.0)

                match_flow = "Standard Flow"
                if ud_data_available:
                    if u25_prob >= 55.0 and ud_prob >= 50.0:
                        match_flow = "⏳ TENSION COOKER"
                    elif u25_prob <= 45.0 and ud_prob <= 30.0:
                        match_flow = "🚨 BLOWOUT TRAP"
                else:
                    if u25_prob >= 55.0:
                        match_flow = "⏳ LOW-SCORING SIEGE"

                # --- DNA LABELS ---
                h_dna_raw = dna_db.get(str(home_id), {})
                a_dna_raw = dna_db.get(str(away_id), {})
                h_dna_label = "SUPREME_SIEGE" if h_dna_raw.get("Market_Power_Scores", {}).get("Corner_Power", 0) > 80 else "Standard"
                a_dna_label = "SUPREME_SIEGE" if a_dna_raw.get("Market_Power_Scores", {}).get("Corner_Power", 0) > 80 else "Standard"

                # --- NEGATIVE BINOMIAL MONTE CARLO ---
                h_monte_prob, _ = run_negative_binomial_siege(
                    total_corners, h_intel["wide_score"], is_chasing
                )
                a_monte_prob, _ = run_negative_binomial_siege(
                    total_corners, a_intel["wide_score"], is_chasing
                )

                # --- 100-POINT SYNDICATE SCORES (BOTH TEAMS) ---
                h_score = self.calculate_syndicate_score(
                    h_intel, h_dna_label, match_flow, ud_prob, u25_prob,
                    h_pers_v, h_pers_o,
                    is_home=True,
                    is_wounded=home_is_wounded,
                    wound_intensity=home_wound_int,
                    monte_prob=h_monte_prob,
                    table_friction=table_friction,
                )
                a_score = self.calculate_syndicate_score(
                    a_intel, a_dna_label, match_flow, ud_prob, u25_prob,
                    a_pers_v, a_pers_o,
                    is_home=False,
                    is_wounded=away_is_wounded,
                    wound_intensity=away_wound_int,
                    monte_prob=a_monte_prob,
                    table_friction=table_friction,
                )

                # --- TRUE FAVOURITE RESOLUTION ---
                if h_score > a_score:
                    true_fav = home_name
                    monte_prob = h_monte_prob
                elif a_score > h_score:
                    true_fav = away_name
                    monte_prob = a_monte_prob
                else:
                    true_fav = home_name if diff >= 0 else away_name
                    monte_prob = h_monte_prob if diff >= 0 else a_monte_prob

                chaos_rating = h_score + a_score
                match_master_score = max(h_score, a_score)

                if match_master_score >= 90:
                    tier = "👑 GOD TIER"
                elif match_master_score >= 75:
                    tier = "💎 PREMIUM"
                elif match_master_score >= 60:
                    tier = "🔥 SOLID"
                else:
                    tier = "🛑 TRAP"

                processed_list.append({
                    "Fixture":         fix_name,
                    "Master_Score":    match_master_score,
                    "Chaos_Rating":    chaos_rating,
                    "Tier":            tier,
                    "True_Corner_Fav": true_fav,
                    "Match_Flow":      match_flow,
                    "U2.5%":           f"{u25_prob}%",
                    "UD_Prob":         f"{ud_prob}%" if ud_data_available else "N/A",
                    "UD_Data_Found":   ud_data_available,   
                    "NB_Prob":         f"{monte_prob}%",
                    "Total_Exp":       round(total_corners, 2),

                    "Home_Pos":        h_pos,
                    "Away_Pos":        a_pos,
                    "Friction":        table_friction,

                    "Home_Wounded":      "🩸 YES" if home_is_wounded else "❌ NO",
                    "Home_Wound_Int":    home_wound_int,
                    "Home_Wound_Reason": home_wound_reason,
                    "Away_Wounded":      "🩸 YES" if away_is_wounded else "❌ NO",
                    "Away_Wound_Int":    away_wound_int,
                    "Away_Wound_Reason": away_wound_reason,

                    "Is_Wounded":     "🩸 YES" if either_wounded else "❌ NO",
                    "Wounded_Team":   wounded_team,
                    "Wounded_Reason": wounded_reason,
                    "Is_Home_Wounded": home_is_wounded,

                    "Home_Team":    home_name,
                    "H_King":       h_king,
                    "Home_Pers_V":  h_pers_v,
                    "Home_Pers_O":  h_pers_o,
                    "Home_Score":   h_score,
                    "Home_Exp":     round(home_exp, 2),
                    "Home_Label":   h_intel["wide_label"],
                    "Home_DNA":     h_dna_label,
                    "Home_SH_Ratio": h_intel["sh_corner_ratio"],

                    "Away_Team":    away_name,
                    "A_King":       a_king,
                    "Away_Pers_V":  a_pers_v,
                    "Away_Pers_O":  a_pers_o,
                    "Away_Score":   a_score,
                    "Away_Exp":     round(away_exp, 2),
                    "Away_Label":   a_intel["wide_label"],
                    "Away_DNA":     a_dna_label,
                    "Away_SH_Ratio": a_intel["sh_corner_ratio"],
                })

                ud_status = f"UD={ud_prob}%" if ud_data_available else "UD=MISSING"
                print(
                    f"  > {fix_name[:28]:<28} | Master: {match_master_score:>3}/100 "
                    f"| {ud_status:<12} | Flow: {match_flow[:20]:<20} "
                    f"| HWound: {home_wound_int} | AWound: {away_wound_int}"
                )

            except Exception as e:
                print(f"  [Warning] Skipped match — bad data: {e}")
                continue

        # ──────────────────────────────────────────────────────────────────────
        # POST-LOOP UD COVERAGE SUMMARY
        # ──────────────────────────────────────────────────────────────────────
        total_matches = ud_hit_count + ud_miss_count
        print(f"\n  📊 UD Coverage: {ud_hit_count}/{max(1, total_matches)} matches had UD data")

        df = pd.DataFrame(processed_list)
        if df.empty:
            print("\n  [FATAL ERROR] All matches were skipped or empty.")
            return

        df["UD_Float"] = df["UD_Prob"].str.rstrip("%").replace("N/A", "0").astype(float)
        df["U2.5_Float"] = df["U2.5%"].str.rstrip("%").astype(float)

        # ──────────────────────────────────────────────────────────────────────
        # THEMED LISTS
        # ──────────────────────────────────────────────────────────────────────

        vip_df = df[
            (df["UD_Data_Found"] == True) &
            (df["U2.5_Float"] >= 60.0) &
            (df["UD_Float"] >= 65.0)
        ].copy()
        if not vip_df.empty:
            vip_df = vip_df.sort_values(by="Master_Score", ascending=False)

        special_df = df[
            (df["UD_Data_Found"] == True) &
            (
                ((df["Home_Label"] == "Wide Bias") & (df["Home_DNA"] == "SUPREME_SIEGE")) |
                ((df["Away_Label"] == "Wide Bias") & (df["Away_DNA"] == "SUPREME_SIEGE"))
            ) &
            (df["UD_Float"] >= 60.0) &
            (df["U2.5_Float"] > 44.0)
        ].sort_values(by="Master_Score", ascending=False)

        golden_df = df[
            (
                ((df["Home_Label"] == "Wide Bias") & (df["Home_DNA"] == "SUPREME_SIEGE")) |
                ((df["Away_Label"] == "Wide Bias") & (df["Away_DNA"] == "SUPREME_SIEGE"))
            ) &
            (df["Match_Flow"] == "⏳ TENSION COOKER")
        ].sort_values(by="Master_Score", ascending=False)

        sh_surge_df = df[
            (
                (df["Home_SH_Ratio"] > 58.0) |
                (df["Away_SH_Ratio"] > 58.0)
            ) &
            (
                (df["Match_Flow"] == "⏳ TENSION COOKER") |
                (df["UD_Float"] >= 65.0)
            )
        ].sort_values(by="Master_Score", ascending=False)

        wounded_df = df[df["Is_Wounded"] == "🩸 YES"].copy()
        if not wounded_df.empty:
            wounded_df = wounded_df.sort_values(
                by=["Is_Home_Wounded", "Master_Score"], ascending=[False, False]
            )

        kings_df = df[
            ((df["Home_Pers_V"] == True) & (df["Home_Label"].isin(["Wide Bias", "WING STORM 🌪️"]))) |
            ((df["Away_Pers_V"] == True) & (df["Away_Label"].isin(["Wide Bias", "WING STORM 🌪️"])))
        ].copy()
        if not kings_df.empty:
            kings_df["Is_Home_King"] = (
                (kings_df["Home_Pers_V"] == True) &
                (kings_df["Home_Label"].isin(["Wide Bias", "WING STORM 🌪️"]))
            )
            kings_df = kings_df.sort_values(
                by=["Is_Home_King", "Master_Score"], ascending=[False, False]
            )

        table2_df = df[
            (df["Home_Pers_O"] == True) | (df["Away_Pers_O"] == True)
        ].copy()
        if not table2_df.empty:
            table2_df["Pers_Score"] = (
                table2_df["Home_Pers_O"].astype(int) +
                table2_df["Away_Pers_O"].astype(int)
            )
            table2_df = table2_df.sort_values(
                by=["Home_Pers_O", "Pers_Score", "Master_Score"],
                ascending=[False, False, False],
            )

        table3_df = df[
            (df["Home_Pers_V"] == True) | (df["Away_Pers_V"] == True)
        ].copy()
        if not table3_df.empty:
            table3_df["Pers_Score"] = (
                table3_df["Home_Pers_V"].astype(int) +
                table3_df["Away_Pers_V"].astype(int)
            )
            table3_df = table3_df.sort_values(
                by=["Home_Pers_V", "Pers_Score", "Master_Score"],
                ascending=[False, False, False],
            )

        # ──────────────────────────────────────────────────────────────────────
        # PRINT OUTPUT
        # ──────────────────────────────────────────────────────────────────────

        print("\n" + "💎" * 40)
        print(" 💎 THE VIP LOCKS (Extreme Game State Sieges) 💎")
        print("💎" * 40)
        print("   Matches with U2.5 >= 60% & UD Fight >= 65%. Almost guaranteed 90-min sieges.\n")
        if not vip_df.empty:
            for i, (_, row) in enumerate(vip_df.iterrows(), 1):
                print(
                    f"{i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                print(
                    f"   * Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']} | U2.5: {row['U2.5%']} | UD: {row['UD_Prob']}"
                )
                if row["Home_Wounded"] == "🩸 YES":
                    print(f"   * 🩸 HOME WOUNDED: {row['Home_Wound_Int']} — {row['Home_Wound_Reason']}")
                if row["Away_Wounded"] == "🩸 YES":
                    print(f"   * 🩸 AWAY WOUNDED: {row['Away_Wound_Int']} — {row['Away_Wound_Reason']}")
                print()
        else:
            print("   [!] No VIP Locks met the extreme criteria today.\n")

        print("\n" + "⭐" * 60)
        print(" 🌟 THE SPECIAL LIST: WIDE BIAS + SUPREME SIEGE 🌟")
        print("⭐" * 60)
        if not special_df.empty:
            for i, (_, row) in enumerate(special_df.iterrows(), 1):
                fav_team = (
                    row["Home_Team"]
                    if row["Home_Label"] == "Wide Bias"
                    else row["Away_Team"]
                )
                print(
                    f"{i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                print(f"   * True Fav: {fav_team} (Wide Bias + SUPREME_SIEGE)")
                print(
                    f"   * Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']} | U2.5: {row['U2.5%']} | UD: {row['UD_Prob']}\n"
                )
        else:
            print("   [!] No matches met the Special List criteria today.\n")

        print("\n" + "★" * 100)
        print(" 👑 THE GOLDEN TICKET LIST (Wide Bias + Supreme Siege + Tension Cooker) 👑")
        print("★" * 100)
        if not golden_df.empty:
            for i, (_, row) in enumerate(golden_df.iterrows(), 1):
                print(
                    f"{i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                print(f"   * True Corner Fav: {row['True_Corner_Fav']} (Tier: {row['Tier']})")
                print(
                    f"   * Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']} | U2.5%: {row['U2.5%']} | UD_Prob: {row['UD_Prob']}\n"
                )
        else:
            print("   [!] No matches met the strict Golden Ticket criteria today.\n")

        print("\n" + "🕒" * 50)
        print(" 🕒 THE SECOND HALF SURGE (Live Betting Goldmine) 🕒")
        print("🕒" * 50)
        if not sh_surge_df.empty:
            for i, (_, row) in enumerate(sh_surge_df.iterrows(), 1):
                surge_team = (
                    row["Home_Team"]
                    if row["Home_SH_Ratio"] > 58.0
                    else row["Away_Team"]
                )
                surge_ratio = (
                    row["Home_SH_Ratio"]
                    if row["Home_SH_Ratio"] > 58.0
                    else row["Away_SH_Ratio"]
                )
                print(
                    f" {i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                print(
                    f"    🔥 {surge_team} wins {surge_ratio}% in 2nd Half! "
                    f"| Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']}\n"
                )
        else:
            print("   [!] No 2nd Half Surge matches found today.\n")

        print("\n" + "🩸" * 40)
        print(" 🩸 THE WOUNDED BEASTS (Revenge & Redemption) 🩸")
        print("🩸" * 40)
        if not wounded_df.empty:
            for i, (_, row) in enumerate(wounded_df.iterrows(), 1):
                print(
                    f"{i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                if row["Home_Wounded"] == "🩸 YES":
                    print(
                        f"   * 🩸 HOME: {row['Home_Team']} — "
                        f"{row['Home_Wound_Int']} ({row['Home_Wound_Reason']})"
                    )
                if row["Away_Wounded"] == "🩸 YES":
                    print(
                        f"   * 🩸 AWAY: {row['Away_Team']} — "
                        f"{row['Away_Wound_Int']} ({row['Away_Wound_Reason']})"
                    )
                print(
                    f"   * Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']} | U2.5: {row['U2.5%']} | UD: {row['UD_Prob']}\n"
                )
        else:
            print("   [!] No Wounded Beasts found today.\n")

        print("\n" + "👑" * 40)
        print(" 👑 THE PERSISTENT KINGS: TEAM OVER GOLDMINE 👑")
        print("👑" * 40)
        if not kings_df.empty:
            for i, (_, row) in enumerate(kings_df.iterrows(), 1):
                if row["Is_Home_King"]:
                    king_team, king_label, king_exp = row["Home_Team"], row["Home_Label"], row["Home_Exp"]
                else:
                    king_team, king_label, king_exp = row["Away_Team"], row["Away_Label"], row["Away_Exp"]
                print(
                    f"{i}. {row['Fixture']} (Master Score: {row['Master_Score']}/100) "
                    f"| [Exp: {row['Home_Exp']:.1f} - {row['Away_Exp']:.1f}]"
                )
                print(f"   * THE KING: 👑 {king_team} (Exp: {king_exp:.1f} | {king_label})")
                print(
                    f"   * Table: {row['Home_Pos']}v{row['Away_Pos']} ({row['Friction']}) "
                    f"| Flow: {row['Match_Flow']} | U2.5: {row['U2.5%']} | UD: {row['UD_Prob']}\n"
                )
        else:
            print("   [!] No Persistent Kings found today.\n")

        print("\n" + "=" * 120)
        print("🔄 TABLE 2: OVERALL PERSISTENT CORNER KINGS")
        print("=" * 120)
        print(
            f"{'Rk':>3}  {'Fixture':45}  {'Exp(H|A)':>12}  "
            f"{'Rating':>10}  {'Master Score':>14}  {'Table (Friction)':>20}"
        )
        if not table2_df.empty:
            for i, (_, row) in enumerate(table2_df.iterrows(), 1):
                rating = "⭐⭐ BOTH" if row["Pers_Score"] == 2 else "⭐ ONE"
                exp_str = f"{row['Home_Exp']:.1f} | {row['Away_Exp']:.1f}"
                tbl_str = f"{row['Home_Pos']}v{row['Away_Pos']} ({row['Friction'][:10]})"
                print(
                    f"{i:>3}  {row['Fixture']:45}  {exp_str:>12}  "
                    f"{rating:>10}  {row['Master_Score']:14}  {tbl_str:>20}"
                )

        print("\n" + "=" * 120)
        print("🏟️ TABLE 3: VENUE-AWARE PERSISTENT KINGS (The Stricter Filter)")
        print("=" * 120)
        print(
            f"{'Rk':>3}  {'Fixture':45}  {'Exp(H|A)':>12}  "
            f"{'Rating':>10}  {'Master Score':>14}  {'Table (Friction)':>20}"
        )
        if not table3_df.empty:
            for i, (_, row) in enumerate(table3_df.iterrows(), 1):
                rating = "⭐⭐ BOTH" if row["Pers_Score"] == 2 else "⭐ ONE"
                exp_str = f"{row['Home_Exp']:.1f} | {row['Away_Exp']:.1f}"
                tbl_str = f"{row['Home_Pos']}v{row['Away_Pos']} ({row['Friction'][:10]})"
                print(
                    f"{i:>3}  {row['Fixture']:45}  {exp_str:>12}  "
                    f"{rating:>10}  {row['Master_Score']:14}  {tbl_str:>20}"
                )

        print("\n" + "=" * 150)
        print("📊 TABLE 1: FULL TACTICAL BRAIN ANALYSIS (Sorted by Chaos Rating & Master Score)")
        print("=" * 150)

        cols = [
            "Fixture", "Tier", "Chaos_Rating", "Master_Score", "Match_Flow",
            "U2.5%", "UD_Prob", "UD_Data_Found", "Total_Exp",
            "Home_Pos", "Away_Pos", "Friction",
            "Home_Wounded", "Home_Wound_Int", "Away_Wounded", "Away_Wound_Int",
            "True_Corner_Fav",
            "Home_Team", "H_King", "Home_Score", "Home_Exp", "Home_Label", "Home_DNA",
            "Away_Team", "A_King", "Away_Score", "Away_Exp", "Away_Label", "Away_DNA",
        ]

        df_display = df[cols].sort_values(
            by=["Chaos_Rating", "Master_Score", "Total_Exp"],
            ascending=[False, False, False],
        )
        print(df_display.to_string(index=False))

        df_display.to_csv(self.output_csv, index=False)
        print(f"\n💾 [Done] Results saved to: {self.output_csv}")


# ==============================================================================
# 📦 THE ALIENEDGE BLACK BOX WRAPPER (STAGE 4)
# ==============================================================================

def run_corner4_aggregator_engine(target_date=None):
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    stage3_file   = os.path.join(OUTPUT_DIR, "tactical_brain_output.json")
    dna_file      = os.path.join(DATA_DIR,   "team_dna_profiles.json")
    output_csv    = os.path.join(OUTPUT_DIR, f"SUPREME_EVOLUTION_OUTPUT_{target_date}.csv")

    # 🛠️ SMART FINDER FOR VS CODE UNDERDOG FILE
    possible_ud_files = [
        os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, f"backtest_underdog_{target_date}.csv")
    ]
    
    catalyst_file = possible_ud_files[1] # Default
    for path in possible_ud_files:
        if os.path.exists(path):
            catalyst_file = path
            break

    agg = CornerAggregator(stage3_file, dna_file, catalyst_file, output_csv, target_date)
    agg.run()


# --- LOCAL TESTING BLOCK ---
if __name__ == "__main__":
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 2000)
    pd.set_option("display.max_columns", None)

    today_test = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_corner4_aggregator_engine(today_test)