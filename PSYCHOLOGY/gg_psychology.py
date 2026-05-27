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
# This ensures the aggregator finds the files in the correct folders
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_gg_psychology_engine(target_date=None):
    """
    Executes the AlienEdge GG Psychology Engine.
    Reads from the Monte Carlo Aggregator and applies strict forensic filters.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    # ==============================================================================
    # 1. CONFIGURATION & SETUP
    # ==============================================================================
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return[]

    BASE_URL = "https://api.sportmonks.com/v3/football"

    # Listen to main.py for the date, otherwise use today
    if not target_date:
        TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        TODAY_STR = target_date

    # --- DYNAMIC FILE PATHING ---
    # INPUT: Reads directly from your small Monte Carlo aggregator inside the output folder
    INPUT_FILE = os.path.join(OUTPUT_DIR, f"JUDGED_GG_PICKS_{TODAY_STR}.csv")
    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")

    # OUTPUT: Feeds into your FINAL Aggregator
    OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_GG_PSYCHOLOGY_FINAL_{TODAY_STR}.csv")

    logging.basicConfig(level=logging.INFO, format='%(asctime)s -[GG PSYCHOLOGY] - %(message)s')

    # ==============================================================================
    # 🛡️ BULLETPROOF API HELPER & CACHE SYSTEM
    # ==============================================================================
    API_CACHE = {}
    STANDINGS_CACHE = {}
    REQUEST_DELAY = 0.2

    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)

        cache_key = path + "?" + "&".join([f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"])
        if cache_key in API_CACHE: return API_CACHE[cache_key]

        backoff = 2.0
        for attempt in range(5):
            try:
                resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    API_CACHE[cache_key] = data
                    time.sleep(REQUEST_DELAY)
                    return data
                elif resp.status_code == 429:
                    time.sleep(backoff)
                    backoff *= 1.5
                    continue
                else: return {"data":[]}
            except Exception:
                time.sleep(1)
                continue
        return {"data":[]}

    def clean_n(name):
        n = str(name).lower()
        for word in["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n = clean_n(name)
        parts = n.split('vs') if 'vs' in n else[n]
        parts = [p.strip() for p in parts]
        parts.sort()
        return "".join(parts)

    # ==============================================================================
    # 📊 LEAGUE STANDINGS (FOR DESPERATION & MID-TABLE LOGIC)
    # ==============================================================================
    def get_league_standings_map(league_id, season_id):
        if not league_id or league_id == "Unknown" or not season_id: return {}
        cache_key = f"{league_id}_{season_id}"
        if cache_key in STANDINGS_CACHE: return STANDINGS_CACHE[cache_key]

        standings_resp = GET(f"/standings/seasons/{season_id}", params={"filters": f"standingLeagues:{league_id}"})
        pos_map = {int(s["participant_id"]): int(s["position"]) for s in standings_resp.get("data",[]) if s.get("participant_id") and s.get("position")}
        STANDINGS_CACHE[cache_key] = pos_map
        return pos_map

    # ==============================================================================
    # 📊 GOAL & STAT EXTRACTORS
    # ==============================================================================
    def extract_goals_by_period(fx, period="FT"):
        home_g, away_g = None, None
        for entry in fx.get("scores",[]):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            desc = str(entry.get("description", s_obj.get("description", ""))).upper()
            
            if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]): continue
            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")
            
            if g is not None:
                try:
                    val = int(g)
                    if period == "FT":
                        if p == "home": home_g = max(home_g or 0, val)
                        elif p == "away": away_g = max(away_g or 0, val)
                    elif period == "HT":
                        if "1ST" in desc or "HT" in desc or "HALF" in desc:
                            if p == "home": home_g = max(home_g or 0, val)
                            elif p == "away": away_g = max(away_g or 0, val)
                except: pass
        return home_g, away_g

    def get_team_and_opp_goals(fx, team_id, period="FT"):
        hg, ag = extract_goals_by_period(fx, period)
        if hg is None or ag is None: return None, None
        for p in fx.get("participants",[]):
            if str(p.get("id")) == str(team_id):
                if (p.get("meta") or {}).get("location") == "home": return hg, ag
                if (p.get("meta") or {}).get("location") == "away": return ag, hg
        local = fx.get("localteam_id") or fx.get("localteam") or fx.get("local_team_id")
        if str(local) == str(team_id): return hg, ag
        return ag, hg

    def get_match_outcome(fx, team_id):
        tg, og = get_team_and_opp_goals(fx, team_id, "FT")
        if tg is None or og is None: return None
        if tg > og: return "W"
        if tg < og: return "L"
        return "D"

    def extract_stat_value(fx, team_id, stat_names):
        entries = fx.get("statistics",[])
        if isinstance(entries, dict): entries = entries.get(str(team_id),[])
        else: entries =[s for s in entries if str(s.get('participant_id', '')) == str(team_id)]
        for s in entries:
            t_name = str(s.get("type", {}).get("name", s.get("name", ""))).upper()
            if any(name.upper() in t_name for name in stat_names):
                val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
                try: return float(val)
                except: pass
        return 0.0

    # ==============================================================================
    # 🧠 GG TACTICS ENGINE (Mutual Destruction Profiler)
    # ==============================================================================
    def analyze_gg_tactics(team_id, opp_id, current_match_id):
        end_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_dt = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
        
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", 
                   params={"include": "statistics.type;participants;scores", "per_page": 15, "order":"desc", "filter": "fixtureStates:5"})
        
        fixtures =[f for f in resp.get("data", []) if str(f.get('id')) != str(current_match_id)]
        last_5 = fixtures[:5]
        
        if not last_5:
            return {
                "avg_conc": 1.0, "avg_sot": 0.0, "avg_bcc": 0.0, "cs_last_5": 0, "btts_count": 0,
                "is_ht_vulnerable": False, "is_ht_killer": False, "is_possession_heavy": False,
                "is_wounded": False, "is_clinical": False, "is_comeback_dog": False, "is_glass_jaw": False
            }

        sot_list =[extract_stat_value(f, team_id,["Shots On Target"]) for f in last_5]
        bcc_list =[extract_stat_value(f, team_id, ["Big Chances"]) for f in last_5]
        poss_list =[extract_stat_value(f, team_id,["Ball Possession"]) for f in last_5]
        
        avg_sot = sum(sot_list) / len(sot_list) if sot_list else 0.0
        avg_bcc = sum(bcc_list) / len(bcc_list) if bcc_list else 0.0
        avg_poss = sum(poss_list) / len(poss_list) if poss_list else 50.0

        conceded_list =[]
        ht_conceded_count, ht_scored_count, btts_count, cs_count = 0, 0, 0, 0
        
        for f in last_5:
            tg, og = get_team_and_opp_goals(f, team_id, "FT")
            if og is not None: conceded_list.append(og)
            if og == 0: cs_count += 1
            if tg is not None and og is not None and tg > 0 and og > 0: btts_count += 1
                
            ht_tg, ht_og = get_team_and_opp_goals(f, team_id, "HT")
            if ht_og is not None and ht_og > 0: ht_conceded_count += 1
            if ht_tg is not None and ht_tg > 0: ht_scored_count += 1

        avg_conc = sum(conceded_list) / len(conceded_list) if conceded_list else 1.0

        # Wounded Beast Logic (Form + H2H)
        outcomes =[get_match_outcome(f, team_id) for f in last_5[:2]]
        shock_loss = (len(outcomes) > 0 and outcomes[0] == "L")
        winless_2 = (len(outcomes) == 2 and "W" not in outcomes)
        
        h2h_data = GET(f"/fixtures/head-to-head/{team_id}/{opp_id}", params={"include":"scores;participants", "per_page": 2, "order":"desc"})
        past_h2h =[h for h in h2h_data.get("data", []) if str(h.get('id')) != str(current_match_id) and h.get('state_id') == 5]
        h2h_hum = (past_h2h and get_match_outcome(past_h2h[0], team_id) == "L")
        
        is_wounded = (shock_loss or winless_2 or h2h_hum)

        return {
            "avg_conc": round(avg_conc, 2), "avg_sot": round(avg_sot, 1), "avg_bcc": round(avg_bcc, 1),
            "cs_last_5": cs_count, "btts_count": btts_count,
            "is_ht_vulnerable": (ht_conceded_count >= 3), "is_ht_killer": (ht_scored_count >= 3),
            "is_possession_heavy": (avg_poss > 58.0 and avg_sot < 3.5), "is_wounded": is_wounded,
            "is_clinical": (avg_sot >= 4.5 and avg_bcc >= 1.5), "is_comeback_dog": (btts_count >= 3 and avg_sot >= 3.5),
            "is_glass_jaw": (avg_conc > 1.5)
        }

    # ==============================================================================
    # ⚖️ THE ALIENEDGE GG RULES ENGINE (Mutual Destruction)
    # ==============================================================================
    def calculate_gg_score(h, a, h_spear, a_spear, h_pos, a_pos):
        score = 0
        reasons =[]

        ud_spear = min(h_spear, a_spear)
        fav_spear = max(h_spear, a_spear)
        spear_gap = fav_spear - ud_spear

        is_h_dog = (ud_spear == h_spear)
        dog_traits = h if is_h_dog else a
        fav_traits = a if is_h_dog else h
        is_fav_away = is_h_dog

        # 🛑 VETOES
        if spear_gap > 35.0: score -= 30; reasons.append(f"🛑 Massacre Trap (Gap: {round(spear_gap)}%)")
        if h['avg_conc'] < 0.80 or a['avg_conc'] < 0.80: score -= 30; reasons.append("🧱 Lone Brick Wall (Elite Defense)")
        if dog_traits['avg_sot'] < 3.0 or dog_traits['avg_bcc'] < 1.0: score -= 25; reasons.append("🚨 Toothless Dog (Can't shoot)")
        if h['is_possession_heavy'] and a['is_possession_heavy']: score -= 20; reasons.append("💤 Tiki-Taka Trap")

        # 💎 BOOSTS
        if ud_spear >= 70.0: score += 20; reasons.append(f"💎 GG HOLY GRAIL (UD Spear {ud_spear}%)")
        if h['is_glass_jaw'] and a['is_glass_jaw']: score += 20; reasons.append("🔨 Mutual Glass Jaw")
        if h['cs_last_5'] == 0 and a['cs_last_5'] == 0: score += 15; reasons.append("🔓 Clean Sheet Virgins")
        if h['is_ht_vulnerable'] and a['is_ht_vulnerable']: score += 15; reasons.append("⏱️ Early Exchange Vulnerability")
        if h['btts_count'] >= 3 and a['btts_count'] >= 3: score += 15; reasons.append("🔥 BTTS Streak")

        # 🚀 PSYCHOLOGICAL UPGRADES
        if h['is_wounded'] and a['is_wounded'] and h['is_glass_jaw'] and a['is_glass_jaw'] and ud_spear >= 50.0:
            score += 25; reasons.append("🌪️ MUTUAL WOUNDED CHAOS")
        if is_fav_away and fav_traits['is_wounded']: score += 15; reasons.append("🩸 Wounded Away Fav (Panicked attacks)")
        if (h['is_ht_killer'] and h['is_glass_jaw'] and a['is_ht_vulnerable']) or \
           (a['is_ht_killer'] and a['is_glass_jaw'] and h['is_ht_vulnerable']):
            score += 15; reasons.append("🎯 First Strike / Glass Jaw Synergy")
        if dog_traits['is_comeback_dog']: score += 15; reasons.append("🐾 Resilient Comeback Dog")
        if (fav_traits['is_clinical'] and dog_traits['cs_last_5'] == 0) or \
           (dog_traits['is_clinical'] and fav_traits['cs_last_5'] == 0):
            score += 15; reasons.append("🏹 Sniper vs No Goalkeeper Synergy")

        # ⚖️ MOTIVATION LAYER
        if h_pos != 99 and a_pos != 99:
            if 8 <= h_pos <= 13 and 8 <= a_pos <= 13: score += 10; reasons.append("🎭 Nothing to Lose (Mid-table clash)")
            elif h_pos >= 15 and a_pos >= 15: score += 10; reasons.append("🆘 Desperate Equalizer (Relegation battle)")

        if not reasons: reasons.append("Neutral Profile")
        return score, reasons

    # ==============================================================================
    # 🚀 MAIN EXECUTION (INSIDE WRAPPER)
    # ==============================================================================
    print(f"\n>>[AlienEdge GG PSYCHOLOGY ENGINE] Reading from Small Aggregator... ({TODAY_STR})")
    
    raw_data =[]
    
    if not os.path.exists(INPUT_FILE):
        print(f"🛑 FATAL ERROR: {INPUT_FILE} not found. Please run the Monte Carlo Aggregator first.")
        return[]

    try:
        df_in = pd.read_csv(INPUT_FILE)
        for _, row in df_in.iterrows():
            raw_data.append({
                "fixture_id": row.get("fixture_id", ""),
                "fixture_name": row.get("Fixture", "Unknown"),
                "monte_prob": row.get("Monte_Prob", "N/A"),
                "rank": row.get("Rank", "N/A"),
                "anomaly": row.get("Anomaly", "N/A")
            })
    except Exception as e:
        print(f"🛑 Error reading {INPUT_FILE}: {e}")
        return[]

    cat_db = {}
    if os.path.exists(FILE_CATALYST):
        try:
            cat_csv = pd.read_csv(FILE_CATALYST)
            for _, row in cat_csv.iterrows():
                try: 
                    fix_key = get_match_key(str(row['fixture']))
                    dog_prob = float(str(row['Audit_Real_Prob']).replace('%', '').strip())
                    fav_prob = float(str(row['Fav_Spear_Power']).replace('%', '').strip())
                    cat_db[fix_key] = {"dog_name": str(row['underdog_team']), "dog_prob": dog_prob, "fav_prob": fav_prob}
                except: continue
        except: pass

    todays_fixtures_map = {}
    print("   🔍 Mapping API IDs to Monte Carlo matches...")
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{TODAY_STR}", params={"include": "participants;league;season", "per_page": 50, "page": page})
        data = resp.get("data",[])
        if not data: break
        for fx in data:
            parts = fx.get("participants",[])
            h = next((p for p in parts if p.get('meta', {}).get('location') == 'home'), None)
            a = next((p for p in parts if p.get('meta', {}).get('location') == 'away'), None)
            if h and a: 
                match_key = get_match_key(f"{h['name']} vs {a['name']}")
                todays_fixtures_map[match_key] = {
                    "fid": fx['id'], "hid": h['id'], "aid": a['id'],
                    "lid": fx.get("league_id"), "sid": fx.get("season_id")
                }
        page += 1
        time.sleep(REQUEST_DELAY)

    processed_list =[]
    
    for match in raw_data:
        try:
            fix_name = str(match["fixture_name"])
            match_key = get_match_key(fix_name)
            
            if match_key not in todays_fixtures_map: continue 
                
            fx_info = todays_fixtures_map[match_key]
            fid, home_id, away_id = fx_info["fid"], fx_info["hid"], fx_info["aid"]
            lid, sid = fx_info["lid"], fx_info["sid"]
            home_name = fix_name.split(" vs ")[0] if " vs " in fix_name else "Home"
            
            cat_info = cat_db.get(match_key, {})
            dog_name = cat_info.get("dog_name", "")
            
            if clean_n(home_name) == clean_n(dog_name):
                h_spear, a_spear = cat_info.get("dog_prob", 0.0), cat_info.get("fav_prob", 0.0)
            else:
                h_spear, a_spear = cat_info.get("fav_prob", 0.0), cat_info.get("dog_prob", 0.0)

            pos_map = get_league_standings_map(lid, sid)
            h_pos = pos_map.get(int(home_id), 99)
            a_pos = pos_map.get(int(away_id), 99)

            h_traits = analyze_gg_tactics(home_id, away_id, fid)
            a_traits = analyze_gg_tactics(away_id, home_id, fid)
            
            psych_score, reasons = calculate_gg_score(h_traits, a_traits, h_spear, a_spear, h_pos, a_pos)

            if psych_score >= 60: tier = "💎 PSYCHOLOGY LOCK"
            elif psych_score >= 35: tier = "🔥 SOLID PSYCHOLOGY"
            elif psych_score <= 0: tier = "🛑 PSYCHOLOGY VETO"
            else: tier = "📊 NEUTRAL"

            processed_list.append({
                "Fixture": fix_name,
                "MC_Rank": match["rank"],
                "MC_Prob": match["monte_prob"],
                "Psych_Score": psych_score,
                "Spears": f"H:{h_spear}%|A:{a_spear}%",
                "Tier": tier,
                "Psych_Triggers": " | ".join(reasons)
            })
            
            print(f" > Audited {fix_name[:30]:<30} | MC: {match['monte_prob']:<6} | Psych: {psych_score:>3}/100 | {tier}")
            
        except Exception as e:
            continue

    # ==============================================================================
    # 🏆 FINAL ALIENEDGE PRINTS & SAVES
    # ==============================================================================
    final_table = pd.DataFrame(processed_list)
    if final_table.empty: 
        print("\n>>[FATAL ERROR] No matches processed.")
        return[]

    final_table = final_table.sort_values(by=["Psych_Score"], ascending=False)
    
    diamond_df = final_table[final_table['Tier'].str.contains("💎")]
    veto_df = final_table[final_table['Tier'].str.contains("🛑")]

    print("\n" + "💎"*45)
    print(" 💎 ALIENEDGE VERIFIED PSYCHOLOGY LOCKS 💎")
    print("💎"*45)
    print("   Passed Monte Carlo AND Passed Tactical Psychology Checks.\n")
    if not diamond_df.empty:
        for i, (_, row) in enumerate(diamond_df.iterrows(), 1):
            print(f"{i}. {row['Fixture']} -> [{row['MC_Rank']}] | MC Prob: {row['MC_Prob']} | Psych Score: {row['Psych_Score']}")
            print(f"   * Triggers: {row['Psych_Triggers']}\n")
    else: print("   [!] No Verified Diamond Locks found today.\n")

    print("\n" + "🚨"*45)
    print(" 🚨 SAVED BY THE BELL: MONTE CARLO PASSED BUT PSYCHOLOGY VETOED 🚨")
    print("🚨"*45)
    print("   Math loved these games, but the Tactical Engine spotted a Trap.\n")
    if not veto_df.empty:
        for i, (_, row) in enumerate(veto_df.iterrows(), 1):
            print(f"{i}. {row['Fixture']} ->[{row['MC_Rank']}] | MC Prob: {row['MC_Prob']} | 🛑 VETOED (Score: {row['Psych_Score']})")
            print(f"   * Reason: {row['Psych_Triggers']}\n")
    else: print("[!] No Vetoes triggered today.\n")

    print("\n" + "="*140)
    print("📊 FULL PIPELINE FORENSIC BOARD (Outputting for Final Aggregator)")
    print("="*140)
    
    cols =["Fixture", "MC_Rank", "MC_Prob", "Psych_Score", "Tier", "Spears", "Psych_Triggers"]
    print(final_table[cols].to_string(index=False))
    
    final_table.to_csv(OUTPUT_CSV, index=False)
    print(f"\n💾 [Done] AlienEdge GG Psychology output saved to: {OUTPUT_CSV}")

    # Return data dynamically for your final Master Aggregator
    return final_table.to_dict(orient="records")

# --- LOCAL TESTING BLOCK ---#
if __name__ == "__main__":
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    run_gg_psychology_engine()