"""
INTELLIGENT_PASS/pass_count.py — Intelligent Pass Count evaluator
═══════════════════════════════════════════════════════════════════════════════
A pure, read-only SECOND-LEVEL AUDIT over the intelligence AlienEdge already
produces. It answers one question per prediction row: "how many of the
applicable existing intelligence checks support this pick?" — expressed as a
compact count like "5/7".

HARD ARCHITECTURE RULES (user spec, all binding):
  • DISPLAY/AUDIT ONLY. It never changes, filters, re-grades or replaces the
    original prediction. Settlement / output_store / engines: 0 changes.
  • ZERO new SportMonks / live-API calls: every input is read from the same
    on-disk output/cache/{key}__{date}.json snapshots the API already serves
    (via output_store's documented convention). This module therefore imports
    nothing network-related and never calls an engine.
  • PER-FIXTURE three-state results: every check resolves to PASS / FAIL /
    NOT_AVAILABLE for that exact fixture. A genuinely unavailable intelligence
    NEVER becomes a fake FAIL. The DENOMINATOR IS FIXED per market: it is the
    market's full rule set (WIN=8, GG=4, …), so N/A outcomes lower the
    numerator only — the same pick always shows the same total (e.g. x/8),
    and only x varies (2/8, 5/8, 8/8 …).
  • No new intelligence is invented: each rule reads one pre-existing field or
    one pre-existing verdict/category produced by an existing engine. Where a
    rule cannot be backed by existing data it is intentionally NOT registered
    for that market (display-only stages keep an empty checklist).

RULE ORIGIN MAP (every threshold verified against the producing engine —
nothing here reinterprets or normalises a scale):
  ─ WIN SOT               PSYCHOLOGY/u2s_psychology.py per-side SOT
                           expectancy — the very columns the WIN page renders
                           as "SOT Expectancy (Dog)" / "SOT Expectancy (Fav)"
                           (Dog_Venue_SOT / Fav_Venue_SOT, last-3 venue SOT).
                           The predicted team's side is identified by the U2S
                           row's own Underdog column (fixture-level identity),
                           never by re-deriving favourite/underdog. The rule
                           is the engine's OWN Tier-A1 comparison (L607-620:
                           `if dog_v_sot > fav_v_sot … elif fav_v_sot >
                           dog_v_sot …` — equal totals award nothing): PASS
                           only when the predicted team's expectancy is
                           strictly greater than the opponent's. Match-level
                           Cerberus (Engine/sot_engine.py) has no per-side SOT
                           (Proj_SOT is a match total), so it is not the WIN
                           SOT source.
  ─ Corner Friction        AGGREGATOR/corner4_aggregator.py Friction labels:
                           💎 PERFECT / 📊 STABLE support a corner market;
                           💀 DEAD / 🛑 AVOID / UNDER oppose it.
  ─ WIN Corners            AGGREGATOR/corner4_aggregator.py "TRUE FAVOURITE
                           RESOLUTION" (L676-684): True_Corner_Fav is the side
                           with the higher syndicate corner score
                           (Home_Score vs Away_Score). WIN rule: PASS when the
                           predicted team IS True_Corner_Fav. The Friction
                           label is NOT the WIN corner rule.
  ─ WIN Psychology         PSYCHOLOGY/win_psychology.py H_Base / A_Base are
                           SIGNED per-side nets (the engine's own Audit_Score
                           is |H_Base - A_Base|). The predicted team's OWN
                           side net > 0 == PASS — the same condition the
                           engine itself uses when it marks a row OVERTURNED
                           (the picked side's base went negative). A fixture
                           level Audit_Score / the apex row's copied
                           Psych_Score is only the documented fallback when
                           the side pair is absent.
  ─ Underdog (U2S)         AGGREGATOR/master_underdog_audit.py Dog_Score_Prob
                           (0-100 "%") is the longshot gate; PASS < 50%. The
                           same producer's Engine/underdog_engine.py
                           dog_score_prob is the documented fallback (same
                           field, same scale, same engine family).
  ─ WIN Goal Intent        CORE/dna_v2_market_factors.py per-side Goal Intent
                           (home_value / away_value 0-100, produced off
                           DNA Market_Power_Scores). WIN rule: the predicted
                           team's Goal Intent > the opponent's → PASS.
                           Fallback for fixtures without a market-factor
                           entry: the same engine's per-team
                           Market_Power_Scores.Goal_Intent profiles
                           (data/team_dna_profiles.json / cache dna) for both
                           named teams — identical field, identical 0-100
                           scale, no new formula.
  ─ WIN Parity             Engine/win_forecast.py parity_score is ALREADY
                           SIGNED PER SIDE ("parity_score": parity_diff if
                           side=="home" else -parity_diff) — the selected
                           team's 5-game goal-involvement (venue+overall+H2H)
                           advantage vs this exact opponent. User rule: PASS
                           = parity_score >= +10 on the selected team's row.
  ─ WIN Form               Pure comparison of the existing form counters
                           (Engine/win_forecast.py): the predicted team's
                           last_5_wins_overall vs the OPPONENT's own side
                           row's last_5_wins_overall (both sides are always
                           written by the same engine). When the opponent's
                           wins counter is absent the row's own
                           last_5_goals_scored vs opp_last_5_goals_scored is
                           the documented fallback. No new thresholds.
  ─ Draw probability       Engine/draw_engine.py mc_draw_prob (0-1 Monte
                           Carlo) < 0.20 (user rule); dmi (Draw Magnet Index
                           0-1) >= 0.45 and parity (0-1) >= 0.6 are the
                           engine's own tier gates (L863/870) — reused
                           verbatim. A WIN pick whose fixture has no draw
                           row falls back to the pick's own
                           Monte_Draw_Prob (the WIN apex engine's own draw
                           risk, 0-100 %) against the same 20% cut.
  ─ DNA parity (draw)      data/dna_v2_market_factors.json markets.draw
                           factor win-count balance: |home_count-away_count|
                           in {0,1} (user rule; values outside 0/1 FAIL).
  ─ O2.5 votes             Engine/over25_forecast.py council gates reused
                           verbatim: pos_gap <= 8 (league-position gap,
                           99 = unknown sentinel → NOT_AVAILABLE),
                           parity_diff > 0 (signed home-minus-away position
                           parity), h2h_overs_last_5 > 0.
  ─ Unders parity          O2.5/O1.5 parity_diff is a SIGNED league-position
                           parity (engine gate: > 0) — NOT a ±0.4 scale.
  ─ FHVI / SHVI            Engine/fhvi_engine.py / shvi_engine.py Category
                           gate: score >= 7 == "TIER 2 - GOOD" or better.
  ─ Dead rubbers           AGGREGATOR/corner4_aggregator.py Chaos_Rating
                           (0-100): <= 20 == nothing to play for.
  ─ U2S native fields      AGGREGATOR/apex_ud_aggregator.py underdog_base
                           row (Dixon-Coles multipliers ~1.0-centred,
                           higher=stronger/weaker): dog_att_strength >= 1.90,
                           fav_def_weakness >= 1.40, dog_is_hot, dog_due_goal,
                           fav_cs_streak == 0, dog_venue_wins > 0.

COMPOSITE CACHE FILES
  gg_o15 and unders store several market heads in one payload. Only the
  whitelisted head is read (_COMPOSITE_HEAD0_KEYS): gg_o15 head 0 = the GG
  supreme list the /api/gg/supreme route serves; unders head 0 = the u25
  list /api/unders serves. Parity / u35 / o15 heads are different markets
  and are never read by this evaluator.

IDENTITY
  fixture_id is the primary key wherever a source carries it (normalised to
  str() — cache files mix str/int, and a raw-int comparison against a
  str-keyed registry silently dropped the WIN side rows). Legacy name-only
  sources (psychology, sot, fhvi, shvi, corner4) use deterministic label
  normalisation — the same clean_n/get_match_key convention those engines
  already use, NOT fuzzy team matching. A fixture_id whose label-bearing
  sources disagree is resolved through label_by_id (majority label of the
  id-bearing engines on that date), so a row that stores the fixture with the
  sides swapped can still reach every name-keyed source. Composite cache files
  (draw, unders, gg_o15) are read head-0 only (their parity-list / u35 / o15
  heads are different markets).

CROSS-DAY SOURCE WINDOW  (why N/A was wrong for existing intelligence)
  main.py documents that the WIN Apex aggregator "takes NO date argument —
  it always reads the latest merged state", so the SAME apex payload is
  snapshotted under every date while its supporting engine rows live in the
  files of the day the apex engine actually read (verified 2026-09-21:
  189/191 apex picks resolve their U2S / psychology / corners / SOT rows in
  the 2026-09-20 caches, one day back; 14/15 on 2026-09-22). Auditing such a
  pick against the requested date alone produced NOT_AVAILABLE for
  intelligence that is saved on disk — the exact failure this module must not
  repeat. Every source join therefore resolves in a bounded date window
  (the requested date FIRST, then ±1..±MAX_SOURCE_LOOKBACK_DAYS), matching by
  fixture_id and, for id-less sources, by the label that date's own
  id-bearing engines confirm. The date that supplied every value is reported
  on the check itself (`source`), so the audit stays fully traceable.

PROVENANCE (how the user can see where each value comes from)
  Every check is {name, result, value, threshold, source, field, mapping}:
    source  — the engine key (cache file) + the date the row was read from;
    field   — the exact source field inside that engine's row;
    mapping — the team/side mapping used (e.g. "predicted=AtNé side=FAV");
  so no PASS/FAIL is ever unexplained.
"""
import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "output", "cache")

PASS = "PASS"
FAIL = "FAIL"
NOT_AVAILABLE = "NOT_AVAILABLE"

# ══════════════════════════════════════════════════════════════════════════════
# CENTRAL RULES CONFIGURATION — the single place every new threshold lives.
# Each entry was verified against the producing engine before being written
# (see module docstring for the origin map). Direction of every comparison is
# repo-native: nothing was inverted or normalised.
# ══════════════════════════════════════════════════════════════════════════════
INTELLIGENT_PASS_RULES = {
    # ── WIN ────────────────────────────────────────────────────────────────
    # Parity +10: win_raw/win_forecast parity_score is signed per side.
    "WIN_PARITY_THRESHOLD": 10,
    # WIN Draw Probability — the requested WIN cut (user rule): a WIN pick is
    # clean when the fixture's draw probability stays BELOW 20%. Both stored
    # representations of that same 20% are listed next to the field they
    # belong to (draw engine mc_draw_prob is a 0-1 Monte Carlo float; the WIN
    # apex row's Monte_Draw_Prob is the same quantity as a 0-100 number).
    "WIN_DRAW_PROB_MAX": 0.20,
    "WIN_DRAW_PROB_MAX_PCT": 20,
    # WIN Underdog — the longshot gate's own scale (0-100 "%"), PASS below it.
    "WIN_UNDERDOG_SCORE_PROB_MAX": 50,
    # Cross-day source window (see the module docstring): the requested date is
    # always tried first; only a genuine miss on that date looks at ±N days.
    "MAX_SOURCE_LOOKBACK_DAYS": 3,
    # Draw engine's own draw-candidate floor (Engine/draw_engine.py TIER2 gate
    # `mc_draw >= 0.22`). A WIN pick PASSES when the fixture is BELOW the
    # engine's draw-candidate floor; the DRAW page uses the same constant in
    # its native direction (>= floor = draw supported).
    "DRAW_MC_DRAW_PROB_FLOOR": 0.22,
    # Draw engine's own tier gates (L863): parity >= 0.6, dmi >= 0.45.
    "DRAW_PARITY_THRESHOLD": 0.6,
    "DRAW_DMI_THRESHOLD": 0.45,
    # DRAW — DNA factor-count parity balance (0 or 1 pass, else fail).
    "DRAW_DNA_PARITY_PASS_VALUES": {0, 1},
    # ── UNDERDOG ───────────────────────────────────────────────────────────
    # Dixon-Coles multipliers (higher = stronger dog attack / weaker
    # favourite defence); repo-native direction is >=.
    "UNDERDOG_DOG_ATT_STRENGTH_THRESHOLD": 1.90,
    "UNDERDOG_FAV_DEF_WEAKNESS_THRESHOLD": 1.40,
    # Underdog-to-score longshot gate (0-100 "%"-string, master_underdog_audit).
    "UNDERDOG_SCORE_PROB_THRESHOLD": 50,
    # ── PSYCHOLOGY (signed net scores, NOT percentages) ────────────────────
    "PSYCHOLOGY_NET_SCORE_PASS": 0,
    # ── O2.5 (Engine/over25_forecast.py own 9-layer council gates) ─────────
    "O25_POS_GAP_VOTE_MAX": 8,          # `if pos_gap <= 8: votes += 1`
    "O25_POISSON_VOTE_MIN": 60,         # `if poisson_over > 60: votes += 1`
    "O25_H2H_OVERS_VOTE_MIN": 3,        # `if h2h_overs_total >= 3: votes += 1`
    "O25_PARITY_VOTE_DIRECTION": 0,     # `if parity_diff > 0: votes += 1`
    # ── DNA engine v2 clash signals (CORE/dna_engine_v2.py L591-607) ───────
    "DNA_OVER_LEAN_CUT": 55,      # LEAN OVER: box_dominance > 55 or goal_intent > 55
    "DNA_GG_FRICTION_HOME": 65,   # STRONG GG: BTTS_Friction home_score > 65
    "DNA_GG_FRICTION_AWAY": 55,   # STRONG GG: BTTS_Friction away_score > 55
    "DNA_LEAN_GG_BOX": 60,        # LEAN GG: combined box dominance > 60
    "DNA_HIGH_CORNERS_CUT": 70,   # HIGH CORNERS: either side Corner_Power > 70
    # ── GG precision engine (Engine/gg_precision_engine.py) ───────────────
    "GG_GK_LIABILITY_CPG": 1.10,  # gk_bonus gate: cpg <= 1.10 = not liable
    "O15_LAMBDA_INTENT_MIN": 1.00,  # intent_bonus: both lambdas >= 1.00
    "O15_COMBINED_LAMBDA_SAT": 2.5,  # sig1 saturation: combined_lambda / 2.5
    # ── FHVI/SHVI Category gate (>=7 == TIER 2 GOOD or better) ────────────
    "FHVI_TIER2_THRESHOLD": 7,
    "SHVI_TIER2_THRESHOLD": 7,
    # SOT engine Game_Script tags that structurally support a shots market.
    "SOT_SUPPORT_TAGS": ("GLASS CANNONS", "SLAUGHTER"),
    "SOT_DIAMOND_TOKEN": "DIAMOND",
}

