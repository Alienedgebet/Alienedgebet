"""
STAGE 8 — live match prediction for users.

WHAT THIS IS FOR
----------------
A user types two team names into the search bar and gets, instantly and with no
API call, an honest read of the match as it stands: who is likely to win, who is
likely to draw, who is likely to score, and where the goal total is heading.

WHY IT IS NOT CODE 6's STORM
----------------------------
Code 6 fires on `structural_break`, which needs one squad rated twice as weak as
the other AND the stronger side controlling the match. Both halves of that are
either static (the squad rating never changes during a match) or need ~45
minutes for pressure to separate at all — so in the recorded history not one
alert fired before 45'. This engine instead reasons from MINUTES REMAINING and
live chance creation, which are meaningful from the first minute.

THE MODEL
---------
A live model has to be anchored somewhere honest, or it is inventing. The book
is the anchor:

  1. Over-2.5 price  ->  expected total goals for the full match (de-vigged,
     inverted through a Poisson CDF).
  2. 1X2 price       ->  how that total splits between the two sides.
  3. Live reality    ->  how much of that total is still unspent, and whether
     the match is running hotter or colder than the price implied.
  4. Structure      ->  a missing key player lowers that side's output; a
     liability keeper raises the opponent's.

Steps 1-3 are the same arithmetic on both sides, so they cannot favour anyone.
Step 4 is the only place the pre-match intelligence is allowed to speak, and it
is bounded and disclosed.

Every published number carries the trace of questions that produced it, and
five independent judges must clear it before it is shown.
"""
import json
import math
import os
import time

from .live_prediction_questions import build_trace, REQUIRED_QUESTION_IDS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

BOARD_FILE = os.path.join(OUTPUT_DIR, "orchestrator_board.json")
DANGER_FILE = os.path.join(DATA_DIR, "danger_audit.json")
PREMATCH_FILE = os.path.join(DATA_DIR, "prematch_team_audit.json")
# NOT "live_predictions.json" — that file belongs to Code 1
# (live_stage1_prematch.PREDICTIONS_FILE) and holds the daily picks feed. The
# first draft of this engine pointed here and overwrote Code 1's output on
# every cycle. Stage 1 rewrites it each run so it self-heals, but two engines
# sharing one filename means one silently destroys the other, and neither finds
# out. Namespaced to this stage instead.
OUTPUT_FILE = os.path.join(DATA_DIR, "stage8_live_prediction.json")

REGULATION_MINUTES = 90
# How far the structural layer is allowed to move the split. Bounded on
# purpose: an unbacktested adjustment must not be able to overturn the market.
MAX_STRUCTURAL_SHIFT = 0.18

# Fallback anchor, used only when a fixture has NO prematch price.
#
# WHY THIS EXISTS: Code 1 admits a fixture to the prematch board only once the
# provider returns an official lineup. On the live board right now that is 1
# fixture in 5 — the rest are INSUFFICIENT purely because nobody priced them
# for us, which makes the engine useless exactly where a user is most likely to
# ask about it.
#
# So when there is no price, the anchor becomes the match's OWN observed chance
# creation, shrunk toward a league-average goal rate. It is a real estimate from
# real xG and shot counts, not a guess — but it is weaker than a price, so it is
# named in `model.anchor` and the market judge downgrades it to WARN rather
# than passing it as if a bookmaker had endorsed it.
FALLBACK_GOAL_RATE = 2.65      # league-average goals per match
FALLBACK_PRIOR_STRENGTH = 45.0  # pseudo-minutes of prior; higher = more shrink
SHOT_TO_GOAL_WEIGHT = 0.30     # blend of shots-on-target alongside xG


