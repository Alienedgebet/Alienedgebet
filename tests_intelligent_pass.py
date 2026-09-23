"""
Focused offline tests for the Intelligent Pass Count evaluator
(INTELLIGENT_PASS/pass_count.py). Pure unit tests: they inject synthetic
per-date snapshots via _SNAPSHOTS, so nothing on disk or on the network is
touched. Run:  ./venv/bin/python3 tests_intelligent_pass.py
"""
import sys

from INTELLIGENT_PASS import pass_count as pc

DATE = "2099-01-01"
RESULTS = []


def check(label, cond):
    RESULTS.append((label, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + label)


def fresh_snapshot(overrides=None):
    """A snapshot where every source index is empty → every check is
    NOT_AVAILABLE (the denominator stays FIXED at the market's full rule
    set; only the numerator varies). Tests override only the sources
    relevant to the rule under test. The date window is PINNED to DATE so
    sealed-offline suites never touch real cache files on neighbouring dates."""
    pc._seal_date(DATE)
    snap = {
        "date": DATE, "label_by_id": {}, "dna_prof_by_name": {},
        "win_by_id": {}, "win_by_name": {},
        "wps_by_id": {}, "wps_by_name": {},
        "gps_by_id": {}, "gps_by_name": {},
        "ops_by_id": {}, "ops_by_name": {},
        "u2s_by_id": {}, "u2s_by_name": {},
        "sot_by_id": {}, "sot_by_name": {},
        "cagg_by_id": {}, "cagg_by_name": {},
        "ud_by_id": {}, "ud_by_name": {},
        "uda_by_id": {}, "uda_by_name": {},
        "draw_by_id": {}, "draw_by_name": {},
        "un_by_id": {}, "un_by_name": {},
        "dna_by_id": {}, "dna_by_name": {},
        "dna_draw_by_id": {}, "dna_draw_by_name": {},
        "u2s_rows": [], "corner_rows": [],
    }
    snap.update(overrides or {})
    return snap


def evaluate(market, row, snap):
    pc.clear_cache(); pc._seal_date(DATE); pc._SNAPSHOTS[DATE] = snap
    return pc.evaluate_market(market, [dict(row)], DATE)[0]['intelligent_pass_count']


def result_map(ipc):
    return {c["name"]: c["result"] for c in (ipc or {}).get("checks", [])}
# ── 1. WIN — Parity +10 ──────────────────────────────────────────────────────
win_row = {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "Target": "Arsenal"}
side_rows = [
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Arsenal",
     "parity_score": 12, "last_5_goals_scored": 11, "opp_last_5_goals_scored": 6,
     "last_5_wins_overall": 4, "last_5_wins_at_venue": 3,
     "last_5_venue_goals_scored": 9, "last_5_venue_goals_conceded": 2,
     "opp_last_5_conceded_raw": 7},
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Chelsea",
     "parity_score": -12, "last_5_goals_scored": 6, "opp_last_5_goals_scored": 11,
     "last_5_wins_overall": 1, "last_5_wins_at_venue": 0,
     "last_5_venue_goals_scored": 5, "last_5_venue_goals_conceded": 6,
     "opp_last_5_conceded_raw": 2},
]
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows},
                       "label_by_id": {"100": "Arsenal vs Chelsea"}})
ipc = evaluate("win_apex", win_row, snap)
rm = result_map(ipc)
check("WIN Parity +12 → PASS", rm.get("Parity +10") == pc.PASS)
_form = next(c for c in ipc["checks"] if c["name"] == "Form")
check("WIN Form = ONE check — three legs, all pass → FULL PASS "
      "(venue goals 9>5, venue wins 3>0, conceded 2<6)",
      rm.get("Form") == pc.PASS
      and _form["value"]["tier"] == "FULL"
      and _form["value"]["legs_passed"] == 3
      and all(m["basis"] == "venue" for m in _form["value"]["legs"]))
check("WIN provenance: parity check names the engine field",
      next(c for c in ipc["checks"] if c["name"] == "Parity +10")["field"]
      == "parity_score")

