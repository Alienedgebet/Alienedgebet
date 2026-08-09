from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import traceback
import sys
import os

# ── PATH BOOTSTRAP ────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ── APP INIT ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlienEdge Prediction API",
    version="2.0.0",
    description="Forensic football prediction engine — REST interface",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SHARED HELPER ─────────────────────────────────────────────────────────────
def _run(fn, *args, **kwargs):
    """Run a synchronous engine function and catch any exceptions."""
    try:
        result = fn(*args, **kwargs)
        return result if result is not None else []
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


def _read_json(path: str, default=None):
    """Fast disk read for live REST snapshots — never imports heavy engines."""
    import json
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _incoming_rows_from_disk():
    """Normalize incoming_predictions.json → [{fixture_id, fixture, picks}]."""
    path = os.path.join(ROOT, "data", "incoming_predictions.json")
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
# FOUNDATION ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/dna/{date}", tags=["Foundation"])
def get_dna_profiles(date: str):
    from CORE.dna_profiler import run_dna_profiler
    return _run(run_dna_profiler, date)


# ════════════════════════════════════════════════════════════════════════════
# DNA ENGINE V2 (additive — parallel to /api/dna, never replaces it)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/dna/v2/{date}", tags=["Foundation"])
def get_dna_v2(date: str):
    """
    Runs DNA Engine V2 + the market-factor mapper live and returns the
    combined payload. Mirrors the existing /api/dna/{date} pattern.
    """
    from CORE.dna_engine_v2 import run_dna_engine_v2
    from CORE.dna_v2_market_factors import build_market_factor_counts

    engine_result = _run(run_dna_engine_v2, date)
    market_factors = _run(build_market_factor_counts, date)

    dna_profiles = engine_result.get("dna_profiles", {}) if isinstance(engine_result, dict) else {}
    fixture_clashes = engine_result.get("fixture_clashes", []) if isinstance(engine_result, dict) else []

    return {
        "dna_profiles": dna_profiles,
        "fixture_clashes": fixture_clashes,
        "market_factors": market_factors,
    }


@app.get("/api/dna/v2/latest", tags=["Foundation"])
def get_dna_v2_latest():
    """
    Fast disk-only read of the most recently computed DNA v2 output —
    never imports or runs the engine. Used by the frontend for instant
    fixture-list DNA counts and instant DNA Analysis page opens.
    """
    profiles_path = os.path.join(ROOT, "data", "team_dna_v2_profiles.json")
    clashes_path = os.path.join(ROOT, "data", "fixture_style_clashes_v2.json")
    factors_path = os.path.join(ROOT, "data", "dna_v2_market_factors.json")

    return {
        "dna_profiles": _read_json(profiles_path, {}),
        "fixture_clashes": _read_json(clashes_path, []),
        "market_factors": _read_json(factors_path, {}),
    }


@app.get("/api/underdog/{date}", tags=["Foundation"])
def get_underdog(date: str):
    from Engine.underdog_engine import run_underdog_engine
    return _run(run_underdog_engine, date)

@app.get("/api/underdog/audit/{date}", tags=["Foundation"])
def get_underdog_audit(date: str):
    from Engine.master_underdog_audit import run_underdog_master_engine
    return _run(run_underdog_master_engine, date)

@app.get("/api/underdog/apex/{date}", tags=["Foundation"])
def get_underdog_apex(date: str):
    from AGGREGATOR.apex_ud_aggregator import run_apex_underdog_aggregator
    return _run(run_apex_underdog_aggregator, date)

@app.get("/api/calibration/{date}", tags=["Foundation"])
def get_calibration(date: str):
    from CORE.handshake_logic import run_total_visibility_merger
    return _run(run_total_visibility_merger, date)


# ════════════════════════════════════════════════════════════════════════════
# WIN ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/win/forecast/{date}", tags=["Foundation"])
def get_win_forecast(date: str):
    from Engine.win_forecast import run_win_forecast_engine
    return _run(run_win_forecast_engine, date)