def _live_anchor_goals(board, stats, played):
    """
    Estimate expected total goals from the match's own chance creation, shrunk
    toward the league average.

    Shrinkage is not decoration: a 20-minute sample of shots and xG extrapolated
    to 90 minutes is wildly unstable, so the observed rate is given weight
    (elapsed / (elapsed + prior)) and the rest comes from the base rate.
    """
    h_xg = float(board.get("h_xg") or 0.0)
    a_xg = float(board.get("a_xg") or 0.0)
    sot = 0.0
    for side in ("home", "away"):
        block = stats.get(side) or {}
        if isinstance(block, dict):
            sot += float(block.get("shots-on-target") or 0.0)
    observed_equiv = (1.0 - SHOT_TO_GOAL_WEIGHT) * (h_xg + a_xg) \
        + SHOT_TO_GOAL_WEIGHT * sot
    if observed_equiv <= 0:
        return None
    observed_rate = observed_equiv / played
    extrapolated = observed_rate * REGULATION_MINUTES
    weight = played / (played + FALLBACK_PRIOR_STRENGTH)
    return max(0.2, min(6.0,
                        weight * extrapolated
                        + (1.0 - weight) * FALLBACK_GOAL_RATE))


def _load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _as_rows(data):
    """Accept a list of records or a mapping keyed by id. Never guess further."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        out = []
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            row.setdefault("fixture_id", key)
            out.append(row)
        return out
    return []


# ── Poisson helpers ────────────────────────────────────────────────────────
def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_at_least_one(lam):
    """P(X >= 1). Used for every to-score line."""
    return 1.0 - math.exp(-lam) if lam > 0 else 0.0


def poisson_between(lo, hi, lam):
    return sum(poisson_pmf(k, lam) for k in range(lo, hi + 1))


def implied_total_goals(odds_over25, min_goals=0.35, max_goals=6.0):
    """
    Invert an over-2.5 price into the expected total goals it implies.

    Solves P(X > 2.5) = 1/price for lambda under a Poisson. Bisection, not a
    closed form: there isn't one, and a wrong lambda here silently shifts every
    goal market on the page.

    THE BOUNDARY CHECK WAS INVERTED IN AN EARLIER DRAFT. It asked whether
    P(0-2 goals) at the ceiling was still BELOW the target, which is true for
    almost every price, and so returned the ceiling 12.0 for every fixture
    instead of the answer. lambda 12 is twelve expected goals: it produced 100%
    "to score" and 98.9% over-2.5 on a match priced at 5.5. A comparison that
    cannot match, silently returning a boundary — the fifth of this family.

    Football totals live roughly between 0.35 and 6.0 expected goals. A price
    implying more than that is not a market view, so it is refused rather than
    clamped: a wrong anchor would corrupt every number downstream.
    """
    if not odds_over25 or float(odds_over25) <= 1.0:
        return None
    target = 1.0 / float(odds_over25)
    lo, hi = 0.01, 20.0
    # Unreachable only if even the ceiling produces too FEW overs.
    if (1.0 - poisson_between(0, 2, hi)) < target:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if (1.0 - poisson_between(0, 2, mid)) < target:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    if lam < min_goals or lam > max_goals:
        return None
    return lam


def devig_two_way(price_a, price_b):
    """Strip the bookmaker's overround from a two-way market."""
def load_context(fixture_id):
    """
    Assemble the feeds for one fixture.

    Returns None only when the fixture is not on the live board at all. A
    fixture that IS live but has no pre-match intelligence still returns a
    context — it will be labelled LIVE_ONLY, which is very different from being
    silently absent.
    """
    board_rows = _as_rows((_load(BOARD_FILE, {}) or {}).get("matches", [])
                          if isinstance(_load(BOARD_FILE, {}), dict) else [])
    board = next((m for m in board_rows
                  if str(m.get("id")) == str(fixture_id)), None)
    if board is None:
        return None

    danger_rows = _as_rows(_load(DANGER_FILE, []))
    danger_row = next((r for r in danger_rows
                       if str(r.get("fixture_id")) == str(fixture_id)), None)

    pm_rows = _as_rows(_load(PREMATCH_FILE, {}))
    pm = next((r for r in pm_rows
               if str(r.get("fixture_id")) == str(fixture_id)), None)

    danger = {
        "home_team": (danger_row or {}).get("home_team") or {},
        "away_team": (danger_row or {}).get("away_team") or {},
        "home_name": ((danger_row or {}).get("home_team") or {}).get(
            "team_name") or (pm or {}).get("home", {}).get("team_name"),
        "away_name": ((danger_row or {}).get("away_team") or {}).get(
            "team_name") or (pm or {}).get("away", {}).get("team_name"),
        "available": danger_row is not None,
    }
    # Fall back to the board's own name when no audit names the sides.
    if not danger["home_name"] or not danger["away_name"]:
        name = str(board.get("name") or "")
        for sep in (" vs ", " v ", " - "):
            if sep in name:
                home, _, away = name.partition(sep)
                danger["home_name"] = danger["home_name"] or home.strip()
                danger["away_name"] = danger["away_name"] or away.strip()
                break

    odds = {}
    if pm:
        odds = {"home": pm.get("odds_home_win"),
                "away": pm.get("odds_away_win"),
                "over25": pm.get("odds_o25")}

    stats = board.get("statistics") or {}
    h_goals = (stats.get("home") or {}).get("goals")
    a_goals = (stats.get("away") or {}).get("goals")

    return {
        "fixture_id": str(fixture_id),
        "board": board,
        "danger": danger,
        "prematch": pm or {},
        "odds": odds,
        "score": {"home": int(h_goals or 0), "away": int(a_goals or 0)},
        "mode": "FULL" if danger["available"] else "LIVE_ONLY",
    }


