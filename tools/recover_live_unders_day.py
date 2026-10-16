"""One-off RECOVERY: re-file today's finished Stage 9 fixtures that the
pre-sticky-retention bug dropped from the day's live-unders snapshot.

WHY THIS EXISTS
---------------
On 2026-10-16 the Stage 9 retention had a timing deadlock (Stage 1 culled
finished fixtures from the audit before Stage 9 ran; Stage 6 wrote the
board's finished rows after it), so every fixture that left the pick list
was dropped from `output/cache/live_unders__{date}.json` forever — the day's
list decayed 19 → 2 while 22 of its fixtures had already played and finished.
The engine's per-cycle pick VALUES (u25/u35 scores, tiers, signals) were
never persisted anywhere, so they cannot be recovered — but the FIXTURES
themselves (identity, teams, kickoff) survive in data/fixture_date_cache.json
(stage 1's day listing, which carries the lineups + formations that made
them admissible picks in the first place).

This script re-files those fixtures as finished rows, honestly marked
`recovered: true` with the engine values absent (the frontend renders "—",
Verify grades the U2.5/U3.5 lines from final results once the archiver
writes today's archive — the rows then settle WON/LOST permanently).

IDEMPOTENT + ZERO PROVIDER CALLS: reads only on-disk files, skips any
fixture already in the snapshot, and writes through output_store with the
collapse guard (growth is monotonic, so the guard always ALLOWs).

Usage:  ./venv/bin/python3 tools/recover_live_unders_day.py 2026-10-16
"""
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import output_store  # noqa: E402

DATE_CACHE_FILE = os.path.join(BASE_DIR, "data", "fixture_date_cache.json")
SAVE_KEY = "live_unders"


def _state_label(fx):
    st = fx.get("state")
    if isinstance(st, dict):
        return str(st.get("state") or "")
    return str(st or "")


def _sides(fx):
    """(home_name, away_name) resolved via the formations location map."""
    forms = fx.get("formations") or []
    by_pid = {}
    for f in forms:
        if isinstance(f, dict) and f.get("participant_id") is not None:
            by_pid[str(f["participant_id"])] = str(f.get("location") or "")
    home = away = ""
    for p in fx.get("participants") or []:
        if not isinstance(p, dict):
            continue
        loc = by_pid.get(str(p.get("id")))
        if loc == "home":
            home = p.get("name") or ""
        elif loc == "away":
            away = p.get("name") or ""
    if not home or not away:  # fallback: the listing name is "H vs A"
        parts = str(fx.get("name") or "").split(" vs ")
        if len(parts) == 2:
            home = home or parts[0].strip()
            away = away or parts[1].strip()
    return home, away


def recover(date_str):
    with open(DATE_CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    day = (cache.get(date_str) or {}).get("data") or []

    prev, _ = output_store.load(SAVE_KEY, date_str, default=[])
    rows = prev if isinstance(prev, list) else []
    have = {str(r.get("fixture_id")) for r in rows
            if isinstance(r, dict) and r.get("fixture_id") not in (None, "")}

    added = 0
    for fx in day:
        if not isinstance(fx, dict) or _state_label(fx) != "FT":
            continue
        fid = str(fx.get("id") or "")
        if not fid or fid in have:
            continue  # already filed (current pick, or recovered previously)
        forms = fx.get("formations") or []
        locations = {str(f.get("location")) for f in forms
                     if isinstance(f, dict)}
        if not {"home", "away"} <= locations:
            continue  # was never lineup/formation-admissible — not a pick
        home, away = _sides(fx)
        rows.append({
            "fixture_id": fid,
            "fixture": fx.get("name") or f"{home} vs {away}",
            "home_team": home,
            "away_team": away,
            "fixture_status": "finished",
            "is_live": False,
            "finished_date": date_str,
            "kickoff_utc": fx.get("starting_at"),
            "recovered": True,
            "recovery_note": (
                "re-filed after the 2026-10-16 retention bug; the engine's "
                "per-cycle pick values were not persisted and are honestly "
                "absent — Verify grades the lines from final results"
            ),
        })
        have.add(fid)
        added += 1

    if added:
        output_store.save(SAVE_KEY, date_str, rows, guard=True)
    print(f"[RECOVER] {date_str}: {added} finished fixture(s) re-filed "
          f"(snapshot now holds {len(rows)} rows)")
    return added


if __name__ == "__main__":
    target = (sys.argv[1].strip() if len(sys.argv) > 1
              else __import__("datetime").datetime.now().strftime("%Y-%m-%d"))
    recover(target)
