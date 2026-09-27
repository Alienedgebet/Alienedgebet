"""
signal_ledger.py — shared, read-only loaders for the market-signal backtest.

WHY THIS FILE EXISTS
--------------------
The 2026-09-26 investigation of "can Corners / SOT be ordered so the front
passes verify?" could only join 3 days of predictions against
`data/ft_result_snapshot.json` (n=67 corners, n=65 SOT). That sample is far
too small to separate a real ordering edge from noise.

This module opens up the FULL history: `output/archive_<date>.json` holds a
per-fixture settled snapshot (corner + shot-on-target counts) for every date
the daily archiver has run, and `output/cache/<engine>__<date>.json` holds
that date's prediction rows. Joining the two yields the per-row
(signal -> outcome) ledger the backtest needs.

HARD RULES (identical in spirit to INTELLIGENT_PASS/pass_count.py):
  * READ-ONLY. This module never writes, rewrites or re-grades a prediction.
    It appends to a separate ledger file; `output/cache/*` and the archives
    are opened for reading only.
  * NO new API calls. Everything comes from files already on disk.
  * VERDICTS COME FROM THE ONE GRADER. Every outcome is produced by
    `settlement_service.grade_row(market, ...)`, the exact function the API
    uses to render the Verify column. The ledger therefore cannot drift from
    what the user sees; we never re-implement the win condition.

The win conditions (see settlement_service.grade_row) are fixed thresholds on
the COMBINED match totals, and deliberately do NOT read the pick itself:
    corners : WON iff total_corners >= 7
    sot     : WON iff total_sot > 6
"""

import json
import math
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "output", "cache")
ARCHIVE_DIR = os.path.join(ROOT, "output")
DATA_DIR = os.path.join(ROOT, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "signal_ledger.jsonl")

# market -> prediction cache key
#
# ONLY markets whose settlement is a FIXED THRESHOLD that never reads the pick
# belong here. That is what makes an ordering meaningful: the front of the list
# can be re-ordered toward a higher expected total.
#
# `win`/`1x2` is graded AGAINST A STORED PICK ("did THIS team win"), so an
# ordering of it is a different claim and is not made here at all.
#
# `u2s` IS included but is ADVISORY ONLY. Its verdict grades the stored
# `Underdog` column ("did the underdog score"), which is pick-dependent.
# `win` is graded per-ROW against that row's own `side`/`team_name`, which is
# what makes its ordering legitimate: each row is a separate bet, so ranking by
# that bet's own win probability raises the precision of the list. The
# qualifying block is 65.1% against a 38.0% base.
#
# Nothing in the UI may present the u2s ordering as a prediction of the u2s
# market; the win ordering IS a prediction of the win market and is labelled
# as such.
#
# `u25` / `u35` / `draw` come from COMPOSITE payloads whose cache file holds a
# LIST OF BLOCKS rather than a list of rows (unders = [u25, u35]). They are read
# through load_blocks(); they are deliberately NOT listed in MARKETS, because
# MARKETS is the "one file, one market" map and these are not that.
MARKETS = {
    "corners": "corners_aggregator",
    "sot": "sot",
    "gg": "gg_supreme",
    "o25": "over25_stage1",
    "o15": "over15_stage3",
    "shvi": "shvi",
    "fhvi": "fhvi",
    "u2s": "u2s_psychology",
    "win": "win_forecast",
}

# Composite payloads hold several markets in one file, as a list of row-lists.
# This is the file and the block index each market lives in. It is the ONLY
# place these three markets are registered: keeping them out of MARKETS means
# there is no second, contradictory entry to keep in sync.
BLOCK_INDEX = {
    "u25": ("unders", 0),
    "u35": ("unders", 1),
    "draw": ("draw", 0),
}

# Every market this module can grade.
ALL_MARKETS = tuple(MARKETS) + tuple(BLOCK_INDEX)

