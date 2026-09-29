"""
SIGNED IMPACT — is a team hurt, helped, or merely churning?
=========================================================

WHY THIS MODULE EXISTS
----------------------
Stage 4 decided DANGER vs SAFE with a headcount:

    breached = (len(missing_details) >= 4) or gk_hole
    danger_level = "DANGER" if breached else "SAFE"

and computed a `vulnerability_pct` that it displayed on the card and then never
used. That is why the label looked arbitrary: the number the user could see had
no influence on the verdict at all.

A headcount also cannot express the most important truth about an absence:

    losing your BEST players is damage;
    losing your WORST players is, on the evidence, an upgrade.

Measuring the live board against the engine's own numbers showed 10 of 22 sides
labelled DANGER while the players who left were, on average, WORSE than the
players who stayed. Northern Ireland vs Hungary was the clearest case: 8 players
missing — the heaviest damage on the board — with the eight out averaging 6.83
against 7.41 for the eleven who started. It was painted as the most damaged team
in the feed and was in fact the most improved.

THE SIGN CONVENTION (the whole point)
-------------------------------------
    net_impact > 0  ->  DANGER   (quality was LOST)
    net_impact < 0  ->  BLESSING (the XI was UPGRADED)
    confidence low  ->  ROTATION (churn; no directional call)

Three states, not two, because the evidence base is often too thin to support a
call in either direction. On the live board, 77% of "missing key players" had
fewer than three appearances of history behind them. Forcing a binary verdict on
a 2-appearance sample replaces one false claim with another. ROTATION is the
honest home for that case, and it suppresses directional picks rather than
guessing.

WHY CONFIDENCE SHRINKS THE NUMBER
--------------------------------
Measured on the live cache: 62% of the 11,045 players the engines treated as
"key" were rated BELOW average (mean 6.71). The worth formula is dominated by an
`apps * 8000` term, roughly an order of magnitude above the rating contribution,
so "key player" substantially means "played a lot", not "was good".

A raw rating difference computed from one or two appearances is noise. Each

THE REGIME GATE
---------------
Rotation is not equally costly depending on what the market expects. A strong
favourite's XI *is* the product: removing good players from it is genuinely
dangerous, so DANGER is easier to justify. For a big dog the XI is already
expected to lose, so rotation is nearly free and an improvement is a real upside
tail rather than a risk. Market odds are the only honest proxy for that
expectation, and this is the first point at which Stage 4 ever sees them.

    odds <= FAVOURITE_MAX  ->  STRONG_FAVOURITE  (tighten DANGER)
    odds >= OUTSIDER_MIN   ->  BIG_DOG           (loosen DANGER)
    otherwise              ->  MID_FIELD

A backtest on 220 team-matches from the history cache found the rotation effect
real but asymmetric: high-churn sides scored +0.48 more goals (t=+2.58,
significant) while conceding slightly FEWER. That is a per-team ATTACK uplift,
not an open-game effect, so it is deliberately NOT wired to Over 2.5 / Over 1.5,
where the same sample returned z=1.41 and z=0.34 — not significant.

THE GOALKEEPER
--------------
`calculate_gk_vulnerability_pro` returned `(85.0, True, "DEBUT/UNKNOWN GK
(Max Risk)")` whenever it could not find a starting keeper, and 26% of cached
keepers have under 3 appearances. A debutant is UNKNOWN, not guilty: absence of
data was being converted into the maximum penalty. An unlisted keeper is now
UNKNOWN, and DANGER requires a *proven* keeper (>= 3 apps) replaced by a
*weaker proven* one, or no keeper named at all on a strong favourite.

NOTHING HERE CALLS THE PROVIDER
-------------------------------
This module is pure computation over already-parsed squad maps and lineup ids.
The rating, apps, minutes and worth of every player involved are already being
computed by Stages 1/3/4 and are currently discarded before the verdict is made.
This module consumes them; it adds no SportMonks calls and no quota cost.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Positional weights: how much a unit of quality is worth to a team, and the
# denominator for the share-of-importance figures Stages 1/3 already publish.
# Goalkeeper dominates because a keeper is the single most consequential
# position, and that is also why a missing keeper has always dominated the
# missing-player list.
POS_WEIGHTS: Dict[str, float] = {
    "Goalkeeper": 50.0,
    "Defender": 9.0,
    "Midfielder": 4.5,
    "Attacker": 1.5,
    "Unknown": 3.0,
}

# The rating an average professional performance sits at. Measured across the
# cached key players: mean 6.71, median 6.72, so 6.8 is the honest "no better
# or worse than typical" line. Subtract it so the sign reads as
# better-than-typical / worse-than-typical rather than absolute rating.
DEFAULT_BASELINE = 6.8

# Evidence required before a player's quality difference is trusted at full
# weight: the bulk of a normal league season, so a two-appearance cameo does
# not qualify.
FULL_CONFIDENCE_APPS = 8.0
FULL_CONFIDENCE_MINS = 720.0

# Below this mean confidence across the missing players, the evidence is too
# thin to call the fixture either way and the verdict is ROTATION.
MIN_CONFIDENCE_FOR_CALL = 0.45

# A goalkeeper needs this many appearances before the engine is allowed to
# describe its quality at all (mirrors the existing small-sample guard).
PROVEN_GK_APPS = 3

# Market regime boundaries, in decimal odds for the favourite of the match.
FAVOURITE_MAX = 1.60
OUTSIDER_MIN = 2.60

# Per-team attack uplift measured on the history-cache backtest: high-churn
# sides scored +0.48 more goals. Applied to that team's own scoring markets, and
# deliberately not to Over/Under, where the same sample was not significant.
ROTATION_ATTACK_UPLIFT = 0.48

STATE_DANGER = "DANGER"
STATE_ROTATION = "ROTATION"
STATE_BLESSING = "BLESSING"
STATE_UNKNOWN = "UNKNOWN"

# Regime bars: the absolute net impact DANGER / BLESSING must clear.
#
# Calibrated against the live board's own distribution of |net_impact| after the
# symmetric confidence fix (n=21): p25=2.7, p50=4.6, p75=6.4, p90=8.9, max=25.
#
# MID_FIELD sits at 6.0, just under p75, so a verdict is only issued when the
# effect is larger than a typical one — the asymmetry between a clearly-signed
# result and noise.
#
# The regime spread is deliberately narrow (8 / 6 / 3.5) rather than dramatic.
# Rotation is not equally costly, but odds are a weak proxy for how much an XI
# matters, and an aggressive spread would let a coin-flip price silently flip a
# verdict. The ordering is what carries the meaning, not the magnitude:
#   a strong favourite's XI IS the product, so it takes a bigger hit to call it
#   damaged; a big dog's XI is already written off, so less does.
_DANGER_BAR = {
    "STRONG_FAVOURITE": 8.0,
    "MID_FIELD": 6.0,
    "BIG_DOG": 3.5,
}


def confidence(apps: Any, mins: Any) -> float:
    """How much a player's quality difference deserves to be believed, 0.0-1.0.

    Full weight at FULL_CONFIDENCE_APPS appearances AND
    FULL_CONFIDENCE_MINS minutes; scaled by whichever is scarcer, combined
    geometrically so a player with plenty of minutes but two caps still earns
    very little. Never raises, never returns NaN on junk input, and treats a
    missing/negative value as zero evidence rather than as a data error.
    """
    try:
        a = float(apps or 0)
    except (TypeError, ValueError):
        a = 0.0
    try:
        m = float(mins or 0)
    except (TypeError, ValueError):
        m = 0.0
    a = max(0.0, a)
    m = max(0.0, m)
    return math.sqrt(min(1.0, a / FULL_CONFIDENCE_APPS) * min(1.0, m / FULL_CONFIDENCE_MINS))


def regime_for_odds(favourite_odds: Any) -> str:
    """Classify what the market expects of the team being judged.

    `favourite_odds` is the shorter of the two 1X2 prices. Absent or unusable
    odds resolve to MID_FIELD rather than to a confident band, because the
    regime is a modifier on the verdict and guessing it would silently bias
    every fixture the provider has no price for.
    """
    try:
        o = float(favourite_odds)
    except (TypeError, ValueError):
        return "MID_FIELD"
    if not (o > 0) or o != o:  # also rejects NaN
        return "MID_FIELD"
    if o <= FAVOURITE_MAX:
        return "STRONG_FAVOURITE"
    if o >= OUTSIDER_MIN:
        return "BIG_DOG"
    return "MID_FIELD"


def _pos_weight(pos: Any) -> float:
    return POS_WEIGHTS.get(str(pos or "Unknown"), POS_WEIGHTS["Unknown"])


def _rating_of(player: Optional[Dict[str, Any]]) -> Optional[float]:
    """Read a player's average rating, tolerating the field names in use."""
    if not isinstance(player, dict):
        return None
    for key in ("avg_rating", "rating"):
        raw = player.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val == val:  # not NaN
            return val
    return None


