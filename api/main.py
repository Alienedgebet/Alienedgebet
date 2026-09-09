"""
AlienEdge Prediction API — v4.0 (pure disk-first architecture)

HOW DATA GETS HERE
--------------------
This API never runs an engine. Every route below reads a file that main.py
already wrote via output_store.save() — same module, same key, imported by
both sides, so there is no filename to guess and nothing to drift out of
sync. If main.py hasn't run for a date yet, the route returns an honest
empty list/dict (never a wrong date's stale data, never a crash) and the
frontend's own mock-fallback (`useApi` in lib/use-api.ts) paints demo rows
with a visible "Demo" badge until the pipeline catches up.

Two file-sourcing patterns exist side by side, deliberately:
  1. Pre-match picks (Win/GG/Over.../Corners/etc.) — written by main.py on a
     cron schedule. Read via output_store.load(key, date).
  2. Live in-play data (/api/live/*) — written continuously by the SEPARATE
     always-on run_live_scanner_24_7.py process. Read directly from the
     data/*.json files it maintains. This was already correct before and is
     unchanged here.

Starting main.py itself is done OUT OF PROCESS (cron / systemd timer, see
the deployment guide) — NOT from inside a request handler. The one
admin-triggered `/api/admin/run-pipeline/{date}` route below only launches
main.py as a detached background subprocess and returns immediately; it
never blocks a web worker for the minutes a full run takes.
"""

