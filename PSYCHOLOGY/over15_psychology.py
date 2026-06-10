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

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_o15_psychology_engine(target_date=None):
    """
    Executes the AlienEdge Over 1.5 Psychology Engine.
    Reads exclusively from the Over 1.5 Handshake output (over15_stage3_final.csv).
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    API_KEY = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return []

    BASE_URL = "https://api.sportmonks.com/v3/football"

    if not target_date:
        TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        TODAY_STR = target_date

    # Reads from Handshake Output, NOT the head file
    HANDSHAKE_FILE = os.path.join(OUTPUT_DIR, "over15_stage3_final.csv")
    FILE_CATALYST = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")
    OUTPUT_CSV = os.path.join(OUTPUT_DIR, f"ALIENEDGE_O15_PREDICTIONS_{TODAY_STR}.csv")

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - [O1.5 ENGINE] - %(message)s')

    # 🛡️ BULLETPROOF API HELPER & CACHE SYSTEM
    API_CACHE = {}
    STANDINGS_CACHE = {}
    REQUEST_DELAY = 0.2

    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault("api_token", API_KEY)

        cache_key = path + "?" + "&".join([f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token"])
        if cache_key in API_CACHE:
            return API_CACHE[cache_key]

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
                else:
                    return {"data":[]}
            except Exception:
                time.sleep(1)
                continue
        return {"data":[]}

    def clean_n(name):
        n = str(name).lower()
        for word in ["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
            n = n.replace(word, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n = clean_n(name)
        parts = n.split('vs') if 'vs' in n else [n]
        parts = [p.strip() for p in parts]
        parts.sort()
        return "".join(parts)

    def get_league_standings_map(league_id, season_id):
        if not league_id or league_id == "Unknown" or not season_id:
            return {}

        cache_key = f"{league_id}_{season_id}"
        if cache_key in STANDINGS_CACHE:
            return STANDINGS_CACHE[cache_key]

        standings_resp = GET(f"/standings/seasons/{season_id}", params={"filters": f"standingLeagues:{league_id}"})
        standings_list = standings_resp.get("data", [])
        
        pos_map = {int(s["participant_id"]): int(s["position"]) for s in standings_list if s.get("participant_id") and s.get("position")}
        STANDINGS_CACHE[cache_key] = pos_map
        return pos_map

    def extract_goals_by_period(fx, period="FT"):
        home_g, away_g = None, None
        for entry in fx.get("scores", []):
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

        for p in fx.get("participants", []):
            if str(p.get("id")) == str(team_id):
                loc = (p.get("meta") or {}).get("location")
                if loc == "home": return hg, ag
                if loc == "away": return ag, hg

        local = fx.get("localteam_id") or fx.get("localteam") or fx.get("local_team_id")
        visitor = fx.get("visitorteam_id") or fx.get("visitorteam") or fx.get("visitor_team_id")
        if str(local) == str(team_id): return hg, ag
        if str(visitor) == str(team_id): return ag, hg

        parts = fx.get("participants", [])
        if len(parts) >= 2:
            if str(parts[0].get("id")) == str(team_id): return hg, ag
            if str(parts[1].get("id")) == str(team_id): return ag, hg

        return None, None

    def get_match_outcome_bulletproof(fx, team_id, period="FT"):
        tg, og = get_team_and_opp_goals(fx, team_id, period)
        if tg is None or og is None: return None
        if tg > og: return "W"
        if tg < og: return "L"
        return "D"

    def extract_stat_value(fx, team_id, stat_names):
        entries = fx.get("statistics", [])
        if isinstance(entries, dict):
            entries = entries.get(str(team_id), [])
        else:
            entries = [s for s in entries if str(s.get('participant_id', '')) == str(team_id)]
            
        for s in entries:
            t_name = str(s.get("type", {}).get("name", s.get("name", ""))).upper()
            if any(name.upper() in t_name for name in stat_names):
                val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
                try: return float(val)
                except: pass
        return 0.0

    # ==============================================================================
    # 🧠 OVER 1.5 TACTICS ENGINE (The Chaos Profiler)
    # ==============================================================================
    def analyze_o15_tactics(team_id, current_match_id):
        end_dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_dt = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
        
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", 
                   params={"include": "statistics.type;participants;scores", "per_page": 15, "order":"desc", "filter": "fixtureStates:5"})
        
        fixtures = [f for f in resp.get("data", []) if str(f.get('id')) != str(current_match_id)]
        last_5 = fixtures[:5]
        
        if not last_5:
            return {
                "is_attacking": False, "is_defensive": False, "is_possession": False, 
                "is_crossing": False, "is_glass_jaw": False, "is_ht_active": False, 
                "is_ht_killer": False, "is_ht_vulnerable": False, "is_clinical": False, 
                "total_goals": 0, "no_clean_sheets": False, "is_wounded": False, "avg_sot": 0.0
            }

        attacks = sum([extract_stat_value(f, team_id, ["Attacks"]) for f in last_5]) / len(last_5)
        dang_attacks = sum([extract_stat_value(f, team_id, ["Dangerous Attacks"]) for f in last_5]) / len(last_5)
        sot_list = [extract_stat_value(f, team_id, ["Shots On Target"]) for f in last_5]
        avg_sot = sum(sot_list) / len(sot_list) if sot_list else 0.0
        bcc_list = [extract_stat_value(f, team_id, ["Big Chances"]) for f in last_5]
        avg_bcc = sum(bcc_list) / len(bcc_list) if bcc_list else 0.0
        
        tackles = sum([extract_stat_value(f, team_id, ["Tackles"]) for f in last_5]) / len(last_5)
        interceptions = sum([extract_stat_value(f, team_id, ["Interceptions"]) for f in last_5]) / len(last_5)
        poss = sum([extract_stat_value(f, team_id, ["Ball Possession"]) for f in last_5]) / len(last_5)
        crosses = sum([extract_stat_value(f, team_id, ["Total Crosses"]) for f in last_5]) / len(last_5)
        
        is_attacking = (attacks > 60 and dang_attacks > 40 and avg_sot >= 3.5)
        is_defensive = (tackles >= 14 and interceptions >= 8 and avg_sot < 3.5)
        is_possession = (poss >= 58)
        is_crossing = (crosses >= 15)
        is_clinical = (avg_sot >= 4.5 and avg_bcc >= 1.5)

        scored_list = []
        conceded_list = []
        ht_scored_count = 0
        ht_conceded_count = 0
        ht_win_count = 0
        
        for f in last_5:
            tg, og = get_team_and_opp_goals(f, team_id, "FT")
            if tg is not None: scored_list.append(tg)
            if og is not None: conceded_list.append(og)
            
            ht_tg, ht_og = get_team_and_opp_goals(f, team_id, "HT")
            if ht_tg is not None and ht_tg > 0: ht_scored_count += 1
            if ht_og is not None and ht_og > 0: ht_conceded_count += 1
            if ht_tg is not None and ht_og is not None and ht_tg > ht_og: ht_win_count += 1

        total_goals = sum(scored_list)
        avg_conc = sum(conceded_list) / len(conceded_list) if conceded_list else 1.0
        
        is_glass_jaw = (avg_conc > 1.8 and len(conceded_list) >= 3)
        is_ht_active = (ht_scored_count >= 3)
        is_ht_killer = (ht_win_count >= 3)
        is_ht_vulnerable = (ht_conceded_count >= 3)
        no_clean_sheets = (conceded_list.count(0) == 0 and len(conceded_list) >= 4)

        outcomes_2 = [get_match_outcome_bulletproof(f, team_id, "FT") for f in last_5[:2]]
        shock_loss = (len(outcomes_2) > 0 and outcomes_2[0] == "L")
        winless_2 = (len(outcomes_2) == 2 and "W" not in outcomes_2)
        is_wounded = (shock_loss or winless_2)

        return {
            "is_attacking": is_attacking, "is_defensive": is_defensive, "is_possession": is_possession,
            "is_crossing": is_crossing, "is_glass_jaw": is_glass_jaw, "is_ht_active": is_ht_active,
            "is_ht_killer": is_ht_killer, "is_ht_vulnerable": is_ht_vulnerable, "is_clinical": is_clinical,
            "total_goals": total_goals, "no_clean_sheets": no_clean_sheets, "is_wounded": is_wounded,
            "avg_sot": round(avg_sot, 1)
        }

    # ==============================================================================
    # ⚖️ THE ALIENEDGE OVER 1.5 RULES ENGINE (Reverse Psychology)
    # ==============================================================================
    def calculate_o15_score(h, a, h_spear, a_spear, h_pos, a_pos):
        """Calculates the 100-Point Over 1.5 Score based on your exact Rules."""
        score = 0
        reasons = []

        is_h_fav = (h_spear >= a_spear)
        is_a_fav = (a_spear > h_spear)
        ud_spear = min(h_spear, a_spear)

        both_attacking = h['is_attacking'] and a['is_attacking']
        both_defensive = h['is_defensive'] and a['is_defensive']
        both_possession = h['is_possession'] and a['is_possession']
        both_glass_jaw = h['is_glass_jaw'] and a['is_glass_jaw']
        both_ht_active = h['is_ht_active'] and a['is_ht_active']
        both_clinical = h['is_clinical'] and a['is_clinical']
        
        one_attacking = h['is_attacking'] or a['is_attacking']
        one_glass_jaw = h['is_glass_jaw'] or a['is_glass_jaw']
        one_crossing = h['is_crossing'] or a['is_crossing']
        no_cs_both = h['no_clean_sheets'] and a['no_clean_sheets']
        total_goals_high = (h['total_goals'] > 10 and a['total_goals'] > 10)

        # ---------------------------------------------------------
        # 🔴 THE VETOES (Negative Points)
        # ---------------------------------------------------------
        if both_possession: 
            score -= 25; reasons.append("🛑 Both Possession (-25)")
        if both_defensive: 
            score -= 30; reasons.append("🧱 Both Defensive (-30)")

        # ---------------------------------------------------------
        # 🟢 THE POSITIVE BOOSTS
        # ---------------------------------------------------------
        if both_attacking and both_glass_jaw and both_ht_active:
            score += 25
            reasons.append("💎 THE HOLY GRAIL: Attack + No Defense + HT Goals (+25)")
        else:
            if both_attacking:
                score += 12; reasons.append("⚔️ Both Attacking (+12)")
            if both_glass_jaw:
                score += 15; reasons.append("🔨 Both Glass Jaw (+15)")
            if both_ht_active:
                score += 10; reasons.append("⚡ Both HT Active (+10)")

        if (h['is_ht_killer'] and a['is_ht_vulnerable']) or (a['is_ht_killer'] and h['is_ht_vulnerable']):
            score += 15; reasons.append("⏱️ Early Kill Matchup (+15)")

        if not both_attacking and not both_defensive and not both_possession:
            if (h['avg_sot'] + a['avg_sot']) >= 9.0:
                score += 12; reasons.append("🎯 Mixed Styles but High SOT (+12)")

        if one_attacking and one_glass_jaw:
            score += 20; reasons.append("🐺 Attacker vs Glass Jaw (+20)")
        
        if one_crossing:
            score += 8; reasons.append("✈️ Crossing Matchup (+8)")

        if both_clinical:
            score += 12; reasons.append("🎯 Both Clinical (+12)")

        if no_cs_both:
            score += 10; reasons.append("🔓 No Clean Sheets for Either (+10)")

        if total_goals_high:
            score += 10; reasons.append("🔥 High Recent Goals >10 (+10)")

        # ---------------------------------------------------------
        # 🧠 THE PSYCHOLOGY ADDITIONS
        # ---------------------------------------------------------
        if ud_spear > 70.0:
            score += 10; reasons.append("🤝 BTTS Synergy / High UD (+10)")
            
        fav_wounded = (is_h_fav and h['is_wounded']) or (is_a_fav and a['is_wounded'])
        if fav_wounded:
            score += 15; reasons.append("🩸 Wounded Fav Rage (+15)")

        if h_pos != 99 and a_pos != 99:
            if h_pos >= 15 and a_pos >= 15:
                score += 10; reasons.append("🆘 Relegation Desperation (+10)")

        if not reasons: reasons.append("Neutral - No Rules Triggered")
        
        return score, reasons

    # ==============================================================================
    # 🚀 MAIN EXECUTION
    # ==============================================================================
    print(f"\n>> [AlienEdge OVER 1.5 ENGINE] Initializing Reverse Psychology Protocol... ({TODAY_STR})")
    
    # READS FROM THE RE-ROUTED HANDSHAKE
    raw_data_dict = {}
    if os.path.exists(HANDSHAKE_FILE):
        try:
            df_in = pd.read_csv(HANDSHAKE_FILE)
            match_col = next((c for c in df_in.columns if "match" in c.lower() or "fixture" in c.lower()), df_in.columns[0])
            poisson_col = next((c for c in df_in.columns if "poisson" in c.lower()), None)
            grade_col = next((c for c in df_in.columns if ("grade" in c.lower() and "num" not in c.lower()) or "votes" in c.lower()), None)
            
            for _, row in df_in.iterrows():
                fix_name = str(row[match_col])
                key = get_match_key(fix_name)
                poisson_val = row[poisson_col] if poisson_col else "Unknown"
                grade_val = row[grade_col] if grade_col else "Unknown"
                
                raw_data_dict[key] = {
                    "fixture_name": fix_name,
                    "base_poisson": poisson_val,
                    "base_grade": grade_val
                }
        except Exception as e:
            print(f"🛑 Error reading {os.path.basename(HANDSHAKE_FILE)}: {e}")
    else:
        print(f"⚠️ [WARNING] {os.path.basename(HANDSHAKE_FILE)} not found.")

    raw_data = list(raw_data_dict.values())
    if not raw_data:
        print("🛑 FATAL ERROR: No matches found in Handshake output. Please run handshake engine first.")
        return []

    # READ CATALYST FOR UD/FAV SPEARS
    cat_db = {}
    if os.path.exists(FILE_CATALYST):
        try:
            cat_csv = pd.read_csv(FILE_CATALYST)
            for _, row in cat_csv.iterrows():
                try: 
                    fix_key = get_match_key(str(row['fixture']))
                    dog_name = str(row['underdog_team'])
                    dog_prob = float(str(row['Audit_Real_Prob']).replace('%', '').strip())
                    fav_prob = float(str(row['Fav_Spear_Power']).replace('%', '').strip())
                    cat_db[fix_key] = {"dog_name": dog_name, "dog_prob": dog_prob, "fav_prob": fav_prob}
                except: continue
        except: pass

    todays_fixtures_map = {}
    page = 1
    while True:
        resp = GET(f"/fixtures/date/{TODAY_STR}", params={"include": "participants;league;season", "per_page": 50, "page": page})
        data = resp.get("data", [])
        if not data: break
        for fx in data:
            parts = fx.get("participants", [])
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

    processed_list = []
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

            h_traits = analyze_o15_tactics(home_id, fid)
            a_traits = analyze_o15_tactics(away_id, fid)
            
            o15_score, reasons = calculate_o15_score(h_traits, a_traits, h_spear, a_spear, h_pos, a_pos)

            if o15_score >= 60: tier = "💎 DIAMOND OVER 1.5"
            elif o15_score >= 40: tier = "🔥 SOLID OVER 1.5"
            elif o15_score >= 25: tier = "📊 PLAYABLE OVER 1.5"
            else: tier = "🛑 AVOID / UNDER"

            processed_list.append({
                "Fixture": fix_name,
                "Base_Poisson": match["base_poisson"],
                "Base_Grade": match["base_grade"],
                "Score": o15_score,
                "Tier": tier,
                "Reasons": " | ".join(reasons)
            })

            print(f" > Audited {fix_name[:35]:<35} | Score: {o15_score:>3}/100 | {tier}")
            
        except Exception as e:
            continue

    final_table = pd.DataFrame(processed_list)
    if final_table.empty: 
        print("\n>> [FATAL ERROR] No matches processed.")
        return []

    final_table = final_table.sort_values(by=["Score"], ascending=False)
    
    diamond_df = final_table[final_table['Tier'].str.contains("💎")]
    solid_df = final_table[final_table['Tier'].str.contains("🔥")]

    print("\n" + "💎"*45)
    print(" 💎 ALIENEDGE VERIFIED LOCKS: OVER 1.5 GOALS 💎")
    print("💎"*45)
    print("   Maximum chaos detected. No defense, high attacks, and early goals expected.\n")
    if not diamond_df.empty:
        for i, (_, row) in enumerate(diamond_df.iterrows(), 1):
            print(f"{i}. {row['Fixture']} -> 🏆 BET: OVER 1.5 (Score: {row['Score']}/100)")
            print(f"   * Base Math: Poisson {row['Base_Poisson']} | Grade {row['Base_Grade']}")
            print(f"   * Triggers: {row['Reasons']}\n")
    else: print("   [!] No Verified Diamond Locks found today.\n")

    print("\n" + "🔥"*45)
    print(" 🔥 SOLID VERIFIED WINS: OVER 1.5 GOALS 🔥")
    print("🔥"*45)
    if not solid_df.empty:
        for i, (_, row) in enumerate(solid_df.iterrows(), 1):
            print(f"{i}. {row['Fixture']} -> 🏆 BET: OVER 1.5 (Score: {row['Score']}/100)")
            print(f"   * Base Math: Poisson {row['Base_Poisson']} | Grade {row['Base_Grade']}")
            print(f"   * Triggers: {row['Reasons']}\n")
    else: print("   [!] No Solid Verified Wins found today.\n")

    print("\n" + "="*120)
    print("📊 FULL OVER 1.5 FORENSIC BOARD")
    print("="*120)
    
    cols = ["Fixture", "Base_Poisson", "Base_Grade", "Score", "Tier", "Reasons"]
    print(final_table[cols].to_string(index=False))
    
    final_table.to_csv(OUTPUT_CSV, index=False)
    print(f"\n💾 [Done] AlienEdge Over 1.5 Predictions saved to: {OUTPUT_CSV}")

    return final_table.to_dict(orient="records")