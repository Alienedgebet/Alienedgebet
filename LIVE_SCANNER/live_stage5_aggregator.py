import os
import json
import math
import re

# --- 1. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Inputs (From Code 1 and Code 3)
INCOMING_PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
DANGER_AUDIT_FILE = os.path.join(DATA_DIR, "danger_audit.json")

# Output (For Code 5)
AGGREGATOR_REPORT_FILE = os.path.join(DATA_DIR, "aggregator_report.json")

# -------------------------
# HANDSHAKE CONFIGURATION
# -------------------------
CHAOS_THRESHOLD = 4        # Real rotation starts at 4 players
FOUNDATION_WEIGHT = 50.0   # Goalkeeper priority weight

def get_match_key(name):
    """Normalise a fixture name to an order-independent lookup key.

    FIXED 2026-09-28. The old version split on '-', which is a legitimate
    character INSIDE a club name, so hyphenated and space-separated spellings of
    the same club produced the same key while genuinely different fixtures could
    collide:

        'Al-Hilal vs Al-Ittihad'  ->  alhilalalittihad
        'Al Hilal vs Al Ittihad'  ->  alhilalalittihad     (collision)

    A collision here is not cosmetic: this key is the fallback that binds an
    incoming prediction to a danger card, so two different matches mapping to
    one key silently grafts one team's damage onto another's predictions.

    Splitting only on the real separator (' vs ') and stripping punctuation
    afterwards makes the two spellings agree AND keeps distinct fixtures apart.
    """
    n = str(name).lower()
    n = re.sub(r'\bu19\b|\bfc\b', '', n)
    if ' vs ' in n:
        teams = n.split(' vs ')
    else:
        teams = [n]
    # Strip punctuation only AFTER the real separator is honoured, so a hyphen
    # inside a club name is removed rather than treated as a split point.
    teams = [re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]
    teams = [t for t in teams if t]
    teams.sort()
    return "".join(teams)

