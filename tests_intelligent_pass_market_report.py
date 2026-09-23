"""MARKET-KEYED REPORT ARCHITECTURE — offline purity tests (no network).

Proves the requested architecture: the PICK is the primary object.
get_team_intelligence(team, date, market=<key>) runs ONLY that market's
evaluator branch and returns score+checks for that pick alone — no other
market's checks can leak in. Zero new data acquisition: reads the same
snapshots as the market pages.
"""
import INTELLIGENT_PASS.pass_count as pc

DATE = "2026-09-20"
FAILS = []


def check(name, ok):
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        FAILS.append(name)


# ── synthetic snapshot: every market's intelligence present for ONE fixture ─
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

snap = {k: {} for k in [
    "win_by_id", "win_by_name", "wps_by_id", "wps_by_name",
    "gps_by_id", "gps_by_name", "ops_by_id", "ops_by_name",
    "u2s_by_id", "u2s_by_name", "sot_by_id", "sot_by_name",
    "fhvi_by_id", "fhvi_by_name", "shvi_by_id", "shvi_by_name",
    "cagg_by_id", "cagg_by_name", "ud_by_id", "ud_by_name",
    "uda_by_id", "uda_by_name", "draw_by_id", "draw_by_name",
    "un_by_id", "un_by_name", "dna_by_id", "dna_by_name",
    "dna_draw_by_id", "dna_draw_by_name", "o25f_by_id", "o25f_by_name",
    "ggc_by_id", "ggc_by_name", "o15c_by_id", "o15c_by_name"]}
snap["u2s_rows"], snap["corner_rows"] = [], []
snap["date"], snap["label_by_id"] = DATE, {"100": "Arsenal vs Chelsea"}
snap["dna_prof_by_name"] = {}
snap["win_by_id"] = {"100": side_rows}
snap["win_by_name"] = {pc._norm("Arsenal vs Chelsea"): side_rows}
snap["draw_by_id"] = {"100": {"mc_draw_prob": 0.30, "parity": 0.7, "dmi": 0.5,
                              "home_position": 3, "away_position": 15}}
snap["dna_by_id"] = {"100": {
    "over25": {"factors": [_GOAL_OVER25, _BOX_OVER25]},
    "gg": {"factors": [_FRICTION_GG, _GG_GOAL]},
    "draw": {"home_count": 3, "away_count": 3,
             "factors": [{"name": "Tempo", "home_value": 40, "away_value": 35,
                          "winner": "home"}]},
}}
snap["dna_draw_by_id"] = {"100": {"home_count": 3, "away_count": 3}}
snap["o25f_by_id"] = {"100": {"kill_switch_pass": True, "poisson_over_prob_num": 71.5,
                              "h2h_overs_last_5": 4, "pos_gap": 5, "parity_diff": 22,
                              "council_votes": "8/9",
                              "combined_gs_last_5": 24}}
snap["ggc_by_id"] = {"100": {"home_gk_liable": True, "away_gk_liable": False,
                             "gg_score": 88.0, "h2h_btts_rate": 0.5}}
snap["o15c_by_id"] = {"100": {"combined_lambda": 3.1, "lambda_home": 1.6,
                              "lambda_away": 1.5, "home_gk_liable": True,
                              "away_gk_liable": False, "o15_score": 78.0}}
snap["fhvi_by_name"] = {pc._norm("Arsenal vs Chelsea"): {
    "fixture": "Arsenal vs Chelsea", "fhvi_score": 8.4,
    "Category": "⚡ TIER 2 - GOOD FH"}}
snap["shvi_by_name"] = {pc._norm("Arsenal vs Chelsea"): {
    "fixture": "Arsenal vs Chelsea", "shvi_score": 5.1,
    "Category": "⚖️ TIER 3 - NEUTRAL"}}

pc.clear_cache()
pc._SNAPSHOTS[DATE] = snap
pc._seal_date(DATE)


def report(market, team="Arsenal"):
    return pc.get_team_intelligence(team, DATE, market=market)


# ── identity: the report carries team+date+market and NEVER a markets map ───
r25 = report("over25")
check("report identity = team+date+market", r25["market"] == "over25"
      and r25["team"] == "Arsenal" and r25["date"] == DATE)
check("single-market payload has NO markets map", "markets" not in r25)
check("O2.5 report shows the Over 2.5 label", r25["market_label"] == "Over 2.5")
check("fixture resolved for the audited pick", r25["fixture"] == "Arsenal vs Chelsea"
      and r25["opponent"] == "Chelsea")

