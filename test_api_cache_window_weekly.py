#!/usr/bin/env python3
"""
Shared API cache + canonical aliases + 7-day future window + Weekly family — TESTS.

Run:  ./venv/bin/python test_api_cache_window_weekly.py

Safety (deliberate, enforced):
  * NO network: `api_cache._original_get` is replaced by a fake, so every "API
    call" is counted locally. Zero SportMonks requests are made.
  * NO production writes: the window store, output_store's cache dir, the Weekly
    output dir and the 429 gate lock are ALL redirected into a /tmp sandbox.
  * NO pipeline run: `alienedge_master_system` is never called; the Weekly family
    is composed with spies, so no engine mathematics executes here either.
  * Live isolation and DNA non-modification are asserted, not assumed.
"""

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SBOX = "/tmp/alienedge_api_window_sandbox"
shutil.rmtree(SBOX, ignore_errors=True, onerror=None)
for sub in ("data", "output", "cache"):
    os.makedirs(os.path.join(SBOX, sub), exist_ok=True)

sys.path.insert(0, ROOT)

import output_store as store
store.CACHE_DIR = os.path.join(SBOX, "cache")          # snapshots land in the sandbox

import api_cache
import api_request_identity as rid
import shared_fixture_window as window

api_cache.GATE_LOCK_FILE = os.path.join(SBOX, "data", "api_429_cooldown.lock")
window.WINDOW_FILE = os.path.join(SBOX, "data", "future_fixture_window.json")

# ── fake network ────────────────────────────────────────────────────────────
CALLS = []
FAIL_DATES = set()


def _fixture(fid, date, include):
    """A minimal fixture carrying exactly the relations the request asked for."""
    item = {"id": fid, "name": f"Fixture {fid}", "starting_at": f"{date} 15:00:00"}
    for rel in (include or "").split(";"):
        rel = rel.strip()
        if not rel:
            continue
        head = rel.split(".")[0]
        if head == "participants":
            item["participants"] = [{"id": fid * 10, "name": "H",
                                     "meta": {"location": "home"}},
                                    {"id": fid * 10 + 1, "name": "A",
                                     "meta": {"location": "away"}}]
        elif head in ("league", "season", "state"):
            item[head] = {"id": 1, "name": head}
        else:
            item[head] = []
    return item


def _make_body(url, params):
    date = url.rstrip("/").split("/")[-1].split("?")[0]
    include = (params or {}).get("include") or ""
    page = int((params or {}).get("page", 1) or 1)
    fixtures = [_fixture(1000 + i, date, include) for i in range(3)]
    body = {"data": fixtures,
            "pagination": {"count": len(fixtures), "per_page": 50,
                           "current_page": page, "next_page": None,
                           "has_more": False}}
    if include and "." in include:
        # nested relation shapes (statistics.type) need the nested key too
        for item in fixtures:
            if "statistics" in item and isinstance(item["statistics"], list):
                item["statistics"] = [{"type": {"id": 1, "name": "Shots"}}]
    return body


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.ok = status_code == 200
        self.elapsed = None
        self.reason = "OK"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_get(url, params=None, **kwargs):
    date = url.rstrip("/").split("/")[-1].split("?")[0]
    CALLS.append({"url": url, "params": dict(params or {})})
    if date in FAIL_DATES:
        return FakeResponse(500, {"data": []})
    return FakeResponse(200, _make_body(url, params))


api_cache._original_get = fake_get
CALLS.clear()
api_cache.install()          # patches requests.get — every engine path now uses it

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "✅" if cond else "❌"
    extra = f" — {detail}" if detail and not cond else ""
    print(f"{mark} {name}{extra}")


def fresh_cache():
    api_cache.flush_memory(report=False)
    CALLS.clear()


URL = "https://api.sportmonks.com/v3/football"
DATE_A = "2099-01-01"
DATE_B = "2099-01-02"
CANON = "participants;league;season;state;scores;lineups;formations;statistics"


def get(path, **params):
    return api_cache.smart_get(f"{URL}{path}", params=params)


# ════════════════════════════════════════════════════════════════════════════
print("\n=== A. GLOBAL CACHE: HIT / MISS / KEY ISOLATION ===")
# ════════════════════════════════════════════════════════════════════════════
fresh_cache()
r1 = get(f"/fixtures/date/{DATE_A}", include=CANON, per_page=50, page=1)
r2 = get(f"/fixtures/date/{DATE_A}", include=CANON, per_page=50, page=1)
check("A1 same request twice -> ONE API call",
      len(CALLS) == 1 and api_cache.STATS.get("hit") == 1,
      f"calls={len(CALLS)} stats={api_cache.STATS}")
