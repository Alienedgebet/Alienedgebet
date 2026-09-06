import os
import sys
import json
import csv
import traceback
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ── PATH BOOTSTRAP ────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_DIR = os.path.join(ROOT, "output")
MASTER_AGG_DIR = os.path.join(ROOT, "master_aggregator")

# ── APP INIT ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlienEdge Prediction API",
    version="2.0.0",
    description="Forensic football prediction engine — REST interface",
)

# ── CORS SPECIFICATION (Supports all Vercel domains & local dev) ───────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://alienedgebet.vercel.app",
        "https://alienedgebet-baston1.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── ROUTERS ───────────────────────────────────────────────────────────────────
from api.user_rules_router import router as user_rules_router
app.include_router(user_rules_router)

# ── VERIFICATION SETTLEMENT IMPORTS (Root Level) ──────────────────────────────
from settlement_service import settle_predictions
from live_cache import get_live_scores_cached


# ── DISK READING HELPERS ──────────────────────────────────────────────────────
def _read_json(path: str, default=None):
    """Fast disk read for JSON snapshots."""
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_csv(path: str, default=None):
    """Fast disk read for pre-computed CSV prediction files."""
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # Format numbers if possible
                row = {}
                for k, v in r.items():
                    try:
                        if "." in v:
                            row[k] = float(v)
                        else:
                            row[k] = int(v)
                    except (ValueError, TypeError):
                        row[k] = v
                rows.append(row)
        return rows
    except Exception:
        return default


def _read_disk_first(candidate_paths, fallback_fn=None, *args, **kwargs):
    """
    Looks for existing pre-computed files on disk first.
    Only falls back to live engine execution if no file exists.
    """
    for p in candidate_paths:
        if os.path.exists(p) and os.path.getsize(p) > 10:
            if p.endswith(".json"):
                data = _read_json(p, None)
            elif p.endswith(".csv"):
                data = _read_csv(p, None)
            else:
                data = None
            if data:
                return data

    # Fallback to live computation if no pre-computed file is on disk
    if fallback_fn:
        try:
            res = fallback_fn(*args, **kwargs)
            return res if res is not None else []
        except Exception:
            return []
    return []


def _run(fn, *args, **kwargs):
    """Run an engine safely catching exceptions."""
    try:
        result = fn(*args, **kwargs)
        return result if result is not None else []
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


def _settled(data, market_type="win", date_str=None):
    """
    Enriches prediction rows with live scores and ✅/❌ verdicts.
    Reads from daily_archiver JSON if viewing a past date (0 API cost).
    """
    if not isinstance(data, list) or len(data) == 0:
        return data

    # 1. Check if an offline archive exists for this date (0 API calls)
    if date_str:
        archive_path = os.path.join(OUTPUT_DIR, f"archive_{date_str}.json")
        archive_data = _read_json(archive_path, None)
        if archive_data and "fixtures" in archive_data:
            return settle_predictions(data, archive_data["fixtures"], market_type=market_type)

    # 2. Live in-play fallback (2-min shared cache)
    try:
        live_db = get_live_scores_cached()
        return settle_predictions(data, live_db, market_type=market_type)
    except Exception:
        return data


def _incoming_rows_from_disk():
    """Normalize incoming_predictions.json → [{fixture_id, fixture, picks}]."""
    path = os.path.join(DATA_DIR, "incoming_predictions.json")
    raw = _read_json(path, {})
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    rows = []
    for fixture_id, value in raw.items():
        if isinstance(value, list):
            rows.append({
                "fixture_id": str(fixture_id),
                "fixture": str(fixture_id),
                "picks": value,
            })
        elif isinstance(value, dict):
            picks = value.get("picks", [])
            rows.append({
                "fixture_id": str(value.get("fixture_id", fixture_id)),
                "fixture": str(value.get("fixture", fixture_id)),
                "picks": picks if isinstance(picks, list) else [],
            })
    return rows


# ════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "AlienEdge Prediction API", "version": "2.0.0"}


# ════════════════════════════════════════════════════════════════════════════
# FOUNDATION ENGINES (Disk-First)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/dna/{date}", tags=["Foundation"])
def get_dna_profiles(date: str):
    p1 = os.path.join(DATA_DIR, "team_dna_profiles.json")
    p2 = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    from CORE.dna_profiler import run_dna_profiler
    return _read_disk_first([p1, p2], fallback_fn=run_dna_profiler, target_date=date)


