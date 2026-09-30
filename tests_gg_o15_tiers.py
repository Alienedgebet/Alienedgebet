"""
tests_gg_o15_tiers.py — the GG / Over 1.5 tier contract must not drift.

Run:  ./venv/bin/python3 tests_gg_o15_tiers.py

WHAT THIS PROVES
----------------
The tier LABELS are a cross-module contract, not display text. Three consumers
regex-match them to decide what survives:

  Engine/over15_stage3.py:167   df["o15_tier"].str.contains("TIER 1|TIER 2")
  AGGREGATOR/gg_forensics_audit.py:224  df["gg_tier"].str.contains("TIER 1")
  FILTER/gg_precision_filter.py  _last3_from_tier() — regex TIER\\s*([1-9]),
                                 mapping TIER 1 -> 3 and TIER 2 -> 2

Renaming a tier, renumbering it, or dropping the "TIER n" substring silently
empties those filters: the file still parses, the pipeline still runs, and the
downstream board just quietly returns nothing.

This suite pins:
  1. every tier label string, byte for byte
  2. that each label survives the three consumers' own regex/substring logic
  3. that the threshold ladders are monotone (a higher score never scores worse)
  4. that the scorers return a bounded 0-100 score and a populated breakdown
  5. that the artifact filenames main.py depends on are still registered
  6. that the Phase 1 / Phase 2 weights stay where the measurements put them
  7. the PROXY suppression that Phase 3 proposed and the data refused

SAFETY (deliberate, enforced): fully offline — the scorers under test take only
already-computed scalars, so the suite makes zero network calls and writes
nothing. Import is guarded so a missing dependency reports SKIP, never a false
PASS.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

RESULTS = []


def check(label, cond):
    RESULTS.append((label, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + label)


def skip(label, why):
    RESULTS.append((label, None))
    print("SKIP  " + label + "  (" + why + ")")


try:
    from Engine.gg_precision_engine import (
        get_gg_tier,
        get_o15_tier,
        calculate_gg_score,
        calculate_o15_score,
    )
except Exception as exc:  # pragma: no cover - reported as SKIP, never PASS
    skip("engine import", f"{type(exc).__name__}: {exc}")
    print("\nRESULT: engine could not be imported; nothing was verified")
    sys.exit(2)

# ── 1. THE LABEL CONTRACT (byte-for-byte) ─────────────────────────────────────
GG_T1_LOCK = "\U0001f48e GG TIER 1 — LOCK"
GG_T1_HIGH = "\U0001f525 GG TIER 1 — HIGH CONFIDENCE"
GG_T2 = "✅ GG TIER 2 — SOLID"
GG_T3 = "\U0001f4ca GG TIER 3 — LEAN"
GG_OUT = "⚪ GG BELOW THRESHOLD"
O15_T1 = "\U0001f48e O1.5 TIER 1 — LOCK"
O15_T2 = "✅ O1.5 TIER 2 — SOLID"
O15_T3 = "\U0001f4ca O1.5 TIER 3 — LEAN"
O15_OUT = "⚪ O1.5 BELOW THRESHOLD"

check("GG Tier 1 lock label is byte-exact", get_gg_tier(70.0, 4) == GG_T1_LOCK)
check("GG Tier 1 high-confidence label is byte-exact",
      get_gg_tier(70.0, 3) == GG_T1_HIGH)
check("GG Tier 2 label is byte-exact", get_gg_tier(55.0, 2) == GG_T2)
check("GG Tier 3 label is byte-exact", get_gg_tier(40.0, 1) == GG_T3)
check("GG below-threshold label is byte-exact", get_gg_tier(10.0, 0) == GG_OUT)
check("O1.5 Tier 1 label is byte-exact", get_o15_tier(75.0) == O15_T1)
check("O1.5 Tier 2 label is byte-exact", get_o15_tier(55.0) == O15_T2)
check("O1.5 Tier 3 label is byte-exact", get_o15_tier(40.0) == O15_T3)
check("O1.5 below-threshold label is byte-exact", get_o15_tier(10.0) == O15_OUT)

# ── 2. THE THREE CONSUMERS STILL MATCH THE LABELS ────────────────────────────
# Engine/over15_stage3.py:167 — keeps "TIER 1|TIER 2" on the O1.5 column.
o15_kept = [o for o in (O15_T1, O15_T2, O15_T3, O15_OUT)
            if re.search("TIER 1|TIER 2", o, re.IGNORECASE)]
check("over15_stage3 keeps exactly the O1.5 Tier 1 and Tier 2 rows",
      o15_kept == [O15_T1, O15_T2])

# AGGREGATOR/gg_forensics_audit.py:224 — keeps "TIER 1" on the GG column.
gg_kept = [g for g in (GG_T1_LOCK, GG_T1_HIGH, GG_T2, GG_T3, GG_OUT)
           if re.search("TIER 1", g, re.IGNORECASE)]
check("gg_forensics_audit keeps both GG Tier 1 variants and nothing else",
      gg_kept == [GG_T1_LOCK, GG_T1_HIGH])

# FILTER/gg_precision_filter.py — _last3_from_tier(): TIER 1 -> 3, TIER 2 -> 2.
def _last3_from_tier(tier):
    """Copy of gg_precision_filter._last3_from_tier (regex-identical)."""
    t = str(tier or "").upper()
    m = re.search(r"TIER\s*([1-9])", t)
    if not m:
        return None
    n = int(m.group(1))
    if n == 1:
        return 3
    if n == 2:
        return 2
    return None


check("gg_precision_filter reads TIER 1 as last-3 form",
      _last3_from_tier(GG_T1_LOCK) == 3)
check("gg_precision_filter reads TIER 2 as partial form",
      _last3_from_tier(GG_T2) == 2)
check("gg_precision_filter returns None for a non-tier label",
      _last3_from_tier(GG_OUT) is None)

# ── 3. THE LADDERS ARE MONOTONE AND BOUNDED ──────────────────────────────────
check("GG tier never downgrades as the score rises",
      [get_gg_tier(s, 4) for s in (0, 35, 50, 68, 100)] ==
      [GG_OUT, GG_T3, GG_T2, GG_T1_LOCK, GG_T1_LOCK])
check("O1.5 tier never downgrades as the score rises",
      [get_o15_tier(s) for s in (0, 38, 51, 69, 100)] ==
      [O15_OUT, O15_T3, O15_T3, O15_T2, O15_T1])
check("GG Tier 1 requires the signals gate, not the score alone",
      get_gg_tier(90.0, 1) != GG_T1_LOCK)

# ── 4. THE SCORERS STAY PURE AND BOUNDED ─────────────────────────────────────
gg_args = dict(btts_prob=0.55, venue_btts_home=0.6, venue_btts_away=0.5,
               home_gk_is_liability=False, away_gk_is_liability=False,
               home_gk_cpg=1.2, away_gk_cpg=1.1, h2h_btts_rate=0.6,
               lambda_home=1.4, lambda_away=1.3)
gg_score, gg_fired, gg_bd = calculate_gg_score(**gg_args)
check("calculate_gg_score returns a 0-100 score", 0.0 <= gg_score <= 100.0)
check("calculate_gg_score returns an integer signal count 0-5",
      isinstance(gg_fired, int) and 0 <= gg_fired <= 5)
check("calculate_gg_score returns a populated breakdown",
      isinstance(gg_bd, dict) and len(gg_bd) >= 8)
check("calculate_gg_score is deterministic (no RNG, no clock)",
      calculate_gg_score(**gg_args)[0] == gg_score)

o15_args = dict(lambda_home=1.4, lambda_away=1.3, mc_over15_prob=0.78,
                venue_goals_avg_home=2.6, venue_goals_avg_away=2.4,
                league_weight=0.24, fatigue_home=0.3, fatigue_away=0.2,
                home_scored_total=7.0, away_scored_total=6.0,
                home_conceded_total=5.0, away_conceded_total=4.0,
                home_gk_cpg=1.2, away_gk_cpg=1.1,
                home_gk_liable=False, away_gk_liable=False,
                h2h_o15_rate=0.6)
try:
    o15_score, o15_bd = calculate_o15_score(**o15_args)
    check("calculate_o15_score returns a 0-100 score", 0.0 <= o15_score <= 100.0)
    check("calculate_o15_score returns a populated breakdown",
          isinstance(o15_bd, dict) and len(o15_bd) >= 5)
    check("calculate_o15_score is deterministic (no RNG, no clock)",
          calculate_o15_score(**o15_args)[0] == o15_score)
except TypeError as exc:
    # A signature change is itself a contract break for callers that build the
    # argument set by name; report it rather than crashing the suite.
    check(f"calculate_o15_score accepts its documented signature ({exc})", False)

# ── 4b. PHASE 1: the retired terms must have ZERO influence ─────────────────
# Measured as noise on 1,461 settled matches and removed 2026-09-30. This
# pins that fact so nobody re-adds them, and so a future change that starts
# using them again fails loudly rather than silently restoring dead weight.
try:
    from Engine.gg_precision_engine import O15_REMOVED_TERMS
except Exception:
    O15_REMOVED_TERMS = ("sig4_league_weight", "sig5_fatigue_penalty",
                         "gk_leak_bonus", "user_form_scoring",
                         "user_form_conceding")

noisy = dict(o15_args)
noisy.update(home_scored_total=99.0, away_scored_total=99.0,
             home_conceded_total=99.0, away_conceded_total=99.0,
             home_gk_cpg=9.0, away_gk_cpg=9.0,
             home_gk_liable=True, away_gk_liable=True,
             fatigue_home=1.0, fatigue_away=1.0, league_weight=0.95)
try:
    check("retired O1.5 terms have zero influence on the score",
          calculate_o15_score(**noisy)[0] == calculate_o15_score(**o15_args)[0])
    _bd = calculate_o15_score(**o15_args)[1]
    check("retired O1.5 columns are still emitted, pinned at 0.0",
          all(k in _bd and _bd[k] == 0.0 for k in O15_REMOVED_TERMS))
except TypeError:
    check("retired-term invariance check could not run", False)

# ── 4c. PHASE 1: the new draw-odds term is monotone and safe ───────────────
# A SHORT draw price (market does not expect a stalemate) must be the strong
# Over 1.5 case. This caught a real inverted-scale bug during Phase 1, where
# the term normalised implied PROBABILITY against a 0.50 floor and therefore
# scored ZERO for exactly the fixtures it was meant to reward.
try:
    bonuses = []
    for price in (1.10, 1.40, 1.80, 2.20, None, "not-a-number"):
        try:
            bonuses.append(calculate_o15_score(**o15_args,
                                               draw_odds=price)[1]["sig6_draw_odds_bonus"])
        except Exception:
            bonuses.append(None)
            check("calculate_o15_score never raises on a bad draw price", False)
    numeric = [b for b in bonuses[:4] if b is not None]
    check("short draw price scores higher than a long draw price",
          len(numeric) == 4 and numeric[0] > numeric[-1])
    # Endpoints must be pinned, not merely ordered. A mere monotonicity check
    # is too weak here: normalising implied PROBABILITY against a 0.50 floor
    # ALSO decreases as price rises (20 / 12.2 / 3.2 / 0.0) and would sail
    # through an ordering-only assertion while being the wrong transform.
    # The correct transform saturates at the ceiling: a very short draw price
    # must earn the FULL weight, and a price at/above the floor must earn 0.
    check("a very short draw price earns the FULL draw-odds weight",
          numeric and numeric[0] >= 20.0)
    check("a long draw price earns exactly zero",
          len(numeric) == 4 and numeric[-1] == 0.0)
    # Midpoint value, pinned EXACTLY. Ordering alone cannot catch the wrong
    # transform: normalising implied PROBABILITY against a 0.50 floor produces
    # the SAME endpoints (20.0 short, 0.0 long) and is likewise monotone, so an
    # ordering check sails straight through it. The two transforms only diverge
    # in the middle, which is where the discrimination actually lives:
    #     price 1.60 -> correct 9.76  |  probability-scale 7.14
    try:
        from Engine.gg_precision_engine import (
            O15_DRAW_PRICE_CEIL, O15_DRAW_PRICE_FLOOR, O15_DRAW_WEIGHT)
        mid = 1.60
        span = O15_DRAW_PRICE_FLOOR - O15_DRAW_PRICE_CEIL
        expected = max(0.0, min(1.0, (O15_DRAW_PRICE_FLOOR - mid) / span)) \
            * O15_DRAW_WEIGHT
        got = calculate_o15_score(**o15_args, draw_odds=mid)[1]["sig6_draw_odds_bonus"]
        # The breakdown is published at 1 decimal (round(x, 1)), so the
        # tolerance is the half-ulp of that scale (0.05) plus a hair — not 1e-6.
        # A wrong transform differs by ~2.6 points here, far outside this band.
        check("draw-odds term matches the price-space transform at the midpoint",
              abs(got - expected) <= 0.05)
    except Exception as exc:
        check(f"draw-odds midpoint transform check could not run ({exc})", False)

    check("missing / unparseable draw odds is neutral (0.0), never a penalty",
          bonuses[4] == 0.0 and bonuses[5] == 0.0)
except (KeyError, TypeError):
    check("sig6_draw_odds_bonus is present in the breakdown", False)

# ── 5. ARTIFACT COLUMN CONTRACT ──────────────────────────────────────────────
# main.py:164 registers these three filenames under save_key "gg_o15".
with open(os.path.join(ROOT, "main.py"), "r", encoding="utf-8") as fh:
    main_src = fh.read()
for fname in ("gg_o15_feed_{date}.json",
              "ALIENEDGE_GG_PICKS_{date}.csv",
              "ALIENEDGE_O15_PICKS_{date}.csv"):
    check(f"main.py still registers {fname}", fname in main_src)

# ── 5. PHASE 2: the GG weights must match the measured evidence ─────────────
# The 20 points on keeper vulnerability were moved to head-to-head on measured
# AUC (sig3 0.5110, sig4 0.6261). These pin the weights so a later "harmonising"
# edit cannot silently rebalance the GG score back toward the dead signal.
try:
    from Engine.gg_precision_engine import (
        GG_W_MC_BTTS, GG_W_VENUE_BTTS, GG_W_GK_VULN, GG_W_H2H_BTTS,
        GG_W_DIRECTIONAL, GK_LIABILITY_CPG)
except Exception as exc:
    skip("GG weight constants", str(exc))
    GG_W_MC_BTTS = GG_W_VENUE_BTTS = GG_W_GK_VULN = 0
    GG_W_H2H_BTTS = GG_W_DIRECTIONAL = 0
    GK_LIABILITY_CPG = 1.5

check("GG weights still sum to 100",
      GG_W_MC_BTTS + GG_W_VENUE_BTTS + GG_W_GK_VULN
      + GG_W_H2H_BTTS + GG_W_DIRECTIONAL == 100)
check("head-to-head outranks keeper vulnerability",
      GG_W_H2H_BTTS > GG_W_GK_VULN)
check("goalkeeper vulnerability is now a residual term (<= 5 pts)",
      0 < GG_W_GK_VULN <= 5)

# The GK term must remain strictly ordered: both leaky >= one leaky >= neither,
# preserving the shortlist gg_forensics_audit builds from the liability flags.
_gk_args = dict(btts_prob=0.55, venue_btts_home=0.6, venue_btts_away=0.5,
                home_gk_cpg=1.2, away_gk_cpg=1.1, h2h_btts_rate=0.6,
                lambda_home=1.4, lambda_away=1.3)
_both = calculate_gg_score(home_gk_is_liability=True,
                           away_gk_is_liability=True, **_gk_args)[0]
_one = calculate_gg_score(home_gk_is_liability=True,
                          away_gk_is_liability=False, **_gk_args)[0]
_neither = calculate_gg_score(home_gk_is_liability=False,
                              away_gk_is_liability=False, **_gk_args)[0]
check("GG keeper term stays ordered: both >= one >= neither",
      _both > _one > _neither)
check("GG score reaches its ceiling only when every term saturates",
      # sig5 measures the gap ABOVE lambda 1.0, so lambda 1.0/1.0 gives 0 there.
      # Saturating it needs lambda 2.5 each (gap 1.5 / 1.5 = 1.0 -> full 10).
      # sig3's "neither liable" branch is capped at 5 * 0.4 = 2, so the ceiling
      # is 30 + 25 + 2 + 30 + 10 = 97, not 100. Two leaky keepers would score
      # 5 there but would contradict the rest of the scenario.
      calculate_gg_score(btts_prob=0.60, venue_btts_home=0.60,
                         venue_btts_away=0.60, home_gk_is_liability=False,
                         away_gk_is_liability=False, home_gk_cpg=1.5,
                         away_gk_cpg=1.5, h2h_btts_rate=0.60,
                         lambda_home=2.5, lambda_away=2.5)[0] == 97.0)
check("GG score is bounded above by the sum of the weights",
      calculate_gg_score(btts_prob=1.0, venue_btts_home=1.0,
                         venue_btts_away=1.0, home_gk_is_liability=True,
                         away_gk_is_liability=True, home_gk_cpg=9.0,
                         away_gk_cpg=9.0, h2h_btts_rate=1.0,
                         lambda_home=9.0, lambda_away=9.0)[0] <= 100.0)

# ── 6. PHASE 3 WAS PROPOSED, MEASURED, AND REJECTED — keep it rejected ──────
# Phase 3 planned to cap "proxy risk" rows out of GG Tier 1. The headline that
# motivated it was real but the conclusion drawn from it was wrong:
#
#   213 rows where no goalkeeper could be identified settled at 46.0% BTTS,
#   9 points BELOW the 55.0% base rate — which reads like a defect.
#
# It is not a defect in the scoring. Conditioning on the score band, the gap
# vanishes and even reverses:
#
#   band      all rows   PROXY rows   delta
#   0-40        39.3%       39.3%     -0.0
#   40-55       42.3%       38.7%     -3.6
#   55-65       51.1%       55.0%     +3.9
#   65-75       52.6%       63.2%    +10.6
#   75-101      65.4%       61.3%     -4.1
#
# Capping PROXY out of Tier 1 therefore changes nothing (score>=68: 62.4% ->
# 62.3%). "proxy risk" describes the FIXTURE (no keeper identified pre-match),
# not a property of the model, and the model already prices it correctly.
# Phase 2 shrank the GK weight 20 -> 5, which was the real fix: proxy rows
# entering Tier 1 fell 120 -> 103 without needing a special case.
#
# These assertions exist so the idea is not silently re-introduced on the
# strength of the misleading 46% headline alone.
try:
    from Engine.gg_precision_engine import (
        calculate_gk_vulnerability, GG_W_GK_VULN)
    _proxy_note = "Unlisted GK (proxy risk)"
    # No proxy-related suppression hook exists in the tier path: get_gg_tier()
    # takes only a score and a signal count, so it CANNOT special-case a row.
    import inspect
    _tier_params = list(inspect.signature(get_gg_tier).parameters)
    check("GG tier gate takes only score + signals (no proxy special-case)",
          _tier_params == ["gg_score", "signals_fired"])
    check("the GK weight small enough that proxy rows cannot be propped up",
          GG_W_GK_VULN <= 5)
except Exception as exc:
    check(f"PROXY-regression guard could not run ({exc})", False)

failed = [label for label, ok in RESULTS if ok is False]
skipped = [label for label, ok in RESULTS if ok is None]
print("\n" + "=" * 78)
print(f"RESULT: {len(RESULTS) - len(failed) - len(skipped)} passed, "
      f"{len(failed)} failed, {len(skipped)} skipped")
if failed:
    for label in failed:
        print("  FAILED: " + label)
print("=" * 78)
sys.exit(1 if failed else 0)

