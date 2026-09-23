"""
api/weekly_filter_live.py — the Weekly page's filter controls, wired to the engines.

THE BUG THIS FIXES
------------------
`/weekly/*` has always sent its full control set with every request:

    mode (public | tipster | advanced)  ·  risk_level  ·  odds_band
    MIN PROBABILITY / MAX TOTAL PARITY / MIN HOME-AWAY GG / MIN H2H GG /
    MAX TABLE DISTANCE / MIN-MAX GG ODDS / STRICT PARITY LOCK      (GG drawer)
    MIN FORM-VENUE-H2H / OPP CONCEDED / OPP LOSSES / PARITY / ODDS /
    NO-DRAW / STRICT MODE                                           (WIN drawer)
    MIN POISSON / MIN VOTES / MAX POS GAP / MIN H2H OVERS / ODDS   (O2.5 drawer)

but the routes read ONLY the precomputed snapshot and ignored `mode`, the odds
corridor and every drawer value — so the buttons looked inert while the weekly
data (dates) loaded. The engines were never missing the maths: the
`apply_tipster_filter` / `apply_over_tipster_filter` sliders, the GG gate
config and the public odds bands all already existed and were simply never
called with the user's values.

WHAT THIS MODULE DOES
---------------------
1. Parses/validates the controls (`gg_filter_params` / `win_filter_params` /
   `o25_filter_params` — FastAPI dependencies) into one normalised dict.
2. `is_baseline()` — true for the SHIPPED request (public preset, default odds
   band, no drawer edits). The caller then keeps reading the precomputed
   snapshot: byte-identical rows, zero compute, no latency change.
3. `live_query()` — for anything else, runs the SAME existing FILTER functions
   over the SAME dated artifacts, per date, with `persist=False` so a slider
   move can never overwrite a pipeline artifact. A short TTL cache keeps
   repeated moves cheap.
4. `narrow_rows()` — in Public mode the preset filter runs first (exactly as
   the pipeline did) and the drawer values then narrow the surviving rows with
   the same >= / <= semantics, so a control is never silently ignored.

NO new prediction mathematics and NO new API calls: every gate is an existing
gate; every value is a real dated value or is treated as unevaluable.
"""

import json
import math
import time
from typing import Optional

# ── modes ─────────────────────────────────────────────────────────────────────
PUBLIC = "public"
TIPSTER_MODES = ("tipster", "advanced")

# ── risk presets / odds corridors (the exact sets the engines accept) ─────────
WIN_RISKS = ("safe", "balanced", "aggressive")
O25_RISKS = ("banker", "balanced", "aggressive")
GG_RISKS = ("banker", "balanced", "aggressive")

WIN_BANDS = ("1.30-1.60", "1.40-1.90", "1.80-2.40")
O25_BANDS = ("1.30-1.60", "1.50-1.85", "1.80-2.20")
GG_BANDS = ("1.40-1.75", "1.50-1.85", "1.80-2.20")

WIN_DEFAULT_BAND = "1.40-1.90"     # apply_public_filter's own default
O25_DEFAULT_BAND = "1.50-1.85"     # apply_over_public_filter's own default

# ── value clamps (a slider can never ask for an impossible value) ────────────
_ODDS = (1.01, 100.0)
_PROB = (0.0, 100.0)
_COUNT = (0, 50)
_VOTES = (0, 20)
_GAP = (0, 200)
_PARITY = (0.0, 50.0)


def _clamp_num(value, bounds):
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return max(float(bounds[0]), min(float(bounds[1]), f))


def _clamp_int(value, bounds):
    f = _clamp_num(value, bounds)
    return None if f is None else int(f)


def _band(band, allowed, default):
    """Normalise an odds-corridor string to the market's own band set."""
    if not band:
        return default
    band = str(band).strip()
    return band if band in allowed else default


