"""
SHADOW MODE — records what the convergence rule WOULD have done.

This module is deliberately incapable of changing a prediction.

It reads `incoming_predictions.json` after Stage 3 has written it, works out
what the two-independent-source rule would have said about every pick, and
writes the answer to `convergence_shadow.json`. It never writes to
`incoming_predictions.json`, `danger_audit.json` or the aggregator board.

Why shadow first: the signals this rule depends on have not been shown to beat
the base rate (Over 2.5 58.5%, BTTS 48.1% on 183 internationals). Gating live
picks on an unvalidated rule could lose matches. So the first job is to watch
it disagree with the live feed and find out whether the disagreements are the
bad picks or the good ones.
"""
import json
import os
import time

from .live_convergence import converge

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "data")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "incoming_predictions.json")
PREMATCH_FILE = os.path.join(DATA_DIR, "prematch_team_audit.json")
SHADOW_FILE = os.path.join(DATA_DIR, "convergence_shadow.json")
LEDGER_FILE = os.path.join(DATA_DIR, "convergence_shadow_ledger.json")

# A pick needs this many independent sources to survive under the proposed
# rule. Mirrors live_convergence's own threshold.
SOURCES_REQUIRED = 2


def _load(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _review_pick(fixture_id, pick):
    """
    Map one prediction onto the convergence rule.

    An unmappable pick is reported as unmappable rather than guessed at — a
    shadow layer that fabricates coverage is worse than one that admits a gap.
    """
    ptype = pick.get("type")

    if ptype == "TO_SCORE":
        target = pick.get("target_loc")
        if target not in ("home", "away"):
            return {"type": ptype, "mappable": False, "would_gate": None,
                    "note": "no target_loc — cannot attribute a side"}

        # PROXY, and labelled as one. `win` is the only two-sided market the
        # feed prices (we hold a total O2.5 price, not a per-team one), so the
        # book's view of this side is approximated by its win price. "To score"
        # and "to win" are not the same question; this is the closest honest
        # read available, not an exact one.
        c = converge(fixture_id, "win", target)
        if "error" in c:
            # converge declines rather than guessing when a source is missing.
            # Honour that: report the pick as UNEVALUATED instead of letting a
            # KeyError abort the whole shadow report. One fixture without
            # danger data must not blind the layer to every other fixture.
            return {"type": ptype, "mappable": True, "evaluable": False,
                    "target": target, "team": pick.get("target_name"),
                    "would_gate": None,
                    "note": f"convergence could not evaluate: {c['error']}",
                    "reason_now": pick.get("reason")}
        return {
            "type": ptype, "mappable": True, "evaluable": True,
            "target": target, "team": pick.get("target_name"),
            "label": c["label"], "sources_agreeing": c["sources_agreeing"],
            "source_count": c["source_count"], "market": c["market"],
            "would_gate": c["source_count"] < SOURCES_REQUIRED,
            "proxy": "win-market price used as proxy for to-score",
            "reason_now": pick.get("reason"),
        }

    if ptype in ("GG", "GG_OVER_2.5"):
        # A both-teams claim needs BOTH sides to have a case, so it is reviewed
        # side by side and gated if either side has no source behind it.
        sides, failed = {}, False
        for target in ("home", "away"):
            c = converge(fixture_id, "win", target)
            if "error" in c:
                failed = True
                break
            sides[target] = {
                "label": c["label"],
                "sources_agreeing": c["sources_agreeing"],
                "source_count": c["source_count"],
                "market_leans": c["market"]["leans"],
            }
        if failed:
            return {"type": ptype, "mappable": True, "evaluable": False,
                    "would_gate": None,
                    "note": "convergence could not evaluate both sides",
                    "reason_now": pick.get("reason")}
        weakest = min(sides.values(), key=lambda s: s["source_count"])
        return {
            "type": ptype, "mappable": True, "evaluable": True, "sides": sides,
            "label": " / ".join(f"{k}={v['source_count']}"
                                for k, v in sides.items()),
            "would_gate": weakest["source_count"] < SOURCES_REQUIRED,
            "proxy": "per-side win-market review used as proxy "
                     "for a both-teams claim",
            "reason_now": pick.get("reason"),
        }

    return {"type": ptype, "mappable": False, "would_gate": None,
            "note": "no convergence market defined for this prediction type"}


def _fixture_names():
    """fixture_id -> fixture name, for readable shadow output."""
    pm = _load(PREMATCH_FILE, {})
    rows = list(pm.values()) if isinstance(pm, dict) else (
        pm if isinstance(pm, list) else [])
    return {str(r["fixture_id"]): r.get("fixture")
            for r in rows
            if isinstance(r, dict) and r.get("fixture_id") is not None}


def _kickoffs():
    pm = _load(PREMATCH_FILE, {})
    rows = list(pm.values()) if isinstance(pm, dict) else (
        pm if isinstance(pm, list) else [])
    return {str(r["fixture_id"]): r.get("kickoff_utc") for r in rows
            if isinstance(r, dict) and r.get("fixture_id") is not None}


def _record_ledger(fixtures, names, kickoffs):
    """
    Append each shadow decision to a durable ledger, once per pick.

    The snapshot above is overwritten every cycle, so by the time a fixture
    settles, the reading that actually scored it is gone. The ledger is what
    makes settlement possible: it keeps the FIRST reading of each pick, which
    is the one that would have gated it at the moment it was made.

    De-duplicated on (fixture, type, target). Recording every cycle instead
    would write the same decision hundreds of times and make a hit rate
    impossible to compute from the file.
    """
    ledger = _load(LEDGER_FILE, {})
    if not isinstance(ledger, dict):
        ledger = {}

    added = 0
    for fixture_id, block in fixtures.items():
        entry = ledger.setdefault(str(fixture_id), {
            "fixture": block.get("fixture"), "picks": []})
        # The key must be built ONLY from fields that are actually persisted
        # below. An earlier version keyed on whether the record carried a
        # `sides` block — but that field is not written to the ledger, so on
        # every re-read the stored key said False while the incoming record said
        # True, and every both-teams pick was appended again, forever. A
        # de-duplication key that cannot survive the round trip is no key.
        seen = {(p.get("type"), p.get("target"))
                for p in entry["picks"]}
        for rec in block["picks"]:
            key = (rec.get("type"), rec.get("target"))
            if key in seen:
                continue
            seen.add(key)
            entry["picks"].append({
                "recorded_at": time.time(),
                "kickoff_utc": kickoffs.get(str(fixture_id)),
                "type": rec.get("type"),
                "target": rec.get("target"),
                "team": rec.get("team"),
                "would_gate": rec.get("would_gate"),
                "source_count": rec.get("source_count"),
                "label": rec.get("label"),
                "sources_agreeing": rec.get("sources_agreeing"),
                "market_agrees": (rec.get("market") or {}).get(
                    "agrees_with_live"),
                "reason_now": rec.get("reason_now"),
            })
            added += 1

    if added:
        tmp = LEDGER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=1)
        os.replace(tmp, LEDGER_FILE)
    return added


