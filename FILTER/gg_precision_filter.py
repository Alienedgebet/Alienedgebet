import os
import glob
import pandas as pd
import numpy as np
import re
from datetime import datetime, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ============================================================
# USER FLEXIBILITY CONFIG (Deadly Accuracy Layer)
# ============================================================
USER_FILTER = {
    "last3_gg_min": 2,           # Must have at least 2 GG in last 3 matches
    "last3_gg_max": 3,           # 🟢 UPGRADED: No longer hardcoded to 3 in the logic
    "h2h_gg_min": 3,             # History must show high H2H GG frequency
    "pos_diff_min": 1,           # 🟢 UPGRADED: Minimum table positions apart
    "pos_diff_max": 10,          # 🟢 UPGRADED: Maximum table positions apart
    "home_gg_side_min": 3,       # Home team must have 3+ GG matches at home
    "away_gg_side_min": 3,       # Away team must have 3+ GG matches away
    "min_probability": 60.0      # Probability floor
}

# ============================================================
# PATH & SCHEMA CONFIG
# ============================================================
# Scanning the OUTPUT_DIR where your stages save their files
ENGINE_PREFIX = "picks_gg" 
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "forecast_final_gg_precision.csv")

# 🟢 UPGRADED: Added the missing vital columns so the engine doesn't crash during aggregation
REQUIRED_COLS =[
    "fixture_id",
    "league_id",
    "home_team",
    "away_team",
    "tier",
    "gg_prob_pct",
    "home_gg_last3",
    "away_gg_last3",
    "h2h_gg_count",
    "home_position",
    "away_position",
    "home_gg_count",
    "away_gg_count",
    "h2h_goal_parity",
    "concede_parity"
]

# ============================================================
# 🟢 UPGRADED: TEAM NAME NORMALIZATION
# ============================================================
def normalize_name(name):
    """Standardizes team names to prevent grouping failures."""
    n = str(name).lower()
    n = re.sub(r'\bu19\b|\bfc\b|\bsc\b|\bunited\b|\bcity\b|\bclub\b|\bafc\b|\brc\b|\bas\b', '', n)
    return re.sub(r'[^a-z0-9]', '', n.strip())

# ============================================================
# DATA LOADER & VALIDATOR
# ============================================================
def load_validated_history(days=7):
    # Search for files matching the prefix in the OUTPUT directory
    search_pattern = os.path.join(OUTPUT_DIR, f"{ENGINE_PREFIX}*.csv")
    files = sorted(glob.glob(search_pattern))
    
    if not files:
        print("⚠️ No engine CSV files found. Aggregator waiting for data...")
        return pd.DataFrame()

    files = files[-days:]
    print(f"📂 Scanning last {len(files)} days of structural data in {OUTPUT_DIR}...")

    dfs =[]
    for f in files:
        try:
            df = pd.read_csv(f)
            
            # --- THE VALIDATION GATE ---
            missing = [c for c in REQUIRED_COLS if c not in df.columns]
            if missing:
                print(f"❌ Skipping {os.path.basename(f)}: Missing required precision columns: {missing}")
                continue
            
            # 🟢 UPGRADED: DUPLICATE FIXTURE REMOVAL
            # Prevents double-counting a match if the engine accidentally ran twice in one day
            initial_count = len(df)
            df = df.drop_duplicates(subset=["fixture_id"])
            if len(df) < initial_count:
                print(f"   [!] Cleaned {initial_count - len(df)} duplicate fixtures from {os.path.basename(f)}")

            df["source_file"] = os.path.basename(f)
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ Error reading {os.path.basename(f)}: {e}")

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# ============================================================
# THE DEADLY PRECISION FILTER
# ============================================================
def apply_precision_filter(df, cfg):
    if df.empty: return df
    
    # 🟢 UPGRADED: FLEXIBLE TABLE DISTANCE LOGIC
    # Mask out 0 and 99 positions (Cup games/unranked)
    valid_positions = (df["home_position"] > 0) & (df["home_position"] < 90) & \
                      (df["away_position"] > 0) & (df["away_position"] < 90)
    
    # Calculate absolute distance between teams
    pos_diff = (df["home_position"] - df["away_position"]).abs()

    # Strictly applying your 100% accuracy logic
    mask = (
        # Layer 1: Probability Floor
        (df["gg_prob_pct"] >= cfg["min_probability"]) &

        # Layer 2: THE TOTAL PARITY LIMIT (Strictly <= 4)
        (df["h2h_goal_parity"] + df["concede_parity"] <= 4) &

        # Layer 3: SHORT TERM FORM (Now dynamic using User Config)
        (df["home_gg_last3"].between(cfg["last3_gg_min"], cfg["last3_gg_max"])) &
        (df["away_gg_last3"].between(cfg["last3_gg_min"], cfg["last3_gg_max"])) &

        # Layer 4: H2H GG VOLUME
        (df["h2h_gg_count"] >= cfg["h2h_gg_min"]) &

        # Layer 5: 🟢 UPGRADED STANDINGS GATE (Distance Based)
        (valid_positions) &
        (pos_diff.between(cfg["pos_diff_min"], cfg["pos_diff_max"])) &

        # Layer 6: HISTORICAL SIDE-BIAS (Home vs Away performance)
        (df["home_gg_count"] >= cfg["home_gg_side_min"]) &
        (df["away_gg_count"] >= cfg["away_gg_side_min"])
    )

    df_filtered = df[mask].copy()
    
    # Save the distance so user can see it in output
    if not df_filtered.empty:
        df_filtered["table_distance"] = pos_diff[mask]
        
    return df_filtered