import os
import sys
import json
import subprocess
import traceback
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── PATH BOOTSTRAP ────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "data")
OUTPUT_DIR = os.path.join(ROOT, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

import output_store as store  # noqa: E402  (same module main.py writes through)

# ── APP INIT ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlienEdge Prediction API",
    version="4.0.0",
    description="Forensic football prediction engine — disk-first REST interface",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
ALLOW_ORIGINS = [o.strip() for o in _env_origins.split(",") if o.strip()]
if not ALLOW_ORIGINS:
    ALLOW_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    print(f"[UNHANDLED] {request.url}: {traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# ── ROUTERS ───────────────────────────────────────────────────────────────────
from api.user_rules_router import router as user_rules_router  # noqa: E402
app.include_router(user_rules_router)

# ── SETTLEMENT / LIVE SCORES (independent of the pre-match pipeline) ──────────
from settlement_service import settle_predictions  # noqa: E402
from live_cache import get_live_scores_cached  # noqa: E402

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def require_admin(token: Optional[str]):
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing admin token")


def to_records(x) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return x
    return []


def ensure_defaults(rows, defaults: dict) -> list:
    """
    Guarantees every row has every key `defaults` names, using the default
    only when the SAVED row is missing that key entirely — this is what
    stopped `r.fatigue_home.toFixed()` etc. from ever crashing the frontend
    again, regardless of which historical engine version wrote the file.

    Also stamps `_incomplete` (bool) + `_missing_fields` (list) onto each
    row that needed any defaulting. This does NOT change any field the
    frontend's TypeScript interfaces already expect — it's an additive,
    ignorable-by-default marker — but it means a defaulted/failed row is no
    longer visually indistinguishable from a genuine "0%" prediction to
    anything that chooses to check it (ops tooling, or a future frontend
    badge), instead of defaults silently passing as real data.
    """
    records = to_records(rows)
    if isinstance(records, dict):
        return records
    out = []
    for r in records:
        if not isinstance(r, dict):
            out.append(r)
            continue
        missing = [k for k in defaults.keys() if k not in r]
        merged = dict(defaults)
        merged.update(r)
        for tier_key in ("tier", "Tier", "Category", "Rank", "gg_tier", "o15_tier",
                          "u25_tier", "u35_tier", "corner_tier", "Verdict"):
            if tier_key in merged and not merged[tier_key]:
                merged[tier_key] = "STANDARD"
                if tier_key not in missing:
                    missing.append(tier_key)
        if "chemistry" in defaults and not merged.get("chemistry"):
            merged["chemistry"] = "strong"
        if missing:
            merged["_incomplete"] = True
            merged["_missing_fields"] = missing
        out.append(merged)
    return out


def _settled(data, market_type: str = "win", date_str: Optional[str] = None):
    if not isinstance(data, list) or len(data) == 0:
        return data
    try:
        live_db = get_live_scores_cached()
        return settle_predictions(data, live_db, market_type=market_type)
    except Exception:
        print(f"[SETTLEMENT WARNING] {market_type}: {traceback.format_exc()}")
        return data


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _date_range(start: str, end: str, max_days: int = 14) -> list:
    """Inclusive list of YYYY-MM-DD strings from start to end, capped so a
    malformed/huge range can't make a single request scan years of files."""
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return [start]
    if d1 < d0:
        d0, d1 = d1, d0
    days = []
    cursor = d0
    while cursor <= d1 and len(days) < max_days:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return days or [start]


def read_range(key_prefix_fn, dates: list, defaults: dict, market_type: str, settle: bool = True) -> list:
    """
    Reads and concatenates one saved file PER DATE in `dates`, tagging each
    row with the date it came from so a "7-day range" filter route actually
    returns a week of picks instead of silently collapsing to a single day
    (the previous behaviour, inherited unchanged from the old backend).
    `key_prefix_fn(date)` returns the output_store key to load for that date.
    """
    combined = []
    for d in dates:
        data, _ = store.load(key_prefix_fn(d), d, default=[])
        rows = ensure_defaults(data, defaults)
        if settle:
            rows = _settled(rows, market_type, d)
        for row in rows:
            if isinstance(row, dict) and "match_date" not in row:
                row["match_date"] = d
        combined.extend(rows)
    return combined


def read(key: str, date: Optional[str], defaults: dict, market_type: str = "win", settle: bool = True):
    """The one helper every picks route uses: load from disk, fill defaults,
    optionally settle against live/finished scores. No engine is ever called
    here — a cache miss is just an empty list, not a live recompute."""
    data, _generated_at = store.load(key, date, default=[])
    rows = ensure_defaults(data, defaults)
    if settle and date:
        rows = _settled(rows, market_type, date)
    return rows


# ════════════════════════════════════════════════════════════════════════════
# DEFAULT FIELD MAPS — matches lib/api.ts's TypeScript interfaces exactly.
# ════════════════════════════════════════════════════════════════════════════
WIN_APEX_DEFAULTS = dict(
    fixture_id="", Fixture="", Target="", Category="STANDARD", Cat_Priority=0,
    Monte_Win_Prob=0, Monte_Draw_Prob=0, Lambda_Detail="", Underdog_Risk="",
    Psych_Score=0, Psych_Logic="", Chokehold_Status="", Veto_Reason="",
)
WIN_PSYCH_DEFAULTS = dict(
    Fixture="", Master_Pick="", Master_Prob="0%", Audit_Score=0, H_Base=0,
    A_Base=0, Tier="STANDARD", Spears="", H_Quality="", A_Quality="",
    Home_Logic="", Away_Logic="",
)
WIN_U2S_DEFAULTS = dict(
    Fixture="", Underdog="", Audit_Verdict="", Spear_Matchup="",
    Dog_Venue_SOT=0, Fav_Venue_SOT=0, Dog_H2H_SOT=0, Fav_H2H_SOT=0,
    Dog_Opp_Avg_Conceded=0, Fav_Opp_Avg_Conceded=0, Dog_Scoring_Consistency="",
    Psych_Score=0, Tier="STANDARD", Triggers="",
)
WIN_FORECAST_DEFAULTS = dict(
    fixture_id="", fixture="", side="", team_name="", win_odds=0,
    poisson_win_prob="0%", poisson_draw_prob="0%", last_5_wins_overall=0,
    last_5_wins_at_venue=0, last_5_goals_scored=0, opp_last_5_goals_scored=0,
    opp_last_5_losses=0, opp_last_5_conceded_raw=0, opp_no_clean_sheet_count=0,
    h2h_wins_last_5=0, last_3_no_draw_BOTH=False, parity_score=0,
    parity_even_count=0,
)
WIN_RAW_DEFAULTS = {k: v for k, v in WIN_FORECAST_DEFAULTS.items()
                    if k not in ("poisson_win_prob", "poisson_draw_prob")}

GG_PRECISION_DEFAULTS = dict(
    fixture_id="", fixture="", home_team="", away_team="", league_id="",
    lambda_home=0, lambda_away=0, combined_lambda=0, mc_btts_prob=0,
    venue_btts_combined=0, h2h_btts_rate=0, home_gk_liable=False,
    away_gk_liable=False, home_gk_cpg=0, away_gk_cpg=0, home_gk_note="",
    away_gk_note="", fatigue_home=0, fatigue_away=0, league_weight=1,
    gg_score=0, gg_signals_fired=0, gg_tier="STANDARD",
    sig1_mc_btts=0, sig2_venue_btts=0, sig3_gk_vuln=0, sig4_h2h_btts=0,
    sig5_directional=0,
)
GG_O15_DEFAULTS = dict(
    fixture_id="", fixture="", home_team="", away_team="", league_id="",
    o15_tier="STANDARD", o15_score=0, combined_lambda=0, mc_over15_prob=0,
    sig1_combined_lambda=0, sig2_mc_over15=0, sig3_venue_goals_avg=0,
    sig4_league_weight=0, sig5_fatigue_penalty=0, combined_venue_goals_avg=0,
    venue_goals_avg_home=0, venue_goals_avg_away=0, fatigue_home=0,
    fatigue_away=0, league_weight=1,
)
GG_FORENSIC_DEFAULTS = dict(
    fixture_id="", league_id="", Fixture="", Score="", DNA_Intelligence="",
    **{"Poisson%": 0}, H2H_GG="", DNA_Insight="", Ranks="", Forensic_Audit="",
)
GG_PSYCH_DEFAULTS = dict(
    Fixture="", MC_Rank="", MC_Prob="0%", Psych_Score=0, Spears="",
    Tier="STANDARD", Psych_Triggers="",
)
GG_SUPREME_DEFAULTS = dict(
    fixture_id="", Fixture="", Category="STANDARD", Cat_Priority=0,
    Monte_GG_Prob=0, NGG_Risk=0, Base_Marks="", DNA_Status="", Psych_Score=0,
    Psych_Triggers="", VIP_Status="", Veto_Status="", Spears="",
)
GG_CROSS_DEFAULTS = dict(
    fixture_id="", home_team="", away_team="", league_id="", gg_prob_pct=0,
    tier="STANDARD", verification_days=0, table_distance=0, audit_timestamp="",
)

O25_STAGE1_DEFAULTS = dict(id="", fixture="", Time="", Odds=0, Confidence="", Algorithm="")
O25_STAGE2_DEFAULTS = dict(id="", fixture="", Time="", Votes=0, Odds=0, Algorithm="", Reasons="")
O25_STAGE3_DEFAULTS = dict(
    Match="", Odds=0, **{"Poisson%": 0}, Grade="", GradeNum=0,
    H2H_Record="", PickedBy="", Failures="",
)
O25_PSYCH_DEFAULTS = dict(Fixture="", Base_Poisson="0%", Base_Grade="", Score=0, Tier="STANDARD", Reasons="")
O25_APEX_DEFAULTS = dict(
    fixture_id="", Fixture="", Category="STANDARD", Cat_Priority=0,
    Super_Monte_Prob=0, U25_Risk=0, Base_Grade="", DNA_Status="",
    Psych_Score=0, Psych_Triggers="", VIP_Status="", Veto_Status="",
)
O25_FORECAST_DEFAULTS = dict(
    fixture_id="", league="", fixture="", o25_odds=0, kill_switch_pass=False,
    poisson_over_prob_num=0, council_votes="", pos_gap=0, parity_diff=0,
    h2h_overs_last_5=0, combined_gs_last_5=0,
)

O15_STAGE3_DEFAULTS = dict(O25_STAGE3_DEFAULTS)
O15_PSYCH_DEFAULTS = dict(O25_PSYCH_DEFAULTS)
O15_APEX_DEFAULTS = dict(Fixture="", Base_Poisson="0%", Base_Grade="", Score=0, Tier="STANDARD", Reasons="")

CORNER_S1_DEFAULTS = dict(
    fixture_id="", fixture="", expected_total_corners=0, corner_tier="STANDARD",
    expected_difference=0, team_more_corners="", team_more_corners_probability_like=0,
    avg_confidence=0, home_win_odds=0, over_2_5_odds=0, tier_1_priority=False,
)
CORNER_S2_DEFAULTS = dict(
    fixture_id="", fixture="", stage1_predicted_corners=0, stage2_predicted_corners=0,
    expected_total_corners=0, corner_tier="STANDARD", style_alignment="",
    expected_difference=0, avg_confidence=0, home_is_persistent_venue=False,
    away_is_persistent_venue=False, home_is_persistent_overall=False,
    away_is_persistent_overall=False,
)
CORNER_PSYCH_DEFAULTS = dict(
    fixture_name="", home_position=0, away_position=0, friction_grade="",
    standings_gap=0, tactical_intelligence_grade="", tactical_note="",
    is_wounded_beast=False, wounded_reason="", wounded_team_name="",
)
CORNER_CATALYST_DEFAULTS = dict(
    fixture_name="", predicted_corners=0, corner_tier="STANDARD",
    home_position=0, away_position=0, friction_grade="",
    home_is_wounded_beast=False, home_wounded_intensity="",
    away_is_wounded_beast=False, away_wounded_intensity="",
)
CORNER_AGG_DEFAULTS = dict(
    Fixture="", Master_Score=0, Chaos_Rating=0, Tier="STANDARD",
    True_Corner_Fav="", Match_Flow="", **{"U2.5%": "0%"}, UD_Prob="0%",
    NB_Prob="0%", Total_Exp=0, Home_Pos=0, Away_Pos=0, Friction="",
    Home_Wounded="False", Home_Wound_Int="", Away_Wounded="False",
    Away_Wound_Int="", Home_Team="", Away_Team="", Home_Score=0, Away_Score=0,
    Home_Label="", Away_Label="", Home_DNA="", Away_DNA="",
    Home_SH_Ratio=0, Away_SH_Ratio=0,
)

DRAW_DEFAULTS = dict(
    fixture_id="", fixture="", home_team="", away_team="", tier="STANDARD",
    section="", composite_draw_score=0, mc_draw_prob=0, poisson_draw_prob=0,
    dmi=0, parity=0, draw_odds=0, value_edge=0, mc_spread=0, mc_stability="",
    most_likely_draw_score="", most_likely_draw_pct=0, home_draws=0,
    away_draws=0, h2h_draws=0, total_draws=0, fatigue_score=0,
    home_position=0, away_position=0,
)
UNDERS_DEFAULTS = dict(
    fixture_id="", fixture="", home_team="", away_team="", combined_lambda=0,
    mc_u25_prob=0, mc_u35_prob=0, u25_score=0, u25_tier="STANDARD",
    u25_signals_fired=0, u35_score=0, u35_tier="STANDARD", home_gk_cpg=0,
    away_gk_cpg=0, home_gk_note="", away_gk_note="", fatigue_home=0,
    fatigue_away=0,
)
SOT_DEFAULTS = dict(
    Fixture="", Verdict="STANDARD", Proj_SOT=0, **{"Poisson_Over_8.5": "0%"},
    Consistency="", Game_Script="", Momentum="", **{"1x2_Home_Odd": 0},
)
FHVI_DEFAULTS = dict(
    fixture="", ht_score="", ft_score="", fhvi_score=0, fhvi_label="",
    fh_pressure=0, country="", comb_fh_r=0, avg_sh_goals=0, h_fh_r_disp=0,
    a_fh_r_disp=0, h_fh_c_r_disp=0, a_fh_c_r_disp=0, Category="STANDARD",
)
SHVI_DEFAULTS = dict(
    fixture="", ht_score="", ft_score="", shvi_score=0, shvi_label="",
    sh_pressure=0, country="", comb_sh_r=0, avg_fh_goals=0, h_sh_r_disp=0,
    a_sh_r_disp=0, h_sh_c_r_disp=0, a_sh_c_r_disp=0, Category="STANDARD",
)

UD_BASE_DEFAULTS = dict(
    fixture_id="", fixture="", league="", underdog_team="", dog_odds=0,
    dog_score_prob="0%", parity_gap=0, dog_att_strength=0, fav_def_weakness=0,
    dog_is_hot=False, dog_due_goal=False, both_no_draw_3=False,
    fav_vulnerability_5="", fav_cs_streak=0, h2h_dog_gs_last_5=0,
    dog_venue_wins=0,
)
UD_AUDIT_DEFAULTS = dict(
    fixture_id="", fixture="", underdog_team="", Audit_Real_Prob="0%",
    Dog_Score_Prob="0%", Fav_Spear_Power="", Dominance_Gap=0,
    Audit_Verdict="STANDARD", parity_gap=0, dog_is_hot=False,
    dog_due_goal=False, fav_cs_streak=0,
)
UD_APEX_DEFAULTS = dict(
    fixture_id="", Fixture="", Rank="STANDARD", Monte_UD_Prob="0%",
    Engine="", Handshake="", DNA="", Rule="", Fav_Vuln="0%", SH_GG_Label="",
)

SH_GG_WINNER_DEFAULTS = dict(
    fixture_id="", league="", kickoff_datetime="",
    teams={"home": {"id": "", "name": ""}, "away": {"id": "", "name": ""}},
    pick_labels=[], flags={}, metrics={},
)
SH_MASTER_DEFAULTS = dict(
    fixture="", league="", shvi_score=0, sh_pressure=0, ht="", ft="",
    sh_scoring_rate="0%", avg_fh_goals=0, late_threat="",
)
SH_8GOAL_DEFAULTS = dict(
    Fixture_ID="", League="", Time="", Fixture="", H_Goals_L5=0,
    A_Goals_L5=0, Labels="", Status="STANDARD",
)

# All engine keys — used by /api/status/{date} to report freshness at a glance.
ALL_ENGINE_KEYS = [
    "dna", "dna_v2", "dna_market_factors", "underdog_base", "underdog_audit",
    "calibration", "underdog_apex", "win_forecast", "sh_gg_winner",
    "corners_stage1", "corners_stage2", "corners_psychology", "corners_catalyst",
    "corners_aggregator", "gg_o15", "gg_forensics", "gg_psychology", "gg_supreme",
    "over25_stage1", "over25_stage2", "over25_stage3", "over25_psychology",
    "over25_gold", "over25_apex", "over25_forecast", "over15_stage3",
    "over15_psychology", "over15_apex", "unders", "draw", "sot", "fhvi", "shvi",
    "u2s_psychology", "win_psychology", "win_apex", "sh_master", "sh_8goal",
    "win_raw", "filter_gg",
    "filter_win__safe", "filter_win__balanced", "filter_win__aggressive",
    "filter_over25__banker", "filter_over25__balanced", "filter_over25__aggressive",
]


# ════════════════════════════════════════════════════════════════════════════
# HEALTH & OPS
# ════════════════════════════════════════════════════════════════════════════
@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "service": "AlienEdge Prediction API",
        "version": "4.0.0",
        "architecture": "disk-first — no live engine calls in request handlers",
        "server_time": datetime.now().isoformat(),
    }


@app.get("/api/status/{date}", tags=["Ops"])
def get_status(date: str):
    """Freshness report — which engines have saved output for this date, and
    when. This is your first stop when a page shows Demo data: it tells you
    immediately whether main.py has run for that date yet."""
    return store.status_for_date(date, ALL_ENGINE_KEYS)


@app.post("/api/admin/run-pipeline/{date}", tags=["Admin"])
def trigger_pipeline(date: str, x_admin_token: Optional[str] = Header(default=None)):
    """
    Launches `python main.py --date={date}` as a DETACHED background process
    and returns immediately (HTTP request is not held open for the minutes a
    full run takes). Poll /api/status/{date} to watch it complete. Requires
    ADMIN_TOKEN — this is an ops tool, not something the frontend calls.
    """
    require_admin(x_admin_token)
    python_bin = sys.executable
    log_path = os.path.join(OUTPUT_DIR, f"pipeline_run_{date}.log")
    with open(log_path, "a", encoding="utf-8") as log_file:
        subprocess.Popen(
            [python_bin, os.path.join(ROOT, "main.py"), f"--date={date}"],
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # detach fully — survives the API request finishing
        )
    return {"started": True, "date": date, "log_file": log_path}


@app.post("/api/admin/cache/clear-status", tags=["Admin"])
def noop_cache_clear(x_admin_token: Optional[str] = Header(default=None)):
    """No in-memory cache exists in this architecture (pure disk-first), so
    there is nothing to clear — this endpoint is kept only so any old ops
    tooling pointed at a 'clear cache' URL gets a clean 200 instead of 404."""
    require_admin(x_admin_token)
    return {"cleared": 0, "note": "disk-first architecture has no in-memory cache to clear"}


# ════════════════════════════════════════════════════════════════════════════
# FOUNDATION
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/dna/{date}", tags=["Foundation"])
def get_dna_profiles(date: str):
    data, _ = store.load("dna", date, default=[])
    return to_records(data)


@app.get("/api/dna/v2/{date}", tags=["Foundation"])
def get_dna_v2(date: str):
    engine_result, _ = store.load("dna_v2", date, default={})
    market_factors, _ = store.load("dna_market_factors", date, default={})
    dna_profiles = engine_result.get("dna_profiles", {}) if isinstance(engine_result, dict) else {}
    fixture_clashes = engine_result.get("fixture_clashes", []) if isinstance(engine_result, dict) else []
    return {
        "dna_profiles": dna_profiles,
        "fixture_clashes": fixture_clashes,
        "market_factors": market_factors or {},
    }


@app.get("/api/dna/v2/latest", tags=["Foundation"])
def get_dna_v2_latest():
    """Disk-only, no recompute — reads today's saved DNA v2 file if present."""
    return get_dna_v2(_today())


@app.get("/api/underdog/{date}", tags=["Foundation"])
def get_underdog(date: str):
    return read("underdog_base", date, UD_BASE_DEFAULTS, "u2s")


@app.get("/api/underdog/audit/{date}", tags=["Foundation"])
def get_underdog_audit(date: str):
    return read("underdog_audit", date, UD_AUDIT_DEFAULTS, "u2s")


@app.get("/api/underdog/apex/{date}", tags=["Foundation"])
def get_underdog_apex(date: str):
    return read("underdog_apex", date, UD_APEX_DEFAULTS, "u2s")


@app.get("/api/calibration/{date}", tags=["Foundation"])
def get_calibration(date: str):
    data, _ = store.load("calibration", date, default=[])
    return to_records(data)


@app.get("/api/win/forecast/{date}", tags=["Win"])
def get_win_forecast(date: str):
    return read("win_forecast", date, WIN_FORECAST_DEFAULTS, "win")


@app.get("/api/sh-gg-winner/{date}", tags=["Specials"])
def get_sh_gg_winner(date: str):
    return read("sh_gg_winner", date, SH_GG_WINNER_DEFAULTS, "shvi")


# ════════════════════════════════════════════════════════════════════════════
# WIN
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/win/psychology/{date}", tags=["Win"])
def get_win_psychology(date: str):
    return read("win_psychology", date, WIN_PSYCH_DEFAULTS, "win")


@app.get("/api/win/u2s/{date}", tags=["Win"])
def get_u2s(date: str):
    return read("u2s_psychology", date, WIN_U2S_DEFAULTS, "u2s")


@app.get("/api/win/apex/{date}", tags=["Win"])
def get_win_apex(date: str):
    # Prefer the exact date-tagged snapshot (main.py saves both); fall back
    # to '__latest' only if this specific date was never snapshotted.
    data, generated_at = store.load("win_apex", date, default=None)
    if data is None:
        data, generated_at = store.load("win_apex", None, default=[])
    return _settled(ensure_defaults(data, WIN_APEX_DEFAULTS), "win", date)


@app.get("/api/win/raw/{date}", tags=["Win"])
def get_win_raw(date: str):
    return read("win_raw", date, WIN_RAW_DEFAULTS, "win")


# ════════════════════════════════════════════════════════════════════════════
# GG / BTTS + OVER 1.5 (unified head engine — composite file)
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/gg/precision/{date}", tags=["GG"])
def get_gg_precision(date: str):
    raw, _ = store.load("gg_o15", date, default=[None, None])
    gg_raw = raw[0] if isinstance(raw, list) and len(raw) > 0 else []
    o15_raw = raw[1] if isinstance(raw, list) and len(raw) > 1 else []
    gg = ensure_defaults(gg_raw, GG_PRECISION_DEFAULTS)
    o15 = ensure_defaults(o15_raw, GG_O15_DEFAULTS)
    return {"gg": _settled(gg, "gg", date), "o15": _settled(o15, "o15", date)}


@app.get("/api/gg/forensics/{date}", tags=["GG"])
def get_gg_forensics(date: str):
    return read("gg_forensics", date, GG_FORENSIC_DEFAULTS, "gg")


@app.get("/api/gg/psychology/{date}", tags=["GG"])
def get_gg_psychology(date: str):
    return read("gg_psychology", date, GG_PSYCH_DEFAULTS, "gg")


@app.get("/api/gg/supreme/{date}", tags=["GG"])
def get_gg_supreme(date: str):
    return read("gg_supreme", date, GG_SUPREME_DEFAULTS, "gg")


@app.get("/api/gg/cross-verify", tags=["GG"])
def get_gg_cross_verify():
    # This route has no date param by design (7-day rolling cross-verify) —
    # correctly reads the dateless "__latest" snapshot main.py always writes.
    data, _ = store.load("filter_gg", None, default=[])
    return _settled(ensure_defaults(data, GG_CROSS_DEFAULTS), "gg")


# ════════════════════════════════════════════════════════════════════════════
# OVER 2.5
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/over25/stage1/{date}", tags=["Over 2.5"])
def get_over25_stage1(date: str):
    return read("over25_stage1", date, O25_STAGE1_DEFAULTS, "o25")


@app.get("/api/over25/stage2/{date}", tags=["Over 2.5"])
def get_over25_stage2(date: str):
    return read("over25_stage2", date, O25_STAGE2_DEFAULTS, "o25")


@app.get("/api/over25/stage3/{date}", tags=["Over 2.5"])
def get_over25_stage3(date: str):
    return read("over25_stage3", date, O25_STAGE3_DEFAULTS, "o25")


@app.get("/api/over25/psychology/{date}", tags=["Over 2.5"])
def get_over25_psychology(date: str):
    return read("over25_psychology", date, O25_PSYCH_DEFAULTS, "o25")


@app.get("/api/over25/gold/{date}", tags=["Over 2.5"])
def get_over25_gold(date: str):
    data, _ = store.load("over25_gold", date, default=[])
    return to_records(data)


@app.get("/api/over25/apex/{date}", tags=["Over 2.5"])
def get_over25_apex(date: str):
    return read("over25_apex", date, O25_APEX_DEFAULTS, "o25")


@app.get("/api/over25/forecast/{date}", tags=["Over 2.5"])
def get_over25_forecast(date: str):
    return read("over25_forecast", date, O25_FORECAST_DEFAULTS, "o25")


# ════════════════════════════════════════════════════════════════════════════
# OVER 1.5
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/over15/stage3/{date}", tags=["Over 1.5"])
def get_over15_stage3(date: str):
    return read("over15_stage3", date, O15_STAGE3_DEFAULTS, "o15")


@app.get("/api/over15/psychology/{date}", tags=["Over 1.5"])
def get_over15_psychology(date: str):
    return read("over15_psychology", date, O15_PSYCH_DEFAULTS, "o15")


@app.get("/api/over15/apex/{date}", tags=["Over 1.5"])
def get_over15_apex(date: str):
    return read("over15_apex", date, O15_APEX_DEFAULTS, "o15")


# ════════════════════════════════════════════════════════════════════════════
# CORNERS
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/corners/stage1/{date}", tags=["Corners"])
def get_corners_stage1(date: str):
    return read("corners_stage1", date, CORNER_S1_DEFAULTS, "corners")


@app.get("/api/corners/stage2/{date}", tags=["Corners"])
def get_corners_stage2(date: str):
    return read("corners_stage2", date, CORNER_S2_DEFAULTS, "corners")


@app.get("/api/corners/psychology/{date}", tags=["Corners"])
def get_corners_psychology(date: str):
    return read("corners_psychology", date, CORNER_PSYCH_DEFAULTS, "corners")


@app.get("/api/corners/catalyst/{date}", tags=["Corners"])
def get_corners_catalyst(date: str):
    return read("corners_catalyst", date, CORNER_CATALYST_DEFAULTS, "corners")


@app.get("/api/corners/aggregator/{date}", tags=["Corners"])
def get_corners_aggregator(date: str):
    return read("corners_aggregator", date, CORNER_AGG_DEFAULTS, "corners")


# ════════════════════════════════════════════════════════════════════════════
# DRAW / UNDERS (composite files: (draws, parity, amateurs) and (u25, u35))
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/draw/{date}", tags=["Draw"])
def get_draw(date: str):
    raw, _ = store.load("draw", date, default=[[], [], []])
    draws_raw = raw[0] if isinstance(raw, list) and len(raw) > 0 else []
    parity_raw = raw[1] if isinstance(raw, list) and len(raw) > 1 else []
    amateurs_raw = raw[2] if isinstance(raw, list) and len(raw) > 2 else []
    return {
        "draws": _settled(ensure_defaults(draws_raw, DRAW_DEFAULTS), "win", date),
        "parity_list": ensure_defaults(parity_raw, DRAW_DEFAULTS),
        "amateurs_list": ensure_defaults(amateurs_raw, DRAW_DEFAULTS),
    }


@app.get("/api/unders/{date}", tags=["Unders"])
def get_unders(date: str):
    raw, _ = store.load("unders", date, default=[[], []])
    u25_raw = raw[0] if isinstance(raw, list) and len(raw) > 0 else []
    u35_raw = raw[1] if isinstance(raw, list) and len(raw) > 1 else []
    return {
        "u25": _settled(ensure_defaults(u25_raw, UNDERS_DEFAULTS), "o25", date),
        "u35": ensure_defaults(u35_raw, UNDERS_DEFAULTS),
    }


# ════════════════════════════════════════════════════════════════════════════
# SOT / FHVI / SHVI
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/sot/{date}", tags=["Specials"])
def get_sot(date: str):
    return read("sot", date, SOT_DEFAULTS, "sot")


@app.get("/api/fhvi/{date}", tags=["Specials"])
def get_fhvi(date: str):
    return read("fhvi", date, FHVI_DEFAULTS, "shvi")


@app.get("/api/shvi/{date}", tags=["Specials"])
def get_shvi(date: str):
    # Strictly keyed on (shvi, date) — this is the fix for the old
    # "shows real data but wrong date" bug. No undated fallback exists here.
    return read("shvi", date, SHVI_DEFAULTS, "shvi")


@app.get("/api/sh-master/{date}", tags=["Specials"])
def get_sh_master(date: str):
    return read("sh_master", date, SH_MASTER_DEFAULTS, "shvi")


@app.get("/api/sh-8goal/{date}", tags=["Specials"])
def get_sh_8goal(date: str):
    return read("sh_8goal", date, SH_8GOAL_DEFAULTS, "shvi")


# ════════════════════════════════════════════════════════════════════════════
# LIVE ENGINES — written continuously by run_live_scanner_24_7.py (a separate
# always-on process). Read directly from data/*.json — unchanged, this
# pattern was already correct (continuous writer, on-demand reader).
# ════════════════════════════════════════════════════════════════════════════
def _read_json(path: str, default=None):
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
    raw = _read_json(os.path.join(DATA_DIR, "incoming_predictions.json"), {})
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    rows = []
    for fixture_id, value in raw.items():
        if isinstance(value, list):
            rows.append({"fixture_id": str(fixture_id), "fixture": str(fixture_id), "picks": value})
        elif isinstance(value, dict):
            picks = value.get("picks", [])
            rows.append({
                "fixture_id": str(value.get("fixture_id", fixture_id)),
                "fixture": str(value.get("fixture", fixture_id)),
                "picks": picks if isinstance(picks, list) else [],
            })
    return rows


@app.get("/api/live/prematch", tags=["Live"])
def get_live_prematch():
    raw = _read_json(os.path.join(DATA_DIR, "prematch_team_audit.json"), {})
    return list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])