# WIN check name → the authoritative source field (provenance for rows that
# resolve with no pickable side, so even NOT_AVAILABLE says where it looked).
_WIN_FIELDS = {
    "SOT": "U2S Dog_Venue_SOT / Fav_Venue_SOT",
    "Corners": "corners_aggregator True_Corner_Fav",
    "Psychology": "win_psychology H_Base / A_Base",
    "Underdog": "underdog Dog_Score_Prob",
    "Goal Intent": "DNA Goal Intent",
    "Draw Probability": "draw mc_draw_prob / apex Monte_Draw_Prob",
    "Parity +10": "win parity_score",
    "Form": "win last_5_wins_overall",
}

# Markets whose pipeline stage carries no applicable second-level intelligence
# of its own: they intentionally render no Intelligent Pass column (the
# frontend hides the cell because the API attaches no audit object).
DISPLAY_ONLY_MARKETS = frozenset({
    "gg_psychology", "gg_forensics", "over25_psychology", "over15_psychology",
    "over25_gold", "over25_stage1", "over25_stage2", "over25_stage3",
    "over15_stage3", "corners_stage1", "corners_stage2",
    "corners_psychology", "corners_catalyst", "sot", "sh_gg_winner",
    "underdog_apex_display", "cross_verify",
})

# ── MARKET-KEYED REPORT ARCHITECTURE ────────────────────────────────────────
# The PICK is the primary object: the Team Intelligence page is a
# MARKET-SPECIFIC audit (team+date+market = the report identity), never a
# generic all-markets dashboard. Canonical keys below are what the report
# URL/API accept; aliases map them onto the evaluator's internal engine keys
# so a click from ANY table opens the report of the market that was clicked.
TEAM_INTELLIGENCE_MARKETS = {
    # canonical report key -> label shown by the report page
    "win": "Win",
    "win_psychology": "Win Psychology",
    "gg": "GG / BTTS Supreme",
    "gg_precision": "GG Precision",
    "gg_o15": "GG / Over 1.5 Composite",
    "over25": "Over 2.5",
    "over15": "Over 1.5",
    "corners": "Corners",
    "draw": "Draw",
    "unders": "Under 2.5",
    "u2s": "Underdog-to-Score",
    "fhvi": "FHVI",
    "shvi": "SHVI",
}
_MARKET_EVALUATOR_ALIASES = {
    # canonical report key -> the evaluator engine key(s) that market audits with
    # "win" and "win_psychology" are the SAME pick (WIN pack): ONE checklist.
    "win": ("win_apex", "win_forecast", "win_raw"),
    "win_psychology": ("win_apex", "win_forecast", "win_raw"),
    "gg": ("gg_supreme",),
    "gg_precision": ("gg_precision",),
    "gg_o15": ("gg_o15",),
    "over25": ("over25_apex", "over25_forecast"),
    "over15": ("over15", "over15_stage3", "over15_apex"),
    "corners": ("corners_aggregator",),
    "draw": ("draw",),
    "unders": ("unders_u25",),
    "u2s": ("u2s",),
    "fhvi": ("fhvi",),
    "shvi": ("shvi",),
}
# ══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _norm(name):
    """Deterministic fixture/team label normalisation (repo clean_n
    convention: case/spacing/punctuation-insensitive, accent-folded).
    This is NOT fuzzy matching — both sides of a join come from the same
    SportMonks feed, so normalised labels are exact."""
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _num(v):
    """Best-effort numeric coercion; returns None when genuinely not a number
    (so the caller can emit NOT_AVAILABLE instead of a fake FAIL)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _frac(v):
    """Coerce a probability that may be stored as 0-1 float or "%"-string
    into a 0-1 float. None when unavailable."""
    f = _num(v)
    if f is None:
        return None
    return f / 100.0 if f > 1.5 else f


def _load(key, date):
    """Disk-only read of one engine snapshot (output_store's documented
    filename convention). Missing file → None (never raises, never computes).

    Composite cache files (gg_o15, unders) store several market heads in one
    payload; only the whitelisted head is ever read (never the parity /
    u35 / o15 heads, which belong to different markets)."""
    path = os.path.join(CACHE_DIR, f"{key}__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f).get("data")
    except Exception:
        return None
    if key in _COMPOSITE_HEAD0_KEYS and isinstance(data, list) and data \
            and isinstance(data[0], list):
        return data[0]
    return data


# Composite cache payloads whose HEAD 0 is the market the API serves for the
# key (verified 2026-09-20: gg_o15 head0 = GG supreme, unders head0 = u25).
_COMPOSITE_HEAD0_KEYS = frozenset({"gg_o15", "unders"})


def _load_heads(key, date):
    """Raw payload of a composite cache file (list of market heads), no
    head-0 shortcut — used where the evaluator needs a specific non-zero
    head (gg_o15 head1 == the Over-1.5 composite rows)."""
    path = os.path.join(CACHE_DIR, f"{key}__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f).get("data")
    except Exception:
        return None
    return data


def _head_n(data, idx):
    if isinstance(data, list) and len(data) > idx and isinstance(data[idx], list):
        return [r for r in data[idx] if isinstance(r, dict)]
    return []


_DNA_PROFILE_MEMO = {"index": None}


def _index_dna_profiles(payload):
    """{normalised team name: DNA profile} from a dna payload
    ({team_id: profile}, CORE/dna_profiler.py)."""
    idx = {}
    if isinstance(payload, dict):
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            name = entry.get("team_name")
            if name:
                idx.setdefault(_norm(name), entry)
    return idx


def _dna_profiles(date):
    """Per-team DNA profiles for this date: the date's own dna cache payload
    when the pipeline produced one, otherwise the cumulative producer file
    data/team_dna_profiles.json (loaded once per process — it is the same
    engine store for every date, so the window never duplicates it)."""
    payload = _load("dna", date)
    if isinstance(payload, dict) and payload:
        return _index_dna_profiles(payload)
    if _DNA_PROFILE_MEMO["index"] is None:
        try:
            with open(os.path.join(ROOT, "data", "team_dna_profiles.json"),
                      "r", encoding="utf-8") as f:
                _DNA_PROFILE_MEMO["index"] = _index_dna_profiles(json.load(f))
        except Exception:
            _DNA_PROFILE_MEMO["index"] = {}
    return _DNA_PROFILE_MEMO["index"]


def _load_dna_factors(date):
    """DNA v2 market factors. Reads the API's served snapshot first
    (output/cache/dna_market_factors__{date}.json, dict {fixture_id: entry});
    falls back to the day's data/dna_v2_market_factors.json (same dict shape,
    same producer file) when the snapshot has not been generated yet.
    Disk-only either way."""
    dmf = _load("dna_market_factors", date)
    if isinstance(dmf, dict) and dmf:
        return dmf
    path = os.path.join(ROOT, "data", f"dna_v2_market_factors__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("market_factors")
    except Exception:
        pass
    path = os.path.join(ROOT, "data", "dna_v2_market_factors.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("market_factors")
    except Exception:
        return None


def _rows(data):
    """Flatten one envelope's data into flat dict rows (handles composite
    list-of-lists payloads defensively)."""
    out = []
    if isinstance(data, list):
        for grp in data:
            if isinstance(grp, list):
                out.extend(x for x in grp if isinstance(x, dict))
            elif isinstance(grp, dict):
                out.append(grp)
    elif isinstance(data, dict):
        out.append(data)
    return out


def _head0(data):
    """Head 0 of a composite cache file (draw → draw intelligence list,
    unders → u25 list). Parity/u35/o15 heads are different markets and are
    deliberately NOT read."""
    if isinstance(data, list) and data and isinstance(data[0], list):
        return [r for r in data[0] if isinstance(r, dict)]
    return _rows(data)
def _idstr(v):
    """Fixture identity as a string, or "" when the value is a placeholder.
    Cache files mix int and str ids ('19713004' vs 19713004) — every registry
    and comparison in this module uses this one normaliser, because an
    int-vs-str comparison against a str-keyed registry is exactly what let an
    apex row silently REPLACE the WIN side rows of its own fixture."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:      # NaN
        return ""
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "n/a", "na", "null", "-"}:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _id_index(rows):
    """{str(fixture_id): row} — fixture_id is the primary identity wherever
    a source carries it (cache files mix str/int ids)."""
    idx = {}
    for r in rows:
        fid = _idstr(r.get("fixture_id"))
        if fid:
            idx.setdefault(fid, r)
    return idx


_NAME_FIELDS = ("fixture", "Fixture", "Match", "fixture_name")


def _name_index(rows):
    """{normalised fixture label: row} for legacy name-keyed sources."""
    idx = {}
    for r in rows:
        for f in _NAME_FIELDS:
            v = r.get(f)
            if v:
                idx.setdefault(_norm(v), r)
                break
    return idx


_VS_SPLIT = r"\s+vs\.?\s+"


