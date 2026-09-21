"""Offline tests for get_team_intelligence (pure, no network).

Every expectation below is written against the VERIFIED producing engines:
  • WIN parity      — win_forecast parity_score signed per side, cut +10
  • Goal Intent     — DNA engine LEAN OVER per-side cut (> 55)
  • GG BTTS Friction— DNA engine STRONG GG gate (home > 65 AND away > 55)
  • Draw Probability— draw engine's own candidate floor (mc_draw >= 0.22)
  • DNA parity      — draw factor-count balance in {0, 1}
"""
import INTELLIGENT_PASS.pass_count as pc

DATE = "2026-09-20"
FAILS = []


def check(name, ok):
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        FAILS.append(name)


_KEYS = ["win_by_id", "win_by_name", "wps_by_id", "wps_by_name",
         "gps_by_id", "gps_by_name", "ops_by_id", "ops_by_name",
         "u2s_by_id", "u2s_by_name", "sot_by_id", "sot_by_name",
         "fhvi_by_id", "fhvi_by_name", "shvi_by_id", "shvi_by_name",
         "cagg_by_id", "cagg_by_name", "ud_by_id", "ud_by_name",
         "uda_by_id", "uda_by_name", "draw_by_id", "draw_by_name",
         "un_by_id", "un_by_name", "dna_by_id", "dna_by_name",
         "dna_draw_by_id", "dna_draw_by_name",
         "o25f_by_id", "o25f_by_name", "ggc_by_id", "ggc_by_name",
         "o15c_by_id", "o15c_by_name"]

_GOAL_OVER25 = {"name": "Goal Intent", "home_value": 72, "away_value": 55, "winner": "home"}
_BOX_OVER25 = {"name": "Box Dominance", "home_value": 80, "away_value": 70, "winner": "home"}
_FRICTION_GG = {"name": "BTTS Friction", "home_value": 70, "away_value": 60, "winner": "home"}
_GG_GOAL = {"name": "Goal Intent", "home_value": 68, "away_value": 64, "winner": "both"}

side_rows = [
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Arsenal",
     "parity_score": 12, "last_5_goals_scored": 11, "opp_last_5_goals_scored": 6,
     "last_5_wins_overall": 4, "last_5_wins_at_venue": 3},
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Chelsea",
     "parity_score": -12, "last_5_goals_scored": 6, "opp_last_5_goals_scored": 11,
     "last_5_wins_overall": 1, "last_5_wins_at_venue": 0},
]


def _build():
    s = {k: {} for k in _KEYS}
    s["u2s_rows"], s["corner_rows"] = [], []
    s["win_by_id"] = {"100": side_rows}
    s["win_by_name"] = {pc._norm("Arsenal vs Chelsea"): side_rows}
    s["draw_by_id"] = {"100": {"mc_draw_prob": 0.30, "parity": 0.7, "dmi": 0.5}}
    s["dna_by_id"] = {"100": {
        "over25": {"factors": [_GOAL_OVER25, _BOX_OVER25]},
        "gg": {"factors": [_FRICTION_GG, _GG_GOAL]},
        "draw": {"home_count": 3, "away_count": 3,
                 "factors": [{"name": "Tempo", "home_value": 40, "away_value": 35,
                              "winner": "home"}]},
    }}
    s["dna_draw_by_id"] = {"100": {"home_count": 3, "away_count": 3}}
    s["o25f_by_id"] = {"100": {"kill_switch_pass": True, "poisson_over_prob_num": 71.5,
                               "h2h_overs_last_5": 4, "pos_gap": 5, "parity_diff": 22,
                               "council_votes": "8/9"}}
    s["ggc_by_id"] = {"100": {"home_gk_liable": True, "away_gk_liable": False,
                              "gg_score": 88.0, "h2h_btts_rate": 0.5}}
    s["o15c_by_id"] = {"100": {"combined_lambda": 3.1, "lambda_home": 1.6,
                               "lambda_away": 1.5, "home_gk_liable": True,
                               "away_gk_liable": False, "o15_score": 78.0}}
    s["fhvi_by_id"] = {}; s["fhvi_by_name"] = {pc._norm("Arsenal vs Chelsea"): {
        "fixture": "Arsenal vs Chelsea", "fhvi_score": 8.4, "Category": "⚡ TIER 2 - GOOD FH"}}
    s["shvi_by_id"] = {}; s["shvi_by_name"] = {pc._norm("Arsenal vs Chelsea"): {
        "fixture": "Arsenal vs Chelsea", "shvi_score": 5.1, "Category": "⚖️ TIER 3 - NEUTRAL"}}
    return s


pc.clear_cache()
pc._SNAPSHOTS[DATE] = _build()