@app.get("/api/live/validation", tags=["Live"])
def get_live_validation():
    alerts = _read_json(os.path.join(DATA_DIR, "validated_picks.json"), {})
    state = _read_json(os.path.join(DATA_DIR, "validation_state.json"), {})
    alert_list = list(alerts.values()) if isinstance(alerts, dict) else alerts
    return {
        "cycle": 1,
        "total_tracked": len(state) if isinstance(state, (list, dict)) else 0,
        "alerts": alert_list if isinstance(alert_list, list) else [],
        "matches": [],
    }


@app.get("/api/live/incoming", tags=["Live"])
def get_live_incoming():
    return _incoming_rows_from_disk()


@app.get("/api/live/danger", tags=["Live"])
def get_live_danger():
    return _read_json(os.path.join(DATA_DIR, "danger_audit.json"), [])


@app.get("/api/live/aggregator", tags=["Live"])
def get_live_aggregator():
    return _read_json(os.path.join(DATA_DIR, "aggregator_report.json"), [])


@app.get("/api/live/orchestrator", tags=["Live"])
def get_live_orchestrator():
    default_board = {"session": "", "cycle": 0, "total_live": 0, "total_db": 0, "matches": []}
    return _read_json(os.path.join(OUTPUT_DIR, "orchestrator_board.json"), default_board)


