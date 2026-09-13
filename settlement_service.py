import os
import re
import json
from datetime import datetime, timezone

def clean_n(name):
    """Normalizes team names to eliminate suffixes like FC, United, U19, etc."""
    if not name:
        return ""
    n = str(name).lower()
    for word in ["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
        n = n.replace(word, "")
    return re.sub(r'[^a-z0-9]', '', n).strip()

def get_match_key(name):
    """Generates an alphabetical match key for order-independent team matching."""
    n = clean_n(name)
    parts = n.split('vs') if 'vs' in n else (n.split('-') if '-' in n else [n])
    parts = [p.strip() for p in parts]
    parts.sort()
    return "".join(parts)

def _extract_match_date(fx):
    """ISO kickoff date (YYYY-MM-DD) from whichever field the raw fixture
    carries. Date-endpoint fixtures expose `starting_at`; the in-play feed
    exposes `starting_at_timestamp` (epoch seconds) — string-slicing THAT
    would produce garbage like '1789123456', so convert it properly. Used by
    the date-constrained name-key fallback in settle_predictions()."""
    raw = fx.get("starting_at")
    if raw:
        return str(raw)[:10]
    ts = fx.get("starting_at_timestamp")
    if ts:
        try:
            # Server-local conversion (the VPS runs WAT) on purpose: every
            # other date in the application (pipeline target dates, _today(),
            # store keys) is the local calendar date, so a kick-off just past
            # midnight local time must map to the local day, not shift a day
            # back via UTC.
            return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        except Exception:
            return None
    return None

def extract_match_data(fx):
    """
    Parses a raw SportMonks fixture object into standardized match data
    (half-time score, full-time score, corners, live state, elapsed minute).
    """
    scores = fx.get("scores", [])
    h_ht = a_ht = h_ft = a_ft = 0
    has_started = False
    is_finished = False

    # Check match completion state. SportMonks v3 exposes the state object as
    # {"state": "FT", "name": "Full Time", "short_name": "FT",
    #  "developer_name": "FT"} — the terse code lives under the "state" KEY and
    # there is no "description" field, so the old
    # str(state.get("description")) was always "" and EVERY fixture — including
    # finished ones — was flagged is_finished=False (rows graded LIVE/IN_PLAY
    # forever, Verify never resolving). Read every plausible key, prefer the
    # terse canonical code, and accept the common finished spellings.
    st = fx.get("state") or {}
    if isinstance(st, dict):
        state_desc = str(
            st.get("state") or st.get("short_name") or st.get("developer_name")
            or st.get("name") or st.get("description") or ""
        ).upper()
    else:
        state_desc = str(st).upper()
    if state_desc in ["FT", "AET", "AP", "FT_PEN", "PEN", "FINISHED", "ENDED",
                      "FULL-TIME", "FULL TIME"]:
        is_finished = True

    for s in scores:
        desc = str(s.get("description", "")).upper()
        if isinstance(s.get("score"), dict):
            p = str(s["score"].get("participant", "")).lower()
            g = int(float(s["score"].get("goals", 0) or 0))
        else:
            p = str(s.get("participant", "")).lower()
            g = int(float(s.get("goals", 0) or 0))

        if desc in ["1ST_HALF", "1ST HALF"]:
            has_started = True
            if p == "home": h_ht = g
            elif p == "away": a_ht = g
        if desc in ["CURRENT", "2ND_HALF", "2ND HALF", "FULL_TIME", "FT"]:
            has_started = True
            if p == "home": h_ft = max(h_ft, g)
            elif p == "away": a_ft = max(a_ft, g)

    # Extract team names & IDs
    parts = fx.get("participants", [])
    h_name = a_name = ""
    h_id = a_id = None
    if len(parts) >= 2:
        h = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), parts[0])
        a = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), parts[1])
        h_name = h.get("name", "")
        a_name = a.get("name", "")
        h_id = str(h.get("id", ""))
        a_id = str(a.get("id", ""))

    # Extract Corners
    h_c = a_c = 0
    for stat in fx.get("statistics", []):
        if "corner" in str(stat.get("type", {}).get("name", "")).lower():
            pid = str(stat.get("participant_id"))
            val = stat.get("data", {}).get("value", stat.get("value", 0))
            try:
                if pid == h_id: h_c += int(float(val))
                elif pid == a_id: a_c += int(float(val))
            except Exception: pass

    sh_h = max(0, h_ft - h_ht)
    sh_a = max(0, a_ft - a_ht)
    minute = fx.get("state", {}).get("minute") or fx.get("time", {}).get("minute") or 0

    return {
        "fixture_id": str(fx.get("id", "")),
        "home_team": h_name,
        "away_team": a_name,
        "h_ht": h_ht, "a_ht": a_ht,
        "h_ft": h_ft, "a_ft": a_ft,
        "ft_score": f"{h_ft}-{a_ft}",
        "total_goals": h_ft + a_ft,
        "sh_goals_home": sh_h, "sh_goals_away": sh_a, "sh_goals": sh_h + sh_a,
        "h_corners": h_c, "a_corners": a_c, "total_corners": h_c + a_c,
        "has_started": has_started,
        "is_finished": is_finished,
        "minute": minute,
        # ISO kickoff date when the raw fixture carries one. Archives are
        # written per-date so this is redundant for them, but the live in-play
        # feed can legitimately contain fixtures of the previous day (late
        # kick-offs past midnight in the feed's timezone). Carrying the date
        # into the standardized shape is what allows settlement's name-key
        # fallback to reject cross-date name collisions instead of silently
        # grading a historical row against today's fixture.
        "match_date": _extract_match_date(fx)
    }

