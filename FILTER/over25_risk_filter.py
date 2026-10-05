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

# The four per-side goal-form columns the Weekly drawer's min_*_goals /
# max_*_conceded gates read. Engine/over25_forecast.py only began writing
# these on 2026-09-30; every dated artifact before that lacks all four.
GOAL_FORM_COLUMNS = (
    "home_goals_scored_last_5",
    "away_goals_scored_last_5",
    "home_goals_conceded_last_5",
    "away_goals_conceded_last_5",
)

# The per-match over/under split behind strict_both_overs_last3 ("both sides'
# last three matches ALL cleared 2.5"). Added 2026-10-01, so until the next
# pipeline run NO artifact carries them.
OVERS3_COLUMNS = ("home_overs_last_3", "away_overs_last_3")

# Drawer gate -> the columns it needs. Used to tell the user when a gate
# cannot be evaluated instead of letting it look like it passed.
GATE_COLUMNS = {
    "goal_form": GOAL_FORM_COLUMNS,
    "overs3": OVERS3_COLUMNS,
}


def over25_source_and_goal_form(target_date):
    """
    (input_csv, families_available) for one date.

    Exists because the drawer's gates SKIP SILENTLY when their columns are
    absent (`if not thr or col not in df_filtered.columns`), which is correct
    as a data rule and disastrous as a user-facing one: the box is filled in,
    the number is sent, the engine honours nothing, and the result set comes
    back unchanged. That was reported as "the box does nothing".

    So the caller asks first and can say which dates were not evaluated,
    rather than letting an unevaluable gate look like a passing one.
    """
    # 2026-10-01 FIX — dated artifacts are tried FIRST and the undated name is
    # only a last resort.
    #
    # The previous order tried master_over_stage2_<date>.csv then jumped
    # straight to the UNDATED council file, never trying the dated council
    # file that now exists. So on any date where the forecast artifact was
    # missing, the filter silently loaded the most recent council output --
    # which could be days old -- and reported it as this date's picks.
    #
    # A missing input must be reported, not silently substituted. Callers get
    # None (and an empty family set) so the UI can say "not evaluated" rather
    # than showing an unevaluable gate as a passing one.
    candidate_inputs = [
        os.path.join(OUTPUT_DIR, f"master_over_stage2_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, f"over25_stage2_picks_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, "over25_stage2_picks.csv"),
    ]
    input_csv = next((f for f in candidate_inputs if os.path.exists(f)), None)
    if not input_csv:
        return None, frozenset()
    try:
        header = set(pd.read_csv(input_csv, nrows=0).columns)
    except Exception:
        return input_csv, frozenset()
    available = {name for name, cols in GATE_COLUMNS.items()
                 if set(cols) <= header}
    return input_csv, frozenset(available)

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
                                  min_odds=None, max_odds=None, 
                                  min_poisson=None, min_votes=None, 
                                  max_pos_gap=None, min_h2h_overs=None,
                                  min_home_goals=None, min_away_goals=None,
                                  max_home_conceded=None, max_away_conceded=None,
                                  strict_h2h_last3_over=False,
                                  strict_both_overs_last3=False,
                                  use_public_preset=True):
        """THE USER'S RULE (2026-10-05)

        "Every match on the board must meet EVERY number I typed. A box I left
        empty must not filter anything."

        Every threshold defaults to None = OFF. They previously defaulted to
        1.40-2.20 odds, poisson 60, votes 6, position gap 10 and 3 H2H overs, and
        the Weekly Tipster board could not run without them: _live_o25()
        substituted O25_DEFAULT_BAND into an empty odds box, and this function
        applied whatever it was handed. So a board with one number typed was
        still filtered by five rules the user had never seen, and clearing the
        odds control reinstated 1.50-1.85 rather than removing the limit.

          use_public_preset=True  — the shipped preset's numbers (pipeline path).
          use_public_preset=False — nothing seeded; only typed numbers filter.

        A gate is applied only when its bound is not None. An absent bound can
        neither pass nor block a row.
        """
        if use_public_preset:
            if min_odds is None:      min_odds = 1.40
            if max_odds is None:      max_odds = 2.20
            if min_poisson is None:   min_poisson = 60
            if min_votes is None:     min_votes = 6
            if max_pos_gap is None:   max_pos_gap = 10
            if min_h2h_overs is None: min_h2h_overs = 3
            if min_home_goals is None:   min_home_goals = 0
            if min_away_goals is None:   min_away_goals = 0
            if max_home_conceded is None: max_home_conceded = 0
            if max_away_conceded is None: max_away_conceded = 0

        df_filtered = df.copy()
        if df_filtered.empty: return df_filtered

        df_filtered['poisson_num'] = _extract_poisson(df_filtered)
        df_filtered['votes_num'] = _extract_votes(df_filtered)

        pos_gap = df_filtered["pos_gap"] if "pos_gap" in df_filtered.columns else pd.Series(0, index=df_filtered.index)
        h2h_overs = (df_filtered["h2h_overs_last_5"]
                     if "h2h_overs_last_5" in df_filtered.columns
                     else pd.Series(float("nan"), index=df_filtered.index))

        # Every gate is optional. A missing column means the value was never
        # measured, so with the gate OFF the row is simply not judged on it.
        cond = pd.Series(True, index=df_filtered.index)
        if min_poisson is not None:
            cond = cond & (df_filtered["poisson_num"] >= float(min_poisson))
        if min_votes is not None:
            cond = cond & (df_filtered["votes_num"] >= float(min_votes))
        if max_pos_gap is not None:
            cond = cond & (pos_gap <= float(max_pos_gap))
        if min_h2h_overs is not None:
            # A row whose H2H overs were never measured cannot satisfy a rule the
            # user typed about them, so it is excluded rather than assumed.
            cond = cond & (h2h_overs >= float(min_h2h_overs))

        if "o25_odds" in df_filtered.columns:
            if min_odds is not None:
                cond = cond & (df_filtered["o25_odds"] >= float(min_odds))
            if max_odds is not None:
                cond = cond & (df_filtered["o25_odds"] <= float(max_odds))

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

        if strict_both_overs_last3:
            # CORRECTED 2026-10-01. This was originally "both sides scored at
            # least once in their last three", which is NOT what the control
            # means. What it means is that EVERY one of each side's last three
            # matches cleared 2.5 goals — won or lost, the match went over.
            #
            # That cannot be derived from the summed goal columns: three matches
            # totalling nine goals could be 3-3, 2-2 or 5-1. It needs the
            # per-match over/under split, which the window helper already
            # computed as `overs` and which over25_forecast.py now writes as
            # home_overs_last_3 / away_overs_last_3.
            #
            # Both sides must reach 3 of 3. One side going 2 of 3 is a fixture
            # out, not a near-miss.
            _need = ["home_overs_last_3", "away_overs_last_3"]
            if all(c in df_filtered.columns for c in _need):
                for _c in _need:
                    _v = pd.to_numeric(df_filtered[_c], errors="coerce")
                    cond = cond & (_v.notna() & (_v >= 3))

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