@app.get("/api/win/psychology/{date}", tags=["Win"])
def get_win_psychology(date: str):
    from PSYCHOLOGY.win_psychology import run_win_psychology_engine
    return _run(run_win_psychology_engine, date)

@app.get("/api/win/apex/{date}", tags=["Win"])
def get_win_apex(date: str):
    from AGGREGATOR.win_apex_aggregator import run_win_apex_aggregator
    return _run(run_win_apex_aggregator, date)

@app.get("/api/win/raw/{date}", tags=["Win"])
def get_win_raw(date: str):
    from Engine.win_raw_engine import run_win_raw_engine
    return _run(run_win_raw_engine, date)

@app.get("/api/win/u2s/{date}", tags=["Win"])
def get_u2s(date: str):
    from PSYCHOLOGY.u2s_psychology import run_u2s_psychology_engine
    return _run(run_u2s_psychology_engine, date)


# ════════════════════════════════════════════════════════════════════════════
# GG / BTTS ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/gg/precision/{date}", tags=["GG"])
def get_gg_precision(date: str):
    from Engine.gg_precision_engine import run_gg_o15_engine
    gg, o15 = _run(run_gg_o15_engine, date)
    return {"gg": gg, "o15": o15}

@app.get("/api/gg/forensics/{date}", tags=["GG"])
def get_gg_forensics(date: str):
    from AGGREGATOR.gg_forensics_audit import run_gg_forensic_aggregator
    return _run(run_gg_forensic_aggregator, date)

@app.get("/api/gg/psychology/{date}", tags=["GG"])
def get_gg_psychology(date: str):
    from PSYCHOLOGY.gg_psychology import run_gg_psychology_engine
    return _run(run_gg_psychology_engine, date)

@app.get("/api/gg/supreme/{date}", tags=["GG"])
def get_gg_supreme(date: str):
    from AGGREGATOR.gg_supreme_vip import run_supreme_gg_aggregator
    return _run(run_supreme_gg_aggregator, date)

@app.get("/api/gg/cross-verify", tags=["GG"])
def get_gg_cross_verify():
    """GG precision filter — 7-day cross-verification (original command)."""
    from FILTER.gg_precision_filter import run_gg_precision_filter
    return _run(run_gg_precision_filter)


# ════════════════════════════════════════════════════════════════════════════
# OVER 2.5 ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/over25/stage1/{date}", tags=["Over 2.5"])
def get_over25_stage1(date: str):
    from Engine.over25_probabilistic import run_over25_stage1
    return _run(run_over25_stage1, date)

@app.get("/api/over25/stage2/{date}", tags=["Over 2.5"])
def get_over25_stage2(date: str):
    from Engine.over25_council import run_over25_stage2
    return _run(run_over25_stage2, date)

@app.get("/api/over25/stage3/{date}", tags=["Over 2.5"])
def get_over25_stage3(date: str):
    from AGGREGATOR.over25_killswitch import run_over25_stage3
    return _run(run_over25_stage3, date)

@app.get("/api/over25/psychology/{date}", tags=["Over 2.5"])
def get_over25_psychology(date: str):
    from PSYCHOLOGY.over25_psychology import run_o25_psychology_engine
    return _run(run_o25_psychology_engine, date)

@app.get("/api/over25/gold/{date}", tags=["Over 2.5"])
def get_over25_gold(date: str):
    from Engine.gold_over25 import run_gold_over_25_engine
    return _run(run_gold_over_25_engine, date)

@app.get("/api/over25/apex/{date}", tags=["Over 2.5"])
def get_over25_apex(date: str):
    from AGGREGATOR.over25_apex import run_over25_aggregator
    return _run(run_over25_aggregator, date)

@app.get("/api/over25/forecast/{date}", tags=["Over 2.5"])
def get_over25_forecast(date: str):
    from Engine.over25_forecast import run_over25_forecast_engine
    return _run(run_over25_forecast_engine, date)


# ════════════════════════════════════════════════════════════════════════════
# OVER 1.5 ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/over15/stage3/{date}", tags=["Over 1.5"])
def get_over15_stage3(date: str):
    from Engine.over15_stage3 import run_over15_stage3
    return _run(run_over15_stage3, date)

