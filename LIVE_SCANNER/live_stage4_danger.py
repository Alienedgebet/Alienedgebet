import os
import requests
import time
import math
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple
import re
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (Shared Memory) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

OUTPUT_FILE = os.path.join(DATA_DIR, "danger_audit.json")

# ── 150-DAY HISTORY CACHE (item: Stage 4 was the single largest quota consumer) ──
# get_key_players_forensics() pulled a 150-day finished-match history for BOTH
# sides of EVERY fixture on EVERY 45s cycle with no reuse whatsoever. The window
# only changes when a team plays, so a finished-match pull is safe to reuse inside
# HISTORY_TTL. Only the RAW provider payload is cached — every parsing, weighting
# and scoring line in this file is untouched. Same JSON-per-stage convention as
# squad_cache_stage1_prematch.json / squad_cache_stage3_incoming.json.
HISTORY_CACHE_FILE = os.path.join(DATA_DIR, "danger_history_cache.json")
HISTORY_TTL = 6 * 3600      # 6h: a team is refetched at most 4x/day, not ~1900x
# Bump this whenever the history payload needs fields that older entries lack.
# Without a schema marker, a cache entry created before statistics were
# requested would keep manufacturing zero dangerous-attack averages for hours.
HISTORY_CACHE_SCHEMA = 2
# 2026-09-20: 400 teams x full raw payloads (lineups incl.) reached 932MB on
# disk and ~2.5GB+ RSS on every cycle load -> the OOM-kill loop that killed the
# scanner 5x (Sep 19/20) and an API worker. 60 teams keeps the file ~250MB and
# the live scanner comfortably under 1GB.
# 2026-09-28: the 60-team count cap was the real reason the evidence was thin.
# Each cycle needs ~34 teams (17 fixtures x 2 sides) and the cap evicted
# everything older than the most recent ~60 pulls, so a team's whole 150-day
# window was thrown away roughly every two cycles and re-pulled from scratch.
# Measured cost is ~1.49MB/team on disk, and the service sits at ~836MB of a
# 1.7GB cgroup limit, so a count cap has to give way to a BYTE budget: it
# self-limits no matter how fixture-heavy the teams in the window happen to be
# (a 19-fixture team costs several times a 3-fixture one, so a fixed count is
# not a fixed cost).
#
# 2026-09-28 HOTFIX: lowered 500MB -> 120MB. The 500MB budget was sized for a
# cold cache and was the wrong trade against a LIVE hourly quota: on the deploy
# the scanner re-pulled years of history in one burst, hit the rate limit, and
# the resulting 429 storm emptied the feeds. 120MB still holds ~80 team
# histories — roughly a week of teams, so the 150-day window genuinely
# accumulates across cycles instead of being evicted every two — while costing
# a fraction of the burst. Raise it only once the quota headroom is measured.
#
#   A count cap is not a cost cap: entry size varies by an order of magnitude
#   with the number of finished fixtures a team has in the window, so 60 entries
#   can be 90MB or 600MB depending on which teams happen to be playing.
#   Budgeting bytes makes retention self-limiting in the worst case as well as
#   the typical one.
#
# Entries are evicted oldest-`at`-first until the file fits. TTL expiry still
# applies first, so a stale entry is dropped for staleness rather than for size.
HISTORY_CACHE_MAX_BYTES = 120 * 1024 * 1024   # ~120MB
_history_cache: Dict[str, Any] = {}

# FEED WRITE GUARD (see live_cache.write_feed): acquired feeds are written through
# this helper so a FAILED SportMonks acquisition can never empty a good feed.
try:
    from live_cache import note_acquisition, acquisition_failed, write_feed
except ImportError:  # running this file directly rather than via the package
    import sys as _sys
    _sys.path.insert(0, BASE_DIR)
    from live_cache import note_acquisition, acquisition_failed, write_feed

# SIGNED IMPACT + CANONICAL STATE (2026-09-28). Stage 4 previously had no state
# rule at all (it audited finished and not-yet-started fixtures) and decided
# DANGER/SAFE from a headcount. Both now come from shared, tested modules.
try:
    from LIVE_SCANNER.live_state_classifier import classify_fixture
    from LIVE_SCANNER import live_signed_impact as si
    from LIVE_SCANNER.live_signed_impact import (
        assess_absence, assess_goalkeeper, regime_for_odds,
    )
except ImportError:  # direct execution without the package on sys.path
    from live_state_classifier import classify_fixture
    import live_signed_impact as si
    from live_signed_impact import (
        assess_absence, assess_goalkeeper, regime_for_odds,
    )

# ==============================================================================
# ⚙️ SYSTEM CONFIGURATION (WORLD STANDARD)
# ==============================================================================
API_KEY = os.getenv("SPORTMONKS_API_KEY")
BASE_URL = "https://api.sportmonks.com/v3/football"

