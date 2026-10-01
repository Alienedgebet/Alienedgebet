"""
Five independent judges.

THE POINT OF INDEPENDENCE
-------------------------
A judge that reuses the engine's arithmetic agrees with it by construction and
therefore proves nothing — it is the same trap as counting Code 4's BLESSING
verdict and its goalkeeper call as two independent sources, which manufactures
confidence that was never earned. That mistake has now bitten this codebase
three separate times.

So each judge here either RECOMPUTES the quantity by a different route, or
CHECKS an invariant the engine never checks. Judge 1 in particular re-derives
the goal total from the price with its own bisection and its own Poisson, and
never calls into the engine's functions.

A judge that cannot run never becomes a PASS. It downgrades to WARN with the
reason attached, because a judge that silently skips is how a broken engine
looks healthy.
"""
import math

VERDICT_PASS = "PASS"
VERDICT_WARN = "WARN"
VERDICT_BLOCK = "BLOCK"


def _verdict(name, verdict, reason, detail=None):
    return {"judge": name, "verdict": verdict, "reason": reason,
            "detail": detail or {}}


# ── JUDGE 1 — MARKET ───────────────────────────────────────────────────────
def judge_market(ctx, prediction):
    """
    Re-derive the goal expectation from the price with INDEPENDENT maths and
    check the engine sits within a sane band of it.

    Deliberately does not import implied_total_goals or poisson_between. Same
    question, separate implementation — otherwise it is a copy that can only
    ever agree.
    """
    odds = ctx.get("odds") or {}
    model = prediction.get("_anchor") or {}
    if model.get("anchor_source") == "live_observation":
        # There is no bookmaker price to check against. That is a real limit on
        # how much the number can be trusted, so it is WARN — never PASS, and
        # never silently treated as if a market had endorsed it.
        return _verdict("market", VERDICT_WARN,
                        "anchored on the match's own chance creation, not a "
                        "bookmaker price — no independent market check possible",
                        {"implied_total_goals": model.get("anchor_total_goals")})

    price = odds.get("over25")
    try:
        price = float(price)
    except (TypeError, ValueError):
        return _verdict("market", VERDICT_BLOCK,
                        "no usable over-2.5 price to check against")
    if price <= 1.0:
        return _verdict("market", VERDICT_BLOCK, f"unusable price {price}")

    # Independent inversion of the same question the engine answers.
    #
    # f(lambda) = P(0-2 goals) DECREASES as lambda rises, and we want
    # f(lambda) == target. So:
    #     f(mid) > target  ->  lambda is too SMALL -> the answer is ABOVE mid
    #     f(mid) <= target ->  lambda is too LARGE -> the answer is BELOW mid
    #
    # This was written backwards twice before it was right, and each wrong way
    # failed the same way: the bracket walks to its edge and returns 20
    # expected goals with no error raised. That is the sixth member of this
    # family in this codebase, and the two that appeared here were both written
    # deliberately as "independent" re-implementations. Being independent is
    # exactly what makes a fresh pair of eyes useless on the maths — which is
    # why the tests compare the two against each other instead of trusting
    # either one.
    target = 1.0 - 1.0 / price          # P(X <= 2) implied by the price
    lo, hi = 0.01, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        p_upto2 = math.exp(-mid) * (1.0 + mid + (mid ** 2) / 2.0)
        if p_upto2 > target:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    if lam < 0.3 or lam > 7.0:
        return _verdict("market", VERDICT_BLOCK,
                        f"price implies {lam:.2f} goals, which is not a "
                        f"football market", {"implied_total_goals": lam})

    total = prediction.get("home_win", 0) + prediction.get("draw", 0) \
        + prediction.get("away_win", 0)
    if abs(total - 100.0) > 0.5:
        return _verdict("market", VERDICT_BLOCK,
                        f"win/draw/away sum to {total:.1f}, not 100")

    model = prediction.get("_anchor") or {}
    engine_lam = model.get("anchor_total_goals")
    if engine_lam is None:
        return _verdict("market", VERDICT_WARN,
                        "engine did not disclose its anchor", {})
    if abs(engine_lam - lam) > 0.05:
        return _verdict("market", VERDICT_BLOCK,
                        f"engine anchored on {engine_lam:.2f} goals but the "
                        f"price implies {lam:.2f} — the anchor is wrong",
                        {"engine": engine_lam, "market": lam})
    return _verdict("market", VERDICT_PASS,
                    f"anchor agrees with the price ({lam:.2f} goals)",
                    {"implied_total_goals": round(lam, 3)})



