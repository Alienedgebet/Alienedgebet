import os
import sys
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

# --- 1. HOSTING & ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS (The Standard Architecture) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

AGGREGATOR_REPORT_FILE = os.path.join(DATA_DIR, "aggregator_report.json")
SH_GG_WINNER_FILE = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json") 
CACHE_FILE = os.path.join(DATA_DIR, "squad_cache.json")
OUTPUT_ALERTS_FILE = os.path.join(OUTPUT_DIR, "ready_to_push.json")
LOG_FILE = os.path.join(OUTPUT_DIR, "system.log")

# 🚨 ENTERPRISE UPGRADE: PROFESSIONAL LOGGING SYSTEM 🚨
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- 3. CONFIGURATION ---
API_TOKEN = os.getenv("SPORTMONKS_API_KEY") or "hD4F4FIFwNW5BxKa6Y0fCCLtB0KkiNRxtULDdsrO3VPss1IMV4HJihBkxwI4"
BASE_URL = "https://api.sportmonks.com/v3/football/livescores/inplay"
HISTORY_URL = "https://api.sportmonks.com/v3/football"

# GLOBAL STATE VAULTS 
SQUAD_VAULT = {}           
LIVE_METRICS_VAULT = {}    
VALIDATION_STATE = {}      
MARKET_SETTLEMENT = {}     
ALERT_HISTORY = set()      

# SYSTEM LOCKS & QUEUES 
cache_lock = threading.Lock()
alert_lock = threading.Lock()
FETCHING_TEAMS = set() 

# ==============================================================================
# 🛠️ SYSTEM UTILITIES
# ==============================================================================
def load_memory():
    global SQUAD_VAULT
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                SQUAD_VAULT = json.load(f)
            logging.info(f"MEMORY RESTORED: {len(SQUAD_VAULT)} teams loaded from squad_cache.json")
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
            if r.status_code == 200: 
                return r.json()
            elif r.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            r.raise_for_status() 
        except Exception as e:
            time.sleep(1)
            continue
    return {"data":[]}

