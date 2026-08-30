import os
import re
import json
from datetime import datetime, timezone

def clean_n(name):
    """Normalizes team names to eliminate suffixes like FC, United, U19, etc."""
    if not name:
        return ""
    n = str(name).lower()
    for word in ["u19", "u23", "fc", "sc", "united", "city", "club", "afc", "rc", "as", "deportivo", "atletico"]:
        n = n.replace(word, "")
    return re.sub(r'[^a-z0-9]', '', n).strip()

def get_match_key(name):
    """Generates an alphabetical match key for order-independent team matching."""
    n = clean_n(name)
    parts = n.split('vs') if 'vs' in n else (n.split('-') if '-' in n else [n])
    parts = [p.strip() for p in parts]
    parts.sort()
    return "".join(parts)

def extract_match_data(fx):
    """
    Parses a raw SportMonks fixture object into standardized match data
    (half-time score, full-time score, corners, live state, elapsed minute).
    """
    scores = fx.get("scores", [])
    h_ht = a_ht = h_ft = a_ft = 0
    has_started = False
    is_finished = False

    # Check match completion state
    state_desc = str(fx.get("state", {}).get("description", "")).upper()
    if state_desc in ["FT", "AET", "FT_PEN", "FINISHED", "FULL-TIME", "ENDED"]:
        is_finished = True

    for s in scores:
        desc = str(s.get("description", "")).upper()
        if isinstance(s.get("score"), dict):
            p = str(s["score"].get("participant", "")).lower()
            g = int(float(s["score"].get("goals", 0) or 0))
        else:
            p = str(s.get("participant", "")).lower()
            g = int(float(s.get("goals", 0) or 0))

        if desc in ["1ST_HALF", "1ST HALF"]:
            has_started = True
            if p == "home": h_ht = g
            elif p == "away": a_ht = g
        if desc in ["CURRENT", "2ND_HALF", "2ND HALF", "FULL_TIME", "FT"]:
            has_started = True
            if p == "home": h_ft = max(h_ft, g)
            elif p == "away": a_ft = max(a_ft, g)

    # Extract team names & IDs
    parts = fx.get("participants", [])
    h_name = a_name = ""
    h_id = a_id = None
    if len(parts) >= 2:
        h = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), parts[0])
        a = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), parts[1])
        h_name = h.get("name", "")
        a_name = a.get("name", "")
        h_id = str(h.get("id", ""))
        a_id = str(a.get("id", ""))

    # Extract Corners
    h_c = a_c = 0
    for stat in fx.get("statistics", []):
        if "corner" in str(stat.get("type", {}).get("name", "")).lower():
            pid = str(stat.get("participant_id"))
            val = stat.get("data", {}).get("value", stat.get("value", 0))
            try:
                if pid == h_id: h_c += int(float(val))
                elif pid == a_id: a_c += int(float(val))
            except Exception: pass

    sh_h = max(0, h_ft - h_ht)
    sh_a = max(0, a_ft - a_ht)
    minute = fx.get("state", {}).get("minute") or fx.get("time", {}).get("minute") or 0

    return {
        "fixture_id": str(fx.get("id", "")),
        "home_team": h_name,
        "away_team": a_name,
        "h_ht": h_ht, "a_ht": a_ht,
        "h_ft": h_ft, "a_ft": a_ft,
        "ft_score": f"{h_ft}-{a_ft}",
        "total_goals": h_ft + a_ft,
        "sh_goals_home": sh_h, "sh_goals_away": sh_a, "sh_goals": sh_h + sh_a,
        "h_corners": h_c, "a_corners": a_c, "total_corners": h_c + a_c,
        "has_started": has_started,
        "is_finished": is_finished,
        "minute": minute
    }