@app.get("/api/dna/v2/{date}", tags=["Foundation"])
def get_dna_v2(date: str):
    profiles_path = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    clashes_path = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
    factors_path = os.path.join(DATA_DIR, "dna_v2_market_factors.json")

    profiles = _read_json(profiles_path, {})
    clashes = _read_json(clashes_path, [])
    factors = _read_json(factors_path, {})

    if profiles and clashes:
        return {
            "dna_profiles": profiles,
            "fixture_clashes": clashes,
            "market_factors": factors,
        }

    from CORE.dna_engine_v2 import run_dna_engine_v2
    from CORE.dna_v2_market_factors import build_market_factor_counts
    engine_result = _run(run_dna_engine_v2, date)
    market_factors = _run(build_market_factor_counts, date)

    return {
        "dna_profiles": engine_result.get("dna_profiles", {}) if isinstance(engine_result, dict) else {},
        "fixture_clashes": engine_result.get("fixture_clashes", []) if isinstance(engine_result, dict) else [],
        "market_factors": market_factors,
    }


@app.get("/api/dna/v2/latest", tags=["Foundation"])
def get_dna_v2_latest():
    profiles_path = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    clashes_path = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
    factors_path = os.path.join(DATA_DIR, "dna_v2_market_factors.json")

    return {
        "dna_profiles": _read_json(profiles_path, {}),
        "fixture_clashes": _read_json(clashes_path, []),
        "market_factors": _read_json(factors_path, {}),
    }


@app.get("/api/underdog/{date}", tags=["Foundation"])
def get_underdog(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"backtest_underdog_{date}.json"),
        os.path.join(OUTPUT_DIR, "backtest_underdog.json"),
    ]
    from Engine.underdog_engine import run_underdog_engine
    data = _read_disk_first(paths, fallback_fn=run_underdog_engine, target_date=date)
    return _settled(data, "u2s", date)


@app.get("/api/underdog/audit/{date}", tags=["Foundation"])
def get_underdog_audit(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{date}.json"),
        os.path.join(OUTPUT_DIR, "audited_underdog_backtest.json"),
    ]
    from Engine.master_underdog_audit import run_underdog_master_engine
    data = _read_disk_first(paths, fallback_fn=run_underdog_master_engine, target_date=date)
    return _settled(data, "u2s", date)


@app.get("/api/underdog/apex/{date}", tags=["Foundation"])
def get_underdog_apex(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"FINAL_APEX_UD_SCORE_{date}.csv"),
        os.path.join(OUTPUT_DIR, "FINAL_APEX_UD_SCORE.csv"),
    ]
    from AGGREGATOR.apex_ud_aggregator import run_apex_underdog_aggregator
    data = _read_disk_first(paths, fallback_fn=run_apex_underdog_aggregator, target_date=date)
    return _settled(data, "u2s", date)


@app.get("/api/calibration/{date}", tags=["Foundation"])
def get_calibration(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"MASTER_CALIBRATION_{date}.csv"),
        os.path.join(OUTPUT_DIR, "MASTER_CALIBRATION.csv"),
    ]
    from CORE.handshake_logic import run_total_visibility_merger
    return _read_disk_first(paths, fallback_fn=run_total_visibility_merger, target_date=date)


# ════════════════════════════════════════════════════════════════════════════
# WIN ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/win/forecast/{date}", tags=["Win"])
def get_win_forecast(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{date}.csv"),
        os.path.join(OUTPUT_DIR, "ranked_win_forecast.csv"),
    ]
    from Engine.win_forecast import run_win_forecast_engine
    data = _read_disk_first(paths, fallback_fn=run_win_forecast_engine, target_date=date)
    return _settled(data, "win", date)


@app.get("/api/win/psychology/{date}", tags=["Win"])
def get_win_psychology(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"tactical_brain_output_{date}.json"),
        os.path.join(OUTPUT_DIR, "tactical_brain_output.json"),
    ]
    from PSYCHOLOGY.win_psychology import run_win_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_win_psychology_engine, target_date=date)
    return _settled(data, "win", date)


@app.get("/api/win/apex/{date}", tags=["Win"])
def get_win_apex(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"FINAL_APEX_WIN_{date}.csv"),
        os.path.join(OUTPUT_DIR, "FINAL_APEX_WIN.csv"),
        os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{date}.csv"),
    ]
    from AGGREGATOR.win_apex_aggregator import run_win_apex_aggregator
    data = _read_disk_first(paths, fallback_fn=run_win_apex_aggregator)
    return _settled(data, "win", date)


@app.get("/api/win/raw/{date}", tags=["Win"])
def get_win_raw(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"production_raw_engine_{date}.csv"),
        os.path.join(OUTPUT_DIR, f"win_poisson_production_{date}.csv"),
    ]
    from Engine.win_raw_engine import run_win_raw_engine
    data = _read_disk_first(paths, fallback_fn=run_win_raw_engine, target_date=date)
    return _settled(data, "win", date)