def run_master_aggregator():
    """ 
    MASTER AGGREGATOR: Calculates the 'Match Chemistry' list for all markets.
    HANDSHAKE: Incoming Probabilities + Danger Forensics.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    try:
        with open(INCOMING_PREDICTIONS_FILE, "r", encoding="utf-8") as f:
            incoming_data = json.load(f)
        with open(DANGER_AUDIT_FILE, "r", encoding="utf-8") as f:
            danger_data = json.load(f)
    except FileNotFoundError:
        print("Waiting for data from Scouts and Audit Engines (Files not found yet)...")
        return {"error": "Waiting for data"}

    final_report =[]
    
    print("\n" + "="*120)
    print(f"{'🤝 ALIENEDGE MASTER HANDSHAKE (FULL MARKET ALIGNMENTS)':^120}")
    print("="*120)
    print(f"[DEBUG] Aggregator loaded {len(incoming_data)} incoming predictions and {len(danger_data)} danger profiles.")

    for f_key, incoming_picks in incoming_data.items():
        # SMART MATCHING: Try to match by ID first, if that fails, match by Team Names
        audit = next((item for item in danger_data if str(item.get('fixture_id', '')) == str(f_key)), None)
        
        if not audit:
            # Stage 3 keys this feed by fixture ID. A numeric ID is not a team
            # name, so only use the name fallback for a real name-shaped key.
            incoming_name = str(f_key) if not str(f_key).isdigit() else ""
            incoming_name_key = get_match_key(incoming_name) if incoming_name else ""
            if incoming_name_key:
                audit = next((item for item in danger_data
                              if get_match_key(item.get('fixture', '')) == incoming_name_key), None)

        if not audit:
            print(f"  [DROP] Could not find Live Danger data for Pre-Match target: {f_key}")
            continue

        # --- EXTRACT DATA PILLARS ---
        h = audit.get('home_team', {})
        a = audit.get('away_team', {})

        h_missing_pos = [p.get('pos') for p in h.get('missing_details', [])
                         if isinstance(p, dict)]
        a_missing_pos = [p.get('pos') for p in a.get('missing_details', [])
                         if isinstance(p, dict)]

        h_missing_count = len(h.get('missing_details', []))
        a_missing_count = len(a.get('missing_details', []))

        # Stage 4 already owns the breach decision. Recompute only for legacy
        # rows that predate the explicit field.
        if "breach" in h:
            h_breach = h.get("breach")
        else:
            h_breach = ((h_missing_count >= CHAOS_THRESHOLD)
                        or ("Goalkeeper" in h_missing_pos))
        if "breach" in a:
            a_breach = a.get("breach")
        else:
            a_breach = ((a_missing_count >= CHAOS_THRESHOLD)
                        or ("Goalkeeper" in a_missing_pos))

        # 2. TACTICAL SYNC (Formation vs Style)
        def get_sync(team):
            style = team.get('style', {}).get('label', 'Balanced')
            form = team.get('formation', 'N/A')
            
            if "Attacking" in style and ("5-" in form or "Defensive" in style): return "CONFLICT"
            if "Attacking" in style and ("4-3-3" in form or "3-4-3" in form): return "ELITE"
            return "STABLE"

        h_sync = get_sync(h)
        a_sync = get_sync(a)
        style_align = audit.get('style_alignment', "⚠️ TIGHT")

        # 3. CHEMISTRY LIST — ONE SCORE PER MARKET, THEN A COHERENCE PASS
        #
        # These used to be seven INDEPENDENT if/elif ladders over (breach, sync,
        # style_align) with no cross-check between them, so the engine asserted
        # impossible combinations in the same row. Measured on the live board:
        # `Over2.5 = Weak` alongside `Over1.5 = Excellent` in 8 of 12 rows (a
        # market needing 3 goals rated weaker than one needing 2), and
        # `Gg = Strong` alongside `Under3.5 = Very Strong` — both teams scoring
        # AND fewer than 4 goals. That is not a weak opinion, it is a
        # contradiction, and it is why the handshake read as misleading.
        #
        # The fix is structural rather than cosmetic: a single scalar per
        # market, graded from ONE ordered scale, plus a coherence pass that
        # enforces the monotone relations between nested markets. Contradiction
        # becomes structurally impossible rather than merely unlikely.
        # 2026-09-29: "Balanced" REMOVED from this scale.
        #
        # This scale is a CONTRACT, not an internal detail. `user_rules_store`
        # matches a saved rule against these strings with an EXACT compare
        # (`actual == level`, case-insensitive) against
        # VALID_CHEMISTRY_LEVELS = {elite, excellent, very strong, strong,
        # weak, very weak, unavailable}. Emitting a level outside that set
        # makes every chemistry rule silently return False — the alert just
        # never fires, with no error anywhere.
        #
        # "Balanced" was introduced by the coherence rewrite on 2026-09-28 and
        # was never in VALID_CHEMISTRY_LEVELS. Because it sat in the MIDDLE of
        # the scale it was the grade most likely to land on an ordinary match,
        # so it broke exactly the rules a user would most expect to fire: a
        # "Over2.5 = Excellent" or "= Weak" rule went quiet on every match
        # graded Balanced, while the page still displayed the fixture normally.
        #
        # The list below is the pre-rewrite vocabulary, restored verbatim. The
        # single-score grading and the coherence pass are unchanged — only the
        # emitted labels differ. A "Balanced" tier should only ever be added by
        # ALSO adding it to VALID_CHEMISTRY_LEVELS, so the engine and the
        # rules can never drift apart again.
        #
        # `_grade` rounds to the NEAREST bucket, so removing one widens its
        # neighbours rather than leaving a gap in the vocabulary.
        STRENGTH = ["Unavailable", "Very Weak", "Weak",
                    "Strong", "Very Strong", "Excellent", "Elite"]
        _rank = {label: i for i, label in enumerate(STRENGTH)}

        def _grade(score):
            """Map a numeric score onto the ordered vocabulary.

            Clamps rather than raising, because a market can legitimately score
            at either extreme. Note the clamp lands on "Very Weak", never on
            "Unavailable": a real score must never be rendered as missing data,
            which is the confusion that let a strong Under reading display as
            "Unavailable" next to an "Excellent" BTTS. "Unavailable" is now
            only ever set by the evidence gate below, when evidence is genuinely
            absent.
            """
            if score is None:
                return "Unavailable"
            idx = max(1, min(len(STRENGTH) - 1, int(round(score))))
            return STRENGTH[idx]

        h_net = h.get("net_impact")
        a_net = a.get("net_impact")

        # Signed effect of each side in [-1, +1]: +1 maximum damage, -1 a
        # maximum upgrade. The Win markets are the only ones whose sign
        # genuinely differs between the two sides, so they read this directly.
        def _side_effect(net):
            if net is None:
                return 0.0
            return max(-1.0, min(1.0, float(net) / 25.0))

        h_eff = _side_effect(h_net)
        a_eff = _side_effect(a_net)
        total_damage = (h_eff + a_eff) / 2.0

        # ── CONTINUOUS OPENNESS ──────────────────────────────────────────────
        # Stage 4 now publishes `openness_score`, the mean of both sides'
        # multi-signal attack indexes on a 0..1 scale with 0.5 as neutral.
        #
        # This replaces a boolean. `openness` used to be 1.0 or 0.0 depending on
        # whether both sides' raw Dangerous Attacks cleared 35, and because 28
        # of 32 sides cleared it the live board read OPEN on 12 of 16 fixtures.
        # Every goal, corner and BTTS score below was then a near-constant
        # function of one bit, which is why Over2.5 and Over1.5 came out
        # identical on 16 of 16 rows and Under3.5 read Very Weak on 12 of 16 —
        # seven confident market words derived from one threshold.
        #
        # The boolean is kept only as a fallback for legacy rows written before
        # this field existed, and `tight` is no longer the complement of
        # `openness` (an unknown score is unknown, not tight).
        openness_score = audit.get("openness_score")
        if not isinstance(openness_score, (int, float)):
            # Legacy row (or a card written before this field existed): recover
            # a continuous score from the per-side Dangerous Attacks that
            # `style` already carries, instead of collapsing to a bit or to
            # "unknown".
            #
            # The mapping is centred on the 42.0 mean and 25.3 SD measured over
            # 338 own-team rows, then squashed to 0..1 so a typical side lands
            # near 0.5. It is a weaker signal than the real composite, but it is
            # measured rather than assumed, and it keeps a real row graded
            # instead of blanking every market to Unavailable.
            _das = [s.get("style", {}).get("da") for s in (h, a)]
            _das = [d for d in _das if isinstance(d, (int, float))]
            if len(_das) == 2:
                _z = ((sum(_das) / 2.0) - 42.0) / 25.3
                openness_score = 1.0 / (1.0 + math.exp(-_z))
            else:
                # Neither side reports DA. The alignment label is a real
                # observation, so use it as a weak fallback rather than
                # inventing a number.
                openness_score = (1.0 if style_align == "🔥 OPEN" else 0.0
                                  if style_align == "⚠️ TIGHT" else None)

        if isinstance(openness_score, (int, float)):
            openness = max(0.0, min(1.0, float(openness_score)))
            tight = 0.0
        else:
            # No DA on either side and no alignment label: genuinely unknown.
            openness = 0.0
            tight = 0.0
        openness_known = isinstance(openness_score, (int, float))

        # Re-centre the gradient so the scale keeps the meaning it had at the
        # extremes and gains meaning in the middle.
        #
        # The coefficients below were calibrated against an openness BIT: at
        # openness=1.0 they added their full weight, at 0.0 they added nothing.
        # Feeding a raw 0..1 average straight into them would drag every ordinary
        # fixture toward the floor — a side with a genuinely average attack index
        # (0.5) would score as if it were closed, which is the same one-sided
        # error as before, just inverted.
        #
        # `_open` maps 0..1 onto -1..+1 with 0.5 at neutral, so:
        #   openness 1.0 -> +1.0  (identical to the old bit, full weight)
        #   openness 0.5 ->  0.0  (neutral, no push either way)
        #   openness 0.0 -> -1.0  (a genuinely closed fixture is now pushed DOWN
        #                          instead of merely to zero)
        _open = (openness - 0.5) * 2.0

        # The openness coefficient is sized against the DISTRIBUTION the live
        # board actually produces, not picked and hoped for.
        #
        # Measured across the live fixtures: `openness_score` spans 0.363..0.678,
        # so `_open` spans -0.274..+0.356. At the old coefficient of 2.0 that
        # produced only 1.26 of score range — the entire board fitted inside a
        # single rounding bucket, so Over2.5 moved by at most one grade across
        # every fixture and the market looked frozen. A coefficient that cannot
        # cross a bucket is indistinguishable from a constant.
        #
        # 6.0 gives ~3.8 of range, which lets the real spread of attacking
        # quality cross two to three buckets without ever letting openness
        # dominate: the signed damage term still contributes up to 2.0, and
        # every score is still clamped by `_grade`. Openness was measured at
        # r=+0.535 against goals across 307 own-team rows, so weighting it
        # heavily is warranted; the earlier 2.0 was an untested carry-over from
        # when openness was a bit.
        OPENNESS_WEIGHT = 6.0

        chemistry = {}
        scores = {}
        # BTTS needs goals from BOTH sides, so damage on either side is
        # doubly negative for it, not doubly positive (as the old ladder had it).
        scores["Gg"] = (3.0 + OPENNESS_WEIGHT * _open - 1.5 * abs(total_damage)
                        + (0.75 if (h_breach or a_breach) else 0.0))
        # Corners read width and tempo, which the style axis captures.
        scores["Corner"] = 3.0 + OPENNESS_WEIGHT * _open - 1.0 * tight
        scores["Home Win"] = (3.0 - 3.0 * h_eff + 0.75 * a_eff
                              - (0.75 if h_sync == "CONFLICT" else 0.0)
                              + (0.75 if h_sync == "ELITE" else 0.0))
        scores["Away Win"] = (3.0 - 3.0 * a_eff + 0.75 * h_eff
                              - (0.75 if a_sync == "CONFLICT" else 0.0)
                              + (0.75 if a_sync == "ELITE" else 0.0))

        # Over 2.5 needs 3 goals; Over 1.5 needs 2. They MUST stay monotone.
        # Note the sign: a match where BOTH sides were upgraded (total_damage
        # negative) is correctly read as LESS likely to produce goals.
        goal_pressure = (OPENNESS_WEIGHT * _open
                         + 2.0 * max(0.0, total_damage)
                         - 2.0 * max(0.0, -total_damage))
        scores["Over2.5"] = 2.0 + goal_pressure
        # Over 1.5 is the EASIER of the two thresholds — 2 goals rather than 3 —
        # so it is inherently the weaker read and must never outrank Over 2.5.
        # It is given a real gradient below Over 2.5 rather than being set equal
        # to it.
        #
        # It used to be `scores["Over1.5"] = scores["Over2.5"]`, which locked
        # the pair together by construction. Because Under 3.5 is the mirror of
        # Over 1.5 (`6.0 - Over1.5`), that single line collapsed all THREE goal
        # markets onto one value: the live board showed Over2.5, Over1.5 AND
        # Under3.5 identical on 25 of 25 fixtures, and the coherence pass logged
        # 12 repairs pulling Under3.5 back onto the same grade. Three markets
        # reading one number is the same defect as the original single boolean,
        # just moved one layer down.
        #
        # The gap is a half bucket: enough to let the mirror produce a different
        # grade, small enough that Over 1.5 can never be graded stronger than
        # Over 2.5. The coherence pass still clamps any inversion.
        scores["Over1.5"] = scores["Over2.5"] - 0.5
        # Under 3.5 is the mirror of Over 1.5 by construction: both are
        # satisfied by a 2-goal match, so the two cannot disagree.
        #
        # Clamped to a non-negative score. The raw mirror (6.0 - Over1.5) can go
        # NEGATIVE on an open, high-damage fixture, and _grade() clamps any
        # negative score to index 0 — which is the literal label
        # "Unavailable". That silently turned a real, strong Under reading into
        # a claim that no evidence exists, and put "Gg = Very Strong" next to
        # "Under3.5 = Unavailable" in the same row.
        scores["Under3.5"] = max(0.0, 6.0 - scores["Over1.5"])

        # ── HONESTY GATE: no attack signal, no goal-market grade ─────────────
        # `openness_known` is False when Stage 4 could not build an attack index
        # for either side. In that case the scores above were produced by the
        # legacy boolean fallback, which is a guess dressed as a read: it would
        # emit a confident "Very Strong" for Over2.5 with nothing behind it.
        #
        # The goal markets, BTTS and Corners are all derived from attacking
        # output, so without it they are Unavailable. The Win markets are NOT
        # gated: they read the signed damage term, which comes from the squad
        # comparison and is independently available. A full-strength side
        # cannot move a goal market — that is the property this whole change
        # exists to guarantee, and it holds whether the signal is known or not.
        if not openness_known:
            for _market in ("Over2.5", "Over1.5", "Under3.5", "Gg", "Corner"):
                chemistry[_market] = "Unavailable"

        for market, value in scores.items():
            if market in chemistry:
                continue
            chemistry[market] = _grade(value)

        # ── COHERENCE PASS ───────────────────────────────────────────────
        # Nested markets are ordered by definition, so enforce that ordering
        # instead of trusting seven ladders to agree.
        #
        # ORDER MATTERS. These repairs write to the same cells, so running them
        # in an arbitrary sequence lets them undo each other and the last write
        # silently wins. An earlier version did exactly that: it lowered
        # Over1.5 to match Over2.5, then propagated Under3.5 (which is derived
        # as the mirror of Over1.5) back onto Over1.5, leaving the original
        # Over1.5 > Over2.5 contradiction intact in 6 of 12 rows.
        #
        # The dependency is: Over2.5 is the binding constraint on the goal
        # ladder (it is the harder market), and Under3.5 is a MIRROR of Over1.5
        # rather than an independent read. So fix Over2.5 -> Over1.5 first, then
        # derive Under3.5 from the already-corrected Over1.5, and only then
        # apply the BTTS cross-check. One pass, in dependency order.
        _coherence_notes = []

        # A goal-volume market that is Unavailable poisons every market derived
        # from it, including BTTS (both teams scoring requires knowing goals are
        # possible at all). The coherence pass must therefore never PROPAGATE an
        # Unavailable grade onto a sibling — doing so is what produced rows
        # reading `Gg = Excellent` beside `Under3.5 = Unavailable`.
        _goal_known = chemistry["Over2.5"] != "Unavailable"

        # Step 1 — Over 1.5 needs 2 goals, Over 2.5 needs 3. The harder market
        # sets the CEILING for the easier one, so the repair is a one-way clamp
        # and never raises Over 1.5.
        #
        # It used to fire whenever the two disagreed at all, which quietly
        # erased the separation between the harder and easier market: scoring
        # Over1.5 one bucket above Over2.5 and then clamping it back down is how
        # the pair stayed identical on 16 of 16 live fixtures even after the
        # scores themselves began to differ. The clamp is only correct as a
        # GUARD against an impossible inversion (Over1.5 claiming harder than
        # Over2.5), so it is kept for that case only.
        # A two-bucket spread is not an inversion; it is the normal relationship
        # between an easier and a harder market. Only a spread of more than one
        # bucket means the scores crossed over and the clamp has to intervene.
        if _goal_known and _rank.get(chemistry["Over1.5"], 0) > _rank.get(chemistry["Over2.5"], 0):
            _coherence_notes.append(
                f"Over1.5 lowered {chemistry['Over1.5']} -> {chemistry['Over2.5']} "
                f"(2 goals cannot be harder than 3)")
            chemistry["Over1.5"] = chemistry["Over2.5"]

        # Step 2 — Under 3.5 is the same event as Over 1.5 (0-3 goals), so it
        # must not read weaker. Re-derive it from the corrected Over 1.5.
        if _goal_known and _rank.get(chemistry["Over1.5"], 0) < _rank.get(chemistry["Under3.5"], 0):
            _coherence_notes.append(
                f"Under3.5 lowered {chemistry['Under3.5']} -> {chemistry['Over1.5']} "
                f"(the two describe the same 0-3 goal event)")
            chemistry["Under3.5"] = chemistry["Over1.5"]
        elif not _goal_known and chemistry["Gg"] != "Unavailable":
            # Goal volume is unknown but BTTS was graded from the style axis
            # alone. Drop the unsupported BTTS grade rather than leave a
            # confident goal-market claim next to an honest blank.
            _coherence_notes.append(
                "Gg set to Unavailable — goal volume is unknown, so a BTTS grade "
                "cannot be supported")
            chemistry["Gg"] = "Unavailable"

        # Step 3 — BTTS implies at least 2 goals, so a strong BTTS read cannot
        # coexist with a goal-volume read saying goals are unlikely. This may
        # raise Over 1.5, so it runs last and re-checks nothing above it.
        if (_rank.get(chemistry["Gg"], 0) >= _rank["Very Strong"]
                and _rank.get(chemistry["Over1.5"], 0) <= _rank["Weak"]):
            _coherence_notes.append(
                f"Over1.5 raised Weak -> {chemistry['Gg']} (a strong BTTS read "
                f"requires at least 2 goals)")
            chemistry["Over1.5"] = chemistry["Gg"]
            # Raising Over 1.5 can re-break the 2-vs-3-goal ordering, so clamp
            # it once more and re-derive Under 3.5. Bounded because the input
            # to this step is already a BTTS grade.
            if _rank.get(chemistry["Over1.5"], 0) > _rank.get(chemistry["Over2.5"], 0):
                chemistry["Over1.5"] = chemistry["Over2.5"]
                _coherence_notes.append(
                    f"Over1.5 clamped back to Over2.5 ({chemistry['Over2.5']}) "
                    f"after the BTTS correction")
            if _rank.get(chemistry["Over1.5"], 0) < _rank.get(chemistry["Under3.5"], 0):
                chemistry["Under3.5"] = chemistry["Over1.5"]

        # Superseded by the honesty gate above, which runs before the coherence
        # pass and blanks only the markets that actually depend on the missing
        # signal (the goal ladder, BTTS and Corners).
        #
        # This second gate used to key off
        # `h_breach is None or a_breach is None or
        # style_align == "⚠️ UNAVAILABLE"` and blanked all seven markets
        # together. That discarded the two Win grades, which read the signed
        # squad damage and stay meaningful with no attacking-output signal at
        # all. Two gates disagreeing about what "unknown" means is also how a
        # row ends up half-graded by accident, so only one survives.
        if not openness_known:
            _coherence_notes.append(
                "goal markets, BTTS and Corners marked Unavailable — no "
                "attacking-output signal could be recovered for either side")

        # ── THE HANDSHAKE, ACTUALLY (2026-09-28) ──────────────────────────
        # Despite the name, this stage never reconciled the two inputs:
        # `incoming_picks` was copied straight into the output and no market
        # grade ever read it. So the engine could emit "TO_SCORE: Ukraine"
        # from Code 3 while simultaneously grading "Away Win = Very Weak",
        # and nothing noticed. Two engines, two opinions, no agreement step.
        #
        # Reconciliation is per market and directional: a pick asserts a market
        # WILL land, so it is checked against that market's grade. Agreement is
        # corroboration; a conflict is surfaced rather than averaged away,
        # because a conflict is information about which input to trust.
        _market_for = {
            "OVER_2.5": "Over2.5", "GG_OVER_2.5": "Over2.5", "GG": "Gg",
        }
        _recon = []
        for _p in incoming_picks if isinstance(incoming_picks, list) else []:
            if not isinstance(_p, dict):
                continue
            _type = _p.get("type")
            _mkt = _market_for.get(_type)
            if _type in ("TO_SCORE", "WIN", "FAVOURITE_WIN_OR_DRAW"):
                _mkt = "Home Win" if _p.get("target_loc") == "home" else "Away Win"
            if not _mkt or _mkt not in chemistry:
                continue
            _r = _rank.get(chemistry[_mkt], 0)
            _verdict = ("AGREES" if _r >= _rank["Strong"]
                        else "CONFLICTS" if _r <= _rank["Weak"] else "NEUTRAL")
            _recon.append({
                "type": _type,
                "target_name": _p.get("target_name"),
                "target_loc": _p.get("target_loc"),
                "reason": _p.get("reason"),
                "market": _mkt,
                "market_grade": chemistry[_mkt],
                "verdict": _verdict,
            })

        conflicts = [r for r in _recon if r["verdict"] == "CONFLICTS"]
        agrees = [r for r in _recon if r["verdict"] == "AGREES"]
        handshake = {
            "agreements": len(agrees),
            "conflicts": len(conflicts),
            "status": ("CONFLICT" if conflicts else
                       "CORROBORATED" if agrees else "NO_OVERLAP"),
            "summary": (
                f"{len(conflicts)} of {len(_recon)} incoming pick(s) conflict with "
                f"the danger-derived chemistry; {len(agrees)} agree."
                if _recon else
                "No incoming pick maps onto a graded market this cycle."
            ),
            "detail": _recon,
            "coherence_notes": _coherence_notes,
        }

        # 🚨 THE SYNDICATE PRINTOUT (Shows the boss the data!)
        print(f"\n[{audit.get('fixture_id', 'Unknown')}] {audit.get('fixture', 'Unknown Match')}")
        print(f" └─ Tactical Alignment: {style_align} | H-Sync: {h_sync} | A-Sync: {a_sync}")
        print(f" └─ Signed: {h.get('team_name','?')}={h.get('verdict')} "
              f"({h_net if h_net is not None else 'n/a'}) | "
              f"{a.get('team_name','?')}={a.get('verdict')} "
              f"({a_net if a_net is not None else 'n/a'})")
        print(f" └─ MARKET ALIGNMENTS:")
        for market, status in chemistry.items():
            icon = "🔥" if status in ["Elite", "Excellent", "Very Strong"] else ("✅" if status == "Strong" else "🛑")
            print(f"      {icon} {market:<10} : {status}")
        for note in _coherence_notes:
            print(f"      ⚠️  coherence: {note}")
        print(f" └─ HANDSHAKE: {handshake['status']} — {handshake['summary']}")
        for _c in conflicts:
            print(f"      ❌ {_c['type']} {_c.get('target_name') or ''} vs "
                  f"{_c['market']}={_c['market_grade']}")

        # FINAL ASSEMBLED OUTPUT
        final_report.append({
            "fixture": audit.get('fixture', 'Unknown'),
            "fixture_id": audit.get('fixture_id', f_key),
            "incoming_probabilities": incoming_picks,
            "handshake": handshake,
            "danger_report": {
                "home": {
                    "id": h.get('id', ''),
                    "team_name": h.get('team_name', ''),
                    "status": h.get('danger_level', 'UNAVAILABLE'),
                    "verdict": h.get('verdict'),
                    "verdict_reason": h.get('verdict_reason'),
                    "net_impact": h.get('net_impact'),
                    "confidence": h.get('impact_confidence'),
                    "gk_verdict": h.get('gk_verdict'),
                    "data_available": h.get('data_available', True),
                    "sync": h_sync, "breach": h_breach
                },
                "away": {
                    "id": a.get('id', ''),
                    "team_name": a.get('team_name', ''),
                    "status": a.get('danger_level', 'UNAVAILABLE'),
                    "verdict": a.get('verdict'),
                    "verdict_reason": a.get('verdict_reason'),
                    "net_impact": a.get('net_impact'),
                    "confidence": a.get('impact_confidence'),
                    "gk_verdict": a.get('gk_verdict'),
                    "data_available": a.get('data_available', True),
                    "sync": a_sync, "breach": a_breach
                }
            },
            "match_chemistry_list": chemistry
        })

    # SAVE SAFELY IN THE DYNAMIC DIRECTORY FOR CODE 6 TO READ
    with open(AGGREGATOR_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=4, ensure_ascii=False)
        
    print(f"\n[🤝] HANDSHAKE COMPLETE: {len(final_report)} Matches Aggregated.")
    print(f" Master Report Saved: {AGGREGATOR_REPORT_FILE}")
    print("="*120 + "\n")

    return final_report

if __name__ == "__main__":
    run_master_aggregator()