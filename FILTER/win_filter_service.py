import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 1. THE PUBLIC FILTER (GOLDEN STANDARD)
# ==============================================================================
def apply_public_filter(df, 
                        risk_level="balanced", 
                        odds_band="1.40-1.90",
                        min_form_wins=3,
                        min_opp_conceded=5,
                        min_h2h=2,
                        require_no_draw=False):
    """
    User-friendly filter for general app users.
    """
    df_filtered = df.copy()
    if df_filtered.empty: return df_filtered

    # ---- ODDS PRESETS ----
    odds_map = {
        "1.30-1.60": (1.30, 1.60),
        "1.40-1.90": (1.40, 1.90),
        "1.80-2.40": (1.80, 2.40)
    }
    min_odd, max_odd = odds_map.get(odds_band, (1.40, 1.90))

    # ---- RISK LOGIC RECTIFICATION ----
    # We ensure the Parity is POSITIVE (meaning our pick is stronger)
    if risk_level == "safe":
        min_parity = 15
        min_form_wins = max(min_form_wins, 4)
    elif risk_level == "aggressive":
        min_parity = 5
    else:  # balanced
        min_parity = 10

    # APPLY FILTERS
    df_filtered = df_filtered[
        (df_filtered["win_odds"] >= min_odd) & 
        (df_filtered["win_odds"] <= max_odd) &
        (df_filtered["last_5_wins_overall"] >= min_form_wins) &
        (df_filtered["opp_last_5_conceded_raw"] >= min_opp_conceded) &
        (df_filtered["h2h_wins_last_5"] >= min_h2h) &
        (df_filtered["parity_score"] >= min_parity) # Must be stronger than opponent
    ]

    if require_no_draw:
        df_filtered = df_filtered[df_filtered["last_3_no_draw_BOTH"] == True]

    return df_filtered


# ==============================================================================
# 2. THE TIPSTER FILTER (GOLDEN STANDARD)
# ==============================================================================
def apply_tipster_filter(df,
                         min_odds=1.40,
                         max_odds=2.00,
                         min_overall_wins=0,
                         min_venue_wins=0,
                         min_h2h_wins=0,
                         min_opp_conceded=0,
                         min_opp_losses=0,
                         min_parity_gap=0,
                         min_even_count=0,
                         require_no_draw=None,
                         strict_mode=True):
    """
    Granular filter for professional tipsters.
    """
    df_filtered = df.copy()
    if df_filtered.empty: return df_filtered

    conditions =[]
    
    # Check if columns exist before applying (Safety Layer)
    conditions.append((df_filtered["win_odds"] >= min_odds) & (df_filtered["win_odds"] <= max_odds))
    conditions.append(df_filtered["last_5_wins_overall"] >= min_overall_wins)
    conditions.append(df_filtered["last_5_wins_at_venue"] >= min_venue_wins)
    conditions.append(df_filtered["h2h_wins_last_5"] >= min_h2h_wins)
    conditions.append(df_filtered["opp_last_5_conceded_raw"] >= min_opp_conceded)
    conditions.append(df_filtered["opp_last_5_losses"] >= min_opp_losses)
    conditions.append(df_filtered["parity_score"] >= min_parity_gap)
    conditions.append(df_filtered["parity_even_count"] >= min_even_count)

    if require_no_draw is not None:
        conditions.append(df_filtered["last_3_no_draw_BOTH"] == require_no_draw)

    if strict_mode:
        for cond in conditions:
            df_filtered = df_filtered[cond]
    else:
        # Soft mode: allow 1 failure (The "Diamond in the Rough" feature)
        mask_sum = sum(cond.astype(int) for cond in conditions)
        df_filtered = df_filtered[mask_sum >= (len(conditions) - 1)]

    return df_filtered


# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_win_filter_service(target_date, mode="public", persist=True, **kwargs):
    """
    This is the entry point. It reads the engine data from the output folder 
    and runs the requested filter.

    `persist=False` (ADDITIVE, used by the API's live Weekly-filter path) keeps
    every gate and the returned rows byte-identical but does NOT write
    FILTERED_{label}_PICKS_{date}.csv — a request-time slider move must never
    overwrite a pipeline artifact. Default `True` = pipeline behaviour unchanged.
    """
    # Ensure directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Candidate source files produced by upstream engines
    candidate_files = [
        os.path.join(OUTPUT_DIR, f"production_raw_engine_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, f"win_poisson_production_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{target_date}.csv"),
    ]

    input_csv = next((f for f in candidate_files if os.path.exists(f)), None)

    if not input_csv:
        print(f"[ERROR] Win Filter Engine: No source file found for {target_date} (checked: {candidate_files}).")
        return []

    print(f"\n[INFO] Running Win Filter Engine ({mode.upper()} MODE) using source: {os.path.basename(input_csv)}...")
    
    # Load data from the Poisson Engine
    df = pd.read_csv(input_csv)

    # ADDITIVE (2026-09-23): production_raw_engine_{date}.csv carries no Poisson
    # probability column, so every Weekly Win row displayed "0%" and the API's
    # ensure_defaults marked it `_incomplete`. ranked_win_forecast_{date}.csv is
    # written by the same existing chain and DOES carry the REAL
    # poisson_win_prob / poisson_draw_prob for the exact same (fixture_id, side)
    # rows (verified 1:1 overlap on 2026-09-22/23). Merge those two columns in
    # when absent: the row universe, every gate and the sort are untouched —
    # no fabrication, and a no-op when the file or the join keys are missing.
    if "poisson_win_prob" not in df.columns and {"fixture_id", "side"} <= set(df.columns):
        ranked_path = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{target_date}.csv")
        if os.path.exists(ranked_path):
            try:
                rf = pd.read_csv(ranked_path)
                if "poisson_win_prob" in rf.columns and {"fixture_id", "side"} <= set(rf.columns):
                    merge_cols = ["_merge_key", "poisson_win_prob"]
                    if "poisson_draw_prob" in rf.columns:
                        merge_cols.append("poisson_draw_prob")
                    df["_merge_key"] = df["fixture_id"].astype(str) + "|" + df["side"].astype(str)
                    rf["_merge_key"] = rf["fixture_id"].astype(str) + "|" + rf["side"].astype(str)
                    df = df.merge(
                        rf[merge_cols].drop_duplicates("_merge_key"),
                        on="_merge_key", how="left",
                    ).drop(columns=["_merge_key"])
            except Exception as exc:
                print(f"[WARN] Win Filter Engine: probability merge skipped ({exc}).")
    
    if mode == "public":
        filtered_df = apply_public_filter(df, **kwargs)
        label = "PUBLIC"
    else:
        filtered_df = apply_tipster_filter(df, **kwargs)
        label = "TIPSTER"

    if filtered_df.empty:
        print(f"[WARN] No picks survived the {label} filter constraints.")
        return []

    # Sorting by strongest Poisson Probability first
    if "poisson_win_prob" in filtered_df.columns:
        try:
            # Strip % to sort numerically
            filtered_df['temp_sort'] = filtered_df['poisson_win_prob'].astype(str).str.replace('%','').astype(float)
            filtered_df = filtered_df.sort_values(by='temp_sort', ascending=False).drop(columns=['temp_sort'])
        except Exception as e:
            print(f"[WARN] Could not sort by poisson_win_prob: {e}")

    # Save output for the App UI to read (safely into the dynamic OUTPUT_DIR)
    # — skipped for request-time (live) filtering so pipeline artifacts are
    # never overwritten by a slider move.
    if persist:
        output_fn = os.path.join(OUTPUT_DIR, f"FILTERED_{label}_PICKS_{target_date}.csv")
        filtered_df.to_csv(output_fn, index=False)
        print(f"[SUCCESS] {label} Filter applied. {len(filtered_df)} picks ready and saved to {output_fn}")
    else:
        print(f"[SUCCESS] {label} Filter applied (live request, no artifact written). {len(filtered_df)} picks.")

    return filtered_df.to_dict(orient="records")

# ==============================================================================
# VS RUNNER (For Local Testing)
# ==============================================================================
if __name__ == "__main__":
    # Get today's date dynamically
    test_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Test Public Filter execution
    run_win_filter_service(target_date=test_date, mode="public", risk_level="safe")
