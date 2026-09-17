"""
output_store.py — the single source of truth for where engine output lives.

WHY THIS FILE EXISTS
---------------------
The old architecture broke because the API guessed which CSV/JSON filename
each engine had written ("candidate paths" lists), and that guess drifted
out of sync with what the engines actually wrote over time. That caused
stale dates, missing fields, and pages stuck on mock data.

This file is the fix: it is the ONLY code that knows the on-disk filename
convention. `main.py` (the writer) calls `save()`. `api/main.py` (the
reader) calls `load()`. Both import this one module, so the filename
convention can never drift between them — there is no second copy of the
naming logic to fall out of sync.

Convention: output/cache/{engine_key}__{date-or-'latest'}.json
Every file is a small JSON envelope: {engine_key, date, generated_at, data}.
Writes are atomic (write to .tmp, then os.replace) so the API can never read
a half-written file while main.py is mid-run.
"""

import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "output", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


class SafeEncoder(json.JSONEncoder):
    """Handles numpy/pandas types that engines commonly return without
    every engine needing to remember to convert them itself."""

    def default(self, o):
        try:
            import numpy as np
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                return float(o) if not np.isnan(o) else None
            if isinstance(o, np.ndarray):
                return o.tolist()
            if isinstance(o, np.bool_):
                return bool(o)
        except ImportError:
            pass
        try:
            import pandas as pd
            if isinstance(o, pd.DataFrame):
                return o.to_dict("records")
            if isinstance(o, pd.Series):
                return o.to_dict()
            if isinstance(o, pd.Timestamp):
                return o.isoformat()
        except ImportError:
            pass
        if hasattr(o, "item"):
            try:
                return o.item()
            except Exception:
                pass
        return str(o)


def _path(key: str, date: str = None) -> str:
    suffix = date if date else "latest"
    safe_key = key.replace("/", "_").replace(" ", "_")
    return os.path.join(CACHE_DIR, f"{safe_key}__{suffix}.json")


def sanitize_non_finite(obj):
    """Recursively convert non-finite floats (NaN, +Inf, -Inf) to None so a
    payload is always strictly JSON-compliant.

    Finite numbers, strings, booleans and all other legitimate values are
    returned UNCHANGED. This is the single serving/write boundary that keeps
    every engine file (including historical ones written with raw NaN
    literals) serializable by FastAPI's `allow_nan=False` JSON encoder and
    by the browser's JSON.parse."""
    import math

    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_non_finite(v) for v in obj]
    return obj


def to_jsonable(x):
    """Convert engine return values (DataFrame / tuple / list / dict) into
    something json.dump can serialize, without losing structure. Non-finite
    floats are sanitized to None here so future pipeline runs can never
    persist NaN/Infinity into a cache file."""
    try:
        import pandas as pd
        if isinstance(x, pd.DataFrame):
            x = x.to_dict("records")
    except ImportError:
        pass
    if isinstance(x, tuple):
        x = [to_jsonable(v) for v in x]
    return sanitize_non_finite(x)


def save(key: str, date: str, data, status: str = "ok", error: str = None,
         guard: bool = False) -> str:
    """Atomically writes one engine's result. `date=None` is only for engines
    whose payload is genuinely cross-day (win_apex) — those save under the
    '__latest' suffix instead. Every date-scoped engine (every market filter,
    including filter_gg) passes its own date, so its snapshot is guarded.

    `status`/`error` let a caller record a FAILED run explicitly (see
    `save_failure()` below) instead of a failure looking identical to an
    engine that legitimately returned zero rows for a quiet day.

    `guard=True` is OPT-IN and only meaningful for date-scoped writes: it
    refuses to replace an existing same-date snapshot with a suspiciously
    collapsed fixture universe (see the SNAPSHOT GUARD block above). On REJECT
    the existing file is left byte-for-byte untouched and its path is returned
    unchanged, so callers keep the exact same contract."""
    path = _path(key, date)
    if (guard and status == "ok" and data is not None and date
            and key not in COLLAPSE_GUARD_EXEMPT_KEYS):
        if guard_same_date_snapshot(key, date, data)["decision"] == "REJECT":
            return path  # existing snapshot preserved; nothing rewritten
    payload = {
        "engine_key": key,
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "status": status,       # "ok" | "failed"
        "error": error,
        "row_count": _row_count(data),
        "data": to_jsonable(data),
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, cls=SafeEncoder, ensure_ascii=False, allow_nan=False)
    os.replace(tmp_path, path)  # atomic — readers never see a partial file
    return path