@app.get("/api/live/alerts", tags=["Live"])
def get_live_alerts():
    path = os.path.join(OUTPUT_DIR, "ready_to_push.json")
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    rows.sort(key=lambda r: r.get("time", ""), reverse=True)
    return rows


@app.get("/api/live/dashboard", tags=["Live"])
def get_live_dashboard():
    return _read_json(os.path.join(OUTPUT_DIR, "live_dashboard.json"), [])


# ════════════════════════════════════════════════════════════════════════════
# FILTER ENDPOINTS — read the risk-level matrix main.py now precomputes
# (filter_win__safe / __balanced / __aggressive, filter_over25__banker /
# __balanced / __aggressive) so the interactive Weekly Filter page never
# needs a live compute either.
# ════════════════════════════════════════════════════════════════════════════
_WIN_RISK_LEVELS = {"safe", "balanced", "aggressive"}
_O25_RISK_LEVELS = {"banker", "balanced", "aggressive"}


@app.get("/api/filter/gg/weekly", tags=["Filters"])
def filter_gg_weekly(mode: str = "public"):
    return get_gg_cross_verify()


@app.get("/api/filter/gg/{date}", tags=["Filters"])
def filter_gg_single(date: str, mode: str = "public"):
    # FIX: main.py saves filter_gg under BOTH the dateless "__latest" key
    # AND a per-date snapshot (store.save("filter_gg", d, ...) in main.py).
    # This route previously always read "__latest" regardless of the date
    # requested, so picking a different date silently returned today's data.
    # Now: prefer the exact date's snapshot; fall back to "__latest" only if
    # that specific date was never snapshotted (e.g. pipeline hasn't run yet).
    data, generated_at = store.load("filter_gg", date, default=None)
    if data is None:
        data, generated_at = store.load("filter_gg", None, default=[])
    return _settled(ensure_defaults(data, GG_CROSS_DEFAULTS), "gg", date)