def assess_absence(
    missing: Sequence[Dict[str, Any]],
    starters: Sequence[Dict[str, Any]],
    regime: str = "MID_FIELD",
    baseline: float = DEFAULT_BASELINE,
) -> Dict[str, Any]:
    """Score one side's XI against its own historical key eleven.

    `missing`  — key-eleven player records that are NOT in today's XI. Each may
                 carry `avg_rating`/`rating`, `apps`, `mins`, `pos`.
    `starters` — today's starting XI records, the comparison group for "what we
                 are putting in instead". An empty `starters` is legal: the
                 missing side is still scored, but the verdict is UNKNOWN rather
                 than damage, since the upgrade claim is meaningless without a
                 replacement group to compare against.

    Returns the signed net impact, the confidence behind it, the verdict, and a
    per-player breakdown so the UI can show its work instead of printing an
    unexplained percentage.
    """
    missing = [p for p in (missing or []) if isinstance(p, dict)]
    starters = [p for p in (starters or []) if isinstance(p, dict)]

    detail: List[Dict[str, Any]] = []
    lost = 0.0
    confs: List[float] = []

    for p in missing:
        w = _pos_weight(p.get("pos"))
        rating = _rating_of(p)
        c = confidence(p.get("apps"), p.get("mins"))
        if rating is None:
            # No rating at all. Contribution and confidence are both zero: the
            # engine does not get to guess that an unknown player was good.
            c = 0.0
            delta = 0.0
        else:
            delta = w * (rating - baseline)
        contribution = delta * c
        lost += contribution
        confs.append(c)
        detail.append({
            "name": p.get("name") or "?",
            "pos": p.get("pos") or "Unknown",
            "rating": rating,
            "apps": p.get("apps"),
            "mins": p.get("mins"),
            "weight": w,
            "confidence": round(c, 3),
            "signed_contribution": round(contribution, 2),
        })

    # The replacement group is shrunk on the SAME curve as the missing group.
    #
    # An earlier version of this deliberately did not shrink it, on the reasoning
    # that a player on the pitch is an observation rather than an estimate. That
    # was wrong, and measurably so: a replacement seen once for 90 minutes with
    # a 6.90 rating contributed a full 0.15 of credit, silently cancelling a real
    # 1.27 of genuine quality loss and turning a clear DANGER into ROTATION.
    # The two sides of a subtraction have to be measured on the same ruler, or
    # the noisier one silently wins. Presence on the pitch tells you WHO is
    # playing; it says nothing about how reliably you know their rating.
    gained = 0.0
    for p in starters:
        w = _pos_weight(p.get("pos"))
        rating = _rating_of(p)
        if rating is None:
            continue
        c = confidence(p.get("apps"), p.get("mins"))
        gained += w * (rating - baseline) * c

    # A full-strength XI has no absence to offset, so the replacement credit is
    # only ever subtracted from a real loss. Without this guard a side with
    # NOTHING missing still returned net = lost - gained = -gained, i.e. the
    # replacement group's own deviation from the baseline was published as
    # signed impact. That is what made a zero-absence side score -9.43..+14.22
    # and read as BLESSING or DANGER purely on squad quality, while the engine
    # reported "Full-strength spine" in the verdict_reason and moved on.
    #
    # The number is documented as the damage done by absences, so with no
    # absences the honest value is exactly zero.
    if not missing:
        gained = 0.0

    net = lost - gained
    mean_conf = (sum(confs) / len(confs)) if confs else 0.0
    verdict, why = _verdict_for(net, mean_conf, regime, len(missing), bool(starters))

    return {
        "net_impact": round(net, 2),
        "confidence": round(mean_conf, 3),
        "verdict": verdict,
        "verdict_reason": why,
        "regime": regime,
        "missing_count": len(missing),
        "quality_lost": round(lost, 2),
        "replacement_credit": round(gained, 2),
        "rotation_uplift": (
            ROTATION_ATTACK_UPLIFT if verdict == STATE_ROTATION else 0.0
        ),
        "details": detail,
    }