side_rows[0]["parity_score"] = 8  # same fixture, below the +10 threshold
ipc = evaluate("win_apex", win_row, snap)
check("WIN Parity +8 → FAIL", result_map(ipc).get("Parity +10") == pc.FAIL)
check("WIN Parity value is the raw signed score",
      ipc["checks"][-2]["value"] == 8)

ipc = evaluate("win_apex", win_row,
               fresh_snapshot({"draw_by_id": {"100": {"mc_draw_prob": "12%"}}}))
rm = result_map(ipc)
check("WIN no WIN rows → Parity +10 NOT_AVAILABLE",
      rm.get("Parity +10") == pc.NOT_AVAILABLE)
check("WIN all checks counted — fixed denominator of 8 (only Draw has data)",
      ipc is not None and ipc["total"] == 8 and ipc["passed"] == 1)
ipc = evaluate("win_apex", win_row, fresh_snapshot())
check("WIN all-missing → 0/8 (denominator FIXED at 8, no fake PASS)",
      ipc is not None and ipc["total"] == 8 and ipc["passed"] == 0
      and all(c["result"] == pc.NOT_AVAILABLE for c in ipc["checks"]))
# ── 2. DRAW — DNA parity 0/1 PASS, otherwise FAIL ────────────────────────────
draw_row = {"fixture_id": 200, "fixture": "Iran U23 vs China U23"}
for balance_home, balance_away, expected in [
        (3, 3, pc.PASS),   # balance 0
        (4, 3, pc.PASS),   # balance 1
        (5, 3, pc.FAIL),   # balance 2 → outside {0, 1}
        (2, 6, pc.FAIL)]:  # balance 4
    snap = fresh_snapshot({"dna_draw_by_id": {"200": {
        "home_count": balance_home, "away_count": balance_away}},
        "dna_draw_by_name": {pc._norm("Iran U23 vs China U23"): {
            "home_count": balance_home, "away_count": balance_away}}})
    ipc = evaluate("draw", draw_row, snap)
    check(f"DRAW DNA parity |{balance_home}-{balance_away}| → {expected}",
          result_map(ipc).get("DNA Parity") == expected)

ipc = evaluate("draw", {**draw_row, "mc_draw_prob": "12%"}, fresh_snapshot())
check("DRAW no DNA factors → DNA Parity NOT_AVAILABLE",
      result_map(ipc).get("DNA Parity") == pc.NOT_AVAILABLE)
check("DRAW DNA Parity counted in the FIXED denominator of 4 (0/4: 12% is below the floor)",
      ipc is not None and ipc["total"] == 4 and ipc["passed"] == 0)
# ── 3. UNDERDOG — Dixon-Coles multipliers (repo-native >= direction) ─────────
ud_row = {"fixture_id": 300, "fixture": "Bournemouth vs Liverpool",
          "Underdog": "Bournemouth", "Psych_Score": 78}
u2s_idx = {pc._norm("Bournemouth vs Liverpool"): {
    "Underdog": "Bournemouth", "Psych_Score": 78}}
for att, att_exp, fav, fav_exp in [
        (1.90, pc.PASS, 1.40, pc.PASS),   # threshold values qualify (>=)
        (2.10, pc.PASS, 1.55, pc.PASS),   # clearly above
        (1.85, pc.FAIL, 1.35, pc.FAIL)]:  # below both thresholds
    snap = fresh_snapshot({"u2s_by_name": u2s_idx, "ud_by_id": {"300": {
        "dog_att_strength": att, "fav_def_weakness": fav}}})
    ipc = evaluate("u2s", ud_row, snap)
    rm = result_map(ipc)
    check(f"U2S DOG ATT STRENGTH {att} → {att_exp}",
          rm.get("Dog ATT Strength") == att_exp)
    check(f"U2S FAV DEF WEAKNESS {fav} → {fav_exp}",
          rm.get("Fav Def Weakness") == fav_exp)

snap = fresh_snapshot({"u2s_by_name": u2s_idx, "ud_by_id": {"300": {
    "dog_att_strength": None, "fav_def_weakness": None}}})
