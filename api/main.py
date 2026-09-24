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
import math
import re
import secrets
import subprocess
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Query, Depends, Request
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

# Weekly filter control layer — turns the /weekly/* page's mode / risk / odds /
# drawer parameters into validated overrides and, for any non-baseline request,
# runs the SAME existing FILTER engines over the SAME dated artifacts
# (persist=False). Pure disk + pandas: no new API calls, no new maths.
from api.weekly_filter_live import (  # noqa: E402
    gg_filter_params,
    win_filter_params,
    win_precision_params,
    o25_filter_params,
    is_baseline,
    live_query,
)

# Intelligent Pass Count — pure read-only second-level audit over the same
# cache snapshots. Display/audit only: it never changes predictions,
# settlement or Verify. Wrapped in try/except so a missing/moved module can
# never take the picks API down (column simply renders empty).
try:  # noqa: E402
    from INTELLIGENT_PASS import pass_count as intelligent_pass
except Exception:  # pragma: no cover
    intelligent_pass = None


def _with_intelligent_pass(market_key: str, rows, date: Optional[str]):
    """Attach the additive `intelligent_pass_count` audit object to each row
    (no existing key is removed, renamed or re-ordered). No-op unless the
    evaluator module imported cleanly — the API contract is unchanged then."""
    if intelligent_pass is None or not date or not rows:
        return rows
    try:
        return intelligent_pass.evaluate_market_safe(market_key, rows, date)
    except Exception:
        return rows


# ── FIXTURE RISK FLAGS (cup / friendly) ──────────────────────────────────────
# One label per fixture, decided ONCE by fixture_classification from the shared
# window and persisted per date by the pipeline. Here it is stamped onto EVERY
# row the API serves, so no market page, weekly page or report can be missing
# the warning. Purely additive: rows keep every key they already had, and a
# fixture with no stored label is reported as `unknown` (never as "safe").
_FIXTURE_RISK_INDEX: dict = {}      # date -> {"by_id": {}, "by_name": {}}
_FIXTURE_RISK_ENABLED = True
_LABEL_SPLIT = re.compile(r"\s+(?:vs?\.?|against|-)\s+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _clean_team(value):
    return " ".join(_NON_ALNUM.sub(" ", str(value or "").lower()).split())


def _normalise_label(label):
    """'Ajax vs Heerenveen' -> 'ajax|heerenveen'.

    MUST produce exactly the same shape as `_label_keys()` (team text with its
    internal spaces kept, teams joined by '|'), because both sides of the join
    are produced here. Order is preserved; the reverse ordering is indexed
    separately by `_label_keys`.
    """
    if not label:
        return ""
    text = str(label).lower().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text).strip()
    parts = [p for p in _LABEL_SPLIT.split(text) if p.strip()]
    if len(parts) >= 2:
        return f"{_clean_team(parts[0])}|{_clean_team(parts[1])}"
    return _clean_team(text)


def _label_keys(home, away):
    """Both orderings of a home/away pair, so 'A vs B' matches either side order."""
    a, b = _clean_team(home), _clean_team(away)
    if not a or not b:
        return []
    return [f"{a}|{b}", f"{b}|{a}"]


def _fixture_risk_index(date: str) -> dict:
    """Load one date's labels, indexed BOTH by fixture id and by fixture label.

    id index   : "19726053"                    (exact, authoritative)
    name index : "napoli|as roma" + reverse   (fallback, unique matches only)

    The name index exists because several prematch engines identify their
    fixture by label only (`Fixture` / `fixture` / `Match`) or by a differently
    named id (`Fixture_ID`, `id`). It is deliberately STRICT: a label is
    accepted only when it maps to exactly ONE fixture that day, and both the
    home|away and away|home orderings are indexed. Ambiguity therefore resolves
    to `unknown`, never to a guess.
    """
    if not _FIXTURE_RISK_ENABLED or not date:
        return {}
    if date in _FIXTURE_RISK_INDEX:
        return _FIXTURE_RISK_INDEX[date]
    by_id, by_name = {}, {}
    try:
        rows, _generated_at = store.load("fixture_risk", date, default=[])
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            fid = row.get("fixture_id")
            if fid in (None, ""):
                continue
            fid = str(fid)
            by_id[fid] = row
            # NOTE: keyed by fixture id, not appended blindly — a fixture is
            # reached by BOTH its participant names and its own `name`, so a
            # list-append would store the same fixture twice under one key and
            # every key would then look "ambiguous" and be thrown away.
            for key in _label_keys(row.get("home_team"), row.get("away_team")):
                by_name.setdefault(key, {})[fid] = row
            label = _normalise_label(row.get("fixture_label"))
            if label:
                by_name.setdefault(label, {})[fid] = row
    except Exception:
        by_id, by_name = {}, {}
    # keep ONLY unambiguous labels (exactly one fixture behind the key)
    by_name = {k: next(iter(v.values())) for k, v in by_name.items() if len(v) == 1}
    _FIXTURE_RISK_INDEX[date] = {"by_id": by_id, "by_name": by_name}
    return _FIXTURE_RISK_INDEX[date]


def _row_fixture_label(row):
    """The fixture label a row displays, whichever of the repo's field names it
    uses (`fixture` / `Fixture` / `Match` / `match` / `Target` / `Fixture_ID`)."""
    for key in ("fixture", "Fixture", "match", "Match", "Target"):
        value = row.get(key)
        if value:
            return value
    return None


