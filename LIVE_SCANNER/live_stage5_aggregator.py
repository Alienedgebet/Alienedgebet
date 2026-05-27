import os
import json
import re

# --- 1. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Inputs (From Code 1 and Code 3)
INCOMING_PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
DANGER_AUDIT_FILE = os.path.join(DATA_DIR, "danger_audit.json")

# Output (For Code 5)
AGGREGATOR_REPORT_FILE = os.path.join(DATA_DIR, "aggregator_report.json")

# -------------------------
# HANDSHAKE CONFIGURATION
# -------------------------
CHAOS_THRESHOLD = 4        # Real rotation starts at 4 players
FOUNDATION_WEIGHT = 50.0   # Goalkeeper priority weight

def get_match_key(name):
    """Alphabetical sorting ensures 'A vs B' matches 'B vs A'."""
    n = str(name).lower()
    n = re.sub(r'\bu19\b|\bfc\b', '', n)
    if ' vs ' in n: teams = n.split(' vs ')
    elif '-' in n: teams = n.split('-')
    else: teams = [n]
    teams =[re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]
    teams.sort()
    return "".join(teams)

def run_master_aggregator():
    """ 
    MASTER AGGREGATOR: Calculates the 'Match Chemistry' list for all markets.
    HANDSHAKE: Incoming Probabilities + Danger Forensics.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    try:
        with open(INCOMING_PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            incoming_data = json.load(f)
        with open(DANGER_AUDIT_FILE, "r", encoding="utf-8") as f:
            danger_data = json.load(f)
    except FileNotFoundError:
        print("Waiting for data from Scouts and Audit Engines (Files not found yet)...")
        return {"error": "Waiting for data"}

    final_report =[]
    
    print("\n" + "="*120)
    print(f"{'🤝 ALIENEDGE MASTER HANDSHAKE (FULL MARKET ALIGNMENTS)':^120}")
    print("="*120)
    print(f"[DEBUG] Aggregator loaded {len(incoming_data)} incoming predictions and {len(danger_data)} danger profiles.")

    for f_key, incoming_picks in incoming_data.items():
        # SMART MATCHING: Try to match by ID first, if that fails, match by Team Names
        audit = next((item for item in danger_data if str(item.get('fixture_id', '')) == str(f_key)), None)
        
        if not audit:
            # Fallback: Try matching by alphabetical name key (Your brilliant fix!)
            incoming_name_key = get_match_key(f_key)
            audit = next((item for item in danger_data if get_match_key(item.get('fixture', '')) == incoming_name_key), None)

        if not audit:
            print(f"  [DROP] Could not find Live Danger data for Pre-Match target: {f_key}")
            continue

        # --- EXTRACT DATA PILLARS ---
        h = audit['home_team']
        a = audit['away_team']
        
        h_missing_pos = [p['pos'] for p in h.get('missing_details',[])]
        a_missing_pos = [p['pos'] for p in a.get('missing_details',[])]
        
        h_missing_count = len(h.get('missing_details',[]))
        a_missing_count = len(a.get('missing_details',[]))
        
        h_breach = (h_missing_count >= CHAOS_THRESHOLD) or ("Goalkeeper" in h_missing_pos)
        a_breach = (a_missing_count >= CHAOS_THRESHOLD) or ("Goalkeeper" in a_missing_pos)

        # 2. TACTICAL SYNC (Formation vs Style)
        def get_sync(team):
            style = team.get('style', {}).get('label', 'Balanced')
            form = team.get('formation', 'N/A')
            
            if "Attacking" in style and ("5-" in form or "Defensive" in style): return "CONFLICT"
            if "Attacking" in style and ("4-3-3" in form or "3-4-3" in form): return "ELITE"
            return "STABLE"

        h_sync = get_sync(h)
        a_sync = get_sync(a)
        style_align = audit.get('style_alignment', "⚠️ TIGHT")

        # 3. CHEMISTRY LIST GENERATOR
        chemistry = {}

        # --- Market: GG (Both Teams to Score) ---
        if style_align == "🔥 OPEN" and (h_breach or a_breach): chemistry["Gg"] = "Excellent"
        elif style_align == "🔥 OPEN": chemistry["Gg"] = "Very Strong"
        else: chemistry["Gg"] = "Weak"

        # --- Market: Corners ---
        if "Wing" in h.get('style', {}).get('label', '') or "Crossing" in h.get('style', {}).get('label', ''):
            chemistry["Corner"] = "Elite"
        elif style_align == "🔥 OPEN": chemistry["Corner"] = "Very Strong"
        else: chemistry["Corner"] = "Strong"

        # --- Market: Home Win ---
        if h_breach: chemistry["Home Win"] = "Very Weak"
        elif h_sync == "CONFLICT": chemistry["Home Win"] = "Weak"
        elif not h_breach and h_sync == "ELITE" and a_breach: chemistry["Home Win"] = "Elite"
        else: chemistry["Home Win"] = "Strong"

        # --- Market: Away Win ---
        if a_breach: chemistry["Away Win"] = "Very Weak"
        elif a_sync == "CONFLICT": chemistry["Away Win"] = "Weak"
        elif not a_breach and a_sync == "ELITE" and h_breach: chemistry["Away Win"] = "Elite"
        else: chemistry["Away Win"] = "Strong"

        # --- Market: Over 2.5 ---
        if style_align == "🔥 OPEN" and h_sync != "CONFLICT" and a_sync != "CONFLICT": chemistry["Over2.5"] = "Strong"
        elif style_align == "🔥 OPEN" and (h_breach and a_breach): chemistry["Over2.5"] = "Excellent"
        else: chemistry["Over2.5"] = "Weak"

        # --- Market: Under 3.5 ---
        if style_align == "⚠️ TIGHT" or h_sync == "CONFLICT" or a_sync == "CONFLICT": chemistry["Under3.5"] = "Very Strong"
        else: chemistry["Under3.5"] = "Weak"

        # --- Market: Over 1.5 ---
        if h_breach or a_breach or style_align == "🔥 OPEN": chemistry["Over1.5"] = "Excellent"
        else: chemistry["Over1.5"] = "Strong"

        # 🚨 THE SYNDICATE PRINTOUT (Shows the boss the data!)
        print(f"\n[{audit.get('fixture_id', 'Unknown')}] {audit.get('fixture', 'Unknown Match')}")
        print(f" └─ Tactical Alignment: {style_align} | H-Sync: {h_sync} | A-Sync: {a_sync}")
        print(f" └─ MARKET ALIGNMENTS:")
        for market, status in chemistry.items():
            icon = "🔥" if status in ["Elite", "Excellent", "Very Strong"] else ("✅" if status == "Strong" else "🛑")
            print(f"      {icon} {market:<10} : {status}")

        # FINAL ASSEMBLED OUTPUT
        final_report.append({
            "fixture": audit.get('fixture', 'Unknown'),
            "fixture_id": audit.get('fixture_id', f_key),
            "incoming_probabilities": incoming_picks,
            "danger_report": {
                "home": {"status": h.get('danger_level', 'SAFE'), "sync": h_sync, "breach": h_breach},
                "away": {"status": a.get('danger_level', 'SAFE'), "sync": a_sync, "breach": a_breach}
            },
            "match_chemistry_list": chemistry 
        })

    # SAVE SAFELY IN THE DYNAMIC DIRECTORY FOR CODE 6 TO READ
    with open(AGGREGATOR_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=4, ensure_ascii=False)
        
    print(f"\n[🤝] HANDSHAKE COMPLETE: {len(final_report)} Matches Aggregated.")
    print(f" Master Report Saved: {AGGREGATOR_REPORT_FILE}")
    print("="*120 + "\n")

    return final_report

if __name__ == "__main__":
    run_master_aggregator()