@app.get("/api/win/u2s/{date}", tags=["Win"])
def get_u2s(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"u2s_predictions_{date}.json"),
        os.path.join(OUTPUT_DIR, "u2s_predictions.json"),
    ]
    from PSYCHOLOGY.u2s_psychology import run_u2s_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_u2s_psychology_engine, target_date=date)
    return _settled(data, "u2s", date)


# ════════════════════════════════════════════════════════════════════════════
# GG / BTTS ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/gg/precision/{date}", tags=["GG"])
def get_gg_precision(date: str):
    p_json = os.path.join(OUTPUT_DIR, f"gg_o15_feed_{date}.json")
    if os.path.exists(p_json):
        raw = _read_json(p_json, {})
        gg = raw.get("gg", []) if isinstance(raw, dict) else raw
        o15 = raw.get("o15", []) if isinstance(raw, dict) else []
        return {"gg": _settled(gg, "gg", date), "o15": _settled(o15, "o15", date)}

    from Engine.gg_precision_engine import run_gg_o15_engine
    gg, o15 = _run(run_gg_o15_engine, date)
    return {"gg": _settled(gg, "gg", date), "o15": _settled(o15, "o15", date)}


@app.get("/api/gg/forensics/{date}", tags=["GG"])
def get_gg_forensics(date: str):
    paths = [
        os.path.join(MASTER_AGG_DIR, f"FINAL_GG_MASTER_LIVE_{date}.csv"),
        os.path.join(MASTER_AGG_DIR, "FINAL_GG_MASTER_LIVE.csv"),
        os.path.join(OUTPUT_DIR, f"FINAL_GG_MASTER_LIVE_{date}.csv"),
    ]
    from AGGREGATOR.gg_forensics_audit import run_gg_forensic_aggregator
    data = _read_disk_first(paths, fallback_fn=run_gg_forensic_aggregator, target_date=date)
    return _settled(data, "gg", date)


@app.get("/api/gg/psychology/{date}", tags=["GG"])
def get_gg_psychology(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"gg_psychology_output_{date}.json"),
        os.path.join(OUTPUT_DIR, "gg_psychology_output.json"),
    ]
    from PSYCHOLOGY.gg_psychology import run_gg_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_gg_psychology_engine, target_date=date)
    return _settled(data, "gg", date)


@app.get("/api/gg/supreme/{date}", tags=["GG"])
def get_gg_supreme(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"supreme_gg_vip_{date}.json"),
        os.path.join(OUTPUT_DIR, "supreme_gg_vip.json"),
        os.path.join(MASTER_AGG_DIR, "FINAL_GG_MASTER_LIVE.csv"),
    ]
    from AGGREGATOR.gg_supreme_vip import run_supreme_gg_aggregator
    data = _read_disk_first(paths, fallback_fn=run_supreme_gg_aggregator, target_date=date)
    return _settled(data, "gg", date)


@app.get("/api/gg/cross-verify", tags=["GG"])
def get_gg_cross_verify():
    paths = [
        os.path.join(OUTPUT_DIR, "forecast_final_gg_precision.csv"),
    ]
    from FILTER.gg_precision_filter import run_gg_precision_filter
    data = _read_disk_first(paths, fallback_fn=run_gg_precision_filter)
    return _settled(data, "gg")