# ==============================================================================
# 🧠 MODULE 1: SYNTHETIC INTELLIGENCE BRAIN 
# ==============================================================================
class SyntheticIntelligenceBrain:
    def __init__(self):
        self.W_P_SOT = 2.0
        self.W_P_BOX = 1.5
        self.W_P_DA = 0.6
        self.W_P_CORN = 0.5
        self.W_X_SOT = 0.45
        self.W_X_BOX = 0.25
        self.W_X_DA = 0.15
        self.W_X_CORN = 0.10
        self.W_X_POS = 0.05

    def compute_team_metrics(self, f_id, stats, side, minute):
        if f_id not in LIVE_METRICS_VAULT:
            LIVE_METRICS_VAULT[f_id] = {"home": deque(maxlen=25), "away": deque(maxlen=25)}
        
        sot = int(stats.get('shots-on-target', 0))
        box = int(stats.get('box', 0))
        da  = int(stats.get('dangerous-attacks', 0))
        corn = int(stats.get('corners', 0))
        pos  = int(stats.get('ball-possession', 50))
        
        pressure = (sot * self.W_P_SOT) + (box * self.W_P_BOX) + (da * self.W_P_DA) + (corn * self.W_P_CORN)
        live_xg = (sot * self.W_X_SOT) + (box * self.W_X_BOX) + (da * self.W_X_DA) + (corn * self.W_X_CORN) + (pos * self.W_X_POS / 100)
        
        buffer = LIVE_METRICS_VAULT[f_id][side]
        buffer.append({"xg": live_xg, "min": minute, "da": da, "sot": sot, "pressure": pressure})
        
        recent_xg_list = [x['xg'] for x in buffer if x['min'] > (minute - 10)]
        rolling_xg = sum(recent_xg_list) / len(recent_xg_list) if recent_xg_list else 0
        
        last_5 = [x['xg'] for x in buffer if x['min'] > (minute - 5)]
        prev_5 =[x['xg'] for x in buffer if (minute - 10) < x['min'] <= (minute - 5)]
        accel = (sum(last_5)/len(last_5)) - (sum(prev_5)/len(prev_5)) if (last_5 and prev_5) else 0.0

        return {
            "pressure_raw": pressure, "live_xg": round(live_xg, 2), "rolling_10_xg": round(rolling_xg, 2),
            "acceleration": round(accel, 2), "da_velocity": round(da / max(1, minute), 2),
            "sot": sot, "box": box, "da": da, "corn": corn
        }

    def analyze_match_state(self, f_id, h_s, a_s, minute, events):
        h = self.compute_team_metrics(f_id, h_s, "home", minute)
        a = self.compute_team_metrics(f_id, a_s, "away", minute)
        
        total_p = h['pressure_raw'] + a['pressure_raw']
        h_p_share = (h['pressure_raw'] / total_p * 100) if total_p > 0 else 50
        
        total_xg = h['live_xg'] + a['live_xg']
        h_dom = (h['live_xg'] / total_xg * 100) if total_xg > 0 else 50
        
        recent_e =[e for e in events if (e.get('minute') or 0) > (minute - 12)]
        cards = len([e for e in recent_e if "card" in str(safe_get(e, "type", "code", default=""))])
        c_burst = len([e for e in recent_e if safe_get(e, "type", "code") == "corner"])
        chaos = (c_burst * 2.5) + (cards * 4.0) + ((h['da_velocity'] + a['da_velocity']) * 10)

        # 🚨 ENTERPRISE UPGRADE: CONFIDENCE SCORING
        confidence_score = min(100, max(0, (total_p * 0.8) + (chaos * 2.0)))

        return {
            "home": h, "away": a,
            "match": {
                "total_pressure": round(total_p, 2), "h_pressure_share": round(h_p_share, 1),
                "a_pressure_share": round(100 - h_p_share, 1), "h_dominance": round(h_dom, 1),
                "a_dominance": round(100 - h_dom, 1), "chaos_index": round(chaos, 2),
                "xg_diff_slope": round(h['live_xg'] - a['live_xg'], 2),
                "confidence_score": round(confidence_score, 1)
            }
        }