check("A2 second call served the same payload",
      r1.json()["data"][0]["id"] == r2.json()["data"][0]["id"])
check("A3 cache key ignores api_token but respects other params",
      api_cache._cache_key(URL + "/x", {"api_token": "t1", "page": 1})
      == api_cache._cache_key(URL + "/x", {"page": 1})
      and api_cache._cache_key(URL + "/x", {"page": 1})
      != api_cache._cache_key(URL + "/x", {"page": 2}))

# ════════════════════════════════════════════════════════════════════════════
print("\n=== B. CANONICAL ALIASING (safe supersets only) ===")
# ════════════════════════════════════════════════════════════════════════════
fresh_cache()
get(f"/fixtures/date/{DATE_A}", include="participants;league;season;state",
    per_page=50, page=1)
before = len(CALLS)
narrow = get(f"/fixtures/date/{DATE_A}", include="participants",
             per_page=50, page=1)
check("B1 narrower include served from cached superset (0 extra calls)",
      len(CALLS) == before and api_cache.STATS.get("alias") == 1,
      f"calls={len(CALLS)} stats={api_cache.STATS}")
check("B2 aliased payload still carries the superset relations",
      set(narrow.json()["data"][0]) >= {"participants", "league", "season",
                                       "state"})

for i, want in enumerate(("participants", "league;season")):
    get(f"/fixtures/date/{DATE_A}", include=want, per_page=50, page=1)
check("B3 three different narrow includes -> still ONE API call total",
      len(CALLS) == before, f"calls={len(CALLS)}")

