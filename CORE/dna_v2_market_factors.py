"""
AlienEdge DNA Engine V2 — Market Factor Mapper
════════════════════════════════════════════════════════════════════════════
This module does NOT recompute any DNA statistic, heuristic, or formula.
It only reads the numbers already produced by CORE/dna_engine_v2.py
(data/team_dna_v2_profiles.json + data/fixture_style_clashes_v2.json) and
compares Home vs Away for a curated set of fields per prediction market,
counting which side "wins" each factor.

This is the server-side source for the fixture-list "DNA count" column
(e.g. "9 : 3") and for the per-market factor breakdown shown on the
full-screen DNA Analysis page. The frontend never performs this comparison
itself — it only renders what this module returns.

Output file: data/dna_v2_market_factors.json
Shape:
{
  "<fixture_id>": {
    "fixture_id": "...",
    "fixture": "Home vs Away",
    "home_team": "...",
    "away_team": "...",
    "markets": {
      "win":     { "home_count": 6, "away_count": 2, "factors": [ {...} ] },
      "gg":      { ... },
      "over25":  { ... },
      "over15":  { ... },
      "unders":  { ... },
      "draw":    { ... },
      "corners": { ... }
    }
  },
  ...
}
"""

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

PROFILES_PATH = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
CLASHES_PATH  = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
OUTPUT_PATH   = os.path.join(DATA_DIR, "dna_v2_market_factors.json")


def _get(profile, section, field):
    """Pull a numeric field out of a team's DNA v2 profile, defaulting to 0."""
    if not profile:
        return 0
    return profile.get(section, {}).get(field, 0) or 0


# ─────────────────────────────────────────────────────────────────────────
# MARKET FACTOR DEFINITIONS
# Each entry: (label, section, field, invert)
#   section  — "Market_Power_Scores" | "Tactical_DNA" | "Raw_Audit_Metrics"
#   field    — key inside that section
#   invert   — True means the LOWER value wins the factor (defensive markets)
# ─────────────────────────────────────────────────────────────────────────
MARKET_FACTORS = {
    "win": [
        ("Win Dominance",        "Market_Power_Scores", "Win_Dominance",     False),
        ("Resistance",           "Raw_Audit_Metrics",   "Resistance_Score",  False),
        ("Passing Control",      "Raw_Audit_Metrics",   "Passing_Control",   False),
        ("Own Pass Quality",     "Raw_Audit_Metrics",   "Own_Pass_Quality_Pct", False),
        ("Tackles",              "Raw_Audit_Metrics",   "Tackles_Avg",       False),
        ("Interceptions",        "Raw_Audit_Metrics",   "Interceptions_Avg", False),
        ("Tempo",                "Tactical_DNA",         "Tempo",            False),
        ("Transition",           "Tactical_DNA",         "Transition_Score", False),
    ],
    "gg": [
        ("BTTS Friction",        "Market_Power_Scores", "BTTS_Friction",     False),
        ("Goal Intent",          "Market_Power_Scores", "Goal_Intent",       False),
        ("Box Dominance",        "Market_Power_Scores", "Box_Dominance",     False),
        ("Big Chances Created",  "Raw_Audit_Metrics",   "Big_Chances_Created", False),
        ("Shots Insidebox",      "Raw_Audit_Metrics",   "Shots_Insidebox",   False),
        ("Dangerous Attacks",    "Raw_Audit_Metrics",   "Dangerous_Attacks", False),
    ],
    "over25": [
        ("Goal Intent",          "Market_Power_Scores", "Goal_Intent",       False),
        ("Box Dominance",        "Market_Power_Scores", "Box_Dominance",     False),
        ("Big Chances Created",  "Raw_Audit_Metrics",   "Big_Chances_Created", False),
        ("Shots Insidebox",      "Raw_Audit_Metrics",   "Shots_Insidebox",   False),
        ("Dangerous Attacks",    "Raw_Audit_Metrics",   "Dangerous_Attacks", False),
        ("Inside Shot Ratio",    "Raw_Audit_Metrics",   "Inside_Shot_Ratio_Pct", False),
    ],
    "over15": [
        ("Goal Intent",          "Market_Power_Scores", "Goal_Intent",       False),
        ("Box Dominance",        "Market_Power_Scores", "Box_Dominance",     False),
        ("Big Chances Created",  "Raw_Audit_Metrics",   "Big_Chances_Created", False),
        ("Shots Insidebox",      "Raw_Audit_Metrics",   "Shots_Insidebox",   False),
        ("Dangerous Attacks",    "Raw_Audit_Metrics",   "Dangerous_Attacks", False),
        ("Inside Shot Ratio",    "Raw_Audit_Metrics",   "Inside_Shot_Ratio_Pct", False),
    ],
    "unders": [
        ("Resistance",           "Raw_Audit_Metrics",   "Resistance_Score",  False),
        ("Win Dominance",        "Market_Power_Scores", "Win_Dominance",     False),
        ("Interceptions",        "Raw_Audit_Metrics",   "Interceptions_Avg", False),
        ("Tackles",              "Raw_Audit_Metrics",   "Tackles_Avg",       False),
        ("Own Pass Quality",     "Raw_Audit_Metrics",   "Own_Pass_Quality_Pct", False),
        ("BTTS Friction",        "Market_Power_Scores", "BTTS_Friction",     True),   # lower chaos favors Under
    ],
    "draw": [
        ("Win Dominance",        "Market_Power_Scores", "Win_Dominance",     False),
        ("BTTS Friction",        "Market_Power_Scores", "BTTS_Friction",     False),
        ("Tempo",                "Tactical_DNA",         "Tempo",            False),
        ("Passing Control",      "Raw_Audit_Metrics",   "Passing_Control",   False),
        ("Resistance",           "Raw_Audit_Metrics",   "Resistance_Score",  False),
    ],
    "corners": [
        ("Corner Power",         "Market_Power_Scores", "Corner_Power",      False),
        ("Avg Corners",          "Raw_Audit_Metrics",   "Avg_Corners",       False),
        ("Estimated Crosses",    "Raw_Audit_Metrics",   "Estimated_Crosses", False),
        ("Estimated Blocks",     "Raw_Audit_Metrics",   "Estimated_Blocks",  False),
    ],
}


