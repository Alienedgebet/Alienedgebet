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
   the same >= / <= semantics, so a control is never silently ignored. Every
   drawer key listed in `filter-config.ts` must appear in one of the mapping
   tables below or in PUBLIC_UNSUPPORTED; `tests_live_scanner_contracts.py`
   asserts it, because a key that is missing from these tables renders a box
   that accepts a number and silently does nothing.

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
    # None means the user cleared the control: no odds band, no odds filter.
    # It used to fall back to WIN_DEFAULT_BAND, which made "cleared" identical
    # to "1.40-1.90" on every request (2026-10-05).
    p["odds_band"] = _band(odds_band, WIN_BANDS, None)
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
    # Retained so an older client sending max_odds still works. The Weekly
    # drawer no longer exposes it — there is one odds box, a floor with no
    # ceiling — but a stale bookmarked request must not silently lose its
    # upper bound.
    max_odds: Optional[float] = None,
    min_home_goals: Optional[float] = None,
    min_away_goals: Optional[float] = None,
    max_home_conceded: Optional[float] = None,
    max_away_conceded: Optional[float] = None,
    # Strict disciplines — TICK BOXES. Only sent when the user actually ticks
    # them, so an untouched drawer keeps the shipped result set. Not clamped:
    # these are booleans, and a False is a decision (force out everything that
    # fails) rather than a threshold.
    strict_h2h_last3_over: Optional[bool] = None,
    strict_both_overs_last3: Optional[bool] = None,
) -> dict:
    p = _normalise(mode, "o25")
    p["risk_level"] = risk_level if risk_level in O25_RISKS else "balanced"
    # Same rule as WIN: a cleared control means no odds band (2026-10-05).
    p["odds_band"] = _band(odds_band, O25_BANDS, None)
    for key, bounds, caster in (("min_poisson", _PROB, _clamp_num),
                                ("min_votes", _VOTES, _clamp_int),
                                ("max_pos_gap", _GAP, _clamp_num),
                                ("min_h2h_overs", _COUNT, _clamp_num),
                                ("min_odds", _ODDS, _clamp_num),
                                ("max_odds", _ODDS, _clamp_num),
                                # Recent goal form, per side. Bounded by
                                # _COUNT (0-50); 0 or blank means the gate is
                                # off, so the shipped result set is unchanged
                                # until a value is actually typed.
                                ("min_home_goals", _COUNT, _clamp_num),
                                ("min_away_goals", _COUNT, _clamp_num),
                                ("max_home_conceded", _COUNT, _clamp_num),
                                ("max_away_conceded", _COUNT, _clamp_num)):
        clamped = caster(locals()[key], bounds)
        if clamped is not None:
            p["overrides"][key] = clamped
    # Tick boxes. A tick is a decision, not a threshold, so it is recorded
    # whenever it arrives — including False, which means "force out everything
    # that fails this gate". Absent stays absent so an untouched drawer sends
    # nothing at all and the shipped result set is unchanged.
    for key in ("strict_h2h_last3_over", "strict_both_overs_last3"):
        ticked = locals()[key]
        if ticked is not None:
            p["overrides"][key] = bool(ticked)
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
    # Recent goal form, per side — real gates, not a display toggle.
    "min_home_goals": "min_home_goals",
    "min_away_goals": "min_away_goals",
    "max_home_conceded": "max_home_conceded",
    "max_away_conceded": "max_away_conceded",
    # Strict disciplines (tick boxes). Same names in Tipster mode, so the tick
    # means the same thing on both sides of the mode toggle.
    "strict_h2h_last3_over": "strict_h2h_last3_over",
    "strict_both_overs_last3": "strict_both_overs_last3",
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
    # Recent goal form, per side. These four gates were added to the drawer and
    # to the Tipster kwargs map, but O25_NARROW never listed them — so in
    # Public mode (the DEFAULT mode) they were accepted by o25_filter_params,
    # carried through the API, and then dropped by this lookup table. The box
    # rendered, took a number, and changed nothing.
    #
    # The `_opt` comparison ops mirror the engine-side gate in
    # FILTER/over25_risk_filter.py::apply_over_tipster_filter exactly, so one
    # box cannot mean two different things depending on the mode toggle:
    #   * a threshold of 0 means OFF (gate skipped, not applied) — the engine
    #     does `if not thr: continue`, and a typed 0 must not mean "<= 0" and
    #     delete every fixture;
    #   * an unknown value PASSES rather than failing — a dated artifact
    #     graded before the engine wrote these columns must not be filtered to
    #     nothing here while surviving in Tipster mode.
    "min_home_goals": ("home_goals_scored_last_5", "min_opt"),
    "min_away_goals": ("away_goals_scored_last_5", "min_opt"),
    "max_home_conceded": ("home_goals_conceded_last_5", "max_opt"),
    "max_away_conceded": ("away_goals_conceded_last_5", "max_opt"),
    # Strict disciplines — TICK BOXES, not dials. Ticking one forces out every
    # fixture that does not clear it, rather than scoring them better on a
    # slider. Same two keys reach the engine in Tipster mode via
    # O25_TIPSTER_KWARGS, so a tick means the same thing in both modes.
    "strict_h2h_last3_over": ("kill_switch_pass", "is_true"),
    # Compound: BOTH sides must clear the bar, so this one takes a tuple of
    # columns and the "all_min" op. The third element is a FIXED threshold of
    # 3 — the control means "all three of the last three", so the bound comes
    # from the window's own length, not from anything the user typed. Only the
    # tick itself is a user choice.
    "strict_both_overs_last3": (
        ("home_overs_last_3", "away_overs_last_3"), "all_min", 3),
}

