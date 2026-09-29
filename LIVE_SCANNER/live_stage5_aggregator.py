import os
import json
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
        openness = 1.0 if style_align == "🔥 OPEN" else 0.0
        tight = 1.0 if style_align == "⚠️ TIGHT" else 0.0

        chemistry = {}
        scores = {}
        # BTTS needs goals from BOTH sides, so damage on either side is
        # doubly negative for it, not doubly positive (as the old ladder had it).
        scores["Gg"] = (3.0 + 2.0 * openness - 1.5 * abs(total_damage)
                        + (0.75 if (h_breach or a_breach) else 0.0))
        # Corners read width and tempo, which the style axis captures.
        scores["Corner"] = 3.0 + 2.0 * openness - 1.0 * tight
        scores["Home Win"] = (3.0 - 3.0 * h_eff + 0.75 * a_eff
                              - (0.75 if h_sync == "CONFLICT" else 0.0)
                              + (0.75 if h_sync == "ELITE" else 0.0))
        scores["Away Win"] = (3.0 - 3.0 * a_eff + 0.75 * h_eff
                              - (0.75 if a_sync == "CONFLICT" else 0.0)
                              + (0.75 if a_sync == "ELITE" else 0.0))
        # Over 2.5 needs 3 goals; Over 1.5 needs 2. They MUST stay monotone.
        # Note the sign: a match where BOTH sides were upgraded (total_damage
        # negative) is correctly read as LESS likely to produce goals.
        goal_pressure = (2.0 * openness
                         + 2.0 * max(0.0, total_damage)
                         - 2.0 * max(0.0, -total_damage))
        scores["Over2.5"] = 2.0 + goal_pressure
        scores["Over1.5"] = 3.0 + goal_pressure + 0.5 * openness
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

        for market, value in scores.items():
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
        # sets the ceiling for the easier one. Skipped entirely when the goal
        # read is unknown, since copying "Unavailable" across would erase a
        # market that may still be perfectly readable on its own terms.
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

        # The evidence gate runs AFTER the coherence pass on purpose.
        #
        # It used to run first, which meant the coherence pass then operated on
        # a fully "Unavailable" row and, worse, left a graded `Gg` sitting next
        # to Unavailable goal markets: the engine asserted "Excellent BTTS" and
        # "we have no idea how many goals" in the same row. If a market is
        # unknown, EVERY market that depends on it must be unknown too, and the
        # only reliable place to enforce that is after the grades exist.
        if h_breach is None or a_breach is None or style_align == "⚠️ UNAVAILABLE":
            # Missing Stage 4 evidence is not a negative or positive market
            # signal. Keep it explicit so user rules cannot fire on a fake
            # Tight/Strong chemistry label.
            chemistry = {market: "Unavailable" for market in (
                "Gg", "Corner", "Home Win", "Away Win",
                "Over2.5", "Under3.5", "Over1.5",
            )}
            _coherence_notes.append(
                "all markets marked Unavailable — Stage 4 evidence is missing "
                "for at least one side")

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