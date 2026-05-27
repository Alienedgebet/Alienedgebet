import os
import json
import pandas as pd
import numpy as np
import re
from datetime import datetime, timezone

# ==============================================================================
# ⚙️ CONFIGURATION & PATHS
# ==============================================================================

# Dynamic Paths - Assumes script is run from the main Alienedgebet folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Determine Today's Date dynamically to grab the correct Pre-Match CSVs
TARGET_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Target Files
DANGER_FILE = os.path.join(DATA_DIR, "danger_audit.json")
WIN_FILE = os.path.join(OUTPUT_DIR, f"ALIENEDGE_WIN_PREDICTIONS_{TARGET_DATE}.csv")
GG_FILE = os.path.join(OUTPUT_DIR, f"JUDGED_GG_PICKS_{TARGET_DATE}.csv")
CORNER_FILE = os.path.join(OUTPUT_DIR, "corner3_qualified.json")
OVER25_FILE = os.path.join(OUTPUT_DIR, "over25_stage2_picks.json")
SH_GG_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")

# ==============================================================================
# 🛠️ UTILITY & MATCHING ALGORITHMS
# ==============================================================================

def get_match_key(name):
    """Universal matching key to connect Live Data with Pre-Match Data seamlessly."""
    if not name or not isinstance(name, str): return "unknown"
    n = name.lower()
    n = re.sub(r'\bu19\b|\bfc\b', '', n)
    if ' vs ' in n: teams = n.split(' vs ')
    elif '-' in n: teams = n.split('-')
    else: teams = [n]
    teams = [re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]
    teams.sort()
    return "".join(teams)

def extract_percentage(val):
    """Safely extracts a float probability from messy strings (e.g. '85%', '85.5', 85)"""
    if pd.isna(val) or val is None: return 0.0
    try:
        s = str(val).replace('%', '').strip()
        match = re.search(r"(\d+(\.\d+)?)", s)
        if match: return float(match.group(1))
    except: pass
    return 0.0

def find_best_prob_column(df, keywords):
    """Scans a dataframe to find the column containing the probability."""
    for col in df.columns:
        for key in keywords:
            if key.lower() in col.lower():
                return col
    return None

# ==============================================================================
# 📥 DATA INGESTION & NORMALIZATION
# ==============================================================================

def load_prematch_data():
    """Loads all 5 Pre-Match prediction files and normalizes them into a Master Dictionary."""
    master_prematch = {}

    # 1. Load Win Predictions (CSV)
    if os.path.exists(WIN_FILE):
        try:
            df = pd.read_csv(WIN_FILE)
            fix_col = find_best_prob_column(df, ['fixture', 'match'])
            prob_col = find_best_prob_column(df, ['prob', 'confidence', '%', 'score'])
            pick_col = find_best_prob_column(df,['prediction', 'pick', 'selection'])
            
            if fix_col and prob_col:
                for _, row in df.iterrows():
                    key = get_match_key(row[fix_col])
                    if key not in master_prematch: master_prematch[key] = {}
                    master_prematch[key]['win_prob'] = extract_percentage(row[prob_col])
                    master_prematch[key]['win_pick'] = str(row[pick_col]) if pick_col else "Win"
        except Exception as e: print(f"[!] Win Parser Error: {e}")

    # 2. Load GG Predictions (CSV)
    if os.path.exists(GG_FILE):
        try:
            df = pd.read_csv(GG_FILE)
            fix_col = find_best_prob_column(df, ['fixture', 'match'])
            prob_col = find_best_prob_column(df, ['prob', 'monte', 'score', '%'])
            if fix_col and prob_col:
                for _, row in df.iterrows():
                    key = get_match_key(row[fix_col])
                    if key not in master_prematch: master_prematch[key] = {}
                    master_prematch[key]['gg_prob'] = extract_percentage(row[prob_col])
        except Exception as e: print(f"[!] GG Parser Error: {e}")

    # 3. Load Corners (JSON)
    if os.path.exists(CORNER_FILE):
        try:
            with open(CORNER_FILE, 'r') as f:
                c_data = json.load(f)
                items = c_data.values() if isinstance(c_data, dict) else c_data
                for row in items:
                    key = get_match_key(row.get('fixture', row.get('name', '')))
                    if key not in master_prematch: master_prematch[key] = {}
                    master_prematch[key]['corner_prob'] = extract_percentage(row.get('prob', row.get('probability', 75.0))) # Fallback 75 if just a 'qualified' list
        except Exception as e: print(f"[!] Corner Parser Error: {e}")

    # 4. Load Over 2.5 (JSON)
    if os.path.exists(OVER25_FILE):
        try:
            with open(OVER25_FILE, 'r') as f:
                o_data = json.load(f)
                items = o_data.values() if isinstance(o_data, dict) else o_data
                for row in items:
                    key = get_match_key(row.get('fixture', row.get('name', '')))
                    if key not in master_prematch: master_prematch[key] = {}
                    master_prematch[key]['o25_prob'] = extract_percentage(row.get('prob', row.get('probability', 75.0)))
        except Exception as e: print(f"[!] Over 2.5 Parser Error: {e}")

    # 5. Load Second Half GG (JSON)
    if os.path.exists(SH_GG_FILE):
        try:
            with open(SH_GG_FILE, 'r') as f:
                sh_data = json.load(f)
                items = sh_data.values() if isinstance(sh_data, dict) else sh_data
                for row in items:
                    key = get_match_key(row.get('fixture', row.get('name', '')))
                    if key not in master_prematch: master_prematch[key] = {}
                    master_prematch[key]['sh_gg_prob'] = extract_percentage(row.get('prob', row.get('probability', 75.0)))
        except Exception as e: print(f"[!] SH GG Parser Error: {e}")

    return master_prematch