def parse_band(band):
    """'1.50-1.85' -> (1.5, 1.85) — the GG corridor has no engine band table."""
    try:
        lo, hi = str(band).split("-", 1)
        return float(lo), float(hi)
    except (TypeError, ValueError):
        return None, None


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI dependencies — one per market, mirroring each Weekly page's config
# ══════════════════════════════════════════════════════════════════════════════
def gg_filter_params(
    mode: str = PUBLIC,
    risk_level: str = "banker",
    odds_band: Optional[str] = None,
    min_prob: Optional[float] = None,
    max_parity: Optional[float] = None,
    min_home_gg5: Optional[float] = None,
    min_away_gg5: Optional[float] = None,
    min_h2h_gg: Optional[float] = None,
    pos_diff_max: Optional[float] = None,
    min_gg_odds: Optional[float] = None,
    max_gg_odds: Optional[float] = None,
    strict_mode: Optional[bool] = None,
) -> dict:
    p = _normalise(mode, "gg")
    p["risk_level"] = risk_level if risk_level in GG_RISKS else "banker"
    p["odds_band"] = _band(odds_band, GG_BANDS, None)
    for key, bounds, caster in (("min_prob", _PROB, _clamp_num),
                                ("max_parity", _PARITY, _clamp_num),
                                ("min_home_gg5", _COUNT, _clamp_num),
                                ("min_away_gg5", _COUNT, _clamp_num),
                                ("min_h2h_gg", _COUNT, _clamp_num),
                                ("pos_diff_max", _GAP, _clamp_num),
                                ("min_gg_odds", _ODDS, _clamp_num),
                                ("max_gg_odds", _ODDS, _clamp_num)):
        clamped = caster(locals()[key], bounds)
        if clamped is not None:
            p["overrides"][key] = clamped
    if strict_mode is not None:
        p["overrides"]["strict_mode"] = bool(strict_mode)
    return p


def win_filter_params(
    mode: str = PUBLIC,
    risk_level: str = "balanced",
    odds_band: Optional[str] = None,
    min_form_wins: Optional[float] = None,
    min_venue_wins: Optional[float] = None,
    min_h2h_wins: Optional[float] = None,
    min_opp_conceded: Optional[float] = None,
    min_opp_losses: Optional[float] = None,
    min_parity_gap: Optional[float] = None,
    min_odds: Optional[float] = None,
    max_odds: Optional[float] = None,
    require_no_draw: Optional[bool] = None,
    strict_mode: Optional[bool] = None,
) -> dict:
    p = _normalise(mode, "win")
    p["risk_level"] = risk_level if risk_level in WIN_RISKS else "balanced"
    p["odds_band"] = _band(odds_band, WIN_BANDS, WIN_DEFAULT_BAND)
    for key, bounds, caster in (("min_form_wins", _COUNT, _clamp_num),
                                ("min_venue_wins", _COUNT, _clamp_num),
                                ("min_h2h_wins", _COUNT, _clamp_num),
                                ("min_opp_conceded", _COUNT, _clamp_num),
                                ("min_opp_losses", _COUNT, _clamp_num),
                                ("min_parity_gap", _PROB, _clamp_num),
                                ("min_odds", _ODDS, _clamp_num),
                                ("max_odds", _ODDS, _clamp_num)):
        clamped = caster(locals()[key], bounds)
        if clamped is not None:
            p["overrides"][key] = clamped
    if require_no_draw is not None:
        p["overrides"]["require_no_draw"] = bool(require_no_draw)
    if strict_mode is not None:
        p["overrides"]["strict_mode"] = bool(strict_mode)
    return p


def win_precision_params(
    mode: str = PUBLIC,
    risk_level: str = "safe",
    odds_band: Optional[str] = None,
    min_form_wins: Optional[float] = None,
    min_venue_wins: Optional[float] = None,
    min_h2h_wins: Optional[float] = None,
    min_opp_conceded: Optional[float] = None,
    min_opp_losses: Optional[float] = None,
    min_parity_gap: Optional[float] = None,
    min_odds: Optional[float] = None,
    max_odds: Optional[float] = None,
    require_no_draw: Optional[bool] = None,
    strict_mode: Optional[bool] = None,
) -> dict:
    """Win Cross-Check uses the same drawer and the SAME snapshot key as the
    Win page's SAFE preset (filter_win__safe), so its default risk is `safe`
    (not `balanced`). Every other control behaves identically to /weekly/win."""
    return win_filter_params(
        mode=mode, risk_level=risk_level, odds_band=odds_band,
        min_form_wins=min_form_wins, min_venue_wins=min_venue_wins,
        min_h2h_wins=min_h2h_wins, min_opp_conceded=min_opp_conceded,
        min_opp_losses=min_opp_losses, min_parity_gap=min_parity_gap,
        min_odds=min_odds, max_odds=max_odds,
        require_no_draw=require_no_draw, strict_mode=strict_mode,
    )