def save_failure(key: str, date: str, error: str) -> str:
    """Records that an engine THREW rather than returned empty. Used by
    main.py's _safe_exec so /api/status/{date} can distinguish
    'never ran' / 'ran and failed' / 'ran and succeeded' instead of every
    non-success case looking like a silent empty list."""
    return save(key, date, data=None, status="failed", error=error)


def _row_count(data) -> int:
    j = to_jsonable(data)
    if isinstance(j, list):
        return len(j)
    if isinstance(j, dict):
        return sum(_row_count(v) for v in j.values() if isinstance(v, (list, dict))) or len(j)
    return 0 if j is None else 1


# ─ SAME-DATE SNAPSHOT COLLAPSE GUARD (Batch A) ──────────────────────────────
# A date-scoped cache file IS that date's universe for every reader. On
# 2026-09-15 the evening run fetched only the 3 fixtures the date endpoint still
# returned after the day's other ~60 matches had finished, and each engine's
# save() then unconditionally replaced the 63-fixture morning snapshot with a
# 3-fixture one — same key, same filename — while the run still reported SUCCESS.
# The good snapshot was unrecoverable.
#
# The guard compares FIXTURE IDENTITY (unique fixture ids), never row counts.
# Row counts are meaningless as a universe measure: win forecast emits two rows
# per fixture (home + away), an aggregator emits one, corners may emit none on a
# quiet day, and the rolling GG filter spans 7 days. Fixture ids are the one
# identity every layer already agrees on, so a collapse is judged only by id sets.
#
# It is OPT-IN via save(..., guard=True), it only can fire when a same-date file
# already exists, and it never invents storage: on REJECT the existing file is
# left exactly as it is and the rejection is logged.
UNIVERSE_MIN_EXISTING = 8     # an existing universe below this is never "known-good"
UNIVERSE_REJECT_RATIO = 0.25  # a new universe must exceed existing * ratio to be kept

# Keys exempt from the guard — currently EMPTY: every key the pipeline writes is
# date-scoped, so every same-date snapshot is protectable. filter_gg was listed
# here because its rows were once aggregated from the last 7 days of GG master
# history instead of from the requested date. FILTER/gg_precision_filter.py is
# now a single-date layer over ALIENEDGE_GG_PICKS_{date}.csv, so its rows ARE the
# run's date universe — skipping it would let a collapsed/empty GG run replace a
# good dated snapshot. Kept as a named constant (rather than deleted) so a future
# genuinely cross-day key has one obvious, reviewed place to be declared.
COLLAPSE_GUARD_EXEMPT_KEYS = set()

_COLLAPSE_GUARD_REJECTIONS = []  # in-process diagnostics for the current run only


def _norm_field_name(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def fixture_universe(data) -> set:
    """Unique fixture ids anywhere in an engine payload — the primary identity.

    Only keys normalising to 'fixtureid'/'fixtureids' count. Team names are
    deliberately NOT used: normalised names collide across dates, which is the
    same collision that mis-graded a historical Falkirk v Hearts row. A payload
    carrying no fixture identity at all (dna, psychology tables, ...) yields an
    EMPTY set, which makes the guard a no-op for that key instead of guessing.
    """
    found = set()

    def _take(value):
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _take(item)
        elif value is None or isinstance(value, (dict, bool)):
            return
        else:
            text = str(value).strip()
            if text:
                found.add(text)

    def _walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if _norm_field_name(key) in ("fixtureid", "fixtureids"):
                    _take(value)
                else:
                    _walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item)

    _walk(data)
    return found


def existing_fixture_universe(key: str, date: str = None) -> set:
    """Fixture ids already stored in this key's same-date snapshot. Reads through
    load(), so a missing / failed / unreadable file yields an empty set (guard
    ALLOW) rather than raising."""
    data, _ = load(key, date)
    return fixture_universe(data)


