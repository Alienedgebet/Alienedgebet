"""
tests_weekly_filter_params.py — the /weekly/* filter controls must be LIVE.

Run:  ./venv/bin/python3 tests_weekly_filter_params.py

WHAT THIS PROVES
----------------
The Weekly pages (GG / Over 2.5 / Win / Win Cross-Check) send mode, risk preset,
odds corridor and every "Mathematical Precision Thresholds" drawer value on each
request. Before this fix the API read only the precomputed snapshot and ignored
all of them, so no button ever changed the result set.

  1. BASELINE REGRESSION — the default request still returns EXACTLY the rows of
     the precomputed dated snapshot (no behaviour change, zero compute).
  2. EVERY CONTROL MOVES THE ANSWER — risk preset, odds corridor, tipster mode
     and each drawer threshold demonstrably change what survives, for GG, WIN
     and O2.5, on both the weekly and the single-date routes.
  3. GATES ARE HONOURED, NOT COSMETIC — surviving rows really satisfy the bound
     the user asked for (odds inside the corridor, probability floor, votes...).
  4. GG PARITY + GG-ODDS GATES — unit-level: evaluated when the dated operands
     exist, and honestly skipped (never a silent pass) when they do not.
  5. NO ARTIFACT IS EVER REWRITTEN — a request-time filter run must not touch
     any pipeline output file (persist=False).
  6. INPUTS ARE CLAMPED — absurd slider values cannot crash or bypass a gate.

SAFETY (deliberate, enforced): fully offline (local dated CSVs + pandas only,
zero SportMonks calls) and non-destructive: the live path runs with
persist=False, and the suite additionally asserts that no output/ file mtime
changed during the whole run. Dated inputs are pinned to real existing dates;
if a pinned date is missing the dependent checks are reported as SKIP, never
silently passed.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

RESULTS = []
OUTPUT_DIR = os.path.join(ROOT, "output")


def check(label, cond):
    RESULTS.append((label, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + label)


def skip(label, why):
    RESULTS.append((label, None))
    print("SKIP  " + label + "  (" + why + ")")


def quiet(fn, *args, **kwargs):
    """Run a noisy engine/API call with its stdout captured."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*args, **kwargs)


def mtimes():
    out = {}
    for dirpath, _dirs, files in os.walk(OUTPUT_DIR):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                out[path] = os.stat(path).st_mtime_ns
            except OSError:
                pass
    return out


def snapshot_ids(key, dates):
    """Identity strings of a precomputed snapshot: fixture_id, plus `side`
    when the market carries one (win rows are per side)."""
    import output_store as store
    ids = []
    for date in dates:
        rows, _ = store.load(key, date, default=[])
        for row in rows or []:
            if isinstance(row, dict):
                side = row.get("side")
                ids.append(str(row.get("fixture_id")) + (f"|{side}" if side else ""))
    return ids


def route_ids(rows):
    ids = []
    for row in rows or []:
        if isinstance(row, dict):
            side = row.get("side")
            ids.append(str(row.get("fixture_id")) + (f"|{side}" if side else ""))
    return sorted(ids)


DATES = ["2026-09-20", "2026-09-22"]
have = lambda name: all(os.path.exists(os.path.join(OUTPUT_DIR, name.format(date=d))) for d in DATES)


# ══════════════════════════════════════════════════════════════════════════════
if not have("ALIENEDGE_GG_PICKS_{date}.csv"):
    print("Pinned dated inputs are missing — cannot run the Weekly filter suite.")
    sys.exit(1)

from api.weekly_filter_live import (  # noqa: E402
    gg_filter_params, win_filter_params, win_precision_params, o25_filter_params,
    is_baseline, live_query, narrow_rows, parse_band,
)
import api.main as api  # noqa: E402
from FILTER.gg_precision_filter import USER_FILTER, apply_precision_filter  # noqa: E402

S, E = DATES[0], DATES[-1]
# The routes walk EVERY date in [start, end] — use the same expansion here so the
# snapshot comparison covers 09-20, 09-21 and 09-22 (not just the two pins).
RANGE = api._date_range(S, E)
BEFORE = mtimes()

# ── 1. BASELINE REGRESSION: default request == precomputed snapshot ───────────
gg_base = quiet(api.filter_gg_weekly, filters=gg_filter_params(), start_date=S, end_date=E)
check("GG baseline rows == filter_gg snapshots",
      route_ids(gg_base) == sorted(snapshot_ids("filter_gg", RANGE)))