def o25_filter_params(
    mode: str = PUBLIC,
    risk_level: str = "balanced",
    odds_band: Optional[str] = None,
    min_poisson: Optional[float] = None,
    min_votes: Optional[float] = None,
    max_pos_gap: Optional[float] = None,
    min_h2h_overs: Optional[float] = None,
    min_odds: Optional[float] = None,
    max_odds: Optional[float] = None,
) -> dict:
    p = _normalise(mode, "o25")
    p["risk_level"] = risk_level if risk_level in O25_RISKS else "balanced"
    p["odds_band"] = _band(odds_band, O25_BANDS, O25_DEFAULT_BAND)
    for key, bounds, caster in (("min_poisson", _PROB, _clamp_num),
                                ("min_votes", _VOTES, _clamp_int),
                                ("max_pos_gap", _GAP, _clamp_num),
                                ("min_h2h_overs", _COUNT, _clamp_num),
                                ("min_odds", _ODDS, _clamp_num),
                                ("max_odds", _ODDS, _clamp_num)):
        clamped = caster(locals()[key], bounds)
        if clamped is not None:
            p["overrides"][key] = clamped
    return p


def _normalise(mode, market):
    mode = str(mode or PUBLIC).strip().lower()
    if mode not in (PUBLIC,) + TIPSTER_MODES:
        # "odds_band" / anything unknown from an older client = preset view
        mode = PUBLIC
    return {"market": market, "mode": mode, "risk_level": None,
            "odds_band": None, "overrides": {}}


# ══════════════════════════════════════════════════════════════════════════════
# Baseline detection — keep the shipped zero-compute snapshot path for the
# default request; compute only for the user's own choices.
# ══════════════════════════════════════════════════════════════════════════════
def is_baseline(params: dict) -> bool:
    if params.get("mode") != PUBLIC or params.get("overrides"):
        return False
    band = params.get("odds_band")
    if params.get("market") == "gg":
        return not band and params.get("risk_level") in (None, "banker")
    default_band = WIN_DEFAULT_BAND if params["market"] == "win" else O25_DEFAULT_BAND
    return band in (None, "", default_band)


# ══════════════════════════════════════════════════════════════════════════════
# Mapping tables — drawer key -> the engine's own keyword / row field
# ══════════════════════════════════════════════════════════════════════════════
WIN_TIPSTER_KWARGS = {
    "min_form_wins": "min_overall_wins",   # apply_tipster_filter's own name
    "min_venue_wins": "min_venue_wins",
    "min_h2h_wins": "min_h2h_wins",
    "min_opp_conceded": "min_opp_conceded",
    "min_opp_losses": "min_opp_losses",
    "min_parity_gap": "min_parity_gap",
    "min_odds": "min_odds",
    "max_odds": "max_odds",
    "require_no_draw": "require_no_draw",
    "strict_mode": "strict_mode",
}

O25_TIPSTER_KWARGS = {
    "min_poisson": "min_poisson",
    "min_votes": "min_votes",
    "max_pos_gap": "max_pos_gap",
    "min_h2h_overs": "min_h2h_overs",
    "min_odds": "min_odds",
    "max_odds": "max_odds",
}

GG_CFG_KEYS = {
    "min_prob": "min_probability",
    "min_home_gg5": "home_gg_side_min",
    "min_away_gg5": "away_gg_side_min",
    "min_h2h_gg": "h2h_gg_min",
    "pos_diff_max": "pos_diff_max",
}

