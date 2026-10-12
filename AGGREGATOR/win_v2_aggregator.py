"""
AlienEdge Win Forecast v2 Aggregator — EXPERIMENTAL
==========================================================================
Reads the v2 engine's own output and publishes ONE ranked board under the
"win_v2_apex" save key. It is the v2 counterpart of win_apex_aggregator.py,
but deliberately simpler and deliberately v2-only:

  - NO cross-engine merges (no underdog / psychology / calibration joins).
    v2 already carries its own probabilities, edges and verdicts; importing
    another engine's signals here would manufacture confidence the v2 model
    never produced. An empty upstream stays empty (enforced upstream by
    main.py's ENGINE_UPSTREAM gate on "win_v2_apex" -> "win_forecast_v2").
  - The ranking is the model's own numbers, ordered honestly:
      1. verdict tier (VALUE CONFIRMED first)
      2. model confidence (HIGH first)
      3. expected value (desc)
      4. favoured probability (desc)
    No invented composite score, no logistic re-fit — this is an ordering
    of what the engine already said, not a new signal.
  - Every row carries model_version / calibration_version / apex_tier so
    the EXPERIMENTAL status travels with the data. See the v2 engine's
    HONESTY LEDGER: calibration is identity, thresholds unvalidated.

Reads : output/ranked_win_forecast_v2_{date}.csv  (fallback: the
        output_store snapshot saved under save_key "win_forecast_v2")
Writes: returns the row list; main.py saves it under "win_v2_apex".
"""

import os
import sys
import math
import time
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")


def _valid_fixture_id(fid):
    """Same BUG-2 guard as win_apex_aggregator: a real integer fixture id,
    or None for any placeholder (None, NaN, '', 'N/A', 'Unknown', ...)."""
    if fid is None:
        return None
    try:
        if pd.isna(fid):
            return None
    except (TypeError, ValueError):
        pass
    s = str(fid).strip()
    if not s or s.lower() in {"n/a", "na", "none", "unknown", "nan", "null", "-"}:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _f(x, default=0.0):
    """Tolerant float — CSV round-trips turn missing values into NaN/''."""
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
VERDICT_RANK = {
    "VALUE CONFIRMED": 0,
    "STRONG PREDICTION — NO VALUE": 1,
    "DO NOT AUTO-BET — LOW CONFIDENCE": 2,
    "NO BET": 3,
}


def _apex_tier(verdict, confidence):
    """Tier derived ONLY from the engine's own verdict + confidence — never
    an invented score. Every tier keeps the (EXPERIMENTAL) marker."""
    if verdict == "VALUE CONFIRMED" and confidence == "HIGH":
        return "ELITE (EXPERIMENTAL)"
    if verdict == "VALUE CONFIRMED":
        return "VALUE (EXPERIMENTAL)"
    if verdict == "STRONG PREDICTION — NO VALUE":
        return "STRONG (EXPERIMENTAL)"
    if verdict == "DO NOT AUTO-BET — LOW CONFIDENCE":
        return "WATCH (EXPERIMENTAL)"
    return "NO BET (EXPERIMENTAL)"


def _load_v2_rows(target_date):
    """Read the v2 engine's output for this date, preferring the file with
    the FULL schema.

    The engine writes two CSVs every run: the lean ranked forecast
    (ranked_win_forecast_v2_{date}.csv, a display-shaped subset) and the
    full audit board (win_model_audit_v2_{date}.csv, every column). The
    audit file is read FIRST because the apex rows carry fields the lean
    file omits — calibration_version, market_books, fair odds, per-side
    edge, lambdas, overround. Reading the lean file silently published
    those as blanks; reading the audit file publishes what the engine
    actually computed. Falls back to the lean file, then to the
    pipeline's own store snapshot.
    """
    for fname in (f"win_model_audit_v2_{target_date}.csv",
                  f"ranked_win_forecast_v2_{target_date}.csv"):
        path = os.path.join(OUTPUT_DIR, fname)
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                if len(df) > 0:
                    return df.to_dict(orient="records")
            except Exception:
                pass
    try:
        sys.path.insert(0, BASE_DIR)
        from output_store import load
        data, _meta = load("win_forecast_v2", target_date, default=None)
        if data:
            return list(data)
    except Exception:
        pass
    return []


