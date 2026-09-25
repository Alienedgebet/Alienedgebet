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

def _is_finished_state(value):
    """Final-state detection (Batch C): explicit allowlist rooted in what the
    existing system already accepted (``FT``, ``AET``, ``AP``, ``FT_PEN``,
    ``PEN``, ``FINISHED``, ``ENDED``, ``FULL-TIME``, ``FULL TIME``) plus the
    canonical SportMonks terse variants not previously handled (``FULL_TIME``,
    ``FT_PEN`` as a terse code). Unknown or in-progress states are never
    treated as finished."""
    if not value:
        return False
    token = str(value).strip().upper()
    if token in _EXPLICIT_FINAL_TOKENS:
        return True
    return token.startswith("FT_")


def _usable_fixture_id(val) -> str:
    """A fixture identity usable for matching. Placeholder ids (``"N/A"``,
    ``""``, ``"0"``, …) return ``""``, so they count as "no identity" and fall
    through to the name fallback instead of blocking the row under an unusable
    key."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in _PLACEHOLDER_FIXTURE_IDS else s


# ---- helpers referenced by extract_match_data() and the matching layer ----

_STATE_CODE_KEYS = ("state", "short_name", "developer_name", "name")

_EXPLICIT_FINAL_TOKENS = frozenset((
    "FT", "AET", "AP", "FT_PEN", "PEN", "FINISHED", "ENDED",
    "FULL-TIME", "FULL TIME", "FULL_TIME",
))

_PLACEHOLDER_FIXTURE_IDS = frozenset({"n/a", "na", "none", "0", ""})


def get_strict_match_key(name):
    """Qualifier-preserving identity — distinguishes "Napoli U19 vs Arsenal U19"
    from "Napoli vs Arsenal" so the strict fallback selects exactly one of two
    same-loose-key candidates instead of silently cross-matching youth vs senior."""
    n = str(name).lower()
    parts = n.split('vs') if 'vs' in n else (n.split('-') if '-' in n else [n])
    parts = [p.strip() for p in parts]
    parts.sort()
    return "".join(parts)

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
        # Batch C: accept a canonical finished code from ANY of the code-bearing
        # fields (a value may also carry a human suffix, e.g.
        # "FT_PEN: Home won on penalties"). Explicit allowlist only — an unknown
        # or in-progress state is never treated as finished.
        is_finished = any(_is_finished_state(st.get(k)) for k in _STATE_CODE_KEYS)
    else:
        is_finished = _is_finished_state(st)

    # Batch C: track whether a REAL final score was actually read for BOTH
    # sides. h_ft/a_ft default to 0, so grading a finished fixture whose score
    # entries are absent would invent a 0-0 result out of thin air. Settlement
    # uses this to stay PENDING instead (see grade_row). A genuine 0-0 still
    # reports both sides, so real goalless draws are unaffected.
    saw_home_final = False
    saw_away_final = False

    # A finished match must have started — this lets grade_row reach the
    # "FINISHED BUT RESULT UNUSABLE" check even when no score entries exist.
    if is_finished:
        has_started = True

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
            if p == "home":
                h_ft = max(h_ft, g)
                saw_home_final = True
            elif p == "away":
                a_ft = max(a_ft, g)
                saw_away_final = True

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

    # Extract Shots On Target (SOT) — same statistics feed and same
    # participant-id matching as corners. SportMonks exposes the per-team
    # count as "Shots On Target" (older feeds: "Shots On Goal"); both
    # spellings are accepted. Feeds the SOT verify branch (combined SOT
    # of both teams > 6 → WON) for both live in-play snapshots and the
    # nightly archives, which already carry statistics.
    h_sot = a_sot = 0
    for stat in fx.get("statistics", []):
        _type_name = str(stat.get("type", {}).get("name", "")).lower()
        if "shots on target" in _type_name or "shots on goal" in _type_name:
            pid = str(stat.get("participant_id"))
            val = stat.get("data", {}).get("value", stat.get("value", 0))
            try:
                if pid == h_id: h_sot += int(float(val))
                elif pid == a_id: a_sot += int(float(val))
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
        "h_sot": h_sot, "a_sot": a_sot, "total_sot": h_sot + a_sot,
        "has_started": has_started,
        "is_finished": is_finished,
        # Batch C (additive field): True only when a final-score entry was read
        # for BOTH sides. Legacy payloads (archives written before this field
        # existed) have no key at all and settlement defaults it to True, so
        # their verdicts stay byte-identical.
        "score_available": bool(saw_home_final and saw_away_final),
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

_ARCHIVE_CACHE = {}  # {date_str: (mtime_or_None, size_or_None, {fixture_id: standardized})}
_ARCHIVE_MISSING_RECHECK_S = 60  # re-stat a missing file at most once per minute
_ARCHIVE_MISSING_LAST_CHECK = {}  # {date_str: monotonic_seconds_of_last_stat}


def load_finished_archive(date_str):
    """Load output/archive_{date}.json into a {fixture_id: standardized} map.

    - Returns {} when the archive is missing or unreadable: settlement then
      behaves exactly as before (live in-play source only) and never crashes.
    - The per-process cache is invalidated by the file's mtime/size: an
      archive that appears after being missing, or that is rewritten
      (nightly archiver re-run), is re-read on the next call. A missing file
      is NEVER cached permanently — it is re-statted (at most once per
      minute per date) so a late-night archive landing is picked up without
      a worker restart. A corrupt/unreadable file degrades to {} exactly as
      before.
    - Every entry is already constrained to `date_str` by construction (one
      archive file per date), which is what gives historical Verify its
      date isolation: an id or name from another date can never leak in.
    """
    import time as _time

    if not date_str:
        return {}
    archive_file = os.path.join(ARCHIVE_DIR, f"archive_{date_str}.json")
    try:
        st = os.stat(archive_file)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        # Missing file: serve {} but do NOT cache it permanently — re-stat
        # periodically so an archive that lands later is picked up.
        now = _time.monotonic()
        last = _ARCHIVE_MISSING_LAST_CHECK.get(date_str)
        if last is not None and (now - last) < _ARCHIVE_MISSING_RECHECK_S:
            cached = _ARCHIVE_CACHE.get(date_str)
            if cached is not None:
                return cached[2]
            return {}
        _ARCHIVE_MISSING_LAST_CHECK[date_str] = now
        _ARCHIVE_CACHE[date_str] = (None, None, {})
        return {}
    cached = _ARCHIVE_CACHE.get(date_str)
    if cached is not None and (cached[0], cached[1]) == sig:
        return cached[2]
    fixtures_map = {}
    try:
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

    _ARCHIVE_CACHE[date_str] = (sig[0], sig[1], fixtures_map)
    _ARCHIVE_MISSING_LAST_CHECK.pop(date_str, None)
    return fixtures_map


# ── FT RESULT SNAPSHOT (persistent results captured at FT detection) ─────────
# Fills the gap: LIVE → FT → SportMonks removes fixture from inplay feed →
# nightly archive hasn't run yet → snapshot preserves the result for settlement.
# Written by live_cache.get_live_scores_cached() when it detects a finished fixture.
# Loaded by settle_predictions() as an additional persistent source alongside the
# live feed and the nightly archive.
#
# Location: data/ft_result_snapshot.json (alongside live_inplay_cache.json)
# Shape: {fixtures: {date_str: {fixture_id: standardized}}} — only finished fixtures.
FT_SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ft_result_snapshot.json")

_FT_SNAPSHOT_CACHE = {}  # {date_str: (mtime_or_None, size_or_None, {fixture_id: standardized})}
_FT_SNAPSHOT_MISSING_RECHECK_S = 60
_FT_SNAPSHOT_MISSING_LAST_CHECK = {}


def load_ft_snapshot(date_str):
    """Load data/ft_result_snapshot.json into a {fixture_id: standardized} map.

    - Returns {} when the snapshot is missing or unreadable: settlement then
      behaves exactly as before (live in-play + archive only) and never crashes.
    - The per-process cache is invalidated by the file's mtime/size.
    - Only finished fixtures (is_finished=True) are loaded.
    - Every entry carries match_date for date isolation.
    """
    import time as _time

    if not date_str:
        return {}
    try:
        st = os.stat(FT_SNAPSHOT_FILE)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        now = _time.monotonic()
        last = _FT_SNAPSHOT_MISSING_LAST_CHECK.get(date_str)
        if last is not None and (now - last) < _FT_SNAPSHOT_MISSING_RECHECK_S:
            cached = _FT_SNAPSHOT_CACHE.get(date_str)
            if cached is not None:
                return cached[2]
            return {}
        _FT_SNAPSHOT_MISSING_LAST_CHECK[date_str] = now
        _FT_SNAPSHOT_CACHE[date_str] = (None, None, {})
        return {}
    cached = _FT_SNAPSHOT_CACHE.get(date_str)
    if cached is not None and (cached[0], cached[1]) == sig:
        return cached[2]
    fixtures_map = {}
    try:
        with open(FT_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        raw = payload.get("fixtures", {}) if isinstance(payload, dict) else {}
        if isinstance(raw, dict):
            date_fixtures = raw.get(date_str, {})
            if isinstance(date_fixtures, dict):
                for fid, fx in date_fixtures.items():
                    if not isinstance(fx, dict):
                        continue
                    if not fx.get("is_finished"):
                        continue
                    if all(k in fx for k in ("fixture_id", "home_team", "has_started")):
                        std = fx
                    else:
                        std = extract_match_data(fx)
                    if fid:
                        fixtures_map[fid] = std
    except Exception:
        fixtures_map = {}

    _FT_SNAPSHOT_CACHE[date_str] = (sig[0], sig[1], fixtures_map)
    _FT_SNAPSHOT_MISSING_LAST_CHECK.pop(date_str, None)
    return fixtures_map


def write_ft_snapshot(fixtures_by_date):
    """Write/update the FT result snapshot.

    `fixtures_by_date` is a dict: {date_str: [standardized_fixture, ...]}.
    Only finished fixtures (is_finished=True) are written.
    Existing entries are preserved (merge, not replace).
    Atomic write via tmp+replace.
    """
    import os as _os

    existing = {}
    if _os.path.exists(FT_SNAPSHOT_FILE):
        try:
            with open(FT_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, dict) or "fixtures" not in existing:
                existing = {}
        except Exception:
            existing = {}

    if not isinstance(existing, dict):
        existing = {}
    if "fixtures" not in existing:
        existing["fixtures"] = {}
    if "updated_at" not in existing:
        existing["updated_at"] = None

    for date_str, fixtures in fixtures_by_date.items():
        if not isinstance(fixtures, list):
            continue
        date_fixtures = existing["fixtures"].setdefault(date_str, {})
        if not isinstance(date_fixtures, dict):
            date_fixtures = {}
            existing["fixtures"][date_str] = date_fixtures
        for fx in fixtures:
            if not isinstance(fx, dict):
                continue
            if not fx.get("is_finished"):
                continue
            std = fx
            if not all(k in fx for k in ("fixture_id", "home_team", "has_started")):
                std = extract_match_data(fx)
            fid = str(std.get("fixture_id") or "")
            if fid:
                # Never let a score-less write (the 429-storm shape) DOWNGRADE
                # a stored entry that already carries a usable final score:
                # keep the richer existing one and overwrite only when the
                # new row is scored, the old one was not, or both are equal.
                prev = date_fixtures.get(fid)
                if isinstance(prev, dict) and prev.get("score_available", True) \
                        and not std.get("score_available", True):
                    continue
                date_fixtures[fid] = std

    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    existing["date"] = datetime.now().strftime("%Y-%m-%d")

    _os.makedirs(_os.path.dirname(FT_SNAPSHOT_FILE), exist_ok=True)
    tmp = f"{FT_SNAPSHOT_FILE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    _os.replace(tmp, FT_SNAPSHOT_FILE)


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

    # 2b. FINISHED BUT RESULT UNUSABLE (Batch C)
    # The state says the match is over, but no final-score entry could be read.
    # h_ft/a_ft default to 0, so grading here would fabricate a 0-0 result and a
    # verdict from it. Stay PENDING instead. `score_available` defaults to True
    # for legacy payloads (archives written before the field existed), so every
    # pre-existing verdict is unchanged; the frontend already renders verdict
    # PENDING as an em-dash, so no client contract changes.
    if is_finished and not actual_match.get("score_available", True):
        # Batch D — "live source saw the final whistle": the archive row says
        # the match is over but the archived payload carries no usable score
        # (the 429-storm shape). BEFORE falling back to PENDING, check the
        # persistent FT snapshot (data/ft_result_snapshot.json), which the
        # live scanner writes the moment it sees the finished fixture and the
        # archiver tops up on every run. A snapshot entry for the SAME
        # fixture on the SAME date (or, lacking the id, the single FINISHED
        # score-available entry under the same strict match key) is
        # authoritative — the row is graded from it immediately instead of
        # waiting for the next night's archive.
        _cand = None
        try:
            _snap_date = actual_match.get("match_date")
            _snap = load_ft_snapshot(_snap_date) if _snap_date else {}
            if _snap:
                _fid = str(actual_match.get("fixture_id") or "")
                _cand = _snap.get(_fid)
                # A score-less snapshot entry for the same id adds nothing —
                # promoting it would grade a fabricated 0-0. Require a usable
                # score on ANY promoted candidate, direct-id or fallback.
                if _cand is not None and (
                        _cand is actual_match
                        or not _cand.get("score_available", True)):
                    _cand = None
                    _key = get_strict_match_key(
                        f"{actual_match.get('home_team', '')} vs "
                        f"{actual_match.get('away_team', '')}")
                    _fallbacks = []
                    for _fx in _snap.values():
                        if _fx is actual_match or not _fx.get("is_finished") \
                                or not _fx.get("score_available", True):
                            continue
                        if _key and get_strict_match_key(
                                f"{_fx.get('home_team', '')} vs "
                                f"{_fx.get('away_team', '')}") != _key:
                            continue
                        _fallbacks.append(_fx)
                    if len(_fallbacks) == 1:
                        _cand = _fallbacks[0]
        except Exception:
            _cand = None
        if _cand is not None:
            # Promote: live snapshot wins over the score-less archive row.
            promoted = dict(actual_match)
            promoted["h_ft"] = _cand.get("h_ft", 0)
            promoted["a_ft"] = _cand.get("a_ft", 0)
            promoted["ft_score"] = _cand.get(
                "ft_score", f"{promoted['h_ft']}-{promoted['a_ft']}")
            promoted["total_goals"] = promoted["h_ft"] + promoted["a_ft"]
            promoted["h_sot"] = _cand.get("h_sot", 0)
            promoted["a_sot"] = _cand.get("a_sot", 0)
            promoted["total_sot"] = _cand.get("total_sot",
                                              promoted["h_sot"] + promoted["a_sot"])
            promoted["h_corners"] = _cand.get("h_corners", 0)
            promoted["a_corners"] = _cand.get("a_corners", 0)
            promoted["total_corners"] = _cand.get("total_corners",
                                                  promoted["h_corners"] + promoted["a_corners"])
            promoted["score_available"] = True
            return grade_row(market_type, row, promoted)

        return {
            "status": "FINISHED",
            "score": "—",
            "minute": minute,
            "verdict": "PENDING",
            "badge_text": "—",
            "note": "Full time — result not available yet"
        }

    # 2. LIVE IN-PLAY STATE
    m = str(market_type).lower()
    if not is_finished:
        live_payload = {
            "status": "LIVE",
            "score": ft_score,
            "minute": minute,
            "verdict": "IN_PLAY",
            "badge_text": f"{ft_score} ({minute}')",
            "note": f"Match in play ({minute}')"
        }
        # Keep the live market metric visible in Verify as well as the final
        # result. Other markets continue to show the football score.
        if m == "sot":
            live_payload.update({
                "h_sot": int(actual_match.get("h_sot", 0)),
                "a_sot": int(actual_match.get("a_sot", 0)),
                "total_sot": int(actual_match.get(
                    "total_sot",
                    int(actual_match.get("h_sot", 0)) + int(actual_match.get("a_sot", 0)),
                )),
            })
        elif m == "corners":
            live_payload.update({
                "h_corners": int(actual_match.get("h_corners", 0)),
                "a_corners": int(actual_match.get("a_corners", 0)),
                "total_corners": int(actual_match.get(
                    "total_corners",
                    int(actual_match.get("h_corners", 0)) + int(actual_match.get("a_corners", 0)),
                )),
            })
        return live_payload

    # 3. SETTLED / FINISHED STATE (Market-Aware Math)
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

    # --- HIGH PARITY (score gap ≤ 2) ---
    # User-confirmed: the High Parity List wins when the final score stays
    # CLOSE (|home - away| <= 2), NOT only on an exact draw — that is the
    # conventional Draw branch above and it is untouched.
    elif m in ["parity", "high_parity"]:
        gap = abs(h_ft - a_ft)
        won = gap <= 2
        note = f"Score gap {gap} (≤2) ({ft_score})"

    # --- UNDER 3.5 GOALS ---
    # The u35 list lives in the composite unders payload (raw[1]) and was
    # previously graded nowhere — Verify stayed blank. Total goals <= 3 is
    # the Under-3.5 condition; do NOT fold it into the u25 branch (<= 2).
    elif m in ["u35", "u3.5", "under35", "under 3.5"]:
        won = (tot_g <= 3)
        note = f"{tot_g} goals ({ft_score})"

    # --- CORNERS (verify the TOTAL, not the corner winner) ---
    # The corner market is a fixed 7+ total threshold: the result is the
    # combined home + away corner count, independent of the displayed pick
    # projection. The note exposes both team counts for the UI.
    elif m in ["corners"]:
        tot_c = actual_match["total_corners"]
        h_c = int(actual_match.get("h_corners", 0))
        a_c = int(actual_match.get("a_corners", 0))
        if tot_c <= 0:
            # 0-0 corners almost always means the finished snapshot carries
            # no corner statistics. Grading those as LOST would fabricate a
            # verdict, so keep the row pending until real stats are available.
            return {
                "status": "FINISHED",
                "score": ft_score,
                "minute": None,
                "verdict": "PENDING",
                "badge_text": ft_score,
                "note": "Corner stats unavailable",
                "h_corners": h_c,
                "a_corners": a_c,
                "total_corners": tot_c,
            }
        line = 7  # user-confirmed combined-corner threshold: 7+
        won = tot_c >= line
        note = f"{h_c}+{a_c}={tot_c} corners vs line {line} → {'OVER' if won else 'UNDER'}"

    # --- SECOND HALF GOALS (SHVI) ---
    elif m in ["shvi", "sh_goal"]:
        sh_g = actual_match["sh_goals"]
        won = sh_g > 0
        note = f"{sh_g} SH goals ({ft_score})"

    # --- SHOTS ON TARGET (SOT) — corners method, fixed line 6 ---
    # Exactly mirrors the corners branch: read the per-team SOT counts that
    # extract_match_data() pulled from the statistics feed, guard against
    # grading a finished fixture with no shot stats (0+0 would fabricate a
    # LOST), then grade the COMBINED total. User-confirmed rule: combined
    # SOT strictly greater than 6 wins the pick; <= 6 loses. The SOT payload
    # stores no per-row projected line (unlike corners), so the line is the
    # fixed AlienEdge threshold of 6.
    elif m in ["sot"]:
        h_s = int(actual_match.get("h_sot", 0))
        a_s = int(actual_match.get("a_sot", 0))
        tot_s = int(actual_match.get("total_sot", h_s + a_s))
        if tot_s <= 0:
            return {
                "status": "FINISHED",
                "score": ft_score,
                "minute": None,
                "verdict": "PENDING",
                "badge_text": ft_score,
                "note": "SOT stats unavailable",
                "h_sot": h_s,
                "a_sot": a_s,
                "total_sot": tot_s,
            }
        line = 6  # combined both-teams SOT line (strictly over 6 wins)
        won = tot_s > line
        note = f"{h_s}+{a_s}={tot_s} SOT vs {line} → {'OVER' if won else 'UNDER'}"

    # --- FIRST HALF GOALS (FHVI) ---
    # FHVI is graded on FIRST-half goals. It previously routed through the
    # SHVI (second-half) branch via get_fhvi()'s market key — the wrong half
    # of the match. h_ht/a_ht are the 1st-half score entries read from the
    # same "1ST_HALF" score rows that feed sh_goals; the condition mirrors
    # SHVI's (sh_goals > 0) applied to the correct half.
    elif m in ["fhvi", "fh_goal"]:
        fh_g = int(actual_match.get("h_ht", 0)) + int(actual_match.get("a_ht", 0))
        won = fh_g > 0
        note = (f"{fh_g} FH goals "
                f"(HT {actual_match.get('h_ht', 0)}-{actual_match.get('a_ht', 0)}, FT {ft_score})")

    # --- UNDERDOG TO SCORE (U2S) ---
    # Verify against the STORED underdog selection (the engine's pick at
    # prediction time — preferred over re-deriving from current odds, which
    # can drift). The old fall-through graded an unmatched dog as a
    # fabricated LOST even though its side was never identified; when the
    # stored name cannot be matched to either team the honest answer is
    # PENDING, never a verdict.
    elif m in ["u2s"]:
        target = str(row.get("Underdog") or row.get("Target_Underdog") or row.get("underdog_team") or "")
        t_key = clean_n(target)
        h_key = clean_n(actual_match["home_team"])
        a_key = clean_n(actual_match["away_team"])
        matched = None
        if t_key and t_key in h_key:
            matched = ("home", actual_match["home_team"], h_ft)
        elif t_key and t_key in a_key:
            matched = ("away", actual_match["away_team"], a_ft)
        if matched is None:
            return {
                "status": "FINISHED",
                "score": ft_score,
                "minute": None,
                "verdict": "PENDING",
                "badge_text": ft_score,
                "note": f"Underdog '{target or '?'}' not identifiable in this fixture",
            }
        side, team, goals = matched
        won = goals >= 1
        note = (
            f"{team} ({side}) {'scored' if won else 'blanked'} "
            f"({goals}g, {ft_score})"
        )

    if m == "sot":
        return {
            "status": "FINISHED",
            "score": ft_score,
            "minute": None,
            "verdict": "WON" if won else "LOST",
            "badge_text": f"{'✅' if won else '❌'} {ft_score}",
            "note": note,
            "h_sot": h_s,
            "a_sot": a_s,
            "total_sot": tot_s,
        }
    if m == "corners":
        return {
            "status": "FINISHED",
            "score": ft_score,
            "minute": None,
            "verdict": "WON" if won else "LOST",
            "badge_text": f"{'✅' if won else '❌'} {ft_score}",
            "note": note,
            "h_corners": h_c,
            "a_corners": a_c,
            "total_corners": tot_c,
        }
    return {
        "status": "FINISHED",
        "score": ft_score,
        "minute": None,
        "verdict": "WON" if won else "LOST",
        "badge_text": f"{'✅' if won else '❌'} {ft_score}",
        "note": note
    }

def _fixture_identity(fx) -> str:
    """Authoritative fixture identity: the fixture id as a string ("" when the
    entry carries none)."""
    return _usable_fixture_id(fx.get("fixture_id"))


def _same_result(a, b) -> bool:
    """True when two entries describe the identical outcome."""
    return (bool(a.get("is_finished")) == bool(b.get("is_finished"))
            and str(a.get("ft_score") or "") == str(b.get("ft_score") or "")
            and int(a.get("h_ft") or 0) == int(b.get("h_ft") or 0)
            and int(a.get("a_ft") or 0) == int(b.get("a_ft") or 0))


def _merge_identified_fixture(id_map, ambiguous_ids, fid, fx):
    """Insert one result under its FIXTURE ID, keeping the existing
    archive/live merge priority and never silently choosing between two
    contradictory finished results.

      * new id                     -> insert
      * finished vs unfinished     -> the FINISHED entry wins (archive priority,
                                      exactly as before)
      * two unfinished             -> newest wins (the fresher live snapshot —
                                      identical to the previous dict behaviour)
      * two finished, same result  -> keep the existing entry (no conflict)
      * two finished, DIFFERENT    -> AMBIGUOUS: the id is dropped, so the row
                                      stays unmatched/PENDING instead of being
                                      graded against an arbitrary result
    """
    if not fid or fid in ambiguous_ids:
        return
    current = id_map.get(fid)
    if current is None:
        id_map[fid] = fx
        return
    cur_fin, new_fin = bool(current.get("is_finished")), bool(fx.get("is_finished"))
    if cur_fin != new_fin:
        id_map[fid] = fx if new_fin else current
        return
    if cur_fin and new_fin and not _same_result(current, fx):
        id_map.pop(fid, None)
        ambiguous_ids.add(fid)
        return
    id_map[fid] = fx


def _add_name_candidate(name_map, strict_map, fx):
    """Index one merged result under BOTH its loose (qualifier-stripped) and
    strict (qualifier-preserving) identity key.

    Lists, not single values: one loose key can legitimately cover two different
    fixtures (a U19 and a senior match between the same clubs on the same day).
    """
    home = str(fx.get("home_team") or "")
    away = str(fx.get("away_team") or "")
    if not home and not away:
        return
    pair = f"{home} vs {away}"
    name_map.setdefault(get_match_key(pair), []).append(fx)
    strict_map.setdefault(get_strict_match_key(pair), []).append(fx)


def _match_by_name(name_map, strict_map, fix_name, row_fid, row, date_str):
    """Date-scoped name fallback — used ONLY when fixture identity is missing on
    at least one side. Never second-guesses two different known fixture ids, and
    never picks arbitrarily between two same-named candidates."""
    candidates = name_map.get(get_match_key(fix_name)) or []
    if not candidates:
        return None

    row_date = str(row.get("match_date") or date_str or "")[:10]
    dated = []
    for cand in candidates:
        m_date = cand.get("match_date")
        # Existing rule, unchanged: the name key is not unique across dates, so
        # when both sides carry a kickoff date they must agree. A date-less
        # legacy entry keeps the historical permissive behaviour, so no
        # previously-working match is weakened.
        if not m_date or not row_date or m_date == row_date:
            dated.append(cand)
    if not dated:
        return None

    # Two different KNOWN fixture ids are two different fixtures, even when the
    # team names are identical. A row that carries a real id may therefore only
    # be completed by an entry whose id agrees (or by a legacy entry with no id
    # at all).
    if row_fid:
        dated = [c for c in dated
                 if not _fixture_identity(c) or _fixture_identity(c) == row_fid]
        if not dated:
            return None

    if len(dated) == 1:
        return dated[0]

    # Same loose name key with several candidates (U19 vs senior, two matches
    # between the same clubs on one day): break the tie with the
    # qualifier-preserving key. Exactly one survivor is a confident match;
    # anything else is genuinely ambiguous and returns PENDING rather than an
    # arbitrary pick.
    exact = strict_map.get(get_strict_match_key(fix_name)) or []
    survivors = [c for c in dated if any(c is s for s in exact)]
    return survivors[0] if len(survivors) == 1 else None


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

    MATCHING PRIORITY (Batch D — fixture id is the authoritative identity):
      1. EXACT fixture id (globally unique; no date check needed). If two
         contradictory FINISHED results share one id the id is declared
         ambiguous and the row stays unmatched rather than being graded
         against an arbitrary result.
      2. NAME FALLBACK, only when identity is missing on at least one side
         (the row has no usable id, or the candidate entry has none) AND the
         dates agree when both are known. Within the fallback:
           2a. one candidate surviving the date/id filter -> match
           2b. several candidates (e.g. "Napoli U19 vs Arsenal U19" and
               "Napoli vs Arsenal" share one qualifier-stripped key) -> the
               qualifier-preserving key must select exactly one, otherwise
               the row is AMBIGUOUS -> unmatched
      3. Otherwise UNMATCHED -> the row settles to SCHEDULED/PENDING. A
         fixture from another date, or a different fixture id, is never
         accepted merely because the team names match.
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

    # ── UNIVERSE INDEXED BY FIXTURE ID (authoritative identity) ───────────
    # `_merge_identified_fixture` keeps the archive/live priority below and
    # refuses to silently choose between two contradictory finished results.
    id_map = {}
    ambiguous_ids = set()
    for fx in std_db:
        _merge_identified_fixture(id_map, ambiguous_ids, _fixture_identity(fx), fx)

    # ── FT RESULT SNAPSHOT (new layer between live and archive) ────────────
    # This fills the gap: LIVE → FT → SportMonks removes fixture from feed →
    # nightly archive hasn't run yet → snapshot preserves the result.
    # Priority: FT snapshot FINISHED > live UNFINISHED (same as archive priority)
    if date_str:
        ft_snapshot = load_ft_snapshot(date_str)
        for fid, fx in ft_snapshot.items():
            live_fx = id_map.get(fid)
            if fx.get("is_finished") or live_fx is None:
                _merge_identified_fixture(id_map, ambiguous_ids,
                                          _fixture_identity(fx) or fid, fx)

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
                _merge_identified_fixture(id_map, ambiguous_ids,
                                          _fixture_identity(fx) or fid, fx)

    # ── NAME INDEX (fallback identity only) ────────────────────────────────
    # Built from the MERGED, id-deduplicated universe so a fixture can never be
    # indexed twice under its own name, plus any live entry that carries no
    # fixture id at all (names are the only identity those rows have).
    name_map = {}
    strict_map = {}
    for fx in id_map.values():
        _add_name_candidate(name_map, strict_map, fx)
    for fx in std_db:
        if not _fixture_identity(fx):
            _add_name_candidate(name_map, strict_map, fx)

    enriched = []
    for row in predictions:
        rec = dict(row)
        fid = _usable_fixture_id(rec.get("fixture_id") or rec.get("id"))
        fix_name = str(rec.get("fixture") or rec.get("Fixture") or rec.get("Match") or "")

        # 1. Match by fixture_id first (globally unique — no date check needed).
        #    A placeholder id ("N/A") counts as NO identity, which keeps those
        #    rows on the name fallback instead of blocking them.
        matched = id_map.get(fid) if fid else None

        # 2. Fallback to clean_n match key — DATE-CONSTRAINED and
        #    identity-guarded.
        #    The name key is not unique across dates, so a historical row must
        #    never be satisfied by an identically named fixture of another day
        #    (same clubs meet weekly, and the live feed only ever contains
        #    *today's* matches). When both sides carry a kickoff date, exact
        #    agreement is required; entries without a date (legacy cached
        #    payloads) keep the permissive behaviour so the 3ffe1f5 name
        #    matching is never weakened for existing data. Inside
        #    `_match_by_name` a row that HAS a real fixture id can no longer be
        #    completed by an entry carrying a DIFFERENT id, and a name key with
        #    two candidates (a U19 and a senior match between the same clubs) is
        #    only accepted when the qualifier-preserving key selects exactly one
        #    — otherwise the row stays unmatched/PENDING. A row whose own id was
        #    declared ambiguous never falls back to a name guess.
        if not matched and fix_name and not (fid and fid in ambiguous_ids):
            matched = _match_by_name(name_map, strict_map, fix_name, fid, rec, date_str)

        # Attach verification object to row
        rec["verification"] = grade_row(market_type, rec, matched)
        enriched.append(rec)

    return enriched