# ════════════════════════════════════════════════════════════════════════════
# OVER 2.5 ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/over25/stage1/{date}", tags=["Over 2.5"])
def get_over25_stage1(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over25_stage1_picks.json"),
        os.path.join(OUTPUT_DIR, "over25_stage1_picks.csv"),
    ]
    from Engine.over25_probabilistic import run_over25_stage1
    data = _read_disk_first(paths, fallback_fn=run_over25_stage1, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/stage2/{date}", tags=["Over 2.5"])
def get_over25_stage2(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over25_stage2_picks.json"),
        os.path.join(OUTPUT_DIR, "over25_stage2_picks.csv"),
        os.path.join(OUTPUT_DIR, f"master_over_stage2_{date}.csv"),
    ]
    from Engine.over25_council import run_over25_stage2
    data = _read_disk_first(paths, fallback_fn=run_over25_stage2, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/stage3/{date}", tags=["Over 2.5"])
def get_over25_stage3(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over25_stage3_final.json"),
        os.path.join(OUTPUT_DIR, "over25_stage3_final.csv"),
    ]
    from AGGREGATOR.over25_killswitch import run_over25_stage3
    data = _read_disk_first(paths, fallback_fn=run_over25_stage3, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/psychology/{date}", tags=["Over 2.5"])
def get_over25_psychology(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"o25_psychology_{date}.json"),
        os.path.join(OUTPUT_DIR, "o25_psychology.json"),
    ]
    from PSYCHOLOGY.over25_psychology import run_o25_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_o25_psychology_engine, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/gold/{date}", tags=["Over 2.5"])
def get_over25_gold(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "gold_over_25_feed.json"),
    ]
    from Engine.gold_over25 import run_gold_over_25_engine
    data = _read_disk_first(paths, fallback_fn=run_gold_over_25_engine, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/apex/{date}", tags=["Over 2.5"])
def get_over25_apex(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over25_stage3_final.json"),
        os.path.join(OUTPUT_DIR, "over25_stage3_final.csv"),
    ]
    from AGGREGATOR.over25_apex import run_over25_aggregator
    data = _read_disk_first(paths, fallback_fn=run_over25_aggregator, target_date=date)
    return _settled(data, "o25", date)


@app.get("/api/over25/forecast/{date}", tags=["Over 2.5"])
def get_over25_forecast(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"over25_forecast_{date}.csv"),
        os.path.join(OUTPUT_DIR, "over25_stage2_picks.json"),
    ]
    from Engine.over25_forecast import run_over25_forecast_engine
    data = _read_disk_first(paths, fallback_fn=run_over25_forecast_engine, target_date=date)
    return _settled(data, "o25", date)


# ════════════════════════════════════════════════════════════════════════════
# OVER 1.5 ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/over15/stage3/{date}", tags=["Over 1.5"])
def get_over15_stage3(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over15_stage3_final.json"),
        os.path.join(OUTPUT_DIR, "over15_stage3_final.csv"),
    ]
    from Engine.over15_stage3 import run_over15_stage3
    data = _read_disk_first(paths, fallback_fn=run_over15_stage3, target_date=date)
    return _settled(data, "o15", date)


@app.get("/api/over15/psychology/{date}", tags=["Over 1.5"])
def get_over15_psychology(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"o15_psychology_{date}.json"),
        os.path.join(OUTPUT_DIR, "o15_psychology.json"),
    ]
    from PSYCHOLOGY.over15_psychology import run_o15_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_o15_psychology_engine, target_date=date)
    return _settled(data, "o15", date)


@app.get("/api/over15/apex/{date}", tags=["Over 1.5"])
def get_over15_apex(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "over15_stage3_final.json"),
    ]
    from AGGREGATOR.over15_apex import run_o15_apex_engine
    data = _read_disk_first(paths, fallback_fn=run_o15_apex_engine, target_date=date)
    return _settled(data, "o15", date)


# ════════════════════════════════════════════════════════════════════════════
# UNDER ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/unders/{date}", tags=["Unders"])
def get_unders(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"unders_predictions_{date}.json"),
        os.path.join(OUTPUT_DIR, "unders_predictions.json"),
    ]
    if any(os.path.exists(p) for p in paths):
        raw = _read_disk_first(paths)
        if isinstance(raw, dict):
            u25 = raw.get("u25", [])
            u35 = raw.get("u35", [])
            return {"u25": _settled(u25, "o25", date), "u35": u35}

    from Engine.unders_engine import run_unders_engine
    u25, u35 = _run(run_unders_engine, date)
    return {"u25": _settled(u25, "o25", date), "u35": u35}


# ════════════════════════════════════════════════════════════════════════════
# DRAW ENGINE (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/draw/{date}", tags=["Draw"])
def get_draw(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"draw_predictions_{date}.json"),
        os.path.join(OUTPUT_DIR, "draw_predictions.json"),
    ]
    if any(os.path.exists(p) for p in paths):
        raw = _read_disk_first(paths)
        if isinstance(raw, dict):
            draws = raw.get("draws", [])
            return {
                "draws": _settled(draws, "win", date),
                "parity_list": raw.get("parity_list", []),
                "amateurs_list": raw.get("amateurs_list", [])
            }

    from Engine.draw_engine import run_draw_engine
    draws, parity, amateurs = _run(run_draw_engine, date)
    return {"draws": _settled(draws, "win", date), "parity_list": parity, "amateurs_list": amateurs}


# ════════════════════════════════════════════════════════════════════════════
# CORNER ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/corners/stage1/{date}", tags=["Corners"])
def get_corners_stage1(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "corner3_qualified.json"),
        os.path.join(OUTPUT_DIR, f"corner_stage1_{date}.json"),
    ]
    from Engine.corner_miner import run_corner_engine_stage1
    data = _read_disk_first(paths, fallback_fn=run_corner_engine_stage1, target_date=date)
    return _settled(data, "corners", date)


