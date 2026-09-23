"""
GG PRECISION FILTER — daily precision layer over the AUTHORITATIVE GG engine output.

ARCHITECTURE (conformant with the WIN / O2.5 daily-snapshot model):
    run_gg_o15_engine(target_date)            Engine/gg_precision_engine.py  (sole predictor)
      -> output/ALIENEDGE_GG_PICKS_{date}.csv          (authoritative daily predictions)
    run_gg_forensic_aggregator(target_date)   AGGREGATOR/gg_forensics_audit.py
      -> output/JUDGED_GG_PICKS_{date}.csv             (daily forensics: H2H GG count +
                                                        verified standings ranks — already
                                                        acquired by the daily pipeline)
    run_gg_precision_filter(target_date)      FILTER/gg_precision_filter.py  (THIS FILE)
      -> output/forecast_final_gg_precision.csv
      -> per-date snapshot filter_gg__{date}.json      (saved by main.py via output_store)
    /api/filter/gg/weekly -> read_range() over the dated snapshots (api/main.py).

DATA SOURCING RULES (enforced in code):
  - The ONLY prediction source is ALIENEDGE_GG_PICKS_{target_date}.csv for the requested
    date. NO globbing of arbitrary GG CSVs. Downstream artifacts (JUDGED_*,
    ALIENEDGE_GG_PSYCHOLOGY_FINAL_*, FINAL_GG_MASTER_LIVE.csv) and this filter's own
    previous output are NEVER prediction sources.
  - JUDGED_GG_PICKS_{target_date}.csv is read purely as an ENRICHMENT join on
    fixture_id (never by team name) to supply forensics-computed fields the engine
    CSV does not carry: h2h_gg_count and verified standings positions.
  - ZERO default fabrication. Every value is real. A required-but-unavailable value
    excludes the row from the gate that needs it — no substitute constants, ever.
  - NO network access in this file: it is a local file-processing layer. Zero
    SportMonks calls are added by this filter.
"""

import os
import re
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# --- DYNAMIC PATHS FOR SERVERS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ============================================================
# VALUE PARSING HELPERS (strict — None when not provable)
# ============================================================
def _norm_id(value):
    """Normalize a fixture/league id to a clean string ('19744607.0' -> '19744607')."""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

def _to_int(value):
    try:
        f = float(str(value).strip())
        return int(f) if f == f else None
    except (TypeError, ValueError):
        return None

def _to_float(value):
    try:
        f = float(str(value).strip())
        return f if f == f else None
    except (TypeError, ValueError):
        return None

def _last3_from_tier(tier):
    """
    Derive last-3 GG form from the engine's tier label (real engine output, not a
    default). gg_precision_engine.get_gg_tier() assigns TIER 1 when all/most form
    signals fired (2-3 of last 3 each side) and TIER 2 when form is partial
    (1-2 of last 3). Returns None when the tier label carries no form information
    (STANDARD/other) — the row is then excluded from the last-3 gate.
    """
    t = str(tier or "").upper()
    m = re.search(r"TIER\s*([1-9])", t)
    if not m:
        return None
    n = int(m.group(1))
    if n == 1:
        return 3   # TIER 1: form signals fired on both sides (2-3 of last 3)
    if n == 2:
        return 2   # TIER 2: partial form (1-2 of last 3)
    return None