@app.get("/api/over15/psychology/{date}", tags=["Over 1.5"])
def get_over15_psychology(date: str):
    from PSYCHOLOGY.over15_psychology import run_o15_psychology_engine
    return _run(run_o15_psychology_engine, date)

@app.get("/api/over15/apex/{date}", tags=["Over 1.5"])
def get_over15_apex(date: str):
    from AGGREGATOR.over15_apex import run_o15_apex_engine
    return _run(run_o15_apex_engine, date)


# ════════════════════════════════════════════════════════════════════════════
# UNDER ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/unders/{date}", tags=["Unders"])
def get_unders(date: str):
    from Engine.unders_engine import run_unders_engine
    u25, u35 = _run(run_unders_engine, date)
    return {"u25": u25, "u35": u35}


# ════════════════════════════════════════════════════════════════════════════
# DRAW ENGINE
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/draw/{date}", tags=["Draw"])
def get_draw(date: str):
    from Engine.draw_engine import run_draw_engine
    draws, parity, amateurs = _run(run_draw_engine, date)
    return {"draws": draws, "parity_list": parity, "amateurs_list": amateurs}


# ════════════════════════════════════════════════════════════════════════════
# CORNER ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/corners/stage1/{date}", tags=["Corners"])
def get_corners_stage1(date: str):
    from Engine.corner_miner import run_corner_engine_stage1
    return _run(run_corner_engine_stage1, date)

@app.get("/api/corners/stage2/{date}", tags=["Corners"])
def get_corners_stage2(date: str):
    from Engine.corner_refiner import run_corner_engine_stage2
    return _run(run_corner_engine_stage2, date)

@app.get("/api/corners/psychology/{date}", tags=["Corners"])
def get_corners_psychology(date: str):
    from PSYCHOLOGY.corner_psychology import run_corner3_psychology_engine
    return _run(run_corner3_psychology_engine, date)

@app.get("/api/corners/catalyst/{date}", tags=["Corners"])
def get_corners_catalyst(date: str):
    from Engine.corner_catalyst import run_catalyst_corner_engine
    return _run(run_catalyst_corner_engine, date)

@app.get("/api/corners/aggregator/{date}", tags=["Corners"])
def get_corners_aggregator(date: str):
    from AGGREGATOR.corner4_aggregator import run_corner4_aggregator_engine
    return _run(run_corner4_aggregator_engine, date)


# ════════════════════════════════════════════════════════════════════════════
# SOT / HALF-TIME / SECOND-HALF ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/sot/{date}", tags=["Specials"])
def get_sot(date: str):
    from Engine.sot_engine import run_sot_engine
    return _run(run_sot_engine, date)

@app.get("/api/fhvi/{date}", tags=["Specials"])
def get_fhvi(date: str):
    from Engine.fhvi_engine import run_fhvi_engine
    return _run(run_fhvi_engine, date)

@app.get("/api/shvi/{date}", tags=["Specials"])
def get_shvi(date: str):
    from Engine.shvi_engine import run_shvi_engine
    return _run(run_shvi_engine, date)

@app.get("/api/sh-gg-winner/{date}", tags=["Specials"])
def get_sh_gg_winner(date: str):
    from Engine.sh_gg_winner import run_sh_gg_winner_engine
    return _run(run_sh_gg_winner_engine, date)

@app.get("/api/sh-master/{date}", tags=["Specials"])
def get_sh_master(date: str):
    from Engine.sh_master_vortex import run_sh_master_vortex
    return _run(run_sh_master_vortex, date)

@app.get("/api/sh-8goal/{date}", tags=["Specials"])
def get_sh_8goal(date: str):
    from AGGREGATOR.sh_8goal_aggregator import run_sh_gg_8goal_aggregator
    return _run(run_sh_gg_8goal_aggregator, date)


