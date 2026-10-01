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
def run_over25_filter_aggregator(target_date=None, mode="public", risk_level="balanced",
                                 odds_band="1.50-1.85", persist=True, **overrides):
    """
    Executes Over 2.5 Goals Filter Aggregator.
    Translates raw Stage 2 data into betting picks (Banker/Aggressive/Balanced).

    ADDITIVE (2026-09-23):
      * `overrides` are forwarded verbatim to the EXISTING tipster filter
        (min_odds/max_odds/min_poisson/min_votes/max_pos_gap/min_h2h_overs) so
        the Weekly page's Tipster sliders drive the real engine. Public mode
        ignores them here (the API narrows the preset rows instead).
      * `persist=False` keeps every gate and returned row byte-identical but
        does NOT write FILTERED_O25_*.csv — request-time filtering must never
        overwrite a pipeline artifact. Default `True` = unchanged.
    """
    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Flexible candidate paths to ensure Stage 2 input is always found
    candidate_inputs = [
        os.path.join(OUTPUT_DIR, f"master_over_stage2_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, "over25_stage2_picks.csv"),
        os.path.join(OUTPUT_DIR, f"over25_stage2_picks_{target_date}.csv"),
    ]

    input_csv = next((f for f in candidate_inputs if os.path.exists(f)), None)

    if not input_csv:
        print(f"[ERROR] Stage 3 Filter: Input file not found for {target_date} (checked: {candidate_inputs}). Run Stage 2 first.")
        return []

    def _extract_poisson(df):
        """Robust extractor for Poisson probability handling float, int, and percent string."""
        # Stage 2 writes this value as `poisson_over_prob_num` (see
        # output/master_over_stage2_<date>.csv). It was missing from the
        # candidate list below, so every row fell through to the 0.0
        # default and the risk gates (banker >=70 / balanced >=60 /
        # aggressive >=65) rejected ALL rows on every date. Adding the
        # real column name is a FIELD BINDING fix only — no threshold,
        # gate, odds band, kill-switch, votes or pos-gap logic changed.
        for col in ['poisson_over_prob', 'poisson_prob', 'poisson_over', 'o25_prob', 'prob',
                    'poisson_over_prob_num']:
            if col in df.columns:
                return pd.to_numeric(df[col].astype(str).str.replace('%', '', regex=False), errors='coerce').fillna(0.0)
        return pd.Series(0.0, index=df.index)

    def _extract_votes(df):
        """Robust extractor for council votes handling int or '7/9' format."""
        for col in ['council_votes', 'votes', 'votes_num']:
            if col in df.columns:
                return pd.to_numeric(df[col].astype(str).str.split('/').str[0], errors='coerce').fillna(0).astype(int)
        return pd.Series(0, index=df.index)

    # -------------------------
    # INTERNAL FILTER 1: PUBLIC (PRESET RISK LEVELS)
    # -------------------------
    def apply_over_public_filter(df, r_level, o_band="1.50-1.85"):
        df_filtered = df.copy()
        if df_filtered.empty: return df_filtered

        # Odds Bands
        odds_map = {
            "1.30-1.60": (1.30, 1.60),
            "1.50-1.85": (1.50, 1.85),
            "1.80-2.20": (1.80, 2.20)
        }
        min_odd, max_odd = odds_map.get(o_band, (1.50, 1.85))

        # Robust Data Cleaning for filtering
        df_filtered['poisson_num'] = _extract_poisson(df_filtered)
        df_filtered['votes_num'] = _extract_votes(df_filtered)

        # Risk Logic Rectified for Total Accuracy
        if r_level == "banker":
            # Highest Accuracy: Kill Switch + Tight Table Gap + High Math
            pos_gap = df_filtered["pos_gap"] if "pos_gap" in df_filtered.columns else pd.Series(0, index=df_filtered.index)
            kill_pass = df_filtered["kill_switch_pass"] if "kill_switch_pass" in df_filtered.columns else pd.Series(True, index=df_filtered.index)

            df_filtered = df_filtered[
                (kill_pass == True) &
                (pos_gap <= 6) &
                (df_filtered["votes_num"] >= 7) &
                (df_filtered["poisson_num"] >= 70)
            ]
        elif r_level == "aggressive":
            # High Firepower: Combined goals are massive
            combined_gs = df_filtered["combined_gs_last_5"] if "combined_gs_last_5" in df_filtered.columns else pd.Series(20, index=df_filtered.index)
            parity_diff = df_filtered["parity_diff"].abs() if "parity_diff" in df_filtered.columns else pd.Series(5, index=df_filtered.index)

            df_filtered = df_filtered[
                (df_filtered["poisson_num"] >= 65) &
                (combined_gs >= 20) &
                (parity_diff >= 5)
            ]
        else:  # balanced
            kill_pass = df_filtered["kill_switch_pass"] if "kill_switch_pass" in df_filtered.columns else pd.Series(True, index=df_filtered.index)

            df_filtered = df_filtered[
                (kill_pass == True) &
                (df_filtered["votes_num"] >= 6) &
                (df_filtered["poisson_num"] >= 60)
            ]

        # Final Odds Filter (if column exists)
        if "o25_odds" in df_filtered.columns:
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
                                  max_pos_gap=10, min_h2h_overs=3,
                                  min_home_goals=0, min_away_goals=0,
                                  max_home_conceded=0, max_away_conceded=0,
                                  strict_h2h_last3_over=False,
                                  strict_both_scored_last3=False):
        df_filtered = df.copy()
        if df_filtered.empty: return df_filtered

        df_filtered['poisson_num'] = _extract_poisson(df_filtered)
        df_filtered['votes_num'] = _extract_votes(df_filtered)

        pos_gap = df_filtered["pos_gap"] if "pos_gap" in df_filtered.columns else pd.Series(0, index=df_filtered.index)
        h2h_overs = df_filtered["h2h_overs_last_5"] if "h2h_overs_last_5" in df_filtered.columns else pd.Series(min_h2h_overs, index=df_filtered.index)

        cond = (
            (df_filtered["poisson_num"] >= min_poisson) &
            (df_filtered["votes_num"] >= min_votes) &
            (pos_gap <= max_pos_gap) &
            (h2h_overs >= min_h2h_overs)
        )

        if "o25_odds" in df_filtered.columns:
            cond = cond & (df_filtered["o25_odds"] >= min_odds) & (df_filtered["o25_odds"] <= max_odds)

        # ── RECENT GOAL FORM, PER SIDE ──────────────────────────────────────
        # 2026-09-30. Four real gates replacing the display-only L5/L3 toggle.
        # A toggle that changed no gate was not a filter, and it sat down by
        # the results rather than among the controls that decide what survives.
        #
        # A 0 threshold means OFF — the column is skipped entirely, so the
        # shipped result set is unchanged until a value is actually typed.
        #
        # Missing values PASS rather than fail: a dated artefact graded before
        # the engine wrote these columns must not be silently filtered down to
        # nothing, and absence of evidence is not evidence against a pick.
        for col, thr, op in (("home_goals_scored_last_5", min_home_goals, "ge"),
                             ("away_goals_scored_last_5", min_away_goals, "ge"),
                             ("home_goals_conceded_last_5", max_home_conceded, "le"),
                             ("away_goals_conceded_last_5", max_away_conceded, "le")):
            if not thr or col not in df_filtered.columns:
                continue
            vals = pd.to_numeric(df_filtered[col], errors="coerce")
            known = vals.notna()
            ok = (vals >= thr) if op == "ge" else (vals <= thr)
            cond = cond & (~known | ok)

        # ── STRICT GATES (tick boxes) ───────────────────────────────────────
        # 2026-10-01. Requested as ticks rather than numeric thresholds: these
        # are yes/no disciplines, not dials. Ticking one means "force out every
        # fixture that does not qualify" — the team must clear it or it is
        # dropped, rather than merely scoring better on a slider.
        #
        # OFF by default, and a missing column skips the gate entirely so an
        # older dated artifact is never filtered to nothing by a column the
        # engine had not yet written.
        if strict_h2h_last3_over and "kill_switch_pass" in df_filtered.columns:
            # kill_switch_pass is the forecast engine's own h2h_last_3_all_over
            # verdict — the last three head-to-heads all cleared 2.5. This is
            # that engine's existing decision, not a new rule: the O2.5 banker
            # and balanced presets already apply it, so ticking this extends
            # the same discipline to the aggressive preset and to Tipster mode.
            _ks = df_filtered["kill_switch_pass"]
            cond = cond & _ks.notna() & (_ks == True)  # noqa: E712 — engine writes a real bool

        if strict_both_scored_last3:
            _need = ["home_goals_scored_last_3", "away_goals_scored_last_3"]
            if all(c in df_filtered.columns for c in _need):
                # Both sides must have found the net at least once in their own
                # last three. A side that has scored nothing in three is not
                # an Over 2.5 side yet, whatever the Poisson number says.
                for _c in _need:
                    _v = pd.to_numeric(df_filtered[_c], errors="coerce")
                    cond = cond & (_v.notna() & (_v >= 1))

        df_filtered = df_filtered[cond]

        return df_filtered.drop(columns=['poisson_num', 'votes_num'])

    # -------------------------
    # EXECUTION PIPELINE
    # -------------------------
    print(f"[STAGE 3 FILTER] Processing {input_csv} in {mode} mode...")
    
    try:
        raw_df = pd.read_csv(input_csv)
        
        if mode == "public":
            final_df = apply_over_public_filter(raw_df, risk_level, odds_band)
            label = f"PUBLIC_{risk_level.upper()}"
        else:
            # Tipster/advanced: forward the Weekly sliders to the EXISTING
            # tipster filter. Unspecified keys keep the filter's own defaults.
            final_df = apply_over_tipster_filter(raw_df, **overrides)
            label = "TIPSTER_PRO"

        # Sort by best probability first (safe extraction)
        if not final_df.empty:
            sort_vals = _extract_poisson(final_df)
            final_df['sort_help'] = sort_vals
            final_df = final_df.sort_values(by="sort_help", ascending=False).drop(columns=['sort_help'])

        # SAVE THE FINAL PICKS (skipped for request-time/live filtering)
        if persist:
            output_filename = os.path.join(OUTPUT_DIR, f"FILTERED_O25_{label}_{target_date}.csv")
            final_df.to_csv(output_filename, index=False)
            print(f"[SUCCESS] Filter applied. {len(final_df)} {label} picks saved to {output_filename}")
        else:
            print(f"[SUCCESS] Filter applied (live request, no artifact written). {len(final_df)} {label} picks.")

        return final_df.to_dict(orient="records")

    except Exception as e:
        print(f"[CRITICAL ERROR] Filter failed: {e}")
        return []

# Standard execution block for local VS Code testing
if __name__ == "__main__":
    # Test for today's date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_over25_filter_aggregator(target_date=today, mode="public", risk_level="banker")