def grade_row(market_type, row, actual_match):
    """
    Evaluates an individual prediction row against actual match data.
    Returns the exact 3-state verification payload.
    """
    # 1. SCHEDULED / PRE-MATCH STATE
    if not actual_match or not actual_match.get("has_started"):
        return {
            "status": "SCHEDULED",
            "score": "—",
            "minute": None,
            "verdict": "PENDING",
            "badge_text": "—",
            "note": "Awaiting Kickoff"
        }

    is_finished = actual_match.get("is_finished", False)
    ft_score = actual_match.get("ft_score", "0-0")
    minute = actual_match.get("minute", 0)

    # 2. LIVE IN-PLAY STATE
    if not is_finished:
        return {
            "status": "LIVE",
            "score": ft_score,
            "minute": minute,
            "verdict": "IN_PLAY",
            "badge_text": f"{ft_score} ({minute}')",
            "note": f"Match in play ({minute}')"
        }

    # 3. SETTLED / FINISHED STATE (Market-Aware Math)
    m = str(market_type).lower()
    h_ft = actual_match["h_ft"]
    a_ft = actual_match["a_ft"]
    tot_g = actual_match["total_goals"]
    won = False
    note = ""

    # --- 1X2 WIN ---
    if m in ["win", "1x2"]:
        target = str(row.get("Target") or row.get("team_name") or row.get("Master_Pick") or row.get("fixture") or "")
        winner = (actual_match["home_team"] if h_ft > a_ft else actual_match["away_team"] if a_ft > h_ft else "DRAW")
        won = clean_n(target) in clean_n(winner) or clean_n(winner) in clean_n(target)
        note = f"{winner} ({ft_score})"

    # --- GG / BTTS ---
    elif m in ["gg", "btts"]:
        won = (h_ft > 0 and a_ft > 0)
        note = f"Both scored ({ft_score})" if won else f"Blanked ({ft_score})"

    # --- OVER 2.5 ---
    elif m in ["o25", "over25", "over 2.5"]:
        won = (tot_g >= 3)
        note = f"{tot_g} goals ({ft_score})"

    # --- OVER 1.5 ---
    elif m in ["o15", "over15", "over 1.5"]:
        won = (tot_g >= 2)
        note = f"{tot_g} goals ({ft_score})"

    # --- CORNERS ---
    elif m in ["corners"]:
        line = float(row.get("Corner_Line") or 9.5)
        tot_c = actual_match["total_corners"]
        won = tot_c > line
        note = f"{tot_c} corners (Line {line})"

    # --- SECOND HALF GOALS (SHVI) ---
    elif m in ["shvi", "sh_goal"]:
        sh_g = actual_match["sh_goals"]
        won = sh_g > 0
        note = f"{sh_g} SH goals ({ft_score})"

    # --- UNDERDOG TO SCORE (U2S) ---
    elif m in ["u2s"]:
        target = str(row.get("Underdog") or row.get("Target_Underdog") or row.get("underdog_team") or "")
        if clean_n(target) in clean_n(actual_match["home_team"]):
            won = h_ft > 0
        elif clean_n(target) in clean_n(actual_match["away_team"]):
            won = a_ft > 0
        note = f"Underdog scored ({ft_score})" if won else f"Underdog blanked ({ft_score})"

    return {
        "status": "FINISHED",
        "score": ft_score,
        "minute": None,
        "verdict": "WON" if won else "LOST",
        "badge_text": f"{'✅' if won else '❌'} {ft_score}",
        "note": note
    }

def settle_predictions(predictions, live_matches_db, market_type="win"):
    """
    Settles a list of prediction rows against actual live/finished matches.
    PRIORITY 1: Match by fixture_id (exact & unambiguous)
    PRIORITY 2: Fallback to clean_n() name key
    """
    id_map = {str(fx.get("fixture_id")): fx for fx in live_matches_db if fx.get("fixture_id")}
    name_map = {get_match_key(f"{fx.get('home_team', '')} vs {fx.get('away_team', '')}"): fx for fx in live_matches_db if fx.get("home_team")}

    enriched = []
    for row in predictions:
        rec = dict(row)
        fid = str(rec.get("fixture_id") or rec.get("id") or "")
        fix_name = str(rec.get("fixture") or rec.get("Fixture") or rec.get("Match") or "")

        # 1. Match by fixture_id first
        matched = id_map.get(fid)

        # 2. Fallback to clean_n match key
        if not matched and fix_name:
            key = get_match_key(fix_name)
            matched = name_map.get(key)

        # Attach verification object to row
        rec["verification"] = grade_row(market_type, rec, matched)
        enriched.append(rec)

    return enriched