@app.get("/api/corners/stage2/{date}", tags=["Corners"])
def get_corners_stage2(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "corner3_qualified.json"),
        os.path.join(OUTPUT_DIR, f"corner_stage2_{date}.json"),
    ]
    from Engine.corner_refiner import run_corner_engine_stage2
    data = _read_disk_first(paths, fallback_fn=run_corner_engine_stage2, target_date=date)
    return _settled(data, "corners", date)


@app.get("/api/corners/psychology/{date}", tags=["Corners"])
def get_corners_psychology(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "corner3_qualified.json"),
    ]
    from PSYCHOLOGY.corner_psychology import run_corner3_psychology_engine
    data = _read_disk_first(paths, fallback_fn=run_corner3_psychology_engine, target_date=date)
    return _settled(data, "corners", date)


@app.get("/api/corners/catalyst/{date}", tags=["Corners"])
def get_corners_catalyst(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "corner3_qualified.json"),
        os.path.join(OUTPUT_DIR, f"corner_catalyst_{date}.json"),
    ]
    from Engine.corner_catalyst import run_catalyst_corner_engine
    data = _read_disk_first(paths, fallback_fn=run_catalyst_corner_engine, target_date=date)
    return _settled(data, "corners", date)


@app.get("/api/corners/aggregator/{date}", tags=["Corners"])
def get_corners_aggregator(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "corner3_qualified.json"),
    ]
    from AGGREGATOR.corner4_aggregator import run_corner4_aggregator_engine
    data = _read_disk_first(paths, fallback_fn=run_corner4_aggregator_engine, target_date=date)
    return _settled(data, "corners", date)


# ════════════════════════════════════════════════════════════════════════════
# SOT / HALF-TIME / SECOND-HALF ENGINES (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/sot/{date}", tags=["Specials"])
def get_sot(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"sot_cerberus_predictions_{date}.json"),
        os.path.join(OUTPUT_DIR, f"sot_cerberus_predictions_{date}.csv"),
    ]
    from Engine.sot_engine import run_sot_engine
    data = _read_disk_first(paths, fallback_fn=run_sot_engine, target_date=date)
    return _settled(data, "sot", date)


@app.get("/api/fhvi/{date}", tags=["Specials"])
def get_fhvi(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"hvi_strict_filtered_{date}.json"),
        os.path.join(OUTPUT_DIR, f"hvi_strict_filtered_{date}.csv"),
    ]
    from Engine.fhvi_engine import run_fhvi_engine
    data = _read_disk_first(paths, fallback_fn=run_fhvi_engine, target_date=date)
    return _settled(data, "shvi", date)


@app.get("/api/shvi/{date}", tags=["Specials"])
def get_shvi(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"hvi_vortex_report_{date}.json"),
        os.path.join(OUTPUT_DIR, f"hvi_vortex_report_{date}.csv"),
    ]
    from Engine.shvi_engine import run_shvi_engine
    data = _read_disk_first(paths, fallback_fn=run_shvi_engine, target_date=date)
    return _settled(data, "shvi", date)


@app.get("/api/sh-gg-winner/{date}", tags=["Specials"])
def get_sh_gg_winner(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json"),
    ]
    from Engine.sh_gg_winner import run_sh_gg_winner_engine
    data = _read_disk_first(paths, fallback_fn=run_sh_gg_winner_engine, target_date=date)
    return _settled(data, "shvi", date)


@app.get("/api/sh-master/{date}", tags=["Specials"])
def get_sh_master(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"hvi_vortex_report_{date}.json"),
        os.path.join(OUTPUT_DIR, "hvi_vortex_report.json"),
    ]
    from Engine.sh_master_vortex import run_sh_master_vortex
    data = _read_disk_first(paths, fallback_fn=run_sh_master_vortex, target_date=date)
    return _settled(data, "shvi", date)


@app.get("/api/sh-8goal/{date}", tags=["Specials"])
def get_sh_8goal(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"FINAL_SH_GG_8GOAL_{date}.csv"),
        os.path.join(OUTPUT_DIR, "FINAL_SH_GG_8GOAL.csv"),
    ]
    from AGGREGATOR.sh_8goal_aggregator import run_sh_gg_8goal_aggregator
    data = _read_disk_first(paths, fallback_fn=run_sh_gg_8goal_aggregator, target_date=date)
    return _settled(data, "shvi", date)