ipc = evaluate("u2s", ud_row, snap)
rm = result_map(ipc)
check("U2S missing multipliers → both NOT_AVAILABLE",
      rm.get("Dog ATT Strength") == pc.NOT_AVAILABLE
      and rm.get("Fav Def Weakness") == pc.NOT_AVAILABLE)
check("U2S multipliers count in the FIXED denominator of 3",
      ipc is not None and ipc["total"] == 3 and ipc["passed"] == 1)
# ── 4. Per-fixture availability / denominator integrity ──────────────────────
ipc = evaluate("u2s", ud_row, fresh_snapshot())
check("U2S all-missing → 0/3 (denominator FIXED at 3, no fake FAIL)",
      ipc is not None and ipc["total"] == 3 and ipc["passed"] == 0)

ipc = evaluate("u2s", {"fixture_id": 300, "fixture": "Bournemouth vs Liverpool",
                       "Underdog": "Bournemouth", "Psych_Score": "VETOED"},
               fresh_snapshot())
rm = result_map(ipc)
check("U2S 'VETOED' psychology → NOT_AVAILABLE, 0/3 (no fake FAIL)",
      ipc is not None and ipc["total"] == 3 and ipc["passed"] == 0
      and rm.get("Psychology") == pc.NOT_AVAILABLE)
# ── 5. Display/audit-only guarantee ──────────────────────────────────────────
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows},
                       "label_by_id": {"100": "Arsenal vs Chelsea"}})
rows = pc.evaluate_market("win_apex", [dict(win_row)], DATE)
row_keys_before = {"fixture_id", "Fixture", "Target"}
check("evaluate_market only ADDS intelligent_pass_count (prediction untouched)",
      set(rows[0].keys()) == row_keys_before | {"intelligent_pass_count"})
check("evaluate_market_safe returns rows unchanged on evaluator crash",
      pc.evaluate_market_safe("win_apex", [dict(win_row)], "bogus-date") is not None)
# ── 6. WIN on forecast side rows (Target fallback → team_name) ───────────────
fc_row = {"fixture_id": 100, "fixture": "Arsenal vs Chelsea", "team_name": "Chelsea",
          "parity_score": -14, "last_5_goals_scored": 4, "opp_last_5_goals_scored": 9,
          "last_5_wins_overall": 0, "last_5_wins_at_venue": 0}
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows},
                       "label_by_id": {"100": "Arsenal vs Chelsea"}})
ipc = evaluate("win_apex", fc_row, snap)
rm = result_map(ipc)
check("WIN forecast row resolves its own side (Chelsea parity -14 → FAIL)",
      rm.get("Parity +10") == pc.FAIL
      and next(c for c in ipc["checks"] if c["name"] == "Parity +10")["value"] == -14)
_form2 = next(c for c in ipc["checks"] if c["name"] == "Form")
check("WIN forecast row Form trio for Chelsea (0/3 legs → NONE → FAIL)",
      rm.get("Form") == pc.FAIL and _form2["value"]["tier"] == "NONE"
      and _form2["value"]["legs_passed"] == 0)

# ── 6b. WIN Form tier ladder — SAME side pair, different concessions ─────────
weak = [dict(side_rows[0], last_5_venue_goals_conceded=7), dict(side_rows[1])]
snap_b = fresh_snapshot({"win_by_id": {"100": weak},
                         "win_by_name": {pc._norm("Arsenal vs Chelsea"): weak},
                         "label_by_id": {"100": "Arsenal vs Chelsea"}})
rm_b = result_map(evaluate("win_apex", win_row, snap_b))
check("WIN Form with the conceded leg flipped → HALF (2/3), still FAIL",
      rm_b.get("Form") == pc.FAIL
      and next(c for c in evaluate("win_apex", win_row, snap_b)["checks"]
               if c["name"] == "Form")["value"]["tier"] == "HALF")
strong_nan = [dict(side_rows[0], last_5_venue_goals_scored=None,
                   last_5_goals_scored=None), dict(side_rows[1])]