def normalise(text):
    """Lowercase, strip punctuation and accents so a typed name still matches."""
    import unicodedata
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKD", str(text))
    cleaned = "".join(c for c in cleaned if not unicodedata.combining(c))
    cleaned = cleaned.lower()
    for ch in ".'’,-_()":
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


def _tokens(text):
    """Words worth matching on — drop the noise words that appear in no club."""
    noise = {"fc", "afc", "cf", "sc", "ac", "as", "ss", "us", "cd", "rc",
             "vs", "v", "de", "del", "la", "le", "1", "fk", "sk", "bk", "if"}
    return {w for w in normalise(text).split() if w and w not in noise}


def find_fixtures(query):
    """
    Match a typed string against the live board.

    A user types two team names in any order and with any amount of slop
    ("denmark portugal", "Denmark vs Portugal", "DENMARK"). Matching is done on
    content words with a containment rule, because a strict equality test on a
    provider name like "Dunajská Streda" fails almost every real query.
    """
    wanted = _tokens(query)
    if not wanted:
        return []
    rows = _as_rows((_load(BOARD_FILE, {}) or {}).get("matches", [])
                    if isinstance(_load(BOARD_FILE, {}), dict) else [])
    hits = []
    for m in rows:
        name = normalise(m.get("name"))
        available = _tokens(name)
        if not available:
            continue
        matched = sum(1 for w in wanted if w in available)
        # Every typed word must land somewhere, and at least two distinct team
        # words must match, or "Denmark" alone would silently match Denmark v
        # Iceland and report the wrong match.
        if matched == len(wanted) and matched >= 2:
            hits.append((matched, m))
        elif matched == len(wanted) and matched == 1 and len(wanted) == 1:
            hits.append((matched, m))
    hits.sort(key=lambda t: -t[0])
    return [m for _, m in hits]

    if not price_a or not price_b:
        return None
    if float(price_a) <= 1.0 or float(price_b) <= 1.0:
        return None
    raw_a = 1.0 / float(price_a)
    raw_b = 1.0 / float(price_b)
    total = raw_a + raw_b
    if not total:
        return None
    return raw_a / total

def _structural_shift(ctx, trace):
    """
    How far the pre-match intelligence is allowed to move the goal split.

    Bounded by MAX_STRUCTURAL_SHIFT on purpose. Signals like "liability keeper"
    and "key man out" have never been shown to beat the price on this feed, so
    they get a voice with a hard ceiling, never a veto and never an unbounded
    say. Returns (shift, supporting_question_ids).
    """
    shift = 0.0
    supporting = []
    home_gk_bad = any(q["id"] == "keeper_liability_home"
                      and q["direction"] == "for_away" for q in trace)
    away_gk_bad = any(q["id"] == "keeper_liability_away"
                      and q["direction"] == "for_home" for q in trace)

    # Both keepers flagged = no edge either way. Symmetry must cancel, or two
    # identical liabilities would manufacture a preference out of nothing.
    if home_gk_bad and not away_gk_bad:
        shift += MAX_STRUCTURAL_SHIFT * 0.5
        supporting.append("keeper_liability_home")
    elif away_gk_bad and not home_gk_bad:
        shift -= MAX_STRUCTURAL_SHIFT * 0.5
        supporting.append("keeper_liability_away")

    for side in ("home", "away"):
        q = next((x for x in trace if x["id"] == f"absences_{side}"), None)
        if q and q["available"] and q["direction"] in ("for_home",
                                                        "against_home"):
            favourable = (q["direction"] == "for_home" if side == "home"
                          else q["direction"] == "against_home")
            if favourable:
                shift += 0.02 if side == "home" else -0.02
                supporting.append(q["id"])
    return (max(-MAX_STRUCTURAL_SHIFT, min(MAX_STRUCTURAL_SHIFT, shift)),
            supporting)


