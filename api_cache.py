"""
api_cache.py — AlienEdge GLOBAL API CACHE / TRAFFIC WARDEN (umbrella layer).

WHAT THIS IS
------------
This is the single, application-wide SportMonks traffic-protection layer. It is
NOT a Weekly cache, NOT a DNA cache and NOT a fixture-only cache: every engine
and every acquisition path in the pre-match process goes through `smart_get`,
which is installed over `requests.get` by main.py exactly as before:

    Engine A -> global cache
    Engine B -> global cache
    Engine C -> global cache
    shared future-fixture acquisition -> global cache
                                        -> SportMonks (only on a real miss)

WHAT WAS PRESERVED FROM main.py (deliberately unchanged)
-------------------------------------------------------
  * `GLOBAL_API_CACHE` — the same dict object, same name, values are raw JSON
    payloads exactly as before.
  * `smart_get(url, params=None, **kwargs)` — identical signature and identical
    cache-key string (`url?sorted&params` minus api_token).
  * `CachedResponseWrapper` — same class, same constructor semantics (extra
    optional args are additive).
  * 🟨 = cache hit, 🟩 = real API call, and the 0.25 s pacing after a real 200.
  * a successful 200 is cached; non-200 responses never are.

WHAT WAS ADDED (all additive, none of it weakens a protection)
-------------------------------------------------------------
  1. per-resource TTL          — `_ttl_for_path()`; live endpoints are never
                                 cached here (TTL 0) so the Live freshness model
                                 cannot be affected by this layer.
  2. a bounded cache           — `MAX_ENTRIES`, oldest-first eviction, so the
                                 cache can never grow without limit.
  3. canonical superset ALIASING — a narrower request may be answered from a
                                 cached superset, but ONLY through the strict
                                 safety gate in api_request_identity
                                 (same path + same identity params + include
                                 coverage + page match + structural containment).
                                 Unsafe aliases are refused, not guessed.
  4. the shared 429 cooldown   — `Retry-After` / `X-RateLimit-Reset` aware,
                                 bounded jittered backoff, and participation in
                                 the EXISTING cross-process cooldown file
                                 `data/api_429_cooldown.lock` (same format and
                                 same file the archiver and live stages use).
                                 No second rate limiter is introduced.
  5. the canonical future-fixture window — after an in-memory miss, an eligible
                                 `/fixtures/date/{date}` request may be served
                                 from the shared 7-day future-fixture store
                                 (0 API calls), using the same safety gate.
  6. counters                  — hit / alias / window / miss per resource class,
                                 reported compactly at flush time.
"""

import gc
import json
import os
import random
import time
import traceback

import requests

import api_request_identity as rid

# ══════════════════════════════════════════════════════════════════════════════
# 1. THE CACHE (identical object identity + value shape to the original)
# ═════════════════════════════════════════════════════════════════════════════
GLOBAL_API_CACHE = {}
_original_get = requests.get

# Kept under the historical name as well: the original main.py called the
# captured real getter `original_get`, and other code may still reference it.
original_get = _original_get

# cache_key -> meta {path, identity, include, exclude, params, ts, ttl, headers,
#                    status, url}
_API_CACHE_META = {}
# (path, identity) -> {cache_key, ...} — bounded bucket index for alias lookups
_ALIAS_INDEX = {}

MAX_ENTRIES = 2000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GATE_LOCK_FILE = os.path.join(BASE_DIR, "data", "api_429_cooldown.lock")


class CachedResponseWrapper:
    """
    Mimics enough of requests.Response that a cache HIT behaves the same as
    a real HTTP response to whatever engine code consumes it (see the original
    main.py docstring: .text/.content/.headers/.ok/.elapsed are all covered so
    a cache hit can never raise AttributeError deep inside engine code).

    `headers` / `url` / `elapsed` are optional and default to the original
    behaviour, so existing callers are unaffected; when the layer has them it
    restores them (which is what lets Retry-After-aware code keep working even
    when the response was served from cache).
    """
    def __init__(self, json_data, status_code=200, headers=None, url=None,
                 elapsed=None, from_cache=True):
        self._json_data = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.headers = headers if headers is not None else {}
        self.elapsed = elapsed
        self.reason = "OK" if self.ok else "Cached-Error"
        self.url = url
        self.from_cache = from_cache
        try:
            self._text = json.dumps(json_data)
        except Exception:
            self._text = str(json_data)

    def json(self):
        return self._json_data

    @property
    def text(self):
        return self._text

    @property
    def content(self):
        return self._text.encode("utf-8")

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Error (cached)", response=self
            )


