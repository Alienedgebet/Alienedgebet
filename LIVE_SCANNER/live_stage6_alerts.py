import os
import sys
import re
import time
import json
import requests
import threading
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from collections import deque
from dotenv import load_dotenv

from user_rules_store import list_rules, evaluate_rule_for_match

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

def GET(url, params=None):
    if params is None: params = {}
    params.setdefault("api_token", API_TOKEN)
    backoff = 2.0
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200: return r.json()
            elif r.status_code == 429:
                time.sleep(backoff); backoff *= 2; continue
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
                return entry["players"]
            else:
                # Old flat format — migrate in place
                SQUAD_VAULT[tid_str] = {
                    "players":       entry,
                    "team_avg_leak": 1.2
                }
                return entry

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
    def evaluate(self, f_id, intel, structural, pre, minute, key_loss, all_rules):
        triggered = []
        conf = intel['match']['confidence_score']

        if conf >= CONFIDENCE_PREMIUM_THRESHOLD:
            tier = "🔥 PREMIUM"
        elif conf >= CONFIDENCE_STANDARD_THRESHOLD:
            tier = "✅ STANDARD"
        else:
            tier = "📊 MONITOR"

        for rule in all_rules:
            hit = evaluate_rule_for_match(rule, intel, pre, minute, key_loss)
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
            self.cycle += 1
            db = self.load_all_prematch_data()

            if not db:
                logging.info(
                    "[MOCK MODE] No prematch report found. "
                    "Live-only monitoring active."
                )

            self.maintenance_thread(db)

            try:
                live_data = self.fetch_live_scores()
                live_ids  = {str(fx['id']) for fx in live_data}

                self.cleanup_stale_memory(live_ids)

                # ── FIX: Build name→fixture_id map for fallback matching ──
                # Code 2's live_predictions.json uses fixture IDs from the
                # scheduled endpoint. The inplay endpoint may return the
                # same fixture under a different ID in some competitions.
                # We build a name-based lookup as a fallback.
                live_name_map = {}
                for fx in live_data:
                    name_key = self._name_key(fx.get('name', ''))
                    live_name_map[name_key] = str(fx['id'])

                cycle_matches = []

                for fx in live_data:
                    f_id     = str(fx['id'])
                    pre      = db.get(f_id, {})

                    # ── FIX: Name-based fallback for prematch context ──────
                    # If the scheduled fixture ID doesn't match the live ID,
                    # try matching by team names
                    if not pre and db:
                        name_key = self._name_key(fx.get('name', ''))
                        for db_fid, db_entry in db.items():
                            db_name = self._name_key(
                                db_entry.get('fixture',
                                db_entry.get('name', ''))
                            )
                            if db_name and db_name == name_key:
                                pre = db_entry
                                break

                    minute   = self.extract_minute(fx)
                    if not minute or minute <= 0: continue

                    self.update_market_settlement(f_id, fx)

                    h_s, a_s = self.extract_stats(fx)
                    intel    = self.Brain.analyze_match_state(
                        f_id, h_s, a_s, minute, fx.get('events', [])
                    )
                    ctx        = self.extract_impact_context(fx)
                    structural = self.Detective.investigate(ctx, pre)

                    # NEW: real live key-player-lost tracking, ported from
                    # the same idea as live_stage2_verification.py — but
                    # self-contained here so Code 6 doesn't depend on Stage
                    # 2 running. Key-11 sets are built lazily once both
                    # squads are cached, then substitution events are
                    # checked against those sets every cycle.
                    key_loss = self._track_key_player_loss(f_id, ctx, fx)

                    fixture_name = fx.get('name', f_id)

                    active_rules = list_rules(active_only=True)

                    user_alerts   = self.UserLogic.evaluate(
                        f_id, intel, structural, pre, minute, key_loss, active_rules
                    )
                    fired_this    = []

                    for ua in user_alerts:
                        if (ua['tier'] in ["🔥 PREMIUM","✅ STANDARD"] and
                                ua['id'] not in ALERT_HISTORY):
                            self.fire_alert(
                                f_id, fixture_name,
                                ua['tier'], ua['msg'], ua['conf'], minute,
                                user_id=ua.get('user_id'),
                                rule_id=ua.get('rule_id'),
                                rule_label=ua.get('rule_label'),
                            )
                            ALERT_HISTORY.add(ua['id'])
                            fired_this.append(ua)
                        elif ua['tier'] == "📊 MONITOR":
                            fired_this.append(ua)

                    self.process_ai_gates(
                        f_id, fixture_name, minute,
                        intel, structural, pre
                    )

                    cycle_matches.append({
                        "name":       fixture_name,
                        "id":         f_id,
                        "minute":     minute,
                        "conf":       intel['match']['confidence_score'],
                        "h_pressure": intel['match']['h_pressure_share'],
                        "a_pressure": intel['match']['a_pressure_share'],
                        "chaos":      intel['match']['chaos_index'],
                        "h_xg":       intel['home']['live_xg'],
                        "a_xg":       intel['away']['live_xg'],
                        "h_sot":      intel['home']['sot'],
                        "a_sot":      intel['away']['sot'],
                        "structural": structural.get('status','OK'),
                        "key_loss":   key_loss,
                        "alerts":     fired_this,
                        "in_db":      bool(pre)
                    })

                self.print_orchestrator_board(
                    cycle_matches, len(live_data), len(db)
                )

            except Exception as e:
                logging.error(f"Engine Loop Failure: {e}")

            time.sleep(45)

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
                        print(f"       {ua['tier']} → {ua['msg']}")
                else:
                    print("       No alerts this cycle.")

        if SESSION_ALERTS:
            print(f"\n  {'─'*78}")
            print(f"  🔥 SESSION ALERTS FIRED: {len(SESSION_ALERTS)}")
            for a in SESSION_ALERTS[-5:]:
                print(
                    f"    [{a['tier']}] {a['fixture']} | "
                    f"Min {a['minute']}' | Conf {a['conf']}% | "
                    f"{a['msg'][:55]}"
                )

        print(f"{'═'*80}\n")

    # ── AI GATES ─────────────────────────────────────────────────────────
    def process_ai_gates(self, f_id, fixture_name,
                          minute, intel, struct, pre):
        conf = intel['match']['confidence_score']

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
                    f_id, fixture_name, tier, msg, conf, minute
                )
                ALERT_HISTORY.add(a_key)

    # ── FIRE ALERT ────────────────────────────────────────────────────────
    def fire_alert(self, f_id, fixture_name,
                   level, msg, confidence, minute,
                   user_id=None, rule_id=None, rule_label=None):
        now    = datetime.now()
        banner = ("🔥" if "PREMIUM" in level
                  else ("✅" if "STANDARD" in level else "📊"))

        print(f"\n{'━'*80}")
        print(f"  {banner} {level} ALERT | {now.strftime('%H:%M:%S')} UTC")
        print(f"  Match    : {fixture_name}")
        print(f"  Minute   : {minute}'")
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
        }
        SESSION_ALERTS.append(record)

        with alert_lock:
            try:
                with open(OUTPUT_ALERTS_FILE, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                logging.error(f"Alert Write Failed: {e}")

        with alert_lock:
            try:
                with open(SESSION_LOG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(SESSION_ALERTS, f, indent=2)
            except Exception as e:
                logging.error(f"Session Log Failed: {e}")

    # ── PREMATCH LOADER ───────────────────────────────────────────────────
    def load_all_prematch_data(self):
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

    def maintenance_thread(self, db):
        for f_id, data in db.items():
            for tid in [data.get('h_id'), data.get('a_id')]:
                if tid:
                    with FETCHING_LOCK:
                        already = (tid in FETCHING_TEAMS or
                                   str(tid) in SQUAD_VAULT)
                    if not already:
                        with FETCHING_LOCK:
                            FETCHING_TEAMS.add(tid)
                        self.executor.submit(
                            self._fetch_and_store_squad, tid
                        )

    # ── MARKET SETTLEMENT ─────────────────────────────────────────────────
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
            m = (p.get("time", {}).get("minute") or
                 p.get("minute") or p.get("length"))
            if m: found.append(int(m))
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