def _verdict_for(
    net: float, mean_conf: float, regime: str,
    missing_count: int, has_starters: bool,
) -> Tuple[str, str]:
    """The three-way verdict and the sentence explaining it.

    Order matters: unusable evidence is rejected before any direction is
    claimed, because a confident label on a two-appearance sample is the exact
    failure this module exists to remove.
    """
    band = str(regime or "MID_FIELD").lower().replace("_", " ")
    if not has_starters:
        return STATE_UNKNOWN, (
            "No starting XI available to compare against — the upgrade half of "
            "the comparison is impossible, so no verdict is issued."
        )
    if missing_count == 0:
        return STATE_UNKNOWN, (
            "Full-strength spine — every key player is in the starting XI."
        )
    if mean_conf < MIN_CONFIDENCE_FOR_CALL:
        return STATE_ROTATION, (
            f"{missing_count} key player(s) absent, but the evidence behind them "
            f"averages only {mean_conf:.2f} confidence (under "
            f"{MIN_CONFIDENCE_FOR_CALL}) — too thin to call this hurt or helped, "
            f"so it is treated as rotation."
        )
    bar = _DANGER_BAR.get(regime, _DANGER_BAR["MID_FIELD"])
    if net > bar:
        return STATE_DANGER, (
            f"{missing_count} key player(s) absent and the XI is measurably WORSE "
            f"for it (net impact {net:+.1f} against a {band} bar of {bar:.0f}, "
            f"confidence {mean_conf:.2f}) — this is your winners being out."
        )
    if net < -bar:
        return STATE_BLESSING, (
            f"{missing_count} key player(s) absent, but those who left were WORSE "
            f"than the eleven now starting (net impact {net:+.1f}, confidence "
            f"{mean_conf:.2f}) — the rotation has upgraded this side."
        )
    return STATE_ROTATION, (
        f"{missing_count} key player(s) absent with net impact {net:+.1f}, which "
        f"does not clear the {bar:.0f} bar for a {band} fixture (confidence "
        f"{mean_conf:.2f}) — churn, not damage."
    )