# ════════════════════════════════════════════════════════════════════════════
# LIVE / DASHBOARD ENGINES
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/live/prematch", tags=["Live"])
def get_live_prematch():
    """Stage 1 rich strategic audit board (persisted print columns)."""
    from LIVE_SCANNER.live_stage1_prematch import get_prematch_audit_snapshot, run_prematch_engine
    snap = get_prematch_audit_snapshot()
    if snap:
        return snap
    return _run(run_prematch_engine)

@app.get("/api/live/validation", tags=["Live"])
def get_live_validation():
    """
    Stage 2 VALIDATION BOARD — tracks stage 1 live_predictions picks in-play
    (monitoring → 30' handshake → 45' supreme alert → settled) plus fired alerts.
    """
    from LIVE_SCANNER.live_stage2_verification import get_validation_board_snapshot
    return _run(get_validation_board_snapshot)

@app.get("/api/live/incoming", tags=["Live"])
def get_live_incoming():
    """Stage 3 snapshot — thin JSON read (engine runs via CLI)."""
    return _incoming_rows_from_disk()

@app.get("/api/live/danger", tags=["Live"])
def get_live_danger():
    """Stage 4 snapshot — thin JSON read (engine runs via CLI)."""
    raw = _read_json(os.path.join(ROOT, "data", "danger_audit.json"), [])
    return raw if isinstance(raw, list) else []

@app.get("/api/live/aggregator", tags=["Live"])
def get_live_aggregator():
    """Stage 5 snapshot — thin JSON read (engine runs via CLI)."""
    raw = _read_json(os.path.join(ROOT, "data", "aggregator_report.json"), [])
    if isinstance(raw, dict) and "error" in raw:
        return []
    return raw if isinstance(raw, list) else []

@app.get("/api/live/orchestrator", tags=["Live"])
def get_live_orchestrator():
    """Stage 6 — last VIP + LIVE orchestrator board cycle."""
    from LIVE_SCANNER.live_stage6_alerts import get_orchestrator_board_snapshot
    return _run(get_orchestrator_board_snapshot)

@app.get("/api/live/alerts", tags=["Live"])
def get_live_alerts():
    """Stage 6 — VIP + free LIVE orchestrator alerts (ready_to_push / session logs)."""
    from LIVE_SCANNER.live_stage6_alerts import get_alerts_snapshot
    return _run(get_alerts_snapshot)

@app.get("/api/live/dashboard", tags=["Live"])
def get_live_dashboard():
    from LIVE_SCANNER.live_stage7_dashboard import run_supreme_dashboard
    return _run(run_supreme_dashboard)


# ════════════════════════════════════════════════════════════════════════════
# ★  NEW FILTER ENDPOINTS — upgraded 3-engine system
# ════════════════════════════════════════════════════════════════════════════

# ── GG FILTER (Engine/gg_engine_weekly.py) ───────────────────────────────────
# NOTE: /weekly must be registered BEFORE /{date} so FastAPI doesn't swallow
#       the literal string "weekly" as a date path parameter.

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
    """
    GG weekly filter — scans full date range then applies filter.
    mode: public | tipster | odds_band | advanced
    """
    from Engine.gg_engine_weekly import run_gg_weekly_filter
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_prob=min_prob, min_h2h_gg=min_h2h_gg,
        max_parity=max_parity, min_dominance=min_dominance,
        strict_mode=strict_mode,
    )
    return _run(
        run_gg_weekly_filter,
        start_date, end_date, anchor_date, mode,
        **kwargs
    )


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
    """
    GG single-date filter.
    mode: public | tipster | odds_band | advanced
    """
    from Engine.gg_engine_weekly import run_gg_filter_service
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_prob=min_prob, min_home_gg5=min_home_gg5,
        min_away_gg5=min_away_gg5, min_home_gg3=min_home_gg3,
        min_away_gg3=min_away_gg3, min_h2h_gg=min_h2h_gg,
        max_parity=max_parity, min_dominance=min_dominance,
        max_home_missing=max_home_missing,
        max_away_missing=max_away_missing,
        min_gg_odds=min_gg_odds, max_gg_odds=max_gg_odds,
        strict_mode=strict_mode,
    )
    return _run(run_gg_filter_service, date, mode, **kwargs)


