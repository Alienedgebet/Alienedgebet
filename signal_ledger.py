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
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "output", "cache")
ARCHIVE_DIR = os.path.join(ROOT, "output")
DATA_DIR = os.path.join(ROOT, "data")
LEDGER_PATH = os.path.join(DATA_DIR, "signal_ledger.jsonl")

# market -> prediction cache key
MARKETS = {
    "corners": "corners_aggregator",
    "sot": "sot",
}

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
        return float(value)
    text = str(value).strip()
    if not text or text in {"N/A", "None", "nan", "-", "--"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def prediction_path(engine_key: str, date: str) -> str:
    return os.path.join(CACHE_DIR, f"{engine_key}__{date}.json")


def archive_path(date: str) -> str:
    return os.path.join(ARCHIVE_DIR, f"archive_{date}.json")


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
    return {}


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
    return {}


def build_entries(market: str, date: str):
    """Join predictions to settled results and grade each one.

    Returns (entries, stats). An entry is only emitted for a row that BOTH
    joined to a real fixture AND received a terminal verdict from grade_row.
    PENDING rows (not started, no score, or no corner/shot stats) are counted
    and skipped — treating them as losses is exactly the fabrication the
    existing settlement code goes out of its way to avoid.
    """
    engine_key = MARKETS[market]
    predictions = load_predictions(engine_key, date)
    results = load_results(date)

    entries = []
    stats = {"predictions": len(predictions), "joined": 0, "pending": 0, "won": 0, "lost": 0,
             "unmatched": 0, "ungraded": 0}

    for row in predictions:
        name = row.get("fixture") or row.get("Fixture") or ""
        key = fixture_key(name)
        actual = results.get(key) if key else None
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
            "actual_total": actual.get("total_corners" if market == "corners" else "total_sot"),
        }
        entry.update(row_signal_fields(market, row))
        entry.update(row_text_fields(market, row))
        entries.append(entry)

    return entries, stats
    if not a or not b:
        return None
    return a, b