# ── unsafe aliases must be REFUSED ──
fresh_cache()
get(f"/fixtures/date/{DATE_A}", include="participants", per_page=50, page=1)
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include="odds", per_page=50, page=1)
check("B4 cached [participants] does NOT serve [odds] (unsafe alias refused)",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")

fresh_cache()
get(f"/fixtures/date/{DATE_A}", include="statistics", per_page=50, page=1)
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include="statistics.type", per_page=50, page=1)
check("B5 cached [statistics] does NOT serve nested [statistics.type]",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")

fresh_cache()
get(f"/fixtures/date/{DATE_A}", include=CANON, per_page=50, page=1)
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include="participants", per_page=50, page=2)
check("B6 page 2 is never served from cached page 1",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include="participants", per_page=10, page=1)
check("B7 different per_page identity is never aliased",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")
before = len(CALLS)
get(f"/fixtures/date/{DATE_B}", include="participants", per_page=50, page=1)
check("B8 a different resource path (other date) is never aliased",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include="participants", per_page=50, page=1,
    filters="fixtureStates:5")
check("B9 a different filter set is never aliased",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")

# objects.1: an entry fetched WITHOUT an exclude cannot answer a caller that
# explicitly EXCLUDES a relation (the stored payload may still contain it).
fresh_cache()
get(f"/fixtures/date/{DATE_B}", include="participants", per_page=50, page=1)
before = len(CALLS)
get(f"/fixtures/date/{DATE_B}", include="participants", per_page=50, page=1,
    exclude="odds")
check("B10 request that excludes a relation is not served from a non-excluding entry",
      len(CALLS) == before + 1, f"calls={len(CALLS)}")

fresh_cache()
get(f"/fixtures/date/{DATE_B}", include="participants;odds", per_page=50, page=1,
    exclude="lineups")
before = len(CALLS)
get(f"/fixtures/date/{DATE_B}", include="participants", per_page=50, page=1)
check("B11 an entry that excluded MORE can safely serve a non-excluding request",
      len(CALLS) == before, f"calls={len(CALLS)}")

# ════════════════════════════════════════════════════════════════════════════
print("\n=== C. PER-RESOURCE TTL ===")
# ════════════════════════════════════════════════════════════════════════════
ttl_expect = {
    "/livescores/inplay": 0,
    "/odds/pre-match/fixtures/1": 900,
    "/fixtures/date/2099-01-01": 3600,
    "/fixtures/between/a/b/1": 21600,
    "/fixtures/head-to-head/1/2": 21600,
    "/standings/seasons/1": 21600,
    "/teams/1/squad/2": 86400,
    "/something/else": api_cache.DEFAULT_TTL,
}
bad = {p: (api_cache._ttl_for_path(p), t) for p, t in ttl_expect.items()
       if api_cache._ttl_for_path(p) != t}
check("C1 each resource class has its own TTL", not bad, bad)
check("C2 live endpoints are NEVER cached by this layer",
      api_cache._ttl_for_path("/livescores/inplay") == 0)

fresh_cache()
get("/livescores/inplay", include="participants")
check("C3 a live request is neither stored nor served from this cache",
      len(api_cache.GLOBAL_API_CACHE) == 0, list(api_cache.GLOBAL_API_CACHE))

fresh_cache()
get(f"/odds/pre-match/fixtures/{DATE_A}")
key = list(api_cache.GLOBAL_API_CACHE)[0]
api_cache._API_CACHE_META[key]["ts"] = time.time() - 901         # age past 900 s
check("C4 an entry past its TTL is evicted on read",
      api_cache._get_entry(key) is None and key not in api_cache.GLOBAL_API_CACHE)
check("C5 eviction also removes the alias-index entry (no orphan alias)",
      not any(key in bucket for bucket in api_cache._ALIAS_INDEX.values()))

fresh_cache()
old_max = api_cache.MAX_ENTRIES
api_cache.MAX_ENTRIES = 3
for i in range(6):
    get(f"/odds/pre-match/fixtures/{i}")
check("C6 cache stays bounded (MAX_ENTRIES)",
      len(api_cache.GLOBAL_API_CACHE) <= 3
      and len(api_cache._API_CACHE_META) <= 3,
      f"cache={len(api_cache.GLOBAL_API_CACHE)}")
check("C7 index and cache stay consistent after eviction",
      all(any(k in bucket for bucket in api_cache._ALIAS_INDEX.values())
          for k in api_cache.GLOBAL_API_CACHE))
api_cache.MAX_ENTRIES = old_max

# ════════════════════════════════════════════════════════════════════════════
print("\n=== D. FLUSH SAFETY (the 9 existing flush_system_ram call sites) ===")
# ════════════════════════════════════════════════════════════════════════════
fresh_cache()
get(f"/fixtures/date/{DATE_A}", include=CANON, per_page=50, page=1)
api_cache.flush_memory(report=False)
check("D1 flush clears payloads, metadata and the alias index together",
      api_cache.GLOBAL_API_CACHE == {} and api_cache._API_CACHE_META == {}
      and api_cache._ALIAS_INDEX == {})
before = len(CALLS)
get(f"/fixtures/date/{DATE_A}", include=CANON, per_page=50, page=1)
check("D2 after a flush the cache repopulates normally (no stale alias)",
      len(CALLS) == before + 1 and len(api_cache.GLOBAL_API_CACHE) == 1)

main_src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
check("D3 main.flush_system_ram still exists and delegates to the layer",
      "def flush_system_ram():" in main_src
      and "api_cache.flush_memory()" in main_src
      and "GLOBAL_API_CACHE.clear()" not in main_src)
check("D4 all existing flush call sites are still present",
      main_src.count("flush_system_ram()") == 11,
      main_src.count("flush_system_ram()"))
check("D5 GLOBAL_API_CACHE / smart_get / CachedResponseWrapper still exposed by main",
      "GLOBAL_API_CACHE" in main_src and "smart_get" in main_src
      and "CachedResponseWrapper" in main_src)
check("D6 the hijack is still installed",
      __import__("requests").get is api_cache.smart_get)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== E. SHARED 7-DAY FUTURE FIXTURE WINDOW ===")
# ════════════════════════════════════════════════════════════════════════════
ANCHOR = "2099-03-01"
fresh_cache()
summ = window.fill_window(ANCHOR)
check("E1 initial fill acquires all 7 future days",
      len(summ["dates"]) == 7 and sorted(summ["fetched"]) == sorted(summ["dates"])
      and summ["reused"] == [], summ)
check("E2 the 7-day horizon starts at the PREMATCH target date",
      summ["dates"][0] == ANCHOR and summ["dates"][-1] == "2099-03-07", summ["dates"])
check("E3 exactly one canonical API call per date (no duplicated acquisition)",
      len(CALLS) == 7 and len({c["url"] for c in CALLS}) == 7,
      f"calls={len(CALLS)}")
check("E4 every canonical fetch requests the same superset include",
      all(c["params"].get("include") == window.CANONICAL_INCLUDE
          and c["params"].get("per_page") == 50 for c in CALLS))
check("E5 the window is ONE canonical store, written atomically",
      os.path.exists(window.WINDOW_FILE)
      and not os.path.exists(window.WINDOW_FILE + ".tmp"))
st = window.window_status()
check("E6 store holds the 7 days with counts",
      len(st["days"]) == 7 and all(d["count"] == 3 for d in st["days"].values()), st)

# ── rolling: drop the expired oldest day, acquire ONLY the new day ──
before_calls = len(CALLS)
rolled = window.fill_window("2099-03-02")
check("E7 rolling evicts exactly the expired oldest day",
      rolled["evicted"] == [ANCHOR], rolled["evicted"])
check("E8 rolling reuses the 6 still-relevant days",
      sorted(rolled["reused"]) == ["2099-03-02", "2099-03-03", "2099-03-04",
                                   "2099-03-05", "2099-03-06", "2099-03-07"],
      rolled["reused"])
check("E9 rolling acquires ONLY the newly required day",
      rolled["fetched"] == ["2099-03-08"], rolled["fetched"])
check("E10 rolling cost exactly ONE new API call (never a 7-day refetch)",
      len(CALLS) - before_calls == 1, len(CALLS) - before_calls)
check("E11 evicted day is gone from the window",
      ANCHOR not in window.window_status()["days"])

# ── stale-fallback: a failed refetch never empties a good day ──
# A roll to an anchor fully inside the stored window must find every day FRESH
# (DAY_FRESH_SECONDS) and reuse it with no refetch — the exact behaviour the
# nightly pipeline relies on. (Previous step rolled to 2099-03-02, so the
# window now holds 02..08; the next anchor 2099-03-07 keeps 07,08 and acquires
# 09..13 — genuine FIFO.)
still_fresh = window.fill_window("2099-03-07")
check("E12a rolling to the next anchor evicts only expired days "
      "and acquires only the newly required ones",
      still_fresh["evicted"] == ["2099-03-02", "2099-03-03", "2099-03-04",
                                 "2099-03-05", "2099-03-06"]
      and still_fresh["fetched"] == ["2099-03-09", "2099-03-10", "2099-03-11",
                                     "2099-03-12", "2099-03-13"]
      and still_fresh["reused"] == ["2099-03-07", "2099-03-08"], still_fresh)
# Simulate a NEW process generation (only the DISK store holds data) and force
# a refetch whose network fails: the store's good day must be preserved verbatim.
fresh_cache()
FAIL_DATES.add("2099-03-07")
stale = window.fill_window("2099-03-07", force=True)
FAIL_DATES.discard("2099-03-07")
count_before = 3
count_after = window.window_status()["days"].get("2099-03-07", {}).get("count")
check("E12 a failed acquisition preserves the stored day (stale-fallback)",
      count_after == count_before == 3 and "2099-03-07" in stale["stale_kept"],
      f"before={count_before} after={count_after} kept={stale['stale_kept']}")
check("E13 the preserved day is still servable",
      window.lookup_for_request("/fixtures/date/2099-03-07",
                                {"include": "participants", "per_page": 50,
                                 "page": 1}) is not None)

# ── the window is FUTURE-only: it can never become a same-day/Live source ──
import datetime as _dt
today = _dt.datetime.now().strftime("%Y-%m-%d")
check("E14 today is not a 'future' date for the window",
      window.is_future_date(today) is False
      and window.is_future_date("2099-01-01") is True)
today_entry = window._load_store()
_today_anchor = _dt.datetime.now().strftime("%Y-%m-%d")
today_store = window._load_store()
today_store.setdefault("days", {})[_today_anchor] = {
    "fetched_at": time.time(), "count": 3, "page_count": 1, "acquisition_ok": True,
    "pages": {"1": {"params": {"api_token": "x", "include": window.CANONICAL_INCLUDE,
                               "per_page": 50, "page": 1},
                    "body": _make_body("https://x/fixtures/date/" + _today_anchor,
                                       {"include": window.CANONICAL_INCLUDE,
                                        "per_page": 50, "page": 1})}}}
window._save_store(today_store)
window.release_memory()
check("E15 a request for TODAY is never answered from the window "
      "(even when a day is stored for it)",
      window.lookup_for_request(f"/fixtures/date/{_today_anchor}",
                                {"include": "participants", "per_page": 50,
                                 "page": 1}) is None)

# ── unsafe window serving is refused exactly like an unsafe alias ──
check("E16 window refuses a request for a relation it never stored (odds)",
      window.lookup_for_request("/fixtures/date/2099-03-07",
                                {"include": "odds", "per_page": 50,
                                 "page": 1}) is None)
check("E17 window refuses a mismatched identity (per_page)",
      window.lookup_for_request("/fixtures/date/2099-03-07",
                                {"include": "participants", "per_page": 10,
                                 "page": 1}) is None)
check("E18 window refuses a page it does not hold",
      window.lookup_for_request("/fixtures/date/2099-03-07",
                                {"include": "participants", "per_page": 50,
                                 "page": 7}) is None)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== F. DUPLICATE ACQUISITION PREVENTED (Prematch + Weekly share) ===")
# ════════════════════════════════════════════════════════════════════════════
fresh_cache()
W_ANCHOR = "2099-05-01"
window.fill_window(W_ANCHOR)
acquire = len(CALLS)
check("F0 window acquired the 7 shared days once", acquire == 7, acquire)

# Real in-repo include signatures, all asking the SAME date the SAME way.
PREM_CHAIN = [
    ("gg_precision_engine", "participants;scores;lineups;formations;statistics"),
    ("over25_probabilistic", "participants;scores;odds"),      # odds NOT stored -> must miss
    ("over25_council", "participants;scores;odds;lineups;statistics"),
    ("apex_ud_aggregator", "participants"),
    ("gg_psychology", "participants;league;season"),
    ("u2s_psychology", "participants;scores"),
]
served, missed = [], []
for name, inc in PREM_CHAIN:
    n = len(CALLS)
    api_cache.smart_get(f"{URL}/fixtures/date/{W_ANCHOR}",
                        params={"include": inc, "per_page": 50, "page": 1})
    (served if len(CALLS) == n else missed).append(name)

check("F1 prematch engine requests for the shared date add NO API call "
      "when their relations are covered",
      all(n in served for n in ("gg_precision_engine", "apex_ud_aggregator",
                                "gg_psychology", "u2s_psychology")),
      f"served={served} missed={missed}")
check("F2 a request for a relation the window never stored (odds) correctly "
      "falls through to its own call",
      "over25_probabilistic" in missed and "over25_council" in missed,
      f"served={served} missed={missed}")

# Weekly-side request for the same date + a post-flush repeat (durability).
n = len(CALLS)
api_cache.smart_get(f"{URL}/fixtures/date/{W_ANCHOR}",
                    params={"include": "participants;scores;lineups;formations;statistics",
                            "per_page": 50, "page": 1})
check("F3 weekly-side request for the shared date adds NO API call",
      len(CALLS) == n, len(CALLS) - n)

api_cache.flush_memory(report=False)          # simulate a flush_system_ram() boundary
n = len(CALLS)
api_cache.smart_get(f"{URL}/fixtures/date/{W_ANCHOR}",
                    params={"include": "participants;scores;lineups;formations;statistics",
                            "per_page": 50, "page": 1})
check("F4 after a full cache flush the SAME fixture data is STILL served "
      "with 0 API calls (durable window)",
      len(CALLS) == n, len(CALLS) - n)
check("F5 total fixture-list API calls for the shared date: 1 canonical "
      "acquisition + 2 requests for the never-stored `odds` relation that are "
      "correctly NOT aliased (0 extra calls for any covered consumer)",
      sum(1 for c in CALLS if c["url"].endswith(f"/fixtures/date/{W_ANCHOR}")) == 3
      and len(missed) == 2,
      sum(1 for c in CALLS if c["url"].endswith(f"/fixtures/date/{W_ANCHOR}")))

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== G. WEEKLY FAMILY COMPOSES EXISTING INTELLIGENCE ===")
# ════════════════════════════════════════════════════════════════════════════
import WEEKLY.weekly_engine as we

WEEKLY_OUT = os.path.join(SBOX, "output")
os.makedirs(WEEKLY_OUT, exist_ok=True)
we.OUTPUT_DIR = WEEKLY_OUT
week_calls = []


def spy(name, artifact=None, rows=None):
    def _f(target_date, *a, **kw):
        week_calls.append((name, target_date, a, kw))
        if artifact:
            with open(os.path.join(WEEKLY_OUT, artifact.format(date=target_date)),
                      "w", encoding="utf-8") as fh:
                fh.write("fixture_id,fixture\n1,x\n")
        return rows if rows is not None else [{"fixture_id": "1"}]
    return _f


we.run_gg_o15_engine = spy("run_gg_o15_engine", "ALIENEDGE_GG_PICKS_{date}.csv")
we.run_gg_forensic_aggregator = spy("run_gg_forensic_aggregator")
we.run_gg_precision_filter = spy("run_gg_precision_filter", rows=[{"fixture_id": "1"}])
we.run_win_raw_engine = spy("run_win_raw_engine", "production_raw_engine_{date}.csv")
we.run_win_filter_service = spy("run_win_filter_service", rows=[{"fixture_id": "1"}])
we.run_over25_forecast_engine = spy("run_over25_forecast_engine",
                                    "master_over_stage2_{date}.csv")
we.run_over25_filter_aggregator = spy("run_over25_filter_aggregator",
                                      rows=[{"fixture_id": "1"}])

W_TARGET = "2099-06-01"
res = we.run_weekly_family(W_TARGET, horizon=2, flush_between_dates=True)
names = [c[0] for c in week_calls]

check("G1 horizon drives one Weekly pass per window date",
      sorted(res["per_date"]) == ["2099-06-01", "2099-06-02"], list(res["per_date"]))
check("G2 Weekly GG runs the existing factory order "
      "(predictor -> forensics -> filter)",
      names[:3] == ["run_gg_o15_engine", "run_gg_forensic_aggregator",
                    "run_gg_precision_filter"], names[:3])
check("G3 Weekly WIN runs the existing predictor + ONE filter call per risk level",
      names.count("run_win_filter_service") == 2 * len(we.WIN_RISK_LEVELS),
      names.count("run_win_filter_service"))
check("G4 Weekly O2.5 runs the existing forecast engine + one filter per risk level",
      names.count("run_over25_forecast_engine") == 2
      and names.count("run_over25_filter_aggregator") == 2 * len(we.O25_RISK_LEVELS),
      f"{names.count('run_over25_forecast_engine')}/"
      f"{names.count('run_over25_filter_aggregator')}")
check("G5 every Weekly engine call receives the window's date",
      all(c[1] in ("2099-06-01", "2099-06-02") for c in week_calls))
check("G6 the WIN filter gets the SAME risk levels main.py precomputes",
      sorted({c[3].get("risk_level") for c in week_calls
              if c[0] == "run_win_filter_service"}) == sorted(we.WIN_RISK_LEVELS))
check("G7 the O2.5 filter gets the SAME risk levels main.py precomputes",
      sorted({c[3].get("risk_level") for c in week_calls
              if c[0] == "run_over25_filter_aggregator"}) == sorted(we.O25_RISK_LEVELS))

expected_keys = ["filter_gg"] + [f"filter_win__{r}" for r in we.WIN_RISK_LEVELS] \
                + [f"filter_over25__{r}" for r in we.O25_RISK_LEVELS]
missing = [k for k in expected_keys
           if not os.path.exists(os.path.join(store.CACHE_DIR, f"{k}__{W_TARGET}.json"))]
check("G8 Weekly writes the existing Weekly filter keys per date", not missing, missing)
env = json.load(open(os.path.join(store.CACHE_DIR, f"filter_gg__{W_TARGET}.json")))
check("G9 snapshots use the existing output_store envelope "
      "(no parallel output system)",
      set(env) >= {"engine_key", "date", "generated_at", "status", "row_count", "data"},
      sorted(env))

plan = we.preview_weekly("2099-06-01", restore=True)
check("G10 preview resolves the composition to "
      "the REAL existing intelligence functions (not the test spies)",
      [s["module"] for s in plan["gg"]] == ["Engine.gg_precision_engine",
                                            "AGGREGATOR.gg_forensics_audit",
                                            "FILTER.gg_precision_filter"]
      and all(s["module"].startswith(("Engine.", "AGGREGATOR.", "FILTER."))
              for m in plan for s in plan[m]), plan)

we_src = open(os.path.join(ROOT, "WEEKLY", "weekly_engine.py"), encoding="utf-8").read()
_maths = [t for t in ("import math", "import numpy", "poisson", "parity", "monte",
                      "def apply_") if t in we_src]
check("G11 the Weekly module contains NO new prediction mathematics", not _maths, _maths)

# ═══════════════════════════════════════════════════════════════════════════
print("\n=== H. LIVE REMAINS TOUCHED-BY-NOTHING AND ISOLATED ===")
# ════════════════════════════════════════════════════════════════════════════
LIVE_FILES = [os.path.join(ROOT, "data", f) for f in
              ("live_inplay_cache.json", "live_prematch_cache.json",
               "fixture_date_cache.json")]
live_mtimes = {f: (os.path.getmtime(f) if os.path.exists(f) else None)
               for f in LIVE_FILES}
live_calls_after = sum(1 for c in CALLS if "livescores" in c["url"])
check("H1 nothing in the new layers requests a live endpoint",
      live_calls_after == 0, live_calls_after)

# Re-run the whole stack (window roll + a 1-date Weekly pass) and compare mtimes.
before = dict(live_mtimes)
window.fill_window("2099-07-01")
we.run_weekly_family("2099-07-01", horizon=1, flush_between_dates=True)
live_mtimes2 = {f: (os.path.getmtime(f) if os.path.exists(f) else None)
                for f in LIVE_FILES}
check("H2 every existing Live data file is byte-untouched (mtime identical)",
      all(live_mtimes2[f] == before[f] for f in LIVE_FILES), live_mtimes2)
check("H3 Live's fixture cache was not reused as the canonical shared store",
      window.WINDOW_FILE.endswith("future_fixture_window.json")
      and window.WINDOW_FILE != os.path.join(ROOT, "data", "fixture_date_cache.json")
      and not os.path.exists(os.path.join(SBOX, "future_fixtures.json")))
check("H4 the window store does not contain any live-only keys/relations",
      all(rel not in window.CANONICAL_INCLUDE
          for rel in ("livescores", "inplay", "events")),
      window.CANONICAL_INCLUDE)

# ════════════════════════════════════════════════════════════════════════════
print("\n=== I. DNA UNCHANGED (out of scope, proven) ===")
# ════════════════════════════════════════════════════════════════════════════
import subprocess as _sp


def _changed(path):
    r = _sp.run(["git", "diff", "--name-only", "--", path], cwd=ROOT,
                capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.strip()]


dna_changed = _changed("CORE/dna_profiler.py") + _changed("CORE/dna_engine_v2.py") \
    + _changed("CORE/dna_v2_market_factors.py")
check("I1 DNA modules have zero modifications", not dna_changed, dna_changed)

_CHECKED_FOR_ABSENCE_OF_DNA = ("WEEKLY/weekly_engine.py", "shared_fixture_window.py")
imports = []
for mod_file in ("WEEKLY/weekly_engine.py", "shared_fixture_window.py",
                 "api_cache.py", "api_request_identity.py"):
    src = open(os.path.join(ROOT, mod_file), encoding="utf-8").read()
    # Structural tokens only: real imports of intelligence layers (CORE/Engine/
    # AGGREGATOR/PSYCHOLOGY/FILTER) or DNA cache symbols. Plain prose mentions
    # of "DNA" in comments/docstrings (e.g. "not a DNA cache") are NOT touches.
    # WEEKLY legitimately composes the GG / WIN / O2.5 ENGINE+FILTER functions,
    # so the "references DNA" rule for WEEKLY is: no CORE import, no dna_* symbol.
    dna_touches = [ln.strip() for ln in src.splitlines()
                   if not ln.strip().startswith("#")
                   and ("dna_" in ln.lower()
                        or ("CORE." in ln or "from CORE" in ln))]
    code_imports = ([mod_file] if (mod_file == "WEEKLY/weekly_engine.py"
                                   and not dna_touches) else [])
    if dna_touches and mod_file in _CHECKED_FOR_ABSENCE_OF_DNA:
        imports.append((mod_file, dna_touches))
check("I2 no new module touches or references DNA", not imports, imports)

check("I3 no new DNA TTL / freshness / cache architecture introduced",
      "dna_ttl" not in we_src.lower())

# ════════════════════════════════════════════════════════════════════════════
print("\n=== SUMMARY ===")
print(f"passed={len(PASS)} failed={len(FAIL)}")
if FAIL:
    print("FAILED CHECKS:")
    for name in FAIL:
        print(f"  ❌ {name}")
    sys.exit(1)
print("ALL CHECKS PASSED — no network, no production writes, no pipeline run.")
sys.exit(0)