def _reverse_label(label):
    """The same fixture with its two sides swapped ("A vs B" → "B vs A").
    Deterministic, not fuzzy: the two labels describe the identical fixture,
    only the stored orientation differs between engines. Used ONLY after the
    exact label and the date's canonical label both missed."""
    parts = re.split(_VS_SPLIT, str(label or "").strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return ""
    return f"{parts[1].strip()} vs {parts[0].strip()}"


def _canonical_label(snap, fid):
    """The fixture's label as stored by that date's ID-BEARING engines
    (win_raw/win_forecast, underdog, draw, unders, over25, fhvi/shvi, DNA
    market factors). Apex rows are known to store the fixture with the sides
    swapped (verified: apex 'Atlético Nacional vs Llaneros' == side rows'
    'Llaneros vs Atlético Nacional'), so the id-bearing majority label — not
    the calling row's own string — is what the name-keyed engines are joined
    on."""
    fid = _idstr(fid)
    if not fid:
        return ""
    return (snap.get("label_by_id") or {}).get(fid, "")


def _resolve(snap, prefix, fid, fxn):
    """Resolve a source row: fixture_id first, then the exact label, then the
    date's canonical label for that id, then the reversed label. Indexes are
    per-source, so an id hit is always same-file, and every fallback is an
    exact normalised string comparison (never fuzzy matching)."""
    by_id = snap.get(prefix + "_by_id") or {}
    by_name = snap.get(prefix + "_by_name") or {}
    fid_s = _idstr(fid)
    if fid_s and fid_s in by_id:
        return by_id[fid_s]
    if fxn:
        key = _norm(fxn)
        if key in by_name:
            return by_name[key]
    canon = _canonical_label(snap, fid_s)
    if canon:
        key = _norm(canon)
        if key in by_name:
            return by_name[key]
        rev = _norm(_reverse_label(canon))
        if rev and rev in by_name:
            return by_name[rev]
    if fxn:
        rev = _norm(_reverse_label(fxn))
        if rev and rev in by_name:
            return by_name[rev]
    return None


def _fixture_label(row):
    for f in _NAME_FIELDS:
        v = row.get(f)
        if v:
            return str(v)
    return ""


def _split_fixture(label):
    parts = re.split(_VS_SPLIT, str(label or "").strip())
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")
# ══════════════════════════════════════════════════════════════════════════════
# PER-DATE SNAPSHOT (lazy memo — one dict of references to already-on-disk rows
# per date; the cross-day window keeps at most _MAX_WINDOW_SNAPSHOTS dates)
# ══════════════════════════════════════════════════════════════════════════════

_SNAPSHOTS = {}
# Bounded window cache: enough for the requested date plus the ±lookback days
# the cross-day payloads actually need (5 dates ≈ 22 MB on real 2026-09 data).
_MAX_WINDOW_SNAPSHOTS = 5
# Hermetic-test seam for _seal_date() below: when set, cross-day source
# lookups are restricted to exactly these dates, so an injected snapshot can
# never silently fall through to real cache files on disk.
_WINDOW_DATES_OVERRIDE = None


def _seal_date(*dates):
    """Hermetic-test seam: PIN cross-day joins to exactly the given dates.

    Offline suites inject synthetic snapshots, but the evaluator's source
    window would otherwise fall through to REAL cache files on neighbouring
    dates (fortuitous hits/flaky misses). Every suite must call this with its
    synthetic date right after injecting — the window then touches nothing
    else."""
    global _WINDOW_DATES_OVERRIDE
    _WINDOW_DATES_OVERRIDE = list(dates)


def clear_cache():
    """Test/ops hook — drop every memoised per-date snapshot. Also UNSEALS
    the date window (the next call re-seals as needed)."""
    global _WINDOW_DATES_OVERRIDE
    _SNAPSHOTS.clear()
    _WINDOW_DATES_OVERRIDE = None
    _SNAPSHOTS.clear()


def _window_dates(date):
    """The dates a source join may look at, in priority order: the requested
    date first, then the nearer neighbours (±1 … ±MAX_SOURCE_LOOKBACK_DAYS).
    Bounded by construction — the module never scans the whole archive."""
    if _WINDOW_DATES_OVERRIDE is not None:
        return list(_WINDOW_DATES_OVERRIDE)
    from datetime import date as _d, timedelta as _td
    try:
        base = _d.fromisoformat(str(date))
    except (TypeError, ValueError):
        return [date]
    span = int(INTELLIGENT_PASS_RULES["MAX_SOURCE_LOOKBACK_DAYS"])
    out = [base.strftime("%Y-%m-%d")]
    for step in range(1, span + 1):
        out.append((base - _td(days=step)).strftime("%Y-%m-%d"))
        out.append((base + _td(days=step)).strftime("%Y-%m-%d"))
    return out


def _trim_window_cache(keep):
    """Evict the least-recently-inserted snapshot once the window cache is
    full (plain FIFO — the requested date of the current call is always the
    most recent insertion, so it can never be evicted mid-evaluation)."""
    while len(_SNAPSHOTS) > _MAX_WINDOW_SNAPSHOTS:
        for key in list(_SNAPSHOTS):
            if key != keep:
                _SNAPSHOTS.pop(key, None)
                break
        else:
            break


def _snapshot(date):
    snap = _SNAPSHOTS.get(date)
    if snap is not None:
        return snap

    # WIN side rows: win_raw and win_forecast share the win_forecast engine's
    # row shape (same producer) and BOTH store parity_score signed per side —
    # so a row for the selected team is the row whose team_name matches.
    # win_apex rows are APPENDED to the registry (not the side rows): when a
    # pipeline run produced apex picks but not the win side (or vice versa),
    # the team-intelligence fixture locator must still resolve the fixture —
    # the report page must never say "no fixture" for a fixture the engines
    # clearly saved. Apex rows carry fixture_id + label (fixture-level).
    #
    # ID NORMALISATION (bug fix): the apex registry check MUST compare the
    # normalised key, otherwise an apex row (fixture_id stored as int) sees
    # "19713004 not in {'19713004': [...]}" and REPLACES the side rows of its
    # own fixture — which is what silently turned Parity/Form into N/A.
    win_side_rows = _rows(_load("win_raw", date)) + _rows(_load("win_forecast", date))
    win_apex_rows = _rows(_load("win_apex", date))
    win_by_id, win_by_name = {}, {}
    for r in win_side_rows:
        fid = _idstr(r.get("fixture_id"))
        if fid:
            win_by_id.setdefault(fid, []).append(r)
        label = _fixture_label(r)
        if label:
            win_by_name.setdefault(_norm(label), []).append(r)
    for r in win_apex_rows:
        fid = _idstr(r.get("fixture_id"))
        label = _fixture_label(r)
        if not fid or not label:
            continue
        if fid not in win_by_id:  # side rows take priority (they carry team_name)
            win_by_id[fid] = [r]
        key = _norm(label)
        if key not in win_by_name:
            win_by_name[key] = [r]

    u2s_rows = _rows(_load("u2s_psychology", date))
    corner_rows = _rows(_load("corners_aggregator", date))
    dmf = _load_dna_factors(date)
    # DNA v2 engine output: per-fixture clash rows carrying the engine's OWN
    # market verdicts (market_signals) for fixtures it covered that day.
    dna_v2 = _load_heads("dna_v2", date)
    dna_clash_rows = []
    if isinstance(dna_v2, dict):
        dna_clash_rows = [r for r in (dna_v2.get("fixture_clashes") or [])
                          if isinstance(r, dict)]

    # Composite files can be served nested (engine assembly) or flat (cache
    # rewrite) depending on pipeline timing. Row-shape filters keep each
    # checklist joined to the CORRECT market head in both layouts:
    #   draw   head = rows carrying the draw engine's Monte-Carlo fields;
    #   unders u25 = rows WITHOUT the u35 tier marker.
    draw_rows = [r for r in _head0(_load("draw", date))
                 if "mc_draw_prob" in r or "composite_draw_score" in r]
    unders_rows = [r for r in _head0(_load("unders", date))
                   if "u35_tier" not in r]

    # O2.5 forecast rows (Engine/over25_forecast.py) — the source of the
    # O2.5 engine's own council gates, joined by fixture for apex picks.
    o25f_rows = _rows(_load("over25_forecast", date))
    # gg_o15 composite heads: head0 = GG BTTS rows (sig1_mc_btts..sig5),
    # head1 = Over 1.5 rows (sig1_combined_lambda..sig5_fatigue_penalty).
    gg_o15_heads = _load_heads("gg_o15", date)
    ggc_rows = _head_n(gg_o15_heads, 0)
    o15c_rows = _head_n(gg_o15_heads, 1)
    # GG supreme rows themselves — the gg branch's psychology verdict lives
    # on the supreme row's own Psych_Score field (not on the composite head).
    gg_rows = _rows(_load("gg_supreme", date))

    # ── ID → CANONICAL LABEL REGISTRY ────────────────────────────────────────
    # Built from the engines that store BOTH the fixture id and a real
    # 'home vs away' label; the id-bearing majority wins, apex rows are added
    # LAST (they can store the fixture with its sides swapped), so a fixture
    # whose only saved row is an apex row still gets a label.
    underdog_base_rows = _rows(_load("underdog_base", date))
    underdog_audit_rows = _rows(_load("underdog_audit", date))
    fhvi_rows = _rows(_load("fhvi", date))
    shvi_rows = _rows(_load("shvi", date))
    label_cand = {}

    def _add_label(r):
        fid = _idstr(r.get("fixture_id"))
        label = _fixture_label(r)
        if not fid or not label:
            return
        bucket = label_cand.setdefault(fid, {})
        key = _norm(label)
        bucket[key] = (label, bucket.get(key, ("", 0))[1] + 1)

    for rows in (win_side_rows, underdog_base_rows, underdog_audit_rows,
                 draw_rows, unders_rows, o25f_rows, ggc_rows, o15c_rows,
                 gg_rows, dna_clash_rows, fhvi_rows, shvi_rows):
        for r in rows or []:
            _add_label(r)
    for fid, entry in (dmf or {}).items():
        if isinstance(entry, dict) and _fixture_label(entry):
            _add_label(dict(entry, fixture_id=fid))
    for r in win_apex_rows:
        _add_label(r)
    label_by_id = {
        fid: max(bucket.items(), key=lambda kv: kv[1][1])[1][0]
        for fid, bucket in label_cand.items() if bucket
    }

    dna_factors_by_id, dna_factors_by_name = {}, {}
    dna_draw_by_id, dna_draw_by_name = {}, {}
    if isinstance(dmf, dict):
        for fid, entry in dmf.items():
            if not isinstance(entry, dict):
                continue
            markets = entry.get("markets") or {}
            fkey = _idstr(fid)
            dna_factors_by_id[fkey] = markets
            label = entry.get("fixture")
            if label:
                key = _norm(label)
                dna_factors_by_name.setdefault(key, markets)
                dna_draw_by_id[fkey] = markets.get("draw") or {}
                dna_draw_by_name.setdefault(key, markets.get("draw") or {})

    snap = {
        # the date this snapshot was read from (every check reports it)
        "date": date,
        # fixture_id → canonical 'home vs away' label for this date
        "label_by_id": label_by_id,
        # per-side WIN rows
        "win_by_id": win_by_id,
        "win_by_name": win_by_name,
        # legacy name-keyed sources (id-less engines, existing convention)
        "wps_by_id": {}, "wps_by_name": _name_index(_rows(_load("win_psychology", date))),
        "gps_by_id": {}, "gps_by_name": _name_index(_rows(_load("gg_psychology", date))),
        "ops_by_id": {}, "ops_by_name": _name_index(_rows(_load("over25_psychology", date))),
        "u2s_by_id": {}, "u2s_by_name": _name_index(u2s_rows),
        "sot_by_id": {}, "sot_by_name": _name_index(_rows(_load("sot", date))),
        "fhvi_by_id": {}, "fhvi_by_name": _name_index(fhvi_rows),
        "shvi_by_id": {}, "shvi_by_name": _name_index(shvi_rows),
        "cagg_by_id": {}, "cagg_by_name": _name_index(corner_rows),
        # id-keyed sources (id may be str or int on disk — normalised to str)
        "ud_by_id": _id_index(underdog_base_rows),
        "ud_by_name": _name_index(underdog_base_rows),
        "uda_by_id": _id_index(underdog_audit_rows),
        "uda_by_name": _name_index(underdog_audit_rows),
        # Market-filtered composite rows (see shape filters above)
        "draw_by_id": _id_index(draw_rows),
        "draw_by_name": _name_index(draw_rows),
        "un_by_id": _id_index(unders_rows),
        "un_by_name": _name_index(unders_rows),
        # DNA v2 market factors (data/dna_v2_market_factors.json — disk-only)
        "dna_by_id": dna_factors_by_id,
        "dna_by_name": dna_factors_by_name,
        "dna_draw_by_id": dna_draw_by_id,
        "dna_draw_by_name": dna_draw_by_name,
        # per-team DNA profiles (Market_Power_Scores.Goal_Intent) — the WIN
        # Goal Intent fallback for fixtures without a market-factor entry
        "dna_prof_by_name": _dna_profiles(date),
        # O2.5 engine forecast rows + GG/O1.5 composite heads
        "o25f_by_id": _id_index(o25f_rows),
        "o25f_by_name": _name_index(o25f_rows),
        "ggc_by_id": _id_index(ggc_rows),
        "ggc_by_name": _name_index(ggc_rows),
        "o15c_by_id": _id_index(o15c_rows),
        "o15c_by_name": _name_index(o15c_rows),
        # GG supreme rows themselves (the gg branch's psychology verdict
        # lives on the supreme row's own Psych_Score field)
        "gsup_by_id": _id_index(gg_rows),
        "gsup_by_name": _name_index(gg_rows),
        # DNA engine's own per-fixture clash verdicts
        "dna_clash_by_id": _id_index(dna_clash_rows),
        "dna_clash_by_name": _name_index(dna_clash_rows),
        # raw per-fixture underdog identity rows (from the U2S feed itself)
        "u2s_rows": u2s_rows,
        "corner_rows": corner_rows,
    }
    _SNAPSHOTS[date] = snap
    _trim_window_cache(date)
    return snap
# ══════════════════════════════════════════════════════════════════════════════
# CROSS-DAY SOURCE RESOLUTION — the requested date is tried FIRST; only a
# genuine miss looks at the window (see the module docstring). Every helper
# returns the date that supplied the row so the check can report it.
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_any(date, prefix, fid, fxn):
    """(row, source_date) for one source across the date window, or (None, "").

    Cross-fixture guard: when a neighbouring date knows the SAME label under a
    DIFFERENT fixture id (two-legged ties, double-headers), that date is
    skipped — its row belongs to another fixture, not to this pick."""
    fid_s = _idstr(fid)
    for d in _window_dates(date):
        snap = _snapshot(d)
        if d != date and fid_s:
            known = snap.get("label_by_id") or {}
            if fxn:
                mapped = _label_fixture_id(snap, fxn)
                if mapped and mapped != fid_s:
                    continue
            elif known:
                continue
        row = _resolve(snap, prefix, fid_s, fxn)
        if row is not None:
            return row, d
    return None, ""


def _label_fixture_id(snap, label):
    """The fixture id a date's own id-bearing engines give a label (either
    orientation), or "" when that date has no such fixture."""
    key = _norm(label)
    if not key:
        return ""
    rev = _norm(_reverse_label(label))
    for fid, lab in (snap.get("label_by_id") or {}).items():
        k = _norm(lab)
        if k == key or (rev and k == rev):
            return fid
    return ""


def _canonical_label_any(date, fid, fxn):
    """(canonical label, source_date) for a fixture across the source window —
    the label that date's id-bearing engines agree on. Falls back to the
    calling row's own label when no date knows the fixture id."""
    fid_s = _idstr(fid)
    if fid_s:
        for d in _window_dates(date):
            lab = (_snapshot(d).get("label_by_id") or {}).get(fid_s, "")
            if lab:
                return lab, d
    return (fxn or ""), date


def _win_rows_any(date, fid, fxn):
    """(side_rows, source_date) for a fixture's WIN side rows. The canonical
    label of the supplying date is used when the calling row stored the
    fixture with its sides swapped."""
    fid_s = _idstr(fid)
    for d in _window_dates(date):
        snap = _snapshot(d)
        rows = []
        if fid_s:
            rows = list((snap.get("win_by_id") or {}).get(fid_s, []))
        if not rows and fxn:
            label = ""
            if fid_s:
                label = (snap.get("label_by_id") or {}).get(fid_s, "")
            if not label:
                label = fxn
            for key in (_norm(label), _norm(_reverse_label(label)), _norm(fxn)):
                if not key:
                    continue
                rows = list((snap.get("win_by_name") or {}).get(key, []))
                if rows:
                    break
        side_rows = [r for r in rows if r.get("team_name")]
        if side_rows:
            return side_rows, d
    return [], ""


def _win_side_trio(date, fid, fxn, team):
    """(selected row, opponent row, source_date) for one team's WIN side rows.

    The pair is the engine's own output shape: Engine/win_forecast.py always
    writes BOTH sides of a fixture, so the opponent's own row (its
    last_5_wins_overall / parity_score) is reachable from the same source."""
    rows, d = _win_rows_any(date, fid, fxn)
    if not rows:
        return None, None, ""
    t = _norm(team or "")
    if not t:
        return rows[0], None, d
    mine = next((r for r in rows if _norm(r.get("team_name") or "") == t), None)
    theirs = next((r for r in rows if _norm(r.get("team_name") or "") != t), None)
    return mine, theirs, d


def _win_side_row_any(date, fid, fxn, team):
    row, _opp, d = _win_side_trio(date, fid, fxn, team)
    return row, d
# ══════════════════════════════════════════════════════════════════════════════
# RULE EVALUATION PRIMITIVES (one pre-existing field/verdict each)
# ══════════════════════════════════════════════════════════════════════════════

def _psych_side(snap, prefix, fid, fxn, side):
    """Psychology signed net score for ONE side of a fixture (PSYCHOLOGY
    engines compute H_Base and A_Base per fixture — the net score is signed
    toward the home or away team, NOT a 0-100 percentage). Fixture-level
    audits (side=None) fall back to the row's OWN psych verdict when the
    side base pair is absent (e.g. gg_psychology rows carry Psych_Score but
    no H_Base/A_Base) — the intelligence EXISTS, so it must not read N/A."""
    row = _resolve(snap, prefix, fid, fxn)
    if not row:
        return NOT_AVAILABLE
    if side in ("home", "away"):
        h, a = _num(row.get("H_Base")), _num(row.get("A_Base"))
        if h is None or a is None:
            return NOT_AVAILABLE
        if side == "home":
            return PASS if (h - a) > 0 else FAIL
        return PASS if (a - h) > 0 else FAIL
    # Market/fixture-level row (no side): its own signed audit score is the
    # verdict. Coerce — psych engines store numeric strings ("+162").
    ps = _num(row.get("Psych_Score"))
    if ps is None:
        ps = _num(row.get("Audit_Score"))
    if ps is None:
        return NOT_AVAILABLE
    return PASS if ps > INTELLIGENT_PASS_RULES["PSYCHOLOGY_NET_SCORE_PASS"] else FAIL


def _dna_factors(snap, fid, fxn, market):
    """Factor list of one existing DNA v2 market (win/gg/over25/over15/
    unders/draw/corners) for this fixture, from the market-factors breakdown
    produced by CORE/dna_v2_market_factors.py off Market_Power_Scores."""
    markets = _resolve(snap, "dna", fid, fxn)
    if not markets:
        return None
    mv = markets.get(market) or {}
    factors = mv.get("factors") or []
    return factors or None


def _dna_factor(factors, name):
    return next((f for f in factors if f.get("name") == name), None)


def _win_res(result, value=None, threshold=None, source="", field="", mapping=""):
    """One WIN check's payload — the rule result plus its provenance
    (source engine + date, source field, team/side mapping) so the report can
    show exactly where every value came from."""
    return {"result": result, "value": value, "threshold": threshold,
            "source": source, "field": field, "mapping": mapping}


def _win_goal_intent_check(date, fid, fxn, target):
    """WIN Goal Intent — the predicted team's existing DNA Goal Intent (0-100)
    must beat its opponent's. Preferred source: the fixture's own market-factor
    breakdown (CORE/dna_v2_market_factors.py, over25 → "Goal Intent"
    home_value/away_value). Fallback for fixtures that pass did not cover: the
    same engine's per-team profiles (Market_Power_Scores.Goal_Intent) for both
    named sides — identical field and scale, so no normalisation is added."""
    canon, _cd = _canonical_label_any(date, fid, fxn)
    label = canon or fxn or ""
    home, away = _split_fixture(label)
    t_n, h_n, a_n = _norm(target), _norm(home), _norm(away)
    if not t_n or t_n not in (h_n, a_n):
        return _win_res(NOT_AVAILABLE,
                        source="dna_market_factors / dna profiles",
                        field="Goal Intent",
                        mapping=f"{target} = neither side of '{label}'")
    markets, d = _resolve_any(date, "dna", fid, label)
    goal = _dna_factor((markets or {}).get("over25", {}).get("factors") or [],
                       "Goal Intent")
    if goal:
        tv = _num(goal.get("home_value") if t_n == h_n else goal.get("away_value"))
        ov = _num(goal.get("away_value") if t_n == h_n else goal.get("home_value"))
        if tv is not None and ov is not None:
            return _win_res(PASS if tv > ov else FAIL,
                            value={"team": tv, "opp": ov},
                            threshold="team Goal Intent > opponent (0-100)",
                            source=f"dna_market_factors @ {d}",
                            field="Goal Intent (home_value/away_value)",
                            mapping=f"{target} = {'home' if t_n == h_n else 'away'}")
    prof = _snapshot(d or date).get("dna_prof_by_name") or {}
    opp_name = away if t_n == h_n else home
    pt, po = prof.get(t_n), prof.get(_norm(opp_name))
    if pt and po:
        tv = _num((pt.get("Market_Power_Scores") or {}).get("Goal_Intent"))
        ov = _num((po.get("Market_Power_Scores") or {}).get("Goal_Intent"))
        if tv is not None and ov is not None:
            return _win_res(PASS if tv > ov else FAIL,
                            value={"team": tv, "opp": ov},
                            threshold="team Goal Intent > opponent (0-100)",
                            source=f"dna profiles @ {d or date}",
                            field="Market_Power_Scores.Goal_Intent",
                            mapping=f"{target} vs {opp_name}")
    return _win_res(NOT_AVAILABLE,
                    source="dna_market_factors / dna profiles",
                    field="Goal Intent",
                    mapping=f"{target} = no DNA Goal Intent in the window")


def _win_sot_check(date, fid, fxn, target):
    """WIN SOT — the predicted team's OWN side SOT expectancy from the U2S
    engine (the WIN page's "SOT Expectancy (Dog)/(Fav)" columns:
    Dog_Venue_SOT / Fav_Venue_SOT), evaluated with the engine's own Tier-A1
    comparison (a side's expectancy must be strictly greater; a tie awards
    nothing). The row's Underdog column names the dog, so the predicted team's
    side is read, never re-derived from odds."""
    row, d = _resolve_any(date, "u2s", fid, fxn)
    if not row:
        return _win_res(NOT_AVAILABLE, source="u2s_psychology",
                        field="Dog_Venue_SOT / Fav_Venue_SOT",
                        mapping=f"{target} = no U2S row in the source window")
    dog = str(row.get("Underdog") or "")
    t_n, dog_n = _norm(target), _norm(dog)
    canon, _cd = _canonical_label_any(date, fid, fxn)
    home, away = _split_fixture(canon or fxn or "")
    if not t_n or t_n not in (_norm(home), _norm(away)):
        return _win_res(NOT_AVAILABLE, source=f"u2s_psychology @ {d}",
                        field="Dog_Venue_SOT / Fav_Venue_SOT",
                        mapping=f"{target} = not a side of '{canon or fxn}'")
    side = "dog" if t_n == dog_n else "fav"
    t_field = "Dog_Venue_SOT" if side == "dog" else "Fav_Venue_SOT"
    o_field = "Fav_Venue_SOT" if side == "dog" else "Dog_Venue_SOT"
    tv, ov = _num(row.get(t_field)), _num(row.get(o_field))
    if tv is None or ov is None:
        return _win_res(NOT_AVAILABLE, source=f"u2s_psychology @ {d}",
                        field=t_field, mapping=f"{target} = {side.upper()}")
    return _win_res(PASS if tv > ov else FAIL,
                    value={"side": side, "team_sot": tv, "opp_sot": ov},
                    threshold="team SOT expectancy > opponent (U2S Tier A1)",
                    source=f"u2s_psychology @ {d}",
                    field=f"{t_field} vs {o_field}",
                    mapping=f"{target} = {side.upper()} (U2S Underdog={dog})")


def _dna_clash_signal(snap, fid, fxn, market_signals_key):
    """The DNA engine's OWN per-fixture verdict (CORE/dna_engine_v2.py
    `market_signals` on the fixture clash row): Over_Under / GG_NoGG /
    Corners. Returns (verdict_string, clash_row) or (None, None)."""
    clash = _resolve(snap, "dna_clash", fid, fxn)
    if not clash:
        return None, None
    ms = clash.get("market_signals") or {}
    v = ms.get(market_signals_key)
    if v is None:
        return None, None
    return str(v).strip(), clash


def _dna_over_signal(snap, fid, fxn, market="over25"):
    """The DNA engine's own Over/Under verdict for this fixture.
    PRIMARY source: the engine's clash `market_signals.Over_Under`
    (STRONG OVER / LEAN OVER / LEAN UNDER / NEUTRAL) — a verbatim verdict,
    no arithmetic at all.
    FALLBACK (fixture absent from the clash set): the engine's documented
    aggregation of its own Market_Power_Scores — combined_goal_intent and
    combined_box_dominance are the two sides' average, and the engine's own
    LEAN OVER line is `box > 55 or intent > 55` (dna_engine_v2 L576-593).
    Returns (result, value).
    """
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "Over_Under")
    if verdict is not None:
        up = verdict.upper()
        is_over = up in ("STRONG OVER", "LEAN OVER")
        value = {"dna_signal": verdict}
        if clash:
            value["combined_goal_intent"] = clash.get("combined_goal_intent")
            value["combined_box_dominance"] = clash.get("combined_box_dominance")
        return (PASS if is_over else FAIL), value

    factors = _dna_factors(snap, fid, fxn, market)
    if not factors:
        return NOT_AVAILABLE, None
    gi = _dna_factor(factors, "Goal Intent")
    bd = _dna_factor(factors, "Box Dominance")
    if not gi and not bd:
        return NOT_AVAILABLE, None

    def _avg(f):
        if not f:
            return None
        hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
        if hv is None and av is None:
            return None
        return ((hv or 0) + (av or 0)) / 2.0

    intent_avg, box_avg = _avg(gi), _avg(bd)
    if intent_avg is None and box_avg is None:
        return NOT_AVAILABLE, None
    cut = INTELLIGENT_PASS_RULES["DNA_OVER_LEAN_CUT"]
    is_over = (box_avg is not None and box_avg > cut) or \
              (intent_avg is not None and intent_avg > cut)
    signal = ("STRONG OVER" if (box_avg or 0) > 70 and (intent_avg or 0) > 65
              else "LEAN OVER" if is_over else "NOT OVER")
    value = {"combined_goal_intent": None if intent_avg is None else round(intent_avg, 1),
             "combined_box_dominance": None if box_avg is None else round(box_avg, 1),
             "dna_signal": signal}
    return (PASS if is_over else FAIL), value


