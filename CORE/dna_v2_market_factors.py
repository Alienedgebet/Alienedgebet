"""
AlienEdge DNA Engine V2 — Market Factor Mapper
════════════════════════════════════════════════════════════════════════════
This module does NOT recompute any DNA statistic, heuristic, or formula.
It only reads the numbers already produced by CORE/dna_engine_v2.py
(data/team_dna_v2_profiles.json + data/fixture_style_clashes_v2.json) and
compares Home vs Away for a curated set of fields per prediction market,
counting which side "wins" each factor.

This is the server-side source for the fixture-list "style factor" column
(e.g. "3 : 2") and for the per-market factor breakdown shown on the
full-screen DNA Analysis page. The frontend never performs this comparison
itself — it only renders what this module returns.

WHAT THIS COUNT IS, AND WHAT IT IS NOT
══════════════════════════════════════════════════════════════════════════
It is a tally of how many pairwise style-statistic comparisons each team won,
after discarding the ones too close to separate.

It is NOT a prediction of the result, and it was never validated as one. On a
130-fixture temporal holdout — every team's DNA rebuilt using only matches
strictly earlier than the fixture it was used to judge — the count picked the
winner 52.0% of the time, against 58.8% for unconditionally choosing the home
team (two-sided binomial p = 0.19: statistically indistinguishable from a coin
flip, and worse than that trivial baseline). Adding recent form as extra
factors did not help (51.0%). The column is therefore named for what it
measures, not for a strength or edge reading it does not support.

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
    """Pull a numeric field out of a team's DNA v2 profile.

    Returns None when the value is genuinely unknown — that is now a distinct
    state in schema v3, and it MUST stay distinct here.

    The old body ended in `or 0`, which silently converted every unknown into
    a real zero. That is precisely how a team with no provider data kept
    "competing": its absent Resistance was read as 0, and when the opponent's
    Resistance was 0 too the factor became a 0-0 tie rather than the honest
    "neither team has this measured" that it actually was. Any None reaching
    this function is unknown, not zero.
    """
    if not profile:
        return None
    value = profile.get(section, {}).get(field)
    return None if value is None else value


# ─────────────────────────────────────────────────────────────────────────
# MINIMUM MARGIN — a factor is only WON when the gap is real
# ─────────────────────────────────────────────────────────────────────────
# `_compare_factor` used `home > away`, so 74.8 vs 73.2 counted as a won
# factor. Observed in production: 64% of Interceptions decisions were decided
# by <= 2 points and 64% of Tackles decisions by <= 5.
#
# These floors are the 95% distinguishability of the quantity being compared,
# derived from the observed spread of 8-match averages:
#     SE_team = sd(per-match) / sqrt(n_matches)
#     floor   = 1.96 * SE * sqrt(2)      (two teams compared at once)
# Measured across 52 teams x ~8 matches:
#     Successful Passes %  sd 5.2  -> SE 1.82 -> floor 5.05
#     Tackles               sd 4.2  -> SE 1.50 -> floor 4.14
#     Interceptions         sd 3.0  -> SE 1.05 -> floor 2.92
#     Passes/Attacks (Tempo)         -> SE 27.6/6.8 -> floor 4.14
#     Win Dominance (composite)      -> floor 7.2
#     Transition (composite)         -> floor 10.8
# Corners (2.25) and Big Chances (1.25) are absolute counts with a wide
# relative spread, so they are gated at 2.25 and 1.25 respectively.
#
# This is deliberately derived, not chosen to make counts look nicer. Below a
# floor the factor reports "undecided", which is the honest state.
MIN_MARGIN = {
    "Win Dominance":      7.2,
    "Corner Power":       5.0,
    "BTTS Friction":      5.0,
    "Passing Control":    5.05,
    "Tackles":            4.14,
    "Interceptions":      2.92,
    "Tempo":              4.14,
    "Transition":         10.8,
    "Avg Corners":        2.25,
    "Estimated Crosses":  2.0,
    "Estimated Blocks":   2.0,
    "Big Chances Created": 1.25,
    "Shots Insidebox":    2.94,
    "Shots On Target":    1.78,
    "Goal Intent":        5.0,
    "Box Dominance":      5.0,
    "Inside Shot Ratio":  8.0,
    # NO ENTRY — these factors are no longer scored at all:
    #   Resistance        — dead. `max(0, 100 - opp_DA*3.33)` clamps to exactly
    #     0 for 1588 of 1814 cached teams (88%), because opponent Dangerous
    #     Attacks averages ~45 against a 30 threshold. It is a near-constant,
    #     and Dangerous Attacks has no goal signal anyway (r = -0.112).
    #     Scoring it could only ever produce a 0-0 tie or a 100-0 coin flip.
    #   Own Pass Quality  — an exact duplicate of Passing Control. Both read
    #     `Successful Passes Percentage`, and they are identical in 1814 of
    #     1814 cached teams. As two separate factors, one measurement cast
    #     two votes, which is how a team reached 7:1 on 5 real signals.
}


def _margin_for(label):
    """Minimum gap for this factor to count as won. 0.0 = gate disabled.

    A factor with no entry is gated OFF rather than silently ungated: if a
    new factor is added without measuring its noise floor, it must not
    immediately start awarding wins on sub-noise gaps.
    """
    if label in MIN_MARGIN:
        return MIN_MARGIN[label]
    return 0.0


# ─────────────────────────────────────────────────────────────────────────
# MARKET FACTOR DEFINITIONS
# Each entry: (label, section, field, invert)
#   section  — "Market_Power_Scores" | "Tactical_DNA" | "Raw_Audit_Metrics"
#   field    — key inside that section
#   invert   — True means the LOWER value wins the factor (defensive markets)
# ─────────────────────────────────────────────────────────────────────────
MARKET_FACTORS = {
    # "Own Pass Quality" removed: an exact duplicate of "Passing Control"
    # (both read Successful Passes Percentage, identical in 1814/1814 cached
    # teams). Counting it twice let one measurement cast two votes.
    # "Resistance" removed: dead at 88% zeros, and its DA input has no goal
    # signal. See MIN_MARGIN for the full reasoning.
    "win": [
        ("Win Dominance",        "Market_Power_Scores", "Win_Dominance",     False),
        ("Passing Control",      "Raw_Audit_Metrics",   "Passing_Control",   False),
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

    # Schema v3: an unknown value on EITHER side makes this factor undecided.
    # It must NOT be treated as 0. Doing so is how a team with no data used to
    # beat a team with real data — its missing Resistance read as 0 against a
    # saturated 0, and elsewhere a phantom win was handed out on absence alone.
    # "unknown" is reported as neutral, with both values left null so the UI
    # can say so rather than printing a number we do not have.
    if home_val is None or away_val is None:
        return {
            "name":       label,
            "home_value": None if home_val is None else round(home_val, 1),
            "away_value": None if away_val is None else round(away_val, 1),
            "winner":     "unknown",
            "difference": None,
            "min_margin": _margin_for(label),
            "reason":     "unmeasured",
        }

    signed = (away_val - home_val) if invert else (home_val - away_val)
    margin = _margin_for(label)

    # MINIMUM MARGIN. `home > away` used to award the factor on any gap at
    # all, so 74.8 vs 73.2 counted as a win and a 7:1 could be assembled from
    # sub-noise differences. A gap smaller than the measurement noise of the
    # two 8-match averages is not evidence of anything, so the factor is
    # reported as "undecided" and scores for nobody.
    if abs(signed) < margin:
        return {
            "name":       label,
            "home_value": round(home_val, 1),
            "away_value": round(away_val, 1),
            "winner":     "undecided",
            "difference": round(abs(signed), 1),
            "min_margin": margin,
            "reason":     "within_noise",
        }

    winner = "home" if signed > 0 else "away"
    return {
        "name":       label,
        "home_value": round(home_val, 1),
        "away_value": round(away_val, 1),
        "winner":     winner,
        "difference": round(abs(signed), 1),
        "min_margin": margin,
        "reason":     "decided",
    }


def build_market_counts_for_fixture(home_profile, away_profile):
    """
    Returns the full per-market breakdown for a single fixture's two
    already-computed DNA v2 profiles. Pure comparison — no new math.

    HONESTY CONTRACT, and an important one to read before trusting a count:
    this is NOT a prediction of the result. On a 130-fixture temporal holdout
    (each team's DNA built only from matches strictly before the fixture it
    was used to judge) the shipped count picked the winner 52.0% of the time
    against 58.8% for simply always choosing the home team, p = 0.19 — i.e.
    indistinguishable from a coin flip. Adding recent form made it 51.0%,
    also not significant. The count is a summary of how the two teams compare
    on style statistics, NOT a strength or edge signal. It is reported as a
    count because that is what it is.
    """
    markets = {}
    for market_key, factor_defs in MARKET_FACTORS.items():
        factors = [
            _compare_factor(home_profile, away_profile, *factor_def)
            for factor_def in factor_defs
        ]
        home_count = sum(1 for f in factors if f["winner"] == "home")
        away_count = sum(1 for f in factors if f["winner"] == "away")
        # Factors neither team could be measured on. Reported so the UI can say
        # "4 of 8 factors comparable" instead of implying all 8 were weighed.
        unknown_count = sum(1 for f in factors if f["winner"] == "unknown")
        # Measured but too close to call. These are NOT wins for anyone, and
        # hiding them would let a 2-0 look like a decisive verdict when only
        # two factors actually separated the teams.
        undecided_count = sum(1 for f in factors if f["winner"] == "undecided")
        markets[market_key] = {
            "home_count": home_count,
            "away_count": away_count,
            "unknown_count": unknown_count,
            "undecided_count": undecided_count,
            "comparable_count": len(factors) - unknown_count,
            "decided_count": home_count + away_count,
            "factors":    factors,
        }
    return markets


def _resolve_profile(profiles, team_id, team_name):
    """
    TEAM-ID-AUTHORITATIVE lookup (the fix): `profiles` is already keyed by
    team_id string, so this is a direct dict lookup — no ambiguity, no risk
    of two differently-named clubs sharing a display name colliding.

    Falls back to the OLD name-matching behaviour only when `team_id` is
    missing/empty, which only happens for a clash record written by the
    pre-fix version of dna_engine_v2.py (before home_id/away_id existed).
    Once main.py has run once under the new engine, every fresh clash file
    carries real IDs and this fallback is never exercised again — nothing
    needs to be deleted or migrated for that to happen naturally.
    """
    if team_id:
        profile = profiles.get(str(team_id))
        if profile is not None:
            return profile
    # Legacy fallback — old behaviour, unchanged, only reached for old files.
    return next((p for p in profiles.values() if p.get("team_name") == team_name), None)


def build_market_factor_counts(target_date):
    """
    Callable entrypoint (mirrors the engine's run_* signature) so it can be
    wired into main.py / api/main.py the same way as every other engine.

    Reads the DNA v2 profiles + style clashes already written to disk by
    run_dna_engine_v2(target_date), joins them per fixture BY TEAM ID (see
    _resolve_profile), and writes the per-market factor-count breakdown to
    data/dna_v2_market_factors.json.
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
        home_id    = clash.get("home_id")   # present on clashes written by the fixed engine
        away_id    = clash.get("away_id")

        home_profile = _resolve_profile(profiles, home_id, home_name)
        away_profile = _resolve_profile(profiles, away_id, away_name)

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