# Public-mode narrowing: drawer key -> (row field, comparison).
WIN_NARROW = {
    "min_form_wins": ("last_5_wins_overall", "min"),
    "min_venue_wins": ("last_5_wins_at_venue", "min"),
    "min_h2h_wins": ("h2h_wins_last_5", "min"),
    "min_opp_conceded": ("opp_last_5_conceded_raw", "min"),
    "min_opp_losses": ("opp_last_5_losses", "min"),
    "min_parity_gap": ("parity_score", "min"),
    "min_odds": ("win_odds", "min"),
    "max_odds": ("win_odds", "max"),
    "require_no_draw": ("last_3_no_draw_BOTH", "is_true"),
}
O25_NARROW = {
    "min_poisson": ("poisson_over_prob_num", "min"),
    "min_votes": ("council_votes", "split_min"),
    "max_pos_gap": ("pos_gap", "max"),
    "min_h2h_overs": ("h2h_overs_last_5", "min"),
    "min_odds": ("o25_odds", "min"),
    "max_odds": ("o25_odds", "max"),
}

# GG risk presets. The GG engine has no risk table of its own, so the presets
# are expressed ONLY with values/mechanisms that already exist in this repo:
#   banker     -> the filter's own USER_FILTER defaults with every gate strict
#                 (exactly the precomputed `filter_gg` snapshot, so the default
#                  page load stays byte-identical),
#   balanced   -> the forensics auditor's own RULE_MIN_PROB (55.0), strict,
#   aggressive -> the same 55.0 floor with the WIN tipster filter's soft rule
#                 (one gate may fail).
GG_PRESETS = {
    "banker": ({"min_probability": 60.0}, True),
    "balanced": ({"min_probability": 55.0}, True),
    "aggressive": ({"min_probability": 55.0}, False),
}



# ══════════════════════════════════════════════════════════════════════════════
# Row helpers
# ══════════════════════════════════════════════════════════════════════════════
def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("true", "1", "yes")


def _json_safe(rows):
    """numpy scalars -> python, non-finite floats -> None (JSON has no NaN)."""
    try:
        import numpy as _np
    except Exception:                                    # pragma: no cover
        _np = None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        clean = {}
        for key, value in row.items():
            if _np is not None and isinstance(value, _np.generic):
                value = value.item()
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            clean[key] = value
        out.append(clean)
    return out


def _stamp(rows, date):
    for row in rows:
        if isinstance(row, dict):
            row["match_date"] = date
    return rows


def narrow_rows(rows, market, overrides):
    """Apply the drawer's thresholds to already-preset-filtered rows.

    A row whose evaluated field is missing is EXCLUDED — the same zero-
    fabrication rule the engines use: no operand, no verdict.
    """
    spec = WIN_NARROW if market == "win" else O25_NARROW
    active = [(field, op, overrides[canonical])
              for canonical, (field, op) in spec.items()
              if canonical in overrides and overrides[canonical] is not None]
    if not active:
        return rows
    kept = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        keep = True
        for field, op, bound in active:
            raw = row.get(field)
            if op == "is_true":
                if not _truthy(raw):
                    keep = False
                    break
                continue
            got = _num(str(raw).split("/")[0]) if op == "split_min" else _num(raw)
            if got is None:
                keep = False
                break
            if op == "min" and got < bound:
                keep = False
                break
            if op == "max" and got > bound:
                keep = False
                break
        if keep:
            kept.append(row)
    return kept



# ══════════════════════════════════════════════════════════════════════════════
# Live engine execution (lazy imports: the API boots without pandas and the
# zero-compute baseline never pays for it)
# ══════════════════════════════════════════════════════════════════════════════
def _live_gg(dates, params):
    from FILTER.gg_precision_filter import run_gg_precision_filter

    overrides = params.get("overrides") or {}
    preset_cfg, preset_strict = GG_PRESETS.get(
        params.get("risk_level") or "banker", GG_PRESETS["banker"])
    cfg_overrides = {GG_CFG_KEYS[k]: v for k, v in overrides.items() if k in GG_CFG_KEYS}
    for key, value in preset_cfg.items():
        cfg_overrides.setdefault(key, value)
    strict_mode = bool(overrides["strict_mode"]) if "strict_mode" in overrides else preset_strict
    min_odds = overrides.get("min_gg_odds")
    max_odds = overrides.get("max_gg_odds")
    if min_odds is None and max_odds is None and params.get("odds_band"):
        min_odds, max_odds = parse_band(params["odds_band"])

    rows = []
    for date in dates:
        produced = run_gg_precision_filter(
            date, cfg_overrides=cfg_overrides,
            max_parity=overrides.get("max_parity"), strict_mode=strict_mode,
            min_gg_odds=min_odds, max_gg_odds=max_odds, persist=False,
        ) or []
        rows.extend(_stamp(produced, date))
    return rows