# ── WIN FILTER (Engine/win_engine_weekly.py) ─────────────────────────────────
# NOTE: /weekly registered before /{date} — prevents path-param shadowing.

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
    """
    Win weekly filter — scans full date range then applies filter.
    mode: public | tipster | odds_band
    """
    from Engine.win_engine_weekly import run_win_weekly_filter
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_form_wins=min_form_wins, min_parity_gap=min_parity_gap,
        strict_mode=strict_mode,
    )
    return _run(
        run_win_weekly_filter,
        start_date, end_date, anchor_date, mode,
        **kwargs
    )


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
    """
    Win single-date filter.
    mode: public | tipster | odds_band
    """
    from Engine.win_engine_weekly import run_win_filter_service
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_form_wins=min_form_wins, min_opp_conceded=min_opp_conceded,
        min_h2h=min_h2h, require_no_draw=require_no_draw,
        min_odds=min_odds, max_odds=max_odds,
        min_overall_wins=min_overall_wins, min_venue_wins=min_venue_wins,
        min_h2h_wins=min_h2h_wins, min_opp_losses=min_opp_losses,
        min_parity_gap=min_parity_gap, min_even_count=min_even_count,
        strict_mode=strict_mode, min_parity=min_parity,
    )
    return _run(run_win_filter_service, date, mode, **kwargs)


# ── OVER 2.5 FILTER (Engine/over25_engine_weekly.py) ─────────────────────────
# NOTE: /weekly registered before /{date} — prevents path-param shadowing.

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
    """
    Over 2.5 weekly filter — scans full date range then applies filter.
    mode: public | tipster | odds_band
    """
    from Engine.over25_engine_weekly import run_over25_weekly_filter
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_poisson=min_poisson, min_votes=min_votes,
    )
    return _run(
        run_over25_weekly_filter,
        start_date, end_date, anchor_date, mode,
        **kwargs
    )


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
    """
    Over 2.5 single-date filter.
    mode: public | tipster | odds_band
    """
    from Engine.over25_engine_weekly import run_over25_filter_service
    kwargs = dict(
        risk_level=risk_level, odds_band=odds_band,
        min_poisson=min_poisson, min_votes=min_votes,
        max_pos_gap=max_pos_gap, min_h2h_overs=min_h2h_overs,
        min_odds=min_odds, max_odds=max_odds,
    )
    return _run(run_over25_filter_service, date, mode, **kwargs)


# ── WIN PRECISION COMMAND (FILTER/win_precision_filter.py) ───────────────────
# NOTE: /weekly registered before /{date} — prevents path-param shadowing.

@app.get("/api/filter/win/precision/weekly", tags=["Filters"])
def filter_win_precision_weekly(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    """
    Win precision command — 7-day cross-verification.
    Mirrors what gg_precision_filter does for GG picks.
    """
    from FILTER.win_precision_filter import run_win_weekly_precision
    return _run(run_win_weekly_precision, start_date, end_date, anchor_date)


@app.get("/api/filter/win/precision/{date}", tags=["Filters"])
def filter_win_precision_single(date: str):
    """
    Win precision command — single date.
    Applies the locked WIN_PRECISION_FILTER rules.
    """
    from FILTER.win_precision_filter import run_win_precision_filter
    return _run(run_win_precision_filter, date)


# ════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE ENDPOINT
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/pipeline/{date}", tags=["Pipeline"])
def run_full_pipeline(date: str, phases: Optional[str] = "all"):
    """
    Run multiple engines for a date in one call.
    ?phases=foundation,win,gg,over25,over15,corners,specials,filters
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
        from Engine.gg_engine_weekly     import run_gg_filter_service
        from Engine.win_engine_weekly    import run_win_filter_service
        from Engine.over25_engine_weekly import run_over25_filter_service
        safe("filter_gg",     run_gg_filter_service,     date, "public")
        safe("filter_win",    run_win_filter_service,    date, "public")
        safe("filter_over25", run_over25_filter_service, date, "public")

    return {
        "date":        date,
        "phases_run":  list(requested),
        "results":     results,
        "errors":      errors,
    }