def _dna_gg_signal(snap, fid, fxn):
    """The DNA engine's own GG/No-GG verdict (market_signals.GG_NoGG)."""
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "GG_NoGG")
    if verdict is None:
        return NOT_AVAILABLE, None
    up = verdict.upper()
    value = {"dna_signal": verdict}
    if clash:
        value["combined_goal_intent"] = clash.get("combined_goal_intent")
        value["combined_box_dominance"] = clash.get("combined_box_dominance")
    return (PASS if up in ("STRONG GG", "LEAN GG") else FAIL), value


def _dna_corners_signal(snap, fid, fxn):
    """The DNA engine's own corners verdict (market_signals.Corners)."""
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "Corners")
    if verdict is None:
        return NOT_AVAILABLE, None
    value = {"dna_signal": verdict}
    if clash:
        value["combined_box_dominance"] = clash.get("combined_box_dominance")
        value["overall_structural_edge"] = clash.get("overall_structural_edge")
    return (PASS if verdict.upper() == "HIGH CORNERS" else FAIL), value


def _dna_side_factor_check(snap, fid, fxn, market, factor_name, home_cut, away_cut):
    """Generic per-side DNA factor gate reusing a producing engine's own
    thresholds (home_cut / away_cut). Returns (result, value)."""
    factors = _dna_factors(snap, fid, fxn, market)
    f = _dna_factor(factors or [], factor_name)
    if not f:
        return NOT_AVAILABLE, None
    hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
    if hv is None or av is None:
        return NOT_AVAILABLE, None
    return (PASS if hv > home_cut and av > away_cut else FAIL), \
        {"home_value": f.get("home_value"), "away_value": f.get("away_value")}