# ═════════════════════════════════════════════════════════════════════════════
# 2. PER-RESOURCE TTL (data-aware freshness, not one arbitrary TTL)
# ════════════════════════════════════════════════════════════════════════════
# Resolution: first matching prefix wins. Rationale per class:
#   /livescores/*            TTL 0  — Live owns its freshness (120 s in
#                                     live_cache.py). This pre-match layer must
#                                     never cache or serve live score data.
#   /odds/pre-match/         15 min — volatile by nature; the 900 s value is the
#                                     SAME number live_cache.py already uses for
#                                     pre-match odds/lineups (PREMATCH_TTL).
#   /fixtures/date/{date}    1 h    — fixture identity/schedule is stable once
#                                     published; odds are NOT included here.
#   /fixtures/between/...    6 h    — completed-match history (stable after FT)
#   /fixtures/head-to-head/  6 h    — same, historical results
#   /standings/              6 h    — standings move only when matches finish
#   /teams|leagues|seasons|stages|venues|countries  24 h — reference data
#   anything else            15 min — conservative default
_TTL_RULES = (
    ("/livescores", 0),
    ("/odds/pre-match/", 900),
    ("/fixtures/date/", 3600),
    ("/fixtures/between/", 21600),
    ("/fixtures/head-to-head/", 21600),
    ("/standings/", 21600),
    ("/teams/", 86400),
    ("/leagues/", 86400),
    ("/seasons/", 86400),
    ("/stages/", 86400),
    ("/venues/", 86400),
    ("/countries/", 86400),
)
DEFAULT_TTL = 900


def _ttl_for_path(path):
    for prefix, ttl in _TTL_RULES:
        if str(path).startswith(prefix):
            return ttl
    return DEFAULT_TTL


def _resource_class(path):
    """Coarse bucket used for the compact flush-time counter report."""
    for prefix in ("/livescores", "/odds/pre-match/", "/fixtures/date/",
                   "/fixtures/between/", "/fixtures/head-to-head/",
                   "/standings/", "/teams/", "/leagues/"):
        if str(path).startswith(prefix):
            tail = prefix.strip("/").split("/")
            return tail[0]
    return "other"


# ═════════════════════════════════════════════════════════════════════════════
# 3. COUNTERS (measurement — this is how API savings are PROVEN, not claimed)
# ═════════════════════════════════════════════════════════════════════════════
STATS = {"hit": 0, "alias": 0, "window": 0, "miss": 0, "api": 0, "refused": 0}
STATS_BY_CLASS = {}


def _count(kind, path):
    STATS[kind] = STATS.get(kind, 0) + 1
    cls = _resource_class(path)
    bucket = STATS_BY_CLASS.setdefault(cls, {})
    bucket[kind] = bucket.get(kind, 0) + 1


def stats_line():
    """One compact line describing what the umbrella cache did this generation."""
    if not any(STATS.get(k) for k in ("hit", "alias", "window", "miss")):
        return None
    parts = []
    for cls, bucket in sorted(STATS_BY_CLASS.items()):
        seg = "/".join(f"{k}:{bucket[k]}" for k in
                       ("api", "hit", "alias", "window", "miss") if bucket.get(k))
        parts.append(f"{cls}[{seg}]")
    return ("[API CACHE] api={api} exact_hits={hit} alias_hits={alias} "
            "window_hits={window} misses={miss} alias_refused={refused} | {}"
            ).format(" ".join(parts), **STATS)


def _reset_stats():
    for k in list(STATS):
        STATS[k] = 0
    STATS_BY_CLASS.clear()