# ── §20 CRITICAL DATA TEST: same fixture, different clicks → different reports
names = lambda m: [c["name"] for c in report(m)["checks"]]
check("click O2.5 → ONLY the six user rules",
      set(names("over25")) == {"Kill Switch", "Poisson Gate",
                               "Council Votes", "Goal Count",
                               "Goal Intent", "League Top 10"})
check("click WIN → WIN-only checks (SOT/Corners/Psychology/Underdog/Goal Intent/Draw Prob/Parity/Form)",
      set(names("win")) == {"SOT", "Corners", "Psychology", "Underdog",
                            "Goal Intent", "Draw Probability", "Parity +10", "Form"})
check("click GG → GG-only checks",
      set(names("gg")) == {"Psychology", "Goalkeeper", "BTTS Friction", "Goal Intent"})
check("click DRAW → Draw-only checks",
      set(names("draw")) == {"Draw Probability", "Psychology Parity",
                             "Draw Magnet", "DNA Parity"})
check("click FHVI → FHVI-only check", set(names("fhvi")) == {"FHVI"})
check("click SHVI → SHVI-only check", set(names("shvi")) == {"SHVI"})

# ── §12/§23: no unrelated market's checks leak into another market ──────────
WIN_ONLY = {"Parity +10", "Form", "SOT", "Underdog"}
O25_ONLY = {"Kill Switch", "Poisson Gate", "Council Votes", "Goal Count"}
GG_ONLY = {"Goalkeeper", "BTTS Friction"}
check("no WIN checks inside O2.5 report", not (WIN_ONLY & set(names("over25"))))
check("no O2.5 checks inside WIN report", not (O25_ONLY & set(names("win"))))
check("no GG checks inside WIN report", not (GG_ONLY & set(names("win"))))
check("no WIN checks inside GG report", not (WIN_ONLY & set(names("gg"))))
check("no O2.5 checks inside DRAW report", not (O25_ONLY & set(names("draw"))))

# ── scores differ per pick on the SAME fixture (not one generic number) ────
# FIXED-DENOMINATOR RULE: totals are each market's FULL rule set
# (O2.5=6, WIN=8, FHVI/SHVI=1); only the numerator varies per pick. WIN is
# 2/8 under the new single-check trio rules: Parity +10 / Goal Intent support
# the pick; Form is HALF (goals + wins pass, conceded has no data for this
# fixture → the check FAILs, honestly, on an incomplete trio); the four
# side-sourced checks have no intelligence here (NOT_AVAILABLE — never
# fabricated) and Draw Probability FAILs at mc_draw 0.30 against the WIN
# rule's own < 20% cut.
check("same fixture, per-pick scores: O2.5 6/6 vs WIN 2/8 vs FHVI 1/1 vs SHVI 0/1",
      report("over25")["score"] == {"passed": 6, "total": 6}
      and report("win")["score"] == {"passed": 2, "total": 8}
      and next(c for c in report("win")["checks"]
               if c["name"] == "Form")["value"]["tier"] == "HALF"
      and report("fhvi")["score"] == {"passed": 1, "total": 1}
      and report("shvi")["score"] == {"passed": 0, "total": 1})

# ── WIN psychology is the SAME pick audited by the SAME WIN checklist ───────
wp = report("win_psychology")
check("WIN-psychology click runs the WIN checklist (8 same-name checks)",
      [c["name"] for c in wp["checks"]]
      == [c["name"] for c in report("win")["checks"]]
      and wp["market"] == "win_psychology"
      and wp["score"] == report("win")["score"])

# ── every sidebar market has its own evaluator (§12) ───────────────────────
ALL_MARKETS = ["win", "win_psychology", "gg", "gg_precision", "gg_o15", "over25",
               "over15", "corners", "draw", "unders", "u2s", "fhvi", "shvi",
               "sot"]
for m in ALL_MARKETS:
    rep = report(m)
    check(f"market {m!r} has a single-market evaluator", rep["fixture_found"] is True
          and rep["market"] == m and isinstance(rep["score"], dict)
          and isinstance(rep["checks"], list))

# ── §10: FIXED denominator — every rule the market defines counts, N/A or not
cor = report("corners")
check("corners denominator is FIXED at the market's full rule set (N/A included)",
      cor["score"]["total"] == len(cor["checks"]) and cor["score"]["total"] == 2
      and cor["score"]["passed"] == 0)

# ── §7: unknown / blank market is rejected, not silently generic ───────────
try:
    report("bogus_market")
    check("unknown market raises ValueError", False)
except ValueError:
    check("unknown market raises ValueError", True)

