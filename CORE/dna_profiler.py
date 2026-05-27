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
def run_dna_profiler(target_date):
    """
    Executes the Commercial DNA Identity Engine.
    Math, heuristics, and logic are 100% untouched.
    """
    # Ensure data directory exists safely
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # -------------------------
    # CONFIGURATION
    # -------------------------
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"

    # Professional Settings
    REQUEST_DELAY = 0.2
    HISTORY_LOOKBACK = 8        # Professional forensic sample size
    LOOKBACK_DAYS = 365         # Date range to find the 8 matches
    PAGINATION_PER_PAGE = 50    
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return {}

    # -------------------------
    # COMMERCIAL STATS MAPPING
    # -------------------------
    DNA_STATS =[
        "Ball Possession %", "Successful Passes Percentage", "Passes", "Long Passes",
        "Shots Total", "Shots On Target", "Attacks", "Dangerous Attacks", 
        "Fouls", "Yellowcards", "Tackles", "Interceptions", "Offsides", 
        "Big Chances Created", "Corners", "Total Crosses", "Blocked Shots", 
        "Shots Blocked", "Saves", "Shots Insidebox", "Shots Outsidebox", "Goals"
    ]

    # -------------------------
    # API WRAPPERS (ROBUST)
    # -------------------------
    def GET(path, params=None):
        """
        Standard HTTP GET wrapper with retry logic and 429 (Rate Limit) handling.
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
                    # Wait 30 seconds if rate limit is hit
                    print(f"\n⚠️  Rate Limit! Waiting 30s... (Attempt {attempt+1})")
                    time.sleep(30)
                    continue
                else:
                    # Other error (401, 404, etc) - return empty
                    return {"data":[]}
            except Exception as e:
                print(f"Network error: {e}")
                time.sleep(2)
                
        return {"data":[]}

    def fetch_all_fixtures_for_date(date_str):
        """
        STRICT PAGINATION: IMPLEMENTED FROM MASTER ENGINE
        Loops through every page to find 100% of matches for the day.
        """
        all_fx =[]
        page = 1
        print(f"[1/3] Scanning master fixture list for {date_str}...")
        
        while True:
            params = {
                "include": "participants;scores;league;season",
                "per_page": 50,
                "page": page
            }
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data",[])
            
            if not data:
                break
                
            all_fx.extend(data)
            
            # Log progress every 100 matches
            if len(all_fx) % 100 == 0 or len(data) < 50:
                print(f"   ...Successfully retrieved {len(all_fx)} matches.")

            # Master Engine Break Condition
            if len(data) < 50:
                break
                
            page += 1
            time.sleep(REQUEST_DELAY)
            
        return all_fx

    def get_team_history_stats(team_id):
        """
        Fetches the last 8 finished matches with deep statistics for a specific team.
        (Adapted to respect target_date for historical backtesting accuracy)
        """
        # Map to the target_date passed by the Master Aggregator
        t_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        
        end_dt = (t_date_obj - timedelta(days=1)).isoformat()
        start_dt = (t_date_obj - timedelta(days=LOOKBACK_DAYS)).isoformat()
        
        params = {
            "include": "statistics.type;participants;scores",
            "filters": "fixtureStates:5",
            "sortBy": "starting_at",
            "order": "desc",
            "per_page": HISTORY_LOOKBACK
        }
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params)
        return resp.get("data",[])

    # -------------------------
    # THE TACTICAL BRAIN (HEURISTIC ENGINE)
    # -------------------------
    def calculate_comprehensive_dna(team_id, team_name, fixtures):
        """
        Core Logic: Turns raw match stats into tactical DNA pillars.
        Includes fallback logic (Heuristics) for missing data fields.
        """
        if not fixtures: 
            return None

        sums = defaultdict(float)
        counts = defaultdict(int)
        opp_stats = defaultdict(list)

        for fx in fixtures:
            stats = fx.get("statistics",[])
            
            # Find if our target team was Home or Away in this historical match
            target_loc = None
            for p in fx.get("participants",[]):
                if str(p.get("id")) == str(team_id):
                    target_loc = p.get("meta", {}).get("location")
                    break
            
            if not target_loc: 
                continue

            for s in stats:
                s_type = s.get("type", {})
                s_name = s_type.get("name") if isinstance(s_type, dict) else None
                s_val = s.get("data", {}).get("value", 0)
                s_loc = s.get("location")
                
                try:
                    # Clean strings like '65%' to floats like 65.0
                    val = float(str(s_val).replace('%', '').strip())
                    
                    if s_loc == target_loc:
                        if s_name in DNA_STATS:
                            sums[s_name] += val
                            counts[s_name] += 1
                    else:
                        # Capture opponent data to measure Pressing/Resistance
                        opp_stats[s_name].append(val)
                except: 
                    continue

        # Calculate raw averages
        avgs = {k: (sums[k] / counts[k] if counts[k] > 0 else 0) for k in DNA_STATS}
        
        # ---------------------------------------------------------
        # HEURISTIC FALLBACKS (The "Intelligence" Layer)
        # ---------------------------------------------------------
        # Rule 1: If "Blocked Shots" is missing, estimate based on off-target shots.
        # Pro teams usually have ~35% of their non-SOT shots blocked.
        real_blocks = avgs.get("Blocked Shots", 0) or avgs.get("Shots Blocked", 0)
        if real_blocks == 0 and avgs.get("Shots Total", 0) > 0:
            off_target = max(0, avgs.get("Shots Total") - avgs.get("Shots On Target"))
            real_blocks = off_target * 0.38 # 38% deflection proxy
        
        # Rule 2: If "Total Crosses" is missing, estimate based on Corners and Dangerous Attacks.
        # Logic: High Corners + High Dangerous Attacks = High Wing Play.
        real_crosses = avgs.get("Total Crosses", 0)
        if real_crosses == 0 and avgs.get("Dangerous Attacks", 0) > 0:
            # A corner usually implies 2-3 previous crosses. Dangerous attacks represent box entries.
            real_crosses = (avgs.get("Corners", 0) * 2.6) + (avgs.get("Dangerous Attacks", 0) * 0.12)

        # ---------------------------------------------------------
        # MARKET POWER SCORES
        # ---------------------------------------------------------

        # PILLAR 1: CORNER POWER (Commercial Audit)
        # Formula: Crossing Pressure + Deflection Friction + Set-Piece History
        corner_logic = (real_crosses * 2.1) + (real_blocks * 1.7) + (avgs.get("Corners", 0) * 1.3)
        corner_score = min(100, (corner_logic / 65) * 100)

        # PILLAR 2: GOAL INTENT (Over 2.5 & Win Audit)
        # Efficiency of turning general attacks into dangerous ones + Finishing accuracy.
        intent_ratio = (avgs.get("Dangerous Attacks", 0) / max(1, avgs.get("Attacks", 1))) * 100
        shot_accuracy = (avgs.get("Shots On Target", 0) / max(1, avgs.get("Shots Total", 1))) * 100
        goal_logic = (intent_ratio * 0.60) + (shot_accuracy * 0.40)
        goal_score = min(100, (goal_logic / 52) * 100)

        # PILLAR 3: BTTS FRICTION (The Chaos Index)
        # High Long Ball usage + Aggression (Fouls/Cards) = Uncontrolled/Messy Football.
        verticality = (avgs.get("Long Passes", 0) / max(1, avgs.get("Passes", 1))) * 100
        chaos_friction = (verticality * 0.6) + (avgs.get("Fouls", 0) * 1.8) + (avgs.get("Yellowcards", 0) * 4.5)
        gg_score = min(100, (chaos_friction / 68) * 100)

        # PILLAR 4: WIN DOMINANCE (Suffocation Index)
        # Can they keep the ball and destroy the opponent's passing?
        opp_pass_acc = sum(opp_stats.get("Successful Passes Percentage", [75])) / len(opp_stats.get("Successful Passes Percentage", [1]))
        pressing_intensity = (avgs.get("Interceptions", 0) * 3.2) + (100 - opp_pass_acc)
        win_logic = (avgs.get("Ball Possession %", 0) * 0.4) + (pressing_intensity * 0.6)
        win_dominance = min(100, (win_logic / 82) * 100)

        # ---------------------------------------------------------
        # TACTICAL LABELLING
        # ---------------------------------------------------------
        tempo_raw = (avgs.get("Passes", 0) * 0.3) + (avgs.get("Attacks", 0) * 0.7)
        tempo_score = min(100, (tempo_raw / 640) * 100)
        
        line_height_raw = (avgs.get("Offsides", 0) * 15) + (avgs.get("Interceptions", 0) * 2)
        
        # Final Archetype Assignment
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

        return {
            "team_name": team_name,
            "Archetype": archetype,
            "Market_Power_Scores": {
                "Corner_Power": round(corner_score, 1),
                "Goal_Intent": round(goal_score, 1),
                "BTTS_Friction": round(gg_score, 1),
                "Win_Dominance": round(win_dominance, 1)
            },
            "Tactical_DNA": {
                "Tempo": round(tempo_score, 1),
                "Line_Height": "High" if line_height_raw > 45 else "Medium" if line_height_raw > 25 else "Low",
                "Risk_Appetite": "High" if shot_accuracy > 40 else "Low",
                "Verticality": "Direct" if verticality > 16 else "Horizontal"
            },
            "Raw_Audit_Metrics": {
                "Avg_Corners": round(avgs.get("Corners", 0), 1),
                "Estimated_Crosses": round(real_crosses, 1),
                "Estimated_Blocks": round(real_blocks, 1),
                "Dangerous_Attacks": round(avgs.get("Dangerous Attacks", 0), 1),
                "Passing_Control": round(avgs.get("Successful Passes Percentage", 0), 1)
            }
        }

    # -------------------------
    # MAIN EXECUTION LOOP
    # -------------------------
    # 1. Fetch all matches (IMPLEMENTED MASTER PAGINATION)
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        print("❌ CRITICAL: No fixtures returned from API. Check key or date.")
        return {}
    
    # 2. Collect all unique team IDs to process
    unique_teams = {}
    for fx in fixtures:
        for p in fx.get("participants", []):
            if p.get('id'):
                unique_teams[p['id']] = p['name']
                
    print(f"[2/3] Identity Check: Found {len(unique_teams)} teams to profile.")

    # 3. Process each team one by one
    dna_profiles = {}
    count = 1
    for team_id, team_name in unique_teams.items():
        print(f"   ({count}/{len(unique_teams)}) Processing DNA: {team_name}...", end=" ", flush=True)
        
        # Step A: Get 8-match historical data
        match_history = get_team_history_stats(team_id)
        
        # Step B: Pass to DNA Engine
        profile = calculate_comprehensive_dna(team_id, team_name, match_history)
        
        if profile:
            dna_profiles[str(team_id)] = profile
            print("Done ✅")
        else:
            print("Skipped (No Stats) ⚠️")
        
        count += 1
        time.sleep(REQUEST_DELAY)

    # 4. Final Save to Library inside the DATA folder
    output_path = os.path.join(DATA_DIR, "team_dna_profiles.json")
    print(f"[3/3] Saving DNA library to {output_path}...")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dna_profiles, f, indent=4)

    print("\n" + "="*60)
    print(f"🏆 COMMERCIAL DNA IDENTITY ENGINE: COMPLETE ({target_date})")
    print(f"Handled {len(dna_profiles)} profiles with Tactical Heuristics.")
    print("="*60)
    
    # Return it to the Master Aggregator memory just in case
    return dna_profiles

# Allow local testing if someone presses "Run" on this specific file
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_dna_profiler(today_date)