snap_c = fresh_snapshot({"win_by_id": {"100": strong_nan},
                         "win_by_name": {pc._norm("Arsenal vs Chelsea"): strong_nan},
                         "label_by_id": {"100": "Arsenal vs Chelsea"}})
rm_c = result_map(evaluate("win_apex", win_row, snap_c))
check("WIN Form overall-fallback basis scoreboard: missing venue goals on "
      "BOTH rows and missing overall goals → that leg NOT_AVAILABLE",
      next(c for c in evaluate("win_apex", win_row, snap_c)["checks"]
           if c["name"] == "Form")["value"]["legs"][0]["result"]
      == pc.NOT_AVAILABLE)

# ── 7. O2.5 — the engine's own council gates (Engine/over25_forecast.py) ─────
for ks, po, h2h, pg, pd, exp_pass in [
        (True, 71.5, 4, 5, 22, 5),     # all five council gates support
        (False, 55.0, 1, 12, -3, 0)]:  # none support
    # market "over25_forecast": the row IS the engine's forecast row
    row = {"fixture_id": 400, "fixture": "Ajax vs Feyenoord",
           "kill_switch_pass": ks, "poisson_over_prob_num": po,
           "h2h_overs_last_5": h2h, "pos_gap": pg, "parity_diff": pd}
    ipc = evaluate("over25_forecast", row, fresh_snapshot())
    rm = result_map(ipc)
    got = sum(1 for k in ("Kill Switch", "Poisson Gate", "H2H Overs",
                          "Position Gap", "Parity") if rm.get(k) == pc.PASS)
    check(f"O2.5 council gates (ks={ks}, poisson={po}, h2h={h2h}, gap={pg}, parity={pd}) → {exp_pass}/5",
          got == exp_pass)
# apex picks join the SAME engine's forecast row by fixture id
snap = fresh_snapshot({"o25f_by_id": {"400": {
    "kill_switch_pass": True, "poisson_over_prob_num": 66.0, "h2h_overs_last_5": 3,
    "pos_gap": 8, "parity_diff": 1}}})
ipc = evaluate("over25_apex", {"fixture_id": 400, "fixture": "Ajax vs Feyenoord"}, snap)
rm = result_map(ipc)
check("O2.5 apex joins the over25_forecast row (pos_gap 8 → PASS, boundary)",
      rm.get("Position Gap") == pc.PASS)
snap = fresh_snapshot({"o25f_by_id": {"400": {"pos_gap": 99, "kill_switch_pass": True}}})
ipc = evaluate("over25_apex", {"fixture_id": 400, "fixture": "Ajax vs Feyenoord"}, snap)
check("O2.5 pos_gap 99 sentinel → NOT_AVAILABLE (fixed denominator of 6)",
      result_map(ipc).get("Position Gap") == pc.NOT_AVAILABLE
      and ipc["total"] == 6 and ipc["passed"] == 1)
ipc = evaluate("over25_apex", {"fixture_id": 999, "fixture": "No Rows vs At All"},
               fresh_snapshot())
check("O2.5 apex with no forecast row → every gate NOT_AVAILABLE, 0/6",
      ipc is not None and ipc["total"] == 6 and ipc["passed"] == 0)

# ── 8. WIN PSYCHOLOGY rows (Master_Pick) — ONE WIN checklist ───────────────
# Psychology rows are WIN picks (the picked winner): the SAME eight WIN
# checks run, sourced per-side. Psychology passes only when the predicted
# team's OWN base sits 50+ ABOVE the opponent's (H_Base for home, A_Base for
# away); without a pick the audit is honest about what is missing but keeps
# the fixed denominator.
wps_row = {"fixture_id": 500, "Fixture": "Roma vs Lazio",
           "Master_Pick": "Roma"}
snap = fresh_snapshot({"wps_by_name": {pc._norm("Roma vs Lazio"): {
    "H_Base": 120, "A_Base": 44, "Audit_Score": 76}},
    "label_by_id": {"500": "Roma vs Lazio"}})