# ============================================================
# AGGREGATION (CROSS-DAY VERIFICATION)
# ============================================================
def aggregate_picks(df):
    
    # 🟢 UPGRADED: Create normalized columns for bulletproof grouping
    df["norm_home"] = df["home_team"].apply(normalize_name)
    df["norm_away"] = df["away_team"].apply(normalize_name)

    # 🟢 UPGRADED: LEAGUE SEPARATION & NORMALIZED GROUPING
    # This prevents crossing stats of teams with the same name in different leagues
    grouped = (
        df
        .groupby(["league_id", "norm_home", "norm_away"])
        .agg({
            "fixture_id": "first",
            "home_team": "first",     # Keeps the original pretty name for the final CSV
            "away_team": "first",
            "gg_prob_pct": "mean",    # Averages the probability across the verified days
            "table_distance": "first",
            "tier": "first",
            "source_file": "nunique"  # Verification days
        })
        .reset_index()
        .drop(columns=["norm_home", "norm_away"]) # Hide the ugly normalized names from final output
        .sort_values("gg_prob_pct", ascending=False)
    )

    grouped.rename(columns={"source_file": "verification_days"}, inplace=True)
    return grouped

# ============================================================
# 📦 THE BLACK BOX WRAPPER
# ============================================================
def run_gg_precision_filter():
    print("\n" + "="*80)
    print("🚀 GG PRECISION AGGREGATOR ACTIVE (7-DAY CROSS-VERIFICATION)")
    print("="*80)
    
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 1. Load and Validate
    df_all = load_validated_history(days=7)
    if df_all.empty:
        print("❌ Aggregator closed: No valid data sources found.")
        return[]

    # 2. Filter
    print("🎯 Applying Precision Layers (Total Parity <= 4, Form constraints, Table Distance)...")
    df_filtered = apply_precision_filter(df_all, USER_FILTER)

    if df_filtered.empty:
        print("🛑 Precision Check: No matches survived the deadly accuracy layers.")
        return[]

    # 3. Aggregate
    df_final = aggregate_picks(df_filtered)
    df_final["audit_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # 4. Save and Print
    df_final.to_csv(OUTPUT_FILE, index=False)
    
    print("\n      🏆 FINAL HIGH-PRECISION VERIFIED PICKS (AGGREGATED) 🏆")
    print("-" * 80)
    
    if not df_final.empty:
        print(df_final[["home_team", "away_team", "table_distance", "gg_prob_pct", "tier", "verification_days"]].to_string(index=False))
        print("\n" + "-"*80)
        print(f"✅ SUCCESS: {len(df_final)} Matches verified and saved to {OUTPUT_FILE}")
    else:
        print("No picks survived the final precision audit.")
        
    return df_final.to_dict(orient="records")

if __name__ == "__main__":
    run_gg_precision_filter()