# ════════════════════════════════════════════════════════════════════════════
# 4. SHARED 429 COOLDOWN (the EXISTING mechanism, reused — not a second one)
# ════════════════════════════════════════════════════════════════════════════
# Same file, same JSON shape ({"until": <epoch>, "by": "<who>"}), same
# tmp+os.replace atomic write, same 45 s clamp and the same priority order as
# daily_archiver._429_gate_wait / the LIVE_SCANNER stages:
#     Retry-After > X-RateLimit-Reset > shared gate > jittered floor
# The pipeline now BROADCASTS into that shared window and PACES itself through
# it, like its sibling processes, instead of retrying blindly.
MAX_429_RETRIES = 5
GATE_WAIT_CAP = 45.0
RATE_RESET_CAP = 60.0
GATE_READ_TTL = 2.0

_gate_read = {"ts": 0.0, "remaining": 0.0}


def gate_remaining():
    """Seconds left in an ACTIVE shared cooldown window, else 0 (cheap + cached)."""
    now = time.time()
    if now - _gate_read["ts"] < GATE_READ_TTL:
        return _gate_read["remaining"]
    remaining = 0.0
    try:
        with open(GATE_LOCK_FILE, "r") as f:
            gate = json.load(f)
        remaining = max(0.0, float(gate.get("until", 0)) - now)
    except Exception:
        remaining = 0.0
    _gate_read["ts"] = now
    _gate_read["remaining"] = remaining
    return remaining


def broadcast_gate(seconds, who="smart_get"):
    """Record a cooldown so OTHER processes wait instead of re-triggering 429."""
    try:
        os.makedirs(os.path.dirname(GATE_LOCK_FILE), exist_ok=True)
        with open(GATE_LOCK_FILE + ".tmp", "w") as f:
            json.dump({"until": time.time() + seconds, "by": who}, f)
        os.replace(GATE_LOCK_FILE + ".tmp", GATE_LOCK_FILE)
        _gate_read["ts"] = 0.0  # force a re-read on the next check
    except Exception:
        pass


def gate_wait(retry_after=None, limit_reset=None, attempt=1, who="pipeline",
              broadcast=False, floor_base=2.0):
    """Wait out a SportMonks 429 using the best available signal.

    Priority: server Retry-After > X-RateLimit-Reset > shared cooldown file >
    jittered exponential floor (2s, 4s, 8s, 16s…). CLAMPED to 45 s per attempt
    (SportMonks sometimes sends ~20-minute Retry-After values; a background
    pipeline must not freeze on those). With broadcast=True the cooldown is
    published to sibling processes. Returns the seconds slept.
    """
    now = time.time()
    wait = 0.0
    shared_active = False
    try:
        wait = max(wait, float(retry_after))
    except (TypeError, ValueError):
        pass
    shared_left = gate_remaining()
    if shared_left > 0:
        shared_active = True
        wait = max(wait, shared_left)
    if isinstance(limit_reset, str) and limit_reset.isdigit():
        wait = max(wait, min(max(float(limit_reset) - now, 0.0), RATE_RESET_CAP))
    if attempt and attempt > 0:
        wait = max(wait, min(floor_base * (2 ** (attempt - 1)), 30.0))
        wait += random.random() * 1.5
    wait = min(wait, GATE_WAIT_CAP)
    if attempt is not None and attempt <= 0 and retry_after is None and not shared_active:
        return 0.0                       # pacing call with nothing to wait for
    if broadcast:
        broadcast_gate(wait, who)
    time.sleep(wait)
    return wait


# ════════════════════════════════════════════════════════════════════════════
# 5. CACHE STORAGE (bounded, TTL'd) + CANONICAL ALIAS RESOLUTION
# ════════════════════════════════════════════════════════════════════════════
def _cache_key(url, params):
    """UNCHANGED key generation from the original smart_get:
    full URL + every param except api_token, sorted for determinism."""
    safe_params = dict(params) if params else {}
    param_string = "&".join([f"{k}={v}" for k, v in sorted(safe_params.items())
                             if k != "api_token"])
    return f"{url}?{param_string}"


def _drop(key):
    GLOBAL_API_CACHE.pop(key, None)
    meta = _API_CACHE_META.pop(key, None)
    if meta:
        bucket = _ALIAS_INDEX.get((meta.get("path"), meta.get("identity")))
        if bucket is not None:
            bucket.discard(key)
            if not bucket:
                _ALIAS_INDEX.pop((meta.get("path"), meta.get("identity")), None)