# ── backward compat: no market → legacy all-markets payload, unchanged ─────
legacy = pc.get_team_intelligence("Arsenal", DATE)
check("legacy all-markets payload still intact",
      set(legacy["markets"]) == {"win", "win_psychology", "gg", "gg_precision",
                                 "over25", "over15", "corners", "draw", "unders",
                                 "u2s", "fhvi", "shvi", "sot"}
      and legacy["fixture_found"] is True)

# ── §14: team identity ≠ market identity — away-side audit finds same fixture
check("away-side team resolves the same fixture for its own pick",
      report("over25", "Chelsea")["fixture"] == "Arsenal vs Chelsea"
      and report("over25", "Chelsea")["score"] == report("over25")["score"])

# ── per-row audits carry their market tag (table → click provenance) ───────
row_audit = pc.evaluate_market("over25_forecast", [
    {"fixture_id": 100, "fixture": "Arsenal vs Chelsea", "kill_switch_pass": True,
     "poisson_over_prob_num": 71.5, "h2h_overs_last_5": 4, "pos_gap": 5,
     "parity_diff": 22, "council_votes": "8/9"}], DATE)
check("row audit carries its market key (travels with the click)",
      row_audit and row_audit[0]["intelligent_pass_count"]["market"] == "over25_forecast")

# ── unknown team stays honest in single-market mode ────────────────────────
miss = pc.get_team_intelligence("Not A Real Team", DATE, market="win")
check("unknown team → fixture_found=False with market echoed",
      miss["fixture_found"] is False and miss["markets" if False else "market"] == "win"
      and miss["score"] is None and miss["checks"] == [])

print("OK" if not FAILS else str(len(FAILS)) + " FAILURES", flush=True)

# ── regression: GG psychology verdict AND raw value from the SUPREME row ────
# (gg_psychology rows carry Psych_Score but no H_Base/A_Base; the branch
# reads the verdict off the gg_supreme row the GG table rows carry)
snap["gsup_by_id"] = {"100": {"Fixture": "Arsenal vs Chelsea", "Psych_Score": 75}}
snap["gsup_by_name"] = {pc._norm("Arsenal vs Chelsea"): snap["gsup_by_id"]["100"]}
gg_rep = report("gg")
gps = next((c for c in gg_rep["checks"] if c["name"] == "Psychology"), None)
check("gg Psychology verdict+value come from the supreme row's own Psych_Score",
      gps is not None and gps["result"] == pc.PASS and gps.get("value") == 75)

# ── regression: fixtures whose ONLY saved rows are fixture-level (apex-only)
DATE2 = "2026-09-27"
snap2 = {k: {} for k in snap}
snap2["u2s_rows"], snap2["corner_rows"] = [], []
snap2["date"], snap2["label_by_id"], snap2["dna_prof_by_name"] = DATE2, {}, {}
apex_row = {"fixture_id": 200, "Fixture": "Real Madrid vs Barcelona",
            "Target": "Real Madrid"}
snap2["win_by_id"] = {"200": [apex_row]}
snap2["win_by_name"] = {pc._norm("Real Madrid vs Barcelona"): [apex_row]}
pc._SNAPSHOTS[DATE2] = snap2
pc._seal_date(DATE2)
mad = pc.get_team_intelligence("Real Madrid", DATE2, market="over25")
check("apex Target match resolves the fixture (strong pass)",
      mad["fixture_found"] is True
      and mad["fixture"] == "Real Madrid vs Barcelona"
      and mad["opponent"] == "Barcelona")
bar = pc.get_team_intelligence("Barcelona", DATE2, market="over25")
check("the OTHER side resolves by label containment (apex-only runs)",
      bar["fixture_found"] is True
      and bar["fixture"] == "Real Madrid vs Barcelona")

# ── regression: word-boundary guard — an U21 fixture never swallows the team
snap3 = {k: {} for k in snap}
snap3["u2s_rows"], snap3["corner_rows"] = [], []
snap3["date"], snap3["label_by_id"], snap3["dna_prof_by_name"] = DATE, {}, {}
snap3["win_by_id"] = {"300": [{"fixture_id": 300,
                               "Fixture": "Arsenal U21 vs Brighton U21"}]}
check("word-boundary guard: senior team does NOT resolve an U21-only fixture",
      pc._locate_fixture(DATE, snap3, "Arsenal") == ("", [], ""))
pc._SNAPSHOTS.pop(DATE2, None)

print("OK" if not FAILS else str(len(FAILS)) + " FAILURES", flush=True)