def _dna_corner_power(snap, fid, fxn):
    """Reuses the DNA engine's HIGH CORNERS gate (L606-607): either side's
    Corner_Power > 70. Returns (result, value)."""
    factors = _dna_factors(snap, fid, fxn, "corners")
    f = _dna_factor(factors or [], "Corner Power")
    if not f:
        return NOT_AVAILABLE, None
    hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
    if hv is None and av is None:
        return NOT_AVAILABLE, None
    cut = INTELLIGENT_PASS_RULES["DNA_HIGH_CORNERS_CUT"]
    return (PASS if (hv or 0) > cut or (av or 0) > cut else FAIL), \
        {"home_value": f.get("home_value"), "away_value": f.get("away_value")}


def _gg_signal_checks(row, sig_map):
    """Engine-native GG / O1.5 composite signal checks: the engine awards a
    signal's points ONLY when it fires (Engine/gg_precision_engine.py), so
    points > 0 == fired == PASS. No thresholds are invented here.
    Returns (checks, applicable_count)."""
    checks = []
    for name, field in sig_map:
        v = _num(row.get(field))
        if v is None:
            checks.append({"name": name, "result": NOT_AVAILABLE,
                           "value": None, "threshold": "fired (points > 0)"})
        else:
            checks.append({"name": name, "result": PASS if v > 0 else FAIL,
                           "value": row.get(field),
                           "threshold": "fired (points > 0)"})
    return checks


def _u2s_row_for(snap, fid, fxn, row_id, row_fixture):
    """The fixture's U2S psychology row + its named underdog team. The U2S
    feed itself is the identity source (its 'Underdog' field names the dog) —
    no cross-file team guessing."""
    row = _resolve(snap, "u2s", row_id, row_fixture or fxn)
    if not row:
        return None, None
    return row, row.get("Underdog")


def _dna_parity_eval(snap, fid, fxn):
    """DRAW DNA parity: |home_count - away_count| over the existing draw
    market factor counts. 0/1 → PASS, anything else → FAIL (user rule)."""
    mk = _resolve(snap, "dna_draw", fid, fxn)
    if not mk:
        return NOT_AVAILABLE
    h, a = _num(mk.get("home_count")), _num(mk.get("away_count"))
    if h is None or a is None:
        return NOT_AVAILABLE
    return PASS if int(abs(h - a)) in INTELLIGENT_PASS_RULES["DRAW_DNA_PARITY_PASS_VALUES"] else FAIL


def _win_side_row(snap, fid, fxn, team):
    """The WIN side row for the selected team (parity_score is signed per
    side by the producer)."""
    fid = str(fid) if fid not in (None, "") else ""
    if fid:
        for r in (snap.get("win_by_id") or {}).get(fid, []):
            if _norm(r.get("team_name") or "") == _norm(team or ""):
                return r
    fx_key = _norm(fxn or "")
    for r in (snap.get("win_by_name") or {}).get(fx_key, []):
        if _norm(r.get("team_name") or "") == _norm(team or ""):
            return r
    return None


def _win_parity_eval(date, fid, fxn, team, src_row=None):
    """WIN Parity +10 — the selected team's OWN row already carries its signed
    advantage vs this opponent (Engine/win_forecast.py stores
    parity_diff if side==home else -parity_diff). PASS = >= +10.
    When the calling row itself is that side row (win_forecast/win_raw rows
    are), its own value is authoritative and the join is skipped — otherwise
    the fixture's side rows are resolved across the source window."""
    v = _num(src_row.get("parity_score")) if isinstance(src_row, dict) else None
    if v is not None:
        return _win_res(PASS if v >= INTELLIGENT_PASS_RULES["WIN_PARITY_THRESHOLD"] else FAIL,
                        value=v, threshold=">= +10",
                        source="calling row", field="parity_score",
                        mapping=f"{team} = the row's own side")
    r, d = _win_side_row_any(date, fid, fxn, team)
    if not r:
        return _win_res(NOT_AVAILABLE, threshold=">= +10",
                        source="win_raw/win_forecast", field="parity_score",
                        mapping=f"{team} = no saved side row in the window")
    v = _num(r.get("parity_score"))
    if v is None:
        return _win_res(NOT_AVAILABLE, threshold=">= +10",
                        source=f"win_raw/win_forecast @ {d}", field="parity_score")
    return _win_res(PASS if v >= INTELLIGENT_PASS_RULES["WIN_PARITY_THRESHOLD"] else FAIL,
                    value=v, threshold=">= +10",
                    source=f"win_raw/win_forecast @ {d}", field="parity_score",
                    mapping=f"{team} = {r.get('side') or 'selected'} side row")


def _win_form_eval(date, fid, fxn, team, src_row=None):
    """WIN Form — the predicted team's existing last-5 WINS vs the opponent's
    own side row's last-5 WINS (both counters come from the same
    Engine/win_forecast.py pair). The row's own goals counters are the
    documented fallback when the opponent's wins counter is absent."""
    mine, opp, d = _win_side_trio(date, fid, fxn, team)
    # The calling row's OWN wins counter is authoritative when present — the
    # same precedence as the parity check (the audited WIN row IS the
    # predicted team's engine row, so its counter outranks the saved pair).
    src_w = _num(src_row.get("last_5_wins_overall")) if isinstance(src_row, dict) else None
    if src_w is not None and opp is not None:
        ow = _num(opp.get("last_5_wins_overall"))
        if ow is not None:
            return _win_res(PASS if src_w > ow else FAIL,
                            value={"team_wins": src_w, "opp_wins": ow},
                            threshold="team last-5 wins > opponent last-5 wins",
                            source=f"calling row + win_raw/win_forecast @ {d}",
                            field="last_5_wins_overall",
                            mapping=f"{team} (calling row) vs opponent's own row")
    # Goals fallback stays INSIDE the same engine's output shape: a side row
    # carries BOTH its own goals and the opponent's (opp_last_5_goals_scored),
    # so the calling row can stand in when the registered pair misses it.
    if mine is None and isinstance(src_row, dict) \
            and _num(src_row.get("last_5_goals_scored")) is not None:
        mine, opp = src_row, None
    if mine is None:
        return _win_res(NOT_AVAILABLE,
                        source="win_raw/win_forecast",
                        field="last_5_wins_overall",
                        mapping=f"{team} = no saved side row in the window")
    w, ow = _num(mine.get("last_5_wins_overall")), _num(opp.get("last_5_wins_overall")) if opp else None
    if w is not None and ow is not None:
        return _win_res(PASS if w > ow else FAIL,
                        value={"team_wins": w, "opp_wins": ow},
                        threshold="team last-5 wins > opponent last-5 wins",
                        source=f"win_raw/win_forecast @ {d}",
                        field="last_5_wins_overall",
                        mapping=f"{team} vs {opp.get('team_name')}")
    gs, og = _num(mine.get("last_5_goals_scored")), _num(mine.get("opp_last_5_goals_scored"))
    if gs is None or og is None:
        return _win_res(NOT_AVAILABLE, source=f"win_raw/win_forecast @ {d}",
                        field="last_5_wins_overall")
    return _win_res(PASS if gs > og else FAIL, value={"team": gs, "opp": og},
                    threshold="team last-5 goals > opponent last-5 goals (fallback)",
                    source=f"win_raw/win_forecast @ {d}",
                    field="last_5_goals_scored",
                    mapping=f"{team} vs opponent's own row")



def _win_corners_check(date, fid, fxn, target):
    """WIN Corners — the predicted team must also be the fixture's TRUE corner
    favourite (AGGREGATOR/corner4_aggregator.py "TRUE FAVOURITE RESOLUTION":
    True_Corner_Fav is the side with the higher syndicate corner score)."""
    c, d = _resolve_any(date, "cagg", fid, fxn)
    if not c:
        return _win_res(NOT_AVAILABLE, source="corners_aggregator",
                        field="True_Corner_Fav",
                        mapping=f"{target} = no corner row in the source window")
    fav = str(c.get("True_Corner_Fav") or "")
    if not fav:
        return _win_res(NOT_AVAILABLE, source=f"corners_aggregator @ {d}",
                        field="True_Corner_Fav")
    h_team = c.get("Home_Team")
    is_home = _norm(target) == _norm(h_team) or (
        not h_team and _norm(target) == _norm(_split_fixture(fxn)[0]))
    t_score = c.get("Home_Score") if is_home else c.get("Away_Score")
    o_score = c.get("Away_Score") if is_home else c.get("Home_Score")
    return _win_res(PASS if _norm(fav) == _norm(target) else FAIL,
                    value={"true_corner_fav": fav, "team_corner_score": t_score,
                           "opp_corner_score": o_score,
                           "Total_Exp": c.get("Total_Exp")},
                    threshold="predicted team == True_Corner_Fav",
                    source=f"corners_aggregator @ {d}",
                    field="True_Corner_Fav (Home_Score vs Away_Score)",
                    mapping=f"{target} vs corner favourite '{fav}'")


def _win_psych_check(date, fid, fxn, target, side, src_row=None):
    """WIN Psychology — the predicted team's OWN signed psychology net.
    PSYCHOLOGY/win_psychology.py H_Base/A_Base are signed per side
    (Audit_Score is |H-A|) and the engine itself marks a row OVERTURNED when
    the picked side's base goes negative. PASS = the predicted side's net > 0.
    A fixture-level audit score is only the documented fallback when the side
    pair (or the side mapping) is unavailable."""
    if side in ("home", "away") and isinstance(src_row, dict):
        h, a = _num(src_row.get("H_Base")), _num(src_row.get("A_Base"))
        if h is not None and a is not None:
            v = h if side == "home" else a
            return _win_res(PASS if v > INTELLIGENT_PASS_RULES["PSYCHOLOGY_NET_SCORE_PASS"] else FAIL,
                            value=v, threshold="signed net > 0",
                            source="calling row", field="H_Base/A_Base",
                            mapping=f"{target} = {side} side net")
    row, d = _resolve_any(date, "wps", fid, fxn)
    if row and side in ("home", "away"):
        h, a = _num(row.get("H_Base")), _num(row.get("A_Base"))
        if h is not None and a is not None:
            v = h if side == "home" else a
            return _win_res(PASS if v > INTELLIGENT_PASS_RULES["PSYCHOLOGY_NET_SCORE_PASS"] else FAIL,
                            value=v, threshold="signed net > 0",
                            source=f"win_psychology @ {d}", field="H_Base/A_Base",
                            mapping=f"{target} = {side} side net")
    psych_srcs = []
    if isinstance(src_row, dict):
        psych_srcs.append(("calling row", src_row))
    if row:
        psych_srcs.append((f"win_psychology @ {d}", row))
    for src, srow in psych_srcs:
        for val in ("Psych_Score", "Audit_Score"):
            v = _num(srow.get(val))
            if v is not None:
                return _win_res(PASS if v > INTELLIGENT_PASS_RULES["PSYCHOLOGY_NET_SCORE_PASS"] else FAIL,
                                value=v, threshold="signed net > 0",
                                source=src, field=val,
                                mapping=f"{target} (fixture-level net)")
    return _win_res(NOT_AVAILABLE, source="win_psychology",
                    field="H_Base/A_Base",
                    mapping=f"{target} = no psychology row in the source window")


def _win_underdog_check(date, fid, fxn):
    """WIN Underdog — the existing longshot gate on the fixture's dog
    (master_underdog_audit Dog_Score_Prob, 0-100 "%"): PASS when the underdog
    scores less than half the time. underdog_engine's dog_score_prob is the
    same field of the same engine family, used when the audit row is absent."""
    cut = INTELLIGENT_PASS_RULES["WIN_UNDERDOG_SCORE_PROB_MAX"]
    for prefix, field, label in (("uda", "Dog_Score_Prob", "underdog_audit"),
                                 ("ud", "dog_score_prob", "underdog_base")):
        row, d = _resolve_any(date, prefix, fid, fxn)
        if not row:
            continue
        p = _frac(row.get(field))
        if p is None:
            continue
        return _win_res(PASS if p < cut / 100.0 else FAIL,
                        value=row.get(field), threshold=f"< {cut}%",
                        source=f"{label} @ {d}", field=field,
                        mapping=f"dog = {row.get('underdog_team') or 'the fixture underdog'}")
    return _win_res(NOT_AVAILABLE,
                    source="underdog_audit / underdog_base",
                    field="Dog_Score_Prob",
                    mapping="fixture not covered by the underdog engines")


