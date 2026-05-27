import os
import sys
import requests
import pandas as pd
import json
import re
from datetime import datetime
from dotenv import load_dotenv

# --- 1. HOSTING & SETUP ---
load_dotenv()

BASE_DIR   = os.path.abspath(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MASTER_DIR = os.path.join(BASE_DIR, "master_aggregator")

API_KEY = os.getenv("SPORTMONKS_API_KEY") or "7ST9IhxYqJG7zaGlC47MICTW5bFKe8HyJGIZfIK7t52TkAOKHe8EsmXGrogM"

# ==============================================================================
# COLUMN CONTROL
# Lists exactly which columns to show per engine, in order.
# Columns not listed are silently excluded — this is how we stop corners
# from showing formations and player names.
# Add or remove names here to match your engine output exactly.
# ==============================================================================
ENGINE_COLUMNS = {

    "win": [
        "Fixture", "fixture", "Match",
        "Target", "Master_Pick", "team_name",
        "poisson_win_prob", "Super_Monte_Prob",
        "Category", "Cat_Priority", "Tier",
    ],

    "gg": [
        "Fixture", "fixture", "Match",
        "Super_Monte_Prob", "gg_prob",
        "Category", "Cat_Priority", "Tier",
    ],

    "o25": [
        "Fixture", "fixture", "Match",
        "Super_Monte_Prob", "over25_prob",
        "Category", "Cat_Priority", "Tier",
    ],

    "u2s": [
        "Fixture", "fixture",
        "Underdog", "Target_Underdog", "underdog_team",
        "Audit_Verdict",
        "Spear_Matchup",
        "Dog_Venue_SOT", "Fav_Venue_SOT",
        "Dog_H2H_SOT",   "Fav_H2H_SOT",
        "Dog_Opp_Avg_Conceded", "Fav_Opp_Avg_Conceded",
        "Dog_Scoring_Consistency",
        "Psych_Score", "Tier", "Triggers",
        "Super_Monte_Prob", "dog_score_prob",
        "Category", "Cat_Priority",
    ],

    # CORNERS: prediction columns only — NO formation, NO player names
    "corners": [
        "Fixture", "fixture", "Match",
        "True_Corner_Fav", "team_more_corners",
        "Corner_Team", "corner_prediction",
        "Win_Prob", "prob", "probability",
        "corner_prob",
        "expected_corners_home", "expected_corners_away",
        "home_corner_avg", "away_corner_avg",
        "Corner_Line", "corner_line", "Line",
        "Category", "Cat_Priority", "Tier",
    ],

    "shvi": [
        "Fixture", "fixture", "Match",
        "Super_Monte_Prob", "sh_gg_prob", "prob",
        "Category", "Cat_Priority", "Tier",
    ],
}

# ==============================================================================
# UTILITIES
# ==============================================================================
def GET(endpoint, params=None):
    if params is None: params = {}
    params['api_token'] = API_KEY
    url = f"https://api.sportmonks.com/v3/football{endpoint}"
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200: return r.json()
    except: pass
    return {"data": []}

def clean_n(name):
    n = str(name).lower()
    for word in ["u19","u23","fc","sc","united","city","club",
                 "afc","rc","as","deportivo","atletico"]:
        n = n.replace(word, "")
    return re.sub(r'[^a-z0-9]', '', n).strip()

def get_match_key(name):
    n     = clean_n(name)
    parts = n.split('vs') if 'vs' in n else (n.split('-') if '-' in n else [n])
    parts = [p.strip() for p in parts]
    parts.sort()
    return "".join(parts)

def _fixture_name(record):
    for key in ['Fixture','fixture','Match','match','name','Name']:
        val = record.get(key, None)
        if val and str(val).strip() not in ['','nan','None']:
            return str(val).strip()
    return None

# ==============================================================================
# SCORE EXTRACTOR
# ==============================================================================
def get_scores_ht_ft(scores_list):
    h_ht = a_ht = h_ft = a_ft = 0
    has_started = False
    for s in (scores_list or []):
        desc = str(s.get("description","")).upper()
        if isinstance(s.get("score"), dict):
            p = str(s["score"].get("participant","")).lower()
            g = int(float(s["score"].get("goals", 0) or 0))
        else:
            p = str(s.get("participant","")).lower()
            g = int(float(s.get("goals", 0) or 0))
        if desc in ["1ST_HALF","1ST HALF"]:
            has_started = True
            if p == "home": h_ht = g
            elif p == "away": a_ht = g
        if desc in ["CURRENT","2ND_HALF","2ND HALF","FULL_TIME","FT"]:
            has_started = True
            if p == "home": h_ft = max(h_ft, g)
            elif p == "away": a_ft = max(a_ft, g)
    return (h_ht, a_ht), (h_ft, a_ft), has_started

def extract_match_data(fx):
    (h_ht,a_ht),(h_ft,a_ft),has_started = get_scores_ht_ft(fx.get("scores",[]))
    h_id = next((str(p['id']) for p in fx.get('participants',[])
                 if p.get('meta',{}).get('location')=='home'), None)
    a_id = next((str(p['id']) for p in fx.get('participants',[])
                 if p.get('meta',{}).get('location')=='away'), None)
    if not h_id and len(fx.get('participants',[]))>=2:
        h_id = str(fx['participants'][0]['id'])
        a_id = str(fx['participants'][1]['id'])
    h_c = a_c = 0
    for stat in fx.get('statistics',[]):
        if 'corner' in stat.get('type',{}).get('name','').lower():
            pid = str(stat.get('participant_id'))
            val = stat.get('data',{}).get('value', stat.get('value',0))
            try:
                if pid==h_id: h_c += int(float(val))
                elif pid==a_id: a_c += int(float(val))
            except: pass
    sh_h = max(0, h_ft-h_ht); sh_a = max(0, a_ft-a_ht)
    return {
        "h_ht":h_ht,"a_ht":a_ht,"h_ft":h_ft,"a_ft":a_ft,
        "total_goals":h_ft+a_ft,
        "sh_goals_home":sh_h,"sh_goals_away":sh_a,"sh_goals":sh_h+sh_a,
        "h_corners":h_c,"a_corners":a_c,"total_corners":h_c+a_c,
        "has_started":has_started,
    }

# ==============================================================================
# ACTUAL RESULTS FETCHER
# ==============================================================================
def fetch_actual_results(date_str):
    print(f"\n  Fetching real results from SportMonks for {date_str}...")
    actual = {}
    page = 1; seen = set()
    while True:
        resp = GET(f"/fixtures/date/{date_str}", params={
            "include":"participants;scores;statistics;statistics.type",
            "per_page":50,"page":page})
        data = resp.get("data",[])
        if not data: break
        added = False
        for fx in data:
            fid = fx.get("id")
            if fid in seen: continue
            seen.add(fid); added = True
            parts = fx.get("participants",[])
            if len(parts)<2: continue
            h = next((p for p in parts if p.get('meta',{}).get('location')=='home'), parts[0])
            a = next((p for p in parts if p.get('meta',{}).get('location')=='away'), parts[1])
            key   = get_match_key(f"{h['name']} vs {a['name']}")
            stats = extract_match_data(fx)
            if stats["has_started"] or fx.get("scores"):
                stats.update({
                    "home_team":h['name'],"away_team":a['name'],
                    "ft_score":f"{stats['h_ft']}-{stats['a_ft']}",
                    "ht_score":f"{stats['h_ht']}-{stats['a_ht']}",
                })
                actual[key] = stats
        if not added: break
        page += 1
    print(f"  Downloaded actual results for {len(actual)} played matches.\n")
    return actual

# ==============================================================================
# FILE FINDER
# ==============================================================================
def find_files(prefixes, date_str, extensions=None):
    if extensions is None: extensions=[".csv",".json"]
    found=[]; pl=[p.lower() for p in prefixes]
    for d in [MASTER_DIR, OUTPUT_DIR]:
        if not os.path.exists(d): continue
        for f in os.listdir(d):
            fl=f.lower()
            if not any(fl.endswith(ext) for ext in extensions): continue
            if not any(p in fl for p in pl): continue
            if re.search(r'\d{4}-\d{2}-\d{2}',fl):
                if date_str in fl: found.append(os.path.join(d,f))
            else:
                found.append(os.path.join(d,f))
    return list(set(found))

# ==============================================================================
# COLUMN SELECTOR
# ==============================================================================
def select_cols(available, engine_key):
    wanted   = ENGINE_COLUMNS.get(engine_key, [])
    selected = [c for c in wanted if c in available]
    return selected if selected else list(available)

# ==============================================================================
# BORDERED TABLE PRINTER
# Draws box-drawing character tables that are readable at a glance.
# ==============================================================================
TERM_WIDTH = 200

# Column width caps (characters) — keeps long text from exploding the table
COL_CAPS = {
    'Fixture':38,'fixture':38,'Match':38,
    'Triggers':48,
    'Verdict':40,
    'Actual_Score':13,
    'Tier':26,
    'Spear_Matchup':24,
    'Audit_Verdict':16,
    'Dog_Scoring_Consistency':14,
}
DEFAULT_CAP = 20

def _col_w(col, rows):
    cap     = COL_CAPS.get(col, DEFAULT_CAP)
    header  = len(str(col))
    content = max((len(str(r.get(col,''))) for r in rows), default=0)
    return min(cap, max(header, content, 4))

def _trunc(val, width):
    s = str(val) if str(val) not in ['nan','None',''] else ''
    return (s[:width-1]+'…') if len(s)>width else s.ljust(width)

def _border(widths, cols, left, mid, right, fill='─'):
    segs = [fill*(w+2) for w in [widths[c] for c in cols]]
    return left + mid.join(segs) + right

def _row_line(record, widths, cols):
    cells = ['│ ' + _trunc(record.get(c,''), widths[c]) + ' ' for c in cols]
    return ''.join(cells) + '│'

def _header_line(widths, cols):
    cells = ['│ ' + str(c).ljust(widths[c]) + ' ' for c in cols]
    return ''.join(cells) + '│'

def print_bordered_table(rows, display_cols, precision_label, wins, losses, skipped):
    """
    Prints a full bordered table:
      ┌──────┬──────┐
      │ Col1 │ Col2 │
      ├──────┼──────┤
      │ val  │ val  │
      └──────┴──────┘
    """
    all_cols = display_cols + ['Actual_Score','Verdict']
    widths   = {c: _col_w(c, rows) for c in all_cols}

    # Shrink widest column if total overflows terminal
    total_w = sum(widths[c]+3 for c in all_cols) + 1
    if total_w > TERM_WIDTH:
        for trim in ['Triggers','Verdict','Fixture','fixture']:
            if trim in widths and total_w > TERM_WIDTH:
                excess        = total_w - TERM_WIDTH
                widths[trim]  = max(10, widths[trim]-excess)
                total_w       = sum(widths[c]+3 for c in all_cols)+1

    top    = _border(widths, all_cols, '  ┌','┬','┐')
    header = '  ' + _header_line(widths, all_cols)
    mid    = _border(widths, all_cols, '  ├','┼','┤')
    bottom = _border(widths, all_cols, '  └','┴','┘')

    print(top)
    print(header)
    print(mid)
    for row in rows:
        print('  ' + _row_line(row, widths, all_cols))
    print(bottom)

    total = wins + losses
    if total > 0:
        pct    = wins/total*100
        filled = int(pct/5)
        bar    = '█'*filled + '░'*(20-filled)
        flag   = '✅ PROFITABLE' if pct>=55 else ('⚠️  BORDERLINE' if pct>=45 else '❌ BELOW PAR')
        print(f"\n  🎯 {precision_label}: {wins}/{total} ({pct:.1f}%)  [{bar}]  {flag}")
        if skipped: print(f"  ⚪ {skipped} rows skipped — result not found or not played yet")
    else:
        print(f"\n  ⚪ {precision_label}: No verifiable results found for this date")
    print()

# ==============================================================================
# VERDICT ATTACHMENT
# ==============================================================================
def attach_verdicts(rows, results_db, verdict_fn):
    out=[]; wins=losses=skipped=0
    for row in rows:
        rec      = dict(row) if not isinstance(row,dict) else row.copy()
        fix_name = _fixture_name(rec)
        if not fix_name:
            rec['Actual_Score']='N/A'; rec['Verdict']='⚪ No fixture name'
            out.append(rec); continue
        key = get_match_key(fix_name)
        if key not in results_db:
            rec['Actual_Score']='Not played'; rec['Verdict']='⚪ Result not found'
            skipped+=1; out.append(rec); continue
        actual    = results_db[key]
        won, note = verdict_fn(rec, actual)
        rec['Actual_Score'] = actual.get('ft_score','N/A')
        rec['Verdict']      = ('✅ WON  — ' if won else '❌ LOST — ')+note
        if won: wins+=1
        else:   losses+=1
        out.append(rec)
    return out, wins, losses, skipped

# ==============================================================================
# DATAFRAME FILTER
# ==============================================================================
def _filter_df(df):
    if 'Cat_Priority' in df.columns:
        return df[df['Cat_Priority'].isin([1,2,3,4])].sort_values('Cat_Priority').copy()
    if 'Tier' in df.columns:
        mask = df['Tier'].astype(str).str.contains(
            r'💎|🔥|Elite|Strong|LOCK|PLAY|MONITOR', na=False)
        return df[mask].copy() if mask.any() else df.copy()
    return df.copy()

def _group_col(df):
    for c in ['Category','Tier','section','Group']:
        if c in df.columns: return c
    return None

# ==============================================================================
# SECTION RUNNERS
# ==============================================================================
def run_csv_section(fp, engine_key, section_emoji, precision_label,
                    verdict_fn, results_db):
    try:
        df = pd.read_csv(fp, encoding='utf-8', on_bad_lines='skip')
        df = _filter_df(df)
        if df.empty:
            print(f"  ⚪ No qualifying rows in {os.path.basename(fp)}")
            return 0,0

        print('\n' + '═'*100)
        print(f"  {section_emoji}   {os.path.basename(fp)}")
        print('═'*100)

        gc = _group_col(df)
        groups = df.groupby(gc, sort=False) if gc else [("",df)]
        total_w=total_l=0

        for gname, gdf in groups:
            if gc and (pd.isna(gname) or str(gname).strip()==''):
                continue
            if gc and str(gname).strip():
                print(f"\n  ── {str(gname).upper()} ──")

            display_cols = select_cols(gdf.columns.tolist(), engine_key)
            raw_rows     = [row for _,row in gdf.iterrows()]
            out, w, l, s = attach_verdicts(raw_rows, results_db, verdict_fn)

            # Build display dicts with only selected cols
            disp = []
            for rec in out:
                d = {c: rec.get(c,'') for c in display_cols}
                d['Actual_Score'] = rec['Actual_Score']
                d['Verdict']      = rec['Verdict']
                disp.append(d)

            print_bordered_table(disp, display_cols, precision_label, w, l, s)
            total_w+=w; total_l+=l

        return total_w, total_l
    except Exception as e:
        print(f"  ⚠️  Error ({os.path.basename(fp)}): {e}")
        return 0,0


def run_json_section(fp, engine_key, section_emoji, precision_label,
                     verdict_fn, results_db):
    try:
        with open(fp,'r',encoding='utf-8') as f: data=json.load(f)
        items = list(data.values()) if isinstance(data,dict) else data
        if not items:
            print(f"  ⚪ No items in {os.path.basename(fp)}")
            return 0,0

        print('\n'+'═'*100)
        print(f"  {section_emoji}   {os.path.basename(fp)}")
        print('═'*100)

        groups={}
        for item in items:
            cat = item.get('Category', item.get('Tier', item.get('tier','General')))
            groups.setdefault(cat,[]).append(item)

        wanted  = ENGINE_COLUMNS.get(engine_key,[])
        total_w=total_l=0

        for cat_name, cat_items in groups.items():
            if str(cat_name).strip():
                print(f"\n  ── {str(cat_name).upper()} ──")

            # Keys present in this group
            all_keys=[]; seen_k=set()
            for item in cat_items:
                for k in item.keys():
                    if k not in seen_k: all_keys.append(k); seen_k.add(k)

            display_cols = [c for c in wanted if c in all_keys] or all_keys
            out, w, l, s = attach_verdicts(cat_items, results_db, verdict_fn)

            disp=[]
            for rec in out:
                d = {c: rec.get(c,'') for c in display_cols}
                d['Actual_Score']=rec['Actual_Score']
                d['Verdict']=rec['Verdict']
                disp.append(d)

            print_bordered_table(disp, display_cols, precision_label, w, l, s)
            total_w+=w; total_l+=l

        return total_w, total_l
    except Exception as e:
        print(f"  ⚠️  Error ({os.path.basename(fp)}): {e}")
        return 0,0

# ==============================================================================
# VERDICT FUNCTIONS
# ==============================================================================
def verdict_win(row, actual):
    target = str(row.get('Target', row.get('Master_Pick',
             row.get('team_name', row.get('pick','')))))
    if not target or target in ['None','nan','']: return False,"No target team in row"
    winner = (actual['home_team'] if actual['h_ft']>actual['a_ft']
              else actual['away_team'] if actual['a_ft']>actual['h_ft'] else "DRAW")
    won = clean_n(target) in clean_n(winner) or clean_n(winner) in clean_n(target)
    return won, f"{winner} ({actual['ft_score']})"

def verdict_gg(row, actual):
    won = actual['h_ft']>0 and actual['a_ft']>0
    return won, (f"Both scored ({actual['ft_score']})" if won
                 else f"{'Home' if actual['a_ft']==0 else 'Away'} blanked ({actual['ft_score']})")

def verdict_o25(row, actual):
    won = actual['total_goals']>=3
    return won, f"{actual['total_goals']} goals ({actual['ft_score']})"

def verdict_u2s(row, actual):
    target = str(row.get('Underdog', row.get('Target_Underdog',
             row.get('underdog_team', row.get('dog_name','')))))
    if not target or target in ['None','nan','']: return False,"No underdog name in row"
    if clean_n(target) in clean_n(actual['home_team']):
        return actual['h_ft']>0, f"{actual['home_team']} scored {actual['h_ft']} ({actual['ft_score']})"
    if clean_n(target) in clean_n(actual['away_team']):
        return actual['a_ft']>0, f"{actual['away_team']} scored {actual['a_ft']} ({actual['ft_score']})"
    return False, f"Could not match '{target}' to home/away"

def verdict_corners_team(row, actual):
    target = str(row.get('True_Corner_Fav', row.get('team_more_corners',
             row.get('Corner_Team', row.get('corner_prediction',
             row.get('team_name',''))))))
    if not target or target in ['None','nan','Tight','']: return False,"No corner team target"
    winner = (actual['home_team'] if actual['h_corners']>actual['a_corners']
              else actual['away_team'] if actual['a_corners']>actual['h_corners'] else "TIE")
    won = clean_n(target) in clean_n(winner) or clean_n(winner) in clean_n(target)
    return won, f"H:{actual['h_corners']} A:{actual['a_corners']} — {winner} won"

def verdict_corners_over(row, actual):
    line = 9.5
    for col in ['Corner_Line','corner_line','Line','Over_Line']:
        v = row.get(col)
        if v and str(v) not in ['nan','None','']:
            try: line=float(v); break
            except: pass
    won = actual['total_corners']>line
    return won, f"{actual['total_corners']} corners (line {line})"

def verdict_sh_goal(row, actual):
    won = actual['sh_goals']>0
    return won, f"SH goals {actual['sh_goals']} (HT {actual['ht_score']} FT {actual['ft_score']})"

def verdict_sh_gg(row, actual):
    won = actual['sh_goals_home']>0 and actual['sh_goals_away']>0
    return won, (f"SH: H+{actual['sh_goals_home']} A+{actual['sh_goals_away']} "
                 f"(HT {actual['ht_score']} FT {actual['ft_score']})")

# ==============================================================================
# ENGINE RUNNERS
# ==============================================================================
def verify_win_matrix(date_str, results_db):
    prefixes=["WIN_SUPER_MATRIX_FINAL","ALIENEDGE_WIN_PREDICTIONS","ranked_win_forecast"]
    total_w=total_l=0
    for fp in find_files(prefixes, date_str,[".csv"]):
        w,l=run_csv_section(fp,"win","🏆 WIN PREDICTIONS","WIN PRECISION",verdict_win,results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

def verify_gg_matrix(date_str, results_db):
    prefixes=["FINAL_GG_MASTER_LIVE","ALIENEDGE_GG_PSYCHOLOGY_FINAL",
              "JUDGED_GG_PICKS","forecast_final_gg_precision"]
    total_w=total_l=0
    for fp in find_files(prefixes, date_str,[".csv"]):
        w,l=run_csv_section(fp,"gg","⚽ GG PREDICTIONS","GG PRECISION",verdict_gg,results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

def verify_o25_matrix(date_str, results_db):
    prefixes=["O25_MASTER_LIVE","ALIENEDGE_O25_PREDICTIONS",
              "over25_stage3_final","master_over_stage2"]
    total_w=total_l=0
    for fp in find_files(prefixes, date_str,[".csv"]):
        w,l=run_csv_section(fp,"o25","🔥 OVER 2.5 PREDICTIONS","O2.5 PRECISION",verdict_o25,results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

def verify_u2s_matrix(date_str, results_db):
    prefixes=["FINAL_APEX_UD_SCORE","ALIENEDGE_U2S_PSYCHOLOGY",
              "audited_underdog_backtest","backtest_underdog"]
    total_w=total_l=0
    for fp in find_files(prefixes, date_str,[".csv"]):
        w,l=run_csv_section(fp,"u2s","🐺 U2S PREDICTIONS","U2S PRECISION",verdict_u2s,results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

def verify_corners(date_str, results_db):
    total_w=total_l=0
    for fp in find_files(["SUPREME_EVOLUTION_OUTPUT","ALIENEDGE_CORNER_AGGREGATOR"],
                         date_str,[".csv"]):
        try:
            df  = pd.read_csv(fp, encoding='utf-8', nrows=1)
            has_t = any(c in df.columns for c in
                        ['True_Corner_Fav','team_more_corners','Corner_Team'])
            vfn = verdict_corners_team if has_t else verdict_corners_over
        except:
            vfn = verdict_corners_team
        w,l=run_csv_section(fp,"corners","🚩 CORNER PREDICTIONS","CORNER PRECISION",vfn,results_db)
        total_w+=w; total_l+=l
    for fp in find_files(["corner3_qualified"], date_str,[".json"]):
        w,l=run_json_section(fp,"corners","🚩 CORNER PREDICTIONS","CORNER PRECISION",
                             verdict_corners_team, results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

def verify_shvi(date_str, results_db):
    prefixes=["shvi_vortex_report","shvi_strict_filtered","FINAL_SH_GG_8GOAL"]
    total_w=total_l=0
    for fp in find_files(prefixes, date_str,[".csv",".json"]):
        vfn = verdict_sh_gg if "GG" in fp.upper() else verdict_sh_goal
        if fp.endswith(".json"):
            w,l=run_json_section(fp,"shvi","⏱️ SHVI PREDICTIONS","SHVI PRECISION",vfn,results_db)
        else:
            w,l=run_csv_section(fp,"shvi","⏱️ SHVI PREDICTIONS","SHVI PRECISION",vfn,results_db)
        total_w+=w; total_l+=l
    return total_w, total_l

# ==============================================================================
# GRAND SUMMARY
# ==============================================================================
def print_grand_summary(section_results):
    print('\n'+'█'*100)
    print(f"{'📊  ALIENEDGE TOTAL SYSTEM — GRAND SUMMARY':^100}")
    print('█'*100+'\n')

    # Table header
    h1 = f"  {'Engine':<24} │ {'Wins':>5} │ {'Losses':>6} │ {'Total':>6} │ {'Precision':>10} │  Progress"
    div = "  " + "─"*24 + "─┼─" + "─"*5 + "─┼─" + "─"*6 + "─┼─" + "─"*6 + "─┼─" + "─"*10 + "─┼─" + "─"*26
    print(h1)
    print(div)

    grand_w=grand_l=0
    for name,(w,l) in section_results.items():
        total = w+l
        pct   = (w/total*100) if total>0 else 0
        bar   = '█'*int(pct/5) + '░'*(20-int(pct/5))
        flag  = '✅' if pct>=55 else ('⚠️ ' if pct>=45 else '❌')
        print(f"  {name:<24} │ {w:>5} │ {l:>6} │ {total:>6} │ {pct:>9.1f}% │  {bar}  {flag}")
        grand_w+=w; grand_l+=l

    print(div)
    gt = grand_w+grand_l
    gp = (grand_w/gt*100) if gt>0 else 0
    gb = '█'*int(gp/5)+'░'*(20-int(gp/5))
    gf = '✅' if gp>=55 else ('⚠️ ' if gp>=45 else '❌')
    print(f"  {'OVERALL':<24} │ {grand_w:>5} │ {grand_l:>6} │ {gt:>6} │ {gp:>9.1f}% │  {gb}  {gf}")
    print()
    print('█'*100)
    print(f"{'✅  TOTAL SYSTEM AUDIT COMPLETE':^100}")
    print('█'*100+'\n')

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print('\n'+'█'*100)
    print(f"{'⚖️  ALIENEDGE TOTAL SYSTEM AUDITOR':^100}")
    print(f"{'Engine columns preserved exactly  •  Verdict appended  •  Clean bordered tables':^100}")
    print('█'*100)

    target_date = input("\n  Enter Past Date to Audit (YYYY-MM-DD): ").strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', target_date):
        print("  Invalid date format. Use YYYY-MM-DD.")
        return

    results_db = fetch_actual_results(target_date)
    if not results_db:
        print("  No match results found. Games may not be played yet.")
        return

    section_results = {}
    w,l = verify_win_matrix(target_date, results_db);    section_results["🏆 Win"]       = (w,l)
    w,l = verify_gg_matrix(target_date, results_db);     section_results["⚽ GG"]         = (w,l)
    w,l = verify_o25_matrix(target_date, results_db);    section_results["🔥 Over 2.5"]   = (w,l)
    w,l = verify_u2s_matrix(target_date, results_db);    section_results["🐺 U2S"]        = (w,l)
    w,l = verify_corners(target_date, results_db);       section_results["🚩 Corners"]    = (w,l)
    w,l = verify_shvi(target_date, results_db);          section_results["⏱️ SHVI"]       = (w,l)

    print_grand_summary(section_results)

if __name__ == "__main__":
    main()