page = pc.get_team_intelligence("Arsenal", DATE)
check("page resolves team to fixture", page["fixture_found"] is True)
check("fixture label from the side row", page["fixture"] == "Arsenal vs Chelsea")
check("fixture id resolved", page["fixture_id"] == "100")
check("opponent resolved from the second side row", page["opponent"] == "Chelsea")
check("markets dict present", isinstance(page.get("markets"), dict))
check("all market sections present",
      set(page["markets"].keys()) ==
      {"win", "win_psychology", "gg", "gg_precision", "over25", "over15",
       "corners", "draw", "unders", "u2s", "fhvi", "shvi"})
win = page["markets"]["win"]
check("win section has Parity +10 PASS with the raw signed value",
      any(c["name"] == "Parity +10" and c["result"] == pc.PASS and c["value"] == 12
          for c in win["checks"]))
check("win Goal Intent uses the DNA LEAN OVER per-side cut (72 > 55 = PASS)",
      any(c["name"] == "Goal Intent" and c["result"] == pc.PASS and c["value"] == 72
          for c in win["checks"]))
check("win denominator is FIXED at the full 8-rule set (N/A included)",
      win["total"] == 8 and win["passed"] == 3)
# 3/4 is CORRECT here: this fixture IS a live draw candidate per the draw
# engine's own floor (mc_draw 0.30 >= 0.22), so the WIN-side "Draw
# Probability" check legitimately FAILs while the DRAW section PASSes the
# very same field — same engine constant, opposite direction per market.
check("win vs draw use the same mc_draw floor in opposite directions",
      next(c for c in win["checks"] if c["name"] == "Draw Probability")["result"] == pc.FAIL
      and next(c for c in page["markets"]["draw"]["checks"]
               if c["name"] == "Draw Probability")["result"] == pc.PASS)
check("win Form check reports both counters",
      any(c["name"] == "Form" and c["value"] == {"team": 11, "opp": 6}
          for c in win["checks"]))

gg = page["markets"]["gg"]
fr = next((c for c in gg["checks"] if c["name"] == "BTTS Friction"), None)
check("gg BTTS Friction uses the DNA STRONG GG gate (70 > 65 and 60 > 55 = PASS)",
      fr is not None and fr["result"] == pc.PASS
      and fr["value"] == {"home_value": 70, "away_value": 60})
gk = next((c for c in gg["checks"] if c["name"] == "Goalkeeper"), None)
check("gg Goalkeeper reuses the engine's own liable flag",
      gk is not None and gk["result"] == pc.PASS)

draw = page["markets"]["draw"]
dp = next((c for c in draw["checks"] if c["name"] == "Draw Probability"), None)
check("draw section uses the engine's native floor (0.30 >= 0.22 = PASS)",
      dp is not None and dp["result"] == pc.PASS and dp["value"] == 0.30)
dnap = next((c for c in draw["checks"] if c["name"] == "DNA Parity"), None)
check("draw DNA parity |3-3| = 0 → PASS", dnap is not None and dnap["result"] == pc.PASS)

o25 = page["markets"]["over25"]
check("O2.5 section reuses the engine council gates (pos_gap 5, parity 22, h2h 4, poisson 71.5, kill switch)",
      {c["name"]: c["result"] for c in o25["checks"]} ==
      {"Kill Switch": pc.PASS, "Poisson Gate": pc.PASS, "H2H Overs": pc.PASS,
       "Position Gap": pc.PASS, "Parity": pc.PASS, "DNA Over Signal": pc.PASS})

fhvi = page["markets"]["fhvi"]
check("FHVI section uses the >= 7 TIER-2 gate (8.4 = PASS)",
      fhvi["total"] == 1 and fhvi["passed"] == 1)
shvi = page["markets"]["shvi"]
check("SHVI section uses the same >= 7 gate (5.1 = FAIL)",
      shvi["total"] == 1 and shvi["passed"] == 0)

check("unavailable intelligence stays NOT_AVAILABLE (no fabrication)",
      next(c for c in page["markets"]["corners"]["checks"]
           if c["name"] == "Corner Friction")["result"] == pc.NOT_AVAILABLE)

ctx = page["context"]
check("context carries the raw WIN side values (parity 12, form 11 vs 6)",
      ctx["win_side"]["parity_score"] == 12
      and ctx["win_side"]["last_5_goals_scored"] == 11
      and ctx["win_side"]["opp_last_5_goals_scored"] == 6)
check("context carries the DNA market factors for this fixture",
      "over25" in ctx["dna_market_factors"]
      and any(f["name"] == "Goal Intent"
              for f in ctx["dna_market_factors"]["over25"]["factors"]))
check("context carries the O2.5 forecast council inputs",
      ctx["over25"]["council_votes"] == "8/9" and ctx["over25"]["kill_switch_pass"] is True)

page2 = pc.get_team_intelligence("Not A Real Team", DATE)
check("unknown team gives honest fixture_found=False (no fabricated page)",
      page2["fixture_found"] is False and page2["markets"] == {})

print("OK" if not FAILS else str(len(FAILS)) + " FAILURES", flush=True)