# ── JUDGE 2 — LIVE STATE ───────────────────────────────────────────────────
def judge_live_state(ctx, prediction):
    """
    Check the prediction is merely POSSIBLE.

    These are invariants the engine never asserts about itself. It will happily
    report a 70% chance of a side scoring at 88 minutes when that side has had
    no shots, because nothing in the model knows that is strange. This judge
    does.
    """
    board = ctx.get("board") or {}
    stats = board.get("statistics") or {}
    minute = int(board.get("minute") or 0)
    score = ctx.get("score") or {}
    problems = []

    total = (prediction.get("home_win", 0) + prediction.get("draw", 0)
             + prediction.get("away_win", 0))
    if abs(total - 100.0) > 0.6:
        problems.append(f"win/draw/away sum to {total:.1f}")

    for key in ("home_win", "draw", "away_win", "over_2_5", "under_3_5",
                "exactly_3_goals"):
        value = prediction.get(key)
        if value is None or not (0.0 <= float(value) <= 100.0):
            problems.append(f"{key} is {value}, outside 0-100")

    # The three goal lines overlap exactly at "3 goals". If they do not, one of
    # them is arithmetically wrong.
    o25 = float(prediction.get("over_2_5") or 0)
    u35 = float(prediction.get("under_3_5") or 0)
    ex3 = float(prediction.get("exactly_3_goals") or 0)
    if abs((o25 + u35 - ex3) - 100.0) > 1.5:
        problems.append(
            f"goal lines do not reconcile: {o25} + {u35} - {ex3} = "
            f"{o25 + u35 - ex3:.1f}, expected 100")

    # A match with no time left produces three goal lines that are all 100% —
    # arithmetically consistent, and useless to read. Refusing it is better
    # than showing the user "over 2.5: 100%, under 3.5: 100%, exactly 3: 100%"
    # and letting them wonder whether the engine has broken.
    if o25 >= 99.5 and u35 >= 99.5:
        problems.append(
            "every goal line reads 100% — the match is over, so these are not "
            "predictions and must not be presented as such")

    if minute >= 80:
        for side, key in (("home", "home_to_score"),
                          ("away", "away_to_score")):
            block = stats.get(side) or {}
            block = block if isinstance(block, dict) else {}
            shot = float(block.get("shots-on-target") or 0)
            already = (score.get(side) or 0) > 0
            pct = float((prediction.get(key) or {}).get("pct") or 0)
            if not already and shot <= 1 and pct > 55:
                problems.append(
                    f"{side} to score {pct:.0f}% at {minute}' with {shot} "
                    f"shots on target and no goal is not credible")

    if problems:
        return _verdict("live_state", VERDICT_BLOCK,
                        "; ".join(problems), {"minute": minute})
    return _verdict("live_state", VERDICT_PASS,
                    f"internally consistent and plausible at {minute}'",
                    {"minute": minute})


# ── JUDGE 3 — TRACE ────────────────────────────────────────────────────────
def judge_trace(ctx, prediction, trace):
    """
    Walk the trace and confirm every answer names a real source.

    This is the judge that catches fabrication. Four separate bugs in this
    codebase returned a value that could never match — a literal "favours"
    instead of a team, a string/int id, a dict read as a list, an inverted
    bisection boundary — and every one of them looked like a legitimate zero.
    A trace that cannot point at its source field is how that happens again.
    """
    if not trace:
        return _verdict("trace", VERDICT_BLOCK, "no trace was produced")

    unsourced = []
    for q in trace:
        if not str(q.get("source") or "").strip():
            unsourced.append(q.get("id"))
        if q.get("available") and not str(q.get("answer") or "").strip():
            unsourced.append(q.get("id"))

    if unsourced:
        return _verdict("trace", VERDICT_BLOCK,
                        f"{len(unsourced)} answers with no usable source",
                        {"unsourced": unsourced})

    available = [q for q in trace if q.get("available")]
    if len(available) < 4:
        return _verdict("trace", VERDICT_WARN,
                        f"only {len(available)} of {len(trace)} questions "
                        f"could be answered", {})
    return _verdict("trace", VERDICT_PASS,
                    f"all {len(available)} answers name a source field",
                    {"questions": len(trace), "answered": len(available)})


