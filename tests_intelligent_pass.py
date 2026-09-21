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
    NOT_AVAILABLE (denominator excludes them). Tests then override only the
    sources relevant to the rule under test."""
    snap = {
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
    pc.clear_cache()
    pc._SNAPSHOTS[DATE] = snap
    rows = pc.evaluate_market(market, [dict(row)], DATE)
    return rows[0]["intelligent_pass_count"]


def result_map(ipc):
    return {c["name"]: c["result"] for c in (ipc or {}).get("checks", [])}
# ── 1. WIN — Parity +10 ──────────────────────────────────────────────────────
win_row = {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "Target": "Arsenal"}
side_rows = [
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Arsenal",
     "parity_score": 12, "last_5_goals_scored": 11, "opp_last_5_goals_scored": 6},
    {"fixture_id": 100, "Fixture": "Arsenal vs Chelsea", "team_name": "Chelsea",
     "parity_score": -12, "last_5_goals_scored": 6, "opp_last_5_goals_scored": 11},
]
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows}})
ipc = evaluate("win_apex", win_row, snap)
rm = result_map(ipc)
check("WIN Parity +12 → PASS", rm.get("Parity +10") == pc.PASS)

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
check("WIN Parity excluded from the denominator",
      ipc is not None and ipc["total"] == 1 and ipc["passed"] == 1)
ipc = evaluate("win_apex", win_row, fresh_snapshot())
check("WIN all-missing → ipc None (denominator 0, never fake FAIL)",
      ipc is None)
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
check("DRAW DNA Parity excluded from the denominator",
      ipc is not None and ipc["total"] == 1)
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
check("U2S missing multipliers do NOT enter the denominator",
      ipc is not None and ipc["total"] == 1 and ipc["passed"] == 1)
# ── 4. Per-fixture availability / denominator integrity ──────────────────────
ipc = evaluate("u2s", ud_row, fresh_snapshot())
check("U2S all-missing → ipc None (no fake FAIL from missing intelligence)",
      ipc is None)

ipc = evaluate("u2s", {"fixture_id": 300, "fixture": "Bournemouth vs Liverpool",
                       "Underdog": "Bournemouth", "Psych_Score": "VETOED"},
               fresh_snapshot())
check("U2S 'VETOED' psychology → NOT_AVAILABLE, ipc None (no fake FAIL)",
      ipc is None)
# ── 5. Display/audit-only guarantee ──────────────────────────────────────────
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows}})
rows = pc.evaluate_market("win_apex", [dict(win_row)], DATE)
row_keys_before = {"fixture_id", "Fixture", "Target"}
check("evaluate_market only ADDS intelligent_pass_count (prediction untouched)",
      set(rows[0].keys()) == row_keys_before | {"intelligent_pass_count"})
check("evaluate_market_safe returns rows unchanged on evaluator crash",
      pc.evaluate_market_safe("win_apex", [dict(win_row)], "bogus-date") is not None)
# ── 6. WIN on forecast side rows (Target fallback → team_name) ───────────────
fc_row = {"fixture_id": 100, "fixture": "Arsenal vs Chelsea", "team_name": "Chelsea",
          "parity_score": -14, "last_5_goals_scored": 4, "opp_last_5_goals_scored": 9}
snap = fresh_snapshot({"win_by_id": {"100": side_rows},
                       "win_by_name": {pc._norm("Arsenal vs Chelsea"): side_rows}})
ipc = evaluate("win_apex", fc_row, snap)
rm = result_map(ipc)
check("WIN forecast row resolves its own side (Chelsea parity -14 → FAIL)",
      rm.get("Parity +10") == pc.FAIL
      and next(c for c in ipc["checks"] if c["name"] == "Parity +10")["value"] == -14)
check("WIN forecast row Form compares the selected side (4 < 9 → FAIL)",
      rm.get("Form") == pc.FAIL)

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
check("O2.5 pos_gap 99 sentinel → NOT_AVAILABLE (not a fake FAIL)",
      result_map(ipc).get("Position Gap") == pc.NOT_AVAILABLE
      and ipc["total"] == 1 and ipc["passed"] == 1)
ipc = evaluate("over25_apex", {"fixture_id": 999, "fixture": "No Rows vs At All"},
               fresh_snapshot())
check("O2.5 apex with no forecast row → every gate NOT_AVAILABLE, ipc None",
      ipc is None)

# ── 8. WIN PSYCHOLOGY rows (fixture-level, side-neutral) ─────────────────────
wps_row = {"fixture_id": 500, "Fixture": "Roma vs Lazio"}
snap = fresh_snapshot({"wps_by_name": {pc._norm("Roma vs Lazio"): {
    "H_Base": 120, "A_Base": 44, "Audit_Score": 76}},
    "sot_by_name": {pc._norm("Roma vs Lazio"): {
        "Verdict": "DIAMOND", "Game_Script": "GLASS CANNONS"}}})
ipc = evaluate("win_psychology", dict(wps_row), snap)
rm = result_map(ipc)
check("WIN psychology: signed net H>A → PASS, SOT DIAMOND → PASS",
      rm.get("Psychology") == pc.PASS and rm.get("SOT") == pc.PASS)
check("WIN psychology: missing corners/underdog/draw excluded from denominator",
      ipc["total"] == 2 and ipc["passed"] == 2)

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
check("O1.5 composite: missing gk flags → NOT_AVAILABLE, denominator 2",
      ipc["total"] == 2 and ipc["passed"] == 2)

# ── 10. FHVI / SHVI Category gate (>= 7 == TIER 2 or better) ─────────────────
ipc = evaluate("fhvi", {"fixture": "Legia vs Jagiellonia", "fhvi_score": 7.0},
               fresh_snapshot())
check("FHVI score 7 → PASS (TIER 2 boundary)", result_map(ipc).get("FHVI") == pc.PASS)
ipc = evaluate("fhvi", {"fixture": "Legia vs Jagiellonia", "fhvi_score": 6.9},
               fresh_snapshot())
check("FHVI score 6.9 → FAIL", result_map(ipc).get("FHVI") == pc.FAIL)
ipc = evaluate("shvi", {"fixture": "A vs B"}, fresh_snapshot())
check("SHVI missing score → NOT_AVAILABLE, ipc None (no fake FAIL)", ipc is None)

print()
failed = [l for l, ok in RESULTS if not ok]
print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)