# ==============================================================================
# 🧠 THE SUPREME JUDGE ALGORITHM (Adjusting Math using Danger Specs)
# ==============================================================================

def calculate_adjusted_probabilities(prematch_data, danger_data):
    """
    Takes the raw Morning Math and surgically alters it based on Live Lineup Intelligence.
    Returns Adjusted Probability + Traffic Light Status.
    """
    results = {}

    # --- Extract Live Danger Intel ---
    h_info = danger_data.get('home_team', {})
    a_info = danger_data.get('away_team', {})
    style_align = danger_data.get('style_alignment', "⚠️ TIGHT")

    h_dmg = float(h_info.get('vulnerability_pct', 0.0))
    a_dmg = float(a_info.get('vulnerability_pct', 0.0))
    h_leak = float(h_info.get('gk_leak', 0.0))
    a_leak = float(a_info.get('gk_leak', 0.0))
    
    h_miss_pos =[p.get('pos', '') for p in h_info.get('missing_details', [])]
    a_miss_pos =[p.get('pos', '') for p in a_info.get('missing_details', [])]
    
    h_style = h_info.get('style', {}).get('label', '')
    a_style = a_info.get('style', {}).get('label', '')

    # --- Ensure we have base probabilities (Use 50 if missing but danger exists) ---
    base_win = prematch_data.get('win_prob', 0)
    win_pick = prematch_data.get('win_pick', 'Home Win')
    base_gg = prematch_data.get('gg_prob', 0)
    base_o25 = prematch_data.get('o25_prob', 0)
    base_corner = prematch_data.get('corner_prob', 0)
    base_sh_gg = prematch_data.get('sh_gg_prob', 0)

    # ---------------------------------------------------------
    # ⚖️ JUDGEMENT 1: WIN MARKET CALIBRATION
    # ---------------------------------------------------------
    adj_win = base_win
    win_reason = ""
    if base_win > 0:
        if "Home" in win_pick:
            if h_dmg >= 40.0: 
                adj_win -= 25.0
                win_reason = "(VETO: Home Squad heavily damaged)"
            elif "Attacker" in h_miss_pos: 
                adj_win -= 12.0
                win_reason = "(Caution: Missing Key Attackers)"
            if a_dmg >= 45.0:
                adj_win += 15.0
                win_reason = "(BOOST: Away Squad destroyed by injuries)"
        elif "Away" in win_pick:
            if a_dmg >= 40.0: 
                adj_win -= 25.0
                win_reason = "(VETO: Away Squad heavily damaged)"
            elif "Attacker" in a_miss_pos: 
                adj_win -= 12.0
                win_reason = "(Caution: Missing Key Attackers)"
            if h_dmg >= 45.0:
                adj_win += 15.0
                win_reason = "(BOOST: Home Squad destroyed by injuries)"

    # ---------------------------------------------------------
    # ⚖️ JUDGEMENT 2: GG (BTTS) MARKET CALIBRATION
    # ---------------------------------------------------------
    adj_gg = base_gg
    gg_reason = ""
    if base_gg > 0:
        if style_align == "🔥 OPEN":
            adj_gg += 8.0
            gg_reason = "(BOOST: Open Tactical Alignment)"
        if h_leak > 1.3 and a_leak > 1.3:
            adj_gg += 12.0
            gg_reason = "(BOOST: Double GK Leakage detected)"
        if style_align == "⚠️ TIGHT" and (h_dmg < 15 and a_dmg < 15):
            adj_gg -= 20.0
            gg_reason = "(VETO: Defensive Gridlocked match)"

    # ---------------------------------------------------------
    # ⚖️ JUDGEMENT 3: OVER 2.5 MARKET CALIBRATION
    # ---------------------------------------------------------
    adj_o25 = base_o25
    o25_reason = ""
    if base_o25 > 0:
        if style_align == "🔥 OPEN" and (h_dmg > 20 or a_dmg > 20):
            adj_o25 += 15.0
            o25_reason = "(BOOST: Fast pace vs Damaged Defenses = Shootout)"
        elif style_align == "⚠️ TIGHT":
            adj_o25 -= 18.0
            o25_reason = "(VETO: Tight tactics throttle goals)"

    # ---------------------------------------------------------
    # ⚖️ JUDGEMENT 4: CORNERS MARKET CALIBRATION
    # ---------------------------------------------------------
    adj_corner = base_corner
    corner_reason = ""
    if base_corner > 0:
        if "Wing" in h_style or "Crossing" in h_style or "Attacking" in h_style:
            adj_corner += 10.0
            corner_reason = "(BOOST: Wide/Attacking formation confirmed)"
        if style_align == "🔥 OPEN":
            adj_corner += 5.0

    # ---------------------------------------------------------
    # ⚖️ JUDGEMENT 5: SECOND HALF GG CALIBRATION
    # ---------------------------------------------------------
    adj_sh_gg = base_sh_gg
    sh_gg_reason = ""
    if base_sh_gg > 0:
        if h_dmg > 30 and a_dmg > 30:
            adj_sh_gg += 15.0
            sh_gg_reason = "(BOOST: Heavy squad rotation causes 2nd half fatigue leaks)"

    # --- Normalize Scores between 0 and 99 ---
    def cap(x): return min(99.0, max(0.0, float(x)))
    
    def get_light(score):
        if score == 0: return "⚪ N/A"
        if score >= 80.0: return "🟢 GREENLIGHT (Elite)"
        if score >= 65.0: return "🟡 PLAYABLE (Caution)"
        return "🛑 REDLIGHT (Veto/Danger)"

    results["Win"] = {"base": base_win, "adj": cap(adj_win), "pick": win_pick, "light": get_light(cap(adj_win)), "reason": win_reason}
    results["GG"] = {"base": base_gg, "adj": cap(adj_gg), "light": get_light(cap(adj_gg)), "reason": gg_reason}
    results["O25"] = {"base": base_o25, "adj": cap(adj_o25), "light": get_light(cap(adj_o25)), "reason": o25_reason}
    results["Corner"] = {"base": base_corner, "adj": cap(adj_corner), "light": get_light(cap(adj_corner)), "reason": corner_reason}
    results["SH_GG"] = {"base": base_sh_gg, "adj": cap(adj_sh_gg), "light": get_light(cap(adj_sh_gg)), "reason": sh_gg_reason}

    return results