def run_shadow_review():
    """
    Build the shadow report. Read-only with respect to every engine output.

    Any failure degrades to an error record rather than propagating: a broken
    shadow report must never be able to stop the live feed producing picks.
    """
    try:
        preds = _load(PREDICTIONS_FILE, {})
        names = _fixture_names()
        if not isinstance(preds, dict):
            return {"error": "predictions file has an unexpected shape",
                    "changes_nothing": True}

        fixtures, gated, unmappable, unevaluable, total = {}, 0, 0, 0, 0
        for fixture_id, picks in preds.items():
            if not isinstance(picks, list):
                continue
            reviewed = []
            for pick in picks:
                if not isinstance(pick, dict):
                    continue
                total += 1
                rec = _review_pick(str(fixture_id), pick)
                if rec is None:
                    unmappable += 1
                    continue
                if rec.get("would_gate"):
                    gated += 1
                if not rec.get("mappable", True):
                    unmappable += 1
                if rec.get("evaluable") is False:
                    unevaluable += 1
                reviewed.append(rec)
            if reviewed:
                fixtures[str(fixture_id)] = {
                    "fixture": names.get(str(fixture_id)),
                    "picks": reviewed,
                }

        try:
            recorded = _record_ledger(fixtures, names, _kickoffs())
        except Exception as exc:
            # The snapshot is still written below; losing the ledger is bad but
            # must not cost us the cycle's comparison.
            recorded = 0
            print(f"[shadow] ledger not updated: {exc}", flush=True)

        report = {
            "generated_at": time.time(),
            "mode": "SHADOW — nothing below changes any live pick",
            "changes_nothing": True,
            "sources_required": SOURCES_REQUIRED,
            "totals": {"picks_reviewed": total,
                       "would_be_gated": gated,
                       "not_mappable": unmappable,
                       "could_not_evaluate": unevaluable,
                       "new_ledger_entries": recorded},
            "fixtures": fixtures,
        }
        tmp = SHADOW_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
        os.replace(tmp, SHADOW_FILE)
        return report
    except Exception as exc:
        return {"error": str(exc), "changes_nothing": True}
