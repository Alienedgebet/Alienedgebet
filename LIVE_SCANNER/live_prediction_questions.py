"""
The questioning layer.

Every number the engine publishes is the answer to a question that was asked of
real data. A question is not a rhetorical device — it names the exact source
field it read, so a reader (and the Trace judge) can walk back from the
prediction to the raw value it came from.

DETERMINISTIC BY DESIGN. There is no model call here and no network access. The
same fixture always produces the same trace, and every answer is either a value
read from a cached file or an explicit "not available". Nothing is ever
generated to fill a gap.

Directions are always stated from the HOME team's point of view:
    "for_home" / "for_away" / "against_home" / "neutral"
"""

# The engine cannot answer without a clock: every probability is a function of
# minutes remaining, so `time_remaining` is the one hard requirement.
#
# It previously also demanded an over-2.5 price. That was wrong in practice: on
# the live board, 4 fixtures in 5 have no prematch price at all — Code 1 admits a
# fixture only once the provider returns an official lineup, and most live club
# matches never get one. Requiring a price made the engine refuse to answer on
# four fifths of the matches a user would actually ask about. The price is now
# the PREFERRED anchor, with the match's own chance creation as a clearly
# labelled fallback, and the market judge downgrades to WARN when the fallback
# is used so a weaker anchor can never be dressed up as a priced one.
REQUIRED_QUESTION_IDS = (
    "time_remaining",
)


def _q(qid, question, source, answer, direction, available=True):
    return {"id": qid, "question": question, "source": source,
            "answer": answer, "direction": direction,
            "available": available}


def _absence_direction(side, team):
    """A negative net_impact means the absences HELPED that side."""
    net = team.get("net_impact")
    if net is None:
        return "neutral"
    if net > 1:
        return "against_home" if side == "home" else "for_home"
    if net < -1:
        return "for_home" if side == "home" else "against_home"
    return "neutral"


def build_trace(ctx):
    """
    Ask every question of one live fixture and return the ordered trace.

    ctx carries the raw feeds. This function only READS and FORMATS — it never
    computes a probability, so it cannot smuggle an invented number into the
    output.
    """
    board = ctx["board"]
    stats = board.get("statistics") or {}
    h_stats = stats.get("home") or {}
    a_stats = stats.get("away") or {}
    danger = ctx["danger"]
    odds = ctx["odds"]

    home_name = danger.get("home_name") or "Home"
    away_name = danger.get("away_name") or "Away"
    minute = board.get("minute") or 0
    trace = []

    # ── 1. KEEPER LIABILITY ────────────────────────────────────────────────
    for side, team in (("home", danger.get("home_team") or {}),
                       ("away", danger.get("away_team") or {})):
        label = home_name if side == "home" else away_name
        verdict = team.get("gk_verdict")
        available = bool(verdict) and team.get("gk_leak_available") is not False
        if available:
            answer = (f"{label}: {verdict}, leak {team.get('gk_leak')}, "
                      f"vulnerability {team.get('vulnerability_pct')}%")
        else:
            answer = f"{label}: no pre-match goalkeeper assessment published"
        direction = "neutral"
        if verdict == "DANGER":
            direction = "for_away" if side == "home" else "for_home"
        trace.append(_q(f"keeper_liability_{side}",
                        f"Is {label}'s goalkeeper a liability?",
                        f"danger_audit.{side}_team.gk_verdict / gk_leak",
                        answer, direction, available))

    # ── 2. WHAT THE DEFENCE HAS ALREADY FACED ──────────────────────────────
    for side, block, opp in (("home", h_stats, a_stats),
                             ("away", a_stats, h_stats)):
        label = home_name if side == "home" else away_name
        sot = opp.get("shots-on-target")
        available = sot is not None
        answer = (f"{label} has faced {sot} shots on target and conceded "
                  f"{opp.get('corners')} corners" if available
                  else f"{label}: no live shot statistics published yet")
        trace.append(_q(f"conceded_{side}",
                        f"What has {label}'s defence already conceded?",
                        f"orchestrator_board.statistics.{side}",
                        answer, "neutral", available))

    # ── 3. IS ONE SIDE PRESSURING? ────────────────────────────────────────
    h_press, a_press = board.get("h_pressure"), board.get("a_pressure")
    total = (h_press or 0) + (a_press or 0)
    h_share = (100.0 * h_press / total) if total else None
    available = h_share is not None
    if available:
        answer = (f"{home_name} {h_press:.0f} vs {away_name} {a_press:.0f} "
                  f"— {h_share:.0f}% of pressure")
    else:
        answer = "no pressure split published for this match"
    trace.append(_q(
        "pressure_share", "Which side is controlling the match?",
        "orchestrator_board.h_pressure / a_pressure", answer,
        ("for_home" if available and h_share > 55
         else "for_away" if available and h_share < 45 else "neutral"),
        available))

    # ── 4. IS THE ATTACK CREATING QUALITY? ─────────────────────────────────
    for side, block, xg in (("home", h_stats, board.get("h_xg")),
                            ("away", a_stats, board.get("a_xg"))):
        label = home_name if side == "home" else away_name
        da, sot = block.get("dangerous-attacks"), block.get("shots-on-target")
        ok = da is not None or xg is not None
        answer = (f"{label}: {da} dangerous attacks, {sot} on target, xG {xg}"
                  if ok else f"{label}: no attacking statistics published yet")
        trace.append(_q(f"chance_creation_{side}",
                        f"Is {label} creating chances?",
                        f"orchestrator_board.statistics.{side} / {'h' if side == 'home' else 'a'}_xg",
                        answer, "neutral", ok))

    # ── 5. WHO IS MISSING, AND DOES IT MATTER? ─────────────────────────────
    for side, team in (("home", danger.get("home_team") or {}),
                       ("away", danger.get("away_team") or {})):
        label = home_name if side == "home" else away_name
        missing = team.get("missing_details") or []
        ok = team.get("data_available") is not False and bool(missing)
        if ok:
            top = sorted(missing, key=lambda m: m.get("worth") or 0,
                         reverse=True)[:3]
            answer = (f"{label} missing {len(missing)}: "
                      + ", ".join(m.get("name", "?") for m in top)
                      + f" (net impact {team.get('net_impact')})")
        else:
            answer = f"{label}: no verified absence data for this fixture"
        trace.append(_q(f"absences_{side}",
                        f"Which key players is {label} missing?",
                        f"danger_audit.{side}_team.missing_details / net_impact",
                        answer, _absence_direction(side, team), ok))

    # ── 6. WHAT DOES THE MARKET THINK? ─────────────────────────────────────
    o25 = odds.get("over25")
    priced = bool(o25 and float(o25) > 1.0)
    trace.append(_q(
        "market_over25", "What has the market priced for goals?",
        "prematch_team_audit.odds_o25",
        f"Over 2.5 priced at {o25}" if priced
        else "no usable over-2.5 price published", "neutral", priced))

    # ── 7. HOW MUCH TIME IS LEFT — the decisive one ────────────────────────
    ok = minute > 0
    trace.append(_q(
        "time_remaining", "How much of the match is left to play?",
        "orchestrator_board.minute",
        (f"{minute}' played — about {max(0, 90 - minute)} minutes of "
         f"regulation time left" if ok
         else "match has not started or minute unavailable"),
        "neutral", ok))

    return trace