# ── JUDGE 4 — CONVERGENCE ──────────────────────────────────────────────────
def judge_convergence(ctx, prediction, trace):
    """
    Do the pre-match cluster and the live cluster point the same way?

    Two disjoint sources by construction: one is read from the pre-match audit,
    the other from the live board. Neither is derived from the other, so
    agreement here is genuine information rather than an echo.
    """
    prematch_votes = [q["direction"] for q in trace
                      if q["id"].startswith("absences_")
                      or q["id"].startswith("keeper_liability_")]
    live_votes = [q["direction"] for q in trace
                  if q["id"] in ("pressure_share", "chance_creation_home",
                                 "chance_creation_away")]
    pre_home = prematch_votes.count("for_home") + prematch_votes.count(
        "against_home")
    pre_away = prematch_votes.count("for_away") + prematch_votes.count(
        "against_home")
    live_home = live_votes.count("for_home")
    live_away = live_votes.count("for_away")

    if pre_home == pre_away:
        return _verdict("convergence", VERDICT_WARN,
                        "pre-match intelligence is balanced — it neither "
                        "supports nor opposes either side here", {})
    live_home = live_home - live_away
    agree = (pre_home > pre_away and live_home > 0) or \
            (pre_away > pre_home and live_home < 0)
    if agree:
        return _verdict("convergence", VERDICT_PASS,
                        "pre-match structure and live play point the same way",
                        {"prematch": pre_home - pre_away, "live": live_home})
    if live_home == 0:
        return _verdict("convergence", VERDICT_WARN,
                        "live play is level, so it neither confirms nor "
                        "contradicts the pre-match read", {})
    return _verdict("convergence", VERDICT_WARN,
                    "pre-match structure and live play disagree — showing "
                    "both rather than picking one", {})


# ── JUDGE 5 — BASE RATE / DEGENERACY ──────────────────────────────────────
def judge_base_rate(ctx, prediction, history=None):
    """
    Catch a model that has stopped responding to the match.

    A rule that emits the same number regardless of the input is worthless no
    matter how confident it sounds. This judge compares the current output with
    recently seen outputs for the same fixture: if the minute has advanced and
    the score is unchanged, a to-score probability must FALL, because time ran
    out. If it did not, the model is not actually reading the clock.
    """
    history = history or []
    minute = int((ctx.get("board") or {}).get("minute") or 0)
    current = {k: (prediction.get(k) or {}).get("pct")
               for k in ("home_to_score", "away_to_score")}

    problems = []
    if minute >= 88:
        for side in ("home_to_score", "away_to_score"):
            if float(current.get(side) or 0) > 25:
                problems.append(
                    f"{side} still {current[side]}% with the match over")

    for prior in history[-5:]:
        if prior.get("fixture_id") != ctx.get("fixture_id"):
            continue
        if float(prior.get("minute") or 0) >= minute:
            continue
        if prior.get("score") != (ctx.get("score")):
            continue  # the score moved, so a change is expected
        for side in ("home_to_score", "away_to_score"):
            before = float((prior.get(side) or 0))
            now = float(current.get(side) or 0)
            if now > before + 5:
                problems.append(
                    f"{side} rose from {before:.0f}% to {now:.0f}% with the "
                    f"score unchanged and time running out")
    if problems:
        return _verdict("base_rate", VERDICT_BLOCK, "; ".join(problems), {})
    return _verdict("base_rate", VERDICT_PASS,
                    "probabilities move with the clock as they should",
                    {"minute": minute})


# ── THE PANEL ──────────────────────────────────────────────────────────────
def run_judges(ctx, prediction, trace, history=None):
    """
    Run every judge and reach one verdict.

    Worst verdict wins. A judge that raises is recorded as WARN with its error,
    never silently dropped — a panel that loses a judge without saying so is
    how a broken engine reports itself healthy.
    """
    checks = (
        ("market", judge_market, (ctx, prediction)),
        ("live_state", judge_live_state, (ctx, prediction)),
        ("trace", judge_trace, (ctx, prediction, trace)),
        ("convergence", judge_convergence, (ctx, prediction, trace)),
        ("base_rate", judge_base_rate, (ctx, prediction, history)),
    )
    results = []
    for name, fn, args in checks:
        try:
            results.append(fn(*args))
        except Exception as exc:
            results.append(_verdict(name, VERDICT_WARN,
                                    f"judge could not run: {exc}", {}))

    verdicts = [r["verdict"] for r in results]
    overall = VERDICT_BLOCK if VERDICT_BLOCK in verdicts else (
        VERDICT_WARN if VERDICT_WARN in verdicts else VERDICT_PASS)
    return {"verdict": overall, "judges": results,
            "blocked_by": [r["judge"] for r in results
                           if r["verdict"] == VERDICT_BLOCK]}