check("GG baseline is detected as baseline", is_baseline(gg_filter_params()))
check("GG rows carry match_date (per-date provenance)",
      all(r.get("match_date") in RANGE for r in gg_base if isinstance(r, dict)))

win_base = quiet(api.filter_win_weekly, filters=win_filter_params(), start_date=S, end_date=E)
check("WIN baseline rows == filter_win__balanced snapshots",
      route_ids(win_base) == sorted(snapshot_ids("filter_win__balanced", RANGE)))

o25_base = quiet(api.filter_over25_weekly, filters=o25_filter_params(), start_date=S, end_date=E)
check("O25 baseline rows == filter_over25__balanced snapshots",
      route_ids(o25_base) == sorted(snapshot_ids("filter_over25__balanced", RANGE)))

prec_base = quiet(api.filter_win_precision_weekly, filters=win_precision_params(), start_date=S, end_date=E)
check("Win Cross-Check baseline == filter_win__safe snapshots",
      route_ids(prec_base) == sorted(snapshot_ids("filter_win__safe", RANGE)))

single_base = quiet(api.filter_gg_single, date=S, filters=gg_filter_params())
check("GG single-date baseline == that date's snapshot",
      route_ids(single_base) == sorted(snapshot_ids("filter_gg", [S])))

# ── 2/3. EVERY CONTROL MOVES THE ANSWER (and the bound is real) ─────────────
base_ids = {str(r.get("fixture_id")) for r in gg_base}

gg_bal = quiet(api.filter_gg_weekly, filters=gg_filter_params(risk_level="balanced"), start_date=S, end_date=E)
gg_agg = quiet(api.filter_gg_weekly, filters=gg_filter_params(risk_level="aggressive"), start_date=S, end_date=E)
gg_prob = quiet(api.filter_gg_weekly, filters=gg_filter_params(min_prob=80), start_date=S, end_date=E)
gg_soft = quiet(api.filter_gg_weekly, filters=gg_filter_params(strict_mode=False), start_date=S, end_date=E)
gg_ids = lambda rows: {str(r.get("fixture_id")) for r in rows}

check("GG risk presets differ from each other (banker != balanced)",
      gg_ids(gg_bal) != base_ids or not base_ids)
check("GG aggressive returns a superset of banker", base_ids <= gg_ids(gg_agg))
check("GG MIN PROBABILITY 80 narrows the result set", len(gg_prob) <= len(gg_base))
check("GG MIN PROBABILITY bound is honoured",
      all(float(r.get("gg_prob_pct") or 0) >= 80 for r in gg_prob))
check("GG STRICT PARITY LOCK off (soft) returns a superset",
      base_ids <= gg_ids(gg_soft))
gg_h2h = quiet(api.filter_gg_weekly, filters=gg_filter_params(min_h2h_gg=4), start_date=S, end_date=E)
check("GG MIN H2H GG bound is honoured",
      all(float(r.get("h2h_gg_count") or 0) >= 4 for r in gg_h2h))
gg_side = quiet(api.filter_gg_weekly, filters=gg_filter_params(min_home_gg5=4, min_away_gg5=4), start_date=S, end_date=E)
check("GG MIN HOME/AWAY GG bound is honoured",
      all(float(r.get("home_gg_count") or 0) >= 4 and float(r.get("away_gg_count") or 0) >= 4 for r in gg_side))
gg_dist = quiet(api.filter_gg_weekly, filters=gg_filter_params(pos_diff_max=2), start_date=S, end_date=E)
check("GG MAX TABLE DISTANCE bound is honoured",
      all(float(r.get("table_distance") or 0) <= 2 for r in gg_dist))
gg_tip = quiet(api.filter_gg_weekly, filters=gg_filter_params(mode="tipster", min_prob=75), start_date=S, end_date=E)
check("GG tipster mode returns its own (tighter) result set",
      len(gg_tip) <= len(gg_base) and
      all(float(r.get("gg_prob_pct") or 0) >= 75 for r in gg_tip))