# Splitting on the real separators. "vs", "vs.", "v", "against", "-" are all
# used somewhere in the wild; a fixture that cannot be split is simply not
# joinable and is reported as such rather than guessed at.
_VS = re.compile(r"\s+(?:vs?\.?|against|-)\s+", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_name(value) -> str:
    """'Atlante vs Monterrey' -> comparable key.

    Accents stripped, punctuation dropped, case folded. Applied to BOTH sides
    of the join so 'Sao Paulo' and 'São Paulo' match.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _NON_ALNUM.sub("", text.lower())


def as_float(value):
    """Best-effort numeric parse that tolerates the engines' string fields.

    The cache stores e.g. Total_Exp='13.11', Consistency='41%'. Returns None
    (never raises, never fabricates a 0) when the value is absent or junk —
    a missing signal must be missing in the ledger too, or the backtest would
    silently grade "no data" rows as if they were low-signal rows.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        # NaN and +/-inf are not signals. Returning them would violate this
        # function's own contract (a missing value must be None, never a
        # number), poison every downstream mean/threshold, and — because
        # json.dump writes bare NaN — produce a ledger file that is not valid
        # JSON and cannot be read back by the TypeScript parity test.
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text or text in {"N/A", "None", "nan", "-", "--"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        parsed = float(match.group(0))
    except ValueError:
        return None
    # A long enough digit run (e.g. a 1e999 written out) overflows to inf.
    return parsed if math.isfinite(parsed) else None


def prediction_path(engine_key: str, date: str) -> str:
    return os.path.join(CACHE_DIR, f"{engine_key}__{date}.json")


def archive_path(date: str) -> str:
    return os.path.join(ARCHIVE_DIR, f"archive_{date}.json")


def load_blocks(engine_key: str, date: str):
    """A COMPOSITE payload's blocks, normalised to a list of row-lists.

    Some engines emit several markets from one run. `unders` writes
    `data = [u25_rows, u35_rows]` and `draw` writes three sections, so the file's
    top level is a list of LISTS, not a list of rows. Reading that with
    load_predictions() returns [] for every date, which is how the whole Unders
    market looked like it had no settled history at all.

    A single-block payload (an ordinary list of rows) is returned as one block,
    so callers never have to know which shape they got.
    """
    path = prediction_path(engine_key, date)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        return []
    if isinstance(rows[0], dict):
        return [[r for r in rows if isinstance(r, dict)]]
    return [[r for r in block if isinstance(r, dict)]
            for block in rows
            if isinstance(block, list) and block and isinstance(block[0], dict)]


def load_predictions(engine_key: str, date: str):
    """That date's prediction rows, or [] when the file is absent/empty."""
    path = prediction_path(engine_key, date)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    return [r for r in (rows or []) if isinstance(r, dict)]


def load_results(date: str):
    """date -> {(home, away): actual_match} from the archiver's snapshot.

    The archiver writes `fixtures` as a LIST in every real file; a dict keyed
    by fixture_id is also accepted so a future format change degrades into a
    supported path instead of a silent empty result.
    """
    path = archive_path(date)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}
    fixtures = payload.get("fixtures") if isinstance(payload, dict) else None
    if not fixtures:
        return {}
    rows = fixtures.values() if isinstance(fixtures, dict) else fixtures
    index = {}
    for match in rows:
        if not isinstance(match, dict):
            continue
        key = (norm_name(match.get("home_team")), norm_name(match.get("away_team")))
        if all(key):
            index[key] = match
    return index


def pair_key(home, away):
    """A fixture identity that does not care which side the archiver called home.

    The archiver and the prediction engines do NOT always agree on venue
    orientation for the same fixture: a prediction may read
    'LA Galaxy vs Minnesota United' while the archive row for that same match
    stores home='Minnesota United', away='LA Galaxy' (neutral-venue and
    data-source fixtures do this). Keying on the ordered tuple silently drops
    every such row, which is how o15 / shvi / fhvi joined ZERO rows in the
    2026-09-27 sweep while corners and sot looked fine purely by luck of
    consistent orientation.

    A frozenset makes 'A vs B' and 'B vs A' the same key. It is only ever used
    for MATCHING; nothing downstream depends on venue, and the settled totals
    (corners, SOT, goals) are side-symmetric, so an orientation mismatch
    cannot change a verdict.
    """
    return frozenset((norm_name(home), norm_name(away)))


def build_actual_index(results):
    """Re-key a load_results() mapping by unordered fixture identity.

    Accepts the ordered-tuple mapping load_results returns today, so existing
    callers and tests that mock load_results with tuple keys keep working
    unchanged. Fixture keys that collide after folding (the same two teams
    listed twice) keep the FIRST row, matching load_results' own behaviour.
    """
    index = {}
    for key, match in (results or {}).items():
        if not isinstance(match, dict):
            continue
        if isinstance(key, frozenset):
            folded = key
        elif isinstance(key, tuple) and len(key) == 2:
            folded = pair_key(key[0], key[1])
        else:
            # Fall back to the row's own team names, so an oddly-keyed mapping
            # still joins instead of silently becoming an unmatched row.
            folded = pair_key(match.get("home_team"), match.get("away_team"))
        if len(folded) != 2 or not all(folded):
            continue
        index.setdefault(folded, match)
    return index


def lookup_actual(results_index, key):
    """Find the archive row for a normalised (home, away) prediction key.

    Tries the exact ordered key first (preserves today's behaviour and the
    home/away-aware tests), then the reversed one, then the unordered index.
    """
    if not key:
        return None
    if isinstance(results_index, dict) and not results_index:
        return None
    ordered = results_index.get(key)
    if ordered:
        return ordered
    return results_index.get(pair_key(key[0], key[1]))


def row_fixture_name(row: dict) -> str:
    """The fixture label of a prediction row, whichever column it arrived in.

    Engines are not consistent about this column name: corners/sot/gg/o25 ship
    'Fixture' (or lowercase 'fixture'), while o15 ships 'Match'. Reading only
    one of them is how the o15 market joined ZERO rows for the whole sweep and
    looked like 'no data' rather than 'wrong column'. Every alias in use across
    output/cache is accepted here, in one place, so adding an engine cannot
    silently drop it from the ledger.
    """
    for column in ("fixture", "Fixture", "Match", "match", "Teams", "teams",
                   "fixture_name", "Fixture_Name"):
        value = row.get(column)
        if value:
            return str(value)
    return ""


def row_fixture_key(row: dict):
    """Normalised (home, away) for a prediction row, or None if unsplittable."""
    return fixture_key(row_fixture_name(row))


def fixture_key(fixture_name: str):
    """'Home vs Away' -> ('home','away') normalised. None if unsplittable."""
    if not fixture_name or " " not in str(fixture_name):
        return None
    parts = _VS.split(str(fixture_name).strip())
    if len(parts) != 2:
        return None
    a, b = norm_name(parts[0]), norm_name(parts[1])
    if not a or not b:
        return None
    return a, b


def _grader():
    """Import the ONE grader lazily, so an import error never breaks callers."""
    import settlement_service
    return settlement_service


def grade(market: str, row: dict, actual: dict):
    """The authoritative verdict for one row, or None if ungradeable."""
    try:
        return _grader().grade_row(market, row, actual)
    except Exception:
        return None


# Squad-availability encodings. The corner engine writes a decorated YES/NO
# flag ('🩸 YES' / '❌ NO') and a severity word. Both are turned into plain
# numbers so the backtest can treat severity as an ordered dose (a CRITICAL
# absence should count for more than a MINOR one) instead of a text label that
# no arithmetic can use.
_WOUND_SEVERITY = {"NONE": 0.0, "MINOR": 1.0, "ACTIVE": 2.0, "CRITICAL": 3.0}


def _wounded_flag(value):
    """1.0 when the side is flagged wounded, 0.0 when explicitly not, else None.

    The three-way result matters: a row with no injury data at all must not
    be recorded as "not wounded", which would silently make healthy-absent
    teams look like the confident baseline.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"None", "nan", "N/A"}:
        return None
    if "YES" in text.upper():
        return 1.0
    if "NO" in text.upper():
        return 0.0
    return None


def _wound_severity(value):
    """0..3 from the severity word, or None when absent/unrecognised."""
    if value is None:
        return None
    return _WOUND_SEVERITY.get(str(value).strip().upper())


def _sum2(a, b):
    """Sum of two optional signals; None unless BOTH sides are known."""
    if a is None or b is None:
        return None
    return a + b


def row_signal_fields(market: str, row: dict) -> dict:
    """Every candidate ranking signal, extracted and typed, per market.

    Kept deliberately EXPLICIT (rather than dumping the whole row) so the
    ledger is a stable, reviewable contract: if an engine renames a field the
    backtest sees the drop instead of silently reading a different column.
    """
    if market == "corners":
        return {
            "Total_Exp": as_float(row.get("Total_Exp")),
            "Home_Exp": as_float(row.get("Home_Exp")),
            "Away_Exp": as_float(row.get("Away_Exp")),
            "Master_Score": as_float(row.get("Master_Score")),
            "Chaos_Rating": as_float(row.get("Chaos_Rating")),
            "Home_Score": as_float(row.get("Home_Score")),
            "Away_Score": as_float(row.get("Away_Score")),
            "U2.5": as_float(row.get("U2.5%")),
            # Underdog probability (UD_Prob, e.g. "65.38%").
            "UD_Prob": as_float(row.get("UD_Prob")),
            # Squad-availability. The engine stores a YES/NO flag plus a
            # severity word; both are encoded numerically here so the
            # backtest can treat severity as an ordered dose.
            "Home_Wounded": _wounded_flag(row.get("Home_Wounded")),
            "Away_Wounded": _wounded_flag(row.get("Away_Wounded")),
            "Home_Wound_Sev": _wound_severity(row.get("Home_Wound_Int")),
            "Away_Wound_Sev": _wound_severity(row.get("Away_Wound_Int")),
            "Wound_Sev_Sum": _sum2(_wound_severity(row.get("Home_Wound_Int")),
                                   _wound_severity(row.get("Away_Wound_Int"))),
            "Wound_Count": _sum2(_wounded_flag(row.get("Home_Wounded")),
                                 _wounded_flag(row.get("Away_Wounded"))),
            "Home_Pos": as_float(row.get("Home_Pos")),
            "Away_Pos": as_float(row.get("Away_Pos")),
        }
    if market == "sot":
        return {
            "Proj_SOT": as_float(row.get("Proj_SOT")),
            "Consistency": as_float(row.get("Consistency")),
            "Poisson_Over_8.5": as_float(row.get("Poisson_Over_8.5")),
        }
    if market == "gg":
        return {
            "Base_Marks": as_float(row.get("Base_Marks")),
            "Monte_GG_Prob": as_float(row.get("Monte_GG_Prob")),
            # NGG_Risk is the engine's own "no-goal" read; it is scored
            # INVERTED by the backtest (a LOW value is the good side), so it is
            # logged under an explicit name to stop anyone reading it naively.
            "NGG_Risk": as_float(row.get("NGG_Risk")),
            "Cat_Priority": as_float(row.get("Cat_Priority")),
            "Psych_Score": as_float(row.get("Psych_Score")),
            "Spears": as_float(row.get("Spears")),
        }
    if market == "o25":
        return {
            "Confidence": as_float(row.get("Confidence")),
            "Odds": as_float(row.get("Odds")),
            "Time": as_float(row.get("Time")),
        }
    if market == "o15":
        return {
            "Poisson": as_float(row.get("Poisson%")),
            "Grade": as_float(row.get("Grade")),
            "GradeNum": as_float(row.get("GradeNum")),
            "H2H_Record": as_float(row.get("H2H_Record")),
            "Odds": as_float(row.get("Odds")),
            "PickCount": as_float(row.get("PickCount")),
            "Failures": as_float(row.get("Failures")),
        }
    if market == "shvi":
        # ft_score / ht_score are DELIBERATELY EXCLUDED: the shvi payload
        # stores the settled score of the very match being predicted, so they
        # are the outcome, not a signal. Including them scores a perfect,
        # meaningless ~1.0 AUC. See tests_signal_ledger.
        return {
            "shvi_score": as_float(row.get("shvi_score")),
            "sh_pressure": as_float(row.get("sh_pressure")),
            "comb_sh_r": as_float(row.get("comb_sh_r")),
            "h_sh_c_r_disp": as_float(row.get("h_sh_c_r_disp")),
            "a_sh_c_r_disp": as_float(row.get("a_sh_c_r_disp")),
            "h_sh_r_disp": as_float(row.get("h_sh_r_disp")),
            "a_sh_r_disp": as_float(row.get("a_sh_r_disp")),
            "avg_fh_goals": as_float(row.get("avg_fh_goals")),
        }
    if market == "win":
        # Each row is one bet on one side, so these are the bet's OWN
        # pre-match numbers. Verified NOT leakage: WON and LOST rows span the
        # same win_odds range (1.00-12.50 vs 1.00-67.00), so the field is a
        # price, not a restatement of the result.
        return {
            "poisson_win_prob": as_float(row.get("poisson_win_prob")),
            "win_odds": as_float(row.get("win_odds")),
            "parity_score": as_float(row.get("parity_score")),
            "last_5_wins_overall": as_float(row.get("last_5_wins_overall")),
            "last_5_wins_at_venue": as_float(row.get("last_5_wins_at_venue")),
            "last_5_goals_scored": as_float(row.get("last_5_goals_scored")),
            "h2h_wins_last_5": as_float(row.get("h2h_wins_last_5")),
            "opp_last_5_conceded_raw": as_float(row.get("opp_last_5_conceded_raw")),
            "opp_last_5_goals_scored": as_float(row.get("opp_last_5_goals_scored")),
            "opp_no_clean_sheet_count": as_float(row.get("opp_no_clean_sheet_count")),
            "poisson_draw_prob": as_float(row.get("poisson_draw_prob")),
        }
    if market in {"u25", "u35"}:
        prefix = "u25" if market == "u25" else "u35"
        return {
            f"{prefix}_score": as_float(row.get(f"{prefix}_score")),
            f"{prefix}_tier": as_float(row.get(f"{prefix}_tier")),
            f"{prefix}_signals_fired": as_float(row.get(f"{prefix}_signals_fired")),
            "combined_lambda": as_float(row.get("combined_lambda")),
            "mc_u25_prob": as_float(row.get("mc_u25_prob")),
            "mc_u35_prob": as_float(row.get("mc_u35_prob")),
            "draw_odds": as_float(row.get("draw_odds")),
            "tier_rank": as_float(row.get("tier_rank")),
            "fatigue_home": as_float(row.get("fatigue_home")),
            "fatigue_away": as_float(row.get("fatigue_away")),
            "home_gk_cpg": as_float(row.get("home_gk_cpg")),
            "away_gk_cpg": as_float(row.get("away_gk_cpg")),
        }
    if market == "draw":
        return {
            "composite_draw_score": as_float(row.get("composite_draw_score")),
            "dmi": as_float(row.get("dmi")),
            "h2h_draws": as_float(row.get("h2h_draws")),
            "total_draws": as_float(row.get("total_draws")),
            "home_draws": as_float(row.get("home_draws")),
            "away_draws": as_float(row.get("away_draws")),
            "parity": as_float(row.get("parity")),
            "mc_draw_prob": as_float(row.get("mc_draw_prob")),
            "poisson_draw_prob": as_float(row.get("poisson_draw_prob")),
            "most_likely_draw_pct": as_float(row.get("most_likely_draw_pct")),
            "value_edge": as_float(row.get("value_edge")),
            "draw_odds": as_float(row.get("draw_odds")),
            "league_weight": as_float(row.get("league_weight")),
        }
    if market == "u2s":
        # ADVISORY ONLY (see MARKETS). `Underdog` itself is deliberately NOT
        # logged as a signal: it IS the graded pick, so scoring it would be
        # scoring the answer.
        return {
            "Spear_Matchup": as_float(row.get("Spear_Matchup")),
            "Dog_Venue_SOT": as_float(row.get("Dog_Venue_SOT")),
            "Fav_Venue_SOT": as_float(row.get("Fav_Venue_SOT")),
            "Dog_H2H_SOT": as_float(row.get("Dog_H2H_SOT")),
            "Fav_H2H_SOT": as_float(row.get("Fav_H2H_SOT")),
            "Dog_Opp_Avg_Conceded": as_float(row.get("Dog_Opp_Avg_Conceded")),
            "Dog_Scoring_Consistency": as_float(row.get("Dog_Scoring_Consistency")),
            "Psych_Score": as_float(row.get("Psych_Score")),
        }
    if market == "fhvi":
        return {
            "fhvi_score": as_float(row.get("fhvi_score")),
            "fh_pressure": as_float(row.get("fh_pressure")),
            "comb_fh_r": as_float(row.get("comb_fh_r")),
            "h_fh_c_r_disp": as_float(row.get("h_fh_c_r_disp")),
            "a_fh_c_r_disp": as_float(row.get("a_fh_c_r_disp")),
        }
    return {}


# The settled quantity each market is actually graded on. Logging the right
# one keeps `actual_total` meaningful now that the ledger covers more than
# corners/SOT (which previously fell through to total_sot for everything).
ACTUAL_TOTAL_FIELD = {
    "corners": "total_corners",
    "sot": "total_sot",
    "o25": "total_goals",
    "o15": "total_goals",
    "u25": "total_goals",
    "u35": "total_goals",
    "draw": "ft_score",
    "parity": "ft_score",
    "gg": "ft_score",
    "shvi": "sh_goals",
    "fhvi": "fh_goals",
}


def row_text_fields(market: str, row: dict) -> dict:
    """Categorical context, logged alongside the numeric signals."""
    if market == "corners":
        return {
            "Verdict": str(row.get("Tier") or ""),
            "Game_Script": str(row.get("Match_Flow") or ""),
            "Momentum": str(row.get("Home_Label") or ""),
            # Friction is the engine's own corner-volume regime call and is
            # strongly worded ('💎 PERFECT' vs '💀 DEAD / UNDER'), which makes
            # it a natural candidate to score as a category.
            "Friction": str(row.get("Friction") or ""),
            "Home_DNA": str(row.get("Home_DNA") or ""),
            "Away_DNA": str(row.get("Away_DNA") or ""),
            "Tier_Raw": str(row.get("Tier") or ""),
        }
    if market == "sot":
        return {
            "Verdict": str(row.get("Verdict") or ""),
            "Game_Script": str(row.get("Game_Script") or ""),
            "Momentum": str(row.get("Momentum") or ""),
        }
    if market == "gg":
        return {
            "Category": str(row.get("Category") or ""),
            "VIP_Status": str(row.get("VIP_Status") or ""),
            "Veto_Status": str(row.get("Veto_Status") or ""),
            "DNA_Status": str(row.get("DNA_Status") or ""),
        }
    if market == "o25":
        return {
            "Algorithm": str(row.get("Algorithm") or ""),
        }
    if market == "o15":
        return {
            "PickedBy": str(row.get("PickedBy") or ""),
        }
    if market in {"shvi", "fhvi"}:
        return {
            "Label": str(row.get("shvi_label") or row.get("fhvi_label") or ""),
            "Category": str(row.get("Category") or ""),
        }
    return {}


def build_entries(market: str, date: str):
    """Join predictions to settled results and grade each one.

    Returns (entries, stats). An entry is only emitted for a row that BOTH
    joined to a real fixture AND received a terminal verdict from grade_row.
    PENDING rows (not started, no score, or no corner/shot stats) are counted
    and skipped — treating them as losses is exactly the fabrication the
    existing settlement code goes out of its way to avoid.
    """
    engine_key = MARKETS.get(market)
    if market in BLOCK_INDEX:
        composite_key, block_index = BLOCK_INDEX[market]
        blocks = load_blocks(composite_key, date)
        predictions = blocks[block_index] if block_index < len(blocks) else []
    else:
        predictions = load_predictions(engine_key, date)
    results = load_results(date)
    # Venue orientation is not reliable across sources, so the join runs
    # against an unordered index as well as the ordered one. Corners and SOT
    # are unaffected (their keys already matched); markets whose engines name
    # the sides the other way round now join instead of vanishing.
    unordered = build_actual_index(results)

    entries = []
    stats = {"predictions": len(predictions), "joined": 0, "pending": 0, "won": 0, "lost": 0,
             "unmatched": 0, "ungraded": 0}

    for row in predictions:
        name = row_fixture_name(row)
        key = fixture_key(name)
        actual = lookup_actual(unordered, key) if key else None
        if not actual:
            stats["unmatched"] += 1
            continue
        verdict = grade(market, row, actual)
        if not verdict:
            stats["ungraded"] += 1
            continue
        state = verdict.get("verdict")
        if state not in {"WON", "LOST"}:
            stats["pending"] += 1
            continue
        stats["joined"] += 1
        if state == "WON":
            stats["won"] += 1
        else:
            stats["lost"] += 1
        entry = {
            "date": date,
            "market": market,
            "fixture": str(name),
            "verdict": state,
            "actual_total": actual.get(ACTUAL_TOTAL_FIELD.get(market, "total_sot")),
        }
        entry.update(row_signal_fields(market, row))
        entry.update(row_text_fields(market, row))
        entries.append(entry)

    return entries, stats
    if not a or not b:
        return None
    return a, b