def _evict_if_needed():
    while len(_API_CACHE_META) > MAX_ENTRIES:
        oldest = min(_API_CACHE_META.items(), key=lambda kv: kv[1].get("ts", 0))[0]
        _drop(oldest)


def _store(url, params, path, data, headers=None):
    """Cache a 200 body under its exact key, with its TTL and identity recorded."""
    ttl = _ttl_for_path(path)
    if ttl <= 0:
        return None                      # this layer never caches this resource
    key = _cache_key(url, params)
    GLOBAL_API_CACHE[key] = data
    _API_CACHE_META[key] = {
        "path": path,
        "params": dict(params or {}),
        "identity": rid.identity(params),
        "include": rid.include_set(params),
        "exclude": rid.exclude_set(params),
        "ts": time.time(),
        "ttl": ttl,
        "headers": headers or {},
    }
    _ALIAS_INDEX.setdefault((path, rid.identity(params)), set()).add(key)
    _evict_if_needed()
    return key


def _get_entry(key):
    """(data, meta) for a live (non-expired) entry, else None."""
    meta = _API_CACHE_META.get(key)
    if meta is None:
        return None
    data = GLOBAL_API_CACHE.get(key)
    if data is None:
        _drop(key)
        return None
    ttl = meta.get("ttl", DEFAULT_TTL)
    if ttl <= 0 or (time.time() - meta.get("ts", 0.0)) > ttl:
        _drop(key)                       # expired -> evicted
        return None
    return data, meta


def _lookup_alias(path, params):
    """Answer a narrower request from a cached SUPERSET of the same resource.

    Only entries recorded under the SAME (path, identity) bucket are considered,
    and each candidate still has to pass the full safety gate in
    api_request_identity.request_can_be_served (include coverage + page match +
    structural containment). Returns (data, meta) or None.
    """
    bucket = _ALIAS_INDEX.get((path, rid.identity(params)))
    if not bucket:
        return None
    for key in list(bucket):
        entry = _get_entry(key)
        if entry is None:
            continue
        data, meta = entry
        ok, _reason = rid.request_can_be_served(
            data, meta.get("params"), path, params, cached_path=meta.get("path"))
        if ok:
            return data, meta
        _count("refused", path)
    return None


def _lookup_window(path, params):
    """Ask the shared future-fixture window for this request (0 API calls).

    Only /fixtures/date/{date} requests for a date held in the canonical 7-day
    window can be served, and only through the same strict safety gate. The
    window module is imported lazily so this layer keeps working (and stays
    importable) even when the window has never been filled.
    """
    if not str(path).startswith("/fixtures/date/"):
        return None
    try:
        import shared_fixture_window as window
    except Exception:
        return None
    if window.is_fetching():
        return None
    return window.lookup_for_request(path, params)


# ════════════════════════════════════════════════════════════════════════════
# 6. SMART_GET — the hijack every engine calls (signature unchanged)
# ════════════════════════════════════════════════════════════════════════════
# Resolution order, cheapest first:
#   1. exact cache hit            🟨   0 API calls
#   2. canonical superset alias   🟦   0 API calls (strict safety gate)
#   3. shared future window       🟪   0 API calls (fixtures/date only)
#   4. real SportMonks call       🟩   the only path that spends quota
BURST_FLOOR_BASE = 3.0      # >= the old 3.0/4.5/6.75/10.1/15.2 s ladder
GATE_PACING_CAP = 60.0      # max seconds smart_get sleeps waiting out a shared
                            # cooldown before it attempts the request anyway