# ==============================================================================
# 🚀 MAIN DASHBOARD EXECUTION
# ==============================================================================

def run_supreme_dashboard():
    print("\n" + "="*120)
    print(f"{'👁️ ALIENEDGE SUPREME INTELLIGENCE DASHBOARD 👁️':^120}")
    print(f"{'Bridging Morning Math with Live Forensic Reality':^120}")
    print("="*120 + "\n")

    # 1. Load Pre-Match Files
    print("[*] Sweeping Pre-Match Output Directories...")
    prematch_db = load_prematch_data()
    print(f"[*] Successfully cached mathematical data for {len(prematch_db)} teams.")

    # 2. Load Danger Audit
    print("[*] Accessing Live Danger Forensics...\n")
    try:
        with open(DANGER_FILE, 'r') as f:
            danger_data = json.load(f)
    except FileNotFoundError:
        print("[!] CRITICAL ERROR: danger_audit.json not found! Run the Danger Engine first.")
        return
    except Exception as e:
        print(f"[!] Danger File Error: {e}")
        return

    # 3. Merging & Displaying
    if not danger_data:
        print("No incoming matches detected in the Danger Audit.")
        return

    for audit in danger_data:
        fixture_name = audit.get('fixture', 'Unknown Match')
        fix_key = get_match_key(fixture_name)

        # Pull Morning Math
        p_math = prematch_db.get(fix_key, {})

        # Run the Supreme Judge Algorithm
        final_verdict = calculate_adjusted_probabilities(p_math, audit)

        # Extact Display Variables for Danger
        h = audit.get('home_team', {})
        a = audit.get('away_team', {})
        style_align = audit.get('style_alignment', 'Unknown')
        
        h_dmg = h.get('vulnerability_pct', 0)
        a_dmg = a.get('vulnerability_pct', 0)
        
        # Missing Players String
        h_miss_names = ", ".join([p.get('name', '') for p in h.get('missing_details', [])]) or "None"
        a_miss_names = ", ".join([p.get('name', '') for p in a.get('missing_details', [])]) or "None"

        print(f"🏆 {fixture_name.upper()} 🏆")
        print("-" * 120)
        
        # --- THE SPY REPORT (Live Reality) ---
        print(">> THE SPY REPORT (Live Lineups):")
        print(f"   Style Alignment: {style_align}")
        print(f"   [HOME]: {h_dmg}% Damage | Missing: {h_miss_names}")
        print(f"   [AWAY]: {a_dmg}% Damage | Missing: {a_miss_names}")
        print("")

        # --- THE JUDGE REPORT (Pre-Match Math vs Adjusted Logic) ---
        print(">> THE JUDGE VERDICT (Adjusted Probabilities):")

        # Win Market
        if final_verdict['Win']['base'] > 0:
            print(f"   🎯 {final_verdict['Win']['pick']} Market:")
            print(f"      Pre-Match Math : {final_verdict['Win']['base']}%")
            print(f"      Final Verdict  : {final_verdict['Win']['adj']:.1f}%  |  {final_verdict['Win']['light']} {final_verdict['Win']['reason']}")
        
        # GG Market
        if final_verdict['GG']['base'] > 0:
            print(f"   ⚽ Both Teams To Score (GG):")
            print(f"      Pre-Match Math : {final_verdict['GG']['base']}%")
            print(f"      Final Verdict  : {final_verdict['GG']['adj']:.1f}%  |  {final_verdict['GG']['light']} {final_verdict['GG']['reason']}")

        # Over 2.5 Market
        if final_verdict['O25']['base'] > 0:
            print(f"   🔥 Over 2.5 Goals:")
            print(f"      Pre-Match Math : {final_verdict['O25']['base']}%")
            print(f"      Final Verdict  : {final_verdict['O25']['adj']:.1f}%  |  {final_verdict['O25']['light']} {final_verdict['O25']['reason']}")

        # Corners Market
        if final_verdict['Corner']['base'] > 0:
            print(f"   🚩 Corners:")
            print(f"      Pre-Match Math : {final_verdict['Corner']['base']}%")
            print(f"      Final Verdict  : {final_verdict['Corner']['adj']:.1f}%  |  {final_verdict['Corner']['light']} {final_verdict['Corner']['reason']}")

        # SH GG Market
        if final_verdict['SH_GG']['base'] > 0:
            print(f"   ⏱️ Second Half GG:")
            print(f"      Pre-Match Math : {final_verdict['SH_GG']['base']}%")
            print(f"      Final Verdict  : {final_verdict['SH_GG']['adj']:.1f}%  |  {final_verdict['SH_GG']['light']} {final_verdict['SH_GG']['reason']}")

        # If no pre-match data was found for this team
        if not p_math:
            print("   [!] No Pre-Match Mathematical Predictions were generated for this fixture today.")

        print("=" * 120 + "\n")

if __name__ == "__main__":
    run_supreme_dashboard()