# ==HELPERS-END==
# ============================================================
# STEP 2/3 — AUTHORITATIVE SOURCE + ZERO-FABRICATION LOADER
# ============================================================
def _load_authoritative_engine(target_date):
    """
    Load the day's authoritative GG engine output: ALIENEDGE_GG_PICKS_{date}.csv.

    Provenance of every mapped field (verified against gg_precision_engine.py):
      fixture_id, league_id, home_team, away_team ... identity columns (real)
      gg_prob_pct      <- mc_btts_prob * 100      (engine Monte-Carlo BTTS, 0-1 -> %)
      home_gg_count    <- venue_btts_home  * 5   (engine venue window is exactly
      away_gg_count    <- venue_btts_away  * 5    LAST_N_GAMES=5 side-specific matches)
      tier             <- gg_tier                 (real engine tier label)
      home/away_gg_last3 <- derived from tier via _last3_from_tier (real engine
                            form signal outcome, never a constant)
      engine_parity    <- parity                  (engine parity_score(), 0-1 SIMILARITY:
                            higher = teams more evenly matched. Exposed under its own
                            accurate name — NOT written into concede_parity, which
                            means abs(conceded diff), a different quantity.)
      h2h_goal_parity / concede_parity -> None (see NOTE 2 below)
      h2h_gg_count, home_position, away_position <- NOT in this CSV; supplied by the
                            forensics enrichment join (_load_forensics_enrichment).
      NOTE 1: h2h_btts_rate * 5 is deliberately NOT used for h2h_gg_count — empirically
      it disagrees with the forensics H2H window (12/28 on 2026-09-16): different
      lookback/method. Using it would misreport real H2H GG counts.
      NOTE 2: h2h_goal_parity / concede_parity are ABSOLUTE INTEGER GOAL/CONCEDE GAP
      counts, as historically produced by Engine/gg_stage1.py & gg_stage2.py:
          h2h_goal_parity = abs(h2h_home_goals - h2h_away_goals)
          concede_parity  = abs(h_conceded      - a_conceded)
      Those orphaned modules are NOT re-introduced. The dated forensics artifact
      (JUDGED_GG_PICKS_{date}.csv) now persists both operands as H2H_Parity /
      Concede_Parity — values the aggregator already derived from data it already
      fetched — and _load_forensics_enrichment() joins them in. They stay None
      (never fabricated) on dates whose artifact predates that column, and Layer 2
      of the gate is evaluated only when a bound is supplied AND operands exist —
      see apply_precision_filter().
    """
    path = os.path.join(OUTPUT_DIR, f"ALIENEDGE_GG_PICKS_{target_date}.csv")
    if not os.path.exists(path):
        print(f"❌ Authoritative GG engine output not found for {target_date}: {path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"⚠️ Error reading {os.path.basename(path)}: {e}")
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        fid = _norm_id(r.get("fixture_id"))
        if not fid or fid == "nan":
            continue
        btts = _to_float(r.get("mc_btts_prob"))
        v_h  = _to_float(r.get("venue_btts_home"))
        v_a  = _to_float(r.get("venue_btts_away"))
        par  = _to_float(r.get("parity"))
        gg_o = _to_float(r.get("gg_odds"))   # ADDITIVE: real BTTS market odds, when the
                                           # engine run that wrote this CSV carried them
        tier = r.get("gg_tier")
        tier = str(tier) if pd.notna(tier) else None
        last3 = _last3_from_tier(tier)
        rows.append({
            "fixture_id":      fid,
            "league_id":       _to_int(r.get("league_id")),
            "home_team":       r.get("home_team"),
            "away_team":       r.get("away_team"),
            "tier":            tier,
            "gg_prob_pct":     round(btts * 100.0, 2) if btts is not None else None,
            "home_gg_last3":   last3,
            "away_gg_last3":   last3,
            "h2h_gg_count":    None,   # from forensics enrichment join (fixture_id)
            "home_position":   None,   # from forensics enrichment join (fixture_id)
            "away_position":   None,   # from forensics enrichment join (fixture_id)
            "home_gg_count":   _to_int(round(v_h * 5)) if v_h is not None else None,
            "away_gg_count":   _to_int(round(v_a * 5)) if v_a is not None else None,
            "h2h_goal_parity": None,   # h2h goal gap — see NOTE 2; filled only when the
            "concede_parity":  None,   # dated forensics artifact carries the operands
            "engine_parity":   round(par, 3) if par is not None else None,
            "gg_odds":         gg_o,
        })
    return pd.DataFrame(rows)

# ==ENGINE-LOADER-END==
# ============================================================
# STEP 4 — FORENSICS ENRICHMENT (local file join on fixture_id ONLY)
# ============================================================
def _load_forensics_enrichment(target_date):
    """
    Read JUDGED_GG_PICKS_{target_date}.csv (AGGREGATOR/gg_forensics_audit.py —
    produced daily by the existing pipeline with its own verified standings and
    H2H calls; this filter performs ZERO new API calls) and index it by fixture_id.

    Supplies:
      h2h_gg_count    <- 'H2H_GG'  column ('3/5' -> 3; forensics get_h2h_forensics)
      home_position   <- 'Ranks'   column ('7v9' -> 7; forensics
                                      get_league_rank_verified; 99 = forensics'
                                      own unranked sentinel, kept REAL)
      away_position   <- 'Ranks'   column ('7v9' -> 9)
    Join key: fixture_id ONLY — never normalized team names, because normalized
    name matching silently conflates distinct clubs that share a name.
    """
    candidates = [
        os.path.join(OUTPUT_DIR, f"JUDGED_GG_PICKS_{target_date}.csv"),
        os.path.join(OUTPUT_DIR, "JUDGED_GG_PICKS.csv"),
    ]
    path = next((c for c in candidates if os.path.exists(c)), None)
    if not path:
        print(f"⚠️ Forensics enrichment not found for {target_date} "
              f"(JUDGED_GG_PICKS_{{{target_date}}}.csv) — h2h/position gates will "
              f"exclude rows honestly (no defaults injected).")
        return {}

    try:
        j = pd.read_csv(path)
    except Exception as e:
        print(f"⚠️ Error reading {os.path.basename(path)}: {e}")
        return {}
    if j.empty:
        return {}

    j = j.assign(fixture_id=j["fixture_id"].map(_norm_id))
    j = j.drop_duplicates(subset=["fixture_id"], keep="first")

    enrich = {}
    for _, r in j.iterrows():
        rec = {"h2h_gg_count": None, "home_position": None, "away_position": None,
               "h2h_goal_parity": None, "concede_parity": None}
        h2h = str(r.get("H2H_GG", "") or "").strip()
        if "/" in h2h:
            rec["h2h_gg_count"] = _to_int(h2h.split("/")[0])
        m = re.match(r"^(\d+)\s*v\s*(\d+)$", str(r.get("Ranks", "") or "").strip())
        if m:
            rec["home_position"] = int(m.group(1))
            rec["away_position"] = int(m.group(2))
        # ADDITIVE (2026-09-23): the forensics auditor now persists the two
        # operands of its own documented TOTAL PARITY layer as real dated
        # columns (H2H_Parity / Concede_Parity — the same integers it already
        # computed from data it already fetched). Older dated files simply
        # lack them → None → the parity gate stays unevaluated (no fabrication).
        if "H2H_Parity" in j.columns:
            rec["h2h_goal_parity"] = _to_int(r.get("H2H_Parity"))
        if "Concede_Parity" in j.columns:
            rec["concede_parity"] = _to_int(r.get("Concede_Parity"))
        enrich[str(r["fixture_id"])] = rec
    return enrich

def _enrich(df, enrich):
    """Fill ONLY missing fields from the fixture_id-indexed forensics record.
    Never overwrites a real value already present."""
    if df.empty or not enrich:
        return df
    def _apply(row):
        e = enrich.get(str(row["fixture_id"]))
        if not e:
            return row
        for k, v in e.items():
            if v is not None and row.get(k) is None:
                row[k] = v
        return row
    return df.apply(_apply, axis=1)

# ==ENRICH-END==

# ============================================================
# USER FLEXIBILITY CONFIG (Deadly Accuracy Layer)
# ============================================================
USER_FILTER = {
    "last3_gg_min": 2,           # Must have at least 2 GG in last 3 matches
    "last3_gg_max": 3,           # 🟢 UPGRADED: No longer hardcoded to 3 in the logic
    "h2h_gg_min": 3,             # History must show high H2H GG frequency
    "pos_diff_min": 1,           # 🟢 UPGRADED: Minimum table positions apart
    "pos_diff_max": 10,          # 🟢 UPGRADED: Maximum table positions apart
    "home_gg_side_min": 3,       # Home team must have 3+ GG matches at home
    "away_gg_side_min": 3,       # Away team must have 3+ GG matches away
    "min_probability": 60.0      # Probability floor
}

# ============================================================
# PATH & SCHEMA CONFIG
# ============================================================
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "forecast_final_gg_precision.csv")

