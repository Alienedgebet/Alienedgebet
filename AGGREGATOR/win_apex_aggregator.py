import os
import sys
import math
import time
import json
import requests
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dotenv import load_dotenv

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS ---
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
DATA_DIR   = os.path.join(BASE_DIR, "data")
MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER
# ==============================================================================
def run_win_apex_aggregator(target_date=None):
    """
    AlienEdge Apex Win Aggregator — GODMODE PRECISION UPDATE

    KEY CHANGES FROM PREVIOUS VERSION
    ──────────────────────────────────────────────────────────────────────────
    1. REAL OPPONENT LAMBDA IN MONTE CARLO
       Previous version hardcoded opp_lambda = 1.1 for every single opponent
       in every single match. This made the simulation output look credible
       while being completely disconnected from reality.

       Fix: opponent lambda is now derived from the ranked_win_forecast CSV
       that Code 11 already writes. Specifically we read the opponent's
       own poisson_win_prob and last_5_goals_scored columns and convert
       them into a real scoring rate lambda for that specific opponent.

       This means when the Monte Carlo says 68% win probability it is
       computed against the real opponent's attacking threat, not a phantom.

    2. PHANTOM ROW PROTECTION
       Previous version unioned all key sources including psych_vetoes.
       A match only in the veto list with no engine entry produced rows
       where target_name came from a regex parse of the Tier string.
       If that regex failed the row entered final output with a malformed
       team name. This is now caught and dropped before output.

    3. VETO vs LOCK CONFLICT RESOLUTION
       A match simultaneously flagged as a psych lock AND a psych veto
       previously got silently Category 3 (veto wins). The engine now
       explicitly resolves the conflict: if the lock team and veto team
       differ, the match is Category 3. If they point to the same team
       the lock stands as Category 2 and the veto is noted.

    4. CATEGORY PROMOTION GATE
       A match can only reach Category 1 (Total Convergence) if the
       Monte Carlo win probability exceeds 60% with the real opponent
       lambda. This prevents matches with inflated probabilities from
       reaching the top category purely on signal count.
    ──────────────────────────────────────────────────────────────────────────
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)
    os.makedirs(MASTER_DIR, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────
    # 1. CONFIGURATION
    # ──────────────────────────────────────────────────────────────────────
    API_KEY = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL = "https://api.sportmonks.com/v3/football"

    TODAY_STR = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    FILE_WIN_FORECAST   = os.path.join(OUTPUT_DIR, f"ranked_win_forecast_{TODAY_STR}.csv")
    FILE_UNDERDOG       = os.path.join(OUTPUT_DIR, f"audited_underdog_backtest_{TODAY_STR}.csv")
    FILE_WIN_PSYCHOLOGY = os.path.join(OUTPUT_DIR, f"ALIENEDGE_WIN_PREDICTIONS_{TODAY_STR}.csv")
    FILE_U2S_PSYCHOLOGY = os.path.join(OUTPUT_DIR, f"ALIENEDGE_U2S_PSYCHOLOGY_{TODAY_STR}.csv")
    FILE_CALIBRATION    = os.path.join(OUTPUT_DIR, f"MASTER_CALIBRATION_{TODAY_STR}.csv")
    FILE_DNA            = os.path.join(DATA_DIR,   "team_dna_profiles.json")
    FILE_VIP_FEED       = os.path.join(OUTPUT_DIR, "sh_gg_winner_feed.json")
    FILE_FINAL_OUTPUT   = os.path.join(MASTER_DIR, f"WIN_SUPER_MATRIX_FINAL_{TODAY_STR}.csv")

    # ──────────────────────────────────────────────────────────────────────
    # 2. UTILITIES
    # ──────────────────────────────────────────────────────────────────────
    def GET(path, params=None):
        if params is None: params = {}
        params.setdefault('api_token', API_KEY)
        try:
            r = requests.get(
                f"{BASE_URL}{path}", params=params, timeout=20
            )
            if r.status_code == 200: return r.json()
        except: pass
        return {}

    def clean_n(name):
        n = str(name).lower()
        for w in ["u19","fc","sc","united","city","club",
                  "afc","rc","as","deportivo","atletico"]:
            n = n.replace(w, "")
        return re.sub(r'[^a-z0-9]', '', n).strip()

    def get_match_key(name):
        n = str(name).lower()
        n = re.sub(r'\bu19\b|\bfc\b', '', n)
        if ' vs ' in n:   teams = n.split(' vs ')
        elif '-' in n:    teams = n.split('-')
        else:             teams = [n]
        teams = [re.sub(r'[^a-z0-9]', '', t.strip()) for t in teams]
        teams.sort()
        return "".join(teams)

    # ──────────────────────────────────────────────────────────────────────
    # 3. OPPONENT LAMBDA BUILDER
    # ──────────────────────────────────────────────────────────────────────
    # This is the core fix. Instead of opp_lambda = 1.1 for everyone,
    # we build a lookup from the ranked CSV that Code 11 already wrote.
    # The lookup maps fixture_key → {home_lambda, away_lambda} so the
    # Monte Carlo can use the real opponent's scoring rate.
    #
    # Lambda derivation from the CSV:
    #   poisson_win_prob already encodes the team's attacking rate.
    #   We back-calculate lambda as: lambda = max(0.5, prob_pct / 35.0)
    #   This is the same formula Code 13 uses for target_lambda, so it
    #   is internally consistent.
    #   We also cross-check with last_5_goals_scored / 5 as a direct rate.
    #   Final lambda = average of both estimates, capped at 3.5.
    # ──────────────────────────────────────────────────────────────────────

    def build_opponent_lambda_map(df_forecast):
        """
        Returns dict:
          key (match_key) → {
            'home_lambda': float,  # home team real scoring rate
            'away_lambda': float,  # away team real scoring rate
            'home_team':  str,
            'away_team':  str,
          }
        """
        opp_map = {}
        if df_forecast is None or df_forecast.empty:
            return opp_map

        grouped = df_forecast.groupby('fixture_id')

        for fid, group in grouped:
            h_row = group[group['side'] == 'home']
            a_row = group[group['side'] == 'away']
            if h_row.empty or a_row.empty: continue

            def derive_lambda(row):
                # Method 1: from Poisson win probability
                try:
                    prob = float(str(row['poisson_win_prob'])
                                 .replace('%',''))
                    lam1 = max(0.5, prob / 35.0)
                except:
                    lam1 = 1.1

                # Method 2: from direct goals scored history
                try:
                    gs   = float(row.get('last_5_goals_scored', 0))
                    lam2 = max(0.5, gs / 5.0)
                except:
                    lam2 = lam1

                # Average both estimates — more robust than either alone
                return round(min(3.5, (lam1 + lam2) / 2), 3)

            h_lambda = derive_lambda(h_row.iloc[0])
            a_lambda = derive_lambda(a_row.iloc[0])
            h_name   = str(h_row.iloc[0].get('team_name', ''))
            a_name   = str(a_row.iloc[0].get('team_name', ''))
            fix_name = str(h_row.iloc[0].get('fixture', ''))
            key      = get_match_key(fix_name)

            opp_map[key] = {
                'home_lambda': h_lambda,
                'away_lambda': a_lambda,
                'home_team':   h_name,
                'away_team':   a_name,
                'fixture':     fix_name,
            }

        return opp_map

    # ──────────────────────────────────────────────────────────────────────
    # 4. MONTE CARLO — now with real opponent lambda
    # ──────────────────────────────────────────────────────────────────────
    def run_monte_carlo_matrix(
        engine_prob,
        dominance_gap,
        psych_score,
        is_veto,
        is_choked_opp,
        dna_align,
        is_risky,
        target_side,        # "home" or "away" — tells us which lambda is target
        opp_lambda_map_entry  # dict from build_opponent_lambda_map or None
    ):
        """
        Runs 10,000-trial Monte Carlo simulation.

        target_lambda : derived from engine_prob (same as before)
        opp_lambda    : NOW derived from the real opponent's scoring rate
                        pulled from the ranked CSV. Falls back to 1.1
                        only if the data is unavailable.
        """
        # ── TARGET LAMBDA ────────────────────────────────────────────────
        try:
            p_val = float(str(engine_prob).replace('%', ''))
        except:
            p_val = 35.0

        target_lambda = max(0.8, p_val / 30.0)

        # ── OPPONENT LAMBDA — REAL VALUE ─────────────────────────────────
        if opp_lambda_map_entry is not None:
            if target_side == "home":
                # target is home → opponent is away
                opp_lambda = opp_lambda_map_entry.get('away_lambda', 1.1)
            else:
                # target is away → opponent is home
                opp_lambda = opp_lambda_map_entry.get('home_lambda', 1.1)
        else:
            # Fallback only when CSV data unavailable
            opp_lambda = 1.1

        # ── SIGNAL MULTIPLIERS ───────────────────────────────────────────
        t_mult = 1.0
        o_mult = 1.0

        synergy_boost = 0.0
        if dna_align:
            synergy_boost += 0.08
        if psych_score != "N/A" and isinstance(psych_score, (int, float)):
            synergy_boost += float(psych_score) / 400.0
        if (dominance_gap != "N/A" and
                isinstance(dominance_gap, (int, float)) and
                dominance_gap > 0):
            synergy_boost += min(0.07, float(dominance_gap) / 200.0)

        t_mult *= (1.0 + min(0.25, synergy_boost))

        if is_choked_opp:
            o_mult *= 0.80
            t_mult *= 1.10

        if is_risky:
            o_mult *= 1.20

        if is_veto:
            t_mult *= 0.80
            o_mult *= 1.15

        # Cap multipliers — prevent extreme distortion
        t_mult = max(0.80, min(1.30, t_mult))
        o_mult = max(0.75, min(1.35, o_mult))

        target_lambda *= t_mult
        opp_lambda    *= o_mult

        # ── SIMULATION ───────────────────────────────────────────────────
        # 10,000 trials (was 5,000) for tighter probability estimates
        np.random.seed(42)   # reproducible — same inputs always same output
        sim_target = np.random.poisson(target_lambda, 10_000)
        sim_opp    = np.random.poisson(opp_lambda,    10_000)

        wins  = np.sum(sim_target > sim_opp)
        draws = np.sum(sim_target == sim_opp)

        m_prob = round((wins  / 10_000) * 100, 2)
        d_prob = round((draws / 10_000) * 100, 2)

        return m_prob, d_prob, round(target_lambda, 3), round(opp_lambda, 3)

    # ──────────────────────────────────────────────────────────────────────
    # 5. MAIN EXECUTION
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "="*145)
    print(
        f" 🚀 ALIENEDGE APEX WIN AGGREGATOR "
        f"(SUPER-MATRIX GODMODE) — {TODAY_STR}"
    )
    print("="*145)

    # ── A. WIN FORECAST (base math + opponent lambda builder) ────────────
    df_forecast  = None
    list_engine  = {}
    opp_lambda_map = {}
    risky_fixtures = set()

    if os.path.exists(FILE_WIN_FORECAST):
        df_forecast = pd.read_csv(FILE_WIN_FORECAST)
        opp_lambda_map = build_opponent_lambda_map(df_forecast)

        for _, row in df_forecast.iterrows():
            try:
                p_val = float(str(row.get('poisson_win_prob','0'))
                              .replace('%',''))
                if p_val >= 35.0:
                    key    = get_match_key(row['fixture'])
                    fid    = row.get('fixture_id')
                    is_risky = fid and int(fid) in risky_fixtures
                    list_engine[key] = {
                        "name":      row['fixture'],
                        "team":      row['team_name'],
                        "side":      str(row['side']).lower(),
                        "prob":      p_val,
                        "odds":      row.get('win_odds',
                                     row.get('Win_Odds','N/A')),
                        "fixture_id": fid,
                        "is_risky":  is_risky,
                        "risk_label": "⚠️ RISKY" if is_risky else "✅ NORMAL"
                    }
            except: continue

        print(
            f">> [WIN FORECAST] Loaded {len(list_engine)} baseline matches "
            f"(≥35% prob). Opponent lambda map: {len(opp_lambda_map)} entries."
        )
    else:
        print(f">> [FATAL] {FILE_WIN_FORECAST} not found.")
        return []

    # ── B. UNDERDOG RISK (risky_fixtures must be populated before A loop) ─
    if os.path.exists(FILE_UNDERDOG):
        df_ud    = pd.read_csv(FILE_UNDERDOG)
        prob_col = ('Audit_Real_Prob'
                    if 'Audit_Real_Prob' in df_ud.columns
                    else 'dog_score_prob')
        for _, row in df_ud.iterrows():
            try:
                prob = float(str(row.get(prob_col,'0')).replace('%',''))
                if prob > 50.0 and pd.notna(row.get('fixture_id')):
                    risky_fixtures.add(int(row['fixture_id']))
            except: continue
        # Re-tag engine entries now that risky_fixtures is populated
        for key, entry in list_engine.items():
            fid = entry.get('fixture_id')
            if fid and int(fid) in risky_fixtures:
                entry['is_risky']   = True
                entry['risk_label'] = "⚠️ RISKY"
        print(
            f">> [UNDERDOG ENGINE] {len(risky_fixtures)} risky fixtures tagged."
        )
    else:
        print(f">> [WARNING] {FILE_UNDERDOG} not found.")

    # ── C. WIN PSYCHOLOGY (locks & vetoes) ───────────────────────────────
    list_psych_locks  = {}
    list_psych_vetoes = {}

    if os.path.exists(FILE_WIN_PSYCHOLOGY):
        df_psych = pd.read_csv(FILE_WIN_PSYCHOLOGY)
        for _, row in df_psych.iterrows():
            key      = get_match_key(row['Fixture'])
            tier_str = str(row.get('Tier',''))
            preferred = str(row.get('Master_Pick','None'))

            pkg = {
                "fixture":   row['Fixture'],
                "score":     row.get('Audit_Score', 0),
                "tier":      tier_str,
                "preferred": preferred,
                "logic": (str(row.get('Home_Logic','')) + " | " +
                          str(row.get('Away_Logic','')))
            }

            if any(x in tier_str for x in
                   ["🚨 OVERTURNED","🛑 CAUTION","TRAP"]):
                if "🚨 OVERTURNED" in tier_str:
                    m = re.search(r"prefers\s+(.+?)(?:\)|$)", tier_str)
                    if m: pkg["preferred"] = m.group(1).strip()
                list_psych_vetoes[key] = pkg

            elif "💎" in tier_str or "🔥" in tier_str:
                list_psych_locks[key] = pkg

        print(
            f">> [PSYCHOLOGY] "
            f"{len(list_psych_locks)} Locks | "
            f"{len(list_psych_vetoes)} Vetoes."
        )
    else:
        print(f">> [WARNING] {FILE_WIN_PSYCHOLOGY} not found.")

    # ── D. U2S CHOKEHOLD ─────────────────────────────────────────────────
    list_u2s_chokehold = {}

    if os.path.exists(FILE_U2S_PSYCHOLOGY):
        df_u2s = pd.read_csv(FILE_U2S_PSYCHOLOGY)
        for _, row in df_u2s.iterrows():
            if any(x in str(row.get('Tier',''))
                   for x in ["🛑","CHOKEHOLD","VETOED"]):
                key = get_match_key(row['Fixture'])
                list_u2s_chokehold[key] = {
                    "fixture":  row['Fixture'],
                    "underdog": row['Underdog'],
                    "triggers": row['Triggers']
                }
        print(
            f">> [U2S CHOKEHOLD] "
            f"{len(list_u2s_chokehold)} suffocated underdogs."
        )
    else:
        print(f">> [WARNING] {FILE_U2S_PSYCHOLOGY} not found.")

    # ── E. MASTER CALIBRATION ────────────────────────────────────────────
    list_handshake_raw = {}

    if os.path.exists(FILE_CALIBRATION):
        df_hs = pd.read_csv(FILE_CALIBRATION)
        for _, row in df_hs.iterrows():
            key = get_match_key(row['fixture'])
            try:
                p = float(row.get('parity_gap',    0))
                d = float(row.get('Dominance_Gap', 0))
                rule_name = None
                if p <= -5 and d >= 20:
                    rule_name = "💎💎 ELITE SHIELD"
                elif d >= 15 and d >= (2*abs(p)) and not (-4 <= p <= 1):
                    rule_name = "💎🛡️ SPECIAL RULE 2"
                elif d >= 15:
                    rule_name = "💎🏦 ELITE BANKER"
                elif d >= 10:
                    rule_name = "💎✅ SYSTEMIC WIN"
                if rule_name:
                    list_handshake_raw[key] = {
                        "name": row['fixture'],
                        "rule": rule_name,
                        "p": p, "d": d
                    }
            except: pass
        print(
            f">> [HANDSHAKE] "
            f"{len(list_handshake_raw)} tactical anomalies."
        )
    else:
        print(f">> [WARNING] {FILE_CALIBRATION} not found.")

    # ── F. DNA MAPPING ───────────────────────────────────────────────────
    list_dna = {}
    api_map  = {}

    if os.path.exists(FILE_DNA):
        with open(FILE_DNA, "r") as f:
            dna_db = json.load(f)

        page = 1
        while True:
            resp = GET(
                f"/fixtures/date/{TODAY_STR}",
                params={"include":"participants","per_page":50,"page":page}
            )
            data = resp.get("data", [])
            if not data: break
            for fx in data:
                api_map[get_match_key(fx['name'])] = fx
            if len(data) < 50: break
            page += 1
            time.sleep(0.1)

        risk_map = {"High": 3, "Medium": 2, "Low": 1}
        for key, fx in api_map.items():
            hid = next(
                (pt['id'] for pt in fx['participants']
                 if pt['meta']['location'] == 'home'), None
            )
            aid = next(
                (pt['id'] for pt in fx['participants']
                 if pt['meta']['location'] == 'away'), None
            )
            if not hid or not aid: continue
            h_dna = dna_db.get(str(hid), {})
            a_dna = dna_db.get(str(aid), {})
            if not h_dna or not a_dna: continue

            h_i = h_dna.get("Market_Power_Scores",{}).get("Goal_Intent",0)
            h_t = h_dna.get("Tactical_DNA",{}).get("Tempo",0)
            h_r = risk_map.get(
                h_dna.get("Tactical_DNA",{}).get("Risk_Appetite","Low"), 1
            )
            a_i = a_dna.get("Market_Power_Scores",{}).get("Goal_Intent",0)
            a_t = a_dna.get("Tactical_DNA",{}).get("Tempo",0)
            a_r = risk_map.get(
                a_dna.get("Tactical_DNA",{}).get("Risk_Appetite","Low"), 1
            )

            if h_i > a_i and h_t > a_t and h_r >= a_r:
                list_dna[key] = {"fav_side":"home","fixture_id":fx['id']}
            elif a_i > h_i and a_t > h_t and a_r >= h_r:
                list_dna[key] = {"fav_side":"away","fixture_id":fx['id']}

        print(
            f">> [DNA ENGINE] "
            f"{len(list_dna)} superior DNA alignments found."
        )
    else:
        print(f">> [WARNING] {FILE_DNA} not found.")

    # ── G. VIP FEED ──────────────────────────────────────────────────────
    list_vip_feed = {}

    if os.path.exists(FILE_VIP_FEED):
        try:
            with open(FILE_VIP_FEED, "r") as f:
                feed_data = json.load(f)
            for item in feed_data:
                flags = item.get("flags", {})
                if (flags.get("home_h2h_win_100") or
                        flags.get("away_h2h_win_100")):
                    h_win  = flags.get("home_h2h_win_100", False)
                    h_name = item.get("teams",{}).get("home",{}).get("name","")
                    a_name = item.get("teams",{}).get("away",{}).get("name","")
                    f_name = f"{h_name} vs {a_name}"
                    key    = get_match_key(f_name)
                    list_vip_feed[key] = {
                        "name":        f_name,
                        "fixture_id":  item.get("fixture_id","N/A"),
                        "target_team": h_name if h_win else a_name,
                        "win_side":    "home" if h_win else "away"
                    }
            print(
                f">> [VIP FEED] "
                f"{len(list_vip_feed)} strict H2H VIP anomalies."
            )
        except Exception as e:
            print(f">> [WARNING] VIP feed error: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # 6. SUPER-MATRIX CROSS-REFERENCE
    # ──────────────────────────────────────────────────────────────────────
    print("\n>> 🧠 SUPER-MATRIX CROSS-EXAMINATION & MONTE CARLO GODMODE...")

    # Only iterate keys that have a real engine entry — this prevents
    # phantom rows from veto-only or lock-only sources
    all_keys = set(list_engine.keys())

    # Also include VIP and lock entries but only if they have a
    # corresponding engine entry OR we can derive a target cleanly
    for k in list(list_vip_feed.keys()) + list(list_psych_locks.keys()):
        all_keys.add(k)

    final_rows = []

    for key in all_keys:
        eng    = list_engine.get(key)
        hs     = list_handshake_raw.get(key)
        dna    = list_dna.get(key)
        vip    = list_vip_feed.get(key)
        p_lock = list_psych_locks.get(key)
        p_veto = list_psych_vetoes.get(key)
        choke  = list_u2s_chokehold.get(key)

        # ── TARGET RESOLUTION ────────────────────────────────────────────
        target_name = "N/A"
        target_side = "N/A"

        if eng:
            target_name = eng['team']
            target_side = eng['side']
        elif vip:
            target_name = vip['target_team']
            target_side = vip['win_side']
        elif p_lock and str(p_lock.get('preferred','')) not in ['None','N/A','']:
            target_name = p_lock['preferred']
        elif (p_veto and
              str(p_veto.get('preferred','')) not in ['None','N/A','']):
            # Only use veto preferred if it came from a clean regex parse
            raw_pref = str(p_veto.get('preferred',''))
            # Reject if it looks like a tier string was mis-parsed
            if any(x in raw_pref for x in ['🛑','🚨','CAUTION','TRAP']):
                continue   # phantom row — drop it
            target_name = raw_pref

        # Hard drop if we still have no clean target
        if not target_name or target_name in ['N/A','None','']:
            continue

        # ── FIXTURE ID ───────────────────────────────────────────────────
        f_id = (eng['fixture_id'] if eng
                else (vip['fixture_id'] if vip
                      else api_map.get(key,{}).get('id','N/A')))

        # ── DNA ALIGNMENT ────────────────────────────────────────────────
        dna_align = (dna and (target_side == dna['fav_side'] or
                               target_side == 'N/A'))

        # ── PSYCHOLOGY FLAGS ─────────────────────────────────────────────
        is_psych_lock = False
        psych_score   = "N/A"
        psych_logic   = "N/A"

        if p_lock and clean_n(p_lock['preferred']) in clean_n(target_name):
            is_psych_lock = True
            psych_score   = p_lock['score']
            psych_logic   = p_lock['logic']

        # ── VETO vs LOCK CONFLICT RESOLUTION (fix) ───────────────────────
        is_psych_veto = False
        veto_reason   = "N/A"

        if p_veto:
            veto_preferred = str(p_veto.get('preferred',''))
            veto_points_at_same_team = (
                veto_preferred in ['None','N/A',''] or
                clean_n(veto_preferred) in clean_n(target_name)
            )

            if is_psych_lock and veto_points_at_same_team:
                # Lock and veto agree on same team — trust the lock,
                # note the veto as a caution flag only
                is_psych_veto = False
                veto_reason   = f"⚠️ Minor veto noted: {p_veto['tier']}"
            elif is_psych_lock and not veto_points_at_same_team:
                # Genuine conflict — veto overrides lock for Category
                is_psych_veto = True
                veto_reason   = p_veto['tier']
            else:
                is_psych_veto = True
                veto_reason   = p_veto['tier']
                if "🚨 OVERTURNED" in veto_reason:
                    m = re.search(r"prefers\s+(.+?)(?:\)|$)", veto_reason)
                    if m:
                        veto_reason = (
                            f"🚨 OVERTURNED "
                            f"(Psych prefers {m.group(1).strip()})"
                        )

        # ── CHOKEHOLD ────────────────────────────────────────────────────
        is_choked_opp = (
            choke and
            clean_n(choke['underdog']) not in clean_n(target_name)
        )

        is_risky     = eng['is_risky'] if eng else False
        engine_prob  = eng['prob'] if eng else (65.0 if vip else 35.0)
        dom_gap      = hs['d'] if hs else "N/A"

        # ── MONTE CARLO with REAL OPPONENT LAMBDA ────────────────────────
        lam_entry = opp_lambda_map.get(key)  # may be None

        m_prob, d_prob, t_lam, o_lam = run_monte_carlo_matrix(
            engine_prob    = engine_prob,
            dominance_gap  = dom_gap,
            psych_score    = psych_score,
            is_veto        = is_psych_veto,
            is_choked_opp  = is_choked_opp,
            dna_align      = dna_align,
            is_risky       = is_risky,
            target_side    = target_side,
            opp_lambda_map_entry = lam_entry
        )

        # ── CATEGORY ASSIGNMENT ──────────────────────────────────────────
        # Category 1 gate: Monte Carlo must exceed 60% with real lambdas.
        # This prevents inflated probabilities reaching the top category.
        cat1_gate_passed = (m_prob >= 60.0)

        final_category = "N/A"
        cat_priority   = 99

        if is_psych_veto:
            final_category = "🚨 CATEGORY 3: THE VETO BOARD"
            cat_priority   = 3

        elif (eng and is_psych_lock and is_choked_opp and
              (dna_align or vip) and cat1_gate_passed):
            final_category = "🌌 CATEGORY 1: TOTAL CONVERGENCE"
            cat_priority   = 1

        elif (eng and is_psych_lock and cat1_gate_passed):
            final_category = "💎 CATEGORY 2: SUPREME AGREEMENT"
            cat_priority   = 2

        elif (eng and is_psych_lock and not cat1_gate_passed):
            # Lock fired but Monte Carlo not confident enough — demote
            final_category = "🔥 CATEGORY 4: LOCK BUT LOW CONFIDENCE"
            cat_priority   = 4

        elif eng and (dna_align or vip or hs):
            final_category = "🔥 CATEGORY 4: SOLID MATH WIN"
            cat_priority   = 4

        else:
            final_category = "📊 CATEGORY 5: BASE PLAYABLE"
            cat_priority   = 5

        # ── RISK STATUS ──────────────────────────────────────────────────
        if is_psych_veto:
            risk_status = "🛑 PSYCH VETO"
        elif is_risky and not is_choked_opp:
            risk_status = "⚠️ RISKY"
        else:
            risk_status = "✅ NORMAL"

        # Lambda transparency label
        lam_label = (
            f"T-λ:{t_lam} vs O-λ:{o_lam} "
            f"({'real' if lam_entry else 'fallback'})"
        )

        final_rows.append({
            "fixture_id":        f_id,
            "Fixture":           (eng['name'] if eng
                                  else (vip['name'] if vip
                                        else api_map.get(key,{})
                                        .get('name', key))),
            "Target":            target_name,
            "Category":          final_category,
            "Cat_Priority":      cat_priority,
            "Monte_Win_Prob":    m_prob,
            "Monte_Draw_Prob":   d_prob,
            "Lambda_Detail":     lam_label,
            "Underdog_Risk":     risk_status,
            "Psych_Score":       psych_score,
            "Psych_Logic":       (str(psych_logic)[:80] + "..."
                                  if len(str(psych_logic)) > 80
                                  else psych_logic),
            "Chokehold_Status":  ("🛑 OPPONENT CHOKED"
                                  if is_choked_opp else "Clear"),
            "Veto_Reason":       veto_reason,
        })

    # ──────────────────────────────────────────────────────────────────────
    # 7. FINAL OUTPUT
    # ──────────────────────────────────────────────────────────────────────
    if not final_rows:
        print("\n>> [FATAL] No matches processed.")
        return []

    df_final = pd.DataFrame(final_rows)
    df_final  = df_final.sort_values(
        by=["Cat_Priority","Monte_Win_Prob","Monte_Draw_Prob"],
        ascending=[True, False, True]
    )

    cat1_df = df_final[df_final['Cat_Priority'] == 1]
    cat2_df = df_final[df_final['Cat_Priority'] == 2]
    cat3_df = df_final[df_final['Cat_Priority'] == 3]
    cat4_df = df_final[df_final['Cat_Priority'] == 4]

    print("\n\n" + "★"*145)
    print(" 🏆 ALIENEDGE FINAL SUPER-MATRIX INTELLIGENCE (GODMODE) ")
    print("★"*145)

    print("\n" + "🌌"*50)
    print(" 🌌 CATEGORY 1: TOTAL CONVERGENCE — The Holy Grail 🌌")
    print("🌌"*50)
    print(
        "   All engines agree AND Monte Carlo ≥60% vs real opponent lambda.\n"
    )
    if not cat1_df.empty:
        for i, (_, row) in enumerate(cat1_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']}  |  Target: {row['Target']}  |  "
                f"Win: {row['Monte_Win_Prob']}%  |  Draw Risk: {row['Monte_Draw_Prob']}%"
            )
            print(f"   Lambdas   : {row['Lambda_Detail']}")
            print(f"   Psych     : +{row['Psych_Score']} | {row['Psych_Logic']}")
            print(f"   Chokehold : {row['Chokehold_Status']}\n")
    else:
        print("   [!] No Category 1 matches today — threshold not met.\n")

    print("\n" + "💎"*50)
    print(" 💎 CATEGORY 2: SUPREME AGREEMENT — Win + Psych Lock 💎")
    print("💎"*50)
    if not cat2_df.empty:
        for i, (_, row) in enumerate(cat2_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']}  |  Target: {row['Target']}  |  "
                f"Win: {row['Monte_Win_Prob']}%  |  Draw Risk: {row['Monte_Draw_Prob']}%"
            )
            print(f"   Lambdas   : {row['Lambda_Detail']}")
            print(f"   Psych     : +{row['Psych_Score']} | {row['Psych_Logic']}\n")
    else:
        print("   [!] No Category 2 matches today.\n")

    print("\n" + "🚨"*50)
    print(" 🚨 CATEGORY 3: THE VETO BOARD — Traps & Overturns 🚨")
    print("🚨"*50)
    if not cat3_df.empty:
        for i, (_, row) in enumerate(cat3_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']}  |  Target: {row['Target']}  |  "
                f"Win: {row['Monte_Win_Prob']}%  |  Draw Risk: {row['Monte_Draw_Prob']}%"
            )
            print(f"   🛑 {row['Veto_Reason']}\n")
    else:
        print("   [!] No vetoes today.\n")

    print("\n" + "🔥"*50)
    print(" 🔥 CATEGORY 4: SOLID MATH WIN — Strong Evidence 🔥")
    print("🔥"*50)
    if not cat4_df.empty:
        for i, (_, row) in enumerate(cat4_df.iterrows(), 1):
            print(
                f"{i}. {row['Fixture']}  |  Target: {row['Target']}  |  "
                f"Win: {row['Monte_Win_Prob']}%  |  Draw Risk: {row['Monte_Draw_Prob']}%"
            )
            print(f"   Lambdas   : {row['Lambda_Detail']}\n")
    else:
        print("   [!] No Category 4 matches today.\n")

    df_final.to_csv(FILE_FINAL_OUTPUT, index=False)
    print(f"\n[🏆] Master Matrix complete. Saved: {FILE_FINAL_OUTPUT}")

    return df_final.to_dict(orient="records")


# --- LOCAL TESTING BLOCK ---
if __name__ == "__main__":
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 2000)
    run_win_apex_aggregator()