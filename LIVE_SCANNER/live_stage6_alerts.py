import os
import sys
import re
import time
import json
import requests
import threading
import logging
import math
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from collections import deque
from dotenv import load_dotenv

# ── SHARED 429 COOLDOWN GATE (live-stage side) ───────────────────────────────
# Mirrors live_stage1_prematch: the archiver/stages broadcast cooldown windows
# into data/api_429_cooldown.lock; GET() paces itself through them so the
# components stop re-triggering each other's burst limits.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATE_FILE = os.path.join(_BASE_DIR, "data", "api_429_cooldown.lock")


def _api_gate_pace(tag=""):
    """Sleep while a shared 429 cooldown is active (cheap no-op otherwise).
    A few seconds of JITTER stagger the wake-up: without it every process
    reads the same gate expiry and fires its next request on the same second,
    re-triggering the burst limit and re-arming the gate (the cooling circle)."""
    try:
        with open(_GATE_FILE, "r") as f:
            gate = json.load(f)
        until = float(gate.get("until", 0)) if isinstance(gate, dict) else 0.0
        remaining = until - time.time()
        if remaining > 0:
            sleep_s = min(remaining, 15.0) + random.random() * 3.0
            logging.getLogger("alienedge.stage6").info(
                f"[API GATE] {tag}: shared cooldown active — pacing {sleep_s:.1f}s")
            time.sleep(sleep_s)
    except Exception:
        pass


def _api_gate_broadcast(wait_s, tag=""):
    """Record a shared cooldown so sibling processes also back off."""
    try:
        os.makedirs(os.path.dirname(_GATE_FILE), exist_ok=True)
        with open(_GATE_FILE + ".tmp", "w") as f:
            json.dump({"until": time.time() + wait_s, "by": tag or "live-stage"}, f)
        os.replace(_GATE_FILE + ".tmp", _GATE_FILE)
    except Exception:
        pass


def _api_gate_clear(tag=""):
    """A 200 just came back from the provider — the burst window is clearly
    over, so DISARM the shared cooldown instead of letting every sibling keep
    pacing until the old expiry (gate hygiene; prevents the hours-long
    cooling circle a single broadcast used to cause)."""
    try:
        os.makedirs(os.path.dirname(_GATE_FILE), exist_ok=True)
        with open(_GATE_FILE + ".tmp", "w") as f:
            json.dump({"until": 0, "by": f"cleared:{tag or 'live-stage'}"}, f)
        os.replace(_GATE_FILE + ".tmp", _GATE_FILE)
    except Exception:
        pass


from LIVE_SCANNER.user_rules_store import list_rules, evaluate_rule_for_match

# --- 1. HOSTING & ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR,   exist_ok=True)

AGGREGATOR_REPORT_FILE   = os.path.join(DATA_DIR,   "aggregator_report.json")
SH_GG_WINNER_FILE        = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")
# NEW: JSON snapshot of the orchestrator board, written every cycle so the
# API (a separate process) can read it. print_orchestrator_board() only
# wrote to console/system.log (plain text) — this is the missing JSON twin.
ORCHESTRATOR_BOARD_FILE  = os.path.join(OUTPUT_DIR, "orchestrator_board.json")
# Live dashboard board for /api/live/dashboard (previously read a file that no
# component ever wrote — the endpoint always returned []).
LIVE_DASHBOARD_FILE      = os.path.join(OUTPUT_DIR, "live_dashboard.json")
# NEW: Stage 1's GK liability + missing-key-player audit, written by the
# additive patch to live_stage1_prematch.py. Third prematch source, merged
# into the same `db` dict as the other two — never overwrites their fields.
PREMATCH_TEAM_AUDIT_FILE  = os.path.join(DATA_DIR,   "prematch_team_audit.json")
CACHE_FILE                = os.path.join(DATA_DIR,   "squad_cache.json")
OUTPUT_ALERTS_FILE        = os.path.join(OUTPUT_DIR, "ready_to_push.json")
LOG_FILE                  = os.path.join(OUTPUT_DIR, "system.log")

SESSION_ID       = datetime.now().strftime("%Y%m%d_%H%M%S")
SESSION_LOG_FILE = os.path.join(OUTPUT_DIR, f"alerts_{SESSION_ID}.json")

# ==============================================================================
# LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
API_TOKEN   = os.getenv("SPORTMONKS_API_KEY")
BASE_URL    = "https://api.sportmonks.com/v3/football/livescores/inplay"
HISTORY_URL = "https://api.sportmonks.com/v3/football"

# Thresholds — lowered for real match conditions
CONFIDENCE_PREMIUM_THRESHOLD  = 50
CONFIDENCE_STANDARD_THRESHOLD = 30
PRESSURE_SHARE_THRESHOLD      = 55
MIN_CHAOS_FOR_FUSED            = 5.0
# How long an alert may stay "pending" before it is declared unverifiable.
# The FT snapshot only retains a day or two, so beyond this the score is
# simply gone and the honest answer is "cannot verify", not "in progress".
STALE_PENDING_AFTER_S = 48 * 3600

# ==============================================================================
# THE STORM TRACK — three escalating gates instead of one
# ==============================================================================
# WHY THIS EXISTS
# Code 6 alerted on only 9 fixtures over 11 days. The cause is NOT the polling
# cadence: the scanner already cycles every ~3 minutes (115-161s of work plus a
# 45s sleep). It is three separate constraints, and only one of them is about
# time:
#
#   1. The structural test is STATIC. `h_triple` is the home squad's average
#      pre-match "doom" rating being 2x the away squad's. It is computed from
#      the squad cache and does not change at 60'. A team structurally broken
#      at 40' is still broken at 75'.
#   2. The handshake was only ever evaluated inside `30 <= minute < 45` — a
#      15-minute window. Sixty of the match's seventy-five eligible minutes
#      were simply never tested, even though the underlying condition holds
#      for the whole match.
#   3. The alert key was "{f_id}_SUPREME_45" and is in ALERT_HISTORY forever,
#      so a fixture could fire exactly once, ever.
#
# The fix multiplies the SURFACE AREA, never loosens the bar. The 2x doom
# ratio and the 50% opposing-pressure test are identical in all three gates.
# We simply ask the same strict question at three points in the match instead
# of one, and each gate keeps its own one-shot key so nothing can repeat.
#
# The late gate demands a HIGHER confidence bar, so precision rises as the
# window widens rather than falling.
#
# GATE 1 IS BYTE-FOR-BYTE THE ORIGINAL CONDITION. It is not modified, relaxed
# or reordered — a contract test pins this.
STORM_GATES = (
    # (key suffix, window start, window end, min confidence, stage label)
    ("SUPREME_45", 30, 45, CONFIDENCE_STANDARD_THRESHOLD, "developing"),
    ("SUPREME_60", 45, 60, CONFIDENCE_STANDARD_THRESHOLD, "sustained"),
    ("SUPREME_75", 60, 75, CONFIDENCE_PREMIUM_THRESHOLD,  "peaking"),
)

# Per-fixture storm progression, updated every cycle but NEVER alertable.
# It exists so the UI can show a storm building before any alert has fired.
STORM_STATE = {}

# GLOBAL STATE
SQUAD_VAULT        = {}
LIVE_METRICS_VAULT = {}
VALIDATION_STATE   = {}
MARKET_SETTLEMENT  = {}
ALERT_HISTORY      = set()
SESSION_ALERTS     = []
# NEW: per-fixture key-11 id sets + live loss counters, mirrors the pattern
# already proven in live_stage2_verification.py's MATCH_CONTEXT_CACHE, but
# scoped to Code 6 so it doesn't depend on Stage 2 running.
KEY_PLAYER_TRACKING = {}

cache_lock    = threading.Lock()
alert_lock    = threading.Lock()
FETCHING_TEAMS = set()
FETCHING_LOCK  = threading.Lock()

# ==============================================================================
# UTILITIES
# ==============================================================================
def load_memory():
    global SQUAD_VAULT
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            # ── FIX: Normalise cache format ───────────────────────────────
            # Old cache stored flat {pid: {...}} per team.
            # New format stores {"players": {...}, "team_avg_leak": float}.
            # If we load old format entries the engine crashes with
            # KeyError: 'home_sq' / 'away_sq' because the Detective's
            # get_squad_data returns the flat dict directly.
            # Fix: wrap any flat dict into the new format on load.
            normalised = {}
            for tid, entry in raw.items():
                if isinstance(entry, dict):
                    if "players" in entry:
                        # Already new format — use as-is
                        normalised[tid] = entry
                    else:
                        # Old flat format — wrap it
                        normalised[tid] = {
                            "players":       entry,
                            "team_avg_leak": 1.2
                        }
            SQUAD_VAULT = normalised
            logging.info(
                f"MEMORY RESTORED: {len(SQUAD_VAULT)} teams loaded "
                f"(normalised to new format)"
            )
        except Exception as e:
            logging.error(f"Memory Load Failed: {e}")
            SQUAD_VAULT = {}

def save_memory():
    with cache_lock:
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(SQUAD_VAULT, f)
        except Exception as e:
            logging.error(f"Memory Save Failed: {e}")

def safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur

def build_prematch_db():
    """
    THE MERGE OF ALL FOUR PREMATCH SOURCES, keyed by fixture_id.

    Promoted out of SupremeOrchestrator.load_all_prematch_data() so the
    rules API can score the setup board's candidate matches with the
    identical merge the live cycle uses. Two copies of this merge would
    drift, and a candidate board that disagrees with what actually fires
    is worse than no board at all.

    Read-only and total: a missing or malformed source is logged and
    skipped, never fatal, and always returns whatever did load.
    """
    db = {}

    if os.path.exists(AGGREGATOR_REPORT_FILE):
        try:
            with open(AGGREGATOR_REPORT_FILE, 'r', encoding='utf-8') as f:
                data  = json.load(f)
                items = data if isinstance(data, list) else data.values()
                for item in items:
                    fid = str(item.get('fixture_id'))
                    db[fid] = item
                    if 'h_id' not in item:
                        dr = item.get('danger_report', {})
                        db[fid]['h_id'] = str(
                            dr.get('home', {}).get('id', '')
                        )
                        db[fid]['a_id'] = str(
                            dr.get('away', {}).get('id', '')
                        )
        except Exception as e:
            logging.warning(f"Aggregator file error: {e}")

    if os.path.exists(SH_GG_WINNER_FILE):
        try:
            with open(SH_GG_WINNER_FILE, 'r', encoding='utf-8') as f:
                data  = json.load(f)
                items = data if isinstance(data, list) else data.values()
                for item in items:
                    fid = str(item.get('fixture_id'))
                    if fid not in db: db[fid] = item
                    else:             db[fid].update(item)
                    if 'h_id' not in db[fid]:
                        db[fid]['h_id'] = str(
                            safe_get(item,'teams','home','id') or ''
                        )
                        db[fid]['a_id'] = str(
                            safe_get(item,'teams','away','id') or ''
                        )
        except Exception as e:
            logging.warning(f"SH-GG file error: {e}")

    # NEW: Gold Over 2.5 engine feed — fourth prematch source, same
    # fixture_id-keyed merge pattern as SH-GG above. Some fixtures carry
    # their prematch flags ONLY here (e.g. h2h_o25_100 from the gold
    # engine), so without this merge user rules referencing those flags
    # could never fire. flags/metrics are dict-merged so a fixture present
    # in both feeds keeps the union of flags instead of being clobbered.
    GOLD_O25_FILE = os.path.join(OUTPUT_DIR, "gold_over_25_feed.json")
    if os.path.exists(GOLD_O25_FILE):
        try:
            with open(GOLD_O25_FILE, 'r', encoding='utf-8') as f:
                data  = json.load(f)
                items = data if isinstance(data, list) else data.values()
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    fid = str(item.get('fixture_id'))
                    if not fid or fid == 'None':
                        continue
                    if fid not in db:
                        db[fid] = item
                    else:
                        for k, v in item.items():
                            if (k in ("flags", "metrics")
                                    and isinstance(v, dict)
                                    and isinstance(db[fid].get(k), dict)):
                                db[fid][k].update(v)
                            else:
                                db[fid].setdefault(k, v)
                    if 'h_id' not in db[fid]:
                        db[fid]['h_id'] = str(
                            safe_get(item,'teams','home','id') or ''
                        )
                        db[fid]['a_id'] = str(
                            safe_get(item,'teams','away','id') or ''
                        )
        except Exception as e:
            logging.warning(f"Gold O2.5 file error: {e}")

    # NEW: Stage 1's GK liability + missing-key-player audit — third
    # prematch source. Keyed by fixture_id like the other two. Uses
    # dict.update() so it never overwrites flags/chemistry already
    # merged in above; it only adds the "home"/"away" audit block.
    if os.path.exists(PREMATCH_TEAM_AUDIT_FILE):
        try:
            with open(PREMATCH_TEAM_AUDIT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for fid, item in data.items():
                    fid = str(fid)
                    if fid not in db:
                        db[fid] = {}
                    db[fid]['team_audit'] = item
                    if 'h_id' not in db[fid] and 'home' in item:
                        db[fid]['h_id'] = str(item['home'].get('team_id', ''))
                        db[fid]['a_id'] = str(item['away'].get('team_id', ''))
        except Exception as e:
            logging.warning(f"Prematch team audit file error: {e}")

    return db



def GET(url, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_TOKEN)
    _api_gate_pace("stage6")
    backoff = 2.0
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200:
                _api_gate_clear("stage6")
                return r.json()
            elif r.status_code == 429:
                try:
                    gate_wait = float(r.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    gate_wait = 0.0
                gate_wait = max(gate_wait, backoff)
                # CAP the shared window (see stage3): giant Retry-After values
                # (~20 min) must not freeze every sibling process.
                _api_gate_broadcast(min(gate_wait, 120.0), "stage6")
                time.sleep(min(gate_wait, 30.0))
                backoff *= 2
                continue
            r.raise_for_status()
        except Exception:
            time.sleep(1); continue
    return {"data": []}

# ==============================================================================
# 🧠 MODULE 1: SYNTHETIC INTELLIGENCE BRAIN
# ==============================================================================
class SyntheticIntelligenceBrain:
    def __init__(self):
        self.W_P_SOT  = 2.0
        self.W_P_BOX  = 1.5
        self.W_P_DA   = 0.6
        self.W_P_CORN = 0.5
        self.W_X_SOT  = 0.45
        self.W_X_BOX  = 0.25
        self.W_X_DA   = 0.15
        self.W_X_CORN = 0.10
        self.W_X_POS  = 0.05

    def compute_team_metrics(self, f_id, stats, side, minute):
        if f_id not in LIVE_METRICS_VAULT:
            LIVE_METRICS_VAULT[f_id] = {
                "home": deque(maxlen=25),
                "away": deque(maxlen=25)
            }

        sot  = int(stats.get('shots-on-target',  0))
        box  = int(stats.get('box',               0))
        da   = int(stats.get('dangerous-attacks', 0))
        corn = int(stats.get('corners',            0))
        pos  = int(stats.get('ball-possession',   50))

        pressure = ((sot  * self.W_P_SOT) + (box  * self.W_P_BOX) +
                    (da   * self.W_P_DA)  + (corn * self.W_P_CORN))
        live_xg  = ((sot  * self.W_X_SOT) + (box  * self.W_X_BOX) +
                    (da   * self.W_X_DA)  + (corn * self.W_X_CORN) +
                    (pos  * self.W_X_POS / 100))

        buf = LIVE_METRICS_VAULT[f_id][side]
        buf.append({
            "xg": live_xg, "min": minute,
            "da": da, "sot": sot, "pressure": pressure
        })

        recent = [x['xg'] for x in buf if x['min'] > (minute - 10)]
        rolling = sum(recent) / len(recent) if recent else 0

        last5 = [x['xg'] for x in buf if x['min'] > (minute - 5)]
        prev5 = [x['xg'] for x in buf
                 if (minute - 10) < x['min'] <= (minute - 5)]
        accel = ((sum(last5)/len(last5)) - (sum(prev5)/len(prev5))
                 if (last5 and prev5) else 0.0)

        return {
            "pressure_raw":  pressure,
            "live_xg":       round(live_xg,    2),
            "rolling_10_xg": round(rolling,    2),
            "acceleration":  round(accel,       2),
            "da_velocity":   round(da / max(1, minute), 2),
            "sot": sot, "box": box, "da": da, "corn": corn
        }

    def analyze_match_state(self, f_id, h_s, a_s, minute, events):
        h = self.compute_team_metrics(f_id, h_s, "home", minute)
        a = self.compute_team_metrics(f_id, a_s, "away", minute)

        total_p   = h['pressure_raw'] + a['pressure_raw']
        h_p_share = (h['pressure_raw'] / total_p * 100) if total_p > 0 else 50

        total_xg = h['live_xg'] + a['live_xg']
        h_dom    = (h['live_xg'] / total_xg * 100) if total_xg > 0 else 50

        recent_e = [e for e in events if (e.get('minute') or 0) > (minute - 12)]
        cards    = len([e for e in recent_e
                        if "card" in str(safe_get(e,"type","code",default=""))])
        c_burst  = len([e for e in recent_e
                        if safe_get(e,"type","code") == "corner"])
        chaos    = ((c_burst * 2.5) + (cards * 4.0) +
                    ((h['da_velocity'] + a['da_velocity']) * 10))

        # Confidence scoring — generous scaling for real match conditions
        pressure_score   = min(60, total_p * 1.2)
        chaos_score      = min(40, chaos * 3.0)
        confidence_score = round(min(100, pressure_score + chaos_score), 1)

        return {
            "home":  h,
            "away":  a,
            "match": {
                "total_pressure":   round(total_p,       2),
                "h_pressure_share": round(h_p_share,     1),
                "a_pressure_share": round(100-h_p_share, 1),
                "h_dominance":      round(h_dom,         1),
                "a_dominance":      round(100-h_dom,     1),
                "chaos_index":      round(chaos,         2),
                "xg_diff_slope":    round(h['live_xg'] - a['live_xg'], 2),
                "confidence_score": confidence_score
            }
        }

# ==============================================================================
# 🕵️ MODULE 2: STRUCTURAL FORENSIC DETECTIVE
# ==============================================================================
class StructuralDetective:
    def get_squad_data(self, team_id):
        tid_str = str(team_id)
        if tid_str in SQUAD_VAULT:
            entry = SQUAD_VAULT[tid_str]
            # ── FIX: Safe format check ────────────────────────────────────
            # If the cached entry is the new format, return players dict.
            # If it is the old flat format, return it directly but also
            # migrate it so next access is correct.
            if isinstance(entry, dict) and "players" in entry:
                # FIX 6 (squad coverage): an EMPTY players dict is the
                # poisoned residue of a failed/empty fetch (e.g. Huracán
                # id 410 had 16 fixtures in its 150-day window yet an
                # empty vault entry that could never recover, because
                # both this guard and maintenance_thread's
                # `str(tid) in SQUAD_VAULT` check treated it as valid
                # data forever → INSUFFICIENT_SQUAD_DATA permanently).
                # Treat empty as a cache MISS and refetch. Non-empty
                # entries keep the exact same short-circuit as before.
                if entry["players"]:
                    return entry["players"]
                # empty → fall through to a fresh fetch below
            else:
                # Old flat format — migrate in place
                if entry:
                    SQUAD_VAULT[tid_str] = {
                        "players":       entry,
                        "team_avg_leak": 1.2
                    }
                    return entry
                # empty flat dict → fall through to a fresh fetch below

        start_dt = (datetime.now(timezone.utc).date()
                    - timedelta(days=150)).isoformat()
        end_dt   = (datetime.now(timezone.utc).date()
                    - timedelta(days=1)).isoformat()
        url      = (f"{HISTORY_URL}/fixtures/between/"
                    f"{start_dt}/{end_dt}/{team_id}")

        resp = GET(url, params={
            "include":  "lineups.details.type;lineups.player.position;"
                        "scores;participants",
            "per_page": 25
        })

        stats = {}
        for fx in resp.get("data", []):
            hid = str(safe_get(fx, "participants", 0, "id"))
            h_g = safe_get(fx, "scores", 0, "score", "goals", default=0)
            a_g = safe_get(fx, "scores", 1, "score", "goals", default=0)
            opp_goals = a_g if tid_str == hid else h_g

            for l in fx.get("lineups", []):
                if str(l.get("team_id")) == tid_str:
                    pid = str(l.get("player_id"))
                    if not l.get("player"): continue
                    m_val = r_val = 0.0; c_val = -1.0
                    for d in l.get("details", []):
                        t_name = str(
                            d.get('type', {}).get('name', '')
                        ).lower()
                        raw_v  = (d.get("data", {}).get("value")
                                  or d.get("value"))
                        try: val = float(str(raw_v).replace('%', ''))
                        except: val = 0.0
                        if "minutes"  in t_name: m_val = val
                        elif "rating" in t_name: r_val = val
                        elif "conceded" in t_name: c_val = val

                    if m_val == 0 and \
                       str(l.get("formation_position")) == "1":
                        m_val = 90
                    if c_val == -1.0: c_val = float(opp_goals)

                    if pid not in stats:
                        stats[pid] = {
                            "ratings":      [],
                            "apps":         0,
                            "mins":         0,
                            "conceded":     0,
                            "clean_sheets": 0,
                            "pos": safe_get(l["player"], "position", "name")
                        }
                    stats[pid]["mins"] += m_val
                    stats[pid]["apps"] += 1
                    if r_val > 0: stats[pid]["ratings"].append(r_val)
                    if m_val > 0:
                        stats[pid]["conceded"] += c_val
                        if c_val == 0: stats[pid]["clean_sheets"] += 1

        processed = {}
        for pid, d in stats.items():
            avg_r  = (sum(d["ratings"]) / len(d["ratings"])
                      if d["ratings"] else 6.0)
            worth  = (d["apps"] * 5000) + (d["mins"] * avg_r)
            c_p90  = (d["conceded"] / d["mins"]) * 90 if d["mins"] > 0 else 0.0
            doom   = ((c_p90 * 0.6) +
                      ((1 - (d["clean_sheets"] / d["apps"]
                              if d["apps"] > 0 else 0)) * 2))
            processed[pid] = {
                "worth": worth, "doom": doom, "pos": d["pos"]
            }

        # Store in new format
        with cache_lock:
            SQUAD_VAULT[tid_str] = {
                "players":       processed,
                "team_avg_leak": 1.2
            }
        save_memory()
        return processed

    def investigate(self, ctx, pre):
        # ── FIX: Safe key access for home/away IDs ────────────────────────
        # Original code accessed ctx['home']['id'] and ctx['away']['id']
        # directly. If extract_impact_context failed to find a participant
        # those keys were None and the squad lookup silently returned {}.
        # Now we validate before looking up.
        h_id = str(ctx.get('home', {}).get('id') or '')
        a_id = str(ctx.get('away', {}).get('id') or '')

        if not h_id or not a_id:
            return {"status": "MISSING_TEAM_IDS"}

        # ── FIX: Access players sub-dict correctly ─────────────────────────
        # SQUAD_VAULT stores {"players": {...}, "team_avg_leak": float}
        # The old code did SQUAD_VAULT.get(h_id, {}) which returned the
        # whole entry including "players" key, then iterated it as if
        # it were the player dict. This caused 'tier' KeyError downstream
        # because it was iterating over {"players":..., "team_avg_leak":...}
        # Fix: always extract the "players" sub-dict.
        h_entry = SQUAD_VAULT.get(h_id, {})
        a_entry = SQUAD_VAULT.get(a_id, {})

        h_sq = (h_entry.get("players", {})
                if isinstance(h_entry, dict) and "players" in h_entry
                else h_entry)
        a_sq = (a_entry.get("players", {})
                if isinstance(a_entry, dict) and "players" in a_entry
                else a_entry)

        if not h_sq or not a_sq:
            return {"status": "INSUFFICIENT_SQUAD_DATA"}

        # Safety check: skip if values are not player dicts
        # (catches migrated flat entries with unexpected structure)
        def is_player_dict(d):
            return isinstance(d, dict) and any(
                isinstance(v, dict) and 'doom' in v
                for v in d.values()
            )

        if not is_player_dict(h_sq) or not is_player_dict(a_sq):
            return {"status": "STALE_CACHE_FORMAT"}

        h_doom_avg = (sum(p['doom'] for p in h_sq.values()) / len(h_sq)
                      if h_sq else 0)
        a_doom_avg = (sum(p['doom'] for p in a_sq.values()) / len(a_sq)
                      if a_sq else 0)

        # Doom threshold: 2x (was 3x — more matches qualify)
        h_triple = (h_doom_avg >= a_doom_avg * 2) if a_doom_avg > 0 else False
        a_triple = (a_doom_avg >= h_doom_avg * 2) if h_doom_avg > 0 else False

        return {
            "h_doom":   h_doom_avg,
            "a_doom":   a_doom_avg,
            "h_triple": h_triple,
            "a_triple": a_triple,
            "h_red":    ctx['impact']['home']['reds'] > 0,
            "a_red":    ctx['impact']['away']['reds'] > 0,
            "h_gk":     ctx['impact']['home']['gk_risk'],
            "a_gk":     ctx['impact']['away']['gk_risk'],
        }

    # ── NEW: KEY-11 IDENTIFICATION (mirrors live_stage2_verification.py's
    # get_k() helper) ────────────────────────────────────────────────────
    def build_key_ids(self, team_id):
        """
        Returns the set of player ids considered 'key' for this team: the
        top-worth goalkeeper plus the top-10-worth outfield players, using
        the exact same SQUAD_VAULT worth data already computed for doom
        scoring. Used only to detect a REAL key player being subbed off
        during a live match — separate from Stage 1's prematch missing-count.
        """
        squad = self.get_squad_data(team_id)
        if not squad:
            return set()
        players = list(squad.values())
        gks = sorted(
            [p for p in players if str(p.get('pos')) == "Goalkeeper"],
            key=lambda x: x.get('worth', 0), reverse=True
        )
        outfield = sorted(
            [p for p in players if str(p.get('pos')) != "Goalkeeper"],
            key=lambda x: x.get('worth', 0), reverse=True
        )
        key_players = (gks[:1] + outfield[:10])
        # NOTE: SQUAD_VAULT entries don't carry their own pid as a key here
        # (StructuralDetective.get_squad_data indexes by pid already), so
        # ids must be pulled from the dict keys, not values.
        key_ids = set()
        for pid, p in squad.items():
            if p in key_players:
                key_ids.add(pid)
        return key_ids

# ==============================================================================
# 🎯 MODULE 3: USER-RULE EVALUATOR
# ==============================================================================
class UserRuleEvaluator:
    """
    Loads every ACTIVE rule saved by every user (user_rules_store.py) and
    checks each one against this match. Each firing rule becomes its own
    alert, tagged with the user_id/rule_id that triggered it, so the
    frontend can show each user only their own alerts.
    """
    def evaluate(self, f_id, intel, structural, pre, minute, key_loss, all_rules,
                 score=None):
        """
        `score` is the running (h, a) scoreline for this fixture, already read
        by score_from_fixture() and already handed to fire_alert(). It is
        threaded through here so a user rule with a scoreline GATE can ask
        "is this trade still available?" before the alert is raised — the one
        question the prematch condition alone can never answer.

        Defaulted to None so any existing caller keeps working, and None means
        "unreadable", which the gate treats as a refusal to fire rather than
        as a 0-0.
        """
        triggered = []
        conf = intel['match']['confidence_score']

        if conf >= CONFIDENCE_PREMIUM_THRESHOLD:
            tier = "🔥 PREMIUM"
        elif conf >= CONFIDENCE_STANDARD_THRESHOLD:
            tier = "✅ STANDARD"
        else:
            tier = "📊 MONITOR"

        for rule in all_rules:
            hit = evaluate_rule_for_match(
                rule, intel, pre, minute, key_loss,
                score=score, fixture_id=f_id,
            )
            if hit is None:
                continue
            triggered.append({
                "id":        f"{f_id}_{hit['rule_id']}",
                "msg":       hit["note"],
                "tier":      tier,
                "conf":      conf,
                "user_id":   hit["user_id"],
                "rule_id":   hit["rule_id"],
                "rule_label": hit["label"],
                # Soft preference — surfaced for ranking and marking only. It
                # never suppressed this alert; it is recorded because the user
                # personally accepted this match in the setup board.
                "watchlisted": hit.get("watchlisted", False),
                "score":       hit.get("score"),
                "gate":        hit.get("gate"),
            })

        return triggered

# ==============================================================================
# 🔄 THE SUPREME ORCHESTRATOR
# ==============================================================================
class SupremeOrchestrator:
    def __init__(self):
        self.Brain     = SyntheticIntelligenceBrain()
        self.Detective = StructuralDetective()
        self.UserLogic = UserRuleEvaluator()
        self.executor  = ThreadPoolExecutor(max_workers=5)
        self.cycle     = 0
        # rule_id -> the live fixtures matching it THIS cycle. Rebuilt from
        # scratch every cycle so it always describes the present moment; a stale
        # entry would claim a match is still live after it has finished.
        self._rule_live = {}
        # FIX: seed ALERT_HISTORY from the persisted on-disk alert log so a
        # restart cannot re-fire alerts that already went out. fire_alert()
        # appends every record as one JSONL line in ready_to_push.json while
        # run_single_cycle()/process_ai_gates() track the same keys only in
        # the in-memory ALERT_HISTORY set — a restart wiped that set and the
        # same fixture/rule pair could alert users twice. Rebuild keys:
        #   user-rule alerts  -> "{f_id}_{rule_id}"   (exact match)
        #   system 45' alerts -> "{f_id}_SUPREME_45"  (best-effort, matched
        #   via the stable "45' Verified" msg emitted by process_ai_gates)
        try:
            if os.path.exists(OUTPUT_ALERTS_FILE):
                with open(OUTPUT_ALERTS_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        rec_fid = rec.get('f_id')
                        if not rec_fid:
                            continue
                        if rec.get('rule_id'):
                            ALERT_HISTORY.add(f"{rec_fid}_{rec['rule_id']}")
                        elif "45' Verified" in str(rec.get('msg', '')):
                            ALERT_HISTORY.add(f"{rec_fid}_SUPREME_45")
                logging.info(
                    f"ALERT_HISTORY seeded from disk: "
                    f"{len(ALERT_HISTORY)} previously fired alert keys"
                )
        except Exception as e:
            logging.error(f"ALERT_HISTORY seed failed: {e}")

    def run(self):
        logging.info("═" * 70)
        logging.info("  SOVEREIGN FORENSIC ORCHESTRATOR ONLINE")
        logging.info(f"  Session: {SESSION_ID}")
        logging.info(
            f"  Thresholds: Premium≥{CONFIDENCE_PREMIUM_THRESHOLD}% | "
            f"Standard≥{CONFIDENCE_STANDARD_THRESHOLD}%"
        )
        logging.info("═" * 70)

        while True:
            self.run_single_cycle()
            time.sleep(45)

    def _process_live_fixture(self, fx, db):
        """Analyze one fixture; callers isolate failures per fixture."""
        f_id = str(fx.get("id", ""))
        pre = db.get(f_id, {})
        if not pre and db:
            name_key = self._name_key(fx.get("name", ""))
            for db_entry in db.values():
                db_name = self._name_key(
                    db_entry.get("fixture", db_entry.get("name", ""))
                )
                if db_name and db_name == name_key:
                    pre = db_entry
                    break

        minute = self.extract_minute(fx)
        if not minute or minute <= 0:
            return None

        self.update_market_settlement(f_id, fx)
        # The scoreline at this instant, captured once and handed to
        # fire_alert() so every alert this cycle is anchored to real state.
        # None means "could not be read" — which is recorded honestly as an
        # unverifiable alert rather than as a 0-0 we never actually saw.
        current_score = self.score_from_fixture(fx)
        h_s, a_s = self.extract_stats(fx)
        intel = self.Brain.analyze_match_state(
            f_id, h_s, a_s, minute, fx.get("events", [])
        )
        ctx = self.extract_impact_context(fx)
        structural = self.Detective.investigate(ctx, pre)
        key_loss = self._track_key_player_loss(f_id, ctx, fx)
        fixture_name = fx.get("name", f_id)

        user_alerts = self.UserLogic.evaluate(
            f_id, intel, structural, pre, minute, key_loss,
            list_rules(active_only=True),
            score=current_score,
        )
        # Record WHICH rules match this fixture right now, independent of
        # whether an alert was actually fired. The setup board needs to be able
        # to say "3 of your alerts match a live match right now" — otherwise a
        # rule that has not fired is indistinguishable from a rule that will
        # never fire, and the user cannot tell a working alert from a broken
        # one. This is deliberately a different thing from ALERT_HISTORY, which
        # only ever holds keys that DID fire.
        for ua in user_alerts:
            self._rule_live.setdefault(ua.get("rule_id"), []).append({
                "fixture_id": f_id,
                "name": fixture_name,
                "minute": minute,
                "score": (f"{current_score[0]}-{current_score[1]}"
                          if current_score else None),
                "gate": ua.get("gate"),
                "note": ua.get("msg"),
            })
        fired_this = []
        for ua in user_alerts:
            tier = ua.get("tier")
            alert_id = ua.get("id")
            if (tier in ["🔥 PREMIUM", "✅ STANDARD"]
                    and alert_id not in ALERT_HISTORY):
                self.fire_alert(
                    f_id, fixture_name, tier, ua.get("msg", ""),
                    ua.get("conf", 0), minute,
                    user_id=ua.get("user_id"),
                    rule_id=ua.get("rule_id"),
                    rule_label=ua.get("rule_label"),
                    score=current_score,
                    gate=ua.get("gate"),
                    watchlisted=ua.get("watchlisted", False),
                )
                ALERT_HISTORY.add(alert_id)
                fired_this.append(ua)
            elif tier == "📊 MONITOR":
                fired_this.append(ua)

        self.update_storm_state(f_id, minute, intel, structural)
        self.process_ai_gates(f_id, fixture_name, minute, intel, structural,
                              pre, score=current_score)
        # Storm progression is surfaced on the board so the UI can show a
        # storm building BEFORE any alert has fired. Read-only: the tracker
        # can never raise an alert.
        storm = STORM_STATE.get(f_id)
        return {
            "name": fixture_name,
            "id": f_id,
            "minute": minute,
            # Live team statistics, published from the h_s/a_s this stage
            # ALREADY extracted from the provider payload. The Code 2
            # validator used to be the only source the live page read, but it
            # no longer runs; surfacing the same numbers here costs nothing —
            # no extra provider call, no extra work.
            "statistics": {"home": h_s, "away": a_s},
            "storm": ({
                "stage": storm.get("stage"),
                "first_seen": storm.get("first_seen"),
                "last_seen": storm.get("last_seen"),
                "confidence": storm.get("confidence"),
                "chaos": storm.get("chaos"),
            } if storm else None),
            "conf": intel["match"]["confidence_score"],
            "h_pressure": intel["match"]["h_pressure_share"],
            "a_pressure": intel["match"]["a_pressure_share"],
            "chaos": intel["match"]["chaos_index"],
            "h_xg": intel["home"]["live_xg"],
            "a_xg": intel["away"]["live_xg"],
            "h_sot": intel["home"]["sot"],
            "a_sot": intel["away"]["sot"],
            "structural": structural.get("status", "OK"),
            "key_loss": key_loss,
            "alerts": fired_this,
            "in_db": bool(pre),
        }


    def run_single_cycle(self):
        """Run one full pass, isolating bad fixtures from the cycle board."""
        self.cycle += 1
        # Reset BEFORE any fixture is processed, so the published map is exactly
        # this cycle's truth and never a mixture of two cycles.
        self._rule_live = {}
        db = self.load_all_prematch_data()
        if not db:
            logging.info("[MOCK MODE] No prematch report found. Live-only monitoring active.")
        self.maintenance_thread(db)

        live_data = []
        cycle_matches = []
        fixture_errors = []
        try:
            live_data = self.fetch_live_scores() or []
            if not live_data:
                logging.warning("Stage 6 live feed returned no fixtures; preserving previous board")
                return
            # Request squads for the LIVE fixtures too. Without this, a match
            # absent from the prematch report could never be structurally
            # evaluated, and the storm gates could never fire on it.
            # Isolated for the same reason the result resolver is: a squad
            # cache problem must never cost us the cycle board.
            try:
                self.maintenance_thread({}, live_data)
            except Exception as squad_err:
                logging.warning(
                    "Live squad backfill skipped: %s", squad_err)
            live_ids = {str(fx.get("id")) for fx in live_data if isinstance(fx, dict)}
            self.cleanup_stale_memory(live_ids)
            # Settle any alert whose fixture has now finished, so the page can
            # show the final score against the score at the moment it fired.
            # Runs BEFORE the per-fixture pass and is fully isolated: a failure
            # here must never stop live analysis.
            try:
                self.resolve_alert_results(
                    {str(fx.get("id")): fx for fx in live_data
                     if isinstance(fx, dict)}
                )
            except Exception as exc:
                logging.warning("Alert result resolution skipped: %s", exc)

            # ── DELIVER PUSH NOTIFICATIONS ────────────────────────────────
            # Runs AFTER alerts have been fired this cycle, so a user's own
            # alert is pushed in the same cycle it was raised.
            #
            # This block did not exist: the push pipeline (notifications.py,
            # sw.js, PushToggle, pywebpush, VAPID keys) was all built and
            # wired, but its only caller was the Code 2 validator, which was
            # removed. "Setup my alert" could fire perfectly and still never
            # reach a phone.
            #
            # Fully isolated, in its own try/except, on this module's
            # standing contract: a push failure must never delay, raise
            # through, or fail a live match cycle.
            try:
                import notifications as notify
                summary = notify.dispatch_pending(limit=50)
                if summary.get("sent") or summary.get("pruned"):
                    logging.info(
                        "Push dispatched: sent=%s failed=%s pruned=%s skipped=%s",
                        summary.get("sent"), summary.get("failed"),
                        summary.get("pruned"), summary.get("skipped"),
                    )
            except Exception as exc:
                logging.warning("Push dispatch skipped this cycle: %s", exc)

            for fx in live_data:
                if not isinstance(fx, dict):
                    continue
                try:
                    match = self._process_live_fixture(fx, db)
                    if match is not None:
                        cycle_matches.append(match)
                except Exception as exc:
                    fixture_id = str(fx.get("id", ""))
                    logging.exception("Stage 6 fixture %s failed: %s", fixture_id, exc)
                    fixture_errors.append({
                        "fixture_id": fixture_id,
                        "error": str(exc),
                    })
            if not cycle_matches:
                logging.warning("Stage 6 found no processable live fixtures; preserving previous board")
                return
            self.print_orchestrator_board(cycle_matches, len(live_data), len(db))
            self.save_orchestrator_board(cycle_matches, len(live_data), len(db), fixture_errors)
            self.save_live_dashboard(cycle_matches, len(live_data), len(db), fixture_errors)
        except Exception as exc:
            logging.exception("Engine Loop Failure: %s", exc)



    # ── HELPER: normalise fixture name for matching ───────────────────────
    def _name_key(self, name):
        if not name: return ""
        n = str(name).lower()
        n = re.sub(r'[^a-z0-9]', '', n)
        return n

    # ── NEW: KEY-PLAYER LOSS TRACKER ────────────────────────────────────
    def _track_key_player_loss(self, f_id, ctx, fx):
        """
        Lazily builds each side's key-11 id set (once both squads are
        cached by maintenance_thread), then checks this cycle's
        substitution events against those sets. Returns a small dict the
        rule evaluator can check for a genuinely LIVE "key player lost
        mid-match" condition — distinct from Stage 1's prematch missing
        count, which only knows who never started at all.
        """
        h_id = ctx.get('home', {}).get('id')
        a_id = ctx.get('away', {}).get('id')

        if f_id not in KEY_PLAYER_TRACKING:
            KEY_PLAYER_TRACKING[f_id] = {
                "h_key": None, "a_key": None,
                "h_lost": 0, "a_lost": 0,
                "seen_events": set(),
            }
        track = KEY_PLAYER_TRACKING[f_id]

        if track["h_key"] is None and h_id and str(h_id) in SQUAD_VAULT:
            track["h_key"] = self.Detective.build_key_ids(h_id)
        if track["a_key"] is None and a_id and str(a_id) in SQUAD_VAULT:
            track["a_key"] = self.Detective.build_key_ids(a_id)

        for e in fx.get('events', []):
            code = safe_get(e, "type", "code")
            if code != "substitution":
                continue
            ev_key = f"{e.get('id')}_{e.get('player_id')}_{e.get('minute')}"
            if ev_key in track["seen_events"]:
                continue

            pid = str(e.get("player_id"))
            side_id = str(e.get("participant_id"))

            if side_id == str(h_id) and track["h_key"] and pid in track["h_key"]:
                track["h_lost"] += 1
                track["seen_events"].add(ev_key)
            elif side_id == str(a_id) and track["a_key"] and pid in track["a_key"]:
                track["a_lost"] += 1
                track["seen_events"].add(ev_key)

        return {"h_lost": track["h_lost"], "a_lost": track["a_lost"]}

    # ── ORCHESTRATOR BOARD ────────────────────────────────────────────────
    # ── LIVE DASHBOARD WRITER ────────────────────────────────────────────────
    # /api/live/dashboard reads output/live_dashboard.json, which NO component
    # wrote — the endpoint always returned []. This board is a compact snapshot
    # of the orchestrator cycle (same data the console prints), so persist it
    # here for the API to serve.
    def save_live_dashboard(self, cycle_matches, total_live, total_db,
                           fixture_errors=None):
        try:
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_live": total_live,
                "total_db": total_db,
                "matches": cycle_matches,
                "errors": fixture_errors or [],
            }
            tmp_path = LIVE_DASHBOARD_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            os.replace(tmp_path, LIVE_DASHBOARD_FILE)  # atomic swap
        except Exception as e:
            logging.error(f"[DASHBOARD] Failed to save live dashboard: {e}")

    def print_orchestrator_board(self, cycle_matches, total_live, total_db):
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n{'═'*80}")
        print(
            f"  🛰️  ORCHESTRATOR BOARD — Cycle #{self.cycle} | "
            f"{now} UTC | Session {SESSION_ID}"
        )
        print(
            f"  Live: {total_live} | DB targets: {total_db} | "
            f"Tracking: {len(cycle_matches)}"
        )
        print(f"{'═'*80}")

        if not cycle_matches:
            print("  No live matches with valid minute data found.")
        else:
            for m in cycle_matches:
                db_tag = "🎯 VIP" if m['in_db'] else "👁️  LIVE"
                print(
                    f"\n  {db_tag} {m['name']} | "
                    f"Min {m['minute']}' | Conf: {m['conf']}%"
                )
                print(
                    f"       H-Pressure {m['h_pressure']}% | "
                    f"A-Pressure {m['a_pressure']}% | "
                    f"Chaos {m['chaos']:.1f} | "
                    f"H-xG {m['h_xg']} | A-xG {m['a_xg']} | "
                    f"H-SOT {m['h_sot']} | A-SOT {m['a_sot']} | "
                    f"Key Lost H:{m['key_loss']['h_lost']} A:{m['key_loss']['a_lost']}"
                )
                struct = m.get('structural','OK')
                if struct not in ['OK','']:
                    print(f"       ⚠️  Structural: {struct}")
                if m['alerts']:
                    for ua in m['alerts']:
                        print(f"       {ua.get('tier', '📊 MONITOR')} → {ua.get('msg', '')}")
                else:
                    print("       No alerts this cycle.")

        if SESSION_ALERTS:
            print(f"\n  {'─'*78}")
            print(f"  🔥 SESSION ALERTS FIRED: {len(SESSION_ALERTS)}")
            for a in SESSION_ALERTS[-5:]:
                print(
                    f"    [{a.get('level', a.get('tier', 'UNKNOWN'))}] {a.get('fixture', 'Unknown')} | "
                    f"Min {a.get('minute', '?')}' | Conf {a.get('confidence', a.get('conf', 0))}% | "
                    f"{a.get('msg', '')[:55]}"
                )

                print(f"{'═'*80}\n")

    # ── NEW: JSON BOARD SNAPSHOT (for the API process to read) ─────────────
    def save_orchestrator_board(self, cycle_matches, total_live, total_db,
                               fixture_errors=None):
        # EVALUATION COVERAGE
        #
        # The storm gates need a squad-derived structural reading (one side's
        # average "doom" rating at least twice the other's). Code 6 builds
        # those squads by replaying the LINEUPS of the team's fixtures over
        # the last 150 days. The provider attaches lineups unevenly — U23,
        # women's and lower-league fixtures routinely return fixtures with no
        # lineups at all — so roughly half the live feed cannot be evaluated
        # no matter what the pressure or confidence are.
        #
        # That is a deliberate trade: the strict 2x bar is kept and the
        # unevaluable remainder is REPORTED, not papered over. But silence is
        # not honest. "No alerts" and "the engine was blind" look identical on
        # a blank screen, so the counts are published here and surfaced on the
        # alerts page: an empty day must be readable as a quiet day or a blind
        # day, never left ambiguous.
        evaluated = 0
        unevaluated = 0
        for m in cycle_matches:
            # Only "OK" means the structural test actually ran. The detective
            # can also return INSUFFICIENT_SQUAD_DATA (no squad) or
            # STALE_CACHE_FORMAT (a cached squad in the wrong shape) — both mean
            # the 2x bar was never tested, so neither may count as coverage.
            # Keying on "OK" rather than on one bad code means a future status
            # is unevaluable by default instead of being silently counted as
            # a clean read.
            usable = (str(m.get("structural") or "") or "OK") == "OK"
            m["evaluation"] = "evaluated" if usable else "not_evaluated"
            m["evaluation_note"] = (
                None if usable else
                "No squad could be built for this fixture — the provider "
                "returned no lineup data, so the 2x structural bar could not "
                "be tested. It cannot raise a storm alert."
            )
            if usable:
                evaluated += 1
            else:
                unevaluated += 1
        total_matches = len(cycle_matches)
        # WARM-UP GUARD
        # On a cold start the squad vault is empty until maintenance_thread's
        # background fetches land, so the first cycle or two after every
        # restart reports a near-zero coverage figure. Publishing that as a
        # plain percentage is actively misleading: it reads as "the engine
        # cannot see anything" when the truth is "it has not finished
        # looking yet". Observed live: 0/13 immediately after a restart,
        # then 8/13 (62%) two cycles later with no other change.
        #
        # So while any squad fetch is still in flight the figure is marked
        # provisional and the UI says "still loading" instead of publishing a
        # number that has not settled. A 0% reading is only published once the
        # fetch queue has actually drained, at which point it is real.
        with FETCHING_LOCK:
            still_fetching = len(FETCHING_TEAMS)
        warming_up = still_fetching > 0
        board = {
            "session":   SESSION_ID,
            "cycle":     self.cycle,
            "total_live": total_live,
            "total_db":   total_db,
            "matches":   cycle_matches,
            "errors":    fixture_errors or [],
            # Which of the user's rules match a LIVE fixture at this instant.
            # Read by the rules API to answer "is anything happening for this
            # alert right now?", which the alert log alone cannot: a rule that
            # has never fired looks identical whether it is about to fire or is
            # permanently unsatisfiable.
            "rule_live": getattr(self, "_rule_live", {}) or {},
            "coverage": {
                "evaluated":   evaluated,
                "unevaluated": unevaluated,
                "total":       total_matches,
                "warming_up":  warming_up,
                "pending_fetches": still_fetching,
                "provisional": warming_up,
                "pct":         (round(100.0 * evaluated / total_matches)
                               if total_matches else 0),
                "reason": (
                    "Code 6 rebuilds each squad from the lineups of that "
                    "team's fixtures over the last 150 days. The provider "
                    "attaches lineups unevenly, so fixtures involving U23, "
                    "women's and lower-league teams often return none. Those "
                    "matches are NOT evaluated: the strict 2x structural bar "
                    "is never loosened to cover them, so they simply cannot "
                    "raise a storm alert."
                ),
            },
        }
        try:
            tmp_path = ORCHESTRATOR_BOARD_FILE + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(board, f)
            os.replace(tmp_path, ORCHESTRATOR_BOARD_FILE)  # atomic swap
        except Exception as e:
            logging.error(f"Orchestrator Board Save Failed: {e}")

    # ── AI GATES ─────────────────────────────────────────────────────────
    def process_ai_gates(self, f_id, fixture_name,
                          minute, intel, struct, pre, score=None):
        """
        The storm track: one handshake observation plus three escalating gates.

        GATE 1 IS THE ORIGINAL LOGIC, UNCHANGED. The `30 <= minute < 45`
        handshake and the `minute >= 45` firing condition below are exactly
        what shipped before the storm track existed. Gates 2 and 3 are purely
        additive siblings: same 2x doom test, same 50% opposing-pressure test,
        a different time window, a stricter confidence bar, and their own
        one-shot alert key.

        Gates 2 and 3 deliberately do NOT require VALID_30. A storm can start
        after 45' — that is the whole point of widening the window — so
        requiring the original handshake would make the new gates
        unreachable in exactly the cases they exist to catch.
        """
        conf = intel['match']['confidence_score']

        # ── THE ORIGINAL HANDSHAKE, UNTOUCHED ──────────────────────────
        if 30 <= minute < 45 and f_id not in VALIDATION_STATE:
            if ((struct.get('h_triple') and
                 intel['match']['a_pressure_share'] > 50) or
                (struct.get('a_triple') and
                 intel['match']['h_pressure_share'] > 50)):
                VALIDATION_STATE[f_id] = "VALID_30"
                logging.info(
                    f"[30' Handshake] {fixture_name} — "
                    f"Synchronized (Conf:{conf}%)"
                )

        # ── THE ORIGINAL FIRING CONDITION, UNTOUCHED ───────────────────
        if (minute >= 45 and
                VALIDATION_STATE.get(f_id) == "VALID_30"):
            a_key = f"{f_id}_SUPREME_45"
            if (a_key not in ALERT_HISTORY and
                    conf >= CONFIDENCE_STANDARD_THRESHOLD):
                tier = ("🔥 PREMIUM"
                        if conf >= CONFIDENCE_PREMIUM_THRESHOLD
                        else "✅ STANDARD")
                msg  = (
                    f"{fixture_name} — 45' Verified. "
                    f"Chaos:{intel['match']['chaos_index']:.1f} | "
                    f"H-xG:{intel['home']['live_xg']} "
                    f"A-xG:{intel['away']['live_xg']}"
                )
                self.fire_alert(
                    f_id, fixture_name, tier, msg, conf, minute,
                    storm_stage="developing", score=score,
                )
                ALERT_HISTORY.add(a_key)

        # ── GATES 2 & 3: the storm persists, so re-ask the same question ──
        # Identical structural test to the handshake. Only the window and the
        # confidence bar change, and the bar rises with the window so a late
        # call has to be a stronger one.
        structural_break = (
            (struct.get('h_triple') and
             intel['match']['a_pressure_share'] > 50) or
            (struct.get('a_triple') and
             intel['match']['h_pressure_share'] > 50)
        )
        # EACH WINDOW IS AN INDEPENDENT QUESTION.
        #
        # The windows deliberately overlap and each one fires on its own:
        #   45  — is there a storm NOW?            -> developing
        #   60  — is there still a storm NOW?      -> sustained
        #   75  — is there a storm NOW?            -> peaking
        # A match that still has a storm at 60' SHOULD produce a second alert,
        # because that is new information: the storm persisted. Staying silent
        # after the first alert would hide persistence, which is the whole
        # thing worth seeing. Silence means "no storm in that window", not
        # "already reported".
        #
        # An earlier version suppressed a gate whenever the previous one had
        # fired. That was wrong: it hid exactly the persistence the user wants
        # to see, and it reported a storm caught at 46' as a single event when
        # the engine had in fact confirmed it twice.
        for key_suffix, win_start, win_end, min_conf, stage in STORM_GATES:
            if key_suffix == "SUPREME_45":
                continue                      # gate 1 is handled above
            if not (win_start <= minute <= win_end):
                continue
            if not structural_break:
                continue
            a_key = f"{f_id}_{key_suffix}"
            if a_key in ALERT_HISTORY or conf < min_conf:
                continue
            tier = ("🔥 PREMIUM"
                    if conf >= CONFIDENCE_PREMIUM_THRESHOLD
                    else "✅ STANDARD")
            label = f"{win_start}'-{win_end}'"
            msg = (
                f"{fixture_name} — Storm {stage}. "
                f"Chaos:{intel['match']['chaos_index']:.1f} | "
                f"H-xG:{intel['home']['live_xg']} "
                f"A-xG:{intel['away']['live_xg']} | "
                f"{label} window"
            )
            self.fire_alert(
                f_id, fixture_name, tier, msg, conf, minute,
                storm_stage=stage, score=score,
            )
            ALERT_HISTORY.add(a_key)
            logging.info(
                f"[Storm {stage}] {fixture_name} @ {minute}' "
                f"(Conf:{conf}%) key={a_key}"
            )

    def update_storm_state(self, f_id, minute, intel, struct):
        """
        Track how far a storm has progressed. NEVER alertable.

        This exists purely so the UI can show a storm building before any
        alert has fired. It deliberately cannot raise an alert: adding a
        notification path here would let the page emit signals that never
        passed the gate confidence bars.
        """
        structural_break = bool(
            (struct.get('h_triple') and
             intel['match']['a_pressure_share'] > 50) or
            (struct.get('a_triple') and
             intel['match']['h_pressure_share'] > 50)
        )
        if not structural_break:
            return
        entry = STORM_STATE.setdefault(
            f_id, {"first_seen": minute, "stage": "developing"}
        )
        if minute < entry.get("first_seen", minute):
            entry["first_seen"] = minute
        if minute >= 60:
            entry["stage"] = "peaking"
        elif minute >= 45:
            entry["stage"] = "sustained"
        else:
            entry["stage"] = "developing"
        entry["last_seen"] = minute
        entry["confidence"] = intel["match"]["confidence_score"]
        entry["chaos"] = intel["match"]["chaos_index"]

    # ── ALERT RESULT RESOLVER ─────────────────────────────────────────────
    @staticmethod
    def score_period(fx, period):
        """
        Read a specific named score period, e.g. "FULLTIME", "CURRENT".

        At full time the CURRENT period is gone, so the score is read from the
        FT snapshot instead (see score_at_ft).
        Returns (home, away) or None when the period is absent.
        """
        h = a = None
        for entry in (fx or {}).get("scores", []) or []:
            if not isinstance(entry, dict):
                continue
            s_obj = entry.get("score") or entry
            if period.upper() not in str(s_obj.get("description", "")).upper():
                continue
            side = str(s_obj.get("participant", "")).lower()
            try:
                val = int(s_obj.get("goals"))
            except (TypeError, ValueError):
                continue
            if side == "home":
                h = val
            elif side == "away":
                a = val
        if h is None or a is None:
            return None
        return h, a

    def score_at_ft(self, f_id, fx):
        """
        The authoritative full-time scoreline, or None when it cannot be read.

        ORDER MATTERS
        1. The FT result snapshot (data/ft_result_snapshot.json) is the
           settlement service's own record and is the authority: it already
           carries ft_score / h_ft / a_ft for every finished fixture. This is
           how Serbia vs Netherlands is known to have finished 1-2.
        2. Fall back to the provider fixture's FULLTIME period.

        RETURNS None, NEVER (0, 0)
        A 0-0 that was never actually read is indistinguishable from a real
        goalless draw, and it produces a confident "no further goal" verdict on
        a match that had goals. That is fabricated evidence, which is strictly
        worse than admitting the score is unavailable — so a caller that gets
        None must record `unverifiable` and nothing else.
        """
        snap = self._ft_snapshot_scores(str(f_id))
        if snap:
            return snap
        return self.score_period(fx, "FULLTIME")

    @staticmethod
    def _ft_snapshot_scores(f_id):
        try:
            from settlement_service import load_ft_snapshot
            today = datetime.now().strftime("%Y-%m-%d")
            for day in (today,
                        (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")):
                snap = load_ft_snapshot(day) or {}
                row = snap.get(f_id)
                if not isinstance(row, dict):
                    continue
                if row.get("ft_score"):
                    return (int(row.get("h_ft") or 0),
                            int(row.get("a_ft") or 0))
                if row.get("h_ft") is not None and row.get("a_ft") is not None:
                    return (int(row["h_ft"]), int(row["a_ft"]))
        except Exception:
            return None
        return None

    @staticmethod
    def fixture_is_finished(fx):
        """
        Is this provider fixture finished?

        Delegates to the SHARED classifier (live_state_classifier) rather than
        keeping a private state list, so an alert cannot be marked settled
        under a different definition of "finished" from the one Stage 1,
        Stage 2 and the API use. A disagreement here would settle alerts at
        the wrong moment.
        """
        try:
            from LIVE_SCANNER.live_state_classifier import classify_fixture
            return bool(classify_fixture(fx).get("is_finished", False))
        except Exception:
            return False

    def resolve_alert_results(self, live_by_id):
        """
        Backfill `final_score` and the outcome tag once a fixture is finished.

        An alert is a claim about a moment. Without the final scoreline there
        is no way to check it afterwards, which is why the page previously
        showed alerts as an unfalsifiable list. This runs each cycle over any
        alert still marked `pending` and settles it when the fixture is done.

        `goals_after` is the number of goals scored AFTER the trigger minute —
        that is the question the page actually answers. It is deliberately
        descriptive: `goal_followed` / `no_further_goal` state a fact about
        the scoreline and make no claim about the engine's accuracy.

        The alert log is append-only JSONL, so resolution is achieved by
        rewriting the file with settled fields merged in. That is safe because
        the merge only ever fills fields that are still null/pending, so an
        already-settled alert is never rewritten.
        """
        if not os.path.exists(OUTPUT_ALERTS_FILE):
            return 0
        with alert_lock:
            try:
                with open(OUTPUT_ALERTS_FILE, "r", encoding="utf-8") as f:
                    records = []
                    for line in f:
                        line = line.strip()
                        if not line or line == "[]":
                            continue
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            continue
            except Exception as e:
                logging.error(f"Alert Resolve Read Failed: {e}")
                return 0

            settled = 0
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                if rec.get("outcome") not in (None, "pending"):
                    continue
                f_id = str(rec.get("f_id"))
                fx = live_by_id.get(f_id)
                # A finished fixture LEAVES the in-play feed, usually within the
                # same cycle. The old guard required the fixture to still be in
                # the live feed AND marked finished, so any match that dropped
                # out was never resolved and its card sat on "Match in progress"
                # for good — the verification was silently losing finished
                # matches. The FT snapshot persists finished results
                # independently of the live feed, so try that first and only
                # fall back to the live fixture.
                from_snapshot = self._ft_snapshot_scores(f_id)
                if from_snapshot is None:
                    if not fx:
                        # Gone from the live feed AND no FT record. The match is
                        # over and its score is unrecoverable. Saying
                        # "unverifiable" NOW is honest; waiting (or letting the
                        # 48h age-out do it) leaves a finished match sitting on
                        # "Match in progress", which is how the verification
                        # appeared to be losing finished matches.
                        rec["final_score"] = None
                        rec["goals_after"] = None
                        rec["outcome"] = "unverifiable"
                        rec["unverifiable_reason"] = (
                            "The match is no longer in the live feed and no "
                            "final result is retained for it, so its score "
                            "cannot be read. The FT snapshot keeps roughly a day."
                        )
                        rec["resolved_at"] = datetime.now().isoformat()
                        settled += 1
                        continue
                    if not self.fixture_is_finished(fx):
                        # Still live and not finished — genuinely pending.
                        continue
                # The authoritative FT score, or None. NEVER a defaulted 0-0:
                # a 0-0 we did not actually read yields a confident
                # "no further goal" verdict on a match that had goals, which is
                # fabricated evidence. 17 records were wrong exactly this way
                # before this was fixed.
                ft = self.score_at_ft(rec.get("f_id"), fx)
                h_trig = rec.get("score_home_trigger")
                a_trig = rec.get("score_away_trigger")
                if ft is None:
                    rec["final_score"] = None
                    rec["goals_after"] = None
                    rec["outcome"] = "unverifiable"
                else:
                    h_ft, a_ft = ft
                    rec["final_score"] = f"{h_ft}-{a_ft}"
                    if h_trig is None or a_trig is None:
                        # No trigger scoreline was captured (a record written
                        # before that was added, or the caller had no fixture
                        # data). Say so rather than inventing a 0-0 anchor.
                        rec["goals_after"] = None
                        rec["outcome"] = "unverifiable"
                    else:
                        after = (h_ft - int(h_trig)) + (a_ft - int(a_trig))
                        rec["goals_after"] = max(0, after)
                        rec["outcome"] = ("goal_followed" if after > 0
                                          else "no_further_goal")
                rec["resolved_at"] = datetime.now().isoformat()
                settled += 1

            # AGE-OUT: a pending record whose match finished days ago and whose
            # score is in no longer-retained source must not keep claiming
            # "Match in progress" forever. The FT snapshot only retains a day
            # or two, so older alerts can never be resolved from it. Saying
            # "we looked and could not find the score" is honest; claiming the
            # match is live is not.
            now = datetime.now()
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                if rec.get("outcome") not in (None, "pending"):
                    continue
                stamp = str(rec.get("time") or "")
                try:
                    fired = datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                if (now - fired).total_seconds() > STALE_PENDING_AFTER_S:
                    rec["final_score"] = None
                    rec["goals_after"] = None
                    rec["outcome"] = "unverifiable"
                    rec["resolved_at"] = now.isoformat()
                    rec["unverifiable_reason"] = (
                        "The match finished, but its final score is no longer "
                        "retained by any source this scanner reads, so nothing "
                        "can be verified. The FT snapshot keeps roughly a day."
                    )
                    settled += 1

            if settled:
                try:
                    tmp = OUTPUT_ALERTS_FILE + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        for rec in records:
                            if isinstance(rec, dict):
                                f.write(json.dumps(rec) + "\n")
                    os.replace(tmp, OUTPUT_ALERTS_FILE)
                    logging.info(
                        f"Alert results resolved: {settled} alert(s) settled"
                    )
                except Exception as e:
                    logging.error(f"Alert Resolve Write Failed: {e}")
                    return 0
        return settled

    # ── FIRE ALERT ────────────────────────────────────────────────────────
    def fire_alert(self, f_id, fixture_name,
                   level, msg, confidence, minute,
                   user_id=None, rule_id=None, rule_label=None,
                   storm_stage=None, score=None, gate=None, watchlisted=False):
        """
        Write one alert record.

        `score` is the scoreline at the instant of firing, supplied by the
        caller (it has the provider fixture in hand). It is optional so every
        existing call site keeps working, and it is stored as
        `score_at_trigger` — the anchor the whole verification panel hangs
        from. Without it an alert is an opinion about a moment with no
        recorded state.

        `gate` and `watchlisted` are forwarded from the rule evaluation and are
        used only to compose the push notification. Both are optional so the
        system's own 45' gate, which is not rule-driven, is unaffected.
        """
        now    = datetime.now()
        banner = ("🔥" if "PREMIUM" in level
                  else ("✅" if "STANDARD" in level else "📊"))

        print(f"\n{'━'*80}")
        print(f"  {banner} {level} ALERT | {now.strftime('%H:%M:%S')} UTC")
        print(f"  Match    : {fixture_name}")
        print(f"  Minute   : {minute}'")
        if score is not None:
            print(f"  Score    : {score[0]}-{score[1]}")
        print(f"  Message  : {msg}")
        print(f"  Conf     : {confidence}%")
        if user_id:
            print(f"  Rule     : {rule_label} (user {user_id})")
        else:
            print(f"  Source   : System Verdict")
        print(f"{'━'*80}\n")

        logging.info(
            f"[{level}] {fixture_name} @ {minute}' | "
            f"Conf:{confidence}% | user={user_id or 'system'} | {msg}"
        )

        record = {
            "f_id":       f_id,
            "fixture":    fixture_name,
            "time":       now.isoformat(),
            "minute":     minute,
            "level":      level,
            "confidence": confidence,
            "msg":        msg,
            "session":    SESSION_ID,
            "user_id":    user_id,
            "rule_id":    rule_id,
            "rule_label": rule_label,
            # ── VERIFICATION FIELDS ────────────────────────────────────
            # storm_stage: which gate fired (developing / sustained /
            # peaking) so the UI can render one card per fixture as an
            # escalation track instead of three near-identical alerts.
            "storm_stage":       storm_stage,
            # score_at_trigger: scoreline at the instant of firing. `None`
            # means the caller had no fixture data — recorded honestly
            # rather than defaulted to "0-0", which would be a fabricated
            # scoreline.
            "score_at_trigger":  (f"{score[0]}-{score[1]}"
                                 if score is not None else None),
            "score_home_trigger": (score[0] if score is not None else None),
            "score_away_trigger": (score[1] if score is not None else None),
            # Filled in later by resolve_alert_results() once the fixture
            # reaches full time. `pending` means the match is still running.
            "final_score":       None,
            "goals_after":       None,
            "outcome":           "pending",
        }
        SESSION_ALERTS.append(record)

        with alert_lock:
            try:
                with open(OUTPUT_ALERTS_FILE, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logging.error(f"Alert Write Failed: {e}")

        # ── PUSH THE USER'S OWN ALERT TO THEIR PHONE ──────────────────────
        # Without this the alert exists ONLY as a row in ready_to_push.json,
        # which the user has to open the app and refresh to see. The push
        # pipeline was built and wired but had no caller since the Code 2
        # validator was removed, so a "Setup my alert" rule was silently
        # in-app-only.
        #
        # Only RULE-driven alerts are announced. The system's own 45' gate has
        # no user_id and stays a broadcast-capable internal signal, so it is
        # deliberately not pushed here.
        #
        # `gate` is the scoreline limitation in words, because "under 2.5" is
        # not actionable from a lockscreen without knowing the match is still
        # inside it.
        if user_id and rule_id:
            try:
                from notifications import emit_event
                emit_event(
                    "USER_ALERT",
                    f_id,
                    fixture_name,
                    market=str(record.get("market") or "ALERT"),
                    target=rule_label or None,
                    audience_user_id=user_id,
                    rule_id=rule_id,
                    rule_label=rule_label,
                    minute=minute,
                    score_at_trigger=record.get("score_at_trigger"),
                    gate=gate,
                    watchlisted=watchlisted,
                )
            except Exception as e:
                # Best-effort by contract: a push failure must never stop the
                # alert from being recorded and shown in-app.
                logging.warning(f"User alert push failed (alert still recorded): {e}")

        with alert_lock:
            try:
                with open(SESSION_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(SESSION_ALERTS, f, indent=2)
            except Exception as e:
                logging.error(f"Session Log Failed: {e}")

    # ── PREMATCH LOADER ───────────────────────────────────────────────────
    def load_all_prematch_data(self):
        # Thin wrapper. The body moved to the module-level build_prematch_db()
        # so the rules API can score candidate matches with the EXACT same
        # merge the cycle uses, instead of a second, drifting copy of it.
        return build_prematch_db()

    # ── STALE MEMORY CLEANUP ──────────────────────────────────────────────
    def cleanup_stale_memory(self, live_ids):
        stale = [fid for fid in LIVE_METRICS_VAULT
                 if fid not in live_ids]
        for fid in stale:
            del LIVE_METRICS_VAULT[fid]
        # NEW: keep key-player tracking cache aligned with live matches too
        stale_key = [fid for fid in KEY_PLAYER_TRACKING if fid not in live_ids]
        for fid in stale_key:
            del KEY_PLAYER_TRACKING[fid]

    # ── SQUAD PREFETCH (thread-safe) ──────────────────────────────────────
    def _fetch_and_store_squad(self, tid):
        try:
            self.Detective.get_squad_data(tid)
        except Exception as e:
            logging.error(f"Squad fetch failed for {tid}: {e}")
        finally:
            with FETCHING_LOCK:
                FETCHING_TEAMS.discard(tid)

    def maintenance_thread(self, db, live_fixtures=None):
        """
        Keep the squad vault populated for every team the storm gates need.

        WHY live_fixtures IS NOW PASSED IN
        This used to iterate the PREMATCH database only. A fixture that is live
        but was not in the prematch report — which is most youth, women's and
        lower-league matches, exactly the kind that produce alerts — never had
        its squads requested. investigate() then returned
        INSUFFICIENT_SQUAD_DATA for the whole match, `h_triple`/`a_triple` were
        never computed, and the storm gates could not fire on it no matter what
        the pressure or confidence were.

        That, not the 15-minute window, was the dominant reason only 9 alerts
        fired in 11 days: the structural bar could not even be evaluated on
        most live matches. Widening the time window does nothing for a match
        whose squad data was never fetched, so live participants are now
        requested alongside the prematch ones.
        """
        team_ids = []
        for _f_id, data in (db or {}).items():
            team_ids.extend([data.get('h_id'), data.get('a_id')])
        for fx in (live_fixtures or []):
            if not isinstance(fx, dict):
                continue
            for p in (fx.get("participants") or []):
                if isinstance(p, dict) and p.get("id") is not None:
                    team_ids.append(p.get("id"))
        for tid in team_ids:
            if tid:
                # FIX 6 (squad coverage): an empty {"players": {}} vault
                # entry is the residue of a failed/empty fetch, not valid
                # squad data. The old `str(tid) in SQUAD_VAULT` check
                # treated it as cached forever, so a poisoned team was
                # never re-fetched and investigate() returned
                # INSUFFICIENT_SQUAD_DATA permanently. Only entries with
                # actual players count as cached.
                vault_entry = SQUAD_VAULT.get(str(tid))
                has_data = bool(
                    vault_entry.get("players")
                    if isinstance(vault_entry, dict)
                    and "players" in vault_entry
                    else vault_entry
                )
                with FETCHING_LOCK:
                    already = (tid in FETCHING_TEAMS or has_data)
                if not already:
                    with FETCHING_LOCK:
                        FETCHING_TEAMS.add(tid)
                    self.executor.submit(
                        self._fetch_and_store_squad, tid
                    )

    # ── MARKET SETTLEMENT ─────────────────────────────────────────────────
    @staticmethod
    def score_from_fixture(fx):
        """
        The scoreline of a fixture RIGHT NOW, or None when it cannot be read.

        THE BUG THIS FIXES
        This used to read ONLY the `CURRENT` score period and default to 0.
        The provider does not always publish a CURRENT period: a fixture live
        at 43' was found carrying only 1ST_HALF and 2ND_HALF, so the read
        returned 0-0 for a match that was actually 1-0. That silently wrote a
        wrong score onto the alert — the one number the verification panel
        exists to show. It is not a full-time-only problem; it happens live.

        ORDER
        1. extract_match_data() — the settlement service's own standardiser and
           already this system's canonical, independently tested reader of the
           same payload. Its h_ft/a_ft are the running total.
        2. The CURRENT period, when the provider did publish one.
        3. The most recent period present. Period entries are CUMULATIVE (a
           2ND_HALF entry holds the total so far, not that period's own goals),
           so the newest period IS the running score.

        RETURNS None, NEVER (0, 0). A 0-0 that was not read is
        indistinguishable from a real goalless draw, so callers must treat
        None as unknown rather than as zero.
        """
        try:
            from settlement_service import extract_match_data
            std = extract_match_data(fx) or {}
            if std.get("score_available"):
                h, a = std.get("h_ft"), std.get("a_ft")
                if h is not None and a is not None:
                    return (int(h), int(a))
        except Exception:
            pass

        current = {}
        latest = {}
        latest_type = -1
        for entry in (fx or {}).get("scores", []) or []:
            if not isinstance(entry, dict):
                continue
            s_obj = entry.get("score") or entry
            side = str(s_obj.get("participant", "")).lower()
            if side not in ("home", "away"):
                continue
            try:
                val = int(s_obj.get("goals"))
            except (TypeError, ValueError):
                continue
            desc = str(s_obj.get("description", "")).upper()
            if "CURRENT" in desc:
                current[side] = val
                continue
            try:
                tid = int(entry.get("type_id") or 0)
            except (TypeError, ValueError):
                tid = 0
            if tid >= latest_type:
                if tid > latest_type:
                    latest_type = tid
                    latest = {}
                latest[side] = val

        for src in (current, latest):
            if src.get("home") is not None and src.get("away") is not None:
                return (int(src["home"]), int(src["away"]))
        return None

    def update_market_settlement(self, f_id, fx):
        h_g = a_g = 0
        for entry in fx.get("scores", []):
            if not isinstance(entry, dict): continue
            s_obj = entry.get("score") or entry
            desc  = str(s_obj.get("description", "")).upper()
            if "CURRENT" not in desc: continue
            side  = str(s_obj.get("participant", "")).lower()
            g     = s_obj.get("goals")
            if g is not None:
                try:
                    val = int(g)
                    if side == "home":  h_g = val
                    elif side == "away": a_g = val
                except Exception: continue

        if f_id not in MARKET_SETTLEMENT:
            MARKET_SETTLEMENT[f_id] = set()
        if h_g > 0 and a_g > 0:        MARKET_SETTLEMENT[f_id].add("GG")
        if (h_g + a_g) >= 3:           MARKET_SETTLEMENT[f_id].add("O2.5")

    # ── STAT EXTRACTOR ────────────────────────────────────────────────────
    def extract_stats(self, fx):
        h, a   = {}, {}
        parts  = fx.get("participants", [])
        h_id = a_id = None
        for p in parts:
            if (p.get('meta') or {}).get('location') == 'home':
                h_id = str(p['id'])
            elif (p.get('meta') or {}).get('location') == 'away':
                a_id = str(p['id'])
        if not h_id and len(parts) >= 2:
            h_id = str(parts[0]["id"]); a_id = str(parts[1]["id"])

        for s in fx.get('statistics', []):
            pid  = str(s.get('participant_id'))
            code = safe_get(s, 'type', 'code')
            val  = safe_get(s, 'data', 'value', default=0)
            try: val = float(val)
            except: val = 0.0
            loc  = "home" if pid == h_id else \
                   ("away" if pid == a_id else None)
            if not loc or not code: continue
            if loc == 'home': h[code] = val
            else:             a[code] = val
            if code in ['touches-in-opposition-box','attacks-in-box']:
                if loc == 'home': h['box'] = h.get('box',0) + val
                else:             a['box'] = a.get('box',0) + val
        return h, a

    # ── IMPACT CONTEXT ────────────────────────────────────────────────────
    def extract_impact_context(self, fx):
        f_id   = str(fx['id'])
        impact = {
            "home": {
                "reds": 0, "gk_risk": False,
                "key_sub_off": 0, "worth_lost": 0
            },
            "away": {
                "reds": 0, "gk_risk": False,
                "key_sub_off": 0, "worth_lost": 0
            }
        }
        parts  = fx.get("participants", [])
        h_id = a_id = None
        for p in parts:
            if (p.get('meta') or {}).get('location') == 'home':
                h_id = str(p['id'])
            elif (p.get('meta') or {}).get('location') == 'away':
                a_id = str(p['id'])
        if not h_id and len(parts) >= 2:
            h_id = str(parts[0]["id"]); a_id = str(parts[1]["id"])

        for e in fx.get('events', []):
            code = safe_get(e, "type", "code")
            pid  = str(e.get("participant_id"))
            loc  = "home" if pid == h_id else \
                   ("away" if pid == a_id else None)
            if not loc: continue
            if code == "red-card":     impact[loc]["reds"] += 1
            if code == "substitution": impact[loc]["key_sub_off"] += 1

        return {
            "home":   {"id": h_id},
            "away":   {"id": a_id},
            "impact": impact,
            "f_id":   f_id
        }

    # ── MINUTE EXTRACTOR ─────────────────────────────────────────────────
    def extract_minute(self, fx):
        found = [0]
        if fx.get("time") and isinstance(fx.get("time"), dict):
            found.append(int(fx["time"].get("minute", 0)))
        if isinstance(fx.get("state"), dict):
            found.append(int(fx.get("state").get("minute", 0)))
        for p in fx.get("periods", []):
            period_time = p.get("time") if isinstance(p.get("time"), dict) else {}
            m = (period_time.get("minute") or p.get("minute")
                 or p.get("minutes") or p.get("length"))
            if m:
                try: found.append(int(m))
                except (TypeError, ValueError): pass
        if fx.get("events"):
            emins = [int(e.get("minute",0))
                     for e in fx["events"] if e.get("minute")]
            if emins: found.append(max(emins))
        if fx.get("starting_at_timestamp"):
            now_ts  = int(datetime.now(timezone.utc).timestamp())
            elapsed = (now_ts - int(fx["starting_at_timestamp"])) // 60
            if 0 < elapsed <= 50:     found.append(elapsed)
            elif 60 < elapsed <= 110: found.append(elapsed - 15)
            elif elapsed > 110:       found.append(90)
        return max(found)

    # ── LIVE SCORE FETCH ─────────────────────────────────────────────────
    def fetch_live_scores(self):
        # ◄── Reads from the 2-minute shared cache (0 extra SportMonks calls)
        try:
            from backend.live_cache import get_live_scores_cached
        except ImportError:
            from live_cache import get_live_scores_cached
            
        return get_live_scores_cached()


# ==============================================================================
# 🚀 MAIN ENTRY POINT
# ==============================================================================
def run_master_orchestrator():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)

    if not API_TOKEN:
        logging.error("CRITICAL: SPORTMONKS_API_KEY is missing!")
        return

    load_memory()
    try:
        SupremeOrchestrator().run()
    except KeyboardInterrupt:
        logging.info("Shutting down gracefully...")
        save_memory()


if __name__ == "__main__":
    run_master_orchestrator()
