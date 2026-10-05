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
                         min_odds=None,
                         max_odds=None,
                         min_overall_wins=None,
                         min_venue_wins=None,
                         min_h2h_wins=None,
                         min_opp_conceded=None,
                         min_opp_losses=None,
                         min_parity_gap=None,
                         min_even_count=None,
                         require_no_draw=None,
                         strict_mode=True,
                         use_public_preset=True):
    """
    Granular filter for professional tipsters.

    THE USER'S RULE (2026-10-05)
    ----------------------------
    "Every match on the board must meet EVERY number I typed. A box I left empty
    must not filter anything."

    Every threshold therefore defaults to None = OFF, rather than to a number.
    They previously defaulted to 1.40/2.00 odds plus a wall of zeros, and the
    Weekly Tipster board could not turn the odds corridor off: _live_win()
    substituted WIN_DEFAULT_BAND (1.40-1.90) into an empty box, and
    apply_tipster_filter applied whatever it was given. A board with one number
    typed was still filtered by seven rules the user had never seen.

      use_public_preset=True  — the shipped preset's numbers are supplied by the
                               CALLER (unchanged behaviour for the pipeline).
      use_public_preset=False — nothing is seeded; only typed numbers filter.

    A gate is added only when its bound is not None, so an absent bound can
    neither pass nor block a row. A half-typed odds range filters only on the
    side given; an absent side is unbounded rather than reverting to a default.
    """

    # Preset seeding for the pipeline path: the caller historically relied on
    # these defaults, so they are applied here rather than in the signature.
    if use_public_preset:
        if min_odds is None:     min_odds = 1.40
        if max_odds is None:     max_odds = 2.00
        if min_overall_wins is None: min_overall_wins = 0
        if min_venue_wins is None:   min_venue_wins = 0
        if min_h2h_wins is None:     min_h2h_wins = 0
        if min_opp_conceded is None: min_opp_conceded = 0
        if min_opp_losses is None:   min_opp_losses = 0
        if min_parity_gap is None:   min_parity_gap = 0
        if min_even_count is None:   min_even_count = 0

    df_filtered = df.copy()
    if df_filtered.empty: return df_filtered

    conditions = []

    # ODDS — both sides optional. An absent min or max is unbounded, so a user
    # who types only a maximum is not silently given a 1.40 floor.
    if min_odds is not None:
        conditions.append(df_filtered["win_odds"] >= float(min_odds))
    if max_odds is not None:
        conditions.append(df_filtered["win_odds"] <= float(max_odds))

    for column, bound in (("last_5_wins_overall", min_overall_wins),
                          ("last_5_wins_at_venue", min_venue_wins),
                          ("h2h_wins_last_5", min_h2h_wins),
                          ("opp_last_5_conceded_raw", min_opp_conceded),
                          ("opp_last_5_losses", min_opp_losses),
                          ("parity_score", min_parity_gap),
                          ("parity_even_count", min_even_count)):
        if bound is not None and column in df_filtered.columns:
            conditions.append(df_filtered[column] >= float(bound))

    if require_no_draw is not None and "last_3_no_draw_BOTH" in df_filtered.columns:
        conditions.append(df_filtered["last_3_no_draw_BOTH"] == require_no_draw)

    if not conditions:
        # Nothing was asked for, so nothing may filter. Returns the full slate
        # rather than crashing on an empty condition list.
        return df_filtered

    if strict_mode:
        for cond in conditions:
            df_filtered = df_filtered[cond]
    elif len(conditions) >= 2:
        # Soft mode: allow 1 failure (The "Diamond in the Rough" feature)
        mask_sum = sum(cond.astype(int) for cond in conditions)
        df_filtered = df_filtered[mask_sum >= (len(conditions) - 1)]
    else:
        # A single typed gate is absolute. "Allow one failure" against one rule
        # would permit exactly what the user excluded.
        df_filtered = df_filtered[conditions[0]]

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
    
    # Load data from the Poisson Engine.  A headerless file (the old empty
    # forecast artifact) is an invalid input, not a zero-pick result.
    try:
        df = pd.read_csv(input_csv)
    except pd.errors.EmptyDataError as exc:
        raise RuntimeError(
            f"Win Filter source {os.path.basename(input_csv)} has no CSV header/columns"
        ) from exc
    if df.empty:
        print(f"[INFO] Win Filter source contains no rows: {os.path.basename(input_csv)}")
        return []

    required_columns = {
        "fixture_id", "fixture", "side", "team_name", "win_odds",
        "last_5_wins_overall", "last_5_wins_at_venue",
        "opp_last_5_conceded_raw", "h2h_wins_last_5", "parity_score",
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise RuntimeError(
            f"Win Filter source {os.path.basename(input_csv)} is missing columns: "
            f"{', '.join(missing_columns)}"
        )
    valid_odds = int(df["win_odds"].notna().sum())
    print(f"[INFO] Win Filter source rows={len(df)}, valid_odds={valid_odds}, "
          f"missing_odds={len(df) - valid_odds}")

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