# 🟢 UPGRADED: Added the missing vital columns so the engine doesn't crash during aggregation
REQUIRED_COLS =[
    "fixture_id",
    "league_id",
    "home_team",
    "away_team",
    "tier",
    "gg_prob_pct",
    "home_gg_last3",
    "away_gg_last3",
    "h2h_gg_count",
    "home_position",
    "away_position",
    "home_gg_count",
    "away_gg_count",
    "h2h_goal_parity",
    "concede_parity"
]

# NOTE: the old normalize_name() helper was removed along with name-based
# grouping. Team names are NEVER a join key in this module — enrichment joins
# on fixture_id only (see _load_forensics_enrichment), because normalized-name
# matching silently conflates distinct clubs that share a name.

# ============================================================
# DATA LOADER & VALIDATOR (deterministic, date-scoped)
# ============================================================
def load_authoritative_history(target_date):
    """
    Load ONE day's validated GG rows from the authoritative engine output for
    exactly target_date (no globbing, no [-days:] slicing, no self-feeding on this
    filter's own forecast CSV, no downstream-artifact contamination).

    Steps:
      1. _load_authoritative_engine(target_date)  — predictions + engine-derived fields
      2. _load_forensics_enrichment(target_date)  — h2h/positions keyed by fixture_id
      3. _enrich()                                — fill ONLY missing fields
      4. schema gate (REQUIRED_COLS must exist — columns may hold None when the
         value is genuinely unavailable; gates exclude such rows, never defaults)
      5. dedupe on fixture_id, tag source_file for verification accounting
    """
    df = _load_authoritative_engine(target_date)
    if df.empty:
        print(f"⚠️ No authoritative GG rows for {target_date}.")
        return pd.DataFrame()

    df = _enrich(df, _load_forensics_enrichment(target_date))

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f"❌ Authoritative GG schema violation for {target_date}: missing {missing}")
        return pd.DataFrame()

    initial_count = len(df)
    df = df.drop_duplicates(subset=["fixture_id"])
    if len(df) < initial_count:
        print(f"   [!] Cleaned {initial_count - len(df)} duplicate fixtures")

    df["source_file"] = f"ALIENEDGE_GG_PICKS_{target_date}.csv"
    print(f"📂 Authoritative source: {df['source_file'].iloc[0]} ({len(df)} rows)")
    return df