ipc = evaluate("win_psychology", dict(wps_row), snap)
rm = result_map(ipc)
_psych = next(c for c in ipc["checks"] if c["name"] == "Psychology")
check("WIN psychology: Master_Pick Roma, margin 120-44=76 >= 50 → PASS",
      rm.get("Psychology") == pc.PASS
      and _psych["value"] == {"team": 120.0, "opp": 44.0, "margin": 76.0}
      and _psych["field"] == "H_Base/A_Base")
check("WIN psychology rows audit the FULL WIN 8-rule set (not a mini-list)",
      ipc["total"] == 8 and len([c for c in ipc["checks"]
                                 if c["result"] == pc.NOT_AVAILABLE]) == 7)

awps_row = {"fixture_id": 501, "Fixture": "Roma vs Lazio",
            "Master_Pick": "Lazio"}
snap = fresh_snapshot({"wps_by_name": {pc._norm("Roma vs Lazio"): {
    "H_Base": 120, "A_Base": -44, "Audit_Score": 164}},
    "label_by_id": {"501": "Roma vs Lazio"}})
ipc = evaluate("win_psychology", dict(awps_row), snap)
rm = result_map(ipc)
check("WIN psychology: away pick Lazio, margin -44-120=-164 < 50 → FAIL",
      rm.get("Psychology") == pc.FAIL)
nopick = {"fixture_id": 502, "Fixture": "Roma vs Lazio"}
ipc = evaluate("win_psychology", dict(nopick), snap)
check("WIN psychology: row without any pick → 0/8, every check NOT_AVAILABLE",
      ipc is not None and ipc["total"] == 8 and ipc["passed"] == 0
      and all(c["result"] == pc.NOT_AVAILABLE for c in ipc["checks"]))

# ── 8b. WIN Corners — per-team expected corners, nearest engine first ────────
crow = {"fixture_id": 700, "Fixture": "Leeds vs Everton", "Target": "Leeds"}
# 1. stage2 by fixture id: predicted 10.2, diff +1.4 → home expects 5.8 > 4.4
s2 = {"fixture_id": 700, "fixture_name": "Leeds vs Everton",
      "predicted_corners": 10.2, "diff": 1.4}
snap = fresh_snapshot({"c2_by_id": {"700": dict(s2, __source="corners_stage2")},
                       "label_by_id": {"700": "Leeds vs Everton"}})
ipc = evaluate("win_apex", dict(crow), snap)
_cor = next(c for c in ipc["checks"] if c["name"] == "Corners")
check("WIN Corners: stage2 pair gives Leeds 5.8 vs Everton 4.4 → PASS",
      result_map(ipc).get("Corners") == pc.PASS
      and _cor["value"]["team_exp"] == 5.8
      and _cor["source"].startswith("corners_stage2"))
# Home-versus-away mapping flips when the pick is away.
ecrow = dict(crow, Target="Everton")
ipc = evaluate("win_apex", ecrow, snap)
check("WIN Corners: away pick gets the away expectation (4.4 < 5.8 → FAIL)",
      result_map(ipc).get("Corners") == pc.FAIL)
# 2. aggregator by label when stage2 is absent: Home_Exp/Away_Exp compare.
agg = {"Fixture": "Leeds vs Everton", "Home_Team": "Leeds", "Away_Team": "Everton",
       "Home_Exp": "4.1", "Away_Exp": "5.9", "Total_Exp": "10.0",
       "True_Corner_Fav": "Everton"}
snap = fresh_snapshot({"cagg_by_name": {pc._norm("Leeds vs Everton"): agg}})
ipc = evaluate("win_apex", dict(crow), snap)
check("WIN Corners: aggregator Home_Exp 4.1 < Away_Exp 5.9 → FAIL for Leeds",
      result_map(ipc).get("Corners") == pc.FAIL)
check("WIN Corners: still counts in the fixed denominator (x/8, not dropped)",
      ipc is not None and ipc["total"] == 8)
# 3. DNA last resort: Avg Corners winner carries the expected-corners pair.
dmf = {"corners": {"home_count": 3, "away_count": 3, "factors": [
    {"name": "Avg Corners", "home_value": 5.2, "away_value": 3.4,
     "winner": "home"}]}}