def run_win_v2_aggregator(target_date=None):
    """Rank the v2 engine's own board into the apex view. Returns a list of
    dicts (saved by main.py under "win_v2_apex"); [] when the engine
    produced nothing usable for this date."""
    if not target_date:
        target_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"[win-v2-agg] Win Forecast v2 Aggregator (EXPERIMENTAL) start: {target_date}")

    rows_in = _load_v2_rows(target_date)
    if not rows_in:
        print(f"[win-v2-agg] No v2 engine output for {target_date} — nothing to rank.")
        return []

    out = []
    for r in rows_in:
        fid = _valid_fixture_id(r.get("fixture_id"))
        if fid is None:
            continue
        conf = str(r.get("model_confidence") or "LOW")
        verdict = str(r.get("final_verdict") or "NO BET")

        out.append({
            "fixture_id": fid,
            "fixture": r.get("fixture") or "",
            "home_team": r.get("home_team") or "",
            "away_team": r.get("away_team") or "",
            "league_id": r.get("league_id") or "",

            "favoured_side": r.get("favoured_side") or "",
            "favoured_probability": round(_f(r.get("favoured_probability")), 4),
            "model_confidence": conf,
            "model_confidence_reason": r.get("model_confidence_reason") or "",
            "final_verdict": verdict,
            "apex_tier": _apex_tier(verdict, conf),
            "data_quality": r.get("data_quality") or "",

            "favoured_edge_pp": round(_f(r.get("favoured_edge_pp")), 2),
            "favoured_ev": round(_f(r.get("favoured_ev")), 4),

            "home_fair_odds": r.get("home_fair_odds"),
            "draw_fair_odds": r.get("draw_fair_odds"),
            "away_fair_odds": r.get("away_fair_odds"),
            "home_market_odds": r.get("home_market_odds"),
            "draw_market_odds": r.get("draw_market_odds"),
            "away_market_odds": r.get("away_market_odds"),
            "market_books": int(_f(r.get("market_books"))),

            "calibrated_home_probability": r.get("calibrated_home_probability"),
            "calibrated_draw_probability": r.get("calibrated_draw_probability"),
            "calibrated_away_probability": r.get("calibrated_away_probability"),
            "home_edge_pp": r.get("home_edge_pp"),
            "draw_edge_pp": r.get("draw_edge_pp"),
            "away_edge_pp": r.get("away_edge_pp"),

            "lambda_home": r.get("lambda_home"),
            "lambda_away": r.get("lambda_away"),
            "league_goals_prior": r.get("league_goals_prior"),
            "bookmaker_overround_pct": r.get("bookmaker_overround_pct"),
            "score_matrix_tail_mass": r.get("score_matrix_tail_mass"),

            "model_version": r.get("model_version") or "",
            "calibration_version": r.get("calibration_version") or "",
            "strength_model_version": r.get("strength_model_version") or "",
        })

    if not out:
        print("[win-v2-agg] No valid fixture ids in v2 output — nothing to rank.")
        return []

    # Honest ordering of the model's own numbers — no invented composite.
    out.sort(key=lambda r: (
        VERDICT_RANK.get(r["final_verdict"], 3),
        -CONFIDENCE_RANK.get(r["model_confidence"], 0),
        -_f(r["favoured_ev"]),
        -_f(r["favoured_probability"]),
    ))
    for i, r in enumerate(out, start=1):
        r["apex_rank"] = i

    # Atomic audit CSV of exactly what was published.
    audit_path = os.path.join(OUTPUT_DIR, f"win_v2_apex_{target_date}.csv")
    try:
        tmp = audit_path + ".tmp"
        pd.DataFrame(out).to_csv(tmp, index=False)
        os.replace(tmp, audit_path)
    except Exception as exc:
        print(f"[win-v2-agg][WARN] audit CSV not written: {exc}")

    print(f"[win-v2-agg][DONE] {len(out)} fixtures ranked.")
    print(f"[win-v2-agg] Tier distribution:"
          f"\n{pd.Series([r['apex_tier'] for r in out]).value_counts().to_string()}")
    print("[win-v2-agg] REMINDER: EXPERIMENTAL — calibration_version is "
          "'none-identity-v0'; thresholds are unvalidated starting defaults.")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _d = sys.argv[1].strip()
        try:
            datetime.strptime(_d, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(f"Invalid date '{_d}'. Use the format YYYY-MM-DD.")
    else:
        _d = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    run_win_v2_aggregator(_d)