def _live_win(dates, params, risk_default="balanced"):
    from FILTER.win_filter_service import run_win_filter_service

    overrides = params.get("overrides") or {}
    if params.get("mode") in TIPSTER_MODES:
        kwargs = {engine_key: overrides[canonical]
                  for canonical, engine_key in WIN_TIPSTER_KWARGS.items()
                  if canonical in overrides}
        # The corridor buttons are visible in Tipster mode too, so an untouched
        # band must still narrow the slider result (the tipster filter's own
        # min_odds/max_odds). Explicit drawer odds always win over the band.
        if "min_odds" not in overrides and "max_odds" not in overrides and params.get("odds_band"):
            band_min, band_max = parse_band(params["odds_band"])
            if band_min is not None and band_max is not None:
                kwargs.setdefault("min_odds", band_min)
                kwargs.setdefault("max_odds", band_max)
        rows = []
        for date in dates:
            produced = run_win_filter_service(date, mode="tipster", persist=False, **kwargs) or []
            rows.extend(_stamp(produced, date))
        return rows

    risk = params.get("risk_level") or risk_default
    band = params.get("odds_band") or WIN_DEFAULT_BAND
    rows = []
    for date in dates:
        produced = run_win_filter_service(date, mode="public", persist=False,
                                          risk_level=risk, odds_band=band) or []
        rows.extend(_stamp(produced, date))
    return narrow_rows(rows, "win", overrides)


def _live_o25(dates, params, risk_default="balanced"):
    from FILTER.over25_risk_filter import run_over25_filter_aggregator

    overrides = params.get("overrides") or {}
    if params.get("mode") in TIPSTER_MODES:
        kwargs = {engine_key: overrides[canonical]
                  for canonical, engine_key in O25_TIPSTER_KWARGS.items()
                  if canonical in overrides}
        # Same corridor rule as WIN: a band with untouched drawer odds still
        # narrows the tipster result; explicit drawer odds win.
        if "min_odds" not in overrides and "max_odds" not in overrides and params.get("odds_band"):
            band_min, band_max = parse_band(params["odds_band"])
            if band_min is not None and band_max is not None:
                kwargs.setdefault("min_odds", band_min)
                kwargs.setdefault("max_odds", band_max)
        rows = []
        for date in dates:
            produced = run_over25_filter_aggregator(date, mode="tipster",
                                                    persist=False, **kwargs) or []
            rows.extend(_stamp(produced, date))
        return rows

    risk = params.get("risk_level") or risk_default
    band = params.get("odds_band") or O25_DEFAULT_BAND
    rows = []
    for date in dates:
        produced = run_over25_filter_aggregator(date, mode="public", persist=False,
                                                 risk_level=risk, odds_band=band) or []
        rows.extend(_stamp(produced, date))
    return narrow_rows(rows, "o25", overrides)


# ══════════════════════════════════════════════════════════════════════════════
# Short TTL cache (a 7-day range re-reads 7 dated artifacts per request)
# ══════════════════════════════════════════════════════════════════════════════
_CACHE_TTL_SEC = 90
_CACHE_MAX = 64
_CACHE: dict = {}


def _cache_key(market, dates, params, risk_default):
    payload = {
        "market": market,
        "dates": list(dates),
        "mode": params.get("mode"),
        "risk": params.get("risk_level"),
        "band": params.get("odds_band"),
        "overrides": params.get("overrides"),
        "risk_default": risk_default,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def live_query(market, dates, params, risk_default="balanced"):
    """Run the existing engine for `dates` with the user's controls applied."""
    dates = [d for d in (dates or []) if d]
    if not dates:
        return []
    key = _cache_key(market, dates, params, risk_default)
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < _CACHE_TTL_SEC:
        return hit[1]
    if market == "gg":
        rows = _live_gg(dates, params)
    elif market == "win":
        rows = _live_win(dates, params, risk_default=risk_default)
    else:
        rows = _live_o25(dates, params, risk_default=risk_default)
    rows = _json_safe(rows)
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (now, rows)
    return rows