# ── FINISHED-RESULTS ARCHIVE (persistent settlement universe) ────────────────
# settlement_service.py lives in the repo ROOT, so a single dirname() is the
# backend root and the archive store written by daily_archiver.py is
# <backend>/output/archive_{date}.json. Settlement previously saw ONLY the
# transient /v3/football/livescores/inplay feed: a verdict evaporated the
# moment a fixture left the in-play list, and a historical date could never
# settle because its fixtures are never in today's feed. The archive is the
# persistent completed-results layer; the live feed remains the layer for
# matches currently being played.
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

_ARCHIVE_CACHE = {}  # {date_str: {fixture_id: standardized_match_dict}}


def load_finished_archive(date_str):
    """Load output/archive_{date}.json into a {fixture_id: standardized} map.

    - Returns {} when the archive is missing or unreadable: settlement then
      behaves exactly as before (live in-play source only) and never crashes.
    - The file is written once per completed day and never modified
      afterwards, so per-process caching needs no invalidation.
    - Every entry is already constrained to `date_str` by construction (one
      archive file per date), which is what gives historical Verify its
      date isolation: an id or name from another date can never leak in.
    """
    if not date_str:
        return {}
    if date_str in _ARCHIVE_CACHE:
        return _ARCHIVE_CACHE[date_str]

    archive_file = os.path.join(ARCHIVE_DIR, f"archive_{date_str}.json")
    fixtures_map = {}
    try:
        if os.path.exists(archive_file):
            with open(archive_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            raw = payload.get("fixtures", []) if isinstance(payload, dict) else []
            if isinstance(raw, list):
                for fx in raw:
                    if not isinstance(fx, dict):
                        continue
                    if all(k in fx for k in ("fixture_id", "home_team", "has_started")):
                        std = fx  # already standardized (archiver uses extract_match_data)
                    else:
                        std = extract_match_data(fx)
                    fid = str(std.get("fixture_id") or "")
                    if fid:
                        fixtures_map[fid] = std
    except Exception:
        fixtures_map = {}  # corrupt archive → treat exactly like a missing one

    _ARCHIVE_CACHE[date_str] = fixtures_map
    return fixtures_map


def grade_row(market_type, row, actual_match):
    """
    Evaluates an individual prediction row against actual match data.
    Returns the exact 3-state verification payload.
    """
    # 1. SCHEDULED / PRE-MATCH STATE
    if not actual_match or not actual_match.get("has_started"):
        return {
            "status": "SCHEDULED",
            "score": "—",
            "minute": None,
            "verdict": "PENDING",
            "badge_text": "—",
            "note": "Awaiting Kickoff"
        }

    is_finished = actual_match.get("is_finished", False)
    ft_score = actual_match.get("ft_score", "0-0")
    minute = actual_match.get("minute", 0)

    # 2. LIVE IN-PLAY STATE
    if not is_finished:
        return {
            "status": "LIVE",
            "score": ft_score,
            "minute": minute,
            "verdict": "IN_PLAY",
            "badge_text": f"{ft_score} ({minute}')",
            "note": f"Match in play ({minute}')"
        }

    # 3. SETTLED / FINISHED STATE (Market-Aware Math)
    m = str(market_type).lower()
    h_ft = actual_match["h_ft"]
    a_ft = actual_match["a_ft"]
    tot_g = actual_match["total_goals"]
    won = False
    note = ""

    # --- 1X2 WIN ---
    if m in ["win", "1x2"]:
        target = str(row.get("Target") or row.get("team_name") or row.get("Master_Pick") or row.get("fixture") or "")
        winner = (actual_match["home_team"] if h_ft > a_ft else actual_match["away_team"] if a_ft > h_ft else "DRAW")
        won = clean_n(target) in clean_n(winner) or clean_n(winner) in clean_n(target)
        note = f"{winner} ({ft_score})"

    # --- GG / BTTS ---
    elif m in ["gg", "btts"]:
        won = (h_ft > 0 and a_ft > 0)
        note = f"Both scored ({ft_score})" if won else f"Blanked ({ft_score})"

    # --- OVER 2.5 ---
    elif m in ["o25", "over25", "over 2.5"]:
        won = (tot_g >= 3)
        note = f"{tot_g} goals ({ft_score})"

    # --- OVER 1.5 ---
    elif m in ["o15", "over15", "over 1.5"]:
        won = (tot_g >= 2)
        note = f"{tot_g} goals ({ft_score})"

    # --- DRAW (1X2 draw) ---
    # Draw rows carry no Target/Master_Pick column — the prediction IS the
    # market ("this match ends level"). Keying them to the "win" branch graded
    # every correctly-predicted draw LOST (fixture name vs winner "DRAW" can
    # never match). Explicit market branch fixes the verdict at the source.
    elif m in ["draw", "draws"]:
        won = (h_ft == a_ft)
        note = f"DRAW ({ft_score})" if won else f"Not a draw ({ft_score})"

    # --- UNDER 2.5 GOALS ---
    # Under-2.5 rows likewise carry no pick column; they were previously keyed
    # to the "o25" branch, which inverted the market (a 0-0, the BEST u25
    # outcome, graded LOST). (u35 rows exist in the composite payload but are
    # rendered without verification and carry no current-branch key, so no
    # "u35" branch is added here — add one only if that list is ever settled.)
    elif m in ["u25", "under25", "under 2.5"]:
        won = (tot_g <= 2)
        note = f"{tot_g} goals ({ft_score})"

    # --- CORNERS ---
    elif m in ["corners"]:
        line = float(row.get("Corner_Line") or 9.5)
        tot_c = actual_match["total_corners"]
        won = tot_c > line
        note = f"{tot_c} corners (Line {line})"

    # --- SECOND HALF GOALS (SHVI) ---
    elif m in ["shvi", "sh_goal"]:
        sh_g = actual_match["sh_goals"]
        won = sh_g > 0
        note = f"{sh_g} SH goals ({ft_score})"

    # --- UNDERDOG TO SCORE (U2S) ---
    elif m in ["u2s"]:
        target = str(row.get("Underdog") or row.get("Target_Underdog") or row.get("underdog_team") or "")
        if clean_n(target) in clean_n(actual_match["home_team"]):
            won = h_ft > 0
        elif clean_n(target) in clean_n(actual_match["away_team"]):
            won = a_ft > 0
        note = f"Underdog scored ({ft_score})" if won else f"Underdog blanked ({ft_score})"

    return {
        "status": "FINISHED",
        "score": ft_score,
        "minute": None,
        "verdict": "WON" if won else "LOST",
        "badge_text": f"{'✅' if won else '❌'} {ft_score}",
        "note": note
    }

def settle_predictions(predictions, live_matches_db, market_type="win", date_str=None):
    """
    Settles a list of prediction rows against actual live/finished matches.
    PRIORITY 1: Match by fixture_id (exact & unambiguous)
    PRIORITY 2: Fallback to clean_n() name key (date-constrained)

    `live_matches_db` is the raw SportMonks v3 in-play feed (from
    live_cache.get_live_scores_cached()) — objects keyed by `id`, with
    `participants` / `scores` / `statistics` / `state`. The maps below need
    the STANDARDIZED shape that extract_match_data() produces (`fixture_id`,
    `home_team`, `away_team`, `has_started`, `is_finished`, `h_ft`, `a_ft`,
    …), so normalize every raw fixture first. Without this the lookups were
    always empty and every row fell back to the SCHEDULED/"Awaiting Kickoff"
    (PENDING) payload — leaving the frontend Verify badge permanently blank.

    PERSISTENT FINISHED-RESULTS UNIVERSE (Fix #3):
    The in-play feed is transient — a finished fixture disappears from it and
    its verdict would evaporate back to SCHEDULED/PENDING, and a historical
    date's fixtures are never in today's feed at all. `date_str` (the date of
    the picks being verified) now also loads the persistent archive
    output/archive_{date}.json written by daily_archiver.py, standardized by
    the same extract_match_data(). Merging priority below:

      1. archive entry (authoritative completed result for that fixture)
      2. live in-play entry (the match currently being played)

    A fixture finished in the archive keeps its WON/LOST verdict forever,
    even after leaving the in-play feed; today-not-yet-archived fixtures
    continue to settle from the live feed exactly as before. Date isolation
    is structural: only archive_{date_str}.json is consulted, so a same-name
    fixture from another date can never satisfy this request; without a
    valid `date_str` the archive layer is skipped entirely and behaviour is
    identical to the pre-archive system.
    """
    # ── LIVE IN-PLAY LAYER (unchanged behaviour, including pass-through) ──
    std_db = []
    for fx in (live_matches_db or []):
        if not isinstance(fx, dict):
            continue
        if all(k in fx for k in ("fixture_id", "home_team", "has_started")):
            std_db.append(fx)  # already standardized — pass through untouched
        else:
            std_db.append(extract_match_data(fx))

    id_map = {str(fx.get("fixture_id")): fx for fx in std_db if fx.get("fixture_id")}
    name_map = {get_match_key(f"{fx.get('home_team', '')} vs {fx.get('away_team', '')}"): fx for fx in std_db if fx.get("home_team")}

    # ── PERSISTENT FINISHED LAYER (archive for this exact date) ────────────
    # Merge priority (authoritative → stale):
    #   archive FINISHED  → overrides live entry and persists the verdict
    #                       after the fixture leaves the in-play feed
    #   archive UNFINISHED (interim snapshot: fixture still in play or not
    #                       started when the archive was written) → only
    #                       added when the live feed has no entry, so the
    #                       fresher live state is never downgraded
    if date_str:
        finished_db = load_finished_archive(date_str)
        for fid, fx in finished_db.items():
            live_fx = id_map.get(fid)
            if fx.get("is_finished") or live_fx is None:
                id_map[fid] = fx
                name_map[get_match_key(f"{fx.get('home_team', '')} vs {fx.get('away_team', '')}")] = fx

    enriched = []
    for row in predictions:
        rec = dict(row)
        fid = str(rec.get("fixture_id") or rec.get("id") or "")
        fix_name = str(rec.get("fixture") or rec.get("Fixture") or rec.get("Match") or "")

        # 1. Match by fixture_id first (globally unique — no date check needed)
        matched = id_map.get(fid)

        # 2. Fallback to clean_n match key — DATE-CONSTRAINED.
        #    The name key is not unique across dates, so a historical row must
        #    never be satisfied by an identically named fixture of another day
        #    (same clubs meet weekly, and the live feed only ever contains
        #    *today's* matches). When both sides carry a kickoff date, require
        #    exact agreement with the requested date; entries without a date
        #    (legacy cached payloads) keep the legacy permissive behaviour so
        #    the 3ffe1f5 name matching is never weakened for existing data.
        if not matched and fix_name:
            key = get_match_key(fix_name)
            cand = name_map.get(key)
            if cand is not None:
                m_date = cand.get("match_date")
                row_date = str(rec.get("match_date") or date_str or "")[:10]
                if not m_date or not row_date or m_date == row_date:
                    matched = cand

        # Attach verification object to row
        rec["verification"] = grade_row(market_type, rec, matched)
        enriched.append(rec)

    return enriched