# ════════════════════════════════════════════════════════════════════════════
# LIVE / DASHBOARD ENGINES (Disk-Safe Reads — Zero Crash on Process Isolation)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/live/prematch", tags=["Live"])
def get_live_prematch():
    """Reads persisted strategic audit from data/prematch_team_audit.json."""
    raw = _read_json(os.path.join(DATA_DIR, "prematch_team_audit.json"), {})
    if isinstance(raw, dict):
        return list(raw.values())
    return raw if isinstance(raw, list) else []


@app.get("/api/live/validation", tags=["Live"])
def get_live_validation():
    """Reads persisted in-play validation state from data/validated_picks.json."""
    alerts = _read_json(os.path.join(DATA_DIR, "validated_picks.json"), {})
    state = _read_json(os.path.join(DATA_DIR, "validation_state.json"), {})
    alert_list = list(alerts.values()) if isinstance(alerts, dict) else alerts
    return {
        "cycle": 1,
        "total_tracked": len(state),
        "alerts": alert_list if isinstance(alert_list, list) else [],
        "matches": []
    }


@app.get("/api/live/incoming", tags=["Live"])
def get_live_incoming():
    """Stage 3 snapshot — thin JSON read."""
    return _incoming_rows_from_disk()


@app.get("/api/live/danger", tags=["Live"])
def get_live_danger():
    """Stage 4 snapshot — thin JSON read."""
    return _read_json(os.path.join(DATA_DIR, "danger_audit.json"), [])


@app.get("/api/live/aggregator", tags=["Live"])
def get_live_aggregator():
    """Stage 5 snapshot — thin JSON read."""
    return _read_json(os.path.join(DATA_DIR, "aggregator_report.json"), [])


@app.get("/api/live/orchestrator", tags=["Live"])
def get_live_orchestrator():
    """Reads Code 6's orchestrator board JSON snapshot."""
    default_board = {"session": "", "cycle": 0, "total_live": 0, "total_db": 0, "matches": []}
    return _read_json(os.path.join(OUTPUT_DIR, "orchestrator_board.json"), default_board)


@app.get("/api/live/alerts", tags=["Live"])
def get_live_alerts():
    """Reads Code 6 ready_to_push alerts from output/ready_to_push.json."""
    path = os.path.join(OUTPUT_DIR, "ready_to_push.json")
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: rows.append(json.loads(line))
                except json.JSONDecodeError: continue
    except Exception:
        return []
    rows.sort(key=lambda r: r.get("time", ""), reverse=True)
    return rows


@app.get("/api/live/dashboard", tags=["Live"])
def get_live_dashboard():
    from LIVE_SCANNER.live_stage7_dashboard import run_supreme_dashboard
    return _run(run_supreme_dashboard)


# ════════════════════════════════════════════════════════════════════════════
# FILTER ENDPOINTS (Disk-First with Settlement)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/filter/gg/weekly", tags=["Filters"])
def filter_gg_weekly(
    mode: str = "public",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
    risk_level: str = "balanced",
    odds_band: str = "1.50-2.00",
    min_prob: float = 60.0,
    min_h2h_gg: int = 2,
    max_parity: int = 5,
    min_dominance: int = 5,
    strict_mode: bool = True,
):
    paths = [
        os.path.join(OUTPUT_DIR, "forecast_final_gg_precision.csv"),
    ]
    from FILTER.gg_precision_filter import run_gg_precision_filter
    data = _read_disk_first(paths, fallback_fn=run_gg_precision_filter)
    return _settled(data, "gg")


@app.get("/api/filter/gg/{date}", tags=["Filters"])
def filter_gg_single(
    date: str,
    mode: str = "public",
    risk_level: str = "balanced",
    odds_band: str = "1.50-2.00",
    min_prob: float = 60.0,
    min_home_gg5: int = 3,
    min_away_gg5: int = 3,
    min_home_gg3: int = 2,
    min_away_gg3: int = 2,
    min_h2h_gg: int = 2,
    max_parity: int = 5,
    min_dominance: int = 5,
    max_home_missing: int = 1,
    max_away_missing: int = 1,
    min_gg_odds: float = 1.40,
    max_gg_odds: float = 2.50,
    strict_mode: bool = True,
):
    paths = [
        os.path.join(OUTPUT_DIR, f"forecast_final_gg_precision_{date}.csv"),
        os.path.join(OUTPUT_DIR, "forecast_final_gg_precision.csv"),
    ]
    from FILTER.gg_precision_filter import run_gg_precision_filter
    data = _read_disk_first(paths, fallback_fn=run_gg_precision_filter)
    return _settled(data, "gg", date)