def _win_draw_check(date, fid, fxn, src_row=None):
    """WIN Draw Probability — below 20% the win side is clean. Primary source:
    the draw engine's own Monte Carlo mc_draw_prob (0-1 float). When the
    fixture has no draw row, the pick's OWN Monte_Draw_Prob (the WIN apex
    engine's draw risk, stored as a 0-100 number) is compared against the same
    20% cut in its own representation."""
    r, d = _resolve_any(date, "draw", fid, fxn)
    if r is not None:
        f = _frac(r.get("mc_draw_prob"))
        if f is None:
            return _win_res(NOT_AVAILABLE, source=f"draw @ {d}",
                            field="mc_draw_prob")
        return _win_res(PASS if f < INTELLIGENT_PASS_RULES["WIN_DRAW_PROB_MAX"] else FAIL,
                        value=r.get("mc_draw_prob"), threshold="< 0.20 (20%)",
                        source=f"draw @ {d}", field="mc_draw_prob",
                        mapping="fixture-level Monte Carlo draw probability")
    if isinstance(src_row, dict):
        raw = _num(src_row.get("Monte_Draw_Prob"))
        if raw is not None:
            return _win_res(PASS if raw < INTELLIGENT_PASS_RULES["WIN_DRAW_PROB_MAX_PCT"] else FAIL,
                            value=raw,
                            threshold=f"< {INTELLIGENT_PASS_RULES['WIN_DRAW_PROB_MAX_PCT']} (20%)",
                            source="calling row (WIN apex)",
                            field="Monte_Draw_Prob",
                            mapping="the pick's own draw risk (0-100 scale)")
    return _win_res(NOT_AVAILABLE, source="draw / Monte_Draw_Prob",
                    field="mc_draw_prob / Monte_Draw_Prob",
                    mapping="no draw intelligence for this fixture in the window")


def _dog_att_eval(snap, fid, fxn):
    """DOG ATT STRENGTH — underdog_base Dixon-Coles attack multiplier
    (~1.0-centred; higher = stronger dog attack). Repo-native direction >=."""
    r = _resolve(snap, "ud", fid, fxn)
    if not r:
        return NOT_AVAILABLE
    v = _num(r.get("dog_att_strength"))
    if v is None:
        return NOT_AVAILABLE
    return PASS if v >= INTELLIGENT_PASS_RULES["UNDERDOG_DOG_ATT_STRENGTH_THRESHOLD"] else FAIL


def _fav_def_eval(snap, fid, fxn):
    """FAV DEF WEAKNESS — underdog_base favourite defensive-weakness
    multiplier (higher = concedes more). Repo-native direction >=."""
    r = _resolve(snap, "ud", fid, fxn)
    if not r:
        return NOT_AVAILABLE
    v = _num(r.get("fav_def_weakness"))
    if v is None:
        return NOT_AVAILABLE
    return PASS if v >= INTELLIGENT_PASS_RULES["UNDERDOG_FAV_DEF_WEAKNESS_THRESHOLD"] else FAIL
# ══════════════════════════════════════════════════════════════════════════════
# MARKET CHECKLISTS — the denominator is FIXED per market: it is ALWAYS the
# branch's full rule set, regardless of whether a given fixture's inputs exist.
# Missing intelligence → NOT_AVAILABLE, which lowers the NUMERATOR only (never
# a fake FAIL and never a smaller denominator): the same market always shows
# the same total (WIN=x/8, GG=x/4 …) and only x varies per pick.
# ══════════════════════════════════════════════════════════════════════════════