# Drawer controls that CANNOT be honoured in Public mode.
#
# `strict_mode` is a parameter of apply_tipster_filter ONLY
# (FILTER/win_filter_service.py:80). apply_public_filter() has no soft/strict
# branch at all, so there is nothing to forward it to. It was previously in the
# WIN config, absent from WIN_NARROW, and therefore silently ignored in Public
# mode. Rather than fake a soft-mode verdict the public engine cannot compute,
# the Weekly UI disables it in Public mode and states why; it works normally in
# Tipster / Forensic mode, where the real parameter exists.
PUBLIC_UNSUPPORTED = {
    "win": ("strict_mode",),
    "o25": (),
    "gg": (),
}

# Which mapping table each market uses in each mode. `filter-config.ts` keys
# ("gg" | "over25" | "win") are mapped to the API's market names ("gg" | "o25" |
# "win") here, so the contract suite can assert every drawer box is reachable
# in EVERY mode rather than in some mode. GG has no entry: _live_gg has no mode
# branch and forwards its whole control set in all three.
NARROW_SPEC = {"o25": "O25_NARROW", "win": "WIN_NARROW"}
TIPSTER_SPEC = {"o25": "O25_TIPSTER_KWARGS", "win": "WIN_TIPSTER_KWARGS"}

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

    Two comparison families exist, and they differ deliberately:

    * `"min"` / `"max"` / `"split_min"` — STRICT. A row whose evaluated field
      is missing is EXCLUDED, the zero-fabrication rule: no operand, no
      verdict.
    * `"min_opt"` / `"max_opt"` — LENIENT, and byte-for-byte the semantics of
      the engine-side gate in FILTER/over25_risk_filter.py. A threshold of 0
      turns the gate OFF, and an unknown value PASSES instead of failing.

    The lenient family exists because the two modes run the same gates through
    two different implementations. Without it, one box would mean "strict, and
    a blank cell deletes the row" in Public mode and "0 is off, a blank cell
    passes" in Tipster mode.
    """
    spec = WIN_NARROW if market == "win" else O25_NARROW
    active = []
    for canonical, spec_val in spec.items():
        if canonical not in overrides:
            continue
        if overrides[canonical] is None:
            continue
        # A 2-element spec is (fields, op); a 3-element one pins the threshold
        # for a gate whose bar is a property of the window rather than
        # something the user typed ("all three of the last three" is 3 by
        # definition, and the tick is still only a tick).
        field, op = spec_val[0], spec_val[1]
        fixed = spec_val[2] if len(spec_val) > 2 else None
        bound = fixed if fixed is not None else overrides[canonical]
        if fixed is not None and not overrides[canonical]:
            continue
        # A falsy bound means the gate is OFF — never "gate at zero". This is the
        # engine's own rule (`if not thr: continue`); without it a typed 0 in
        # "Max ... Conceded" means "<= 0" and wipes every fixture, while the
        # identical 0 in Tipster mode means "no gate".
        #
        # The same rule has to hold for the tick boxes, and it matters most
        # there: the drawer's default is unticked, so a False reaching this
        # loop means the user ticked the box and then unticked it. Treating
        # that as "force out everything that fails" would invert the control:
        # unticking it would delete fixtures instead of releasing them.
        if not bound and (op.endswith("_opt") or op in ("is_true", "all_min")):
            continue
        active.append((field, op, bound))
    if not active:
        return rows
    kept = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        keep = True
        for field, op, bound in active:
            if op == "all_min":
                # Compound gate: EVERY listed column must clear the bar. A
                # column that is absent from the row passes — no operand, no
                # verdict — rather than silently dropping the fixture on a
                # field the engine may not have written for that date.
                for sub in field:
                    got = _num(row.get(sub))
                    if got is not None and got < bound:
                        keep = False
                        break
                if not keep:
                    break
                continue
            raw = row.get(field)
            if op == "is_true":
                if not _truthy(raw):
                    keep = False
                    break
                continue
            got = _num(str(raw).split("/")[0]) if op == "split_min" else _num(raw)
            if got is None:
                # Unknown operand. Strict gates exclude; `_opt` gates pass, so
                # a dated artifact graded before these columns existed is not
                # wiped out here while surviving in Tipster mode.
                if not op.endswith("_opt"):
                    keep = False
                    break
                continue
            if op in ("min", "min_opt") and got < bound:
                keep = False
                break
            if op in ("max", "max_opt") and got > bound:
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

    # PUBLIC vs TIPSTER (2026-10-05).
    #
    # The preset is PUBLIC's opinion. It used to be merged on top of the user's
    # boxes unconditionally, so on the TIPSTER board -- which belongs to the user
    # -- the app's preset filled in every box the user left empty. That is why a
    # board with a single number typed in H2H still had the preset's probability,
    # last-3, table-distance and side rules silently deciding the output.
    #
    # TIPSTER now seeds NOTHING. Only the numbers the user actually typed are
    # forwarded, and an empty box means that rule is off.
    is_tipster = params.get("mode") in TIPSTER_MODES

    if is_tipster:
        cfg_overrides = {GG_CFG_KEYS[k]: v
                         for k, v in overrides.items() if k in GG_CFG_KEYS}
        # Strict mode stays the board's own switch; with no preset there is no
        # preset value to inherit.
        strict_mode = bool(overrides.get("strict_mode", True))
    else:
        preset_cfg, preset_strict = GG_PRESETS.get(
            params.get("risk_level") or "banker", GG_PRESETS["banker"])
        cfg_overrides = {GG_CFG_KEYS[k]: v
                         for k, v in overrides.items() if k in GG_CFG_KEYS}
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
            use_public_preset=not is_tipster,
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
        # ODDS CORRIDOR ON THE TIPSTER BOARD (2026-10-05).
        #
        # It used to be applied unconditionally, and _band() substituted
        # WIN_DEFAULT_BAND into an EMPTY box — so clearing the odds control did
        # not remove the odds filter, it silently reinstated 1.40-1.90. The board
        # could not be run without an odds limit at all, which is the opposite of
        # what clearing a control means.
        #
        # Now the band narrows the result ONLY when the user actually selected
        # one. A cleared box leaves odds unfiltered, and an explicit drawer
        # value always wins over the band.
        if "min_odds" not in overrides and "max_odds" not in overrides and params.get("odds_band"):
            band_min, band_max = parse_band(params["odds_band"])
            if band_min is not None and band_max is not None:
                kwargs.setdefault("min_odds", band_min)
                kwargs.setdefault("max_odds", band_max)

        # Only the user's own numbers gate the board: nothing is seeded from the
        # public preset, so an empty box filters nothing.
        kwargs["use_public_preset"] = False

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
    from FILTER.over25_risk_filter import (run_over25_filter_aggregator,
                                            over25_source_and_goal_form)

    overrides = params.get("overrides") or {}
    # Which drawer gates is the user actually asking for? A 0 or an unticked
    # box means off, so only a truthy value counts.
    want = set()
    if any(overrides.get(k) for k in ("min_home_goals", "min_away_goals",
                                      "max_home_conceded",
                                      "max_away_conceded")):
        want.add("goal_form")
    if overrides.get("strict_both_overs_last3"):
        want.add("overs3")
    # Dates whose artifact predates the engine writing a gate's columns. The
    # engine skips SILENTLY there (`col not in df_filtered.columns`), so
    # without this the drawer shows a box as active while it evaluated
    # nothing at all — which is precisely the "the box does nothing" report.
    unchecked = {}
    if want:
        for date in dates:
            _src, have = over25_source_and_goal_form(date)
            missing = want - set(have)
            if missing:
                unchecked[date] = missing
    if not unchecked:
        return _run(dates, params, risk_default)

    def _mark(rows):
        for row in rows:
            if not isinstance(row, dict):
                continue
            missing = unchecked.get(row.get("match_date"))
            if not missing:
                continue
            row["_goal_form_unchecked"] = True
            row["_goal_form_note"] = (
                f"NOT applied to this fixture ({row.get('match_date')}): "
                + " and ".join(sorted(missing))
                + " — the engine recorded no data for this on that date.")
        return rows

    return _mark(_run(dates, params, risk_default))


def _run(dates, params, risk_default="balanced"):
    """The actual O2.5 dispatch: tipster engine path, or public + narrowing."""
    from FILTER.over25_risk_filter import run_over25_filter_aggregator

    overrides = params.get("overrides") or {}
    if params.get("mode") in TIPSTER_MODES:
        kwargs = {engine_key: overrides[canonical]
                  for canonical, engine_key in O25_TIPSTER_KWARGS.items()
                  if canonical in overrides}
        # 2026-09-30. The drawer now has ONE odds box — a floor, no ceiling.
        # The old guard required BOTH min_odds and max_odds to be absent
        # before the corridor applied, but the drawer always sent min_odds
        # (default 1.50), so the band block was never reached: the stale 1.50
        # floor plus the filter's own 2.20 ceiling silently replaced whatever
        # corridor the user had clicked, and @1.30-1.60 did nothing.
        #
        # Now: the band supplies the CEILING whenever the drawer did not set
        # one, and the drawer's min_odds overrides the band floor only if the
        # user actually typed it. So one box means "this price and above",
        # exactly as labelled, and the corridor still caps the top when the
        # floor is left at its default.
        # A selected corridor still applies. A CLEARED one does not: since
        # _band() now yields None for an empty control, the whole block is
        # skipped and odds go unfiltered rather than being reinstated at
        # O25_DEFAULT_BAND (2026-10-05).
        if params.get("odds_band"):
            band_min, band_max = parse_band(params["odds_band"])
            if band_max is not None and "max_odds" not in overrides:
                kwargs.setdefault("max_odds", band_max)
            if band_min is not None and "min_odds" not in overrides:
                kwargs.setdefault("min_odds", band_min)

        # Only the user's own numbers gate the board (2026-10-05). Nothing is
        # seeded from the public preset, so an empty box filters nothing.
        kwargs["use_public_preset"] = False

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

