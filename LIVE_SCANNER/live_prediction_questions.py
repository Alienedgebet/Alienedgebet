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

VOCABULARY (single home-centred set — no side-specific variants):
    "for_home"     — helps the HOME side (home strengthened / away weakened)
    "for_away"     — helps the AWAY side (home weakened / away strengthened)
    "against_home" — hurts the HOME side (away strengthened); net AGAINST home
    "neutral"      — no directional read

Absence rows use the same set: a HOME absence row saying "for_home" means
home's absences helped home; an AWAY absence row saying "for_home" means the
away side's absences helped home. Consumers add for_home to the home tally,
for_away to the away tally, and treat against_home as negative-home —
never counting one direction on both sides.
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

    # ─────────────────────────────────────────────────────────────────────────
    # DNA INTELLIGENCE QUESTIONS (Questions 6-9)
    # ─────────────────────────────────────────────────────────────────────────
    # These questions query the DNA engine's team profiles and the fixture style
    # clash. Stage 8 was previously blind to this data, using only keeper
    # liability and absence count from the danger audit. DNA feeds into:
    #   - _team_timing_factor(): HT scoring rates adjust goal-timing knots
    #   - _structural_shift(): pillar edges add up to 0.05 to the goal split
    # ─────────────────────────────────────────────────────────────────────────
    dna = ctx.get("dna") or {}
    clash = dna.get("clash") or {}

    # ── 6. DNA ARCHETYPE ────────────────────────────────────────────────────
    for side in ("home", "away"):
        team = dna.get(side) or {}
        label = home_name if side == "home" else away_name
        ok = bool(team.get("available") and team.get("archetype"))
        arch = team.get("archetype")
        pillars = team.get("pillars") or {}
        if ok:
            answer = (f"{label}: archetype '{arch}' "
                      f"(Box {pillars.get('Box_Dominance')}, "
                      f"Intent {pillars.get('Goal_Intent')}, "
                      f"Friction {pillars.get('BTTS_Friction')})")
        else:
            answer = f"{label}: no DNA archetype available"
        trace.append(_q(f"dna_archetype_{side}",
                        f"What is {label}'s tactical archetype?",
                        f"dna.{side}.archetype / pillars",
                        answer, "neutral", ok))

    # ── 7. HALFTIME SCORING HABIT ──────────────────────────────────────────
    # DNA Goal_Volume carries each team's historical fraction of goals scored
    # and conceded in the first half. A team that scores 38% of its goals
    # before HT (vs league ~29%) tends to open scoring — the timing knots in
    # the engine are adjusted to reflect this per-match.
    for side in ("home", "away"):
        team = (dna.get(side) or {})
        gv = team.get("goal_volume") or {}
        label = home_name if side == "home" else away_name
        sc = gv.get("scored_at_ht_rate")
        cc = gv.get("conceded_at_ht_rate")
        cov = gv.get("ht_coverage") or 0
        ok = sc is not None and cc is not None and cov >= 0.7
        if ok:
            answer = (f"{label}: scores {sc:.0%} of goals before HT, "
                      f"concedes {cc:.0%} before HT (coverage {cov:.0%})")
        else:
            answer = (f"{label}: HT scoring rate unknown or "
                      f"insufficient coverage")
        trace.append(_q(f"ht_scoring_habit_{side}",
                        f"Does {label} score or concede in the first half?",
                        f"dna.{side}.goal_volume.scored_at_ht_rate / "
                        f"conceded_at_ht_rate",
                        answer, "neutral", ok))

    # ── 8. STYLE CLASH EDGE ─────────────────────────────────────────────────
    # The fixture style clash decomposes the matchup into 5 pillars and
    # declares a winner per pillar. Box_Dominance and Goal_Intent are the
    # strongest predictors of which side outscores the other, so they feed
    # directly into the structural share shift (up to ±0.05).
    if clash and clash.get("available"):
        edges = clash.get("edges") or {}
        overall = clash.get("overall_edge") or "Unknown"
        home_edges = clash.get("home_pillar_edges", 0)
        away_edges = clash.get("away_pillar_edges", 0)
        sig = clash.get("market_signals") or {}
        o25_sig = sig.get("Over_Under", "Unknown")
        gg_sig = sig.get("GG_NoGG", "Unknown")
        answer = (f"Overall edge: {overall} — home leads {home_edges} "
                  f"pillars, away leads {away_edges}. "
                  f"Market read: {o25_sig} / {gg_sig}")
        trace.append(_q("style_clash_edge",
                        "Which team holds the structural matchup edge?",
                        "dna.clash.edges (fixture_style_clashes_v2)",
                        answer, "neutral", True))
    else:
        trace.append(_q("style_clash_edge",
                        "Which team holds the structural matchup edge?",
                        "dna.clash (fixture_style_clashes_v2)",
                        "no style clash data available for this fixture",
                        "neutral", False))

    # ── 9. DNA PILLAR EDGE ──────────────────────────────────────────────────
    # The quantitative pillar differential that _structural_shift reads to
    # compute the ±0.05 DNA contribution to the goal split.
    if clash and clash.get("available"):
        edges = clash.get("edges") or {}
        bd = edges.get("Box_Dominance") or {}
        gi = edges.get("Goal_Intent") or {}
        bf = edges.get("BTTS_Friction") or {}
        h_bd = bd.get("home")
        a_bd = bd.get("away")
        h_gi = gi.get("home")
        a_gi = gi.get("away")
        h_bf = bf.get("home")
        a_bf = bf.get("away")
        parts = []
        if h_bd is not None and a_bd is not None:
            parts.append(f"Box_Dom {h_bd:.0f}-{a_bd:.0f}")
        if h_gi is not None and a_gi is not None:
            parts.append(f"Intent {h_gi:.0f}-{a_gi:.0f}")
        if h_bf is not None and a_bf is not None:
            parts.append(f"Friction {h_bf:.0f}-{a_bf:.0f}")
        answer = ", ".join(parts) if parts else "no pillar data"
        home_total = ((h_bd or 0) + (h_gi or 0)) / 2.0
        away_total = ((a_bd or 0) + (a_gi or 0)) / 2.0
        if home_total > away_total + 2:
            direction = "for_home"
        elif away_total > home_total + 2:
            direction = "for_away"
        else:
            direction = "neutral"
        trace.append(_q("dna_pillar_edge",
                        "What do the pillar score differentials say about "
                        "the goal split?",
                        "dna.clash.edges (fixture_style_clashes_v2)",
                        answer, direction, bool(parts)))
    else:
        trace.append(_q("dna_pillar_edge",
                        "What do the pillar score differentials say about "
                        "the goal split?",
                        "dna.clash.edges (fixture_style_clashes_v2)",
                        "no style clash data available", "neutral", False))

    # ── 10. WHAT DOES THE MARKET THINK? ─────────────────────────────────────
    o25 = odds.get("over25")
    priced = bool(o25 and float(o25) > 1.0)
    trace.append(_q(
        "market_over25", "What has the market priced for goals?",
        "prematch_team_audit.odds_o25",
        f"Over 2.5 priced at {o25}" if priced
        else "no usable over-2.5 price published", "neutral", priced))

    # ── 11. HOW MUCH TIME IS LEFT — the decisive one ────────────────────────
    # Minute parsing mirrors the engine (never raises): "45+2" -> 47.
    raw_min = board.get("minute")
    if isinstance(raw_min, str) and "+" in raw_min:
        try:
            _mp = raw_min.split("+")
            minute = max(0, int(_mp[0].strip() or 0)
                         + max(0, int(_mp[1].strip() or 0)))
        except (TypeError, ValueError):
            minute = 0
    elif isinstance(raw_min, (int, float)):
        try:
            minute = max(0, int(raw_min))
        except (TypeError, ValueError):
            minute = 0
    else:
        try:
            minute = max(0, int(float(str(raw_min or "0").strip() or "0")))
        except (TypeError, ValueError):
            minute = 0
    ok = minute > 0
    if ok and minute < 90:
        left_txt = (f"{minute}' played — about {90 - minute} regulation "
                    f"minutes plus stoppage left")
    elif ok and minute < 95:
        left_txt = f"{minute}' played — deep in stoppage time"
    elif ok and minute < 120:
        left_txt = f"{minute}' played — in extra time"
    elif ok:
        left_txt = f"{minute}' played — the clock is past extra time"
    else:
        left_txt = "match has not started or minute unavailable"
    trace.append(_q(
        "time_remaining", "How much of the match is left to play?",
        "orchestrator_board.minute",
        left_txt, "neutral", ok))

    return trace