# ==============================================================================
# 🕵️ MODULE 2: STRUCTURAL FORENSIC DETECTIVE
# ==============================================================================
class StructuralDetective:
    def get_squad_data(self, team_id):
        tid_str = str(team_id)
        if tid_str in SQUAD_VAULT: return SQUAD_VAULT[tid_str]
        
        start_dt = (datetime.now(timezone.utc).date() - timedelta(days=150)).isoformat()
        end_dt = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        url = f"{HISTORY_URL}/fixtures/between/{start_dt}/{end_dt}/{team_id}"
        
        resp = GET(url, params={"include": "lineups.details.type;lineups.player.position;scores;participants", "per_page": 25})
        
        stats = {}
        for fx in resp.get("data",[]):
            hid = str(safe_get(fx, "participants", 0, "id"))
            h_g = safe_get(fx, "scores", 0, "score", "goals", default=0)
            a_g = safe_get(fx, "scores", 1, "score", "goals", default=0)
            opp_goals = a_g if tid_str == hid else h_g

            for l in fx.get("lineups",[]):
                if str(l.get("team_id")) == tid_str:
                    pid = str(l.get("player_id"))
                    if not l.get("player"): continue
                    m_val = r_val = 0.0; c_val = -1.0
                    for d in l.get("details",[]):
                        t_name = str(d.get('type', {}).get('name', '')).lower()
                        raw_v = d.get("data", {}).get("value") or d.get("value")
                        try: val = float(str(raw_v).replace('%', ''))
                        except: val = 0.0
                        if "minutes" in t_name: m_val = val
                        elif "rating" in t_name: r_val = val
                        elif "conceded" in t_name: c_val = val
                    
                    if m_val == 0 and str(l.get("formation_position")) == "1": m_val = 90
                    if c_val == -1.0: c_val = float(opp_goals)
                    if pid not in stats:
                        stats[pid] = {"ratings":[], "apps": 0, "mins": 0, "conceded": 0, "clean_sheets": 0, "pos": safe_get(l["player"], "position", "name")}
                    stats[pid]["mins"] += m_val; stats[pid]["apps"] += 1
                    if r_val > 0: stats[pid]["ratings"].append(r_val)
                    if m_val > 0:
                        stats[pid]["conceded"] += c_val
                        if c_val == 0: stats[pid]["clean_sheets"] += 1

        processed = {}
        for pid, d in stats.items():
            avg_r = sum(d["ratings"])/len(d["ratings"]) if d["ratings"] else 6.0
            worth = (d["apps"] * 5000) + (d["mins"] * avg_r)
            c_p90 = (d["conceded"] / d["mins"]) * 90 if d["mins"] > 0 else 0.0
            doom = (c_p90 * 0.6) + ((1 - (d["clean_sheets"]/d["apps"] if d["apps"]>0 else 0)) * 2)
            processed[pid] = {"worth": worth, "doom": doom, "pos": d["pos"]}
            
        with cache_lock:
            SQUAD_VAULT[tid_str] = processed
        save_memory() 
        return processed

    def investigate(self, ctx, pre):
        h_id, a_id = str(ctx['home']['id']), str(ctx['away']['id'])
        h_sq, a_sq = SQUAD_VAULT.get(h_id, {}), SQUAD_VAULT.get(a_id, {})
        
        if not h_sq or not a_sq: return {"status": "INSUFFICIENT_SQUAD_DATA"}

        h_doom_avg = sum(p['doom'] for p in h_sq.values()) / len(h_sq) if len(h_sq) > 0 else 0
        a_doom_avg = sum(p['doom'] for p in a_sq.values()) / len(a_sq) if len(a_sq) > 0 else 0
        
        h_triple = h_doom_avg >= (a_doom_avg * 3) if a_doom_avg > 0 else False
        a_triple = a_doom_avg >= (h_doom_avg * 3) if h_doom_avg > 0 else False
        
        return {
            "h_doom": h_doom_avg, "a_doom": a_doom_avg,
            "h_triple": h_triple, "a_triple": a_triple,
            "h_red": ctx['impact']['home']['reds'] > 0,
            "a_red": ctx['impact']['away']['reds'] > 0,
            "h_gk": ctx['impact']['home']['gk_risk'],
            "a_gk": ctx['impact']['away']['gk_risk']
        }

# ==============================================================================
# 🎯 MODULE 3: USER-RULE EVALUATOR 
# ==============================================================================
class UserRuleEvaluator:
    def evaluate(self, f_id, intel, structural, pre, configs): 
        triggered = []
        conf = intel['match']['confidence_score']
        
        # 🚨 ENTERPRISE UPGRADE: ALERT SCORING TIERS 🚨
        if conf >= 80: tier = "🔥 PREMIUM"
        elif conf >= 60: tier = "✅ STANDARD"
        else: return triggered  # Silent - Kills Noise

        for cfg in configs:
            if cfg['type'] == "PRESSURE_SHARE":
                target = cfg['side']
                if 'require_prematch_flag' in cfg:
                    req_flag = cfg['require_prematch_flag']
                    flags = safe_get(pre, 'flags') or {}
                    if not flags.get(req_flag): continue 

                if intel['match'][f'{target[0]}_pressure_share'] >= cfg['min_pct']:
                    alert_msg = f"{target.upper()} dominating Pressure Share ({intel['match'][f'{target[0]}_pressure_share']}%)."
                    triggered.append({"id": f"{f_id}_USER_PRESSURE", "msg": alert_msg, "tier": tier, "conf": conf})
            
            if cfg['type'] == "FUSED_PREMATCH_LIVE":
                req_label = cfg.get('required_label')
                min_chaos = cfg.get('min_chaos', 0)
                pick_labels = pre.get('pick_labels',[])

                if req_label in pick_labels and intel['match']['chaos_index'] >= min_chaos:
                    alert_msg = f"Pre-match Engine 1 '{req_label}' matched with high live chaos ({intel['match']['chaos_index']})."
                    triggered.append({"id": f"{f_id}_USER_FUSED", "msg": alert_msg, "tier": tier, "conf": conf})
                    
        return triggered

