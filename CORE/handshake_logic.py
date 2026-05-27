import os
import sys
import time
import json
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
# This ensures the merger looks in the 'output' folder where Stage 2 saves its files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_total_visibility_merger(target_date):
    """
    Executes the 100% Visibility Merge.
    Syncs the Parity Engine and the Dominance Engine results.
    """
    # Ensure output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # ---------------------------------------------------------
    # 1. FILE CONFIGURATION (ROBUST PATHING)
    # ---------------------------------------------------------
    # We look for the files inside the OUTPUT_DIR specifically
    parity_file = os.path.join(OUTPUT_DIR, f"backtest_underdog_{target_date}.csv")
    dominance_file = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{target_date}.csv")

    print(f"\n--- 🔄 STARTING 100% VISIBILITY MERGE FOR {target_date} ---")

    # ---------------------------------------------------------
    # 2. VERIFY SOURCE FILES EXIST
    # ---------------------------------------------------------
    if not os.path.exists(parity_file):
        print(f"❌ Error: Missing Parity file: {parity_file}")
        return None
    if not os.path.exists(dominance_file):
        print(f"❌ Error: Missing Dominance file: {dominance_file}")
        return None

    # ---------------------------------------------------------
    # 3. LOAD DATASETS
    # ---------------------------------------------------------
    df_parity = pd.read_csv(parity_file)
    df_dominance = pd.read_csv(dominance_file)

    # ---------------------------------------------------------
    # 4. CLEANING NAMES FOR MAXIMUM MATCHING (ORIGINAL LOGIC)
    # ---------------------------------------------------------
    def clean_name(name):
        """Standard Forensic Cleaning: lower, no spaces, no dots."""
        return str(name).lower().replace(" ", "").replace(".", "").strip()

    df_parity['clean_dog'] = df_parity['underdog_team'].apply(clean_name)
    df_dominance['clean_dog'] = df_dominance['underdog_team'].apply(clean_name)

    print(f"[INFO] Parity List: {len(df_parity)} matches | Dominance List: {len(df_dominance)} matches.")

    # ---------------------------------------------------------
    # 5. PERFORM THE HANDSHAKE (ORIGINAL LOOP PRESERVED)
    # ---------------------------------------------------------
    merged_pool = []
    matches_found = 0
    matches_missed = 0

    for _, p_row in df_parity.iterrows():
        clean_p = p_row['clean_dog']

        # TRY 1: Strict Match on cleaned name
        d_match = df_dominance[df_dominance['clean_dog'] == clean_p]

        if not d_match.empty:
            d_row = d_match.iloc[0]
            merged_pool.append({
                "fixture": p_row['fixture'],
                "underdog_team": p_row['underdog_team'],
                "parity_gap": p_row['parity_gap'],
                "Dominance_Gap": d_row['Dominance_Gap'],
                "Audit_Real_Prob": d_row['Audit_Real_Prob'],
                "Verdict": "Standard"
            })
            matches_found += 1
        else:
            # TRY 2: Partial Match (Contains) - (ORIGINAL LOGIC PRESERVED)
            d_partial = df_dominance[
                df_dominance['clean_dog'].str.contains(clean_p, na=False) |
                df_dominance['underdog_team'].str.contains(str(p_row['underdog_team']), na=False)
            ]
            
            if not d_partial.empty:
                d_row = d_partial.iloc[0]
                merged_pool.append({
                    "fixture": p_row['fixture'],
                    "underdog_team": p_row['underdog_team'],
                    "parity_gap": p_row['parity_gap'],
                    "Dominance_Gap": d_row['Dominance_Gap'],
                    "Audit_Real_Prob": d_row['Audit_Real_Prob'],
                    "Verdict": "Standard"
                })
                matches_found += 1
            else:
                matches_missed += 1

    # ---------------------------------------------------------
    # 6. CREATE MASTER DATAFRAME
    # ---------------------------------------------------------
    df_master = pd.DataFrame(merged_pool)

    # ---------------------------------------------------------
    # 7. SAVE THE CALIBRATION SOURCE
    # ---------------------------------------------------------
    output_filename = f"MASTER_CALIBRATION_{target_date}.csv"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    df_master.to_csv(output_path, index=False)

    # ---------------------------------------------------------
    # 8. DISPLAY EVERYTHING (FORCE ALL VISIBILITY)
    # ---------------------------------------------------------
    pd.set_option('display.max_rows', None) 
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    print("\n" + "="*100)
    print(f"   🏆 HANDSHAKE COMPLETE: {matches_found} MATCHES LINKED / {matches_missed} MISSED")
    print("="*100 + "\n")

    if not df_master.empty:
        # Show exactly what the user requested
        print(df_master[['fixture', 'underdog_team', 'parity_gap', 'Dominance_Gap']].to_string(index=False))
        print(f"\n✅ Final Master File saved as: {output_path}")
    else:
        print("❌ Handshake failed. Ensure team names match between engines.")

    # Return dictionary for Master Scheduler use
    return df_master.to_dict(orient="records")

# --- LOCAL EXECUTION BLOCK ---
if __name__ == "__main__":
    # If running locally, it will default to today or a manual test date
    test_date = "2026-02-28" 
    run_total_visibility_merger(test_date)