def assess_goalkeeper(
    starting_gk: Optional[Dict[str, Any]],
    master_gk: Optional[Dict[str, Any]],
    regime: str = "MID_FIELD",
    leak: Optional[float] = None,
) -> Dict[str, Any]:
    """Judge the keeper in the starting XI against the keeper history expects.

    The governing correction is that an unknown keeper is UNKNOWN, not guilty.
    The old code returned the maximum penalty (85/100, is_liability=True,
    "DEBUT/UNKNOWN GK (Max Risk)") purely because it could not find a starting
    keeper, and 26% of cached keepers have under three appearances — so a large
    part of the fleet was convicted on a blank.

    DANGER now requires a PROVEN keeper (>= PROVEN_GK_APPS) to have been
    replaced by a weaker PROVEN one, or no keeper named at all on a strong
    favourite, where an unplayable keeper genuinely decides the match.
    """
    if not isinstance(starting_gk, dict):
        if regime == "STRONG_FAVOURITE":
            return {
                "liability": True, "label": STATE_DANGER, "confidence": 0.0,
                "note": (
                    "No goalkeeper identified in the starting XI on a strong "
                    "favourite — unplayable at this level, so this is a real risk."
                ),
            }
        return {
            "liability": False, "label": STATE_UNKNOWN, "confidence": 0.0,
            "note": (
                "Goalkeeper not identified in the historical data. Treated as "
                "UNKNOWN, not as a liability: absence of evidence is not evidence "
                "of weakness."
            ),
        }

    rating = _rating_of(starting_gk)
    try:
        apps = float(starting_gk.get("apps") or 0)
    except (TypeError, ValueError):
        apps = 0.0

    if apps < PROVEN_GK_APPS:
        return {
            "liability": False, "label": STATE_UNKNOWN,
            "confidence": round(confidence(apps, starting_gk.get("mins")), 3),
            "note": (
                f"Starting keeper has {apps:.0f} appearance(s) on record — a debut "
                f"or a handful of games. Unproven, not proven poor: no verdict."
            ),
        }

    if rating is None:
        return {
            "liability": False, "label": STATE_UNKNOWN,
            "confidence": round(confidence(apps, starting_gk.get("mins")), 3),
            "note": "Starting keeper has no recorded rating — unknown, no verdict.",
        }

    c = confidence(apps, starting_gk.get("mins"))
    master_rating = _rating_of(master_gk) if isinstance(master_gk, dict) else None
    try:
        master_apps = float((master_gk or {}).get("apps") or 0)
    except (TypeError, ValueError):
        master_apps = 0.0

    if master_rating is not None and master_apps >= PROVEN_GK_APPS:
        gap = rating - master_rating
        if gap <= -0.25:
            return {
                "liability": True, "label": STATE_DANGER, "confidence": round(c, 3),
                "note": (
                    f"Proven keeper replaced: the expected No.1 rates "
                    f"{master_rating:.2f}, the keeper starting rates {rating:.2f} — "
                    f"a {abs(gap):.2f} downgrade behind a settled defence."
                ),
            }
        return {
            "liability": False,
            "label": STATE_BLESSING if gap >= 0.25 else STATE_ROTATION,
            "confidence": round(c, 3),
            "note": (
                f"Proven keeper starting (rating {rating:.2f} vs the expected "
                f"No.1's {master_rating:.2f}) — the goal is not a downgrade."
            ),
        }

    # No proven benchmark. Fall back on the leak signal only if it exists.
    if leak is not None and leak > 1.6:
        return {
            "liability": True, "label": STATE_DANGER, "confidence": round(c, 3),
            "note": (
                f"Keeper concedes {leak:.2f} per 90 over {apps:.0f} appearance(s) — "
                f"a genuine leak, with no established No.1 to compare against."
            ),
        }
    return {
        "liability": False, "label": STATE_ROTATION, "confidence": round(c, 3),
        "note": (
            f"Proven keeper starting (rating {rating:.2f}) but no historical No.1 to "
            f"benchmark against — assumed competent rather than assumed guilty."
        ),
    }


def split_by_squad_map(
    key_eleven: Sequence[Dict[str, Any]],
    starting_ids: Sequence[Any],
    bench_ids: Optional[Sequence[Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partition the key eleven into the absent and the retained.

    A key player counts as PRESENT if they are in today's starting XI, or — when
    `bench_ids` is supplied — if they are named on the bench (type_id 12). Being
    named on the bench is not an injury: the previous audit treated every
    benched regular as MISSING, which is how an ordinary rotation produced a
    DANGER badge.
    """
    start = {str(i) for i in (starting_ids or [])}
    bench = {str(i) for i in (bench_ids or [])}
    missing, retained = [], []
    for p in key_eleven or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        present = pid in start or pid in bench
        (retained if present else missing).append(p)
    return missing, retained