# Stat IDs for Forensic Worth Calculation
RATING_ID = 118       
MINUTES_ID = 119      
STAR_FACTOR_ID = 211  

# Positional Weights for Vulnerability Calculation
POS_WEIGHTS = {
    "Goalkeeper": 50.0, 
    "Defender": 9.0,
    "Midfielder": 4.5,
    "Attacker": 1.5,
    "Unknown": 3.0
}

REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.2
MAX_RETRIES = 5

HISTORICAL_RECALL_DAYS = 150 
CHAOS_THRESHOLD = 4  # 4+ Star players missing = Red Danger

_session = requests.Session()

# ------------------------------------------------------------------------------
# 🛠️ CORE UTILITY FUNCTIONS
# ------------------------------------------------------------------------------
def GET(path: str, params: Optional[Dict[str,Any]] = None) -> Dict[str,Any]:
    if params is None: params = {}
    params = dict(params); params.setdefault("api_token", API_KEY)
    if not path.startswith("/"): path = "/" + path
    url = BASE_URL.rstrip("/") + path
    backoff = 2.0
    problem = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                problem = "HTTP 429 rate limit"
                time.sleep(backoff * attempt); continue
            r.raise_for_status()
            body = r.json()
            # 200 + empty + provider message = subscription/quota shape. Tag it so a
            # failed pull is never read as "this team has no history".
            if isinstance(body, dict) and not body.get("data") and body.get("message"):
                return note_acquisition(body, r.status_code, body.get("message"))
            return body
        except Exception as e:
            resp_obj = getattr(e, "response", None)
            problem = (f"HTTP {resp_obj.status_code} ({type(e).__name__})" if resp_obj is not None
                       else f"{type(e).__name__}: {e}")
            if attempt == MAX_RETRIES:
                return note_acquisition({"data":[]}, None, f"retries exhausted ({problem})")
            time.sleep(backoff); backoff *= 1.5
    return note_acquisition({"data":[]}, None, f"retries exhausted ({problem})")

def safe_int(x: Any, default: Optional[int] = 0) -> int:
    try: return int(float(str(x).strip().replace(",", "")))
    except: return default

def safe_float(x: Any, default: float = 0.0) -> float:
    try: return float(str(x).strip().replace(",", "").rstrip("%"))
    except: return default

def resolve_participants(parts):
    """Return provider-identified home/away participants, or (None, None).

    SportMonks does not guarantee participant array order. Location metadata is
    the authoritative side contract; guessing by position reverses live cards.
    """
    home = next((p for p in parts
                 if (p.get("meta") or {}).get("location") == "home"), None)
    away = next((p for p in parts
                 if (p.get("meta") or {}).get("location") == "away"), None)
    return home, away


def extract_stat_entries(fx: Dict[str,Any], team_id: int) -> Dict[str, float]:
    """🚨 FIX: Bulletproof Participant Mapping! No more blind spots. 🚨"""
    stats_raw = fx.get("statistics") or[]
    result = {}
    t_id = int(team_id)
    
    # Sometimes SportMonks groups by ID as keys, sometimes as a flat list
    entries =[]
    if isinstance(stats_raw, dict):
        entries = stats_raw.get(str(t_id),[])
    else:
        entries =[s for s in stats_raw if int(s.get('participant_id', 0)) == t_id]
        
    for s in entries:
        t_obj = s.get("type", {})
        stat_name = t_obj.get("name") if isinstance(t_obj, dict) else s.get("name")
        val = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
        if stat_name and val is not None: result[str(stat_name)] = safe_float(val)
    return result