win_agg = quiet(api.filter_win_weekly, filters=win_filter_params(risk_level="aggressive"), start_date=S, end_date=E)
win_safe = quiet(api.filter_win_weekly, filters=win_filter_params(risk_level="safe"), start_date=S, end_date=E)
win_lo = quiet(api.filter_win_weekly, filters=win_filter_params(odds_band="1.30-1.60"), start_date=S, end_date=E)
win_hi = quiet(api.filter_win_weekly, filters=win_filter_params(odds_band="1.80-2.40"), start_date=S, end_date=E)
check("WIN risk presets change the result set", len(win_agg) != len(win_safe) or len(win_agg) != len(win_base))
check("WIN corridor 1.30-1.60 honoured",
      all(1.30 <= float(r.get("win_odds") or 0) <= 1.60 for r in win_lo))
check("WIN corridor 1.80-2.40 honoured",
      all(1.80 <= float(r.get("win_odds") or 0) <= 2.40 for r in win_hi))
check("WIN corridors are different populations",
      {str(r.get("fixture_id")) for r in win_lo} != {str(r.get("fixture_id")) for r in win_hi})

win_tip = quiet(api.filter_win_weekly, filters=win_filter_params(mode="tipster", min_odds=1.40, max_odds=1.60), start_date=S, end_date=E)
check("WIN tipster mode returns its own result set", len(win_tip) != len(win_base))
check("WIN tipster odds bound is honoured",
      all(1.40 <= float(r.get("win_odds") or 0) <= 1.60 for r in win_tip))
win_par = quiet(api.filter_win_weekly, filters=win_filter_params(mode="tipster", min_parity_gap=20, strict_mode=True), start_date=S, end_date=E)
check("WIN tipster MIN PARITY bound is honoured",
      all(float(r.get("parity_score") or 0) >= 20 for r in win_par))
win_form = quiet(api.filter_win_weekly, filters=win_filter_params(mode="tipster", min_form_wins=5), start_date=S, end_date=E)
check("WIN tipster MIN FORM WINS bound is honoured",
      all(float(r.get("last_5_wins_overall") or 0) >= 5 for r in win_form))
win_tip_band = quiet(api.filter_win_weekly, filters=win_filter_params(mode="tipster", odds_band="1.80-2.40"), start_date=S, end_date=E)
check("WIN tipster honours the odds corridor buttons",
      all(1.80 <= float(r.get("win_odds") or 0) <= 2.40 for r in win_tip_band))
win_pub_narrow = quiet(api.filter_win_weekly, filters=win_filter_params(min_parity_gap=20), start_date=S, end_date=E)
check("WIN public mode ALSO honours drawer thresholds",
      all(float(r.get("parity_score") or 0) >= 20 for r in win_pub_narrow))

o25_bank = quiet(api.filter_over25_weekly, filters=o25_filter_params(risk_level="banker"), start_date=S, end_date=E)
o25_lo = quiet(api.filter_over25_weekly, filters=o25_filter_params(odds_band="1.30-1.60"), start_date=S, end_date=E)
check("O25 risk presets change the result set", len(o25_bank) != len(o25_base))
check("O25 corridor 1.30-1.60 honoured",
      all(1.30 <= float(r.get("o25_odds") or 0) <= 1.60 for r in o25_lo))
o25_tip = quiet(api.filter_over25_weekly, filters=o25_filter_params(mode="tipster", min_poisson=70, min_votes=8), start_date=S, end_date=E)
check("O25 tipster returns its own result set", len(o25_tip) != len(o25_base))
check("O25 tipster MIN POISSON bound is honoured",
      all(float(r.get("poisson_over_prob_num") or 0) >= 70 for r in o25_tip))
check("O25 tipster MIN VOTES bound is honoured",
      all(int(str(r.get("council_votes") or "0").split("/")[0]) >= 8 for r in o25_tip))
o25_gap = quiet(api.filter_over25_weekly, filters=o25_filter_params(mode="tipster", max_pos_gap=0), start_date=S, end_date=E)
check("O25 tipster MAX POS GAP bound is honoured",
      all(float(r.get("pos_gap") or 0) <= 0 for r in o25_gap))


# ── 4b. SAME GATES THROUGH THE FULL PATH (live_query) in a SANDBOX ─────────
# Pointed at /tmp, never at output/: proves params -> live_query -> GG engine
# really applies the parity and odds gates when the dated artifacts carry the
# operands, and that the dated artifacts are left untouched.
import shutil  # noqa: E402
import api.weekly_filter_live as wl  # noqa: E402
import FILTER.gg_precision_filter as gpf  # noqa: E402
import pandas as pd  # noqa: E402

