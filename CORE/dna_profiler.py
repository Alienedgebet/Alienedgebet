import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
V2_PATH  = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
V1_PATH  = os.path.join(DATA_DIR, "team_dna_profiles.json")
CLASHES_PATH = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")


def run_dna_profiler(target_date):
    """
    Unified DNA v1 compatibility wrapper.

    PREVIOUS BEHAVIOUR (bug): ignored `target_date` completely and returned
    the ENTIRE global profile library (every team ever profiled, across
    every date main.py has run) regardless of which date was requested —
    so /api/dna/{date} always served the same everything-at-once payload no
    matter what date the frontend actually asked for.

    FIX: scope the returned snapshot to only the teams playing on
    `target_date`, by reusing the team-ID set dna_engine_v2.py already
    determined for that date (carried in fixture_style_clashes_v2.json via
    the home_id/away_id fields added alongside this fix). This adds NO new
    API calls and NO competing fixture source — it's the exact same team
    set the DNA engine itself worked from, just read back off disk.

    Global caches on disk (team_dna_v2_profiles.json / team_dna_profiles.
    json) are read-only here and never modified, filtered, or rebuilt by
    this function — filtering only affects what gets RETURNED (and
    therefore what output_store saves under output/cache/dna__{date}.json).

    Safety fallback: if the clashes file is missing, unreadable, or simply
    has no entries for `target_date` (e.g. very first run, or a date whose
    pipeline hasn't executed under the fixed engine yet), this returns the
    full global library exactly as before — nothing regresses to empty.
    """
    profiles = {}
    for path in [V2_PATH, V1_PATH]:
        if os.path.exists(path) and os.path.getsize(path) > 100:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
                break
            except Exception:
                profiles = {}

    if not profiles:
        print("[⚠️ DNA] No cached profiles found on disk yet. Run run_dna_engine_v2 first.")
        return {}

    if not os.path.exists(CLASHES_PATH):
        print(f"[⚠️ DNA] No fixture clashes file yet — returning full global library "
              f"({len(profiles)} teams, unscoped).")
        return profiles

    try:
        with open(CLASHES_PATH, "r", encoding="utf-8") as f:
            clashes = json.load(f)
    except Exception:
        print(f"[⚠️ DNA] Could not read clashes file — returning full global library "
              f"({len(profiles)} teams, unscoped).")
        return profiles

    relevant_ids = set()
    for clash in clashes:
        if clash.get("fixture_date") != target_date:
            continue
        home_id = clash.get("home_id")
        away_id = clash.get("away_id")
        if home_id:
            relevant_ids.add(str(home_id))
        if away_id:
            relevant_ids.add(str(away_id))

    if not relevant_ids:
        # Either an older clashes file predating home_id/away_id, or this
        # date simply isn't the one the clashes file currently reflects
        # (clashes always holds only the MOST RECENTLY processed date).
        print(f"[⚠️ DNA] No ID-tagged fixtures found for {target_date} in the clashes "
              f"file — returning full global library ({len(profiles)} teams, unscoped).")
        return profiles

    scoped = {tid: profiles[tid] for tid in relevant_ids if tid in profiles}
    print(f"[⚡ DNA CACHE] Scoped {len(scoped)}/{len(profiles)} profiles to {target_date} "
          f"(0 API Calls).")
    return scoped


if __name__ == "__main__":
    run_dna_profiler("2026-09-06")