@app.get("/api/filter/win/weekly", tags=["Filters"])
def filter_win_weekly(
    mode: str = "public",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
    risk_level: str = "balanced",
    odds_band: str = "1.40-1.90",
    min_form_wins: int = 3,
    min_parity_gap: int = 10,
    strict_mode: bool = True,
):
    target = anchor_date or start_date or datetime.now().strftime("%Y-%m-%d")
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_PICKS_{target}.csv"),
        os.path.join(OUTPUT_DIR, f"FILTERED_TIPSTER_PICKS_{target}.csv"),
    ]
    from FILTER.win_filter_service import run_win_filter_service
    kwargs = dict(risk_level=risk_level, odds_band=odds_band, min_form_wins=min_form_wins) if mode == "public" else dict(min_parity_gap=min_parity_gap, strict_mode=strict_mode)
    data = _read_disk_first(paths, fallback_fn=run_win_filter_service, target_date=target, mode=mode, **kwargs)
    return _settled(data, "win")


@app.get("/api/filter/win/{date}", tags=["Filters"])
def filter_win_single(
    date: str,
    mode: str = "public",
    risk_level: str = "balanced",
    odds_band: str = "1.40-1.90",
    min_form_wins: int = 3,
    min_opp_conceded: int = 5,
    min_h2h: int = 2,
    require_no_draw: bool = False,
    min_odds: float = 1.40,
    max_odds: float = 2.00,
    min_overall_wins: int = 0,
    min_venue_wins: int = 0,
    min_h2h_wins: int = 0,
    min_opp_losses: int = 0,
    min_parity_gap: int = 0,
    min_even_count: int = 0,
    strict_mode: bool = True,
    min_parity: int = 10,
):
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_PICKS_{date}.csv"),
        os.path.join(OUTPUT_DIR, f"FILTERED_TIPSTER_PICKS_{date}.csv"),
        os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{date}.csv"),
    ]
    from FILTER.win_filter_service import run_win_filter_service
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_form_wins=min_form_wins, min_opp_conceded=min_opp_conceded,
        min_h2h=min_h2h, require_no_draw=require_no_draw,
    ) if mode == "public" else dict(
        min_odds=min_odds, max_odds=max_odds,
        min_overall_wins=min_overall_wins, min_venue_wins=min_venue_wins,
        min_h2h_wins=min_h2h_wins, min_opp_losses=min_opp_losses,
        min_parity_gap=min_parity_gap, min_even_count=min_even_count,
        strict_mode=strict_mode,
    )
    data = _read_disk_first(paths, fallback_fn=run_win_filter_service, target_date=date, mode=mode, **kwargs)
    return _settled(data, "win", date)


@app.get("/api/filter/over25/weekly", tags=["Filters"])
def filter_over25_weekly(
    mode: str = "public",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
    risk_level: str = "balanced",
    odds_band: str = "1.50-1.85",
    min_poisson: float = 60.0,
    min_votes: int = 5,
):
    target = anchor_date or start_date or datetime.now().strftime("%Y-%m-%d")
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_O25_PUBLIC_{risk_level.upper()}_{target}.csv"),
        os.path.join(OUTPUT_DIR, "over25_stage3_final.json"),
    ]
    from FILTER.over25_risk_filter import run_over25_filter_aggregator
    data = _read_disk_first(paths, fallback_fn=run_over25_filter_aggregator, target_date=target, mode=mode, risk_level=risk_level, odds_band=odds_band)
    return _settled(data, "o25")


@app.get("/api/filter/over25/{date}", tags=["Filters"])
def filter_over25_single(
    date: str,
    mode: str = "public",
    risk_level: str = "balanced",
    odds_band: str = "1.50-1.85",
    min_poisson: float = 60.0,
    min_votes: int = 6,
    max_pos_gap: int = 10,
    min_h2h_overs: int = 3,
    min_odds: float = 1.40,
    max_odds: float = 2.20,
):
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_O25_PUBLIC_{risk_level.upper()}_{date}.csv"),
        os.path.join(OUTPUT_DIR, "over25_stage3_final.json"),
    ]
    from FILTER.over25_risk_filter import run_over25_filter_aggregator
    data = _read_disk_first(paths, fallback_fn=run_over25_filter_aggregator, target_date=date, mode=mode, risk_level=risk_level, odds_band=odds_band)
    return _settled(data, "o25", date)