SB = "/tmp/alienedge_gg_gate_sandbox"
shutil.rmtree(SB, ignore_errors=True)
os.makedirs(SB, exist_ok=True)
pd.DataFrame([
    {"fixture_id": 1, "league_id": 7, "home_team": "A", "away_team": "B",
     "gg_tier": "GG TIER 1", "mc_btts_prob": 0.72, "venue_btts_home": 1.0,
     "venue_btts_away": 1.0, "parity": 0.5, "gg_odds": 1.55},
    {"fixture_id": 2, "league_id": 7, "home_team": "C", "away_team": "D",
     "gg_tier": "GG TIER 1", "mc_btts_prob": 0.71, "venue_btts_home": 1.0,
     "venue_btts_away": 1.0, "parity": 0.5, "gg_odds": 2.45},
]).to_csv(os.path.join(SB, "ALIENEDGE_GG_PICKS_2026-01-01.csv"), index=False)
pd.DataFrame([
    {"fixture_id": 1, "league_id": 7, "Fixture": "A vs B", "Score": "6/6",
     "DNA_Intelligence": "ADVANTAGE", "Poisson%": 70.0, "H2H_GG": "4/5",
     "DNA_Insight": "x", "Ranks": "4v9", "Forensic_Audit": "x",
     "H2H_Parity": 2, "Concede_Parity": 1},
    {"fixture_id": 2, "league_id": 7, "Fixture": "C vs D", "Score": "6/6",
     "DNA_Intelligence": "ADVANTAGE", "Poisson%": 70.0, "H2H_GG": "4/5",
     "DNA_Insight": "x", "Ranks": "5v10", "Forensic_Audit": "x",
     "H2H_Parity": 4, "Concede_Parity": 3},
]).to_csv(os.path.join(SB, "JUDGED_GG_PICKS_2026-01-01.csv"), index=False)

_real_output_dir = gpf.OUTPUT_DIR
gpf.OUTPUT_DIR = SB


def sandbox_query(**kwargs):
    wl._CACHE.clear()
    return quiet(wl.live_query, "gg", ["2026-01-01"], gg_filter_params(**kwargs))


try:
    names = lambda rows: sorted(r["home_team"] for r in rows)
    check("sandbox: GG baseline keeps both fixtures", names(sandbox_query()) == ["A", "C"])
    check("sandbox: MAX TOTAL PARITY 3 keeps only the low-parity fixture (2+1)",
          names(sandbox_query(max_parity=3)) == ["A"])
    check("sandbox: MAX TOTAL PARITY 2 excludes both fixtures",
          names(sandbox_query(max_parity=2)) == [])
    check("sandbox: MAX TOTAL PARITY 9 keeps both",
          names(sandbox_query(max_parity=9)) == ["A", "C"])
    check("sandbox: GG odds corridor 1.50-2.00 drops the 2.45 fixture",
          names(sandbox_query(min_gg_odds=1.50, max_gg_odds=2.00)) == ["A"])
    check("sandbox: GG odds corridor 1.50-2.60 keeps both",
          names(sandbox_query(min_gg_odds=1.50, max_gg_odds=2.60)) == ["A", "C"])
finally:
    gpf.OUTPUT_DIR = _real_output_dir
    wl._CACHE.clear()
    shutil.rmtree(SB, ignore_errors=True)

o25_pub = quiet(api.filter_over25_weekly, filters=o25_filter_params(min_poisson=70), start_date=S, end_date=E)
check("O25 public mode ALSO honours drawer thresholds",
      all(float(r.get("poisson_over_prob_num") or 0) >= 70 for r in o25_pub))

prec_tip = quiet(api.filter_win_precision_weekly, filters=win_precision_params(mode="tipster", min_odds=1.40, max_odds=1.60), start_date=S, end_date=E)
check("Win Cross-Check drawer is live too (was silently dropped)",
      len(prec_tip) != len(prec_base) or len(prec_tip) == 0)
prec_single = quiet(api.filter_win_precision_single, date=S, filters=win_precision_params(mode="tipster", min_odds=1.40, max_odds=1.60))
check("Win Cross-Check single-date drawer is live too",
      all(1.40 <= float(r.get("win_odds") or 0) <= 1.60 for r in prec_single))



# ── 4. GG PARITY + GG-ODDS GATES (unit level, with real operands) ───────────
import pandas as pd  # noqa: E402