def _row_fixture_id(row):
    """The fixture id a row carries, whichever field name it uses
    (`fixture_id` / `Fixture_ID` / `id`)."""
    for key in ("fixture_id", "Fixture_ID", "id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _lookup_fixture_risk(row, index):
    """Exact fixture id first, then a unique fixture-label match."""
    fid = _row_fixture_id(row)
    if fid and fid in index["by_id"]:
        return index["by_id"][fid]
    label = _row_fixture_label(row)
    if label:
        key = _normalise_label(label)
        if key and key in index["by_name"]:
            return index["by_name"][key]
        home, away = row.get("home_team"), row.get("away_team")
        if home and away:
            for key in _label_keys(home, away):
                if key in index["by_name"]:
                    return index["by_name"][key]
    return None


def _with_fixture_risk(rows, date: Optional[str]):
    """Stamp additive fixture-risk fields onto each row (no-op without a date).

    `is_cup` / `is_friendly` are booleans (False when unknown, and False is NOT
    a safety claim — `classification` carries the honest `unknown`).
    """
    if not rows or not date:
        return rows
    index = _fixture_risk_index(date)
    if not index or not (index["by_id"] or index["by_name"]):
        return rows
    for row in rows:
        if not isinstance(row, dict):
            continue
        flags = _lookup_fixture_risk(row, index)
        if not flags:
            # No stored label for this fixture: say so instead of implying safety.
            row.setdefault("classification", "unknown")
            continue
        row["classification"] = flags.get("classification")
        row["is_cup"] = bool(flags.get("is_cup"))
        row["is_friendly"] = bool(flags.get("is_friendly"))
        row["is_risk_fixture"] = bool(flags.get("is_risk_fixture"))
        row["risk_level"] = flags.get("risk_level")
        row["risk_label"] = flags.get("risk_label")
        row["competition"] = flags.get("competition")
        row["league_name"] = flags.get("league_name")
    return rows

# ── APP INIT ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AlienEdge Prediction API",
    version="4.0.0",
    description="Forensic football prediction engine — disk-first REST interface",
    docs_url=None if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() == "production" else "/docs",
    redoc_url=None if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() == "production" else "/redoc",
    openapi_url=None if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() == "production" else "/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
ALLOW_ORIGINS = [o.strip() for o in _env_origins.split(",") if o.strip()]
if not ALLOW_ORIGINS and os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "production")).lower() != "production":
    ALLOW_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
  allow_origins=ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Admin-Token", "X-Request-ID"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = request.headers.get("x-request-id", secrets.token_hex(8))
    print(f"[UNHANDLED] request_id={request_id} path={request.url.path} error={type(exc).__name__}")
    return JSONResponse(status_code=500, content={"detail": "Unable to complete the request.", "request_id": request_id})


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    path = request.url.path
    public_paths = {"/", "/health"}
    if path.startswith("/api/auth/") or path in public_paths or path.startswith("/api/admin/"):
        request.state.user = get_user_for_session(request.cookies.get(SESSION_COOKIE))
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    user = get_user_for_session(request.cookies.get(SESSION_COOKIE))
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Authentication required."})
    request.state.user = user
    if not check_rate_limit(f"api:{user['user_id']}", 180, 60):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# ── ROUTERS ───────────────────────────────────────────────────────────────────
from api.auth_store import SESSION_COOKIE, check_rate_limit, get_user_for_session
from api.auth_router import router as auth_router
from api.user_rules_router import router as user_rules_router  # noqa: E402
app.include_router(auth_router)
app.include_router(user_rules_router)