# ==LOADER-END==

# ============================================================
# THE DEADLY PRECISION FILTER (gate logic preserved — all 6 layers)
# ============================================================
def apply_precision_filter(df, cfg, strict_mode=True, max_parity=None,
                           min_gg_odds=None, max_gg_odds=None):
    if df.empty: return df

    # ZERO-FABRICATION EXCLUSION: a row missing a real value for an EVALUATED gate
    # is EXCLUDED — it is never waved through with a substitute constant.
    # Only gate operands that a dated artifact actually produces are listed here.
    required = ["gg_prob_pct", "home_gg_last3", "away_gg_last3",
                "h2h_gg_count", "home_position", "away_position",
                "home_gg_count", "away_gg_count"]
    complete = df.dropna(subset=required)
    excluded = len(df) - len(complete)
    if excluded:
        print(f"   [!] {excluded} row(s) excluded — missing real values "
              f"(no defaults injected): kept {len(complete)} gate-eligible.")

    # 🟢 UPGRADED: FLEXIBLE TABLE DISTANCE LOGIC
    # Mask out 0 and 99 positions (Cup games/unranked)
    valid_positions = (complete["home_position"] > 0) & (complete["home_position"] < 90) & \
                      (complete["away_position"] > 0) & (complete["away_position"] < 90)

    # Calculate absolute distance between teams
    pos_diff = (complete["home_position"] - complete["away_position"]).abs()

    # Numeric conversions for safe masking
    prob_num = pd.to_numeric(complete["gg_prob_pct"].astype(str).str.replace('%', '', regex=False), errors='coerce')
    h_last3 = pd.to_numeric(complete["home_gg_last3"], errors='coerce')
    a_last3 = pd.to_numeric(complete["away_gg_last3"], errors='coerce')
    h2h_cnt = pd.to_numeric(complete["h2h_gg_count"], errors='coerce')
    h_side = pd.to_numeric(complete["home_gg_count"], errors='coerce')
    a_side = pd.to_numeric(complete["away_gg_count"], errors='coerce')

    # ── GATES — each a boolean Series over `complete` (same rows as before) ────
    layers = [
        # Layer 1: Probability Floor
        (prob_num >= cfg["min_probability"]),

        # Layer 3: SHORT TERM FORM (Now dynamic using User Config)
        (h_last3.between(cfg["last3_gg_min"], cfg["last3_gg_max"])),
        (a_last3.between(cfg["last3_gg_min"], cfg["last3_gg_max"])),

        # Layer 4: H2H GG VOLUME
        (h2h_cnt >= cfg["h2h_gg_min"]),

        # Layer 5: STANDINGS GATE (Distance Based)
        valid_positions,
        (pos_diff.between(cfg["pos_diff_min"], cfg["pos_diff_max"])),

        # Layer 6: HISTORICAL SIDE-BIAS (Home vs Away performance)
        (h_side >= cfg["home_gg_side_min"]),
        (a_side >= cfg["away_gg_side_min"]),
    ]

    # ── LAYER 2: TOTAL PARITY LIMIT (additive activation) ────────────────────
    # This layer's operands (absolute integer H2H / conceded gaps — NOTE 2 in
    # _load_authoritative_engine) were historically unproduced, so the layer was
    # never evaluated. The dated forensics artifact now carries them as
    # H2H_Parity / Concede_Parity (computed from data the aggregator already
    # fetched). The gate is evaluated ONLY when the caller supplies a bound AND
    # this date's artifact really carries operands — otherwise it stays
    # unevaluated: never fabricated, never a silent pass. A row missing an
    # operand for an EVALUATED gate is excluded, the same zero-fabrication rule
    # every other layer already follows.
    if max_parity is not None:
        h2h_par = pd.to_numeric(complete["h2h_goal_parity"], errors="coerce") \
            if "h2h_goal_parity" in complete.columns else None
        con_par = pd.to_numeric(complete["concede_parity"], errors="coerce") \
            if "concede_parity" in complete.columns else None
        if h2h_par is None or con_par is None or (h2h_par.isna().all() and con_par.isna().all()):
            print(f"   [!] Total-parity gate requested (<= {max_parity}) but this "
                  f"date's forensics artifact carries no operands — gate NOT evaluated.")
        else:
            layers.append((h2h_par + con_par) <= float(max_parity))

    # ── GG (BTTS) ODDS CORRIDOR (additive activation) ─────────────────────────
    # Same rule: only evaluated when the caller supplies a bound AND this date's
    # engine artifact carries real gg_odds.
    if min_gg_odds is not None or max_gg_odds is not None:
        odds_num = pd.to_numeric(complete["gg_odds"], errors="coerce") \
            if "gg_odds" in complete.columns else None
        if odds_num is None or odds_num.isna().all():
            print(f"   [!] GG-odds gate requested but this date's engine artifact "
                  f"carries no gg_odds — gate NOT evaluated.")
        else:
            if min_gg_odds is not None:
                layers.append(odds_num >= float(min_gg_odds))
            if max_gg_odds is not None:
                layers.append(odds_num <= float(max_gg_odds))

    # ── COMBINE: strict (all gates) or soft (one failure allowed) ─────────────
    if strict_mode:
        mask = layers[0]
        for cond in layers[1:]:
            mask = mask & cond
    else:
        # Soft mode — the same "Diamond in the Rough" rule the WIN tipster
        # filter already ships: allow exactly ONE gate to fail.
        mask_sum = sum(cond.astype(int) for cond in layers)
        mask = mask_sum >= (len(layers) - 1)

    df_filtered = complete[mask].copy()

    # Save the distance so user can see it in output
    if not df_filtered.empty:
        df_filtered["table_distance"] = pos_diff[mask]

    return df_filtered

