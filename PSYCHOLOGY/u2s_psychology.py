import os
import sys
import time
import requests
import pandas as pd
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- ENVIRONMENT SETUP ---
load_dotenv()

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER
# ==============================================================================
def run_u2s_psychology_engine(target_date=None):
    """
    AlienEdge Underdog to Score (U2S) Psychology Engine — REDESIGNED

    ═══════════════════════════════════════════════════════════════════════════
    THREE-LAYER ARCHITECTURE
    ═══════════════════════════════════════════════════════════════════════════

    LAYER 1 — HARD GATES (Binary Pass/Fail — runs before any scoring)
    ──────────────────────────────────────────────────────────────────
      Gate 1 : Dog venue avg SOT < 2.5              → ELIMINATED
      Gate 2 : Fav venue avg conceded < 0.5         → ELIMINATED
      Gate 3 : Fav venue possession > 65%
               AND dog venue possession < 35%        → ELIMINATED

      Gates are absolute. No score is computed for eliminated fixtures.
      Negative points cannot bury a gate — gates fire first, always.

    LAYER 2 — FORENSIC SCORE (All signals venue-locked to last 3 matches)
    ──────────────────────────────────────────────────────────────────────
      TIER A — Primary Evidence (uncapped, drives verdicts)
        Venue SOT Dominance       : Dog > Fav → +20 | Fav > Dog → -15
        Opponent Quality Adj SOT  : Dog earned SOT vs stronger opp → +15
                                    Dog SOT padded vs weaker opp   → -10
                                    (Fixed: no self-cancelling +20/-20)
        Venue Scoring Consistency : 3/3 → +15 | 2/3 → 0 | 0-1/3 → -15

      TIER B — Contextual Boosters (uncapped, must be venue-earned)
        Cerberus Awakening (venue) : High venue SOT + low venue goals → +15
        H2H SOT Edge               : Dog > Fav in last H2H → +10 | Loss → -8
        Wounded Venue Bounce       : Lost last venue match + high venue SOT → +10
        Venue Track Meet           : Both teams venue avg goals combined > 2.5 → +10

      TIER C — Narrative Signals (collectively HARD CAPPED at +20)
        False Favorite             : Dog Spear > Fav Spear + better venue def → +15
        Relegation Desperation     : Dog bottom 5 + Fav top 8 → +10
        Territorial Aggressor      : Dog winning venue corners → +8
        Real Underdog Awakened     : False Fav + Wounded → +10

    LAYER 3 — VERDICT ENGINE
    ────────────────────────
      Score ≥ 50  → 💎 LOCK   (High conviction — Real Underdog)
      Score 30-49 → 🔥 PLAY   (Solid ambush — worth backing)
      Score 10-29 → 📊 MONITOR (Lean — watch line movement)
      Score < 10  → 🛑 PASS   (Insufficient evidence)
      Gate fail   → ❌ VETOED  (Hard eliminated, score not computed)
    ═══════════════════════════════════════════════════════════════════════════
    """

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    # ==========================================================================
    # 1. CONFIGURATION
    # ==========================================================================
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY missing from environment variables!")
        return []

    BASE_URL = "https://api.sportmonks.com/v3/football"

    TODAY_STR = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    INPUT_FILE = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")
    OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U2S_PSYCHOLOGY_{TODAY_STR}.csv")

    # ==========================================================================
    # 🛡️ API LAYER — SINGLE CACHE, SMART BACKOFF, RATE-AWARE
    # ==========================================================================
    API_CACHE       = {}
    STANDINGS_CACHE = {}
    REQUEST_DELAY   = 0.25          # conservative inter-request gap
    _last_request_t = [0.0]         # mutable ref so inner functions can update it

    def GET(path, params=None):
        """
        Single authoritative API caller.
        - Caches by (path + sorted non-token params) to prevent duplicate calls
        - Enforces REQUEST_DELAY between live requests
        - Exponential backoff on 429, up to 5 retries
        - Returns {"data": []} on all failure modes — callers never crash
        """
        if params is None:
            params = {}
        params.setdefault("api_token", API_KEY)

        cache_key = path + "?" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"
        )
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]

        # Enforce minimum gap between live requests
        elapsed = time.time() - _last_request_t[0]
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

        backoff = 2.0
        for attempt in range(5):
            try:
                resp = requests.get(
                    f"{BASE_URL}{path}", params=params, timeout=30
                )
                _last_request_t[0] = time.time()

                if resp.status_code == 200:
                    data = resp.json()
                    API_CACHE[cache_key] = data
                    return data

                elif resp.status_code == 429:
                    print(f"   ⚠️  Rate limited — waiting {backoff:.1f}s (attempt {attempt+1}/5)")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)   # cap at 60s
                    continue

                else:
                    print(f"   ⚠️  API {resp.status_code} on {path}")
                    return {"data": []}

            except Exception as exc:
                print(f"   ⚠️  Request exception: {exc}")
                time.sleep(1)
                continue

        return {"data": []}

    # ==========================================================================
    # 🔑 NAME MATCHING HELPERS
    # ==========================================================================
    def clean_n(name):
        n = str(name).lower()
        for word in ["u19", "u23", "fc", "sc", "united", "city", "club",
                     "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n     = clean_n(name)
        parts = n.split('vs') if 'vs' in n else [n]
        parts = [p.strip() for p in parts]
        parts.sort()
        return "".join(parts)

    # ==========================================================================
    # 📊 STANDINGS
    # ==========================================================================
    def get_league_standings_map(league_id, season_id):
        if not league_id or league_id == "Unknown" or not season_id:
            return {}
        cache_key = f"{league_id}_{season_id}"
        if cache_key in STANDINGS_CACHE:
            return STANDINGS_CACHE[cache_key]

        resp = GET(
            f"/standings/seasons/{season_id}",
            params={"filters": f"standingLeagues:{league_id}"}
        )
        pos_map = {
            int(s["participant_id"]): int(s["position"])
            for s in resp.get("data", [])
            if s.get("participant_id") and s.get("position")
        }
        STANDINGS_CACHE[cache_key] = pos_map
        return pos_map

    # ==========================================================================
    # 📐 STAT & GOAL EXTRACTORS
    # ==========================================================================
    def extract_goals_by_period(fx, period="FT"):
        home_g = away_g = None
        for entry in fx.get("scores", []):
            if not isinstance(entry, dict):
                continue
            s_obj = entry.get("score") or entry
            desc  = str(entry.get("description",
                        s_obj.get("description", ""))).upper()
            if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
                continue
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
                        if any(w in desc for w in ["1ST", "HT", "HALF"]):
                            if p == "home": home_g = max(home_g or 0, val)
                            elif p == "away": away_g = max(away_g or 0, val)
                except Exception:
                    pass
        return home_g, away_g

    def get_team_and_opp_goals(fx, team_id, period="FT"):
        hg, ag = extract_goals_by_period(fx, period)
        if hg is None or ag is None:
            return None, None
        for p in fx.get("participants", []):
            if str(p.get("id")) == str(team_id):
                loc = (p.get("meta") or {}).get("location")
                if loc == "home": return hg, ag
                if loc == "away": return ag, hg
        local = (fx.get("localteam_id") or fx.get("localteam")
                 or fx.get("local_team_id"))
        if str(local) == str(team_id):
            return hg, ag
        return ag, hg

    def get_match_outcome(fx, team_id):
        tg, og = get_team_and_opp_goals(fx, team_id, "FT")
        if tg is None or og is None:
            return None
        return "W" if tg > og else ("L" if tg < og else "D")

    def extract_stat_value(fx, team_id, stat_names):
        entries = fx.get("statistics", [])
        if isinstance(entries, dict):
            entries = entries.get(str(team_id), [])
        else:
            entries = [s for s in entries
                       if str(s.get("participant_id", "")) == str(team_id)]
        for s in entries:
            t_name = str(
                s.get("type", {}).get("name", s.get("name", ""))
            ).upper()
            if any(name.upper() in t_name for name in stat_names):
                val = (s.get("data", {}).get("value")
                       if isinstance(s.get("data"), dict)
                       else s.get("value"))
                try:
                    return float(val)
                except Exception:
                    pass
        return 0.0

    def extract_sot_from_fixture(fx, team_id):
        """Confirmed Cerberus pattern — shots on target for one team."""
        stats_list = fx.get("statistics", [])
        if isinstance(stats_list, dict):
            stats_list = list(stats_list.values())
        for s in stats_list:
            try:
                if str(s.get("participant_id")) != str(team_id):
                    continue
                t_obj    = s.get("type")
                name_raw = t_obj.get("name") if isinstance(t_obj, dict) else t_obj
                if not name_raw:
                    continue
                if "shots on target" in str(name_raw).lower().strip():
                    data_obj = s.get("data")
                    val = (data_obj.get("value") if isinstance(data_obj, dict)
                           else s.get("value"))
                    try:
                        return float(str(val).replace("%", "").strip())
                    except Exception:
                        pass
            except Exception:
                continue
        return 0.0

    def extract_goals_conceded_from_fixture(fx, team_id):
        hg, ag = extract_goals_by_period(fx, "FT")
        if hg is None or ag is None:
            return None
        for p in fx.get("participants", []):
            if str(p.get("id")) == str(team_id):
                loc = (p.get("meta") or {}).get("location")
                if loc == "home": return ag
                if loc == "away": return hg
        return None

    def get_opponent_id_from_fixture(fx, team_id):
        for p in fx.get("participants", []):
            if str(p.get("id")) != str(team_id):
                return str(p.get("id"))
        return None

    def get_corners_matchup(fx, team_id):
        tc     = extract_stat_value(fx, team_id, ["Corners"])
        opp_id = get_opponent_id_from_fixture(fx, team_id)
        oc     = extract_stat_value(fx, opp_id, ["Corners"]) if opp_id else 0
        return tc, oc

    # ==========================================================================
    # 🗄️  BATCH FIXTURE FETCHER
    # One call per team. Returns raw fixtures list. Everything else reads from it.
    # Shared between venue analysis AND tactics — zero duplicate fetches.
    # ==========================================================================
    _fixture_cache = {}   # team_id → raw fixtures list

    def fetch_team_fixtures(team_id, check_date_str, per_page=20):
        """
        Fetches up to `per_page` finished fixtures for a team ending
        the day before check_date_str.  Results are cached by team_id
        so subsequent callers (tactics, venue, H2H) hit memory, not API.
        """
        if team_id in _fixture_cache:
            return _fixture_cache[team_id]

        end_dt   = (datetime.strptime(check_date_str, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        start_dt = (datetime.strptime(check_date_str, "%Y-%m-%d")
                    - timedelta(days=180)).strftime("%Y-%m-%d")

        resp = GET(
            f"/fixtures/between/{start_dt}/{end_dt}/{team_id}",
            params={
                "include":  "participants;statistics.type;scores",
                "filters":  "fixtureStates:5",
                "order":    "desc",
                "per_page": per_page
            }
        )
        fixtures = resp.get("data", [])
        _fixture_cache[team_id] = fixtures
        return fixtures

    def fetch_opponent_avg_conceded(opponent_id, check_date_str):
        """
        Reuses the batch cache — if opponent was already fetched as a
        main team this engine run, zero new API calls. Otherwise one call.
        """
        fixtures = fetch_team_fixtures(opponent_id, check_date_str, per_page=5)
        if not fixtures:
            return None
        values = []
        for fx in fixtures[:5]:
            gc = extract_goals_conceded_from_fixture(fx, opponent_id)
            if gc is not None:
                values.append(gc)
        return round(sum(values) / len(values), 2) if values else None

    # ==========================================================================
    # 🎯 VENUE ANALYSIS — SINGLE FUNCTION, ALL SIGNALS FROM ONE FETCH
    # Returns venue SOT, opp quality, scoring consistency, possession avg
    # ==========================================================================
    def analyze_venue_last3(team_id, venue, current_match_id, check_date_str):
        """
        From the single cached fixture list, filters for venue-specific
        last 3 matches and extracts simultaneously:
          1. Total SOT (venue)
          2. Avg goals conceded by opponents (quality proxy)
          3. Scoring consistency % (goals scored ≥ 1)
          4. Avg possession (venue)
          5. Avg goals scored (venue)
          6. Avg goals conceded (venue — for gate checks)
          7. Whether dog lost last venue match (wounded bounce signal)
        Zero extra API calls. Everything from the cache.
        """
        all_fx = [
            f for f in fetch_team_fixtures(team_id, check_date_str)
            if str(f.get("id")) != str(current_match_id)
        ]

        venue_fx = []
        for fx in all_fx:
            for p in fx.get("participants", []):
                if str(p.get("id")) == str(team_id):
                    loc = (p.get("meta") or {}).get("location")
                    if loc == venue:
                        venue_fx.append(fx)
                        break
            if len(venue_fx) == 3:
                break

        if not venue_fx:
            return {
                "total_sot":           0.0,
                "avg_sot":             0.0,
                "avg_opp_conceded":    None,
                "consistency_pct":     0.0,
                "scored_count":        0,
                "total_matches":       0,
                "avg_poss":            50.0,
                "avg_scored":          0.0,
                "avg_conceded":        1.0,
                "lost_last_venue":     False,
                "corner_wins":         0,
                "match_details":       []
            }

        total_sot         = 0.0
        opp_conceded_list = []
        scored_count      = 0
        poss_list         = []
        goals_scored_list = []
        goals_conc_list   = []
        corner_wins       = 0
        match_details     = []

        for i, fx in enumerate(venue_fx):
            # SOT
            sot = extract_sot_from_fixture(fx, team_id)
            total_sot += sot

            # Possession
            poss = extract_stat_value(fx, team_id, ["Ball Possession"])
            if poss > 0:
                poss_list.append(poss)

            # Goals scored / conceded
            tg, og = get_team_and_opp_goals(fx, team_id, "FT")
            if tg is not None:
                goals_scored_list.append(tg)
                if tg >= 1:
                    scored_count += 1
            if og is not None:
                goals_conc_list.append(og)

            # Corners
            tc, oc = get_corners_matchup(fx, team_id)
            if tc > oc:
                corner_wins += 1

            # Opponent quality — reuses cache
            opp_id           = get_opponent_id_from_fixture(fx, team_id)
            opp_avg_conceded = None
            if opp_id:
                opp_avg_conceded = fetch_opponent_avg_conceded(
                    opp_id, check_date_str
                )
            if opp_avg_conceded is not None:
                opp_conceded_list.append(opp_avg_conceded)

            match_details.append({
                "fixture_id":       fx.get("id"),
                "sot":              sot,
                "scored":           tg,
                "conceded":         og,
                "opp_id":           opp_id,
                "opp_avg_conceded": opp_avg_conceded
            })

        n = len(venue_fx)
        return {
            "total_sot":        round(total_sot, 1),
            "avg_sot":          round(total_sot / n, 2),
            "avg_opp_conceded": (
                round(sum(opp_conceded_list) / len(opp_conceded_list), 2)
                if opp_conceded_list else None
            ),
            "consistency_pct":  round((scored_count / n) * 100, 1),
            "scored_count":     scored_count,
            "total_matches":    n,
            "avg_poss":         (
                round(sum(poss_list) / len(poss_list), 1)
                if poss_list else 50.0
            ),
            "avg_scored":       (
                round(sum(goals_scored_list) / len(goals_scored_list), 2)
                if goals_scored_list else 0.0
            ),
            "avg_conceded":     (
                round(sum(goals_conc_list) / len(goals_conc_list), 2)
                if goals_conc_list else 1.0
            ),
            "lost_last_venue":  (
                get_match_outcome(venue_fx[0], team_id) == "L"
                if venue_fx else False
            ),
            "corner_wins":      corner_wins,
            "match_details":    match_details
        }

    # ==========================================================================
    # 🧠 OVERALL TACTICS (reads from cache — no new API calls)
    # Used only for the False Favorite and Wounded checks.
    # ==========================================================================
    def analyze_overall_last5(team_id, current_match_id):
        all_fx = [
            f for f in _fixture_cache.get(team_id, [])
            if str(f.get("id")) != str(current_match_id)
        ][:5]

        if not all_fx:
            return {
                "avg_conc":   1.0,
                "avg_scored": 1.0,
                "avg_sot":    0.0,
                "is_wounded": False
            }

        sot_vals    = [extract_sot_from_fixture(f, team_id) for f in all_fx]
        scored_vals = []
        conc_vals   = []
        for f in all_fx:
            tg, og = get_team_and_opp_goals(f, team_id, "FT")
            if tg is not None: scored_vals.append(tg)
            if og is not None: conc_vals.append(og)

        outcome_last = get_match_outcome(all_fx[0], team_id) if all_fx else None

        return {
            "avg_conc":   round(sum(conc_vals)   / len(conc_vals),   2) if conc_vals   else 1.0,
            "avg_scored": round(sum(scored_vals) / len(scored_vals), 2) if scored_vals else 1.0,
            "avg_sot":    round(sum(sot_vals)    / len(sot_vals),    1) if sot_vals    else 0.0,
            "is_wounded": (outcome_last == "L")
        }

    # ==========================================================================
    # 🤝 H2H LAST 1 SOT
    # ==========================================================================
    def fetch_h2h_last1_sot(dog_id, fav_id, current_match_id):
        resp = GET(
            f"/fixtures/head-to-head/{dog_id}/{fav_id}",
            params={
                "include":  "participants;statistics.type;scores",
                "per_page": 5
            }
        )
        h2h_fx = [
            f for f in resp.get("data", [])
            if str(f.get("id")) != str(current_match_id)
        ]
        if not h2h_fx:
            return None, None
        last = h2h_fx[0]
        return (
            extract_sot_from_fixture(last, dog_id),
            extract_sot_from_fixture(last, fav_id)
        )

    # ==========================================================================
    # ⚙️  LAYER 1 — HARD GATES
    # Returns (passed: bool, gate_reason: str)
    # ==========================================================================
    def run_hard_gates(dog_venue, fav_venue):
        """
        Gate 1 : Dog venue avg SOT < 2.5
        Gate 2 : Fav venue avg conceded < 0.5  (elite defense)
        Gate 3 : Fav venue possession > 65% AND dog venue possession < 35%

        All gate thresholds are venue-specific — no overall form contamination.
        """
        # Gate 1 — Toothless Dog (venue)
        if dog_venue["avg_sot"] < 2.5:
            return False, (
                f"❌ GATE 1 FAIL: Dog venue avg SOT {dog_venue['avg_sot']} < 2.5 "
                f"— toothless at this venue"
            )

        # Gate 2 — Fav Brick Wall (venue)
        if fav_venue["avg_conceded"] < 0.5:
            return False, (
                f"❌ GATE 2 FAIL: Fav venue avg conceded {fav_venue['avg_conceded']} < 0.5 "
                f"— elite defensive wall at this venue"
            )

        # Gate 3 — Chokehold (venue possession dominance)
        if fav_venue["avg_poss"] > 65.0 and dog_venue["avg_poss"] < 35.0:
            return False, (
                f"❌ GATE 3 FAIL: Fav venue possession {fav_venue['avg_poss']}% "
                f"vs Dog {dog_venue['avg_poss']}% — complete chokehold"
            )

        return True, "✅ All gates passed"

    # ==========================================================================
    # ⚖️  LAYER 2 — FORENSIC SCORING ENGINE
    # ==========================================================================
    def calculate_forensic_score(
        dog_venue, fav_venue,
        dog_overall, fav_overall,
        dog_h2h_sot, fav_h2h_sot,
        dog_spear, fav_spear,
        dog_pos, fav_pos
    ):
        """
        Tier A — Primary Evidence (uncapped)
        Tier B — Contextual Boosters (uncapped, venue-earned)
        Tier C — Narrative Signals (collectively capped at +20)
        """
        score         = 0
        tier_a        = []
        tier_b        = []
        tier_c_raw    = []
        tier_c_score  = 0

        # ==============================================================
        # TIER A — PRIMARY EVIDENCE
        # ==============================================================

        # ── A1: VENUE SOT DOMINANCE ────────────────────────────────────
        dog_v_sot = dog_venue["total_sot"]
        fav_v_sot = fav_venue["total_sot"]

        if dog_v_sot > fav_v_sot:
            score += 20
            tier_a.append(
                f"📊 A1 VENUE SOT WIN: Dog ({dog_v_sot}) > Fav ({fav_v_sot}) "
                f"across last 3 venue matches (+20)"
            )
        elif fav_v_sot > dog_v_sot:
            score -= 15
            tier_a.append(
                f"📊 A1 VENUE SOT LOSS: Fav ({fav_v_sot}) > Dog ({dog_v_sot}) "
                f"across last 3 venue matches (-15)"
            )
        else:
            tier_a.append(
                f"📊 A1 VENUE SOT TIED: Dog ({dog_v_sot}) = Fav ({fav_v_sot}) "
                f"— no venue SOT points awarded"
            )

        # ── A2: OPPONENT QUALITY ADJUSTMENT (FIXED — no self-cancellation) ──
        dog_opp = dog_venue["avg_opp_conceded"]
        fav_opp = fav_venue["avg_opp_conceded"]

        if dog_opp is not None and fav_opp is not None:
            if fav_opp > dog_opp:
                # Fav padded SOT vs weaker opponents — dog's SOT validated
                score += 15
                tier_a.append(
                    f"⚖️  A2 OPP STRENGTH: Fav faced weaker opponents "
                    f"(Fav opp conceded avg: {fav_opp} > Dog opp: {dog_opp}) "
                    f"→ Dog SOT validated vs tougher teams (+15)"
                )
            elif dog_opp > fav_opp:
                # Dog padded SOT vs weaker opponents
                score -= 10
                tier_a.append(
                    f"⚖️  A2 OPP STRENGTH: Dog faced weaker opponents "
                    f"(Dog opp conceded avg: {dog_opp} > Fav opp: {fav_opp}) "
                    f"→ Dog venue SOT softly discounted (-10)"
                )
            else:
                tier_a.append(
                    f"⚖️  A2 OPP STRENGTH: Equal quality "
                    f"(Dog opp: {dog_opp} | Fav opp: {fav_opp}) "
                    f"— no adjustment"
                )
        else:
            tier_a.append(
                "⚪ A2 OPP STRENGTH: Data unavailable — adjustment skipped"
            )

        # ── A3: VENUE SCORING CONSISTENCY ──────────────────────────────
        consistency_pct  = dog_venue["consistency_pct"]
        scored_count     = dog_venue["scored_count"]
        total_matches    = dog_venue["total_matches"]

        if total_matches > 0:
            if consistency_pct == 100.0:
                score += 15
                tier_a.append(
                    f"🏹 A3 CONSISTENCY BONUS: Dog scored in all "
                    f"{scored_count}/{total_matches} venue matches (100%) (+15)"
                )
            elif consistency_pct <= 50.0:
                score -= 15
                tier_a.append(
                    f"🏹 A3 CONSISTENCY PENALTY: Dog scored in only "
                    f"{scored_count}/{total_matches} venue matches "
                    f"({consistency_pct}%) (-15)"
                )
            else:
                tier_a.append(
                    f"🏹 A3 CONSISTENCY NEUTRAL: Dog scored in "
                    f"{scored_count}/{total_matches} venue matches "
                    f"({consistency_pct}%) — no points"
                )
        else:
            tier_a.append(
                "⚪ A3 CONSISTENCY: No venue match data — skipped"
            )

        # ==============================================================
        # TIER B — CONTEXTUAL BOOSTERS
        # ==============================================================

        # ── B1: CERBERUS AWAKENING (venue-locked) ─────────────────────
        # High venue SOT avg but low venue goals avg = DUE for conversion
        if dog_venue["avg_sot"] >= 3.5 and dog_venue["avg_scored"] <= 0.7:
            score += 15
            tier_b.append(
                f"🐕 B1 CERBERUS (venue): Dog venue avg SOT {dog_venue['avg_sot']} "
                f"but avg goals {dog_venue['avg_scored']} — conversion due (+15)"
            )

        # ── B2: H2H SOT EDGE ──────────────────────────────────────────
        if dog_h2h_sot is not None and fav_h2h_sot is not None:
            if dog_h2h_sot > fav_h2h_sot:
                score += 10
                tier_b.append(
                    f"🤝 B2 H2H SOT WIN: Dog ({dog_h2h_sot}) > Fav ({fav_h2h_sot}) "
                    f"in last H2H (+10)"
                )
            elif fav_h2h_sot > dog_h2h_sot:
                score -= 8
                tier_b.append(
                    f"🤝 B2 H2H SOT LOSS: Fav ({fav_h2h_sot}) > Dog ({dog_h2h_sot}) "
                    f"in last H2H (-8)"
                )
            else:
                tier_b.append(
                    f"🤝 B2 H2H SOT TIED: Dog ({dog_h2h_sot}) = Fav ({fav_h2h_sot}) "
                    f"— no points"
                )
        else:
            tier_b.append("⚪ B2 H2H SOT: No H2H data available — skipped")

        # ── B3: WOUNDED VENUE BOUNCE ───────────────────────────────────
        # Lost last venue match BUT venue SOT was still high = angry + clinical
        if dog_venue["lost_last_venue"] and dog_venue["avg_sot"] >= 3.0:
            score += 10
            tier_b.append(
                f"🩸 B3 WOUNDED BOUNCE: Dog lost last venue match but "
                f"venue avg SOT {dog_venue['avg_sot']} — angry and dangerous (+10)"
            )

        # ── B4: VENUE TRACK MEET ──────────────────────────────────────
        # Both teams scoring freely at their respective venues
        combined_venue_goals = dog_venue["avg_scored"] + fav_venue["avg_scored"]
        if combined_venue_goals > 2.5:
            score += 10
            tier_b.append(
                f"🏃 B4 VENUE TRACK MEET: Combined venue avg goals "
                f"{combined_venue_goals:.2f} > 2.5 — open game expected (+10)"
            )

        # ==============================================================
        # TIER C — NARRATIVE SIGNALS (capped at +20 collectively)
        # ==============================================================

        # ── C1: FALSE FAVORITE ────────────────────────────────────────
        is_false_fav = (
            dog_spear > fav_spear and
            dog_overall["avg_conc"] < fav_overall["avg_conc"]
        )
        if is_false_fav:
            tier_c_score += 15
            tier_c_raw.append(
                f"💎 C1 FALSE FAVORITE: Dog Spear {dog_spear}% > Fav {fav_spear}% "
                f"& better overall defense (+15)"
            )

        # ── C2: RELEGATION DESPERATION ────────────────────────────────
        if dog_pos != 99 and fav_pos != 99:
            if dog_pos >= 16 and fav_pos <= 8:
                tier_c_score += 10
                tier_c_raw.append(
                    f"🆘 C2 RELEGATION: Dog (pos {dog_pos}) fighting survival "
                    f"vs comfortable Fav (pos {fav_pos}) (+10)"
                )

        # ── C3: TERRITORIAL AGGRESSOR (venue corners) ─────────────────
        if dog_venue["corner_wins"] >= 2:
            tier_c_score += 8
            tier_c_raw.append(
                f"🚩 C3 TERRITORIAL: Dog won corners in "
                f"{dog_venue['corner_wins']}/3 venue matches (+8)"
            )

        # ── C4: REAL UNDERDOG AWAKENED ────────────────────────────────
        if is_false_fav and dog_overall["is_wounded"]:
            tier_c_score += 10
            tier_c_raw.append(
                f"🌪️  C4 REAL UNDERDOG AWAKENED: False Fav + Wounded "
                f"Dog — maximum motivation (+10)"
            )

        # Apply Tier C cap
        tier_c_applied = min(tier_c_score, 20)
        score += tier_c_applied

        if tier_c_raw:
            cap_note = (
                f" [Tier C capped at +20, raw: +{tier_c_score}]"
                if tier_c_score > 20 else ""
            )
            for r in tier_c_raw:
                tier_b.append(r)   # display under Tier C section in output
            if cap_note:
                tier_b.append(f"⚠️  TIER C CAP APPLIED{cap_note}")

        all_reasons = tier_a + tier_b
        return score, all_reasons, tier_a, tier_b

    # ==========================================================================
    # 🏆 LAYER 3 — VERDICT ENGINE
    # ==========================================================================
    def get_verdict(score):
        if score >= 50:  return "💎 LOCK (Real Underdog)"
        if score >= 30:  return "🔥 PLAY (Solid Ambush)"
        if score >= 10:  return "📊 MONITOR (Lean)"
        return               "🛑 PASS (Insufficient Evidence)"

    # ==========================================================================
    # 🚀 MAIN EXECUTION
    # ==========================================================================
    print(f"\n>> [AlienEdge U2S ENGINE v2] Hunting the Real Underdog... ({TODAY_STR})")

    if not os.path.exists(INPUT_FILE):
        print(f"🛑 FATAL: {INPUT_FILE} not found. Run Master Underdog Engine first.")
        return []

    try:
        df_in    = pd.read_csv(INPUT_FILE)
        raw_data = []
        for _, row in df_in.iterrows():
            dog_prob = float(
                str(row.get("Audit_Real_Prob", "0")).replace("%", "").strip()
            )
            fav_prob = float(
                str(row.get("Fav_Spear_Power", "0")).replace("%", "").strip()
            )
            raw_data.append({
                "fixture_name":  row.get("fixture", "Unknown"),
                "dog_name":      row.get("underdog_team", "Unknown"),
                "dog_prob":      dog_prob,
                "fav_prob":      fav_prob,
                "audit_verdict": row.get("Audit_Verdict", "Unknown")
            })
    except Exception as e:
        print(f"🛑 Error reading {INPUT_FILE}: {e}")
        return []

    # ── MAP TODAY'S API FIXTURE IDs ──────────────────────────────────────────
    todays_fixtures_map = {}
    print("   🔍 Mapping API IDs to backtest matches...")
    page = 1
    while True:
        resp = GET(
            f"/fixtures/date/{TODAY_STR}",
            params={
                "include":  "participants;league;season",
                "per_page": 50,
                "page":     page
            }
        )
        data = resp.get("data", [])
        if not data:
            break
        for fx in data:
            parts = fx.get("participants", [])
            h = next(
                (p for p in parts if p.get("meta", {}).get("location") == "home"),
                None
            )
            a = next(
                (p for p in parts if p.get("meta", {}).get("location") == "away"),
                None
            )
            if h and a:
                key = get_match_key(f"{h['name']} vs {a['name']}")
                todays_fixtures_map[key] = {
                    "fid":    fx["id"],
                    "hid":    h["id"],
                    "aid":    a["id"],
                    "lid":    fx.get("league_id"),
                    "sid":    fx.get("season_id"),
                    "h_name": h["name"],
                    "a_name": a["name"]
                }
        pagination = resp.get("pagination", {})
        if not pagination.get("has_more") and page >= pagination.get("total_pages", 1):
            break
        page += 1

    # ── PRE-FETCH ALL TEAM HISTORIES IN ONE PASS (prevents per-match bursts) ─
    print("   📦 Pre-fetching all team fixture histories...")
    for match in raw_data:
        key = get_match_key(str(match["fixture_name"]))
        if key not in todays_fixtures_map:
            continue
        fx_info = todays_fixtures_map[key]
        for tid in [fx_info["hid"], fx_info["aid"]]:
            fetch_team_fixtures(str(tid), TODAY_STR)

    # ── PROCESS EACH FIXTURE ─────────────────────────────────────────────────
    processed_list = []

    for match in raw_data:
        try:
            fix_name  = str(match["fixture_name"])
            match_key = get_match_key(fix_name)

            if match_key not in todays_fixtures_map:
                continue

            fx_info  = todays_fixtures_map[match_key]
            fid      = fx_info["fid"]
            lid      = fx_info["lid"]
            sid      = fx_info["sid"]

            dog_clean = clean_n(match["dog_name"])
            if dog_clean == clean_n(fx_info["h_name"]):
                dog_id, fav_id = str(fx_info["hid"]), str(fx_info["aid"])
                dog_venue_str  = "home"
                fav_venue_str  = "away"
            else:
                dog_id, fav_id = str(fx_info["aid"]), str(fx_info["hid"])
                dog_venue_str  = "away"
                fav_venue_str  = "home"

            dog_spear = match["dog_prob"]
            fav_spear = match["fav_prob"]

            pos_map = get_league_standings_map(lid, sid)
            dog_pos = pos_map.get(int(dog_id), 99)
            fav_pos = pos_map.get(int(fav_id), 99)

            print(f"   🔎 Analyzing {fix_name[:40]}...")

            # All venue analysis from cache — no new API calls after pre-fetch
            dog_venue = analyze_venue_last3(dog_id, dog_venue_str, fid, TODAY_STR)
            fav_venue = analyze_venue_last3(fav_id, fav_venue_str, fid, TODAY_STR)

            # Overall tactics from cache
            dog_overall = analyze_overall_last5(dog_id, fid)
            fav_overall = analyze_overall_last5(fav_id, fid)

            # H2H (one API call per unique fixture pair)
            dog_h2h_sot, fav_h2h_sot = fetch_h2h_last1_sot(dog_id, fav_id, fid)

            # ── LAYER 1: HARD GATES ──────────────────────────────────
            passed, gate_reason = run_hard_gates(dog_venue, fav_venue)

            if not passed:
                print(f"     {gate_reason}")
                processed_list.append({
                    "Fixture":                 fix_name,
                    "Underdog":                match["dog_name"],
                    "Audit_Verdict":           match["audit_verdict"],
                    "Spear_Matchup":           f"Dog: {dog_spear}% | Fav: {fav_spear}%",
                    "Dog_Venue_SOT":           dog_venue["total_sot"],
                    "Fav_Venue_SOT":           fav_venue["total_sot"],
                    "Dog_H2H_SOT":             dog_h2h_sot if dog_h2h_sot is not None else "N/A",
                    "Fav_H2H_SOT":             fav_h2h_sot if fav_h2h_sot is not None else "N/A",
                    "Dog_Opp_Avg_Conceded":    dog_venue["avg_opp_conceded"] or "N/A",
                    "Fav_Opp_Avg_Conceded":    fav_venue["avg_opp_conceded"] or "N/A",
                    "Dog_Scoring_Consistency": (
                        f"{dog_venue['consistency_pct']}% "
                        f"({dog_venue['scored_count']}/{dog_venue['total_matches']})"
                        if dog_venue["total_matches"] > 0 else "N/A"
                    ),
                    "Psych_Score":             "VETOED",
                    "Tier":                    "❌ VETOED",
                    "Triggers":                gate_reason
                })
                print(f"     > {fix_name[:35]} | ❌ VETOED | {gate_reason}")
                continue

            # ── LAYER 2: FORENSIC SCORE ──────────────────────────────
            psych_score, all_reasons, tier_a, tier_b = calculate_forensic_score(
                dog_venue     = dog_venue,
                fav_venue     = fav_venue,
                dog_overall   = dog_overall,
                fav_overall   = fav_overall,
                dog_h2h_sot   = dog_h2h_sot,
                fav_h2h_sot   = fav_h2h_sot,
                dog_spear     = dog_spear,
                fav_spear     = fav_spear,
                dog_pos       = dog_pos,
                fav_pos       = fav_pos
            )

            # ── LAYER 3: VERDICT ─────────────────────────────────────
            tier = get_verdict(psych_score)

            consistency_label = (
                f"{dog_venue['consistency_pct']}% "
                f"({dog_venue['scored_count']}/{dog_venue['total_matches']})"
                if dog_venue["total_matches"] > 0 else "N/A"
            )

            processed_list.append({
                "Fixture":                 fix_name,
                "Underdog":                match["dog_name"],
                "Audit_Verdict":           match["audit_verdict"],
                "Spear_Matchup":           f"Dog: {dog_spear}% | Fav: {fav_spear}%",
                "Dog_Venue_SOT":           dog_venue["total_sot"],
                "Fav_Venue_SOT":           fav_venue["total_sot"],
                "Dog_H2H_SOT":             dog_h2h_sot if dog_h2h_sot is not None else "N/A",
                "Fav_H2H_SOT":             fav_h2h_sot if fav_h2h_sot is not None else "N/A",
                "Dog_Opp_Avg_Conceded":    dog_venue["avg_opp_conceded"] or "N/A",
                "Fav_Opp_Avg_Conceded":    fav_venue["avg_opp_conceded"] or "N/A",
                "Dog_Scoring_Consistency": consistency_label,
                "Psych_Score":             psych_score,
                "Tier":                    tier,
                "Triggers":                " | ".join(all_reasons)
            })

            print(
                f"     > {fix_name[:35]:<35} | "
                f"Score: {psych_score:>4} | {tier}"
            )

        except Exception as exc:
            print(f"   ⚠️  Error processing {match.get('fixture_name', '?')}: {exc}")
            continue

    # ==========================================================================
    # 🖨️  FINAL OUTPUT
    # ==========================================================================
    final_table = pd.DataFrame(processed_list)
    if final_table.empty:
        print("\n>> [FATAL] No matches processed.")
        return []

    # Sort: vetoed at bottom, then by score descending
    def sort_key(row):
        s = row["Psych_Score"]
        return -999 if s == "VETOED" else -int(s)

    final_table = final_table.iloc[
        sorted(range(len(final_table)),
               key=lambda i: sort_key(final_table.iloc[i]))
    ]

    lock_df  = final_table[final_table["Tier"].str.contains("💎")]
    play_df  = final_table[final_table["Tier"].str.contains("🔥")]
    veto_df  = final_table[final_table["Tier"].str.contains("❌")]

    # ── LOCKS ────────────────────────────────────────────────────────────────
    print("\n" + "💎" * 45)
    print(" 💎  ALIENEDGE VERIFIED LOCKS: UNDERDOG TO SCORE  💎")
    print("💎" * 45)
    if not lock_df.empty:
        for i, (_, row) in enumerate(lock_df.iterrows(), 1):
            print(
                f"\n{i}. {row['Fixture']}"
                f"\n   🏆 BET: {row['Underdog']} Over 0.5 Goals"
                f"\n   Score:       {row['Psych_Score']}"
                f"\n   Base Math:   {row['Spear_Matchup']} ({row['Audit_Verdict']})"
                f"\n   Venue SOT:   Dog {row['Dog_Venue_SOT']} | Fav {row['Fav_Venue_SOT']}"
                f"\n   H2H SOT:     Dog {row['Dog_H2H_SOT']} | Fav {row['Fav_H2H_SOT']}"
                f"\n   Opp Quality: Dog opp {row['Dog_Opp_Avg_Conceded']} | Fav opp {row['Fav_Opp_Avg_Conceded']}"
                f"\n   Consistency: {row['Dog_Scoring_Consistency']}"
                f"\n   Triggers:    {row['Triggers']}"
            )
    else:
        print("\n   [!] No Locks found today.")

    # ── PLAYS ─────────────────────────────────────────────────────────────────
    print("\n" + "🔥" * 45)
    print(" 🔥  SOLID AMBUSH PLAYS  🔥")
    print("🔥" * 45)
    if not play_df.empty:
        for i, (_, row) in enumerate(play_df.iterrows(), 1):
            print(
                f"\n{i}. {row['Fixture']}"
                f"\n   🔥 BET: {row['Underdog']} Over 0.5 Goals"
                f"\n   Score:       {row['Psych_Score']}"
                f"\n   Base Math:   {row['Spear_Matchup']} ({row['Audit_Verdict']})"
                f"\n   Venue SOT:   Dog {row['Dog_Venue_SOT']} | Fav {row['Fav_Venue_SOT']}"
                f"\n   H2H SOT:     Dog {row['Dog_H2H_SOT']} | Fav {row['Fav_H2H_SOT']}"
                f"\n   Opp Quality: Dog opp {row['Dog_Opp_Avg_Conceded']} | Fav opp {row['Fav_Opp_Avg_Conceded']}"
                f"\n   Consistency: {row['Dog_Scoring_Consistency']}"
                f"\n   Triggers:    {row['Triggers']}"
            )
    else:
        print("\n   [!] No Solid Plays found today.")

    # ── VETOES ────────────────────────────────────────────────────────────────
    print("\n" + "❌" * 45)
    print(" ❌  HARD VETOED — GATES ELIMINATED THESE  ❌")
    print("❌" * 45)
    if not veto_df.empty:
        for i, (_, row) in enumerate(veto_df.iterrows(), 1):
            print(
                f"\n{i}. {row['Fixture']}"
                f"\n   🛑 VETOED: {row['Underdog']}"
                f"\n   Base Math: {row['Spear_Matchup']}"
                f"\n   Reason:    {row['Triggers']}"
            )
    else:
        print("\n   [!] No hard vetoes today.")

    # ── FULL BOARD ────────────────────────────────────────────────────────────
    print("\n" + "=" * 150)
    print("📊 FULL U2S FORENSIC BOARD")
    print("=" * 150)
    cols = [
        "Fixture", "Underdog", "Spear_Matchup",
        "Dog_Venue_SOT", "Fav_Venue_SOT",
        "Dog_H2H_SOT", "Fav_H2H_SOT",
        "Dog_Opp_Avg_Conceded", "Fav_Opp_Avg_Conceded",
        "Dog_Scoring_Consistency",
        "Psych_Score", "Tier", "Triggers"
    ]
    print(final_table[cols].to_string(index=False))

    final_table.to_csv(OUTPUT_CSV, index=False)
    print(f"\n💾 [Done] Saved to: {OUTPUT_CSV}")

    return final_table.to_dict(orient="records")


# --- LOCAL TESTING BLOCK ---
if __name__ == "__main__":
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 1000)
    run_u2s_psychology_engine()