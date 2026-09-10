"""
inspect_output.py — trust-but-verify tool.
Run this ON THE SERVER after main.py has completed at least one real run.
It does NOT guess anything — it opens every file main.py actually wrote
under output/cache/ and reports, per engine, per field:
  MISSING  — a field api/main.py's defaults expect, that the real saved
             file does NOT contain. These are the dangerous ones: they are
             currently being silently replaced with a fake "0" / "" / False
             by ensure_defaults() instead of showing real data, and nothing
             on the frontend will visibly complain.
  EXTRA    — a field the real file HAS that api/main.py's defaults never
             mentioned. Harmless (the API just passes it through unused),
             but worth knowing in case it's actually the field you meant
             MISSING to be named.
  ROWS     — how many actual prediction rows were found, and whether ANY
             engine key has zero rows (pipeline ran, but produced nothing).
Usage:
    cd /var/www/backend
    python inspect_output.py 2026-09-08
Then send me the full printed output (or the .txt it also saves) and I'll
correct every mismatch in api/main.py's *_DEFAULTS dicts against the real
field names instead of the TypeScript-file guesses I started from.
"""
import sys
import os
import json

# Auto-detect ROOT cleanly whether placed in root (/var/www/backend) or in deploy/
ROOT = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(ROOT, "output_store.py")):
    ROOT = os.path.dirname(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import output_store as store  # noqa: E402

# Field names api/main.py currently EXPECTS per engine key — copied straight
# from the *_DEFAULTS dicts in api/main.py. If you change those dicts,
# update this list to match so the diff stays meaningful.
EXPECTED_FIELDS = {
    "underdog_base": ["fixture_id", "fixture", "league", "underdog_team", "dog_odds",
        "dog_score_prob", "parity_gap", "dog_att_strength", "fav_def_weakness",
        "dog_is_hot", "dog_due_goal", "both_no_draw_3", "fav_vulnerability_5",
        "fav_cs_streak", "h2h_dog_gs_last_5", "dog_venue_wins"],
    "underdog_audit": ["fixture_id", "fixture", "underdog_team", "Audit_Real_Prob",
        "Dog_Score_Prob", "Fav_Spear_Power", "Dominance_Gap", "Audit_Verdict",
        "parity_gap", "dog_is_hot", "dog_due_goal", "fav_cs_streak"],
    "underdog_apex": ["fixture_id", "Fixture", "Rank", "Monte_UD_Prob", "Engine",
        "Handshake", "DNA", "Rule", "Fav_Vuln", "SH_GG_Label"],
    "win_forecast": ["fixture_id", "fixture", "side", "team_name", "win_odds",
        "poisson_win_prob", "poisson_draw_prob", "last_5_wins_overall",
        "last_5_wins_at_venue", "last_5_goals_scored", "opp_last_5_goals_scored",
        "opp_last_5_losses", "opp_last_5_conceded_raw", "opp_no_clean_sheet_count",
        "h2h_wins_last_5", "last_3_no_draw_BOTH", "parity_score", "parity_even_count"],
    "sh_gg_winner": ["fixture_id", "league", "kickoff_datetime", "teams",
        "pick_labels", "flags", "metrics"],
    "win_psychology": ["Fixture", "Master_Pick", "Master_Prob", "Audit_Score",
        "H_Base", "A_Base", "Tier", "Spears", "H_Quality", "A_Quality",
        "Home_Logic", "Away_Logic"],
    "u2s_psychology": ["Fixture", "Underdog", "Audit_Verdict", "Spear_Matchup",
        "Dog_Venue_SOT", "Fav_Venue_SOT", "Dog_H2H_SOT", "Fav_H2H_SOT",
        "Dog_Opp_Avg_Conceded", "Fav_Opp_Avg_Conceded", "Dog_Scoring_Consistency",
        "Psych_Score", "Tier", "Triggers"],
    "win_apex": ["fixture_id", "Fixture", "Target", "Category", "Cat_Priority",
        "Monte_Win_Prob", "Monte_Draw_Prob", "Lambda_Detail", "Underdog_Risk",
        "Psych_Score", "Psych_Logic", "Chokehold_Status", "Veto_Reason"],
    "win_raw": ["fixture_id", "fixture", "side", "team_name", "win_odds",
        "last_5_wins_overall", "last_5_wins_at_venue", "last_5_goals_scored",
        "opp_last_5_goals_scored", "opp_last_5_losses", "opp_last_5_conceded_raw",
        "opp_no_clean_sheet_count", "h2h_wins_last_5", "last_3_no_draw_BOTH",
        "parity_score", "parity_even_count"],
    "gg_forensics": ["fixture_id", "league_id", "Fixture", "Score",
        "DNA_Intelligence", "Poisson%", "H2H_GG", "DNA_Insight", "Ranks",
        "Forensic_Audit"],
    "gg_psychology": ["Fixture", "MC_Rank", "MC_Prob", "Psych_Score", "Spears",
        "Tier", "Psych_Triggers"],
    "gg_supreme": ["fixture_id", "Fixture", "Category", "Cat_Priority",
        "Monte_GG_Prob", "NGG_Risk", "Base_Marks", "DNA_Status", "Psych_Score",
        "Psych_Triggers", "VIP_Status", "Veto_Status", "Spears"],
    "over25_stage1": ["id", "fixture", "Time", "Odds", "Confidence", "Algorithm"],
    "over25_stage2": ["id", "fixture", "Time", "Votes", "Odds", "Algorithm", "Reasons"],
    "over25_stage3": ["Match", "Odds", "Poisson%", "Grade", "GradeNum",
        "H2H_Record", "PickedBy", "Failures"],
    "over25_psychology": ["Fixture", "Base_Poisson", "Base_Grade", "Score", "Tier", "Reasons"],
    "over25_apex": ["fixture_id", "Fixture", "Category", "Cat_Priority",
        "Super_Monte_Prob", "U25_Risk", "Base_Grade", "DNA_Status", "Psych_Score",
        "Psych_Triggers", "VIP_Status", "Veto_Status"],
    "over25_forecast": ["fixture_id", "league", "fixture", "o25_odds",
        "kill_switch_pass", "poisson_over_prob_num", "council_votes", "pos_gap",
        "parity_diff", "h2h_overs_last_5", "combined_gs_last_5"],
    "over15_stage3": ["Match", "Odds", "Poisson%", "Grade", "GradeNum",
        "H2H_Record", "PickedBy", "Failures"],
    "over15_psychology": ["Fixture", "Base_Poisson", "Base_Grade", "Score", "Tier", "Reasons"],
    "over15_apex": ["Fixture", "Base_Poisson", "Base_Grade", "Score", "Tier", "Reasons"],
    "corners_stage1": ["fixture_id", "fixture", "expected_total_corners",
        "corner_tier", "expected_difference", "team_more_corners",
        "team_more_corners_probability_like", "avg_confidence", "home_win_odds",
        "over_2_5_odds", "tier_1_priority"],
    "corners_stage2": ["fixture_id", "fixture", "stage1_predicted_corners",
        "stage2_predicted_corners", "expected_total_corners", "corner_tier",
        "style_alignment", "expected_difference", "avg_confidence",
        "home_is_persistent_venue", "away_is_persistent_venue",
        "home_is_persistent_overall", "away_is_persistent_overall"],
    "corners_psychology": ["fixture_name", "home_position", "away_position",
        "friction_grade", "standings_gap", "tactical_intelligence_grade",
        "tactical_note", "is_wounded_beast", "wounded_reason", "wounded_team_name"],
    "corners_catalyst": ["fixture_name", "predicted_corners", "corner_tier",
        "home_position", "away_position", "friction_grade",
        "home_is_wounded_beast", "home_wounded_intensity",
        "away_is_wounded_beast", "away_wounded_intensity"],
    "corners_aggregator": ["Fixture", "Master_Score", "Chaos_Rating", "Tier",
        "True_Corner_Fav", "Match_Flow", "U2.5%", "UD_Prob", "NB_Prob",
        "Total_Exp", "Home_Pos", "Away_Pos", "Friction", "Home_Wounded",
        "Home_Wound_Int", "Away_Wounded", "Away_Wound_Int", "Home_Team",
        "Away_Team", "Home_Score", "Away_Score", "Home_Label", "Away_Label",
        "Home_DNA", "Away_DNA", "Home_SH_Ratio", "Away_SH_Ratio"],
    "sot": ["Fixture", "Verdict", "Proj_SOT", "Poisson_Over_8.5", "Consistency",
        "Game_Script", "Momentum", "1x2_Home_Odd"],
    "fhvi": ["fixture", "ht_score", "ft_score", "fhvi_score", "fhvi_label",
        "fh_pressure", "country", "comb_fh_r", "avg_sh_goals", "h_fh_r_disp",
        "a_fh_r_disp", "h_fh_c_r_disp", "a_fh_c_r_disp", "Category"],
    "shvi": ["fixture", "ht_score", "ft_score", "shvi_score", "shvi_label",
        "sh_pressure", "country", "comb_sh_r", "avg_fh_goals", "h_sh_r_disp",
        "a_sh_r_disp", "h_sh_c_r_disp", "a_sh_c_r_disp", "Category"],
    "sh_master": ["fixture", "league", "shvi_score", "sh_pressure", "ht", "ft",
        "sh_scoring_rate", "avg_fh_goals", "late_threat"],
    "sh_8goal": ["Fixture_ID", "League", "Time", "Fixture", "H_Goals_L5",
        "A_Goals_L5", "Labels", "Status"],
}

EXPECTED_OUTPUT_KEYS = [
    # ------------------------------------------------------------------------
    # PHASE 1 — FOUNDATION & DNA
    # ------------------------------------------------------------------------
    "dna",
    "dna_v2",
    "dna_market_factors",
    "underdog_base",
    "underdog_audit",
    "calibration",
    "underdog_apex",
    "win_forecast",
    "sh_gg_winner",
    # ------------------------------------------------------------------------
    # PHASE 2 — CORNER EMPIRE
    # ------------------------------------------------------------------------
    "corners_stage1",
    "corners_stage2",
    "corners_psychology",
    "corners_catalyst",
    "corners_aggregator",
    # ------------------------------------------------------------------------
    # GG + OVER 1.5 UNIFIED HEAD
    # ------------------------------------------------------------------------
    "gg_o15",
    # ------------------------------------------------------------------------
    # GG FORENSIC PIPELINE
    # ------------------------------------------------------------------------
    "gg_forensics",
    "gg_psychology",
    "gg_supreme",
    # ------------------------------------------------------------------------
    # OVER 2.5 PIPELINE
    # ------------------------------------------------------------------------
    "over25_stage1",
    "over25_stage2",
    "over25_stage3",
    "over25_psychology",
    "over25_gold",
    "over25_apex",
    "over25_forecast",
    # ------------------------------------------------------------------------
    # OVER 1.5 PIPELINE
    # ------------------------------------------------------------------------
    "over15_stage3",
    "over15_psychology",
    "over15_apex",
    # ------------------------------------------------------------------------
    # DEFENSIVE UNDER EMPIRE
    # ------------------------------------------------------------------------
    "unders",
    # ------------------------------------------------------------------------
    # DRAW
    # ------------------------------------------------------------------------
    "draw",
    # ------------------------------------------------------------------------
    # SOT / FHVI / SHVI
    # ------------------------------------------------------------------------
    "sot",
    "fhvi",
    "shvi",
    # ------------------------------------------------------------------------
    # WIN / U2S / SH MASTER
    # ------------------------------------------------------------------------
    "u2s_psychology",
    "win_psychology",
    "win_apex",
    "sh_master",
    "sh_8goal",
    "win_raw",
    # ------------------------------------------------------------------------
    # GG FILTER
    # ------------------------------------------------------------------------
    "filter_gg",
    # ------------------------------------------------------------------------
    # OVER 2.5 FILTERS
    # ------------------------------------------------------------------------
    "filter_over25__banker",
    "filter_over25__balanced",
    "filter_over25__aggressive",
    # ------------------------------------------------------------------------
    # WIN FILTERS
    # ------------------------------------------------------------------------
    "filter_win__safe",
    "filter_win__balanced",
    "filter_win__aggressive",
]

# Composite (tuple-shaped) keys need special handling — each index of the
# saved list maps to a different sub-schema.
COMPOSITE_KEYS = {
    "gg_o15": [("gg", EXPECTED_FIELDS.get("gg_forensics", []) and [
        "fixture_id", "fixture", "home_team", "away_team", "league_id",
        "lambda_home", "lambda_away", "combined_lambda", "mc_btts_prob",
        "venue_btts_combined", "h2h_btts_rate", "home_gk_liable", "away_gk_liable",
        "home_gk_cpg", "away_gk_cpg", "home_gk_note", "away_gk_note",
        "fatigue_home", "fatigue_away", "league_weight", "gg_score",
        "gg_signals_fired", "gg_tier"]),
        ("o15", ["fixture_id", "fixture", "home_team", "away_team", "league_id",
        "o15_tier", "o15_score", "combined_lambda", "mc_over15_prob",
        "combined_venue_goals_avg", "venue_goals_avg_home", "venue_goals_avg_away",
        "fatigue_home", "fatigue_away", "league_weight"])],
    "draw": [("draws", ["fixture_id", "fixture", "home_team", "away_team", "tier",
        "composite_draw_score", "mc_draw_prob", "poisson_draw_prob", "dmi",
        "parity", "draw_odds", "value_edge", "most_likely_draw_score",
        "most_likely_draw_pct", "home_draws", "away_draws", "h2h_draws",
        "total_draws"]),
        ("parity_list", []), ("amateurs_list", [])],
    "unders": [("u25", ["fixture_id", "fixture", "home_team", "away_team",
        "combined_lambda", "mc_u25_prob", "u25_score", "u25_tier",
        "home_gk_cpg", "away_gk_cpg", "fatigue_home", "fatigue_away"]),
        ("u35", [])],
}

def inspect_simple(key, date, expected):
    data, generated_at = store.load(key, date, default=None)
    if data is None:
        status = store.load_status(key, date)
        print(f"\n[{key}]  STATUS: {status['status'].upper()}  "
              f"generated_at={status['generated_at']}  error={status['error']}")
        return
    rows = data if isinstance(data, list) else []
    print(f"\n[{key}]  rows={len(rows)}  generated_at={generated_at}")
    if not rows:
        print("   (no rows to inspect field names against)")
        return
    sample = rows[0] if isinstance(rows[0], dict) else {}
    real_keys = set(sample.keys())
    expected_keys = set(expected)
    missing = sorted(expected_keys - real_keys)
    extra = sorted(real_keys - expected_keys)
    if missing:
        print(f"   ❌ MISSING (api/main.py expects these, real data doesn't have them):")
        for m in missing:
            print(f"        - {m}")
    if extra:
        print(f"   ➕ EXTRA (real data has these, api/main.py never mentioned them):")
        for e in extra:
            print(f"        - {e}  (sample value: {sample.get(e)!r})")
    if not missing and not extra:
        print("   ✅ Exact match — every expected field is present, no unknown extras.")

def inspect_composite(key, date, sub_schemas):
    data, generated_at = store.load(key, date, default=None)
    if data is None:
        status = store.load_status(key, date)
        print(f"\n[{key}]  STATUS: {status['status'].upper()}  "
              f"generated_at={status['generated_at']}  error={status['error']}")
        return
    print(f"\n[{key}]  (composite/tuple engine)  generated_at={generated_at}")
    if not isinstance(data, list):
        print(f"   ❌ UNEXPECTED SHAPE: expected a list-of-lists (tuple), got {type(data).__name__}")
        return
    for i, (label, expected) in enumerate(sub_schemas):
        sub = data[i] if i < len(data) else None
        rows = sub if isinstance(sub, list) else []
        print(f"   -> index {i} ('{label}'): rows={len(rows)}")
        if not expected:
            continue
        if rows and isinstance(rows[0], dict):
            real_keys = set(rows[0].keys())
            expected_keys = set(expected)
            missing = sorted(expected_keys - real_keys)
            extra = sorted(real_keys - expected_keys)
            if missing:
                print(f"      ❌ MISSING: {missing}")
            if extra:
                print(f"      ➕ EXTRA: {extra}")

# ============================================================================
# COMPLETE OUTPUT PRESENCE / STATUS AUDIT
# ============================================================================
def inspect_output_presence(key, date):
    status = store.load_status(key, date)
    state = status.get("status", "missing")
    generated_at = status.get("generated_at")
    row_count = status.get("row_count", 0)
    error = status.get("error")
    if state == "ok":
        if row_count == 0:
            print(
                f"   🟡 OUTPUT OK BUT EMPTY | rows=0 | "
                f"generated_at={generated_at}"
            )
        else:
            print(
                f"   ✅ OUTPUT OK | rows={row_count} | "
                f"generated_at={generated_at}"
            )
    elif state == "failed":
        print(
            f"   ❌ OUTPUT FAILED | rows={row_count} | "
            f"generated_at={generated_at} | error={error}"
        )
    elif state == "unreadable":
        print(
            f"   ❌ OUTPUT UNREADABLE | rows={row_count} | "
            f"generated_at={generated_at} | error={error}"
        )
    else:
        print(
            f"   ❌ OUTPUT MISSING | "
            f"generated_at={generated_at} | error={error}"
        )

def inspect_all_main_outputs(date):
    print("\n" + "=" * 90)
    print(" COMPLETE MAIN.PY OUTPUT PRESENCE / STATUS AUDIT")
    print("=" * 90)
    print(f" Date: {date}")
    print(f" Expected output keys: {len(EXPECTED_OUTPUT_KEYS)}")
    print("=" * 90)
    ok_count = 0
    empty_count = 0
    failed_count = 0
    missing_count = 0
    unreadable_count = 0
    for key in EXPECTED_OUTPUT_KEYS:
        print(f"\n[{key}]")
        status = store.load_status(key, date)
        state = status.get("status", "missing")
        row_count = status.get("row_count", 0)
        inspect_output_presence(date=date, key=key)
        if state == "ok" and row_count > 0:
            ok_count += 1
        elif state == "ok" and row_count == 0:
            empty_count += 1
        elif state == "failed":
            failed_count += 1
        elif state == "unreadable":
            unreadable_count += 1
        else:
            missing_count += 1
    print("\n" + "-" * 90)
    print(" COMPLETE MAIN.PY OUTPUT SUMMARY")
    print("-" * 90)
    print(f"   Expected outputs : {len(EXPECTED_OUTPUT_KEYS)}")
    print(f"   ✅ OK with rows   : {ok_count}")
    print(f"   🟡 OK but empty   : {empty_count}")
    print(f"   ❌ FAILED         : {failed_count}")
    print(f"   ❌ MISSING        : {missing_count}")
    print(f"   ❌ UNREADABLE     : {unreadable_count}")
    operational_success = ok_count
    operational_problems = (
        empty_count
        + failed_count
        + missing_count
        + unreadable_count
    )
    print("-" * 90)
    print(
        f"   Operationally populated outputs: "
        f"{operational_success}/{len(EXPECTED_OUTPUT_KEYS)}"
    )
    print(
        f"   Outputs requiring attention: "
        f"{operational_problems}/{len(EXPECTED_OUTPUT_KEYS)}"
    )
    print("-" * 90)
    return {
        "expected": len(EXPECTED_OUTPUT_KEYS),
        "ok": ok_count,
        "empty": empty_count,
        "failed": failed_count,
        "missing": missing_count,
        "unreadable": unreadable_count,
    }

# ============================================================================
# VERIFY THAT EXPECTED_OUTPUT_KEYS AND FIELD SCHEMAS DO NOT CONTRADICT EACH
# OTHER
# ============================================================================
def inspect_schema_coverage():
    expected_set = set(EXPECTED_OUTPUT_KEYS)
    schema_set = set(EXPECTED_FIELDS.keys())
    composite_set = set(COMPOSITE_KEYS.keys())
    covered_by_schema = schema_set & expected_set
    missing_field_schema = expected_set - schema_set - composite_set
    unknown_schema_entries = schema_set - expected_set
    duplicate_shape_entries = schema_set & composite_set
    print("\n" + "=" * 90)
    print(" SCHEMA COVERAGE AUDIT")
    print("=" * 90)
    print(f" Main.py output keys covered operationally : {len(expected_set)}")
    print(f" Simple field schemas available           : {len(covered_by_schema)}")
    print(f" Composite schemas available              : {len(composite_set)}")
    print(
        f" Outputs without field schema yet         : "
        f"{len(missing_field_schema)}"
    )
    if missing_field_schema:
        print("\n   ℹ️ These outputs ARE checked for existence/status/row count,")
        print("      but their exact field names are not guessed:")
        for key in sorted(missing_field_schema):
            print(f"      - {key}")
    if unknown_schema_entries:
        print("\n   ⚠️ EXPECTED_FIELDS contains keys not present in main.py's")
        print("      expected output list:")
        for key in sorted(unknown_schema_entries):
            print(f"      - {key}")
    if duplicate_shape_entries:
        print("\n   ℹ️ These keys have both a simple schema entry and a")
        print("      composite schema entry; composite handling takes priority:")
        for key in sorted(duplicate_shape_entries):
            print(f"      - {key}")
    if not missing_field_schema and not unknown_schema_entries:
        print("\n   ✅ Schema coverage is aligned with the operational output list.")
    print("=" * 90)

# ============================================================================
# OPTIONAL FILE INVENTORY
# ============================================================================
def inspect_cache_files_for_date(date):
    cache_dir = store.CACHE_DIR
    print("\n" + "=" * 90)
    print(" PHYSICAL output/cache FILE INVENTORY")
    print("=" * 90)
    print(f" Cache directory: {cache_dir}")
    print(f" Date filter: {date}")
    print("=" * 90)
    if not os.path.isdir(cache_dir):
        print("   ❌ output/cache directory does not exist.")
        return
    try:
        filenames = sorted(os.listdir(cache_dir))
    except Exception as e:
        print(f"   ❌ Could not list output/cache: {e}")
        return
    date_suffix = f"__{date}.json"
    matching_files = [
        name for name in filenames
        if name.endswith(date_suffix)
    ]
    if not matching_files:
        print("   ❌ No date-specific cache files found.")
        return
    print(f"   Files found for {date}: {len(matching_files)}")
    for filename in matching_files:
        full_path = os.path.join(cache_dir, filename)
        try:
            size = os.path.getsize(full_path)
        except OSError:
            size = -1
        print(f"   📄 {filename} | bytes={size}")
    print("=" * 90)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_output.py YYYY-MM-DD")
        sys.exit(1)
    target_date = sys.argv[1]
    print("=" * 90)
    print(
        " FIELD-NAME AUDIT — comparing api/main.py's assumptions "
        "against REAL saved output"
    )
    print(f" Date: {target_date}")
    print("=" * 90)
    summary = inspect_all_main_outputs(target_date)
    print("\n" + "=" * 90)
    print(" FIELD-NAME / SCHEMA AUDIT")
    print("=" * 90)
    for key, expected in EXPECTED_FIELDS.items():
        if key in COMPOSITE_KEYS:
            continue
        inspect_simple(key, target_date, expected)
    for key, sub_schemas in COMPOSITE_KEYS.items():
        inspect_composite(key, target_date, sub_schemas)
    inspect_schema_coverage()
    inspect_cache_files_for_date(target_date)
    print("\n" + "=" * 90)
    print(" FINAL INSPECTION SUMMARY")
    print("=" * 90)
    print(f" Date inspected: {target_date}")
    print(f" Main.py output keys audited: {summary['expected']}")
    print(f" ✅ Successful with rows: {summary['ok']}")
    print(f" 🟡 Successful but empty: {summary['empty']}")
    print(f" ❌ Failed: {summary['failed']}")
    print(f" ❌ Missing: {summary['missing']}")
    print(f" ❌ Unreadable: {summary['unreadable']}")
    print("=" * 90)