def collapse_decision(existing_ids, new_ids) -> dict:
    """The single definition of 'suspiciously collapsed'. Pure — no I/O — so the
    cache writer (save) and the archiver (daily_archiver.py) share one rule and
    cannot drift apart."""
    existing_n, new_n = len(existing_ids), len(new_ids)
    base = {"existing_fixtures": existing_n, "new_fixtures": new_n}
    if existing_n == 0:
        return dict(base, decision="ALLOW", reason="no existing fixture universe to protect")
    if existing_n < UNIVERSE_MIN_EXISTING:
        return dict(base, decision="ALLOW",
                    reason=f"existing universe below protection floor ({UNIVERSE_MIN_EXISTING})")
    if new_n <= int(existing_n * UNIVERSE_REJECT_RATIO):
        return dict(base, decision="REJECT", reason="suspicious fixture-universe collapse")
    return dict(base, decision="ALLOW", reason="new universe is not a collapse")


def guard_rejections() -> list:
    """Rejections recorded in THIS process (empty for a clean run). main.py uses
    this to exit non-zero so a run that had to discard collapsed snapshots can
    never look green in systemd."""
    return list(_COLLAPSE_GUARD_REJECTIONS)


def guard_same_date_snapshot(key, date, data) -> dict:
    """Guard decision for one prospective same-date write; save() only skips the
    write when it says REJECT. Returns ALLOW without inspecting `data` whenever
    the existing snapshot holds no protectable fixture universe, so a genuinely
    small date still snapshots normally and no engine is ever judged on row
    count."""
    existing_ids = existing_fixture_universe(key, date)
    if len(existing_ids) < UNIVERSE_MIN_EXISTING:
        return {"decision": "ALLOW", "existing_fixtures": len(existing_ids),
                "new_fixtures": None,
                "reason": f"existing universe below protection floor ({UNIVERSE_MIN_EXISTING})"}
    decision = collapse_decision(existing_ids, fixture_universe(to_jsonable(data)))
    if decision["decision"] == "REJECT":
        _COLLAPSE_GUARD_REJECTIONS.append({
            "date": date, "key": key,
            "existing_fixtures": decision["existing_fixtures"],
            "new_fixtures": decision["new_fixtures"],
            "reason": decision["reason"],
        })
        print(f"[SNAPSHOT GUARD] date={date} key={key} "
              f"existing_fixtures={decision['existing_fixtures']} "
              f"new_fixtures={decision['new_fixtures']} "
              f"decision=REJECT reason={decision['reason']} "
              f"existing_snapshot_preserved=true")
    return decision


def load(key: str, date: str = None, default=None):
    """Returns (data, generated_at_iso_or_None). Never raises — a missing
    file (engine hasn't run for that date yet) returns (default, None).
    A FAILED run also returns `default` here (its `data` field is None) so
    routes never accidentally serve a null payload — check load_status()
    if you need to tell 'missing' apart from 'failed'."""
    path = _path(key, date)
    if not os.path.exists(path):
        return default, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        data = payload.get("data")
        if data is None:
            data = default
        # Historical files may contain raw NaN/Infinity literals. Sanitize at
        # the read boundary so every route can serve them as strict JSON
        # (FastAPI serializes with allow_nan=False) without touching the file.
        return sanitize_non_finite(data), payload.get("generated_at")
    except Exception:
        return default, None


def load_status(key: str, date: str = None) -> dict:
    """Full status for one engine/date: missing | ok | failed, plus
    generated_at, row_count and the error message if it failed."""
    path = _path(key, date)
    if not os.path.exists(path):
        return {"status": "missing", "generated_at": None, "row_count": 0, "error": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return {
            "status": payload.get("status", "ok"),
            "generated_at": payload.get("generated_at"),
            "row_count": payload.get("row_count", 0),
            "error": payload.get("error"),
        }
    except Exception as e:
        return {"status": "unreadable", "generated_at": None, "row_count": 0, "error": str(e)}


def status_for_date(date: str, keys: list[str]) -> dict:
    """Freshness + success/failure report for every engine key on a given
    date — used by the /api/status/{date} ops endpoint, not by the picks
    endpoints. This is now the first place to check when a page shows
    Demo data: 'missing' = pipeline hasn't reached it yet, 'failed' = it
    ran and threw, 'ok' with row_count=0 = it genuinely ran dry today."""
    return {key: load_status(key, date) for key in keys}