# ==============================================================================
# 🔄 THE SUPREME ORCHESTRATOR 
# ==============================================================================
class SupremeOrchestrator:
    def __init__(self):
        self.Brain = SyntheticIntelligenceBrain()
        self.Detective = StructuralDetective()
        self.UserLogic = UserRuleEvaluator()
        self.executor = ThreadPoolExecutor(max_workers=5)

    def run(self):
        logging.info("--- SOVEREIGN FORENSIC ORCHESTRATOR ONLINE ---")
        
        while True:
            db = self.load_all_prematch_data()
            if not db:
                sys.stdout.write("Waiting for Prematch Reports to be generated...\r")
                sys.stdout.flush()
                time.sleep(10)
                continue
            
            self.maintenance_thread(db)

            try:
                live_data = self.fetch_live_scores()
                live_ids = {str(fx['id']) for fx in live_data}
                
                # 🚨 ENTERPRISE UPGRADE: MATCH LIFECYCLE CLEANUP (Memory Leak Fix) 🚨
                self.cleanup_stale_memory(live_ids)
                
                sys.stdout.write(f"[{datetime.now().strftime('%H:%M:%S')}] 📡 Radar Sweeping... Tracking {len(db)} VIP Targets | {len(live_data)} matches live.\r")
                sys.stdout.flush()
                
                for fx in live_data:
                    f_id = str(fx['id'])
                    if f_id not in db: continue
                    
                    pre = db[f_id]
                    
                    minutes_found = [0]
                    if fx.get("time") and isinstance(fx.get("time"), dict):
                        minutes_found.append(int(fx["time"].get("minute", 0)))
                    if isinstance(fx.get("state"), dict):
                        minutes_found.append(int(fx.get("state").get("minute", 0)))
                    for p in fx.get("periods",[]):
                        m = p.get("time", {}).get("minute") or p.get("minute") or p.get("length")
                        if m: minutes_found.append(int(m))
                    if fx.get("events"):
                        emins =[int(e.get("minute", 0)) for e in fx["events"] if e.get("minute")]
                        if emins: minutes_found.append(max(emins))
                    if fx.get("starting_at_timestamp"):
                        now_ts = int(datetime.now(timezone.utc).timestamp())
                        elapsed = (now_ts - int(fx["starting_at_timestamp"])) // 60
                        if 0 < elapsed <= 50: minutes_found.append(elapsed)
                        elif 60 < elapsed <= 110: minutes_found.append(elapsed - 15)
                        elif elapsed > 110: minutes_found.append(90)
                    
                    minute = max(minutes_found)
                    if not minute or minute <= 0: continue

                    self.update_market_settlement(f_id, fx)

                    h_s, a_s = self.extract_stats(fx)
                    intel = self.Brain.analyze_match_state(f_id, h_s, a_s, minute, fx.get('events',[]))
                    ctx = self.extract_impact_context(fx)
                    structural = self.Detective.investigate(ctx, pre)

                    user_setup =[
                        {"type": "PRESSURE_SHARE", "side": "home", "min_pct": 75},
                        {"type": "FUSED_PREMATCH_LIVE", "required_label": "🔥 BOTH 2H GOAL (100%)", "min_chaos": 10.0}
                    ]
                    
                    user_alerts = self.UserLogic.evaluate(f_id, intel, structural, pre, user_setup)
                    for ua in user_alerts:
                        if ua['id'] not in ALERT_HISTORY:
                            self.fire_alert(f_id, ua['tier'], ua['msg'], ua['conf'])
                            ALERT_HISTORY.add(ua['id'])

                    self.process_ai_gates(f_id, minute, intel, structural, pre)
            
            except Exception as e:
                logging.error(f"Engine Loop Failure: {e}")

            time.sleep(45)

    def cleanup_stale_memory(self, live_ids):
        """Prevents RAM explosion by deleting matches that are no longer live."""
        stale_ids =[fid for fid in LIVE_METRICS_VAULT if fid not in live_ids]
        for fid in stale_ids:
            del LIVE_METRICS_VAULT[fid]

    def process_ai_gates(self, f_id, minute, intel, struct, pre):
        if 30 <= minute < 45 and f_id not in VALIDATION_STATE:
            if (struct.get('h_triple') and intel['match']['a_pressure_share'] > 62) or \
               (struct.get('a_triple') and intel['match']['h_pressure_share'] > 62):
                VALIDATION_STATE[f_id] = "VALID_30"
                logging.info(f"[30' Handshake] {pre.get('fixture','Unknown')} Logic Synchronized.")

        if minute >= 45 and VALIDATION_STATE.get(f_id) == "VALID_30":
            a_key = f"{f_id}_SUPREME_45"
            conf = intel['match']['confidence_score']
            if a_key not in ALERT_HISTORY and conf >= 60:
                tier = "🔥 PREMIUM" if conf >= 80 else "✅ STANDARD"
                msg = f"{pre.get('fixture','Unknown')} Verification confirmed at 45'. Chaos: {intel['match']['chaos_index']}."
                self.fire_alert(f_id, tier, msg, conf)
                ALERT_HISTORY.add(a_key)

    def load_all_prematch_data(self):
        db = {}
        if os.path.exists(AGGREGATOR_REPORT_FILE):
            try:
                with open(AGGREGATOR_REPORT_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else data.values()
                    for item in items:
                        fid = str(item.get('fixture_id'))
                        db[fid] = item
                        if 'h_id' not in item:
                            dr = item.get('danger_report', {})
                            db[fid]['h_id'] = str(dr.get('home', {}).get('id'))
                            db[fid]['a_id'] = str(dr.get('away', {}).get('id'))
            except: pass
                
        if os.path.exists(SH_GG_WINNER_FILE):
            try:
                with open(SH_GG_WINNER_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    items = data if isinstance(data, list) else data.values()
                    for item in items:
                        fid = str(item.get('fixture_id'))
                        if fid not in db:
                            db[fid] = item
                        else:
                            db[fid].update(item)
                            
                        if 'h_id' not in db[fid]:
                            db[fid]['h_id'] = str(safe_get(item, 'teams', 'home', 'id'))
                            db[fid]['a_id'] = str(safe_get(item, 'teams', 'away', 'id'))
            except: pass
                
        return db

    def _fetch_and_store_squad(self, tid):
        try:
            self.Detective.get_squad_data(tid)
        except Exception as e:
            logging.error(f"Squad fetch failed for {tid}: {e}")
        finally:
            FETCHING_TEAMS.discard(tid)

    def maintenance_thread(self, db):
        for f_id, data in db.items():
            for tid in [data.get('h_id'), data.get('a_id')]:
                if tid and str(tid) not in SQUAD_VAULT and tid not in FETCHING_TEAMS:
                    FETCHING_TEAMS.add(tid)
                    self.executor.submit(self._fetch_and_store_squad, tid)

    def update_market_settlement(self, f_id, fx):
        # ==============================================================
        # FIX: SCORE READING — FILTER BY DESCRIPTION INSTEAD OF INDEX
        #
        # Original used safe_get(fx, "scores", 0, ...) and
        # safe_get(fx, "scores", 1, ...) — blind index access.
        # The Sportmonks API returns scores as a list of objects with
        # different description values (HT, FT, CURRENT, etc).
        # The list order is not guaranteed to be home=0, away=1.
        # Reading by index returned wrong or null values, meaning
        # market settlement (GG, O2.5 detection) never triggered.
        #
        # Fix: iterate the scores list and match by both 'CURRENT'
        # description AND participant side, identical to how every
        # other file in this project correctly reads live scores.
        # ==============================================================
        h_g = 0
        a_g = 0
        for entry in fx.get("scores", []):
            if not isinstance(entry, dict):
                continue
            s_obj = entry.get("score") or entry
            desc = str(s_obj.get("description", "")).upper()
            if "CURRENT" not in desc:
                continue
            side = str(s_obj.get("participant", "")).lower()
            g = s_obj.get("goals")
            if g is not None:
                try:
                    val = int(g)
                    if side == "home":
                        h_g = val
                    elif side == "away":
                        a_g = val
                except Exception:
                    continue

        if f_id not in MARKET_SETTLEMENT:
            MARKET_SETTLEMENT[f_id] = set()
        if h_g > 0 and a_g > 0:
            MARKET_SETTLEMENT[f_id].add("GG")
        if (h_g + a_g) >= 3:
            MARKET_SETTLEMENT[f_id].add("O2.5")

    def extract_stats(self, fx):
        h, a = {}, {}
        parts = fx.get("participants",[])
        if len(parts) < 2: return h, a
        
        h_id, a_id = None, None
        for p in parts:
            if (p.get('meta') or {}).get('location') == 'home': h_id = str(p['id'])
            elif (p.get('meta') or {}).get('location') == 'away': a_id = str(p['id'])
            
        if not h_id: h_id = str(parts[0]["id"])
        if not a_id: a_id = str(parts[1]["id"])

        for s in fx.get('statistics',[]):
            pid = str(s.get('participant_id'))
            code = safe_get(s, 'type', 'code')
            val = safe_get(s, 'data', 'value', default=0)
            try: val = float(val)
            except: val = 0.0

            loc = "home" if pid == h_id else ("away" if pid == a_id else None)
            if not loc or not code: continue

            if loc == 'home': h[code] = val
            else: a[code] = val

            if code in['touches-in-opposition-box', 'attacks-in-box']:
                if loc == 'home': h['box'] = val
                else: a['box'] = val
        return h, a

    def extract_impact_context(self, fx):
        f_id = str(fx['id'])
        impact = {"home": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0}, 
                  "away": {"reds": 0, "gk_risk": False, "key_sub_off": 0, "worth_lost": 0}}
        
        parts = fx.get("participants",[])
        h_id, a_id = None, None
        for p in parts:
            if (p.get('meta') or {}).get('location') == 'home': h_id = str(p['id'])
            elif (p.get('meta') or {}).get('location') == 'away': a_id = str(p['id'])
        if not h_id and len(parts) >= 2: h_id, a_id = str(parts[0]["id"]), str(parts[1]["id"])

        for e in fx.get('events',[]):
            code = safe_get(e, "type", "code")
            pid = str(e.get("participant_id"))
            loc = "home" if pid == h_id else ("away" if pid == a_id else None)
            if not loc: continue

            if code == "red-card": impact[loc]["reds"] += 1
            if code == "substitution":
                impact[loc]["key_sub_off"] += 1
                    
        return {"home": {"id": h_id}, "away": {"id": a_id}, "impact": impact, "f_id": f_id}

    def fetch_live_scores(self):
        url = f"{BASE_URL}?include=statistics.type;events.type;scores;participants;state;periods"
        return GET(url).get('data',[])

    def fire_alert(self, f_id, level, msg, confidence=0):
        log_msg = f"[{level} ALERT] {msg} | Conf: {confidence}%"
        logging.info(log_msg) # Save to system.log so you never lose it
        
        with alert_lock:
            try:
                with open(OUTPUT_ALERTS_FILE, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"f_id": f_id, "time": datetime.now().isoformat(), "level": level, "confidence": confidence, "msg": msg}) + "\n")
            except Exception as e:
                logging.error(f"Writing Alert Failed: {e}")

# ==============================================================================
# 🚀 MAIN ENTRY POINT
# ==============================================================================
def run_master_orchestrator():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not API_TOKEN:
        logging.error("CRITICAL: SPORTMONKS_API_KEY is missing!")
    else:
        load_memory()
        try:
            SupremeOrchestrator().run()
        except KeyboardInterrupt:
            logging.info("Shutting down Orchestrator gracefully...")
            save_memory()

if __name__ == "__main__":
    run_master_orchestrator()