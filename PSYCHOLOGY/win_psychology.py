import os
import sys
import time
import logging
import requests
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER
# ==============================================================================
def run_win_psychology_engine(target_date=None):
    """
    AlienEdge Win Psychology Engine — GODMODE PRECISION UPDATE

    KEY CHANGES FROM PREVIOUS VERSION
    ──────────────────────────────────────────────────────────────────────────
    1. OPPOSITION QUALITY NORMALIZER
       Every psychology signal (Clinical, Fortress, HT Killer, Wounded, etc.)
       is now weighted by the average defensive strength of the opponents
       faced in those matches BEFORE awarding points.

       Quality is measured by opponent avg goals conceded (higher = weaker).
       League baseline is 1.30 goals conceded per match.

       If team built their signal vs opponents weaker than baseline:
         → Signal score is DISCOUNTED (multiplied down)
       If team built their signal vs opponents stronger than baseline:
         → Signal score is AMPLIFIED (multiplied up)

       This means a Fortress record against relegated candidates scores
       far less than the same Fortress record against top-half opposition.
       A Wounded Beast that was hurt by a strong team scores more than
       one hurt by a bottom-table side.

    2. ZERO EXTRA API CALLS
       participants is already in the include string for every history fetch.
       Opposition IDs are extracted from each fixture's participants array.
       Their conceded rate is pulled from the same historical cache that
       is already in memory. No new endpoints touched.

    3. QUALITY CACHE
       All opponent conceded averages are cached the first time they are
       computed so the same opponent is never fetched or calculated twice
       across different fixtures or teams.
    ──────────────────────────────────────────────────────────────────────────
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────
    # 1. CONFIGURATION
    # ──────────────────────────────────────────────────────────────────────
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return []

    BASE_URL  = "https://api.sportmonks.com/v3/football"
    TODAY_STR = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    INPUT_FILE    = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{TODAY_STR}.csv")
    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")
    OUTPUT_CSV    = os.path.join(OUTPUT_DIR, f"ALIENEDGE_WIN_PREDICTIONS_{TODAY_STR}.csv")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - [WIN ENGINE] - %(message)s'
    )

    # ──────────────────────────────────────────────────────────────────────
    # 2. API LAYER
    # ──────────────────────────────────────────────────────────────────────
    API_CACHE     = {}
    REQUEST_DELAY = 0.2

    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)
        cache_key = path + "?" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"
        )
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]
        backoff = 2.0
        for attempt in range(5):
            try:
                resp = requests.get(
                    f"{BASE_URL}{path}", params=params, timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    API_CACHE[cache_key] = data
                    time.sleep(REQUEST_DELAY)
                    return data
                elif resp.status_code == 429:
                    time.sleep(backoff); backoff *= 1.5; continue
                else:
                    return {"data": []}
            except Exception:
                time.sleep(1); continue
        return {"data": []}

    # ──────────────────────────────────────────────────────────────────────
    # 3. NAME HELPERS
    # ──────────────────────────────────────────────────────────────────────
    def clean_n(name):
        n = str(name).lower()
        for w in ["u19","u23","fc","sc","united","city","club",
                  "afc","rc","as","deportivo","atletico"]:
            n = n.replace(w, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n     = clean_n(name)
        parts = n.split('vs') if 'vs' in n else [n]
        parts = [p.strip() for p in parts]; parts.sort()
        return "".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # 4. GOAL EXTRACTORS (unchanged — confirmed working)
    # ──────────────────────────────────────────────────────────────────────
    def extract_goals_by_period(fx, period="FT"):
        home_g = away_g = None
        for entry in fx.get("scores", []):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            desc  = str(entry.get(
                "description", s_obj.get("description", "")
            )).upper()
            if any(w in desc for w in ["PENALTY","EXTRA","AGG"]): continue
            p = s_obj.get("participant") or entry.get("participant")
            g = (s_obj.get("goals") if isinstance(s_obj, dict)
                 else entry.get("goals"))
            if g is not None:
                try:
                    val = int(g)
                    if period == "FT":
                        if p == "home": home_g = max(home_g or 0, val)
                        elif p == "away": away_g = max(away_g or 0, val)
                    elif period == "HT":
                        if any(w in desc for w in ["1ST","HT","HALF"]):
                            if p == "home": home_g = max(home_g or 0, val)
                            elif p == "away": away_g = max(away_g or 0, val)
                except Exception: pass
        return home_g, away_g

    def get_team_and_opp_goals(fx, team_id, period="FT"):
        hg, ag = extract_goals_by_period(fx, period)
        if hg is None or ag is None: return None, None
        for p in fx.get("participants", []):
            if str(p.get("id")) == str(team_id):
                loc = (p.get("meta") or {}).get("location")
                if loc == "home": return hg, ag
                if loc == "away": return ag, hg
        local = (fx.get("localteam_id") or fx.get("localteam")
                 or fx.get("local_team_id"))
        if str(local) == str(team_id): return hg, ag
        parts = fx.get("participants", [])
        if len(parts) >= 2:
            if str(parts[0].get("id")) == str(team_id): return hg, ag
            if str(parts[1].get("id")) == str(team_id): return ag, hg
        return None, None

    def get_match_outcome(fx, team_id, period="FT"):
        tg, og = get_team_and_opp_goals(fx, team_id, period)
        if tg is None or og is None: return None
        return "W" if tg > og else ("L" if tg < og else "D")

    def extract_stat_value(fx, team_id, stat_names):
        entries = fx.get("statistics", [])
        if isinstance(entries, dict):
            entries = entries.get(str(team_id), [])
        else:
            entries = [s for s in entries
                       if str(s.get("participant_id","")) == str(team_id)]
        for s in entries:
            t_name = str(
                s.get("type",{}).get("name", s.get("name",""))
            ).upper()
            if any(name.upper() in t_name for name in stat_names):
                val = (s.get("data",{}).get("value")
                       if isinstance(s.get("data"), dict)
                       else s.get("value"))
                try: return float(val)
                except: pass
        return 0.0

    # ──────────────────────────────────────────────────────────────────────
    # 5. OPPOSITION QUALITY ENGINE
    # ──────────────────────────────────────────────────────────────────────
    # League baseline: average goals conceded per match across all leagues.
    # 1.30 is a conservative cross-league average.
    # Higher value = weaker defense (concedes more).
    # Lower value  = stronger defense (concedes less).
    LEAGUE_BASELINE_CONCEDED = 1.30

    # Cache so the same opponent is never computed twice
    OPP_QUALITY_CACHE = {}

    def get_opponent_id(fx, team_id):
        """Returns the opponent's ID from a fixture."""
        for p in fx.get("participants", []):
            if str(p.get("id")) != str(team_id):
                return str(p.get("id"))
        return None

    def get_opponent_avg_conceded(opp_id, check_date_str):
        """
        Computes the opponent's average goals conceded across their
        last 5 finished matches. Uses the API cache — if the opponent
        was already fetched as a main team this run, zero new calls.
        """
        if not opp_id: return LEAGUE_BASELINE_CONCEDED
        if opp_id in OPP_QUALITY_CACHE: return OPP_QUALITY_CACHE[opp_id]

        end_dt   = (datetime.strptime(check_date_str, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(check_date_str, "%Y-%m-%d")
                    - timedelta(days=180)).strftime("%Y-%m-%d")

        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{opp_id}",
            params={
                "include":  "participants;scores",
                "filters":  "fixtureStates:5",
                "order":    "desc",
                "per_page": 5
            }
        )
        fixtures = resp.get("data", [])[:5]
        if not fixtures:
            OPP_QUALITY_CACHE[opp_id] = LEAGUE_BASELINE_CONCEDED
            return LEAGUE_BASELINE_CONCEDED

        conceded_vals = []
        for fx in fixtures:
            _, og = get_team_and_opp_goals(fx, opp_id, "FT")
            if og is not None: conceded_vals.append(og)

        avg = (round(sum(conceded_vals)/len(conceded_vals), 2)
               if conceded_vals else LEAGUE_BASELINE_CONCEDED)
        OPP_QUALITY_CACHE[opp_id] = avg
        return avg

    def compute_quality_multiplier(fixtures_list, team_id, check_date_str):
        """
        For a list of fixtures, extracts the opponent in each fixture,
        computes their avg goals conceded, and returns:

          quality_multiplier : float
            > 1.0 → opponents were stronger than baseline (signal is amplified)
            < 1.0 → opponents were weaker than baseline  (signal is discounted)
            = 1.0 → opponents were exactly at baseline   (no adjustment)

          avg_opp_conceded : float
            Raw average for transparency in output

        Formula:
          avg_opp_conceded across all fixtures in the list
          multiplier = avg_opp_conceded / LEAGUE_BASELINE_CONCEDED
          BUT inverted: stronger defense (lower conceded) = higher multiplier

          multiplier = LEAGUE_BASELINE_CONCEDED / avg_opp_conceded
            → If opp avg conceded = 0.80 (strong defense):
                multiplier = 1.30/0.80 = 1.625  (signal amplified — earned vs tough)
            → If opp avg conceded = 2.00 (weak defense):
                multiplier = 1.30/2.00 = 0.65   (signal discounted — padded vs weak)
            → If opp avg conceded = 1.30 (baseline):
                multiplier = 1.30/1.30 = 1.00   (no change)

          Capped between 0.50 and 1.80 to prevent extreme distortion.
        """
        if not fixtures_list: return 1.0, LEAGUE_BASELINE_CONCEDED

        opp_conceded_vals = []
        for fx in fixtures_list:
            opp_id  = get_opponent_id(fx, team_id)
            opp_avg = get_opponent_avg_conceded(opp_id, check_date_str)
            opp_conceded_vals.append(opp_avg)

        avg_opp_conceded = round(
            sum(opp_conceded_vals)/len(opp_conceded_vals), 2
        )

        # Invert: lower opp conceded = stronger opponent = higher multiplier
        raw_multiplier = (LEAGUE_BASELINE_CONCEDED / avg_opp_conceded
                          if avg_opp_conceded > 0
                          else 1.0)

        # Cap to prevent extreme distortion
        multiplier = round(max(0.50, min(1.80, raw_multiplier)), 3)
        return multiplier, avg_opp_conceded

    # ──────────────────────────────────────────────────────────────────────
    # 6. WIN TACTICS ENGINE — now quality-normalised
    # ──────────────────────────────────────────────────────────────────────
    def analyze_win_tactics(team_id, target_venue, opp_id, current_match_id):
        end_dt   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_dt = (datetime.now(timezone.utc)
                    - timedelta(days=365)).strftime("%Y-%m-%d")

        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "statistics.type;participants;scores",
                "per_page": 40,
                "order":    "desc",
                "filter":   "fixtureStates:5"
            }
        )
        fixtures = [
            f for f in resp.get("data", [])
            if str(f.get("id")) != str(current_match_id)
        ]

        overall_history = fixtures[:5]

        venue_history = [
            f for f in fixtures
            if any(
                str(p.get("id")) == str(team_id) and
                p.get("meta", {}).get("location") == target_venue
                for p in f.get("participants", [])
            )
        ][:5]

        if len(venue_history) < 3:
            venue_history = overall_history

        # ── QUALITY MULTIPLIERS ──────────────────────────────────────────
        # Computed once per team per venue — reused across all signals
        overall_qm, overall_opp_avg = compute_quality_multiplier(
            overall_history, team_id, TODAY_STR
        )
        venue_qm, venue_opp_avg = compute_quality_multiplier(
            venue_history, team_id, TODAY_STR
        )

        # ── 1. CLINICAL KILLER (overall form — use overall_qm) ──────────
        sot_list = [extract_stat_value(f, team_id, ["Shots On Target"])
                    for f in overall_history]
        bcc_list = [extract_stat_value(f, team_id, ["Big Chances"])
                    for f in overall_history]
        avg_sot = sum(sot_list)/len(sot_list) if sot_list else 0.0
        avg_bcc = sum(bcc_list)/len(bcc_list) if bcc_list else 0.0

        # Apply quality multiplier to the thresholds:
        # If opponents were weak (qm < 1) raise the bar needed to qualify.
        # If opponents were strong (qm > 1) lower the bar — harder to achieve.
        adjusted_sot_threshold = 4.5 / overall_qm
        adjusted_bcc_threshold = 1.5 / overall_qm
        is_clinical = (avg_sot >= adjusted_sot_threshold and
                       avg_bcc >= adjusted_bcc_threshold)

        # ── 2. FORTRESS / HOMESICK (venue form — use venue_qm) ──────────
        venue_ft_outcomes = [
            get_match_outcome(f, team_id, "FT") for f in venue_history
        ]
        venue_wins = venue_ft_outcomes.count("W")

        # Quality-adjusted thresholds:
        # Fortress vs weak opposition requires more wins to qualify.
        # Fortress vs strong opposition requires fewer wins.
        if target_venue == "home":
            # Baseline fortress threshold = 4 wins out of 5
            # Weak opp (qm=0.65): need ceil(4/0.65)=6 → capped at 5 → still 4+
            # Strong opp (qm=1.60): need ceil(4/1.60)=3 → lower bar earned
            fortress_threshold = max(2, round(4 * (1 / venue_qm)))
            is_fortress  = (venue_wins >= fortress_threshold)
            is_homesick  = False
        else:
            fortress_threshold = max(2, round(3 * (1 / venue_qm)))
            is_fortress  = (venue_wins >= fortress_threshold)
            # Homesick: quality-adjusted — if team underperformed vs weak away
            # opposition they are genuinely poor away, not just unlucky
            homesick_ceiling = max(1, round(2 * venue_qm))
            is_homesick  = (venue_wins <= homesick_ceiling)

        # ── 3. 1ST HALF KILLER (venue form — use venue_qm) ──────────────
        venue_ht_outcomes = [
            get_match_outcome(f, team_id, "HT") for f in venue_history
        ]
        ht_wins = venue_ht_outcomes.count("W")
        ht_threshold   = max(2, round(3 * (1 / venue_qm)))
        is_ht_killer   = (ht_wins >= ht_threshold and
                          len(venue_ht_outcomes) >= 4)

        # ── 4. BRICK WALL & GLASS JAW (overall — use overall_qm) ────────
        conceded_list      = []
        ht_conceded_count  = 0
        for f in overall_history:
            tg, og = get_team_and_opp_goals(f, team_id, "FT")
            if og is not None: conceded_list.append(og)
            ht_tg, ht_og = get_team_and_opp_goals(f, team_id, "HT")
            if ht_og is not None and ht_og > 0: ht_conceded_count += 1

        avg_conc = (sum(conceded_list)/len(conceded_list)
                    if conceded_list else 1.0)

        # Quality-adjusted conceded thresholds:
        # Brick wall vs weak attacks (low qm) needs a stricter conceded avg
        # Brick wall vs strong attacks (high qm) is more impressive at same avg
        brick_threshold = 0.85 * overall_qm   # strong opp: easier to qualify
        glass_threshold = 1.80 / overall_qm   # weak opp: harder to qualify

        is_brick_wall   = (avg_conc <= brick_threshold and
                           len(conceded_list) >= 3)
        is_glass_jaw    = (avg_conc > glass_threshold and
                           len(conceded_list) >= 3)
        is_ht_vulnerable = (ht_conceded_count >= 3 and
                            len(overall_history) >= 4)

        # ── 5. WOUNDED BEAST & WINLESS (overall — H2H uses real state) ──
        overall_outcomes_5 = [
            get_match_outcome(f, team_id, "FT") for f in overall_history
        ]
        overall_outcomes_2 = overall_outcomes_5[:2]

        shock_loss = (len(overall_outcomes_2) > 0 and
                      overall_outcomes_2[0] == "L")
        winless_2  = (len(overall_outcomes_2) == 2 and
                      "W" not in overall_outcomes_2)
        is_winless_5 = (len(overall_outcomes_5) >= 4 and
                        "W" not in overall_outcomes_5)

        # H2H: fetch with proper finished-state filter as API param
        h2h_data = GET(
            f"/fixtures/head-to-head/{team_id}/{opp_id}",
            params={
                "include":  "scores;participants",
                "filters":  "fixtureStates:5",   # filter in API not Python
                "per_page": 5,
                "order":    "desc"
            }
        )
        past_h2h = [
            h for h in h2h_data.get("data", [])
            if str(h.get("id")) != str(current_match_id)
        ]
        h2h_hum = (
            bool(past_h2h) and
            get_match_outcome(past_h2h[0], team_id, "FT") == "L"
        )

        # Wounded signal quality weight:
        # A shock loss to a strong opponent (low conceded = high qm) is a
        # more meaningful wound than a loss to a weak side.
        # We do not change is_wounded itself but pass qm for scoring use.
        is_wounded = (shock_loss or winless_2 or h2h_hum)

        return {
            "is_clinical":      is_clinical,
            "is_fortress":      is_fortress,
            "is_homesick":      is_homesick,
            "is_ht_killer":     is_ht_killer,
            "is_brick_wall":    is_brick_wall,
            "is_glass_jaw":     is_glass_jaw,
            "is_ht_vulnerable": is_ht_vulnerable,
            "is_wounded":       is_wounded,
            "is_winless_5":     is_winless_5,
            "avg_sot":          round(avg_sot,    1),
            "avg_bcc":          round(avg_bcc,    1),
            "avg_conc":         round(avg_conc,   2),
            # Quality metadata — passed to scoring for point weighting
            "overall_qm":       overall_qm,
            "venue_qm":         venue_qm,
            "overall_opp_avg":  overall_opp_avg,
            "venue_opp_avg":    venue_opp_avg,
        }

    # ──────────────────────────────────────────────────────────────────────
    # 7. SCORING ENGINE — quality-weighted points
    # ──────────────────────────────────────────────────────────────────────
    def calculate_win_score(team_traits, opp_traits,
                             team_spear, opp_spear, is_home):
        """
        Every point award is now multiplied by the relevant quality
        multiplier before being added to the score.

        overall_qm > 1.0 → team proved their form against strong opponents
                           → signal is worth more points
        overall_qm < 1.0 → team built their record against weak opponents
                           → signal is worth fewer points

        This prevents a team from scoring 80+ psychology points purely
        because they had a great run against relegation-zone opposition.
        """
        score   = 0
        reasons = []

        qm_o = team_traits["overall_qm"]   # for overall-form signals
        qm_v = team_traits["venue_qm"]     # for venue-form signals

        def award(base_pts, qm, label):
            """Apply quality multiplier and return rounded integer points."""
            pts = round(base_pts * qm)
            return max(1, pts)   # always at least 1 if signal fired

        # ── POSITIVE SIGNALS ────────────────────────────────────────────

        if team_traits["is_clinical"]:
            pts = award(15, qm_o, "Clinical")
            score += pts
            reasons.append(
                f"🎯 Clinical (+{pts} | opp avg conc {team_traits['overall_opp_avg']})"
            )

        if team_traits["is_fortress"]:
            pts = award(15, qm_v, "Fortress")
            score += pts
            reasons.append(
                f"🏰 Fortress (+{pts} | venue opp avg conc {team_traits['venue_opp_avg']})"
            )

        if team_traits["is_ht_killer"]:
            pts = award(15, qm_v, "HT Killer")
            score += pts
            reasons.append(f"⚡ 1H Killer (+{pts})")

        if team_traits["is_wounded"]:
            pts = award(15, qm_o, "Wounded")
            score += pts
            reasons.append(f"🩸 Wounded (+{pts})")

        if team_traits["is_ht_killer"] and opp_traits["is_ht_vulnerable"]:
            pts = award(10, qm_v, "Early Kill")
            score += pts
            reasons.append(f"⏱️ Early Kill (+{pts})")

        # ── SPEAR POWER ──────────────────────────────────────────────────
        if team_spear > 65.0:
            score += 15
            reasons.append(f"🔥 Elite Scorer {team_spear}% (+15)")
        elif team_spear > 50.0:
            score += 5
            reasons.append(f"⚔️ Active Scorer {team_spear}% (+5)")

        # ── SPEAR COMPARISON ─────────────────────────────────────────────
        if opp_spear > 75.0 and team_spear > 75.0:
            score -= 30
            reasons.append(f"🛑 Shootout Threat {opp_spear}% (-30)")

        if team_spear > opp_spear:
            score += 20
            reasons.append("⚔️ Superior Spear Power (+20)")
            if (team_spear - opp_spear) >= 15.0:
                score += 10
                reasons.append("🔥 Massive Spear Gap (+10)")

        # ── OPPONENT SIGNALS ─────────────────────────────────────────────
        # Use opponent's OWN quality multipliers for opponent-based signals
        opp_qm_o = opp_traits["overall_qm"]
        opp_qm_v = opp_traits["venue_qm"]

        if opp_traits["is_brick_wall"]:
            # Brick wall vs strong attacks (high opp_qm) is scarier
            pts = award(25, opp_qm_o, "Brick Wall")
            score -= pts
            reasons.append(
                f"🧱 Brick Wall (-{pts} | opp built vs "
                f"avg conc {opp_traits['overall_opp_avg']})"
            )

        if opp_traits["is_glass_jaw"] and opp_spear < 40.0:
            pts = award(20, opp_qm_o, "Glass Jaw")
            score += pts
            reasons.append(f"🔨 Glass Jaw (+{pts})")

        if opp_traits["is_winless_5"]:
            score -= 20
            reasons.append("🐾 Cornered Animal (-20)")

        # ── AWAY PENALTY ─────────────────────────────────────────────────
        if not is_home:
            if team_traits["is_homesick"]:
                # Quality-weight: homesick vs strong away opposition is
                # a harder penalty than homesick vs weak opposition
                pts = award(10, qm_v, "Homesick")
                score -= pts
                reasons.append(f"✈️ Homesick Penalty (-{pts})")
            if opp_spear > 55.0:
                score -= 15
                reasons.append("🌋 Hostile Crowd (-15)")

        if not reasons: reasons.append("No triggers met")
        return score, reasons

    # ──────────────────────────────────────────────────────────────────────
    # 8. MAIN EXECUTION
    # ──────────────────────────────────────────────────────────────────────
    print(f"\n>> [AlienEdge WIN ENGINE — GODMODE] "
          f"Quality-Normalised Protocol Active... ({TODAY_STR})")

    if not os.path.exists(INPUT_FILE):
        print(f"🛑 FATAL: {INPUT_FILE} not found. Run Code 1 first.")
        return []

    try:
        df_in    = pd.read_csv(INPUT_FILE)
        raw_data = []
        grouped  = df_in.groupby('fixture_id')
        for fid, group in grouped:
            fix_name = group.iloc[0]['fixture']
            h_row    = group[group['side'] == 'home']
            a_row    = group[group['side'] == 'away']
            h_poisson = (float(str(h_row.iloc[0]['poisson_win_prob'])
                          .replace('%','')) if not h_row.empty else 0.0)
            a_poisson = (float(str(a_row.iloc[0]['poisson_win_prob'])
                          .replace('%','')) if not a_row.empty else 0.0)
            raw_data.append({
                "fixture_id":   fid,
                "fixture_name": fix_name,
                "h_poisson":    h_poisson,
                "a_poisson":    a_poisson,
            })
    except Exception as e:
        print(f"🛑 Error reading {INPUT_FILE}: {e}")
        return []

    # Catalyst (underdog spear data)
    cat_db = {}
    if os.path.exists(FILE_CATALYST):
        try:
            cat_csv = pd.read_csv(FILE_CATALYST)
            for _, row in cat_csv.iterrows():
                try:
                    fix_key  = get_match_key(str(row['fixture']))
                    dog_name = str(row['underdog_team'])
                    dog_prob = float(str(row['Audit_Real_Prob'])
                                     .replace('%','').strip())
                    fav_prob = float(str(row['Fav_Spear_Power'])
                                     .replace('%','').strip())
                    cat_db[fix_key] = {
                        "dog_name": dog_name,
                        "dog_prob": dog_prob,
                        "fav_prob": fav_prob
                    }
                except: continue
        except: pass

    # Today's fixture ID map
    todays_fixtures_map = {}
    print("   🔍 Mapping fixture IDs...")
    page = 1
    while True:
        resp = GET(
            f"/fixtures/date/{TODAY_STR}",
            params={"include":"participants","per_page":50,"page":page}
        )
        data = resp.get("data", [])
        if not data: break
        for fx in data:
            parts = fx.get("participants", [])
            h = next((p for p in parts
                      if p.get('meta',{}).get('location')=='home'), None)
            a = next((p for p in parts
                      if p.get('meta',{}).get('location')=='away'), None)
            if h and a:
                todays_fixtures_map[fx['id']] = {
                    "hid": h['id'], "aid": a['id']
                }
        page += 1
        time.sleep(REQUEST_DELAY)

    processed_list = []

    for match in raw_data:
        try:
            fid      = match["fixture_id"]
            fix_name = match["fixture_name"]

            if fid not in todays_fixtures_map: continue

            home_id   = todays_fixtures_map[fid]["hid"]
            away_id   = todays_fixtures_map[fid]["aid"]
            home_name = (fix_name.split(" vs ")[0]
                         if " vs " in fix_name else "Home")
            away_name = (fix_name.split(" vs ")[1]
                         if " vs " in fix_name else "Away")

            cat_info = cat_db.get(get_match_key(fix_name), {})
            dog_name = cat_info.get("dog_name", "")

            if clean_n(home_name) == clean_n(dog_name):
                h_spear = cat_info.get("dog_prob", 0.0)
                a_spear = cat_info.get("fav_prob", 0.0)
            else:
                h_spear = cat_info.get("fav_prob", 0.0)
                a_spear = cat_info.get("dog_prob", 0.0)

            print(f"   🔎 Analysing {fix_name[:40]}...")

            h_traits = analyze_win_tactics(home_id, "home", away_id, fid)
            a_traits = analyze_win_tactics(away_id, "away", home_id, fid)

            h_base_score, h_reasons = calculate_win_score(
                h_traits, a_traits, h_spear, a_spear, True
            )
            a_base_score, a_reasons = calculate_win_score(
                a_traits, h_traits, a_spear, h_spear, False
            )

            net_h_score = h_base_score - a_base_score
            net_a_score = a_base_score - h_base_score

            h_poisson   = match["h_poisson"]
            a_poisson   = match["a_poisson"]

            if h_poisson > a_poisson:
                base_pick, base_prob = home_name, h_poisson
            elif a_poisson > h_poisson:
                base_pick, base_prob = away_name, a_poisson
            else:
                base_pick, base_prob = "TIE", h_poisson

            poisson_gap = abs(h_poisson - a_poisson)

            if net_h_score >= 20 and net_h_score > net_a_score:
                audit_raw_winner = home_name
                win_net_score    = net_h_score
                win_reasons      = h_reasons
                new_spear        = h_spear
                old_spear        = a_spear
            elif net_a_score >= 20 and net_a_score > net_h_score:
                audit_raw_winner = away_name
                win_net_score    = net_a_score
                win_reasons      = a_reasons
                new_spear        = a_spear
                old_spear        = h_spear
            else:
                audit_raw_winner = "TIE / AVOID"
                win_net_score    = max(net_h_score, net_a_score)
                win_reasons      = (h_reasons if net_h_score >= net_a_score
                                    else a_reasons)

            # ── OVERTURN GATEKEEPER (bug fixed) ──────────────────────────
            # Original code had `pass` which accidentally allowed overturns.
            # Fixed: explicitly set audit_winner = base_pick when the
            # Poisson gap is small AND the spear advantage is not decisive.
            audit_winner = audit_raw_winner
            if (audit_raw_winner != base_pick and
                    audit_raw_winner != "TIE / AVOID" and
                    base_pick != "TIE"):
                spear_gap = (new_spear - old_spear) if old_spear else 0
                if poisson_gap < 15.0 and spear_gap <= 10.0:
                    # Not enough evidence to overturn — revert to base pick
                    audit_winner = base_pick
                # else: overturn stands (spear gap is decisive)

            if (audit_winner == base_pick and
                    audit_winner != "TIE / AVOID"):
                tier = ("💎 SYNDICATE LOCK (Verified)"
                        if win_net_score >= 45
                        else "🔥 SOLID WIN (Verified)")
            elif audit_winner != "TIE / AVOID":
                tier = f"🚨 OVERTURNED (Auditor prefers {audit_winner})"
            else:
                tier = "🛑 CAUTION: TRAP (Code 1 Pick Avoided)"

            # Quality summary for output transparency
            h_qm_label = (
                f"H-OppAvg:{h_traits['overall_opp_avg']} "
                f"QM:{h_traits['overall_qm']}"
            )
            a_qm_label = (
                f"A-OppAvg:{a_traits['overall_opp_avg']} "
                f"QM:{a_traits['overall_qm']}"
            )

            processed_list.append({
                "Fixture":      fix_name,
                "Master_Pick":  base_pick,
                "Master_Prob":  f"{base_prob}%",
                "Audit_Score":  win_net_score,
                "H_Base":       h_base_score,
                "A_Base":       a_base_score,
                "Tier":         tier,
                "Spears":       f"H:{h_spear}% | A:{a_spear}%",
                "H_Quality":    h_qm_label,
                "A_Quality":    a_qm_label,
                "Home_Logic":   " | ".join(h_reasons),
                "Away_Logic":   " | ".join(a_reasons),
            })

            print(
                f"     > {fix_name[:30]:<30} | "
                f"H:{h_base_score:>3} (QM:{h_traits['overall_qm']}) | "
                f"A:{a_base_score:>3} (QM:{a_traits['overall_qm']}) | "
                f"Net:{win_net_score:>+4} | {tier}"
            )

        except Exception as e:
            print(f"   ⚠️  Error on {match.get('fixture_name','?')}: {e}")
            continue

    # ──────────────────────────────────────────────────────────────────────
    # 9. OUTPUT
    # ──────────────────────────────────────────────────────────────────────
    final_table = pd.DataFrame(processed_list)
    if final_table.empty:
        print("\n>>[FATAL] No matches processed.")
        return []

    final_table = final_table.sort_values(
        by=["Audit_Score"], ascending=False
    )

    diamond_df   = final_table[final_table['Tier'].str.contains("💎")]
    solid_df     = final_table[final_table['Tier'].str.contains("🔥")]
    overturn_df  = final_table[final_table['Tier'].str.contains("🚨")]

    print("\n" + "💎"*40)
    print(" 💎 THE ALIENEDGE VERIFIED LOCKS 💎")
    print("💎"*40)
    if not diamond_df.empty:
        for i, (_,row) in enumerate(diamond_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']} → 🏆 {row['Master_Pick']} "
                f"(Poisson:{row['Master_Prob']} | Net:+{row['Audit_Score']})"
            )
            print(f"   Quality: {row['H_Quality']} | {row['A_Quality']}")
            print(f"   Home:    {row['Home_Logic']}")
            print(f"   Away:    {row['Away_Logic']}\n")
    else:
        print("   [!] No Diamond Locks today.\n")

    print("\n" + "🔥"*40)
    print(" 🔥 SOLID VERIFIED WINS 🔥")
    print("🔥"*40)
    if not solid_df.empty:
        for i, (_,row) in enumerate(solid_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']} → 🏆 {row['Master_Pick']} "
                f"(Poisson:{row['Master_Prob']} | Net:+{row['Audit_Score']})"
            )
            print(f"   Quality: {row['H_Quality']} | {row['A_Quality']}")
            print(f"   Home:    {row['Home_Logic']}")
            print(f"   Away:    {row['Away_Logic']}\n")
    else:
        print("   [!] No Solid Wins today.\n")

    print("\n" + "🚨"*40)
    print(" 🚨 OVERTURNED BY AUDITOR 🚨")
    print("🚨"*40)
    if not overturn_df.empty:
        for i, (_,row) in enumerate(overturn_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']} → 🛑 Code 1: {row['Master_Pick']} "
                f"({row['Master_Prob']})"
            )
            print(f"   {row['Tier']} | Net:+{row['Audit_Score']}")
            print(f"   Home: {row['Home_Logic']}")
            print(f"   Away: {row['Away_Logic']}\n")
    else:
        print("   [!] No overturns today.\n")

    cols = [
        "Fixture","Master_Pick","Master_Prob",
        "H_Base","A_Base","Audit_Score","Tier","Spears",
        "H_Quality","A_Quality","Home_Logic","Away_Logic"
    ]
    print("\n" + "="*150)
    print("📊 FULL WIN FORENSIC BOARD")
    print("="*150)
    print(final_table[cols].to_string(index=False))

    final_table.to_csv(OUTPUT_CSV, index=False)
    print(f"\n💾 Saved: {OUTPUT_CSV}")

    return final_table.to_dict(orient="records")


if __name__ == "__main__":
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    run_win_psychology_engine()