# ── SETTLEMENT / LIVE SCORES (independent of the pre-match pipeline) ──────────
from settlement_service import settle_predictions, extract_match_data, load_finished_archive  # noqa: E402
from live_cache import get_live_scores_cached  # noqa: E402

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def require_admin(token: Optional[str], request: Optional[Request] = None):
    if not ADMIN_TOKEN or not token or not secrets.compare_digest(str(token), ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Admin access required.")
    if request is not None and not check_rate_limit(f"admin:{request.client.host if request.client else 'unknown'}", 10, 60):
        raise HTTPException(status_code=429, detail="Too many admin requests. Please try again later.")


def to_records(x) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    # A dict is NOT a list of records. Returning it as-is let /api/dna/{date}
    # (before the hoist below) emit a JSON object where the frontend expects an
    # array, silently emptying the Win "Team DNA — Goal Intent Board". The
    # {'team_id': profile} shape is unpacked to records in get_dna_profiles().
    return []


def ensure_defaults(rows, defaults: dict) -> list:
    """
    Guarantees every row has every key `defaults` names, using the default
    only when the SAVED row is missing that key entirely — this is what
    stopped `r.fatigue_home.toFixed()` etc. from ever crashing the frontend
    again, regardless of which historical engine version wrote the file.

    Non-finite floats (NaN / ±Infinity) written by older engine versions are
    treated exactly like a missing value: replaced with the schema default
    (`defaults[k]`, else 0) so the row stays JSON-safe and numerically
    meaningful. Finite numbers are NEVER touched.

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
        # ── Non-finite / None repair (NaN / ±Inf / null → schema default) ──
        # NaN and ±Infinity written by older engine versions are treated
        # exactly like a missing value: replaced with the schema default
        # (`defaults[k]`, else 0). `None` values on schema-covered keys get
        # the same treatment (mirrors the historical in-process sanitizer,
        # which served 0 for both NaN and null on schema fields, e.g.
        # corners_stage1 odds). `None` on a key OUTSIDE the schema is a
        # legitimate "no data" marker and is preserved as null.
        # Finite numbers are NEVER touched.
        clean_r = {}
        for k, v in r.items():
            if isinstance(v, float) and not math.isfinite(v):
                clean_r[k] = defaults.get(k, 0)
            elif v is None and k in defaults:
                clean_r[k] = defaults[k]
            else:
                clean_r[k] = v
        missing = [k for k in defaults.keys() if k not in clean_r]
        merged = dict(defaults)
        merged.update(clean_r)
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


# Market keys grade_row() actually implements. Any market outside this set has
# no verdict math — routing it through grade_row would fabricate a LOST verdict
# (grade_row's default is won=False), the same class of silent error the
# "win"-keyed draw rows suffered. Those rows get an explicit PENDING payload
# instead, so the UI never shows a false ❌ for an ungradeable market.
SUPPORTED_SETTLEMENT_MARKETS = {
    "win", "1x2",
    "gg", "btts",
    "o25", "over25", "over 2.5",
    "o15", "over15", "over 1.5",
    "draw", "draws",
    "u25", "under25", "under 2.5",
    # High Parity List (score gap <= 2 — user-confirmed; NOT the exact-draw
    # "draw" branch) and Under 3.5 (total goals <= 3 — NOT the u25 <= 2
    # branch). Both were previously absent here, so /api/draw parity_list and
    # /api/unders u35 rows got the blanket-PENDING path and Verify stayed
    # blank even when grade_row had the math.
    "parity", "high_parity",
    "u35", "u3.5", "under35", "under 3.5",
    "corners",
    "shvi", "sh_goal",
    "sot",
    "fhvi", "fh_goal",
    "u2s",
}


def _settled(data, market_type: str = "win", date_str: Optional[str] = None):
    if not isinstance(data, list) or len(data) == 0:
        return data
    if str(market_type).lower() not in SUPPORTED_SETTLEMENT_MARKETS:
        # No grading branch for this market (e.g. "sot"): PENDING, never a
        # fabricated verdict. Shape mirrors grade_row's SCHEDULED payload so
        # the frontend contract is unchanged.
        pending = {
            "status": "SCHEDULED",
            "score": "—",
            "minute": None,
            "verdict": "PENDING",
            "badge_text": "—",
            "note": "Awaiting Kickoff",
        }
        return [({**row, "verification": dict(pending)} if isinstance(row, dict) else row)
                for row in data]
    try:
        # Historical dates settle entirely from output/archive_{date}.json +
        # FT snapshots. Fetching the live in-play feed for a PAST date is pure
        # waste — and while a shared 429 cooldown gate is active it used to
        # stall every historical request ~10s server-side (the "date switching
        # lags behind" regression). An empty live db is CORRECT here:
        # settle_predictions(date_str=...) loads the archive layer itself and
        # keeps WON/LOST verdicts permanent; today (or undated) keeps the
        # live-feed behaviour unchanged.
        if date_str and str(date_str) < _today():
            live_db = []
        else:
            live_db = get_live_scores_cached()
        # date_str (the date of the picks being verified) is what activates
        # the persistent finished-results layer: settlement additionally
        # loads output/archive_{date_str}.json so WON/LOST survives after a
        # fixture leaves the in-play feed, and historical dates settle from
        # their own archive instead of staying PENDING forever. Without it
        # settlement behaves exactly as before (live feed only).
        return settle_predictions(data, live_db, market_type=market_type, date_str=date_str)
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


# ─ FILTER SHAPE GUARD (P0-6b / forensic-report P0-5) ─────────────────────────
# A one-day historical save-key fault (2026-09-10) wrote the CORNERS payload
# under five filter keys — filter_win__safe, filter_win__balanced and
# filter_over25__{banker,balanced,aggressive} — 26 foreign rows each. The
# weekly endpoints walk every date in [start_date, end_date], so those rows
# were still being SERVED inside a 7-day request (they arrive as all-zero /
# _incomplete rows after ensure_defaults): fabricated picks on a real page.
#
# The files are DATA and must not be deleted or rewritten, so the guard runs at
# the READ boundary, and only for the affected markets.
#
# A row is rejected only when BOTH hold:
#   1. every identity key of the market the key claims is absent, AND
#   2. a key from another market's signature is present.
# So a genuine row of the requested market is always kept, and a row with no
# recognisable signature at all (e.g. an older schema) is also kept — the guard
# only ever removes rows that provably belong to a DIFFERENT market.
# Verified against the real files: 09-10 contaminated rows carry the corners
# signature and zero win/o25 identity keys, while clean win rows carry all four
# identity keys (09-11/13/14) and GG rows match neither set — which is why this
# is opt-in per route (`identity=`) and never applied to GG or other markets.
_FILTER_MARKET_IDENTITY = {
    "win": {"win_odds", "team_name", "side", "parity_score"},
    "o25": {"o25_odds", "poisson_over_prob_num", "council_votes", "pos_gap",
            "kill_switch_pass"},
}
_FOREIGN_MARKET_SIGNATURE = {
    "corner_tier", "expected_total_corners", "team_more_corners",
    "expected_difference",
}


def _is_foreign_filter_row(row, market: Optional[str]) -> bool:
    if not market or not isinstance(row, dict):
        return False
    identity = _FILTER_MARKET_IDENTITY.get(market)
    if not identity:
        return False
    if identity & set(row.keys()):
        return False  # a genuine row of this market → always kept
    return bool(_FOREIGN_MARKET_SIGNATURE & set(row.keys()))


def _guard_filter_rows(rows, market: Optional[str]):
    """Drop provably-foreign rows for `market` (no-op for other markets)."""
    if not market:
        return rows
    kept, dropped = [], 0
    for row in rows:
        if _is_foreign_filter_row(row, market):
            dropped += 1
            continue
        kept.append(row)
    if dropped:
        print(f"[FILTER SHAPE GUARD] dropped {dropped} foreign {market} row(s) — "
              f"payload belongs to another market (historical save-key fault); "
              f"cache file left untouched")
    return kept


def read_range(key_prefix_fn, dates: list, defaults: dict, market_type: str, settle: bool = True,
               identity: Optional[str] = None) -> list:
    """
    Reads and concatenates one saved file PER DATE in `dates`, tagging each
    row with the date it came from so a "7-day range" filter route actually
    returns a week of picks instead of silently collapsing to a single day
    (the previous behaviour, inherited unchanged from the old backend).
    `key_prefix_fn(date)` returns the output_store key to load for that date.
    `identity` (optional) enables the filter-market shape guard above; when
    omitted the behaviour is byte-identical to before.
    """
    combined = []
    for d in dates:
        data, _ = store.load(key_prefix_fn(d), d, default=[])
        # Guard runs on RAW loaded data so it can see which keys the file
        # actually contains. ensure_defaults() below injects every missing
        # schema key (e.g. win_odds=0, team_name=0, side=0, parity_score=0)
        # into every row regardless of origin, so a contaminated corners row
        # from 09-10 would otherwise pass the identity check after defaulting.
        rows = _guard_filter_rows(data, identity)
        rows = ensure_defaults(rows, defaults)
        rows = _with_fixture_risk(rows, d)     # additive cup/friendly labels
        if settle:
            rows = _settled(rows, market_type, d)
        for row in rows:
            if isinstance(row, dict) and "match_date" not in row:
                row["match_date"] = d
        combined.extend(rows)
    return combined


def read(key: str, date: Optional[str], defaults: dict, market_type: str = "win", settle: bool = True,
         identity: Optional[str] = None):
    """The one helper every picks route uses: load from disk, fill defaults,
    optionally settle against live/finished scores. No engine is ever called
    here — a cache miss is just an empty list, not a live recompute.
    `identity` (optional) enables the filter-market shape guard; when omitted
    the behaviour is byte-identical to before."""
    data, _generated_at = store.load(key, date, default=[])
    # Same ordering rationale as read_range above: inspect raw data before
    # ensure_defaults injects schema-wide defaults.
    rows = _guard_filter_rows(data, identity)
    rows = ensure_defaults(rows, defaults)
    rows = _with_fixture_risk(rows, date)     # additive cup/friendly labels
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
    fixture_id="", fixture_name="", stage1_predicted_corners=0, stage2_predicted_corners=0,
    predicted_corners=0, corner_tier="STANDARD", style_alignment="",
    diff=0, avg_confidence=0, prob=0,
    home_is_persistent_venue=False, away_is_persistent_venue=False,
    home_is_persistent_overall=False, away_is_persistent_overall=False,
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
    }


@app.get("/api/status/{date}", tags=["Ops"])
def get_status(date: str):
    """Freshness report — which engines have saved output for this date, and
    when. This is your first stop when a page shows Demo data: it tells you
    immediately whether main.py has run for that date yet."""
    return store.status_for_date(date, ALL_ENGINE_KEYS)


@app.post("/api/admin/run-pipeline/{date}", tags=["Admin"])
def trigger_pipeline(date: str, request: Request, x_admin_token: Optional[str] = Header(default=None)):
    """
    Launches `python main.py --date={date}` as a DETACHED background process
    and returns immediately (HTTP request is not held open for the minutes a
    full run takes). Poll /api/status/{date} to watch it complete. Requires
    ADMIN_TOKEN — this is an ops tool, not something the frontend calls.
    """
    require_admin(x_admin_token, request)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc

    python_bin = sys.executable
    log_path = os.path.join(OUTPUT_DIR, f"pipeline_run_{date}.log")
    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"
    with open(log_path, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [python_bin, "-u", os.path.join(ROOT, "main.py"), f"--date={date}"],
            cwd=ROOT,
            env=child_env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # detach fully — survives the API request finishing
        )
    return {
        "started": True,
        "date": date,
        "pid": process.pid,
        "log_file": log_path,
        "output": "detached; poll /api/status/{date} and inspect log_file",
    }


@app.post("/api/admin/cache/clear-status", tags=["Admin"])
def noop_cache_clear(request: Request, x_admin_token: Optional[str] = Header(default=None)):
    """No in-memory cache exists in this architecture (pure disk-first), so
    there is nothing to clear — this endpoint is kept only so any old ops
    tooling pointed at a 'clear cache' URL gets a clean 200 instead of 404."""
    require_admin(x_admin_token, request)
    return {"cleared": 0, "note": "disk-first architecture has no in-memory cache to clear"}


# ════════════════════════════════════════════════════════════════════════════
# FOUNDATION
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/dna/{date}", tags=["Foundation"])
def get_dna_profiles(date: str):
    data, _ = store.load("dna", date, default={})
    if isinstance(data, dict):
        # dna v1 is persisted as {team_id: profile}. The frontend DnaProfile[]
        # contract expects a flat list, so hoist each dict key into `team_id`
        # and emit records — otherwise Array.isArray() on the client sees an
        # object and the "Team DNA — Goal Intent Board" renders empty despite
        # real profiles being present on disk.
        return [
            {"team_id": str(team_id), **profile}
            for team_id, profile in data.items()
            if isinstance(profile, dict)
        ]
    return to_records(data)


@app.get("/api/dna/v2/latest", tags=["Foundation"])
def get_dna_v2_latest():
    """Disk-only, no recompute — returns the NEWEST dated DNA v2 snapshot on
    disk (not "today"), so it never silently empties when the pipeline has
    not yet run for the current calendar date.

    Resolution: enumerate output/cache/dna_v2__YYYY-MM-DD.json, keep only
    strictly-valid dates, pick the maximum, and delegate to
    get_dna_v2(selected_date). If no valid dated file exists the route
    preserves the safe empty response shape.

    This route MUST stay registered BEFORE /api/dna/v2/{date}: FastAPI
    matches routes in registration order, so with the {date} variant first
    the literal path segment "latest" was captured as a date and resolved
    to the (missing) dna_v2__latest.json file, silently emptying the DNA
    badge across the frontend."""
    prefix = "dna_v2__"
    suffix = ".json"
    try:
        names = os.listdir(store.CACHE_DIR)
    except OSError:
        names = []

    dates = []
    for name in names:
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        candidate = name[len(prefix):-len(suffix)]
        # Strict YYYY-MM-DD match: exactly 10 chars, numeric with dashes at
        # positions 4 and 7 (i.e. "dna_v2__YYYY-MM-DD.json").
        if (
            len(candidate) == 10
            and candidate[:4].isdigit()
            and candidate[4] == "-"
            and candidate[5:7].isdigit()
            and candidate[7] == "-"
            and candidate[8:10].isdigit()
        ):
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
            except ValueError:
                continue
            dates.append(candidate)

    if not dates:
        return {"dna_profiles": {}, "fixture_clashes": [], "market_factors": {}}

    return get_dna_v2(max(dates))


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


@app.get("/api/underdog/{date}", tags=["Foundation"])
def get_underdog(date: str):
    return _with_intelligent_pass(
        "u2s", read("underdog_base", date, UD_BASE_DEFAULTS, "u2s"), date)


@app.get("/api/team-intelligence/{date}/{team_name}", tags=["Foundation"])
def get_team_intelligence(date: str, team_name: str):
    """Team Intelligence page feed — the team's per-check intelligence across
    every market AlienEdge already produced for this date. Read-only local
    composition (INTELLIGENT_PASS/pass_count.py): NO new SportMonks calls, no
    duplicate fixture requests, no duplicate intelligence calculations."""
    if intelligent_pass is None:
        raise HTTPException(status_code=503, detail="Intelligent Pass evaluator unavailable")
    try:
        return intelligent_pass.get_team_intelligence(team_name, date)
    except Exception:
        raise HTTPException(status_code=404, detail="Team intelligence not available")


@app.get("/api/underdog/audit/{date}", tags=["Foundation"])
def get_underdog_audit(date: str):
    return _with_intelligent_pass(
        "u2s", read("underdog_audit", date, UD_AUDIT_DEFAULTS, "u2s"), date)


@app.get("/api/underdog/apex/{date}", tags=["Foundation"])
def get_underdog_apex(date: str):
    # The apex engine's output carries NO underdog-team column (verified:
    # keys are DNA/Engine/Fav_Vuln/Fixture/Handshake/Monte_UD_Prob/Rule/
    # SH_GG_Label), so the u2s grader had nothing to match against and every
    # row degraded to PENDING "Underdog '?' not identifiable". The
    # psychology feed (u2s_psychology, same pipeline date) DOES carry the
    # dog name in its `Underdog` column — merge it in by fixture name
    # BEFORE settlement (read() settles internally, so this endpoint loads
    # with the same building blocks but in merge-first order).
    data, _generated_at = store.load("underdog_apex", date, default=[])
    rows = ensure_defaults(_guard_filter_rows(data, None), UD_APEX_DEFAULTS)
    try:
        psych_rows, _ = store.load("u2s_psychology", date, default=[])
        if isinstance(psych_rows, dict):
            psych_rows = next((v for v in psych_rows.values()
                               if isinstance(v, list)), [])
        dog_by_fixture = {}
        for pr in psych_rows or []:
            if not isinstance(pr, dict):
                continue
            fx_name = str(pr.get("fixture") or pr.get("Fixture") or "").strip()
            dog = str(pr.get("Underdog") or "").strip()
            if fx_name and dog:
                dog_by_fixture[fx_name.lower()] = dog
        for r in rows:
            if not isinstance(r, dict) or r.get("underdog_team"):
                continue
            fx_name = str(r.get("fixture") or r.get("Fixture") or "").strip().lower()
            if not fx_name:
                continue
            if fx_name in dog_by_fixture:
                r["underdog_team"] = dog_by_fixture[fx_name]
                continue
            # Team-level match: the two engines spell team names
            # differently ("OFI" vs "OFI Crete"), so full fixture-string
            # containment fails. A psych row matches when BOTH of the
            # apex row's team names appear in the psych fixture string.
            teams = [t.strip() for t in fx_name.split(" vs ") if t.strip()]
            if len(teams) == 2:
                for k_fx, k_dog in dog_by_fixture.items():
                    if teams[0] in k_fx and teams[1] in k_fx:
                        r["underdog_team"] = k_dog
                        break
    except Exception as _e:
        print(f"[u2s] psychology merge skipped: {_e}")
    if date:
        rows = _settled(rows, "u2s", date)
    for row in rows:
        if isinstance(row, dict) and "match_date" not in row:
            row["match_date"] = date
    return rows


@app.get("/api/calibration/{date}", tags=["Foundation"])
def get_calibration(date: str):
    data, _ = store.load("calibration", date, default=[])
    return to_records(data)


@app.get("/api/win/forecast/{date}", tags=["Win"])
def get_win_forecast(date: str):
    return _with_intelligent_pass(
        "win_apex", read("win_forecast", date, WIN_FORECAST_DEFAULTS, "win"), date)


@app.get("/api/sh-gg-winner/{date}", tags=["Specials"])
def get_sh_gg_winner(date: str):
    return read("sh_gg_winner", date, SH_GG_WINNER_DEFAULTS, "shvi")


# ════════════════════════════════════════════════════════════════════════════
# WIN
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/win/psychology/{date}", tags=["Win"])
def get_win_psychology(date: str):
    return _with_intelligent_pass(
        "win_psychology", read("win_psychology", date, WIN_PSYCH_DEFAULTS, "win"), date)


@app.get("/api/win/u2s/{date}", tags=["Win"])
def get_u2s(date: str):
    return _with_intelligent_pass(
        "u2s", read("u2s_psychology", date, WIN_U2S_DEFAULTS, "u2s"), date)


@app.get("/api/win/apex/{date}", tags=["Win"])
def get_win_apex(date: str):
    # Exact-date snapshot ONLY. A request for a specific date must never
    # silently serve another date's data — the old '__latest' fallback did
    # exactly that whenever the dated file was missing. A missing dated
    # file now returns an honest empty list (existing API contract for a
    # date the pipeline hasn't produced), which the frontend renders as
    # its real-empty state.
    data, _generated_at = store.load("win_apex", date, default=None)
    if data is None:
        data = []
    rows = ensure_defaults(data, WIN_APEX_DEFAULTS)
    rows = _with_fixture_risk(rows, date)
    rows = _settled(rows, "win", date)
    return _with_intelligent_pass("win_apex", rows, date)


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
    return {
        "gg": _with_intelligent_pass("gg_precision", _settled(gg, "gg", date), date),
        "o15": _with_intelligent_pass("gg_o15", _settled(o15, "o15", date), date),
    }


@app.get("/api/gg/forensics/{date}", tags=["GG"])
def get_gg_forensics(date: str):
    return read("gg_forensics", date, GG_FORENSIC_DEFAULTS, "gg")


@app.get("/api/gg/psychology/{date}", tags=["GG"])
def get_gg_psychology(date: str):
    return read("gg_psychology", date, GG_PSYCH_DEFAULTS, "gg")


@app.get("/api/gg/supreme/{date}", tags=["GG"])
def get_gg_supreme(date: str):
    return _with_intelligent_pass(
        "gg_supreme", read("gg_supreme", date, GG_SUPREME_DEFAULTS, "gg"), date)


@app.get("/api/gg/cross-verify", tags=["GG"])
def get_gg_cross_verify():
    # This route has no date param by design: it IS the 7-day rolling GG
    # cross-verification, so it composes the last 7 DATED snapshots through
    # read_range() — the same date-scoped read every other market filter uses.
    # It must NOT read the dateless "__latest" key: main.py snapshots filter_gg
    # per date (store.save("filter_gg", d, ...)), so nothing refreshes
    # "__latest" any more and that read served one frozen payload for every
    # later date. read_range() also settles each row against its own date, so an
    # older row is graded from its own archive instead of the latest live feed.
    end = _today()
    start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    return read_range(lambda d: "filter_gg", _date_range(start, end), GG_CROSS_DEFAULTS, "gg")


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


# Gold Over 2.5 rows are NESTED ({teams:{home,away}, metrics:{...}, flags}) —
# unlike every other market's flat rows. Defaults only fill flat scalar fields;
# nested structures are preserved untouched by ensure_defaults. Verification
# identity is the flat fixture_id, which grade_row/settle_predictions already
# match on — no team-name matching needed for this market.
O25_GOLD_DEFAULTS = dict(
    fixture_id="", engine="", league="", kickoff_datetime="", kickoff_timestamp="",
    flags={},
)


@app.get("/api/over25/gold/{date}", tags=["Over 2.5"])
def get_over25_gold(date: str):
    data, _ = store.load("over25_gold", date, default=[])
    # Gold O2.5 rows were returned raw (no verification payload at all) while
    # every sibling over25 route settles with market key "o25" — the exact
    # total-goals rule (>= 3 WON / <= 2 LOST) the Gold engine predicts. Settle
    # identically to the rest of the Over 2.5 family; rows carry fixture_id so
    # finished matches resolve through the persistent archive layer.
    return _settled(ensure_defaults(data, O25_GOLD_DEFAULTS), "o25", date)


@app.get("/api/over25/apex/{date}", tags=["Over 2.5"])
def get_over25_apex(date: str):
    return _with_intelligent_pass(
        "over25_apex", read("over25_apex", date, O25_APEX_DEFAULTS, "o25"), date)


@app.get("/api/over25/forecast/{date}", tags=["Over 2.5"])
def get_over25_forecast(date: str):
    return _with_intelligent_pass(
        "over25_forecast", read("over25_forecast", date, O25_FORECAST_DEFAULTS, "o25"), date)


# ════════════════════════════════════════════════════════════════════════════
# OVER 1.5
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/over15/stage3/{date}", tags=["Over 1.5"])
def get_over15_stage3(date: str):
    return _with_intelligent_pass(
        "over15", read("over15_stage3", date, O15_STAGE3_DEFAULTS, "o15"), date)


@app.get("/api/over15/psychology/{date}", tags=["Over 1.5"])
def get_over15_psychology(date: str):
    return _with_intelligent_pass(
        "over15", read("over15_psychology", date, O15_PSYCH_DEFAULTS, "o15"), date)


@app.get("/api/over15/apex/{date}", tags=["Over 1.5"])
def get_over15_apex(date: str):
    return _with_intelligent_pass(
        "over15", read("over15_apex", date, O15_APEX_DEFAULTS, "o15"), date)


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
    return _with_intelligent_pass(
        "corners_aggregator",
        read("corners_aggregator", date, CORNER_AGG_DEFAULTS, "corners"), date)


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
        "draws": _with_intelligent_pass(
            "draw",
            _settled(ensure_defaults(draws_raw, DRAW_DEFAULTS), "draw", date),
            date),
        # HIGH PARITY LIST: expected close match. Settlement is the High-Parity
        # rule (|home - away| <= 2, user-confirmed) — a DIFFERENT condition from
        # the conventional Draw branch above (home_goals == away_goals), so
        # these rows are graded with market key "parity", never "draw".
        "parity_list": _settled(ensure_defaults(parity_raw, DRAW_DEFAULTS), "parity", date),
        "amateurs_list": ensure_defaults(amateurs_raw, DRAW_DEFAULTS),
    }


@app.get("/api/unders/{date}", tags=["Unders"])
def get_unders(date: str):
    raw, _ = store.load("unders", date, default=[[], []])
    u25_raw = raw[0] if isinstance(raw, list) and len(raw) > 0 else []
    u35_raw = raw[1] if isinstance(raw, list) and len(raw) > 1 else []
    return {
        "u25": _with_intelligent_pass(
            "unders_u25",
            _settled(ensure_defaults(u25_raw, UNDERS_DEFAULTS), "u25", date),
            date),
        # u35 was the only list in this composite payload never routed
        # through _settled(): grade_row already holds the correct branch
        # (total goals <= 3 -> WON, >= 4 -> LOST) and "u35" is already in
        # SUPPORTED_SETTLEMENT_MARKETS, so Verify stayed blank purely
        # because settlement was never invoked for this head. u25 above is
        # unchanged.
        "u35": _settled(ensure_defaults(u35_raw, UNDERS_DEFAULTS), "u35", date),
    }


# ════════════════════════════════════════════════════════════════════════════
# SOT / FHVI / SHVI
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/sot/{date}", tags=["Specials"])
def get_sot(date: str):
    # SOT carries the user's 2-check Intelligent Pass card (psych > 50,
    # under-2.5 probability > 65%) — wrapped like every other counted market.
    return _with_intelligent_pass(
        "sot", read("sot", date, SOT_DEFAULTS, "sot"), date)


@app.get("/api/fhvi/{date}", tags=["Specials"])
def get_fhvi(date: str):
    # "fhvi" (not "shvi") — FHVI is FIRST-half goals. The old "shvi" key
    # graded it with the second-half branch: wrong half of the match.
    return _with_intelligent_pass(
        "fhvi", read("fhvi", date, FHVI_DEFAULTS, "fhvi"), date)


@app.get("/api/shvi/{date}", tags=["Specials"])
def get_shvi(date: str):
    # Strictly keyed on (shvi, date) — this is the fix for the old
    # "shows real data but wrong date" bug. No undated fallback exists here.
    return _with_intelligent_pass(
        "shvi", read("shvi", date, SHVI_DEFAULTS, "shvi"), date)


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


def _fixture_name_index() -> dict:
    """P0-5: disk-only {fixture_id: "Team A vs Team B"} resolver.

    `incoming_predictions.json` is keyed by fixture id and its values are pick
    lists, so the feed itself carries no team names — the route used to fill
    `fixture` with the id, which the Incoming page rendered next to the
    `fixture_id` column as two identical numbers.

    Every id the incoming feed can contain is ALREADY present locally in the
    in-play cache (canonical "Home vs Away" name), the danger audit and the
    aggregator report (both carry a `fixture` name field), so the name is
    resolved at read time with zero extra SportMonks calls and without
    touching any engine, file or file schema.
    """
    index = {}

    # 1. In-play cache — highest priority: `name` is the canonical fixture name.
    live = _read_json(os.path.join(DATA_DIR, "live_inplay_cache.json"), {})
    live_rows = live.get("data") if isinstance(live, dict) else None
    for fx in live_rows or []:
        if not isinstance(fx, dict):
            continue
        fid, name = fx.get("id"), fx.get("name")
        if fid is not None and name:
            index.setdefault(str(fid), str(name))

    # 2. Danger audit + 3. aggregator report — both carry `fixture_id`+`fixture`.
    for fname in ("danger_audit.json", "aggregator_report.json"):
        raw = _read_json(os.path.join(DATA_DIR, fname), [])
        if isinstance(raw, dict):
            raw = list(raw.values())
        for row in raw if isinstance(raw, list) else []:
            if not isinstance(row, dict):
                continue
            fid, name = row.get("fixture_id"), row.get("fixture")
            if fid is not None and name:
                index.setdefault(str(fid), str(name))

    return index


def _incoming_rows_from_disk():
    raw = _read_json(os.path.join(DATA_DIR, "incoming_predictions.json"), {})
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    names = _fixture_name_index()
    rows = []
    for fixture_id, value in raw.items():
        if isinstance(value, list):
            # Resolve the real name; fall back to the id when nothing local
            # knows this fixture (never invents a name).
            fid = str(fixture_id)
            rows.append({
                "fixture_id": fid,
                "fixture": names.get(fid) or fid,
                "picks": value,
            })
        elif isinstance(value, dict):
            picks = value.get("picks", [])
            fid = str(value.get("fixture_id", fixture_id))
            stored = value.get("fixture")
            # Priority: local name index -> a stored name that is not just a
            # copy of the id -> the id itself.
            resolved = names.get(fid)
            if not resolved and stored and str(stored) != fid:
                resolved = str(stored)
            rows.append({
                "fixture_id": fid,
                "fixture": resolved or fid,
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
    board = _read_json(os.path.join(DATA_DIR, "validation_board.json"), {})
    alert_list = list(alerts.values()) if isinstance(alerts, dict) else alerts
    if not isinstance(alert_list, list):
        alert_list = []
    # The frontend LiveValidationBoard expects `total_live`, `cycle` and a real
    # `matches` list. Those previously defaulted to hardcoded empties because
    # the stage-2 console board was printed but never persisted; it is now
    # written to validation_board.json by run_live_validator_once().
    return {
        "cycle": board.get("cycle", 1) if isinstance(board, dict) else 1,
        "total_live": board.get("total_live", 0) if isinstance(board, dict) else 0,
        "total_tracked": (
            board.get("total_tracked")
            if isinstance(board, dict) and board.get("total_tracked") is not None
            else (len(state) if isinstance(state, (list, dict)) else 0)
        ),
        "alerts": alert_list,
        "matches": board.get("matches", []) if isinstance(board, dict) else [],
    }


def _live_index() -> dict:
    """
    Build a {fixture_id: {score, minute, state, is_finished}} index for the
    three live read endpoints so each row can carry additive live context.

    Sources (P0-4), all local — no new SportMonks calls:
      1. get_live_scores_cached()  → the shared 2-minute in-play disk cache
        (data/live_inplay_cache.json); fresh entries overwrite the archive.
      2. extract_match_data()      → the existing settlement standardizer, so
        score/state/minute come out in exactly the shape settlement already
        uses everywhere else.
      3. load_finished_archive(_today()) → keeps a finished fixture reported
        after it leaves the transient in-play feed (FT rows).

    Minute follows the LIVE_SCANNER stage-6 extract_minute() pattern: time →
    state → periods → events → kickoff-elapsed fallback (HT → 45',
    second-half → +45).
    """
    idx: dict = {}
    # Finished layer first (lower priority): a fixture that has already ended
    # is reported from the archive even when it is no longer in the live feed.
    try:
        for fid, md in (load_finished_archive(_today()) or {}).items():
            md = md if isinstance(md, dict) else {}
            idx[str(fid)] = {
                "score": md.get("ft_score") or "0-0",
                "minute": int(md.get("minute", 0) or 0),
                "state": "FT" if md.get("is_finished") else "",
                "is_finished": bool(md.get("is_finished")),
            }
    except Exception:
        pass
    try:
        live_rows = get_live_scores_cached() or []
    except Exception:
        live_rows = []
    for fx in live_rows:
        if not isinstance(fx, dict):
            continue
        fid = str(fx.get("id") or "")
        if not fid:
            continue
        try:
            md = extract_match_data(fx)
        except Exception:
            continue

        # ---- minute (existing local _live_minute approach: time.minute →
        # state.minute → periods[].minutes, with the canonical half mapping
        # HT → 45 and second-half → +45, then the kickoff-elapsed fallback) ---
        st_obj = fx.get("state") if isinstance(fx.get("state"), dict) else {}
        sd_up = str(st_obj.get("state") or st_obj.get("short_name") or "").upper()
        periods = fx.get("periods") if isinstance(fx.get("periods"), list) else []
        active = next((p for p in periods if isinstance(p, dict) and p.get("ticking")), None)
        found = [0]
        if fx.get("time") and isinstance(fx.get("time"), dict):
            found.append(int(fx["time"].get("minute", 0) or 0))
        found.append(int(st_obj.get("minute", 0) or 0))
        for p in periods:
            if not isinstance(p, dict):
                continue
            m = (p.get("time", {}).get("minute") if isinstance(p.get("time"), dict) else None) \
                or p.get("minute") or p.get("length")
            if m:
                found.append(int(m))
        if fx.get("events"):
            emins = [int(e.get("minute", 0)) for e in fx["events"] if e.get("minute")]
            if emins:
                found.append(max(emins))
        if fx.get("starting_at_timestamp"):
            now_ts = int(datetime.now(timezone.utc).timestamp())
            elapsed = (now_ts - int(fx["starting_at_timestamp"])) // 60
            if 0 < elapsed <= 50:
                found.append(elapsed)
            elif 60 < elapsed <= 110:
                found.append(elapsed - 15)
            elif elapsed > 110:
                found.append(90)
        if sd_up == "HT":
            minute = 45  # canonical half-time minute
        elif active is not None:
            cf = int(active.get("counts_from", 0) or 0)
            if "2ND" in str(active.get("description", "")).upper() and cf < 45:
                cf = 45  # the second half always counts from minute 45
            minute = cf + int(active.get("minutes", 0) or 0)
        else:
            minute = max(found) if found else 0

        entry = {
            "score": md.get("ft_score") or "0-0",
            "minute": minute,
            "state": (fx.get("state") or {}).get("state", "") if isinstance(fx.get("state"), dict) else "",
            "is_finished": bool(md.get("is_finished")),
        }
        idx[fid] = entry  # fresh live rows overwrite the finished layer
    return idx


_LIVE_INDEX_CACHE = {"sig": None, "idx": {}}


def _live_index_cached() -> dict:
    """Read-time memo for _live_index(): one rebuild per cache-file generation
    instead of once per row-serving request. The signature is the in-play
    cache file's (mtime_ns, size) — identical to settlement's archive-cache
    invalidation. Falls back to rebuilding when the stat fails (missing file,
    unreadable dir) so a changed feed is never served stale."""
    raw = os.path.join(DATA_DIR, "live_inplay_cache.json")
    try:
        st = os.stat(raw)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if _LIVE_INDEX_CACHE["sig"] != sig or not _LIVE_INDEX_CACHE["idx"]:
        try:
            _LIVE_INDEX_CACHE["idx"] = _live_index()
        except Exception:
            _LIVE_INDEX_CACHE["idx"] = {}
        _LIVE_INDEX_CACHE["sig"] = sig
    return _LIVE_INDEX_CACHE["idx"]


@app.get("/api/live/incoming", tags=["Live"])
def get_live_incoming():
    rows = _incoming_rows_from_disk()
    live_idx = _live_index_cached()
    for r in rows:
        if isinstance(r, dict):
            r["live"] = live_idx.get(str(r.get("fixture_id") or ""))
    return rows


@app.get("/api/live/danger", tags=["Live"])
def get_live_danger():
    rows = _read_json(os.path.join(DATA_DIR, "danger_audit.json"), [])
    if isinstance(rows, list):
        live_idx = _live_index_cached()
        for r in rows:
            if isinstance(r, dict):
                r["live"] = live_idx.get(str(r.get("fixture_id") or ""))
    return rows


@app.get("/api/live/aggregator", tags=["Live"])
def get_live_aggregator():
    rows = _read_json(os.path.join(DATA_DIR, "aggregator_report.json"), [])
    if isinstance(rows, list):
        live_idx = _live_index_cached()
        for r in rows:
            if isinstance(r, dict):
                r["live"] = live_idx.get(str(r.get("fixture_id") or ""))
    return rows


@app.get("/api/live/orchestrator", tags=["Live"])
def get_live_orchestrator():
    default_board = {"session": "", "cycle": 0, "total_live": 0, "total_db": 0, "matches": []}
    return _read_json(os.path.join(OUTPUT_DIR, "orchestrator_board.json"), default_board)


@app.get("/api/live/alerts", tags=["Live"])
def get_live_alerts(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
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
                    row = json.loads(line)
                    if row.get("user_id") not in (None, user["user_id"]):
                        continue
                    rows.append(row)
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
# FILTER ENDPOINTS — two paths, one contract.
#
# 1. BASELINE (the default request: public preset + default odds band + no
#    drawer edits) reads the risk-level matrix main.py precomputes
#    (filter_win__safe / __balanced / __aggressive, filter_over25__banker /
#    __balanced / __aggressive, filter_gg) — byte-identical rows, zero compute.
#
# 2. ANYTHING ELSE (tipster/advanced sliders, a non-default odds corridor, a
#    non-default GG risk preset, or any drawer threshold) runs the SAME
#    existing FILTER engine over the SAME dated artifacts via
#    api/weekly_filter_live.live_query(), with persist=False so a click can
#    never overwrite a pipeline artifact. See that module for the full
#    control→gate mapping. No new prediction maths, no new API calls.
# ════════════════════════════════════════════════════════════════════════════
_WIN_RISK_LEVELS = {"safe", "balanced", "aggressive"}
_O25_RISK_LEVELS = {"banker", "balanced", "aggressive"}


def _finalize_live_rows(rows, defaults, market_type, identity=None):
    """Give live-computed rows exactly the same post-processing the snapshot
    path applies: shape guard, ensure_defaults, per-date settlement. Live rows
    already carry their own `match_date` (stamped by live_query)."""
    rows = _guard_filter_rows(rows, identity)
    grouped = {}
    order = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("match_date") or "")
        if date not in grouped:
            grouped[date] = []
            order.append(date)
        grouped[date].append(row)
    out = []
    for date in order:
        group = ensure_defaults(grouped[date], defaults)
        group = _with_fixture_risk(group, date or None)   # cup/friendly labels
        group = _settled(group, market_type, date or None)
        out.extend(group)
    return out


@app.get("/api/filter/gg/weekly", tags=["Filters"])
def filter_gg_weekly(
    filters: dict = Depends(gg_filter_params),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    """
    7-day rolling GG cross-verification.

    Range supplied (start_date + end_date) → every date in the range.
    No range → the last 7 dates ending today (or anchor_date).

    Baseline request → the precomputed dated snapshots (unchanged behaviour).
    Any other combination of mode / risk preset / odds corridor / drawer
    thresholds → the live GG precision filter over the same dated artifacts.
    """
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    elif anchor_date or start_date:
        dates = [anchor_date or start_date]
    else:
        end = _today()
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        dates = _date_range(start, end)

    if is_baseline(filters):
        return read_range(lambda d: "filter_gg", dates, GG_CROSS_DEFAULTS, "gg")
    return _finalize_live_rows(
        live_query("gg", dates, filters), GG_CROSS_DEFAULTS, "gg")


@app.get("/api/filter/gg/{date}", tags=["Filters"])
def filter_gg_single(date: str, filters: dict = Depends(gg_filter_params)):
    # GG is a dated snapshot exactly like WIN / O2.5 (main.py calls
    # store.save("filter_gg", d, ...) for the run's date), so the baseline
    # request reads ONLY the requested date's snapshot. A date with no snapshot
    # honestly returns []. Any non-baseline control combination computes the
    # live filter for that one date from the same dated artifacts.
    if is_baseline(filters):
        return read("filter_gg", date, GG_CROSS_DEFAULTS, "gg")
    return _finalize_live_rows(
        live_query("gg", [date], filters), GG_CROSS_DEFAULTS, "gg")


@app.get("/api/filter/win/weekly", tags=["Filters"])
def filter_win_weekly(
    filters: dict = Depends(win_filter_params),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    # Walks every date in [start_date, end_date] (or a single anchor_date) and
    # concatenates that day's picks; dates the pipeline hasn't reached simply
    # contribute 0 rows. Baseline → the precomputed risk snapshot; otherwise the
    # live WIN filter with the request's mode/risk/odds/drawer values.
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    if is_baseline(filters):
        risk = filters["risk_level"] if filters["risk_level"] in _WIN_RISK_LEVELS else "balanced"
        return read_range(lambda d: f"filter_win__{risk}", dates, WIN_FORECAST_DEFAULTS, "win",
                          identity="win")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("win", dates, filters), WIN_FORECAST_DEFAULTS, "win", identity="win")


@app.get("/api/filter/win/{date}", tags=["Filters"])
def filter_win_single(date: str, filters: dict = Depends(win_filter_params)):
    if is_baseline(filters):
        risk = filters["risk_level"] if filters["risk_level"] in _WIN_RISK_LEVELS else "balanced"
        return read(f"filter_win__{risk}", date, WIN_FORECAST_DEFAULTS, "win",
                    identity="win")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("win", [date], filters), WIN_FORECAST_DEFAULTS, "win", identity="win")


@app.get("/api/filter/over25/weekly", tags=["Filters"])
def filter_over25_weekly(
    filters: dict = Depends(o25_filter_params),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    if is_baseline(filters):
        risk = filters["risk_level"] if filters["risk_level"] in _O25_RISK_LEVELS else "balanced"
        return read_range(lambda d: f"filter_over25__{risk}", dates, O25_FORECAST_DEFAULTS, "o25",
                          identity="o25")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("o25", dates, filters), O25_FORECAST_DEFAULTS, "o25", identity="o25")


@app.get("/api/filter/over25/{date}", tags=["Filters"])
def filter_over25_single(date: str, filters: dict = Depends(o25_filter_params)):
    if is_baseline(filters):
        risk = filters["risk_level"] if filters["risk_level"] in _O25_RISK_LEVELS else "balanced"
        return read(f"filter_over25__{risk}", date, O25_FORECAST_DEFAULTS, "o25",
                    identity="o25")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("o25", [date], filters), O25_FORECAST_DEFAULTS, "o25", identity="o25")


@app.get("/api/filter/win/precision/weekly", tags=["Filters"])
def filter_win_precision_weekly(
    filters: dict = Depends(win_precision_params),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    anchor_date: Optional[str] = None,
):
    # Win Cross-Check: same controls as /weekly/win, defaulting to the SAFE
    # preset (filter_win__safe) it has always read.
    if start_date and end_date:
        dates = _date_range(start_date, end_date)
    else:
        dates = [anchor_date or start_date or _today()]
    if is_baseline(filters):
        return read_range(lambda d: "filter_win__safe", dates, WIN_FORECAST_DEFAULTS, "win",
                          identity="win")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("win", dates, filters, risk_default="safe"),
        WIN_FORECAST_DEFAULTS, "win", identity="win")


@app.get("/api/filter/win/precision/{date}", tags=["Filters"])
def filter_win_precision_single(date: str, filters: dict = Depends(win_precision_params)):
    if is_baseline(filters):
        return read("filter_win__safe", date, WIN_FORECAST_DEFAULTS, "win",
                    identity="win")  # FILTER SHAPE GUARD (09-10 foreign rows)
    return _finalize_live_rows(
        live_query("win", [date], filters, risk_default="safe"),
        WIN_FORECAST_DEFAULTS, "win", identity="win")


# ════════════════════════════════════════════════════════════════════════════
# FIXTURE RISK LABELS (cup / friendly) — read-only audit of the per-date
# classification the pipeline writes (main.py PHASE 0b). The same labels are
# already stamped onto every picks row by read()/read_range(); this route exists
# for screens that only know a fixture id (team intelligence, deep links) and
# for verifying coverage of a date.
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/fixtures/risk/{date}", tags=["Foundation"])
def get_fixture_risk_labels(date: str):
    rows, generated_at = store.load("fixture_risk", date, default=[])
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    cup = sum(1 for r in rows if r.get("is_cup"))
    friendly = sum(1 for r in rows if r.get("is_friendly"))
    unknown = sum(1 for r in rows if r.get("risk_level") == "unknown")
    return {
        "date": date,
        "generated_at": generated_at,
        "count": len(rows),
        "cup": cup,
        "friendly": friendly,
        "unknown": unknown,
        "coverage": (len(rows) - unknown) / len(rows) if rows else 0.0,
        "fixtures": rows,
    }


# ════════════════════════════════════════════════════════════════════════════
# TEAM INTELLIGENCE PAGE (display/audit only — pure reuse of the same
# per-date cache snapshots the market pages already read; ZERO new API calls)
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/team/{team_name}/intelligence/{date}", tags=["Foundation"])
def get_team_intelligence(
    team_name: str,
    date: str,
    market: Optional[str] = Query(
        None,
        description="Optional market key — when present the report is a "
        "SINGLE-MARKET audit of that pick (e.g. win, over25, gg, u2s, "
        "corners, draw, unders, over15, fhvi, shvi). Omitted → the legacy "
        "all-markets composition.",
    ),
):
    if intelligent_pass is None:
        raise HTTPException(status_code=503, detail="Intelligent Pass evaluator unavailable")
    try:
        report = intelligent_pass.get_team_intelligence(team_name, date, market=market)
        # Additive: the same cup/friendly label the market pages carry, so the
        # drill-down report warns about the fixture it is auditing too.
        try:
            _with_fixture_risk([report], date)
        except Exception:
            pass
        return report
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Team intelligence evaluation failed")