def _checks_for_market(market, snap, row, fid, fxn, date=None):
    """Return [{name, result, value, threshold, source, field, mapping}]."""
    rules = INTELLIGENT_PASS_RULES
    req_date = date or snap.get("date") or ""
    home, away = _split_fixture(fxn)
    fid_s = _idstr(fid)
    checks = []

    def add(name, result, value=None, threshold=None,
            source="", field="", mapping=""):
        checks.append({"name": name, "result": result, "value": value,
                       "threshold": threshold, "source": source,
                       "field": field, "mapping": mapping})

    # ── WIN (apex/forecast/raw/psychology picks: the predicted team, by id) ──
    if market in ("win_apex", "win_forecast", "win_raw", "win_psychology"):
        target = str(row.get("Target") or row.get("team_name")
                     or row.get("Master_Pick") or "")
        # Resolve the fixture's canonical 'home vs away' label from the
        # id-bearing engines before any side or name join is made.
        canon, _label_date = _canonical_label_any(req_date, fid_s, fxn)
        if canon:
            fxn = canon
            home, away = _split_fixture(fxn)
        if not fxn and target:
            # Row carries no fixture label (some side rows are keyed by id
            # only) — take the label from the fixture's WIN side row.
            probe = _win_side_row(snap, fid_s, "", target)
            if probe:
                fxn = _fixture_label(probe)
                home, away = _split_fixture(fxn)
        side = ("home" if _norm(target) == _norm(home)
                else "away" if target and _norm(target) == _norm(away) else None)
        if target and side is None:
            # First-leg rows carry 'PSG (agg lead)' style labels (append_leg2)
            # — the anchor 'X vs Y' still identifies the side (same fixture).
            side = ("home" if _norm(home) and _norm(home) in _norm(target)
                    else "away" if _norm(away) and _norm(away) in _norm(target) else None)
        if not target or (not side):
            # FIXED DENOMINATOR: even with no pickable side, the WIN audit
            # always carries its FULL 8-rule set (see the rule order below) —
            # the denominator must never depend on row shape.
            for _name in ("SOT", "Corners", "Psychology", "Underdog",
                          "Goal Intent", "Draw Probability", "Parity +10",
                          "Form"):
                add(_name, NOT_AVAILABLE, field=_WIN_FIELDS.get(_name, ""),
                    mapping=f"{target or '?'} = no side mapping")
            return checks
        # 1. SOT expectancy (U2S per-side intelligence, matched by fav/dog)
        r = _win_sot_check(req_date, fid_s, fxn, target)
        add("SOT", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        # 2. Corners (predicted team must be the True_Corner_Fav)
        r = _win_corners_check(req_date, fid_s, fxn, target)
        add("Corners", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        # 3. Psychology — the predicted team's OWN signed side net
        r = _win_psych_check(req_date, fid_s, fxn, target, side, row)
        add("Psychology", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 4. Underdog gate (existing dog_score_prob "<50%" longshot rule)
        r = _win_underdog_check(req_date, fid_s, fxn)
        add("Underdog", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 5. Goal Intent (predicted team's DNA Goal Intent vs opponent's)
        r = _win_goal_intent_check(req_date, fid_s, fxn, target)
        add("Goal Intent", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 6. Draw probability — PASS below 20% (user rule), existing field
        r = _win_draw_check(req_date, fid_s, fxn, row)
        add("Draw Probability", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 7. Parity +10 (win_forecast engine's signed parity_score, own row)
        r = _win_parity_eval(req_date, fid_s, fxn, target, row)
        add("Parity +10", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 8. Form (existing last-5 counters, team vs opponent)
        r = _win_form_eval(req_date, fid_s, fxn, target, row)
        add("Form", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        return checks

    # ── WIN PSYCHOLOGY — same WIN pick, same ONE WIN checklist ────────────────
    # The WIN page's psychology table is another WIN pick (Master_Pick), and
    # supporting-engine identity must never pick the checklist (§15). Its
    # audit is therefore the COMPLETE WIN ruleset above: seed the predicted
    # team from this row and run the same eight checks.
    if market == "win_psychology":
        target = str(row.get("Master_Pick") or row.get("Target")
                     or row.get("team_name") or "")
        if target:
            row = dict(row, Target=target)
        return _checks_for_market("win_apex", snap, row, fid, fxn, date=req_date)
    # ── GG / BTTS ────────────────────────────────────────────────────────────
    if market == "gg_supreme":
        ps_val = _num(row.get("Psych_Score"))
        if ps_val is not None:
            add("Psychology", PASS if ps_val > 0 else FAIL, value=row.get("Psych_Score"))
        else:
            add("Psychology", _psych_side(snap, "gps", fid_s, fxn, None))
        # GG Goalkeeper — gg_precision_engine gk_bonus: a LIABLE GK boosts
        # BTTS (+10 if both, +5 if one). The engine's own boolean flags are
        # on the GG composite row; the cpg > 1.10 gate is the engine's own
        # liability line (GK_LIABILITY_CPG). Unders u25 rows are used only as
        # a fallback source when the GG row is unavailable.
        gk = _resolve(snap, "ggc", fid_s, fxn) or _resolve(snap, "un", fid_s, fxn)
        if not gk:
            add("Goalkeeper", NOT_AVAILABLE)
        else:
            hl, al = gk.get("home_gk_liable"), gk.get("away_gk_liable")
            hc, ac = _num(gk.get("home_gk_cpg")), _num(gk.get("away_gk_cpg"))
            limit = rules["GG_GK_LIABILITY_CPG"]
            if hl is None and al is None and hc is None and ac is None:
                add("Goalkeeper", NOT_AVAILABLE)
            elif bool(hl) or bool(al):
                add("Goalkeeper", PASS,
                    value={"home_gk_cpg": gk.get("home_gk_cpg"),
                           "away_gk_cpg": gk.get("away_gk_cpg"),
                           "home_gk_liable": hl, "away_gk_liable": al},
                    threshold=f"liable (engine flag) / cpg > {limit}")
            elif hl is False and al is False:
                add("Goalkeeper", FAIL,
                    value={"home_gk_liable": hl, "away_gk_liable": al},
                    threshold="either GK liable")
            else:
                add("Goalkeeper", PASS if (hc or 0) > limit or (ac or 0) > limit else FAIL,
                    value={"home_gk_cpg": gk.get("home_gk_cpg"),
                           "away_gk_cpg": gk.get("away_gk_cpg")},
                    threshold=f"either > {limit}")
        # GOAL INTENT → prefers the DNA engine's OWN GG verdict
        # (market_signals.GG_NoGG); falls back to its clash gates
        # (CORE/dna_engine_v2.py L597-600):
        #   STRONG GG : BTTS_Friction home_score > 65 AND away_score > 55
        #   LEAN GG   : combined box dominance > 60
        fr_res, fr_val = _dna_side_factor_check(
            snap, fid_s, fxn, "gg", "BTTS Friction",
            rules["DNA_GG_FRICTION_HOME"], rules["DNA_GG_FRICTION_AWAY"])
        add("BTTS Friction", fr_res, value=fr_val,
            threshold=f"home > {rules['DNA_GG_FRICTION_HOME']} and away > {rules['DNA_GG_FRICTION_AWAY']}")
        gg_sig_res, gg_sig_val = _dna_gg_signal(snap, fid_s, fxn)
        if gg_sig_res == NOT_AVAILABLE:
            gg_sig_res, gg_sig_val = _dna_over_signal(snap, fid_s, fxn, "gg")
        add("Goal Intent", gg_sig_res, value=gg_sig_val,
            threshold="DNA GG verdict (STRONG GG / LEAN GG)")
        return checks

    # ── GG PRECISION composite rows (gg_o15 head0 — the same engine's BTTS
    # composite). Reuses the engine's OWN 5 signals: points are awarded only
    # when a signal fires (Engine/gg_precision_engine.py calculate_gg_score),
    # so `points > 0` == fired == PASS. No thresholds invented.
    if market == "gg_precision":
        checks.extend(_gg_signal_checks(row, (
            ("MC BTTS", "sig1_mc_btts"),
            ("Venue BTTS", "sig2_venue_btts"),
            ("GK Vulnerability", "sig3_gk_vuln"),
            ("H2H BTTS", "sig4_h2h_btts"),
            ("Directional Intent", "sig5_directional"),
        )))
        return checks

    # ── O1.5 composite rows (gg_o15 head1 — the Over-1.5 precision engine).
    # Reuses that engine's own inputs/gates verbatim:
    #   sig1 saturation combined_lambda / 2.5  → combined λ >= 2.5 maxes it
    #   intent_bonus  λ_home >= 1.00 AND λ_away >= 1.00
    #   gk flags      home_gk_liable / away_gk_liable
    #   DNA over signal (existing DNA engine clash output for this market)
    if market == "gg_o15":
        lam = _num(row.get("combined_lambda"))
        if lam is None:
            add("Combined Lambda", NOT_AVAILABLE)
        else:
            sat = rules["O15_COMBINED_LAMBDA_SAT"]
            add("Combined Lambda", PASS if lam >= sat else FAIL,
                value=row.get("combined_lambda"), threshold=f">= {sat} (sig1 saturation)")
        lh, la = _num(row.get("lambda_home")), _num(row.get("lambda_away"))
        if lh is None or la is None:
            add("Attacking Intent", NOT_AVAILABLE)
        else:
            mn = rules["O15_LAMBDA_INTENT_MIN"]
            add("Attacking Intent", PASS if lh >= mn and la >= mn else FAIL,
                value={"lambda_home": row.get("lambda_home"),
                       "lambda_away": row.get("lambda_away")},
                threshold=f"both >= {mn} (intent_bonus gate)")
        hl, al = row.get("home_gk_liable"), row.get("away_gk_liable")
        if hl is None and al is None:
            add("Goalkeeper Leak", NOT_AVAILABLE)
        else:
            add("Goalkeeper Leak", PASS if bool(hl) or bool(al) else FAIL,
                value={"home_gk_liable": hl, "away_gk_liable": al},
                threshold="either GK liable (gk_leak_bonus)")
        ov_res, ov_val = _dna_over_signal(snap, fid_s, fxn, "over15")
        add("DNA Over Signal", ov_res, value=ov_val,
            threshold=f"DNA over signal (cut {rules['DNA_OVER_LEAN_CUT']})")
        return checks

    # ── O2.5 (Engine/over25_forecast.py). Apex picks join the SAME engine's
    # forecast row for their fixture. Every check below is one of the engine's
    # own 9-layer council votes (L259-262) reused verbatim — pos_gap <= 8,
    # parity_diff > 0, h2h_overs_total >= 3, poisson_over > 60 — plus the
    # engine's own kill_switch gate; none of these are invented thresholds.
    if market in ("over25_forecast", "over25_apex"):
        r = row if market == "over25_forecast" else (
            _resolve(snap, "o25f", fid_s, fxn) or {})
        ks = r.get("kill_switch_pass")
        if ks is None:
            add("Kill Switch", NOT_AVAILABLE)
        else:
            add("Kill Switch", PASS if ks else FAIL,
                value=r.get("kill_switch_pass"), threshold="h2h_last_3_all_over")
        po = _num(r.get("poisson_over_prob_num"))
        if po is None:
            add("Poisson Gate", NOT_AVAILABLE)
        else:
            add("Poisson Gate", PASS if po > rules["O25_POISSON_VOTE_MIN"] else FAIL,
                value=r.get("poisson_over_prob_num"),
                threshold=f"> {rules['O25_POISSON_VOTE_MIN']} (council vote)")
        h2h = _num(r.get("h2h_overs_last_5"))
        if h2h is None:
            add("H2H Overs", NOT_AVAILABLE)
        else:
            add("H2H Overs", PASS if h2h >= rules["O25_H2H_OVERS_VOTE_MIN"] else FAIL,
                value=r.get("h2h_overs_last_5"),
                threshold=f">= {rules['O25_H2H_OVERS_VOTE_MIN']} (council vote)")
        pg = _num(r.get("pos_gap"))
        if pg is None or pg >= 99:      # 99 == engine's unknown sentinel
            add("Position Gap", NOT_AVAILABLE)
        else:
            add("Position Gap", PASS if pg <= rules["O25_POS_GAP_VOTE_MAX"] else FAIL,
                value=r.get("pos_gap"),
                threshold=f"<= {rules['O25_POS_GAP_VOTE_MAX']} (council vote)")
        pd_ = _num(r.get("parity_diff"))
        if pd_ is None:
            add("Parity", NOT_AVAILABLE)
        else:
            add("Parity", PASS if pd_ > rules["O25_PARITY_VOTE_DIRECTION"] else FAIL,
                value=r.get("parity_diff"), threshold="> 0 (council vote)")
        ov_res, ov_val = _dna_over_signal(snap, fid_s, fxn, "over25")
        add("DNA Over Signal", ov_res, value=ov_val,
            threshold=f"DNA over signal (cut {rules['DNA_OVER_LEAN_CUT']})")
        return checks

    # ── O1.5 standalone page (over15_apex / over15_psychology / stage-3 rows
    # expose no independent signal fields of their own), so the audit uses the
    # fixture's existing DNA Over-1.5 market intelligence only.
    if market in ("over15", "over15_stage3", "over15_apex"):
        ov_res, ov_val = _dna_over_signal(snap, fid_s, fxn, "over15")
        add("DNA Over Signal", ov_res, value=ov_val,
            threshold=f"DNA over signal (cut {rules['DNA_OVER_LEAN_CUT']})")
        return checks

    # ── Corners (aggregator Friction label + the DNA engine's own HIGH
    # CORNERS gate: either side's Corner_Power > 70) ──────────────────────────
    if market == "corners_aggregator":
        c = row if row.get("Friction") else (_resolve(snap, "cagg", fid_s, fxn) or row)
        fr = str(c.get("Friction") or "")
        if not fr:
            add("Corner Friction", NOT_AVAILABLE)
        elif "PERFECT" in fr or "STABLE" in fr:
            add("Corner Friction", PASS, value=fr)
        elif "DEAD" in fr or "AVOID" in fr:
            add("Corner Friction", FAIL, value=fr)
        else:
            add("Corner Friction", FAIL, value=fr)
        cp_res, cp_val = _dna_corners_signal(snap, fid_s, fxn)
        if cp_res == NOT_AVAILABLE:
            cp_res, cp_val = _dna_corner_power(snap, fid_s, fxn)
        add("Corner Power", cp_res, value=cp_val,
            threshold=f"DNA HIGH CORNERS verdict / either side > {rules['DNA_HIGH_CORNERS_CUT']}")
        return checks

    # ── Draw (engine's own tier gates + the new DNA parity check) ────────────
    if market == "draw":
        # Native direction: a DRAW pick is supported when mc_draw_prob reaches
        # the draw engine's own draw-candidate floor (>= 0.22, TIER2 gate).
        mp = _frac(row.get("mc_draw_prob"))
        if mp is None:
            add("Draw Probability", NOT_AVAILABLE)
        else:
            add("Draw Probability", PASS if mp >= rules["DRAW_MC_DRAW_PROB_FLOOR"] else FAIL,
                value=row.get("mc_draw_prob"), threshold=">= 0.22 (draw engine floor)")
        par = _num(row.get("parity"))
        if par is None:
            add("Psychology Parity", NOT_AVAILABLE)
        else:
            add("Psychology Parity", PASS if par >= rules["DRAW_PARITY_THRESHOLD"] else FAIL,
                value=row.get("parity"), threshold=">=0.6")
        dmi = _num(row.get("dmi"))
        if dmi is None:
            add("Draw Magnet", NOT_AVAILABLE)
        else:
            add("Draw Magnet", PASS if dmi >= rules["DRAW_DMI_THRESHOLD"] else FAIL,
                value=row.get("dmi"), threshold=">=0.45")
        add("DNA Parity", _dna_parity_eval(snap, fid_s, fxn))
        return checks

    # ── Unders (u25 head rows from the unders composite file) ─────────────────
    if market == "unders_u25":
        # gg_precision_engine: sig1_raw saturates at combined_lambda 2.5 —
        # below that, neither side carries O1.5+ firepower → supports U2.5.
        lam = _num(row.get("combined_lambda"))
        if lam is None:
            add("Goal Gap", NOT_AVAILABLE)
        else:
            add("Goal Gap", PASS if lam <= 2.5 else FAIL,
                value=row.get("combined_lambda"), threshold="<= 2.5 (O1.5 λ saturation)")
        # Goalkeeper — gg_precision_engine gk_bonus: both GKs NOT liable
        # (cpg <= 1.10) suppresses goals → supports U2.5.
        hc, ac = _num(row.get("home_gk_cpg")), _num(row.get("away_gk_cpg"))
        if hc is None and ac is None:
            add("Goalkeeper", NOT_AVAILABLE)
        else:
            add("Goalkeeper", PASS if (hc or 0) <= 1.10 and (ac or 0) <= 1.10 else FAIL,
                value={"home_gk_cpg": row.get("home_gk_cpg"),
                       "away_gk_cpg": row.get("away_gk_cpg")}, threshold="both <= 1.10")
        return checks
    # ── Underdog To Score (U2S psychology row + its own named underdog) ──────
    if market == "u2s":
        u_row, dog = _u2s_row_for(snap, fid_s, fxn,
                                  row.get("fixture_id"), row.get("fixture") or row.get("Fixture"))
        if u_row and not dog:
            dog = row.get("Underdog")
        if not u_row or not dog:
            add("Psychology", NOT_AVAILABLE)
            add("Dog ATT Strength", NOT_AVAILABLE)
            add("Fav Def Weakness", NOT_AVAILABLE)
            return checks
        # Psychology: prefer the calling row's own audit score; otherwise the
        # joined U2S row's. Genuinely missing → NOT_AVAILABLE (never a fake FAIL).
        ps_val = _num(row.get("Psych_Score"))
        if ps_val is None:
            ps_val = _num(u_row.get("Psych_Score"))
        if ps_val is None:
            add("Psychology", NOT_AVAILABLE)
        else:
            add("Psychology", PASS if ps_val > 0 else FAIL,
                value=u_row.get("Psych_Score") if row.get("Psych_Score") is None else row.get("Psych_Score"))
        add("Dog ATT Strength", _dog_att_eval(snap, fid_s, fxn))
        add("Fav Def Weakness", _fav_def_eval(snap, fid_s, fxn))
        return checks

    # ── FHVI / SHVI (>=7 == TIER 2 GOOD or better, per-file Category gate) ───
    if market in ("fhvi", "shvi"):
        key = "FHVI" if market == "fhvi" else "SHVI"
        field = "fhvi_score" if market == "fhvi" else "shvi_score"
        score = _num(row.get(field))
        if score is None:
            add(key, NOT_AVAILABLE)
        else:
            thr = rules["FHVI_TIER2_THRESHOLD" if market == "fhvi" else "SHVI_TIER2_THRESHOLD"]
            add(key, PASS if score >= thr else FAIL, value=row.get(field), threshold=">= 7")
        return checks

    # Display-only stages carry no applicable intelligence of their own — no
    # checks at all, so the audit is withheld (ipc None) and the frontend
    # hides the cell. A placeholder check would render "0/1" under the
    # fixed-denominator rule, which is why none is emitted.
    return checks
# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_market(market_key, rows, date):
    """Attach an additive `intelligent_pass_count` object to every row of one
    market snapshot. Returns the SAME list (rows mutated additively — no key
    is ever removed, renamed or re-ordered, so settlement/ensure_defaults and
    the frontend's existing fields are untouched).

    The value is a dict {"passed","total","checks"} — the FRONTEND-visible
    counterpart of this module's fixed-denominator rule (total = the market's
    full rule set). It is None only when the market is display-only / has no
    evaluator branch at all, so the frontend simply hides the cell.
    """
    if market_key in DISPLAY_ONLY_MARKETS:
        return rows
    snap = _snapshot(date)
    for row in rows:
        if not isinstance(row, dict):
            continue
        fxn = _fixture_label(row)
        fid = row.get("fixture_id")
        checks = _checks_for_market(market_key, snap, row, fid, fxn, date=date)
        # FIXED-DENOMINATOR RULE: the denominator is the market's FULL rule
        # set — every check the branch defines, whether its data exists or
        # not (WIN=8, GG=4, O2.5=6, …). N/A never shrinks the total; only
        # the numerator (PASSes) varies. Only a market whose branch emitted
        # NO rules at all has no audit (ipc None).
        row["intelligent_pass_count"] = {
            # The market key travels with the audit so the drill-down can
            # open THIS pick's report (pick = the primary object).
            "market": market_key,
            "passed": sum(1 for c in checks if c["result"] == PASS),
            "total": len(checks),
            "checks": checks,
        } if checks else None
    return rows


def evaluate_market_safe(market_key, rows, date):
    """Crash-isolated wrapper: an evaluator failure must never take down a
    picks route. On any exception the rows are returned UNCHANGED (the
    Intelligent Pass column simply renders empty)."""
    try:
        return evaluate_market(market_key, rows, date)
    except Exception:
        return rows


def _team_context(snap, fid_s, fxn, team_name):
    """Raw EXISTING intelligence values for the Team Intelligence page — the
    numbers behind each PASS/FAIL. Read-only passthrough of engine fields:
    nothing is recomputed, nothing is fabricated (missing → None)."""
    ctx = {}
    home, away = _split_fixture(fxn)

    # WIN side row (parity_score, form counters) — the selected team's own row
    side = _win_side_row(snap, fid_s, fxn, team_name)
    if side:
        ctx["win_side"] = {
            "parity_score": side.get("parity_score"),
            "last_5_wins_overall": side.get("last_5_wins_overall"),
            "last_5_wins_at_venue": side.get("last_5_wins_at_venue"),
            "last_5_goals_scored": side.get("last_5_goals_scored"),
            "opp_last_5_goals_scored": side.get("opp_last_5_goals_scored"),
            "opp_last_5_losses": side.get("opp_last_5_losses"),
            "win_odds": side.get("win_odds"),
            "side": side.get("side"),
        }

    # DNA v2 market factors — every existing market section for this fixture
    markets = _resolve(snap, "dna", fid_s, fxn)
    if markets:
        dna = {}
        for mkey, mv in markets.items():
            factors = (mv or {}).get("factors") or []
            dna[mkey] = {
                "home_count": (mv or {}).get("home_count"),
                "away_count": (mv or {}).get("away_count"),
                "factors": [
                    {"name": f.get("name"), "home_value": f.get("home_value"),
                     "away_value": f.get("away_value"), "winner": f.get("winner")}
                    for f in factors
                ],
            }
        ctx["dna_market_factors"] = dna

    # DNA engine's own clash verdicts for this fixture (market signals)
    clash = _resolve(snap, "dna_clash", fid_s, fxn)
    if clash:
        ctx["dna_clash"] = {
            "market_signals": clash.get("market_signals"),
            "combined_goal_intent": clash.get("combined_goal_intent"),
            "combined_box_dominance": clash.get("combined_box_dominance"),
            "overall_structural_edge": clash.get("overall_structural_edge"),
            "home_team": clash.get("home_team"),
            "away_team": clash.get("away_team"),
        }

    # SOT row (verdict / game script / totals)
    s = _resolve(snap, "sot", fid_s, fxn)
    if s:
        ctx["sot"] = {k: s.get(k) for k in (
            "Verdict", "Game_Script", "Proj_SOT", "Consistency", "Momentum",
            "Proj_Goals", "Tempo") if k in s}

    # Corner aggregator (friction / chaos / expected corners)
    c = _resolve(snap, "cagg", None, fxn)
    if c:
        ctx["corners"] = {k: c.get(k) for k in (
            "Friction", "Chaos_Rating", "Total_Exp", "Master_Score", "Tier",
            "Match_Flow", "True_Corner_Fav") if k in c}

    # WIN psychology row (signed nets)
    w = _resolve(snap, "wps", fid_s, fxn)
    if w:
        ctx["win_psychology"] = {k: w.get(k) for k in (
            "H_Base", "A_Base", "Audit_Score", "Psych_Score", "Audit_Verdict",
            "Quality_Grade", "Spear") if k in w}

    # Underdog rows (identity + the two multipliers + longshot probability)
    ud = _resolve(snap, "ud", fid_s, fxn)
    if ud:
        ctx["underdog_base"] = {k: ud.get(k) for k in (
            "underdog_team", "dog_att_strength", "fav_def_weakness",
            "dog_score_prob", "dog_is_hot", "dog_due_goal", "fav_cs_streak",
            "dog_venue_wins", "parity_gap") if k in ud}
    uda = _resolve(snap, "uda", fid_s, fxn)
    if uda:
        ctx["underdog_audit"] = {k: uda.get(k) for k in (
            "underdog_team", "Dog_Score_Prob", "Audit_Verdict",
            "Audit_Real_Prob", "parity_gap", "Dominance_Gap") if k in uda}

    # Draw row (Monte-Carlo draw probability + engine tier gates)
    d = _resolve(snap, "draw", fid_s, fxn)
    if d:
        ctx["draw"] = {k: d.get(k) for k in (
            "mc_draw_prob", "parity", "dmi", "composite_draw_score", "tier",
            "value_edge", "most_likely_draw_score") if k in d}

    # Unders u25 row (expected goals + keepers)
    un = _resolve(snap, "un", fid_s, fxn)
    if un:
        ctx["unders"] = {k: un.get(k) for k in (
            "combined_lambda", "mc_u25_prob", "u25_score", "u25_tier",
            "u25_signals_fired", "home_gk_cpg", "away_gk_cpg") if k in un}

    # O2.5 forecast row (the engine's own council inputs)
    o25 = _resolve(snap, "o25f", fid_s, fxn)
    if o25:
        ctx["over25"] = {k: o25.get(k) for k in (
            "kill_switch_pass", "poisson_over_prob_num", "council_votes",
            "pos_gap", "parity_diff", "h2h_overs_last_5",
            "combined_gs_last_5", "o25_odds") if k in o25}

    # GG / O1.5 composite rows (heads 0 and 1)
    ggc = _resolve(snap, "ggc", fid_s, fxn)
    if ggc:
        ctx["gg"] = {k: ggc.get(k) for k in (
            "gg_score", "gg_tier", "gg_signals_fired", "mc_btts_prob",
            "h2h_btts_rate", "home_gk_cpg", "away_gk_cpg",
            "home_gk_liable", "away_gk_liable") if k in ggc}
    o15 = _resolve(snap, "o15c", fid_s, fxn)
    if o15:
        ctx["over15"] = {k: o15.get(k) for k in (
            "o15_score", "o15_tier", "combined_lambda", "lambda_home",
            "lambda_away", "mc_over15_prob", "home_gk_liable",
            "away_gk_liable") if k in o15}

    # FHVI / SHVI rows
    for mk, key, field in (("fhvi", "fhvi", "fhvi_score"),
                           ("shvi", "shvi", "shvi_score")):
        r = _resolve(snap, mk, fid_s, fxn)
        if r:
            ctx[mk] = {k: r.get(k) for k in (
                field, "Category", "fhvi_label", "shvi_label",
                "fh_pressure", "sh_pressure", "comb_fh_r", "comb_sh_r",
                "ht_score", "ft_score", "country") if k in r}
    return ctx


def _locate_fixture(date, snap, team_name):
    """Find a team's fixture via the WIN-side registry — across the source
    window, because the WIN pack is cross-day: the requested date is tried
    first, then the neighbours. Strong match: a row naming the team
    (team_name on side rows, Target on apex rows, Master_Pick on psychology
    rows). Weak fallback: a fixture-level row (no team identity) whose label
    contains the team — this keeps the report resolvable for fixtures whose
    ONLY saved rows are fixture-level (e.g. apex-only runs). Returns
    (fixture_id, rows, canonical fixture_label).
    IMPORTANT: the returned label is always the date's CANONICAL 'home vs
    away' label from the id-bearing engines — never a swapped apex label —
    so every name-keyed join downstream resolves."""
    t = _norm(team_name or "")
    if not t:
        return "", [], ""

    def _row_names(r):
        return [n for n in (r.get("team_name"), r.get("Target"),
                            r.get("Master_Pick")) if n]

    for d in _window_dates(date):
        dsnap = snap if d == date else _snapshot(d)
        # First pass: exact team-side match.
        for fid, rows in sorted((dsnap.get("win_by_id") or {}).items()):
            hit = next((r for r in rows
                        if any(_norm(n) == t for n in _row_names(r))), None)
            if hit:
                canon = (dsnap.get("label_by_id") or {}).get(fid, "")
                return fid, rows, canon or _fixture_label(hit)
        # Second pass: label-side fallback. A fixture-level row names at most
        # ONE participant (apex rows carry Target); the other side exists only
        # in the label. Match the fixture label's SIDES (exact normalised
        # equality) — containment would let 'Arsenal' resolve an
        # 'Arsenal U21 vs Brighton U21' fixture.
        for fid, rows in sorted((dsnap.get("win_by_id") or {}).items()):
            for r in rows:
                label = _fixture_label(r) or ""
                if not label:
                    continue
                parts = re.split(r"\s+vs\.?\s+", label, flags=re.I)
                if any(_norm(p) == t for p in parts if p.strip()):
                    canon = (dsnap.get("label_by_id") or {}).get(fid, "")
                    return fid, rows, canon or label
    return "", [], ""


def _opponent_from(rows, fxn, team_name):
    """The other side of the fixture: from side rows when present, else
    derived from the fixture label."""
    t = _norm(team_name or "")
    for r in rows:
        n = r.get("team_name")
        if n and _norm(n) != t:
            return n
    parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", fxn or "", flags=re.I) if p.strip()]
    return next((p for p in parts if _norm(p) != t and _norm(t) not in _norm(p)), "")


def _get_market_intelligence(team_name, date, market):
    """SINGLE-MARKET report payload — the pick is the primary object.

    Identity: fixture/date + team + market. Only the requested market's
    evaluator branch runs, so no other market's checks can appear here (the
    payload carries `score` + `checks`, never a `markets` map). Reads the
    SAME on-disk snapshots as the market pages — zero new data acquisition,
    zero fabricated values (missing intelligence stays NOT_AVAILABLE and can
    only lower the numerator; the denominator stays the market's full rule
    set)."""
    snap = _snapshot(date)

    # Locate the team's fixture via the WIN-side fixture registry (side rows
    # carry team_name; apex rows carry Target; fixture-level-only fixtures
    # resolve by label containment — the engines saved, so it must resolve).
    # Window-aware: the WIN pack is cross-day, so the fixture may live in a
    # neighbouring date's registry — but the report always plays back the
    # REQUESTED date's story, and every source join happens over the window.
    fixture_id, side_rows_hit, fxn = _locate_fixture(date, snap, team_name)
    base = {"team": team_name, "date": date, "market": market,
            "market_label": TEAM_INTELLIGENCE_MARKETS[market]}
    if not fxn:
        return dict(base, fixture="", fixture_id="", fixture_found=False,
                    opponent="", prediction=None, score=None, checks=[])

    fid_s = _idstr(fixture_id)
    opp = _opponent_from(side_rows_hit, fxn, team_name)

    # THE PAGE/MARKET IS AUTHORITATIVE: run ONLY this market's evaluator
    # branch, seeded with the same per-fixture row shape the market tables use.
    engine_key = _MARKET_EVALUATOR_ALIASES[market][0]
    if market in ("win", "win_psychology"):
        row = {"Target": team_name}          # the pick: {team} to win
    elif market == "u2s":
        row = {"fixture_id": fid_s, "fixture": fxn}
    elif market == "draw":
        row = _resolve(snap, "draw", fid_s, fxn) or {}
    elif market == "unders":
        row = _resolve(snap, "un", fid_s, fxn) or {}
    elif market == "fhvi":
        row = _resolve(snap, "fhvi", fid_s, fxn) or {}
    elif market == "shvi":
        row = _resolve(snap, "shvi", fid_s, fxn) or {}
    elif market == "gg":
        # The gg branch reads its psychology verdict from the GG supreme row
        # itself (Psych_Score) — seed it exactly as the GG table rows do.
        row = _resolve(snap, "gsup", fid_s, fxn) or {}
    else:
        # gg_precision / gg_o15 / over25 / over15:
        # their branches join the fixture's own engine rows internally.
        row = {}
    checks = _checks_for_market(engine_key, snap, row, fid_s, fxn, date=date)
    # FIXED-DENOMINATOR RULE (matches evaluate_market): total is the market's
    # FULL rule set; N/A never shrinks it — only the numerator varies.
    score = {
        "passed": sum(1 for c in checks if c["result"] == PASS),
        "total": len(checks),
    }
    return dict(base, fixture=fxn, fixture_id=fixture_id, fixture_found=True,
                opponent=opp,
                prediction=team_name if market in ("win", "win_psychology") else None,
                score=score, checks=checks)


def get_team_intelligence(team_name, date, market=None):
    """Read-only composition for the Team Intelligence page.

    market=None → legacy all-markets payload (unchanged behaviour).
    market=<canonical key> → SINGLE-MARKET report (the requested
    architecture): fixture/date + team + market identity, only that market's
    checks. An unknown market raises ValueError (API maps it to 400).
    ZERO network calls — pure local file reads of the same snapshots the
    fixture pages use."""
    # MARKET-SPECIFIC REPORT: the pick is the primary object. Only the
    # requested market's evaluator runs — no cross-market composition.
    if market is not None:
        if market not in TEAM_INTELLIGENCE_MARKETS:
            raise ValueError(
                "unknown market %r — expected one of %s"
                % (market, sorted(TEAM_INTELLIGENCE_MARKETS)))
        return _get_market_intelligence(team_name, date, market)
    snap = _snapshot(date)

    # Same locator as the single-market report: side rows carry team_name,
    # apex rows carry Target, fixture-level-only rows resolve by label.
    fixture_id, side_rows_hit, fxn = _locate_fixture(date, snap, team_name)
    if not fxn:
        return {"team": team_name, "date": date, "fixture": "",
                "fixture_id": "", "fixture_found": False, "markets": {}}

    fid_s = str(fixture_id)
    opp = _opponent_from(side_rows_hit, fxn, team_name)
    markets = {}

    def _mark(key, checks):
        # FIXED-DENOMINATOR RULE: total = the market's full rule set, N/A
        # checks included; only the numerator (PASSes) varies.
        markets[key] = {
            "passed": sum(1 for c in checks if c["result"] == PASS),
            "total": len(checks),
            "checks": checks,
        }

    _mark("win", _checks_for_market("win_apex", snap, {"Target": team_name}, fid_s, fxn, date=date))
    _mark("win_psychology", _checks_for_market("win_apex", snap,
                                                {"Target": team_name}, fid_s, fxn, date=date))
    _mark("gg", _checks_for_market("gg_supreme", snap, {}, fid_s, fxn, date=date))
    _mark("gg_precision", _checks_for_market("gg_precision", snap, {}, fid_s, fxn, date=date))
    _mark("over25", _checks_for_market("over25_apex", snap, {}, fid_s, fxn, date=date))
    _mark("over15", _checks_for_market("over15", snap, {}, fid_s, fxn, date=date))
    _mark("corners", _checks_for_market("corners_aggregator", snap, {}, fid_s, fxn, date=date))
    _mark("draw", _checks_for_market(
        "draw", snap, _resolve(snap, "draw", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("unders", _checks_for_market(
        "unders_u25", snap, _resolve(snap, "un", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("u2s", _checks_for_market("u2s", snap, {"fixture_id": fid_s, "fixture": fxn}, fid_s, fxn, date=date))
    _mark("fhvi", _checks_for_market(
        "fhvi", snap, _resolve(snap, "fhvi", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("shvi", _checks_for_market(
        "shvi", snap, _resolve(snap, "shvi", fid_s, fxn) or {}, fid_s, fxn, date=date))
    return {
        "team": team_name, "date": date, "fixture": fxn, "fixture_id": fixture_id,
        "opponent": opp, "fixture_found": True, "markets": markets,
        "context": _team_context(snap, fid_s, fxn, team_name),
    }