def predict(fixture_id, history=None):
    """
    Produce the live prediction for one fixture.

    `history` is prior readings of this same fixture, used by the degeneracy
    judge to prove the probabilities actually respond to the clock.

    Never raises for a missing or malformed feed: an unusable fixture comes back
    as an explicit INSUFFICIENT result carrying the reason, because a confident
    number derived from nothing is worse than no number at all.
    """
    ctx = load_context(fixture_id)
    base = {"fixture_id": str(fixture_id)}
    if ctx is None:
        return {**base, "status": "NOT_LIVE",
                "error": "this fixture is not on the live board",
                "predictions": None, "trace": [], "judges": None,
                "verdict": "BLOCK"}

    board = ctx["board"]
    trace = build_trace(ctx)
    answered = {q["id"] for q in trace if q["available"]}
    missing = [q for q in REQUIRED_QUESTION_IDS if q not in answered]

    base = {"fixture_id": str(fixture_id), "fixture": board.get("name"),
            "minute": board.get("minute"),
            "score": f"{ctx['score']['home']}-{ctx['score']['away']}",
            "home_team": ctx["danger"]["home_name"],
            "away_team": ctx["danger"]["away_name"],
            "mode": ctx["mode"], "trace": trace}

    if missing:
        return {**base, "status": "INSUFFICIENT",
                "error": "no live data yet for: " + ", ".join(missing),
                "predictions": None, "judges": None, "verdict": "BLOCK"}

    played = max(1, min(int(board.get("minute") or 0), REGULATION_MINUTES))
    remaining_frac = max(
        0.0, (REGULATION_MINUTES - played) / REGULATION_MINUTES)

    total_goals = implied_total_goals(ctx["odds"].get("over25"))
    anchor = "market_price"
    board_stats = board.get("statistics") or {}
    if total_goals is None:
        # No price. Fall back to the match's own chance creation rather than
        # refusing outright — but say so, loudly, in the model block.
        total_goals = _live_anchor_goals(board, board_stats, played)
        anchor = "live_observation"
    if total_goals is None:
        return {**base, "status": "INSUFFICIENT",
                "error": "no price and no chance-creation data to anchor on",
                "predictions": None, "judges": None, "verdict": "BLOCK"}

    share = devig_two_way(ctx["odds"].get("home"), ctx["odds"].get("away"))
    if share is None:
        # Without a 1X2 price the split comes from who is actually creating
        # chances, which is the best available evidence about the same question.
        total_xg = (float(board.get("h_xg") or 0.0)
                    + float(board.get("a_xg") or 0.0))
        if total_xg > 0.05:
            share = float(board.get("h_xg") or 0.0) / total_xg
        else:
            h_press = float(board.get("h_pressure") or 0.0)
            a_press = float(board.get("a_pressure") or 0.0)
            share = (h_press / (h_press + a_press)
                     if (h_press + a_press) > 0 else 0.5)
        share = max(0.15, min(0.85, share))
    shift, supporting = _structural_shift(ctx, trace)
    share = max(0.05, min(0.95, share + shift))

    # PACE: is the match running hotter than the price implied? Compare the
    # chance quality generated so far against what the anchor expected by this
    # point. This is what makes the engine react to the match rather than
    # replay the pre-match view.
    observed = float(board.get("h_xg") or 0.0) + float(board.get("a_xg") or 0.0)
    expected_so_far = total_goals * (played / REGULATION_MINUTES)
    pace = (observed / expected_so_far) if expected_so_far > 0.05 else 1.0
    pace = max(0.55, min(2.4, pace))

    lam_home = total_goals * share * remaining_frac * pace
    lam_away = total_goals * (1.0 - share) * remaining_frac * pace
    current = ctx["score"]
    goals_already = current["home"] + current["away"]

    home_score_p = poisson_at_least_one(lam_home)
    away_score_p = poisson_at_least_one(lam_away)
    lam_left = lam_home + lam_away
    over25_p = sum(poisson_pmf(k, lam_left) for k in range(26)
                   if goals_already + k > 2)
    under35_p = sum(poisson_pmf(k, lam_left) for k in range(26)
                    if goals_already + k <= 3)
    exactly3 = sum(poisson_pmf(k, lam_left) for k in range(26)
                   if goals_already + k == 3)

    home_w = draw_w = away_w = 0.0
    for i in range(9):
        pi = poisson_pmf(i, lam_home)
        for j in range(9):
            pj = poisson_pmf(j, lam_away)
            fh, fa = current["home"] + i, current["away"] + j
            if fh > fa:
                home_w += pi * pj
            elif fh == fa:
                draw_w += pi * pj
            else:
                away_w += pi * pj
    denom = home_w + draw_w + away_w
    if denom > 0:
        home_w, draw_w, away_w = home_w / denom, draw_w / denom, away_w / denom

    predictions = {
        "home_win": round(100 * home_w, 1),
        "draw": round(100 * draw_w, 1),
        "away_win": round(100 * away_w, 1),
        "home_to_score": {"team": ctx["danger"]["home_name"],
                          "pct": round(100 * home_score_p, 1)},
        "away_to_score": {"team": ctx["danger"]["away_name"],
                          "pct": round(100 * away_score_p, 1)},
        "over_2_5": round(100 * over25_p, 1),
        "under_3_5": round(100 * under35_p, 1),
        "exactly_3_goals": round(100 * exactly3, 1),
    }
    # The market judge needs the anchor the engine actually used, so it can
    # re-derive the same number independently and catch a wrong one.
    judge_payload = dict(predictions)
    judge_payload["_anchor"] = {"anchor_total_goals": round(total_goals, 4),
                                "anchor_source": anchor}
    try:
        from .live_prediction_judges import run_judges
        panel = run_judges(ctx, judge_payload, trace, history)
    except Exception as exc:
        # A panel that cannot run is a BLOCK, not a PASS. Defaulting open here
        # would let any import error silently disable every judge.
        panel = {"verdict": "BLOCK", "judges": [],
                 "blocked_by": ["panel"],
                 "error": f"judge panel failed to run: {exc}"}

    return {**base, "status": "OK", "error": None,
            "predictions": predictions,
            "judges": panel["judges"], "verdict": panel["verdict"],
            "blocked_by": panel.get("blocked_by", []),
            "model": {"anchor": anchor,
                      "lambda_home_remaining": round(lam_home, 3),
                      "lambda_away_remaining": round(lam_away, 3),
                      "anchor_total_goals": round(total_goals, 2),
                      "pace_multiplier": round(pace, 2),
                      "structural_shift": round(shift, 3),
                      "structural_signals": supporting,
                      "minutes_remaining": int(REGULATION_MINUTES - played)}}


def run_live_prediction_engine():
    """
    Predict every fixture on the live board and publish one file.

    The file is the engine's whole output; nothing here writes to any other
    engine's file or makes a network call.
    """
    board = _load(BOARD_FILE, {})
    rows = _as_rows(board.get("matches", []) if isinstance(board, dict)
                    else board)
    out = {}
    for m in rows:
        fid = m.get("id")
        if fid is None:
            continue
        try:
            out[str(fid)] = predict(fid)
        except Exception as exc:
            out[str(fid)] = {"fixture_id": str(fid),
                             "status": "ERROR",
                             "error": f"prediction failed: {exc}",
                             "predictions": None, "trace": [],
                             "judges": None, "verdict": "BLOCK"}
    payload = {"generated_at": time.time(),
               "engines": len(rows), "predictions": out}
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, OUTPUT_FILE)
    return payload
