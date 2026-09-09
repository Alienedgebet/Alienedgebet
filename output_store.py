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


def to_jsonable(x):
    """Convert engine return values (DataFrame / tuple / list / dict) into
    something json.dump can serialize, without losing structure."""
    try:
        import pandas as pd
        if isinstance(x, pd.DataFrame):
            return x.to_dict("records")
    except ImportError:
        pass
    if isinstance(x, tuple):
        return [to_jsonable(v) for v in x]
    return x


def save(key: str, date: str, data, status: str = "ok", error: str = None) -> str:
    """Atomically writes one engine's result. `date=None` for the two
    no-date engines (win_apex, gg_precision_filter) — those save under
    the '__latest' suffix instead.

    `status`/`error` let a caller record a FAILED run explicitly (see
    `save_failure()` below) instead of a failure looking identical to an
    engine that legitimately returned zero rows for a quiet day."""
    path = _path(key, date)
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
        json.dump(payload, f, cls=SafeEncoder, ensure_ascii=False)
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
        return data, payload.get("generated_at")
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
