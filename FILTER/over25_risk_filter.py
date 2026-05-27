import os
import sys
import pandas as pd
import numpy as np
import json
from datetime import datetime, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Architecture Ready) ---
# Finds the root folder to manage 'data' and 'output' correctly across any server
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (OVER 2.5 GOALS - STAGE 3 FILTER)
# ==============================================================================
def run_over25_filter_aggregator(target_date=None, mode="public", risk_level="balanced"):
    """
    Executes Over 2.5 Goals Filter Aggregator.
    Translates raw Stage 2 data into betting picks (Banker/Aggressive/Balanced).
    Logic is 100% preserved and wrapped for professional execution.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Path to the input file (Stage 2 output)
    input_csv = os.path.join(OUTPUT_DIR, f"master_over_stage2_{target_date}.csv")

    if not os.path.exists(input_csv):
        print(f"[ERROR] Stage 3 Filter: Input file {input_csv} not found. Run Stage 2 first.")
        return []

    # -------------------------
    # INTERNAL FILTER 1: PUBLIC (PRESET RISK LEVELS)
    # -------------------------
    def apply_over_public_filter(df, r_level, odds_band="1.50-1.85"):
        df_filtered = df.copy()
        if df_filtered.empty: return df_filtered

        # Odds Bands
        odds_map = {
            "1.30-1.60": (1.30, 1.60),
            "1.50-1.85": (1.50, 1.85),
            "1.80-2.20": (1.80, 2.20)
        }
        min_odd, max_odd = odds_map.get(odds_band, (1.50, 1.85))

        # Data Cleaning for filtering
        df_filtered['poisson_num'] = df_filtered['poisson_over_prob'].str.replace('%','').astype(float)
        df_filtered['votes_num'] = df_filtered['council_votes'].str.split('/').str[0].astype(int)

        # Risk Logic Rectified for Total Accuracy
        if r_level == "banker":
            # Highest Accuracy: Kill Switch + Tight Table Gap + High Math
            df_filtered = df_filtered[
                (df_filtered["kill_switch_pass"] == True) &
                (df_filtered["pos_gap"] <= 6) &
                (df_filtered["votes_num"] >= 7) &
                (df_filtered["poisson_num"] >= 70)
            ]
        elif r_level == "aggressive":
            # High Firepower: Combined goals are massive
            df_filtered = df_filtered[
                (df_filtered["poisson_num"] >= 65) &
                (df_filtered["combined_gs_last_5"] >= 20) &
                (df_filtered["parity_diff"].abs() >= 5)
            ]
        else:  # balanced
            df_filtered = df_filtered[
                (df_filtered["kill_switch_pass"] == True) &
                (df_filtered["votes_num"] >= 6) &
                (df_filtered["poisson_num"] >= 60)
            ]

        # Final Odds Filter
        df_filtered = df_filtered[
            (df_filtered["o25_odds"] >= min_odd) & 
            (df_filtered["o25_odds"] <= max_odd)
        ]

        return df_filtered.drop(columns=['poisson_num', 'votes_num'])

    # -------------------------
    # INTERNAL FILTER 2: TIPSTER (RAW SLIDERS)
    # -------------------------
    def apply_over_tipster_filter(df, 
                                  min_odds=1.40, max_odds=2.20, 
                                  min_poisson=60, min_votes=6, 
                                  max_pos_gap=10, min_h2h_overs=3):
        df_filtered = df.copy()
        if df_filtered.empty: return df_filtered

        df_filtered['poisson_num'] = df_filtered['poisson_over_prob'].str.replace('%','').astype(float)
        df_filtered['votes_num'] = df_filtered['council_votes'].str.split('/').str[0].astype(int)

        df_filtered = df_filtered[
            (df_filtered["o25_odds"] >= min_odds) & 
            (df_filtered["o25_odds"] <= max_odds) &
            (df_filtered["poisson_num"] >= min_poisson) &
            (df_filtered["votes_num"] >= min_votes) &
            (df_filtered["pos_gap"] <= max_pos_gap) &
            (df_filtered["h2h_overs_last_5"] >= min_h2h_overs)
        ]

        return df_filtered.drop(columns=['poisson_num', 'votes_num'])

    # -------------------------
    # EXECUTION PIPELINE
    # -------------------------
    print(f"[STAGE 3 FILTER] Processing {input_csv} in {mode} mode...")
    
    try:
        raw_df = pd.read_csv(input_csv)
        
        if mode == "public":
            final_df = apply_over_public_filter(raw_df, risk_level)
            label = f"PUBLIC_{risk_level.upper()}"
        else:
            final_df = apply_over_tipster_filter(raw_df)
            label = "TIPSTER_PRO"

        # Sort by best probability first
        if not final_df.empty:
            final_df['sort_help'] = final_df['poisson_over_prob'].str.replace('%','').astype(float)
            final_df = final_df.sort_values(by="sort_help", ascending=False).drop(columns=['sort_help'])

        # SAVE THE FINAL PICKS
        output_filename = os.path.join(OUTPUT_DIR, f"FILTERED_O25_{label}_{target_date}.csv")
        final_df.to_csv(output_filename, index=False)

        print(f"[SUCCESS] Filter applied. {len(final_df)} {label} picks saved to {output_filename}")
        return final_df.to_dict(orient="records")

    except Exception as e:
        print(f"[CRITICAL ERROR] Filter failed: {e}")
        return []

# Standard execution block for local VS Code testing
if __name__ == "__main__":
    # Test for today's date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_over25_filter_aggregator(target_date=today, mode="public", risk_level="banker") 