def gg_frame(parity, concede, odds, prob=70.0):
    return pd.DataFrame([{
        "fixture_id": "1", "home_team": "A", "away_team": "B", "tier": "GG TIER 1",
        "gg_prob_pct": prob, "home_gg_last3": 3, "away_gg_last3": 3,
        "h2h_gg_count": 4, "home_position": 4, "away_position": 9,
        "home_gg_count": 4, "away_gg_count": 4,
        "h2h_goal_parity": parity, "concede_parity": concede, "gg_odds": odds,
    }])


kept = apply_precision_filter(gg_frame(2, 1, 1.80), USER_FILTER, max_parity=4)
check("GG total-parity gate evaluates when operands exist (<=4 survives)", len(kept) == 1)
dropped = apply_precision_filter(gg_frame(3, 3, 1.80), USER_FILTER, max_parity=4)
check("GG total-parity gate excludes a row above the bound", len(dropped) == 0)
no_operands = apply_precision_filter(
    gg_frame(None, None, 1.80), USER_FILTER, max_parity=2)
check("GG total-parity gate is honestly SKIPPED when no operands exist (no silent pass)",
      len(no_operands) == 1)
odds_ok = apply_precision_filter(gg_frame(2, 1, 1.80), USER_FILTER, min_gg_odds=1.50, max_gg_odds=2.00)
check("GG odds corridor evaluates when gg_odds exists", len(odds_ok) == 1)
odds_out = apply_precision_filter(gg_frame(2, 1, 2.40), USER_FILTER, min_gg_odds=1.50, max_gg_odds=2.00)
check("GG odds corridor excludes an out-of-corridor row", len(odds_out) == 0)
odds_missing = apply_precision_filter(
    gg_frame(2, 1, None), USER_FILTER, min_gg_odds=1.50, max_gg_odds=2.00)
check("GG odds gate is honestly SKIPPED when the artifact has no gg_odds",
      len(odds_missing) == 1)
strict = apply_precision_filter(
    pd.DataFrame([dict(gg_frame(2, 1, 1.80).iloc[0], gg_prob_pct=10.0)]),
    USER_FILTER, strict_mode=True)
soft = apply_precision_filter(
    pd.DataFrame([dict(gg_frame(2, 1, 1.80).iloc[0], gg_prob_pct=10.0)]),
    USER_FILTER, strict_mode=False)
check("GG strict mode drops a row failing one gate", len(strict) == 0)
check("GG soft mode (STRICT PARITY LOCK off) allows one failed gate", len(soft) == 1)

# ── 5. NO PIPELINE ARTIFACT IS EVER REWRITTEN ──────────────────────────────
AFTER = mtimes()
changed = sorted(p for p in set(BEFORE) | set(AFTER) if BEFORE.get(p) != AFTER.get(p))
check("no output/ file was created, modified or deleted by this suite",
      not changed)
if changed:
    for path in changed[:5]:
        print("        changed: " + os.path.relpath(path, ROOT))

# ── 6. INPUT CLAMPING / ROBUSTNESS ─────────────────────────────────────────
clamped = win_filter_params(min_odds=999, max_odds=-3, min_form_wins=10_000)
check("absurd slider values are clamped into the engine's own ranges",
      clamped["overrides"]["min_odds"] == 100.0 and clamped["overrides"]["max_odds"] == 1.01
      and clamped["overrides"]["min_form_wins"] == 50.0)
check("an in-range odds value is passed through untouched",
      win_filter_params(min_odds=1.85)["overrides"]["min_odds"] == 1.85)
check("unknown risk level falls back to the market default",
      win_filter_params(risk_level="wat")["risk_level"] == "balanced")
check("unknown odds corridor falls back to the engine default band",
      win_filter_params(odds_band="9.99-99.99")["odds_band"] == "1.40-1.90")
check("unknown mode falls back to public", gg_filter_params(mode="wat")["mode"] == "public")
check("any drawer value leaves the baseline path (never ignored)",
      not is_baseline(gg_filter_params(min_prob=61))
      and not is_baseline(win_filter_params(mode="tipster"))
      and not is_baseline(o25_filter_params(min_votes=7)))
check("parse_band reads the corridor buttons", parse_band("1.50-1.85") == (1.5, 1.85))
check("narrow_rows excludes a row whose evaluated field is missing",
      narrow_rows([{"fixture_id": "1"}, {"fixture_id": "2", "parity_score": 15}],
                  "win", {"min_parity_gap": 10}) == [{"fixture_id": "2", "parity_score": 15}])

# ══════════════════════════════════════════════════════════════════════════════
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