# ------------------------------------------------------------------------------
# 🧠 FORENSIC SQUAD ENGINES (FULL IMPLEMENTATION)
# ------------------------------------------------------------------------------
def _load_history_cache():
    """Best-effort load of the per-team history cache; expired entries are dropped."""
    global _history_cache
    _history_cache = {}
    try:
        with open(HISTORY_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    now = time.time()
    if isinstance(raw, dict):
        for k, v in raw.items():
            if (isinstance(v, dict)
                    and v.get("schema") == HISTORY_CACHE_SCHEMA
                    and (now - v.get("at", 0)) < HISTORY_TTL
                    and v.get("data")):
                _history_cache[k] = v
    print(f"[HISTORY CACHE] loaded {len(_history_cache)} team histories "
          f"(TTL {HISTORY_TTL // 3600}h)")


def _save_history_cache():
    """Persist ONLY unexpired entries, hard-capped so the file stays bounded.

    Same guard principle as write_feed: an empty in-memory cache (e.g. a freshly
    started process whose pulls all failed on this cycle) must NEVER overwrite a
    non-empty disk cache — otherwise the cache is emptied exactly when the quota
    situation needs it most (observed live: 32 histories wiped to 0)."""
    try:
        now = time.time()
        items = [(k, v) for k, v in _history_cache.items()
                  if (isinstance(v, dict)
                      and v.get("schema") == HISTORY_CACHE_SCHEMA
                      and (now - v.get("at", 0)) < HISTORY_TTL
                      and v.get("data"))]
        items.sort(key=lambda kv: kv[1].get("at", 0), reverse=True)

        # ── BYTE-BUDGET EVICTION (2026-09-28) ──────────────────────────────────
        # This replaces the old `items[:HISTORY_CACHE_MAX_TEAMS]` slice. A count
        # cap is not a cost cap: entry size varies by an order of magnitude with
        # how many finished fixtures a team has in the window, so 60 entries can
        # be 90MB or 600MB depending on which teams happen to be playing. Keeping
        # the newest entries until the payload fits a byte budget makes retention
        # self-limiting in the worst case as well as the typical one, and is what
        # lets the cache actually accumulate the 150-day window that the signed
        # impact metric (net_impact) needs to tell a key player from a rumour.
        kept, total = [], 0
        for k, v in items:
            try:
                size = len(json.dumps(v, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError):
                size = 0
            if total + size > HISTORY_CACHE_MAX_BYTES:
                break
            kept.append((k, v))
            total += size
        dropped = len(items) - len(kept)
        items = kept

        if not items:
            try:
                with open(HISTORY_CACHE_FILE, "r", encoding="utf-8") as f:
                    if json.load(f):
                        print("[HISTORY CACHE] in-memory cache empty — existing disk "
                              "cache PRESERVED (not overwritten).")
                        return
            except Exception:
                pass
        with open(HISTORY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(dict(items), f)
        # Report retention in MB and how many entries the budget displaced, so
        # the evidence base can be watched growing cycle over cycle instead of
        # assumed. A non-zero `dropped` is normal and healthy (it is the budget
        # working); a rising `dropped` on a quiet day would mean the window is
        # still turning over too fast.
        print(f"[HISTORY CACHE] saved {len(items)} team histories "
              f"({total / 1e6:.1f}MB / {HISTORY_CACHE_MAX_BYTES / 1e6:.0f}MB budget"
              + (f", {dropped} evicted by budget)" if dropped else ")")
              + f" -> {os.path.basename(HISTORY_CACHE_FILE)}")
    except Exception as e:
        print(f"[HISTORY CACHE] save skipped: {e}")


def get_key_players_forensics(team_id: int):
    end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    start_dt = (datetime.now(timezone.utc).date() - timedelta(days=HISTORICAL_RECALL_DAYS)).isoformat()
    t_id = int(team_id)

    # ── HISTORY CACHE ───────────────────────────────────────────────────────────
    # Reuse a team's 150-day finished-match pull inside HISTORY_TTL instead of
    # refetching it for BOTH sides of EVERY fixture on EVERY 45s cycle (the largest
    # single quota consumer in the Live system). Only the RAW payload is cached —
    # every parsing/weighting/scoring line below this block is unchanged.
    player_stats = {}
    cached = _history_cache.get(str(t_id))
    if cached and (time.time() - cached.get("at", 0)) < HISTORY_TTL:
        history = cached.get("data") or []
    else:
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{t_id}", params={
            # Dangerous Attacks is consumed by compute_style_analysis(). The
            # previous cache and request omitted statistics, so missing data was
            # silently coerced to 0.0 and every team looked Defensive.
            "include": "lineups.details.type;lineups.player.position;scores;participants;statistics;statistics.type",
            "filter": "fixtureStates:5",
            "per_page": 50
        })
        history = resp.get("data",[])
        if acquisition_failed(resp):
            # A failed pull must neither be cached nor read as "this team has no
            # history" — fall back to the last known-good window when we have one.
            if cached and cached.get("data"):
                history = cached["data"]
                print(f"[HISTORY CACHE] team {t_id}: acquisition FAILED "
                      f"({resp.get('_failure')}) — reusing cached history "
                      f"({len(history)} fixtures).")
        elif history:
            _history_cache[str(t_id)] = {
                "at": time.time(), "schema": HISTORY_CACHE_SCHEMA, "data": history
            }

    for fx in history:
        # Keeper Conceded Calculation Fallback
        hid, aid = None, None
        for pt in fx.get("participants",[]):
            loc = pt.get("meta", {}).get("location")
            if loc == "home": hid = str(pt.get("id"))
            elif loc == "away": aid = str(pt.get("id"))
        
        h_g, a_g = 0, 0
        for entry in fx.get("scores",[]):
            s_obj = entry.get("score") or entry
            g = s_obj.get("goals")
            if g is not None:
                if str(entry.get("participant_id")) == hid: h_g = int(g)
                else: a_g = int(g)
        
        opp_goals = a_g if str(t_id) == hid else h_g

        for l in fx.get("lineups",[]):
            if int(l.get("team_id", 0)) == t_id:
                p_obj = l.get("player")
                if not p_obj or not isinstance(p_obj, dict): continue
                pid = int(l.get("player_id"))
                
                m_val, r_val, star_val, c_val = 0, 0.0, 0, -1.0
                for d in l.get("details",[]):
                    tid = int(d.get('type_id', 0))
                    val = d.get('data', {}).get('value', 0) if isinstance(d.get('data'), dict) else d.get('value', 0)
                    if tid == MINUTES_ID: m_val = int(safe_float(val))
                    elif tid == RATING_ID: r_val = safe_float(val)
                    elif tid == STAR_FACTOR_ID: star_val = 1 
                    elif "conceded" in str(d.get('type', {}).get('name', '')).lower(): c_val = safe_float(val)

                if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                if c_val == -1.0: c_val = float(opp_goals)

                if pid not in player_stats:
                    pos = p_obj.get("position", {}).get("name", "Unknown") if p_obj.get("position") else "Unknown"
                    player_stats[pid] = {"name": p_obj.get("display_name"), "pos": pos, "mins": 0, "ratings":[], "star": 0, "conceded": 0}
                
                player_stats[pid]["mins"] += m_val
                player_stats[pid]["star"] += star_val
                if r_val > 0: player_stats[pid]["ratings"].append(r_val)
                if m_val > 0: player_stats[pid]["conceded"] += c_val

    worth_list =[]
    for pid, d in player_stats.items():
        avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
        worth = (d["mins"] * avg_r) + (d["star"] * 1000)
        c_p90 = (d["conceded"] / d["mins"] * 90) if d["mins"] > 0 else 0.0
        # 2026-09-28 FIX. avg_rating, apps and mins were COMPUTED here and then
        # dropped on the floor. Everything downstream that judges a player by
        # quality read None, so the signed-impact metric scored 0.00 confidence
        # for every absent player and the entire board read ROTATION with no
        # evidence — and the Incoming detail page showed "no rating on record"
        # for players whose rating was plainly visible in the Live Match table.
        #
        #   `avg_r` is the mean rating above, `apps` is how many rating entries
        #   were observed, `mins` is the minutes already accumulated. All three
        #   are in hand, so this costs no extra provider call.
        #
        # `avg_r` is deliberately NOT defaulted to 6.0 when no rating exists:
        # a fabricated 6.0 reads as "exactly average" and quietly drags the
        # signed verdict toward zero. A player with no observed rating carries
        # `avg_rating: None` so the metric can shrink their contribution to
        # nothing instead of inventing a value for them.
        worth_list.append({
            "id": pid,
            "name": d["name"],
            "pos": d["pos"],
            "worth": worth,
            "c_p90": c_p90,
            "avg_rating": (avg_r if d["ratings"] else None),
            "apps": len(d["ratings"]),
            "mins": d["mins"],
        })

    key_gks = sorted([p for p in worth_list if p['pos'] == "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:1]
    key_others = sorted([p for p in worth_list if p['pos'] != "Goalkeeper"], key=lambda x: x['worth'], reverse=True)[:10]
    
    return {int(p['id']): p for p in (key_gks + key_others)}, history

def compute_style_analysis(history, team_id: int):
    """🚨 FIX: Calibrated Tactical Thresholds to Market Reality! 🚨"""
    recent = history[:8]
    metrics = defaultdict(list)
    t_id = int(team_id)
    for r in recent:
        ent = extract_stat_entries(r, t_id)
        # Absence is not a measured zero. Keep an explicit unavailable state
        # so downstream chemistry cannot present missing data as a real 0 DA.
        if "Dangerous Attacks" in ent:
            metrics["da"].append(ent["Dangerous Attacks"])

    if not metrics["da"]:
        return {"label": "Unavailable", "score": None, "da": None,
                "available": False}

    avg_da = sum(metrics["da"])/len(metrics["da"])
    # Lowered from >45 to >36 so it actually catches attacking teams!
    label = "Attacking" if avg_da > 36 else "Defensive" if avg_da < 28 else "Balanced"
    return {"label": label, "score": round(avg_da/10, 2), "da": avg_da,
            "available": True}

# ROTATION LEDGER (2026-09-28)
# The rotation uplift is the only statistically significant new signal found in
# the audit (high-churn sides scored +0.48 more goals, t=+2.58 on 220
# team-matches), but that sample came from only 40 teams, so the observations
# are NOT independent and the effect could still be a quirk of those clubs.
#
# Every verdict is therefore written here with the fixture it applied to. Once
# those fixtures finish, the outcome can be scored against the call and the
# effect either confirmed on live data or demoted — a decision made from
# evidence rather than from the original 40-team sample.
#
# One JSON object per line, append-only, capped by rotation in save_ledger().
ROTATION_LEDGER_FILE = os.path.join(DATA_DIR, "rotation_ledger.jsonl")
ROTATION_LEDGER_MAX = 20000


def save_ledger(rows):
    """Append this cycle's verdicts to the rotation ledger.

    Best-effort by design: a ledger that cannot be written must never take the
    scanner down, and it is diagnostic data rather than a feed, so a failure is
    reported and swallowed rather than raised.
    """
    if not rows:
        return 0
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ROTATION_LEDGER_FILE, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        # Keep the file bounded: drop the oldest lines once it grows past the cap.
        try:
            if os.path.getsize(ROTATION_LEDGER_FILE) > ROTATION_LEDGER_MAX * 220:
                with open(ROTATION_LEDGER_FILE, encoding="utf-8") as f:
                    lines = f.readlines()
                with open(ROTATION_LEDGER_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-ROTATION_LEDGER_MAX:])
        except OSError:
            pass
        return len(rows)
    except Exception as e:
        print(f"[ROTATION LEDGER] write skipped: {e}")
        return 0


def _favourite_odds(fixture_id) -> Optional[float]:
    """The shorter 1X2 price for a fixture, or None when the provider has none.

    Deliberately the only odds this stage reads. It exists to answer one
    question — is this a strong favourite, an even contest, or a big dog — and
    regime_for_odds() degrades to MID_FIELD when the answer is unavailable, so
    a fixture the provider has no price for is never given a confident regime.
    """
    try:
        resp = GET(f"/odds/pre-match/fixtures/{fixture_id}",
                   params={"market_id": 1})
    except Exception:
        return None
    if acquisition_failed(resp):
        return None
    best: Optional[float] = None
    for row in (resp.get("data") or []):
        if row.get("market_id") != 1:
            continue
        try:
            val = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if val > 100:            # American odds masquerading as decimal
            continue
        if val <= 1.0:
            continue
        best = val if best is None else min(best, val)
    return best


# ── ODDS MEMO ──────────────────────────────────────────────────────────────
# 2026-09-28 HOTFIX. `_favourite_odds` was added to implement the strong-
# favourite / big-dog regime gate, and it was called once per fixture, every
# cycle, unconditionally. It did not exist before, and it is a per-fixture
# provider request, so it was the change that pushed the account into a
# sustained 429: zero rate-limit errors before the deploy, eleven after, with
# cycle time rising from ~40s to ~220s and all three feeds emptied (which
# silenced the alert pipeline entirely).
#
# The odds are only ever used to pick a regime BAND, and the regime only moves
# a bar by a few points. It is worth a provider call when the signed verdict
# sits CLOSE to a bar — that is the only time the answer can change the
# outcome. It is not worth one when the verdict is already decisive, and not
# worth one at all when the fixture has nobody absent.
#
# So: memoise per fixture for the process lifetime, and let the caller ask
# only when the regime could actually matter.
_ODDS_MEMO: Dict[Any, Any] = {}


def _favourite_odds_cached(fixture_id) -> Optional[float]:
    """Memoised `_favourite_odds`, so one fixture costs at most one call.

    Pre-match 1X2 prices do not move within a scan session, and the scanner
    re-reads the same fixtures every cycle, so an unmemoised call is pure
    waste. A miss is memoised too: re-asking a provider that just said "no
    such market" costs the same as asking once and returns the same nothing.
    """
    key = fixture_id
    if key in _ODDS_MEMO:
        return _ODDS_MEMO[key]
    val = _favourite_odds(fixture_id)
    _ODDS_MEMO[key] = val
    return val


def _regime_needed(nets, confidences):
    """Would the regime band plausibly change any of these verdicts?

    Returns True only when a side's net impact is within the spread of the
    three regime bars, i.e. when the verdict is genuinely undecided. Away from
    the bars, every regime agrees on the answer, so the call cannot change it
    and is not worth the quota.
    """
    bars = list(si._DANGER_BAR.values())
    margin = (max(bars) - min(bars)) / 2.0 + 1.0   # half-spread plus a unit
    for net, conf in zip(nets, confidences):
        if net is None or (conf or 0) < si.MIN_CONFIDENCE_FOR_CALL:
            continue
        for bar in bars:
            # Within `margin` of ANY bar means the band could tip it.
            if abs(abs(net) - bar) <= margin:
                return True
    return False


# ------------------------------------------------------------------------------
# 🚀 MAIN PIPELINE (WRAPPED FOR ARCHITECTURE)
# ------------------------------------------------------------------------------
def run_danger_forensic_aggregator():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return[]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _load_history_cache()
    print(f"\n{'='*120}")
    print(f"{'ALIENEDGE SUPREME DANGER FORENSIC AGGREGATOR':^120}")
    print(f"{today:^120}")
    print(f"{'='*120}\n")

    all_fixtures =[]
    current_page = 1
    has_more_pages = True
    acq_failed = False   # a FAILED acquisition must never empty the audit
    
    while has_more_pages:
        #  FIX: Added 'statistics' to include array so we actually get DA!
        resp = GET(f"/fixtures/date/{today}", params={
            "include": "participants;lineups.player;metadata;formations;statistics;statistics.type;scores",
            "page": current_page
        })
        if acquisition_failed(resp) and not acq_failed:
            acq_failed = True
            print(f"[ACQUISITION] /fixtures/date/{today} FAILED — "
                  f"reason={resp.get('_failure')} | http_status={resp.get('_http_status')} "
                  f"| empty audit will NOT overwrite an existing audit.")
        data = resp.get("data",[])
        if not data: break
        
        all_fixtures.extend(data)
        print(f"   [PAGINATION] Captured Page {current_page} ({len(data)} fixtures)...")
        
        pagination = resp.get("pagination", {})
        if not pagination: pagination = resp.get("meta", {}).get("pagination", {})
        has_more_pages = pagination.get("has_more", False)
        current_page += 1
        time.sleep(REQUEST_DELAY)

    print(f"\n[INFO] Successfully recovered {len(all_fixtures)} total fixtures. Starting Deep Forensics...\n")

    output_pool =[]
    processed_count = 0
    ledger_rows =[]

    for fx in all_fixtures:
        try:
            # ── STATE GATE (2026-09-28) ───────────────────────────────────
            # Stage 4 had NO state filter, so it audited every fixture of the
            # day including ones that had not kicked off and ones already
            # finished — five of the seventeen rows in danger_audit.json were
            # not even in the live in-play cache. A danger verdict on a match
            # that has not started is a guess dressed as evidence.
            _st = classify_fixture(fx)
            if _st.get("is_finished") or _st.get("is_stale"):
                continue
            if not (_st.get("is_live") or _st.get("is_not_started")):
                continue

            lineups = fx.get("lineups", [])
            starters_all =[l for l in lineups if int(l.get('type_id', 0)) == 11]
            if not starters_all: continue 

            parts = fx.get("participants",[])
            if len(parts) < 2: continue
            h_p, a_p = resolve_participants(parts)
            # Do not guess sides from provider ordering. A reversed danger card
            # silently reverses every downstream home/away market signal.
            if h_p is None or a_p is None:
                continue

            # ── MARKET REGIME (2026-09-28) ───────────────────────────────
            # Rotation is not equally costly for a strong favourite (whose XI
            # is the product) and a big dog (whose XI is already written off),
            # so the signed verdict needs that context to set its bar. The
            # regime describes the MATCH, so it is shared by both sides.
            #
            # It is resolved LAZILY, after the signed metrics exist, because it
            # costs a provider call. The call used to be made here for every
            # fixture on every cycle; that unconditional per-fixture request is
            # what exhausted the quota and silenced the feeds. `regime_holder`
            # starts as None and is filled in by `_ensure_regime()` only when a
            # verdict is actually close enough to a bar for the band to matter.
            # `None` = not yet decided. It is only resolved into a real band if
            # some side's verdict is close enough to a bar that the band could
            # tip it, and it stays None otherwise — meaning every regime agrees,
            # and MID_FIELD is the honest label for that case.
            regime_holder = {"value": None}

            def _ensure_regime(nets, confidences):
                if regime_holder["value"] is not None:
                    return regime_holder["value"]
                if not _regime_needed(nets, confidences):
                    # Both sides are decisive, or too thin to call. No odds call.
                    return "MID_FIELD"
                band = regime_for_odds(_favourite_odds_cached(fx.get("id")))
                # A fetched band (including a mid-field one) is now settled for
                # the whole fixture: the odds are a property of the MATCH, so a
                # second side must not re-decide it on its own evidence.
                regime_holder["value"] = band
                return band

            def audit_side(team_id, team_name):
                t_id = int(team_id)
                key_monument, history = get_key_players_forensics(t_id)
                current_starters = {int(l['player_id']) for l in starters_all if int(l.get('team_id', 0)) == t_id}
                # A key player named on the bench (type_id 12) is NOT injured.
                # Counting the bench as absent is how an ordinary rotation used
                # to earn a DANGER badge.
                current_bench = {int(l['player_id']) for l in lineups
                                 if int(l.get('team_id', 0)) == t_id
                                 and int(l.get('type_id', 0)) == 12}

                master_gk = next(
                    (info for info in key_monument.values()
                     if info.get('pos') == "Goalkeeper"), None)
                starting_gk = next(
                    (key_monument[pid] for pid in sorted(current_starters)
                     if key_monument.get(pid, {}).get('pos') == "Goalkeeper"), None)
                starting_gk_leak = (starting_gk or {}).get('c_p90')

                missing_details = []
                m_weight, t_weight = 0, 0
                for pid, info in key_monument.items():
                    w = POS_WEIGHTS.get(info['pos'], 3.0)
                    t_weight += w
                    if pid not in current_starters and pid not in current_bench:
                        # The quality evidence travels WITH the absence. It used
                        # to be dropped here, which is precisely what made the
                        # verdict a headcount: the engine could see THAT a
                        # player was gone but never HOW GOOD he was.
                        missing_details.append({
                            "name": info['name'], "pos": info['pos'],
                            "rating": info.get('avg_rating'),
                            "apps": info.get('apps'),
                            "mins": info.get('mins'),
                            "worth": info.get('worth'),
                        })
                        m_weight += w

                data_available = bool(key_monument)
                v_pct = (m_weight / t_weight * 100) if t_weight > 0 else None

                # ── SIGNED VERDICT (2026-09-28) ───────────────────────────────
                # Replaces `breached = (len(missing) >= 4) or gk_hole`, which
                # could only ever count and so could never report an upgrade.
                #
                # Computed under a neutral MID_FIELD regime FIRST, purely to
                # obtain the numbers. The regime band only selects which bar
                # applies, so the net impact and the confidence are identical
                # under every band — only the final label depends on it. That
                # lets the caller decide whether the odds call is warranted
                # (see `_regime_needed`) instead of always paying for it.
                _absent = [{**info, "id": pid}
                           for pid, info in key_monument.items()
                           if pid not in current_starters and pid not in current_bench]
                _present = [{**key_monument[pid], "id": pid}
                            for pid in key_monument if pid in current_starters]
                net = assess_absence(_absent, _present, regime="MID_FIELD")

                # Now that the numbers exist, pay for the regime only if it can
                # change the answer, then re-derive the label under it.
                fav_regime = _ensure_regime([net["net_impact"]],
                                            [net["confidence"]])
                if fav_regime != "MID_FIELD":
                    net = assess_absence(_absent, _present, regime=fav_regime)

                verdict = net["verdict"]
                gk = assess_goalkeeper(starting_gk, master_gk, fav_regime,
                                       starting_gk_leak)
                # A confirmed goalkeeper downgrade is real damage whatever the
                # outfield evidence says, and it is allowed to raise DANGER —
                # but never to manufacture one out of missing data.
                if gk.get("liability") and verdict != si.STATE_DANGER:
                    verdict = si.STATE_DANGER
                    net["verdict"] = verdict
                    net["verdict_reason"] = (
                        f"Outfield {net['verdict_reason'].split('—')[0].strip()} — "
                        f"but the goalkeeper alone settles it: {gk['note']}"
                    )

                breach = (None if not data_available else (verdict == si.STATE_DANGER))
                style = compute_style_analysis(history, t_id)

                # The headline label now carries the SIGN of the effect, not a
                # count. A team whose rotation upgraded it is no longer painted
                # with the same red badge as a team that lost its winners.
                badge = {
                    si.STATE_DANGER:  "🔴 DANGER",
                    si.STATE_BLESSING: "🟢 BLESSING",
                    si.STATE_ROTATION: "🟡 ROTATION",
                }.get(verdict, "⚪ UNAVAILABLE")

                return {
                    "team_name": team_name, "id": t_id, "breach": breach,
                    "data_available": data_available,
                    "danger_level": (badge if data_available
                                     else "⚪ UNAVAILABLE"),
                    "verdict": verdict,
                    "verdict_reason": net["verdict_reason"],
                    "net_impact": net["net_impact"],
                    "impact_confidence": net["confidence"],
                    "regime": fav_regime,
                    "quality_lost": net["quality_lost"],
                    "replacement_credit": net["replacement_credit"],
                    "rotation_uplift": net["rotation_uplift"],
                    "gk_verdict": gk["label"],
                    "gk_note": gk["note"],
                    # Retained for backward compatibility with the existing
                    # consumers, but it is no longer what decides the badge —
                    # `net_impact` is. See live_signed_impact for why.
                    "vulnerability_pct": (round(v_pct, 1) if v_pct is not None else None),
                    "gk_leak": starting_gk_leak,
                    "gk_leak_available": starting_gk_leak is not None,
                    "missing_details": missing_details,
                    "formation": next((f['formation'] for f in fx.get('formations',[]) if int(f['participant_id']) == t_id), "N/A"),
                    "style": style
                }

            home_audit = audit_side(h_p['id'], h_p['name'])
            away_audit = audit_side(a_p['id'], a_p['name'])

            # 🚨 FIX: Tactical Alignment Handshake (Lowered to > 35 to catch open matches)
            home_da = home_audit['style'].get('da')
            away_da = away_audit['style'].get('da')
            style_align = (
                "🔥 OPEN"
                if isinstance(home_da, (int, float)) and isinstance(away_da, (int, float))
                and home_da > 35 and away_da > 35
                else "⚠️ TIGHT"
                if isinstance(home_da, (int, float)) and isinstance(away_da, (int, float))
                else "⚠️ UNAVAILABLE"
            )
            
            # --- DYNAMIC SYMMETRIC BTTS (GG) LOGIC ---
            h_leak = home_audit['gk_leak']
            a_leak = away_audit['gk_leak']
            leak = lambda value, threshold: isinstance(value, (int, float)) and value >= threshold

            gg_label = "Weak"
            if leak(h_leak, 1.50) and leak(a_leak, 1.50):
                gg_label = "Excellent"
            elif ((leak(h_leak, 1.40) and leak(a_leak, 1.50) and home_audit['breach']) or
                  (leak(a_leak, 1.40) and leak(h_leak, 1.50) and away_audit['breach'])):
                gg_label = "Very Strong"
            elif ((leak(h_leak, 1.40) and leak(a_leak, 1.50)) or
                  (leak(a_leak, 1.40) and leak(h_leak, 1.50))):
                gg_label = "Strong"
            elif style_align == "🔥 OPEN" and (home_audit['breach'] or away_audit['breach']):
                gg_label = "Strong"

            # Construct the final data card
            match_card = {
                "fixture": fx['name'], "fixture_id": fx['id'],
                "home_team": home_audit, "away_team": away_audit,
                "style_alignment": style_align,
                "match_chemistry_list": {
                    "Corner": (
                        "Elite"
                        if ((isinstance(home_da, (int, float)) and home_da > 65)
                            or (isinstance(away_da, (int, float)) and away_da > 65))
                        else "Strong"
                    ),
                    "Gg": gg_label
                }
            }

            # ==================================================================
            # 📋 TACTICAL INTELLIGENCE PRINTOUT
            # ==================================================================
            print(f"MATCH: {match_card['fixture']} (ID: {match_card['fixture_id']})")
            print(f"Handshake: [ Alignment: {match_card['style_alignment']} | GG: {gg_label} ]")
            for side, data in[("HOME", home_audit), ("AWAY", away_audit)]:
                print(f"  [{side}] {data['team_name']} -> {data['danger_level']} "
                      f"[{data.get('regime')}] "
                      f"(net {data['net_impact']:+.1f} | conf {data['impact_confidence']:.2f} | "
                      f"GK {data.get('gk_verdict')})")
                print(f"      WHY: {data.get('verdict_reason')}")
                if data['missing_details']:
                    missing_str = ", ".join(
                        f"{p['name']} ({p['pos']}"
                        + (f", rtg {p['rating']:.2f}" if p.get('rating') else ", no rating")
                        + f", {p.get('apps') or 0} apps)"
                        for p in data['missing_details'])
                    print(f"    ABSENT: {missing_str}")
            print("-" * 120)

            output_pool.append(match_card)
            processed_count += 1

            # Record the signed call so its effect can be scored once the
            # fixture finishes. `rotation_uplift` is the number under test: it
            # claims a rotated side scores more, and the ledger is what turns
            # that claim into a measurement instead of an assumption.
            ledger_rows.append({
                "fixture_id": fx.get("id"),
                "fixture": fx.get("name"),
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "regime": fav_regime,
                "sides": [{
                    "team_id": side["id"],
                    "team_name": side["team_name"],
                    "verdict": side["verdict"],
                    "net_impact": side["net_impact"],
                    "confidence": side["impact_confidence"],
                    "missing_count": len(side["missing_details"]),
                    "rotation_uplift": side["rotation_uplift"],
                    "gk_verdict": side.get("gk_verdict"),
                    "style": side["style"].get("label"),
                } for side in (home_audit, away_audit)],
            })
            time.sleep(REQUEST_DELAY)
            
        except Exception as e: continue

    # 💾 SAVE TO JSON FOR THE MASTER AGGREGATOR (never emptied by a FAILED pull)
    write_feed(OUTPUT_FILE, output_pool,
               acquisition_ok=not acq_failed, label="danger_audit.json")
    _save_history_cache()
    logged = save_ledger(ledger_rows)

    # Verdict spread for this cycle. A board that is almost entirely DANGER
    # (or almost entirely ROTATION) is the signal that the evidence base still
    # cannot support a call — which is a fact worth seeing, not a bug to hide.
    if output_pool:
        from collections import Counter as _C
        spread = _C()
        for row in output_pool:
            for side in ("home_team", "away_team"):
                spread[row[side].get("verdict", "UNKNOWN")] += 1
        print(f"[SIGNED IMPACT] verdict spread: {dict(spread)}")
        confs = [row[s]["impact_confidence"]
                 for row in output_pool for s in ("home_team", "away_team")]
        if confs:
            print(f"[SIGNED IMPACT] mean confidence {sum(confs)/len(confs):.2f} "
                  f"(min {min(confs):.2f}) · {len(confs)} sides judged")
    print(f"[ROTATION LEDGER] {logged} call(s) recorded for later scoring")

    print(f"\n[🏆] SUPREME AUDIT COMPLETE: {processed_count} PROFILES SAVED TO DATA DIR")
    
    return output_pool

if __name__ == "__main__":
    run_danger_forensic_aggregator()