snap = fresh_snapshot({"dna_by_name": {pc._norm("Leeds vs Everton"): dmf},
                       "label_by_id": {"700": "Leeds vs Everton"}})
ipc = evaluate("win_apex", dict(crow), snap)
check("WIN Corners: DNA Avg Corners 5.2 > 3.4 → PASS (last resort)",
      result_map(ipc).get("Corners") == pc.PASS)
# 4. A DNA zero is 'no corner data', never a free pass.
zerof = {"corners": {"home_count": 3, "away_count": 3, "factors": [
    {"name": "Avg Corners", "home_value": 6.0, "away_value": 0,
     "winner": "home"}]}}
snap = fresh_snapshot({"dna_by_name": {pc._norm("Leeds vs Everton"): zerof},
                       "label_by_id": {"700": "Leeds vs Everton"}})
ipc = evaluate("win_apex", dict(crow), snap)
check("WIN Corners: DNA opponent value 0 → NOT_AVAILABLE (no fake FAIL/PASS)",
      result_map(ipc).get("Corners") == pc.NOT_AVAILABLE)
# 5. No corner data anywhere → NOT_AVAILABLE (fixed denominator, honest).
ipc = evaluate("win_apex", {"fixture_id": 701, "Fixture": "X vs Y",
                            "Target": "X"}, fresh_snapshot())
check("WIN Corners: no corner row anywhere → NOT_AVAILABLE",
      result_map(ipc).get("Corners") == pc.NOT_AVAILABLE)


# ── 9. GG composites (engine signals echo only; no invented thresholds) ──────
gg_row = {"fixture_id": 600, "fixture": "Basel vs St. Gallen",
          "sig1_mc_btts": 30.0, "sig2_venue_btts": 0.0, "sig3_gk_vuln": 20.0,
          "sig4_h2h_btts": 15.0, "sig5_directional": 0.0}
ipc = evaluate("gg_precision", dict(gg_row), fresh_snapshot())
rm = result_map(ipc)
check("GG precision signals: fired = points > 0 (3 fired, 2 not)",
      ipc["total"] == 5 and ipc["passed"] == 3
      and rm.get("MC BTTS") == pc.PASS and rm.get("Venue BTTS") == pc.FAIL)
o15_row = {"fixture_id": 601, "fixture": "Sporting KC vs Philadelphia Union",
           "combined_lambda": 4.0, "lambda_home": 1.6, "lambda_away": 2.4,
           "o15_score": 80.0}
ipc = evaluate("gg_o15", dict(o15_row), fresh_snapshot())
rm = result_map(ipc)
check("O1.5 composite: lambda 4.0 >= 2.5 saturation PASS, both lambdas >= 1.0 PASS",
      rm.get("Combined Lambda") == pc.PASS and rm.get("Attacking Intent") == pc.PASS)
check("O1.5 composite: missing gk flags → NOT_AVAILABLE, fixed denominator of 4",
      ipc["total"] == 4 and ipc["passed"] == 2)

# ── 10. FHVI / SHVI Category gate (>= 7 == TIER 2 or better) ─────────────────
ipc = evaluate("fhvi", {"fixture": "Legia vs Jagiellonia", "fhvi_score": 7.0},
               fresh_snapshot())
check("FHVI score 7 → PASS (TIER 2 boundary)", result_map(ipc).get("FHVI") == pc.PASS)
ipc = evaluate("fhvi", {"fixture": "Legia vs Jagiellonia", "fhvi_score": 6.9},
               fresh_snapshot())
check("FHVI score 6.9 → FAIL", result_map(ipc).get("FHVI") == pc.FAIL)
ipc = evaluate("shvi", {"fixture": "A vs B"}, fresh_snapshot())
check("SHVI missing score → NOT_AVAILABLE, 0/1 (fixed denominator, no fake FAIL)",
      ipc is not None and ipc["total"] == 1 and ipc["passed"] == 0)

print()
failed = [l for l, ok in RESULTS if not ok]
print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)