@app.get("/api/filter/win/precision/weekly", tags=["Filters"])
def filter_win_precision_weekly(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    target = anchor_date or start_date or datetime.now().strftime("%Y-%m-%d")
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_SAFE_{target}.csv"),
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_PICKS_{target}.csv"),
    ]
    from FILTER.win_filter_service import run_win_filter_service
    data = _read_disk_first(paths, fallback_fn=run_win_filter_service, target_date=target, mode="public", risk_level="safe")
    return _settled(data, "win")


@app.get("/api/filter/win/precision/{date}", tags=["Filters"])
def filter_win_precision_single(date: str):
    paths = [
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_SAFE_{date}.csv"),
        os.path.join(OUTPUT_DIR, f"FILTERED_PUBLIC_PICKS_{date}.csv"),
        os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{date}.csv"),
    ]
    from FILTER.win_filter_service import run_win_filter_service
    data = _read_disk_first(paths, fallback_fn=run_win_filter_service, target_date=date, mode="public", risk_level="safe")
    return _settled(data, "win", date)


# ════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE ENDPOINT (All Phases Supported)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/pipeline/{date}", tags=["Pipeline"])
def run_full_pipeline(date: str, phases: Optional[str] = "all"):
    """
    Run multiple engines for a date in one call.
    Default: all phases.
    """
    requested = set(phases.split(",")) if phases != "all" else {
        "foundation", "win", "gg", "over25", "over15",
        "corners", "specials", "filters"
    }
    results: dict = {}
    errors:  dict = {}

    def safe(key, fn, *args, **kwargs):
        try:
            results[key] = fn(*args, **kwargs)
        except Exception as exc:
            errors[key] = str(exc)

    if "foundation" in requested:
        from Engine.underdog_engine import run_underdog_engine
        from Engine.master_underdog_audit import run_underdog_master_engine
        from CORE.handshake_logic import run_total_visibility_merger
        from Engine.win_forecast import run_win_forecast_engine
        safe("underdog",        run_underdog_engine,          date)
        safe("underdog_audit",  run_underdog_master_engine,   date)
        safe("calibration",     run_total_visibility_merger,  date)
        safe("win_forecast",    run_win_forecast_engine,      date)

    if "gg" in requested:
        from Engine.gg_precision_engine import run_gg_o15_engine
        from AGGREGATOR.gg_forensics_audit import run_gg_forensic_aggregator
        try:
            gg, o15 = run_gg_o15_engine(date)
            results["gg_precision"] = gg
            results["o15_precision"] = o15
        except Exception as exc:
            errors["gg_precision"] = str(exc)
        safe("gg_forensics", run_gg_forensic_aggregator, date)

    if "over25" in requested:
        from Engine.over25_probabilistic import run_over25_stage1
        from Engine.over25_council      import run_over25_stage2
        from AGGREGATOR.over25_killswitch import run_over25_stage3
        safe("over25_s1", run_over25_stage1, date)
        safe("over25_s2", run_over25_stage2, date)
        safe("over25_s3", run_over25_stage3, date)

    if "over15" in requested:
        from Engine.over15_stage3 import run_over15_stage3
        safe("over15_s3", run_over15_stage3, date)

    if "win" in requested:
        from PSYCHOLOGY.win_psychology      import run_win_psychology_engine
        from AGGREGATOR.win_apex_aggregator import run_win_apex_aggregator
        safe("win_psychology", run_win_psychology_engine,  date)
        safe("win_apex",       run_win_apex_aggregator,    date)

    if "corners" in requested:
        from Engine.corner_miner   import run_corner_engine_stage1
        from Engine.corner_refiner import run_corner_engine_stage2
        safe("corners_s1", run_corner_engine_stage1, date)
        safe("corners_s2", run_corner_engine_stage2, date)

    if "specials" in requested:
        from Engine.sot_engine  import run_sot_engine
        from Engine.draw_engine import run_draw_engine
        safe("sot", run_sot_engine, date)
        try:
            draws, parity, amateurs = run_draw_engine(date)
            results["draw"] = {
                "draws": draws,
                "parity_list": parity,
                "amateurs_list": amateurs,
            }
        except Exception as exc:
            errors["draw"] = str(exc)

    if "filters" in requested:
        from FILTER.gg_precision_filter import run_gg_precision_filter
        from FILTER.over25_risk_filter import run_over25_filter_aggregator
        from FILTER.win_filter_service import run_win_filter_service
        safe("filter_gg",     run_gg_precision_filter)
        safe("filter_win",    run_win_filter_service,        date, "public")
        safe("filter_over25", run_over25_filter_aggregator,  date, "public")

    return {
        "date":        date,
        "phases_run":  list(requested),
        "results":     results,
        "errors":      errors,
    }
