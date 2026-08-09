import os
import sys
import time
import json
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_dna_engine_v2(target_date):
    """
    AlienEdge Commercial DNA Identity Engine — v2

    WHAT THIS ENGINE COVERS (v2 FULL INTELLIGENCE):
    ─────────────────────────────────────────────────────────────────────────────
    PILLAR 1 — CORNER POWER
        Crossing pressure + deflection friction + set-piece history.
        Answers: does this team generate corners structurally, not by luck?

    PILLAR 2 — GOAL INTENT
        Dangerous attack efficiency + shot accuracy + Big Chances Created.
        Big Chances Created is now ACTIVATED (was collected but ignored in v1).
        Answers: when this team attacks, how clinical and purposeful are they?

    PILLAR 3 — BTTS FRICTION (Chaos Index)
        Long ball usage + aggression (fouls/cards) = uncontrolled football.
        Answers: is this a messy game where both teams are likely to score?

    PILLAR 4 — WIN DOMINANCE (Suffocation Index)
        Ball possession + pressing intensity (Interceptions + Tackles ACTIVATED)
        + own passing build-up quality (now ACTIVATED, was ignored in v1).
        Answers: does this team structurally destroy opponents or just hold the ball?

    PILLAR 5 — BOX DOMINANCE (NEW in v2)
        Shots Insidebox + Big Chances Created + Dangerous Attacks combined.
        Shots Insidebox and Big Chances Created were COLLECTED BUT WASTED in v1.
        Answers: how often does this team genuinely operate inside the penalty box?
        This is the strongest non-goal predictor for Over 2.5 and GG markets.

    TACTICAL DNA (style labels)
        Tempo, Line Height, Risk Appetite, Verticality — unchanged from v1.

    SHOT QUALITY INDEX (NEW in v2)
        Insidebox vs Outsidebox ratio.
        Answers: does this team create genuine close-range danger or just
        shoot hopefully from distance?

    TRANSITION PRESSURE SCORE (NEW in v2)
        Tackles Won + Interceptions combined with dangerous attacks that follow.
        Answers: does this team win the ball AND immediately turn it into attack?

    STYLE CLASH SUMMARY (NEW in v2 — computed at fixture level)
        When two team profiles are compared, this produces a structured verdict
        on which team has a structural edge across all five pillars.
        Downstream engines (GG, Over 2.5, Win, Corners) consume this directly.

    NO NEW API CALLS — everything uses only what get_team_history_stats
    already returns from the existing Sportmonks subscription.
    ─────────────────────────────────────────────────────────────────────────────
    """

    os.makedirs(DATA_DIR, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    API_KEY          = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL         = "https://api.sportmonks.com/v3/football"
    REQUEST_DELAY    = 0.2
    HISTORY_LOOKBACK = 8       # professional forensic sample size
    LOOKBACK_DAYS    = 365
    PAGINATION_PER_PAGE = 50

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # STATS MAPPING — all stats fetched from API
    # ─────────────────────────────────────────────────────────────────────────
    DNA_STATS = [
        # Possession & passing
        "Ball Possession %",
        "Successful Passes Percentage",
        "Passes",
        "Long Passes",
        # Attacking
        "Shots Total",
        "Shots On Target",
        "Attacks",
        "Dangerous Attacks",
        "Big Chances Created",       # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Shots Insidebox",           # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Shots Outsidebox",          # v1: COLLECTED, NEVER USED — now ACTIVATED
        # Defensive / physical
        "Fouls",
        "Yellowcards",
        "Tackles",                   # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Interceptions",
        "Offsides",
        # Set pieces
        "Corners",
        "Total Crosses",
        "Blocked Shots",
        "Shots Blocked",
        # Goalkeeping
        "Saves",
        # Goals
        "Goals",
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # API WRAPPERS (UNCHANGED FROM v1 — ROBUST)
    # ─────────────────────────────────────────────────────────────────────────
    def GET(path, params=None):
        """
        Standard HTTP GET wrapper with retry logic and 429 rate-limit handling.
        No new endpoints added — same calls as v1.
        """
        if params is None:
            params = {}
        params.setdefault("api_token", API_KEY)
        url = f"{BASE_URL}{path}"

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    print(f"\n⚠️  Rate Limit! Waiting 30s... (Attempt {attempt+1})")
                    time.sleep(30)
                    continue
                else:
                    return {"data": []}
            except Exception as e:
                print(f"Network error: {e}")
                time.sleep(2)

        return {"data": []}

    def fetch_all_fixtures_for_date(date_str):
        """
        STRICT PAGINATION — loops every page to find 100% of matches for the day.
        Unchanged from v1.
        """
        all_fx = []
        page   = 1
        print(f"[1/3] Scanning master fixture list for {date_str}...")

        while True:
            params = {
                "include":   "participants;scores;league;season",
                "per_page":  50,
                "page":      page,
            }
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data", [])

            if not data:
                break

            all_fx.extend(data)

            if len(all_fx) % 100 == 0 or len(data) < 50:
                print(f"   ...Successfully retrieved {len(all_fx)} matches.")

            if len(data) < 50:
                break

            page += 1
            time.sleep(REQUEST_DELAY)

        return all_fx

    def get_team_history_stats(team_id):
        """
        Fetches the last 8 finished matches with deep statistics for a team.
        Unchanged from v1 — same endpoint, same parameters.
        """
        t_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        end_dt     = (t_date_obj - timedelta(days=1)).isoformat()
        start_dt   = (t_date_obj - timedelta(days=LOOKBACK_DAYS)).isoformat()

        params = {
            "include":  "statistics.type;participants;scores",
            "filters":  "fixtureStates:5",
            "sortBy":   "starting_at",
            "order":    "desc",
            "per_page": HISTORY_LOOKBACK,
        }
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params)
        return resp.get("data", [])

    # ─────────────────────────────────────────────────────────────────────────
    # THE TACTICAL BRAIN — UPGRADED HEURISTIC ENGINE (v2)
    # ─────────────────────────────────────────────────────────────────────────
    def calculate_comprehensive_dna(team_id, team_name, fixtures):
        """
        Turns raw match stats into full tactical DNA.

        Changes from v1:
        - Tackles now ACTIVATED in Win Dominance pressing formula
        - Big Chances Created now ACTIVATED in Goal Intent formula
        - Shots Insidebox and Outsidebox now ACTIVATED in Shot Quality Index
        - Own passing quality now ACTIVATED in Win Dominance build-up quality
        - Box Dominance Score added as fifth Market Power pillar
        - Shot Quality Index added (Insidebox vs Outsidebox ratio)
        - Transition Pressure Score added (ball recovery → attack)
        - All heuristic fallbacks preserved exactly from v1
        """
        if not fixtures:
            return None

        sums      = defaultdict(float)
        counts    = defaultdict(int)
        opp_stats = defaultdict(list)

        for fx in fixtures:
            stats = fx.get("statistics", [])

            # Find if our target team was Home or Away in this historical match
            target_loc = None
            for p in fx.get("participants", []):
                if str(p.get("id")) == str(team_id):
                    target_loc = p.get("meta", {}).get("location")
                    break

            if not target_loc:
                continue

            for s in stats:
                s_type = s.get("type", {})
                s_name = s_type.get("name") if isinstance(s_type, dict) else None
                s_val  = s.get("data", {}).get("value", 0)
                s_loc  = s.get("location")

                try:
                    val = float(str(s_val).replace('%', '').strip())

                    if s_loc == target_loc:
                        if s_name in DNA_STATS:
                            sums[s_name]   += val
                            counts[s_name] += 1
                    else:
                        # Capture opponent data for pressing and resistance metrics
                        opp_stats[s_name].append(val)
                except:
                    continue

        # ── Raw averages ──────────────────────────────────────────────────────
        avgs = {
            k: (sums[k] / counts[k] if counts[k] > 0 else 0)
            for k in DNA_STATS
        }

        # ── HEURISTIC FALLBACKS (preserved exactly from v1) ──────────────────

        # Rule 1: Estimate Blocked Shots if missing
        real_blocks = avgs.get("Blocked Shots", 0) or avgs.get("Shots Blocked", 0)
        if real_blocks == 0 and avgs.get("Shots Total", 0) > 0:
            off_target  = max(0, avgs.get("Shots Total") - avgs.get("Shots On Target"))
            real_blocks = off_target * 0.38

        # Rule 2: Estimate Total Crosses if missing
        real_crosses = avgs.get("Total Crosses", 0)
        if real_crosses == 0 and avgs.get("Dangerous Attacks", 0) > 0:
            real_crosses = (
                (avgs.get("Corners", 0) * 2.6) +
                (avgs.get("Dangerous Attacks", 0) * 0.12)
            )

        # ── OPPONENT AVERAGES (for pressing and resistance calculations) ──────
        opp_pass_acc = (
            sum(opp_stats.get("Successful Passes Percentage", [75])) /
            max(1, len(opp_stats.get("Successful Passes Percentage", [1])))
        )
        opp_dangerous_attacks = (
            sum(opp_stats.get("Dangerous Attacks", [0])) /
            max(1, len(opp_stats.get("Dangerous Attacks", [1])))
        )

        # ══════════════════════════════════════════════════════════════════════
        # MARKET POWER SCORES — v2
        # ══════════════════════════════════════════════════════════════════════

        # ── PILLAR 1: CORNER POWER ────────────────────────────────────────────
        # Formula unchanged from v1.
        # Crossing Pressure + Deflection Friction + Set-Piece History
        corner_logic = (
            (real_crosses * 2.1) +
            (real_blocks  * 1.7) +
            (avgs.get("Corners", 0) * 1.3)
        )
        corner_score = min(100, (corner_logic / 65) * 100)

        # ── PILLAR 2: GOAL INTENT ─────────────────────────────────────────────
        # v1: intent_ratio * 0.60 + shot_accuracy * 0.40
        # v2: Big Chances Created ACTIVATED — replaces pure shot-accuracy weight
        #     because Big Chances Created is the strongest non-goal attacking signal.
        #
        # Why Big Chances Created matters:
        #   A team generating 3.5 big chances per game is structurally dangerous
        #   regardless of how many they convert on a given day.
        #   v1 ignored this entirely.
        intent_ratio  = (avgs.get("Dangerous Attacks", 0) / max(1, avgs.get("Attacks", 1))) * 100
        shot_accuracy = (avgs.get("Shots On Target", 0) / max(1, avgs.get("Shots Total", 1))) * 100
        big_chances   = avgs.get("Big Chances Created", 0)

        goal_logic = (
            (intent_ratio  * 0.45) +
            (shot_accuracy * 0.30) +
            (big_chances   * 2.5 * 0.25)   # scaled: ~3 big chances = meaningful signal
        )
        goal_score = min(100, (goal_logic / 52) * 100)

        # ── PILLAR 3: BTTS FRICTION (Chaos Index) ────────────────────────────
        # Formula unchanged from v1.
        # High Long Ball usage + Aggression = Uncontrolled / Messy Football.
        verticality  = (avgs.get("Long Passes", 0) / max(1, avgs.get("Passes", 1))) * 100
        chaos_friction = (
            (verticality * 0.6) +
            (avgs.get("Fouls", 0)       * 1.8) +
            (avgs.get("Yellowcards", 0) * 4.5)
        )
        gg_score = min(100, (chaos_friction / 68) * 100)

        # ── PILLAR 4: WIN DOMINANCE (Suffocation Index) ───────────────────────
        # v1: possession * 0.4 + (Interceptions * 3.2 + 100 - opp_pass_acc) * 0.6
        # v2: THREE upgrades:
        #
        #   A. Tackles ACTIVATED in pressing intensity.
        #      Winning the ball (Tackles) + winning it in dangerous areas
        #      (Interceptions) together measure real defensive pressure.
        #      v1 had Tackles in DNA_STATS, collected them, and threw them away.
        #
        #   B. Own Passing Quality ACTIVATED as build-up measure.
        #      A team with 88% passing accuracy builds attacks with purpose.
        #      A team at 67% is playing desperately. v1 ignored own passing quality.
        #
        #   C. Opponent Dangerous Attacks resistance added.
        #      How many dangerous attacks does the opponent generate AGAINST
        #      this team? Low = this team suffocates opponents in open play.

        own_pass_quality = avgs.get("Successful Passes Percentage", 70)

        pressing_intensity = (
            (avgs.get("Interceptions", 0) * 3.2) +
            (avgs.get("Tackles", 0)       * 1.8) +   # ACTIVATED — was wasted in v1
            (100 - opp_pass_acc)
        )

        # Resistance: fewer opponent dangerous attacks = better defensive shape
        # Normalise: 30 opp dangerous attacks is a heavily pressured game
        resistance_score = max(0, 100 - (opp_dangerous_attacks * (100 / 30)))

        win_logic = (
            (avgs.get("Ball Possession %", 0) * 0.30) +
            (pressing_intensity               * 0.45) +   # Tackles now included here
            (own_pass_quality                 * 0.15) +   # ACTIVATED — was ignored in v1
            (resistance_score                 * 0.10)     # Opponent attack resistance
        )
        win_dominance = min(100, (win_logic / 82) * 100)

        # ── PILLAR 5: BOX DOMINANCE (NEW in v2) ──────────────────────────────
        # Shots Insidebox + Big Chances Created + Dangerous Attacks.
        # All three stats were COLLECTED IN v1 BUT NEVER USED.
        #
        # Why this pillar matters:
        #   Box Dominance is the strongest predictor of goal probability
        #   that doesn't require an actual goal to have been scored.
        #   A team consistently operating inside the box will eventually score
        #   regardless of short-term variance.
        #
        #   Over 2.5 and GG downstream engines benefit most from this signal.
        #   Corners engine benefits because box entries often follow a blocked
        #   shot or a failed cross that deflects for a corner.
        shots_inside  = avgs.get("Shots Insidebox", 0)
        shots_outside = avgs.get("Shots Outsidebox", 0)
        danger_attacks= avgs.get("Dangerous Attacks", 0)
        big_ch        = avgs.get("Big Chances Created", 0)

        box_logic = (
            (shots_inside  * 3.5) +
            (big_ch        * 4.2) +
            (danger_attacks * 0.8)
        )
        box_dominance_score = min(100, (box_logic / 85) * 100)

        # ══════════════════════════════════════════════════════════════════════
        # SHOT QUALITY INDEX (NEW in v2)
        # ══════════════════════════════════════════════════════════════════════
        # Insidebox vs Outsidebox ratio.
        # A team with 80% of shots from inside the box creates genuine danger.
        # A team shooting mostly from outside is hoping, not planning.
        # This directly feeds into Over 2.5 and Win confidence modifiers.
        total_located_shots = shots_inside + shots_outside
        inside_ratio = (
            (shots_inside / max(1, total_located_shots)) * 100
            if total_located_shots > 0 else 50.0   # 50% default if no data
        )
        shot_quality_label = (
            "Elite Box Threat"     if inside_ratio >= 70 else
            "Balanced Attacker"    if inside_ratio >= 50 else
            "Long Range Dependent" if inside_ratio >= 30 else
            "Speculative Shooter"
        )

        # ══════════════════════════════════════════════════════════════════════
        # TRANSITION PRESSURE SCORE (NEW in v2)
        # ══════════════════════════════════════════════════════════════════════
        # Ball recovery (Tackles + Interceptions) weighted by whether
        # recovery leads to dangerous attacks.
        # Logic: a team that wins the ball high up the pitch immediately
        # threatens the opponent — this is different from winning it deep
        # and slowly building. We can't directly measure recovery location
        # from these stats, so we use a proxy:
        #   High Tackles + High Interceptions + High Dangerous Attacks
        #   = team that wins ball AND immediately pressures.
        #
        # This feeds Win Dominance indirectly but is also exposed as a
        # standalone signal for downstream engines that care about tempo.
        ball_recovery   = avgs.get("Tackles", 0) + avgs.get("Interceptions", 0)
        transition_raw  = (ball_recovery * 1.6) + (danger_attacks * 0.9)
        transition_score = min(100, (transition_raw / 75) * 100)

        transition_label = (
            "High Press / Fast Transition" if transition_score >= 72 else
            "Structured Recovery"          if transition_score >= 48 else
            "Passive / Reactive"
        )

        # ══════════════════════════════════════════════════════════════════════
        # TACTICAL LABELLING (unchanged from v1)
        # ══════════════════════════════════════════════════════════════════════
        tempo_raw   = (avgs.get("Passes", 0) * 0.3) + (avgs.get("Attacks", 0) * 0.7)
        tempo_score = min(100, (tempo_raw / 640) * 100)

        line_height_raw = (
            (avgs.get("Offsides", 0)      * 15) +
            (avgs.get("Interceptions", 0) *  2)
        )

        archetype = "Balanced"
        if corner_score > 78:
            archetype = "Set-Piece Specialist (CORNERS)"
        elif goal_score > 78 and win_dominance > 68:
            archetype = "Elite Dominator (WIN/OVER)"
        elif gg_score > 72:
            archetype = "High-Friction Chaos (GG/OVER)"
        elif avgs.get("Ball Possession %", 0) > 60:
            archetype = "Possession Controller (DRAW/UNDER)"
        elif avgs.get("Fouls", 0) > 16:
            archetype = "Aggressive Disruptor (CARDS)"
        elif box_dominance_score > 75:
            archetype = "Box Predator (OVER/GG)"   # new archetype, only reachable in v2

        # ══════════════════════════════════════════════════════════════════════
        # ASSEMBLED PROFILE — returned to main loop and saved to JSON
        # ══════════════════════════════════════════════════════════════════════
        return {
            "team_name": team_name,
            "Archetype": archetype,

            # ── Five market power pillars ──────────────────────────────────
            "Market_Power_Scores": {
                "Corner_Power":    round(corner_score,        1),
                "Goal_Intent":     round(goal_score,          1),
                "BTTS_Friction":   round(gg_score,            1),
                "Win_Dominance":   round(win_dominance,       1),
                "Box_Dominance":   round(box_dominance_score, 1),   # NEW
            },

            # ── Tactical style labels ──────────────────────────────────────
            "Tactical_DNA": {
                "Tempo":               round(tempo_score, 1),
                "Line_Height":         "High"   if line_height_raw > 45 else
                                       "Medium" if line_height_raw > 25 else "Low",
                "Risk_Appetite":       "High" if shot_accuracy > 40 else "Low",
                "Verticality":         "Direct" if verticality > 16 else "Horizontal",
                "Shot_Quality":        shot_quality_label,          # NEW
                "Transition_Style":    transition_label,             # NEW
                "Transition_Score":    round(transition_score, 1),  # NEW
            },

            # ── Raw audit metrics exposed for downstream engines ───────────
            "Raw_Audit_Metrics": {
                "Avg_Corners":             round(avgs.get("Corners",                     0), 1),
                "Estimated_Crosses":       round(real_crosses,                               1),
                "Estimated_Blocks":        round(real_blocks,                                1),
                "Dangerous_Attacks":       round(avgs.get("Dangerous Attacks",          0), 1),
                "Passing_Control":         round(avgs.get("Successful Passes Percentage",0), 1),
                # Previously wasted — now surfaced
                "Big_Chances_Created":     round(avgs.get("Big Chances Created",         0), 1),
                "Shots_Insidebox":         round(avgs.get("Shots Insidebox",             0), 1),
                "Shots_Outsidebox":        round(avgs.get("Shots Outsidebox",            0), 1),
                "Inside_Shot_Ratio_Pct":   round(inside_ratio,                              1),
                "Tackles_Avg":             round(avgs.get("Tackles",                     0), 1),
                "Interceptions_Avg":       round(avgs.get("Interceptions",               0), 1),
                "Own_Pass_Quality_Pct":    round(own_pass_quality,                          1),
                "Opp_Pass_Acc_Allowed":    round(opp_pass_acc,                              1),
                "Opp_Dangerous_Attacks":   round(opp_dangerous_attacks,                     1),
                "Resistance_Score":        round(resistance_score,                          1),
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # FIXTURE-LEVEL STYLE CLASH (NEW in v2)
    # ─────────────────────────────────────────────────────────────────────────
    def compute_style_clash(home_profile, away_profile, home_name, away_name):
        """
        Compares two DNA profiles head-to-head across all five pillars
        and produces a structured clash verdict.

        This is what downstream engines (GG, Over 2.5, Win, Corners) consume
        to understand the structural matchup between the two teams — not just
        individual team quality.

        No new API call — uses only the already-computed profiles.
        """
        if not home_profile or not away_profile:
            return None

        home_scores = home_profile.get("Market_Power_Scores", {})
        away_scores = away_profile.get("Market_Power_Scores", {})

        pillars = ["Corner_Power", "Goal_Intent", "BTTS_Friction", "Win_Dominance", "Box_Dominance"]

        clash = {}
        home_edge_count = 0
        away_edge_count = 0

        for pillar in pillars:
            h = home_scores.get(pillar, 0)
            a = away_scores.get(pillar, 0)
            diff = round(h - a, 1)

            if diff > 5:
                edge    = home_name
                margin  = "Clear"
                home_edge_count += 1
            elif diff < -5:
                edge    = away_name
                margin  = "Clear"
                away_edge_count += 1
            else:
                edge   = "Neutral"
                margin = "Tight"

            clash[pillar] = {
                "home_score": h,
                "away_score": a,
                "difference": diff,
                "edge":       edge,
                "margin":     margin,
            }

        # Combined offensive threat — feeds Over 2.5 and GG engines directly
        combined_box_dominance  = (
            home_scores.get("Box_Dominance", 0) +
            away_scores.get("Box_Dominance", 0)
        ) / 2

        combined_goal_intent = (
            home_scores.get("Goal_Intent", 0) +
            away_scores.get("Goal_Intent", 0)
        ) / 2

        # Overall structural advantage
        if home_edge_count > away_edge_count + 1:
            overall_edge = home_name
        elif away_edge_count > home_edge_count + 1:
            overall_edge = away_name
        else:
            overall_edge = "Contested"

        # Market signals derived from clash
        over_signal = (
            "STRONG OVER" if combined_box_dominance > 70 and combined_goal_intent > 65 else
            "LEAN OVER"   if combined_box_dominance > 55 or  combined_goal_intent > 55  else
            "LEAN UNDER"  if combined_box_dominance < 40 and combined_goal_intent < 40  else
            "NEUTRAL"
        )

        gg_signal = (
            "STRONG GG"  if clash.get("BTTS_Friction", {}).get("home_score", 0) > 65 and
                            clash.get("BTTS_Friction", {}).get("away_score", 0) > 55 else
            "LEAN GG"    if combined_box_dominance > 60 else
            "LEAN NO GG" if combined_box_dominance < 40 else
            "NEUTRAL"
        )

        corners_signal = (
            "HIGH CORNERS" if clash.get("Corner_Power", {}).get("home_score", 0) > 70 or
                              clash.get("Corner_Power", {}).get("away_score", 0) > 70 else
            "AVERAGE"
        )

        return {
            "fixture":                  f"{home_name} vs {away_name}",
            "home_team":                home_name,
            "away_team":                away_name,
            "pillar_clash":             clash,
            "home_pillar_edges":        home_edge_count,
            "away_pillar_edges":        away_edge_count,
            "overall_structural_edge":  overall_edge,
            "combined_box_dominance":   round(combined_box_dominance,  1),
            "combined_goal_intent":     round(combined_goal_intent,     1),
            "market_signals": {
                "Over_Under":   over_signal,
                "GG_NoGG":      gg_signal,
                "Corners":      corners_signal,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN EXECUTION LOOP
    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 — fetch all fixtures for the date (same as v1, with pagination)
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        print("❌ CRITICAL: No fixtures returned from API. Check key or date.")
        return {}

    # Step 2 — collect unique teams AND fixture pairings
    unique_teams   = {}
    fixture_pairs  = []    # NEW: used for style clash computation

    for fx in fixtures:
        participants = fx.get("participants", [])
        pair = []
        for p in participants:
            if p.get("id"):
                unique_teams[p["id"]] = p["name"]
                pair.append({"id": p["id"], "name": p["name"],
                              "location": p.get("meta", {}).get("location")})
        if len(pair) == 2:
            # Ensure home is first, away is second
            home = next((t for t in pair if t.get("location") == "home"), pair[0])
            away = next((t for t in pair if t.get("location") == "away"), pair[1])
            fixture_pairs.append({
                "fixture_id":   fx.get("id"),
                "fixture_date": fx.get("starting_at", target_date)[:10],
                "home":         home,
                "away":         away,
            })

    print(f"[2/3] Identity Check: Found {len(unique_teams)} teams across "
          f"{len(fixture_pairs)} fixtures to profile.")

    # Step 3 — compute DNA for every team
    dna_profiles = {}
    count = 1

    for team_id, team_name in unique_teams.items():
        print(f"   ({count}/{len(unique_teams)}) Processing DNA: {team_name}...",
              end=" ", flush=True)

        match_history = get_team_history_stats(team_id)
        profile       = calculate_comprehensive_dna(team_id, team_name, match_history)

        if profile:
            dna_profiles[str(team_id)] = profile
            print("Done ✅")
        else:
            print("Skipped (No Stats) ⚠️")

        count += 1
        time.sleep(REQUEST_DELAY)

    # Step 4 — compute style clashes for every fixture (NEW in v2)
    print("\n[2.5/3] Computing fixture-level style clashes...")
    fixture_clashes = []

    for fp in fixture_pairs:
        h_id      = str(fp["home"]["id"])
        a_id      = str(fp["away"]["id"])
        h_profile = dna_profiles.get(h_id)
        a_profile = dna_profiles.get(a_id)
        clash     = compute_style_clash(
            h_profile, a_profile,
            fp["home"]["name"], fp["away"]["name"]
        )
        if clash:
            clash["fixture_id"]   = fp["fixture_id"]
            clash["fixture_date"] = fp["fixture_date"]
            fixture_clashes.append(clash)
            print(f"   ✅ Clash: {clash['fixture']} → Edge: {clash['overall_structural_edge']}")

    # Step 5 — save DNA profiles (NEW v2-specific path — v1 file is never touched)
    output_path = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    print(f"\n[3/3] Saving DNA library to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dna_profiles, f, indent=4)

    # Step 6 — save style clashes (NEW — separate file, no v1 file overwritten)
    clashes_path = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
    print(f"[3/3] Saving style clashes to {clashes_path}...")
    with open(clashes_path, "w", encoding="utf-8") as f:
        json.dump(fixture_clashes, f, indent=4)

    print("\n" + "=" * 60)
    print(f"🏆 ALIENEDGE DNA ENGINE v2: COMPLETE ({target_date})")
    print(f"   Teams profiled:      {len(dna_profiles)}")
    print(f"   Fixture clashes:     {len(fixture_clashes)}")
    print(f"   New pillars active:  Box Dominance, Shot Quality, Transition Pressure")
    print(f"   Previously wasted:   Tackles, Big Chances Created, Shots Insidebox,")
    print(f"                        Shots Outsidebox — ALL NOW ACTIVATED")
    print("=" * 60)

    # Return both to Master Aggregator memory
    return {
        "dna_profiles":     dna_profiles,
        "fixture_clashes":  fixture_clashes,
    }


# Allow local testing
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_dna_engine_v2(today_date)