def smart_get(url, params=None, **kwargs):
    path = rid.request_path(url)
    cache_key = _cache_key(url, params)

    entry = _get_entry(cache_key)
    if entry is not None:
        data, meta = entry
        _count("hit", path)
        print("🟨", end="", flush=True)
        return CachedResponseWrapper(data, 200, headers=meta.get("headers"), url=url)

    aliased = _lookup_alias(path, params)
    if aliased is not None:
        data, meta = aliased
        _count("alias", path)
        print("🟦", end="", flush=True)
        return CachedResponseWrapper(data, 200, headers=meta.get("headers"), url=url)

    windowed = _lookup_window(path, params)
    if windowed is not None:
        _count("window", path)
        print("🟪", end="", flush=True)
        # Remember it as a normal entry so repeats are exact hits.
        _store(url, params, path, windowed)
        return CachedResponseWrapper(windowed, 200, url=url)

    _count("miss", path)

    # Pacing: wait out an ACTIVE shared cooldown before spending a request.
    # Two guards keep a storm from starving the pipeline to death:
    #   * JITTER — every process used to read the same gate expiry and wake on
    #     the same second, re-firing in lockstep and re-arming the gate forever
    #     (the observed "cooling circle": one 12h run logged 1,352 × 30s
    #     pacing sleeps ≈ 11h of pure sleep). A small per-call random offset
    #     staggers the wake-ups so siblings no longer collide.
    #   * CAP — at most GATE_PACING_CAP seconds per request; after that the
    #     request is attempted anyway and the server's 429 (with its own
    #     server-side backoff) decides, instead of this process sleeping
    #     forever without ever reaching the wire.
    left = gate_remaining()
    if left > 0:
        pace = min(left, GATE_PACING_CAP) + random.random() * 4.0
        print(f"[API GATE] smart_get: shared cooldown active — pacing {pace:.0f}s ",
              end="", flush=True)
        time.sleep(pace)

    for attempt in range(MAX_429_RETRIES):
        try:
            resp = _original_get(url, params=params, **kwargs)
            if resp.status_code == 200:
                # GATE HYGIENE: a 200 proves the burst window is over — disarm
                # the shared cooldown so sibling processes stop pacing against
                # a stale expiry the moment the provider is serving again.
                broadcast_gate(0, f"cleared:{os.getpid()}")
                data = resp.json()
                try:
                    headers = dict(getattr(resp, "headers", None) or {})
                except Exception:
                    headers = {}
                _store(url, params, path, data, headers=headers)
                _count("api", path)
                print("🟩", end="", flush=True)
                # Deliberate pacing to respect SportMonks per-minute burst boundaries
                time.sleep(0.25)
                return CachedResponseWrapper(data, 200, headers=headers, url=url,
                                             elapsed=getattr(resp, "elapsed", None),
                                             from_cache=False)
            elif resp.status_code == 429:
                wait = gate_wait(
                    retry_after=getattr(resp, "headers", {}).get("Retry-After"),
                    limit_reset=getattr(resp, "headers", {}).get("X-RateLimit-Reset"),
                    attempt=attempt + 1, who="pipeline", broadcast=True,
                    floor_base=BURST_FLOOR_BASE)
                print(f"[API BURST: Cooling {wait:.1f}s] ", end="", flush=True)
                continue
            elif resp.status_code in (401, 403):
                # Auth/subscription failure: retrying cannot help and would
                # only hammer the provider; return the failure as-is (callers
                # treat a non-200 as a FAILED acquisition, which the feed
                # write guard keeps from destroying good data).
                print(f"[API AUTH] provider returned {resp.status_code} for {path} "
                      "— subscription/quota problem, not retrying")
                return resp
            else:
                return resp
        except Exception:
            time.sleep(1.5)
            continue

    return _original_get(url, params=params, **kwargs)


# ════════════════════════════════════════════════════════════════════════════
# 7. MEMORY RESET + INSTALL
# ════════════════════════════════════════════════════════════════════════════
def flush_memory(report=True):
    """Clear every in-memory structure this layer owns.

    Identical memory semantics to the original `flush_system_ram()` (which
    cleared GLOBAL_API_CACHE to permanently eliminate OOM kills) — it now also
    clears the metadata/alias index (so no stale alias can ever point at a
    cleared payload) and releases the window's in-memory day copy. The on-disk
    canonical window is NOT touched: it is the durable store, which is what lets
    cross-generation requests still be served with 0 API calls.
    """
    GLOBAL_API_CACHE.clear()
    _API_CACHE_META.clear()
    _ALIAS_INDEX.clear()
    _gate_read["ts"] = 0.0
    try:
        import shared_fixture_window as window
        window.release_memory()
    except Exception:
        pass
    if report:
        line = stats_line()
        if line:
            print(line, flush=True)
    _reset_stats()


def install():
    """Install the traffic warden over requests.get (exactly as main.py did)."""
    requests.get = smart_get
    print("✅ TRAFFIC WARDEN ACTIVE: Global API Hijack & Managed Cache Synchronized.")