def _compare_factor(home_profile, away_profile, label, section, field, invert):
    home_val = _get(home_profile, section, field)
    away_val = _get(away_profile, section, field)

    if invert:
        winner = "home" if home_val < away_val else "away" if away_val < home_val else "neutral"
    else:
        winner = "home" if home_val > away_val else "away" if away_val > home_val else "neutral"

    return {
        "name":       label,
        "home_value": round(home_val, 1),
        "away_value": round(away_val, 1),
        "winner":     winner,
    }


def build_market_counts_for_fixture(home_profile, away_profile):
    """
    Returns the full per-market breakdown for a single fixture's two
    already-computed DNA v2 profiles. Pure comparison — no new math.
    """
    markets = {}
    for market_key, factor_defs in MARKET_FACTORS.items():
        factors = [
            _compare_factor(home_profile, away_profile, *factor_def)
            for factor_def in factor_defs
        ]
        home_count = sum(1 for f in factors if f["winner"] == "home")
        away_count = sum(1 for f in factors if f["winner"] == "away")
        markets[market_key] = {
            "home_count": home_count,
            "away_count": away_count,
            "factors":    factors,
        }
    return markets


def build_market_factor_counts(target_date):
    """
    Callable entrypoint (mirrors the engine's run_* signature) so it can be
    wired into main.py / api/main.py the same way as every other engine.

    Reads the DNA v2 profiles + style clashes already written to disk by
    run_dna_engine_v2(target_date), joins them per fixture, and writes the
    per-market factor-count breakdown to data/dna_v2_market_factors.json.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(PROFILES_PATH) or not os.path.exists(CLASHES_PATH):
        print("⚠️  DNA v2 profiles/clashes not found on disk — run run_dna_engine_v2 first.")
        return {}

    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        profiles = json.load(f)

    with open(CLASHES_PATH, "r", encoding="utf-8") as f:
        clashes = json.load(f)

    result = {}

    for clash in clashes:
        fixture_id = str(clash.get("fixture_id"))
        home_name  = clash.get("home_team")
        away_name  = clash.get("away_team")

        # Profiles are keyed by team_id, not team_name — resolve by name match
        # against the two profiles referenced in this clash (cheap, since the
        # clash was itself built from exactly these two team profiles).
        home_profile = next(
            (p for p in profiles.values() if p.get("team_name") == home_name), None
        )
        away_profile = next(
            (p for p in profiles.values() if p.get("team_name") == away_name), None
        )

        result[fixture_id] = {
            "fixture_id": fixture_id,
            "fixture":    clash.get("fixture"),
            "home_team":  home_name,
            "away_team":  away_name,
            "markets":    build_market_counts_for_fixture(home_profile, away_profile),
        }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4)

    print(f"✅ DNA v2 market factor counts saved for {len(result)} fixtures → {OUTPUT_PATH}")
    return result


if __name__ == "__main__":
    from datetime import datetime, timezone
    build_market_factor_counts(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