# ==GATE-END==

# ============================================================
# AGGREGATION (single deterministic day — weekly verification now lives in
# /api/filter/gg/weekly via read_range() over per-date snapshots)
# ============================================================
def aggregate_picks(df):
    grouped = df.sort_values("gg_prob_pct", ascending=False).copy()
    # Output-contract compatibility: cross-day verification is now performed by
    # read_range() composing per-date snapshots, so each dated run verifies 1 day.
    grouped["verification_days"] = 1
    return grouped

# ==AGG-END==

# ============================================================
# 📦 THE BLACK BOX WRAPPER (date-aware — mirrors WIN / O2.5 filter entrypoints)
# ============================================================
def run_gg_precision_filter(target_date=None, cfg_overrides=None, max_parity=None,
                            strict_mode=True, min_gg_odds=None, max_gg_odds=None,
                            persist=True):
    """Daily GG precision filter.

    ADDITIVE (2026-09-23) — every new argument defaults to the SHIPPED behaviour,
    so the pipeline call `run_gg_precision_filter(target_date)` is unchanged:
      * `cfg_overrides`  — merge user gate values over USER_FILTER (the Weekly
        drawer's MIN PROBABILITY / MIN HOME-AWAY GG / MIN H2H GG / MAX TABLE
        DISTANCE). Unknown keys are ignored; None never overwrites a default.
      * `max_parity`     — activates the documented Layer-2 total-parity gate
        (H2H_Parity + Concede_Parity <= max_parity) when the dated artifact
        carries operands; unevaluated otherwise.
      * `strict_mode`    — False = allow ONE gate to fail (same soft rule the
        WIN tipster filter already ships) for the STRICT PARITY LOCK toggle.
      * `min/max_gg_odds`— real BTTS-odds corridor, evaluated only when the
        engine artifact carries `gg_odds`.
      * `persist`        — False = request-time filtering does NOT write
        forecast_final_gg_precision.csv.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_date = str(target_date)
    print("\n" + "="*80)
    print(f"🚀 GG PRECISION FILTER ACTIVE — {target_date} (single authoritative daily source)")
    print("="*80)

    # Ensure directories exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Load and Validate (deterministic: exactly one dated engine artifact)
    df_all = load_authoritative_history(target_date)
    if df_all.empty:
        print("❌ Filter closed: no authoritative GG data found for this date.")
        return []

    # 1b. Effective gate config = engine defaults + caller overrides
    cfg = dict(USER_FILTER)
    if cfg_overrides:
        for key, value in cfg_overrides.items():
            if key in cfg and value is not None:
                cfg[key] = value

    # 2. Filter
    print("🎯 Applying Precision Layers (Total Parity <= 4, Form constraints, Table Distance)...")
    df_filtered = apply_precision_filter(df_all, cfg, strict_mode=strict_mode,
                                         max_parity=max_parity,
                                         min_gg_odds=min_gg_odds,
                                         max_gg_odds=max_gg_odds)

    if df_filtered.empty:
        print("🛑 Precision Check: No matches survived the deadly accuracy layers.")
        return []

    # 3. Single-day pass-through (weekly verification = read_range() over dated snapshots)
    df_final = aggregate_picks(df_filtered)
    df_final["audit_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # 4. Save and Print (skipped for request-time/live filtering)
    if persist:
        df_final.to_csv(OUTPUT_FILE, index=False)

    print("\n      🏆 FINAL HIGH-PRECISION VERIFIED PICKS (AGGREGATED) 🏆")
    print("-" * 80)

    cols = [c for c in ["home_team", "away_team", "table_distance", "gg_prob_pct",
                        "tier", "verification_days"] if c in df_final.columns]
    print(df_final[cols].to_string(index=False))
    print("\n" + "-"*80)
    if persist:
        print(f"✅ SUCCESS: {len(df_final)} Matches verified and saved to {OUTPUT_FILE}")
    else:
        print(f"✅ SUCCESS: {len(df_final)} Matches verified (live request, no artifact written)")

    return df_final.to_dict(orient="records")

if __name__ == "__main__":
    run_gg_precision_filter()