@app.get("/api/filter/win/weekly", tags=["Filters"])
def filter_win_weekly(
    mode: str = "public",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
    risk_level: str = "balanced",
):
    # FIX: previously only ever read ONE day even for a 7-day range request.
    # Now genuinely walks every date in [start_date, end_date] (or a single
    # anchor_date if that's all that was given) and concatenates each day's
    # saved picks — this requires main.py to have actually run for each of
    # those dates; days it hasn't reached yet simply contribute 0 rows.
    risk = risk_level if risk_level in _WIN_RISK_LEVELS else "balanced"
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    return read_range(lambda d: f"filter_win__{risk}", dates, WIN_FORECAST_DEFAULTS, "win")


@app.get("/api/filter/win/{date}", tags=["Filters"])
def filter_win_single(date: str, mode: str = "public", risk_level: str = "balanced"):
    risk = risk_level if risk_level in _WIN_RISK_LEVELS else "balanced"
    return read(f"filter_win__{risk}", date, WIN_FORECAST_DEFAULTS, "win")


@app.get("/api/filter/over25/weekly", tags=["Filters"])
def filter_over25_weekly(
    mode: str = "public",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
    risk_level: str = "balanced",
    odds_band: str = "1.50-1.85",
):
    risk = risk_level if risk_level in _O25_RISK_LEVELS else "balanced"
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    return read_range(lambda d: f"filter_over25__{risk}", dates, O25_FORECAST_DEFAULTS, "o25")


@app.get("/api/filter/over25/{date}", tags=["Filters"])
def filter_over25_single(date: str, mode: str = "public", risk_level: str = "balanced"):
    risk = risk_level if risk_level in _O25_RISK_LEVELS else "balanced"
    return read(f"filter_over25__{risk}", date, O25_FORECAST_DEFAULTS, "o25")


@app.get("/api/filter/win/precision/weekly", tags=["Filters"])
def filter_win_precision_weekly(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    return read_range(lambda d: "filter_win__safe", dates, WIN_FORECAST_DEFAULTS, "win")


@app.get("/api/filter/win/precision/{date}", tags=["Filters"])
def filter_win_precision_single(date: str):
    return read("filter_win__safe", date, WIN_FORECAST_DEFAULTS, "win")
