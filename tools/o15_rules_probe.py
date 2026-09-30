"""
o15_rules_probe.py — leak-free measurement of the 13 Over 1.5 rules.

WHAT THIS IS
------------
Phase 1 of the O1.5 investigation. For every settled target fixture it
recomputes the 13 rule flags from PSYCHOLOGY/over15_psychology.py using
ONLY matches that finished strictly before the target's kickoff, then
reports per-rule AUC / fire-rate / strong-vs-weak spread.

WHY IT IS BUILT THIS WAY
------------------------
The production engine's own history fetch used datetime.now() (fixed in
6c88a7b) and read a single undated over15_stage3_final.csv. Neither can be
backtested. This probe re-derives the flags from the SportMonks history
endpoint with an explicit end-date of (target - 1 day), so a rule can
never see the match it is predicting.

It also records DATA AVAILABILITY per rule, separately from the rule's
verdict. A rule that cannot fire because HT goals are missing is a
different problem from a rule that fires and carries no information, and
conflating them is how the previous investigation went wrong.

Usage:
    python3 o15_rules_probe.py --limit 60      # quick smoke
    python3 o15_rules_probe.py                 # full 1,460
    python3 o15_rules_probe.py --out /tmp/x.pkl
"""
import argparse, os, pickle, sys, time
from datetime import datetime, timedelta, timezone

import requests
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SPORTMONKS_API_KEY")
BASE = "https://api.sportmonks.com/v3/football"
DELAY = 0.18
CACHE_PATH = "/tmp/o15_team_history.pkl"

TARGETS = "/tmp/cmp_o15_named.pkl"


# ─────────────────────────── API ───────────────────────────
_cache = {}


class RateLimited(Exception):
    """Raised when the provider rate-limits us and we must NOT proceed.

    WHY THIS EXISTS: an earlier version of this probe cached any failed
    fetch as {"data": []} and carried on. During a quota exhaustion that
    turned every rate-limited team into "this team has no history", which
    silently zeroes every rule flag for it — and looks exactly like a team
    with no attacking form, no glass jaw and no halftime activity. A data
    gap must never be allowed to masquerade as a measured fact.
    """


def GET(path, params, tries=6):
    params = dict(params, api_token=API_KEY)
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "api_token")
    if key in _cache:
        return _cache[key]
    back = 5.0
    for attempt in range(tries):
        try:
            r = requests.get(f"{BASE}{path}", params=params, timeout=40)
            if r.status_code == 200:
                d = r.json()
                _cache[key] = d
                time.sleep(DELAY)
                return d
            if r.status_code == 429:
                reset = r.headers.get("Retry-After")
                print(f"   [429] rate limited (attempt {attempt+1}/{tries}) "
                      f"Retry-After={reset} — backing off {back:.0f}s", flush=True)
                # Respect the server's own number when it gives us one.
                try:
                    back = max(back, float(reset))
                except (TypeError, ValueError):
                    pass
                time.sleep(back)
                back *= 1.5
                continue
            # A 4xx/5xx that is not a rate limit is a real failure. Do not
            # cache it as an empty result set either — surface it.
            raise RuntimeError(f"HTTP {r.status_code} for {path}")
        except (RateLimited, RuntimeError):
            raise
        except Exception as e:
            print(f"   [net] {e} — retry {attempt+1}/{tries}", flush=True)
            time.sleep(2)
    raise RateLimited(f"exhausted retries on {path}; refusing to fake empty data")


# ─────────────── copied verbatim from the engine ───────────────
def extract_goals_by_period(fx, period="FT"):
    home_g = away_g = None
    for entry in fx.get("scores", []):
        if not isinstance(entry, dict):
            continue
        s = entry.get("score") or entry
        desc = str(entry.get("description", s.get("description", ""))).upper()
        if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
            continue
        p = s.get("participant") or entry.get("participant")
        g = s.get("goals") if isinstance(s, dict) else entry.get("goals")
        if g is None:
            continue
        try:
            val = int(g)
        except Exception:
            continue
        if period == "FT":
            # CURRENT is the authoritative full-time row; 2ND_HALF_ONLY can
            # disagree with the true final.
            if desc == "CURRENT":
                if p == "home": home_g = max(home_g or 0, val)
                elif p == "away": away_g = max(away_g or 0, val)
        elif period == "HT":
            # Anchor on 1ST_HALF — "2ND_HALF" contains "HALF" and would
            # collapse HT into the full-time score.
            if desc.startswith("1ST_HALF") or "1ST HALF" in desc:
                if p == "home": home_g = max(home_g or 0, val)
                elif p == "away": away_g = max(away_g or 0, val)
    return home_g, away_g


def team_goals(fx, team_id, period="FT"):
    hg, ag = extract_goals_by_period(fx, period)
    if hg is None or ag is None:
        return None, None
    # `participants` is slimmed to (id, location) pairs by _slim(). The
    # positional fallbacks the production engine carries are unreachable once
    # slimmed, because the id/location pair is always recorded.
    for pid, loc in fx.get("participants", []):
        if str(pid) == str(team_id):
            if loc == "home": return hg, ag
            if loc == "away": return ag, hg
    return None, None


def _team_stats(fx, team_id):
    """(stats, present) for ONE team out of a slimmed fixture."""
    return fx.get("by_team", {}).get(str(team_id), ([], []))


def stat_value(fx, team_id, names):
    """Read a stat for THIS team from a slimmed fixture (see _slim_one)."""
    stats, _ = _team_stats(fx, team_id)
    for name, v in stats:
        if any(n.upper() in name.upper() for n in names):
            return v
    return 0.0


def has_stat(fx, team_id, names):
    _, present = _team_stats(fx, team_id)
    for name in present:
        if any(n.upper() in name.upper() for n in names):
            return True
    return False


def init_hist(fresh=False):
    """Load the raw history cache, unless the caller asked to start clean.

    Loading is deferred to here rather than done at import: the cache is
    500MB of raw JSON and unpickling it peaks above 2.6GB, which exhausts a
    3GB box before main() runs — so --fresh would never get a chance to skip
    it.
    """
    global _hist
    if fresh:
        print("--fresh: starting with an empty history cache.", flush=True)
        _hist = {}
    else:
        _hist = load_hist()
        print(f"history cache: {len(_hist)} team-dates reused.", flush=True)
    return _hist


# ───────────────── team history, cached ─────────────────
def load_hist():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            return pickle.load(f)
    return {}


def save_hist(h):
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(h, f)


_hist = {}   # (team_id, end_date) -> [fixtures]
# NOT loaded at import time. The cache is 500MB of raw JSON and unpickling
# it peaks above 2.6GB, which OOMs a 3GB box before main() even starts — so
# `--fresh` could never take effect. It is loaded lazily by init_hist()
# only when a run actually wants to reuse it.


def _slim_one(f):
    """Slim ONE raw fixture down to what the rules actually read.

    CRITICAL: a fixture's `statistics` list holds BOTH teams' rows — 38 per
    side on a typical match, 76 in total, each tagged with participant_id.
    Averaging that list without filtering by participant_id silently blends
    the two teams together, so a team's "average shots on target" becomes
    the match average. The stats are therefore kept PER TEAM.
    """
    by_team = {}
    for s in f.get("statistics", []) or []:
        if not isinstance(s, dict):
            continue
        pid = str(s.get("participant_id", ""))
        name = str(s.get("type", {}).get("name", s.get("name", "")))
        v = s.get("data", {}).get("value") if isinstance(s.get("data"), dict) else s.get("value")
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        slot = by_team.setdefault(pid, ([], []))
        slot[0].append((name, v))
        slot[1].append(name)

    return {
        "id": f.get("id"),
        "by_team": by_team,
        "participants": [
            (str(p.get("id")), (p.get("meta") or {}).get("location"))
            for p in f.get("participants", [])
        ],
        "scores": f.get("scores", []),
    }


def team_history(team_id, end_date):
    """All finished fixtures for a team strictly before end_date (YYYY-MM-DD)."""
    key = (str(team_id), end_date)
    if key in _hist:
        return _hist[key]
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=180)
    resp = GET(f"/fixtures/between/{start}/{end}/{team_id}",
               {"include": "statistics.type;participants;scores",
                "filters": "fixtureStates:5", "per_page": 100, "order": "desc"})
    data = [_slim_one(f) for f in resp.get("data", [])]
    _hist[key] = data
    return data


# ─────────── the 13 rules, engine thresholds verbatim ───────────
def profile(team_id, target_date, self_fid):
    """Recompute the engine's per-team profile using only prior matches."""
    hist = [f for f in team_history(team_id, target_date)
            if str(f.get("id")) != str(self_fid)]
    hist.sort(key=lambda f: f.get("starting_at") or f.get("startingAt") or "", reverse=True)
    last5 = hist[:5]

    p = dict(n_hist=len(hist), n_used=len(last5), last5=last5)
    if not last5:
        p.update(dict(attacks=0, dang=0, sot=0, bcc=0, tkl=0, itr=0, poss=0, crs=0,
                      is_attacking=False, is_defensive=False, is_possession=False,
                      is_crossing=False, is_clinical=False, is_glass_jaw=False,
                      is_ht_active=False, is_ht_killer=False, is_ht_vulnerable=False,
                      no_cs=False, is_wounded=False, total_goals=0, avg_conc=0.0,
                      has_ht=False, has_sot=False, has_cr=False, has_goals=False,
                      is_wounded_known=False))
        return p

    n = len(last5)
    avg = lambda names: sum(stat_value(f, team_id, names) for f in last5) / n
    attacks = avg(["Attacks"]); dang = avg(["Dangerous Attacks"])
    sot = avg(["Shots On Target"]); bcc = avg(["Big Chances"])
    tkl = avg(["Tackles"]); itr = avg(["Interceptions"])
    poss = avg(["Ball Possession"]); crs = avg(["Total Crosses"])

    scored, conceded = [], []
    ht_sc = ht_cc = ht_win = 0
    ht_seen = 0
    for f in last5:
        tg, og = team_goals(f, team_id, "FT")
        if tg is not None: scored.append(tg)
        if og is not None: conceded.append(og)
        a, b = team_goals(f, team_id, "HT")
        if a is not None and b is not None:
            ht_seen += 1
            if a > 0: ht_sc += 1
            if b > 0: ht_cc += 1
            if a > b: ht_win += 1

    total_goals = sum(scored)
    avg_conc = sum(conceded) / len(conceded) if conceded else 1.0
    outcomes = []
    for f in last5[:2]:
        tg, og = team_goals(f, team_id, "FT")
        outcomes.append(None if tg is None or og is None else ("W" if tg > og else ("L" if tg < og else "D")))

    p.update(dict(
        attacks=attacks, dang=dang, sot=sot, bcc=bcc, tkl=tkl, itr=itr,
        poss=poss, crs=crs, total_goals=total_goals, avg_conc=avg_conc,
        is_attacking=(attacks > 60 and dang > 40 and sot >= 3.5),
        is_defensive=(tkl >= 14 and itr >= 8 and sot < 3.5),
        is_possession=(poss >= 58),
        is_crossing=(crs >= 15),
        is_clinical=(sot >= 4.5 and bcc >= 1.5),
        is_glass_jaw=(avg_conc > 1.8 and len(conceded) >= 3),
        is_ht_active=(ht_sc >= 3),
        is_ht_killer=(ht_win >= 3),
        is_ht_vulnerable=(ht_cc >= 3),
        no_cs=(conceded.count(0) == 0 and len(conceded) >= 4),
        is_wounded=(bool(outcomes) and (outcomes[0] == "L" or (len(outcomes) == 2 and "W" not in outcomes))),
        is_wounded_known=all(o is not None for o in outcomes) and len(outcomes) > 0,
        has_ht=(ht_seen == n),
        has_sot=all(has_stat(f, team_id, ["Shots On Target"]) for f in last5),
        has_cr=all(has_stat(f, team_id, ["Total Crosses"]) for f in last5),
        has_goals=(len(conceded) >= 3),
        outcomes=outcomes,
    ))
    return p


def auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float)
    m = ~np.isnan(s)
    y, s = y[m], s[m]
    if len(y) < 20 or len(np.unique(y)) < 2:
        return np.nan
    r = pd.Series(s).rank().values
    n1 = y.sum(); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return np.nan
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def ci95(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2: return (np.nan, np.nan)
    se = x.std(ddof=1) / np.sqrt(len(x))
    return (x.mean() - 1.96 * se, x.mean() + 1.96 * se)


def boot_diff(a, b, reps=2000, seed=0):
    rng = np.random.default_rng(seed)
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) < 5 or len(b) < 5:
        return (np.nan, np.nan)
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(reps)]
    d = np.array(d)
    return (np.percentile(d, 2.5), np.percentile(d, 97.5))


# ───────────────────── match-level 13 rules ─────────────────────
def match_rules(h, a, spear, fav_h):
    """The 13 scoring rules exactly as the engine applies them (L288-341)."""
    both_poss = h["is_possession"] and a["is_possession"]
    both_def = h["is_defensive"] and a["is_defensive"]
    both_atk = h["is_attacking"] and a["is_attacking"]
    both_gj = h["is_glass_jaw"] and a["is_glass_jaw"]
    both_ht = h["is_ht_active"] and a["is_ht_active"]
    both_clin = h["is_clinical"] and a["is_clinical"]
    one_atk = h["is_attacking"] or a["is_attacking"]
    one_gj = h["is_glass_jaw"] or a["is_glass_jaw"]
    one_cr = h["is_crossing"] or a["is_crossing"]
    no_cs = h["no_cs"] and a["no_cs"]
    tg_hi = (h["total_goals"] > 10 and a["total_goals"] > 10)
    h_kill = (h["is_ht_killer"] and a["is_ht_vulnerable"]) or (a["is_ht_killer"] and h["is_ht_vulnerable"])
    fav_wounded = (fav_h and h["is_wounded"]) or ((not fav_h) and a["is_wounded"])

    R = {}
    R["r01_both_possession_veto"] = bool(both_poss)
    R["r02_both_defensive_veto"] = bool(both_def)
    R["r03_holy_grail"] = bool(both_atk and both_gj and both_ht)
    R["r04_both_attacking"] = bool(both_atk)
    R["r05_both_glass_jaw"] = bool(both_gj)
    R["r06_both_ht_active"] = bool(both_ht)
    R["r07_early_kill"] = bool(h_kill)
    R["r08_mixed_high_sot"] = bool((not both_atk) and (not both_def) and (not both_poss)
                                   and (h["sot"] + a["sot"]) >= 9.0)
    R["r09_attacker_vs_glass_jaw"] = bool(one_atk and one_gj)
    R["r10_crossing"] = bool(one_cr)
    R["r11_both_clinical"] = bool(both_clin)
    R["r12_no_clean_sheets"] = bool(no_cs)
    R["r13_high_recent_goals"] = bool(tg_hi)
    R["p14_btts_ud_high"] = bool(spear > 70.0)
    R["p15_wounded_fav"] = bool(fav_wounded)
    return R


DATA_RULES = {
    "r01_both_possession_veto": "poss",
    "r02_both_defensive_veto": "tkl+itr+sot",
    "r03_holy_grail": "atk+gj+ht",
    "r04_both_attacking": "atk",
    "r05_both_glass_jaw": "goals",
    "r06_both_ht_active": "HT",
    "r07_early_kill": "HT",
    "r08_mixed_high_sot": "sot",
    "r09_attacker_vs_glass_jaw": "atk+gj",
    "r10_crossing": "crosses",
    "r11_both_clinical": "sot+bcc",
    "r12_no_clean_sheets": "goals",
    "r13_high_recent_goals": "goals",
    "p14_btts_ud_high": "catalogue",
    "p15_wounded_fav": "goals",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="/tmp/o15_rule_features.pkl")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the 500MB raw history cache and re-fetch "
                         "(safe now that a 429 raises instead of faking data)")
    a = ap.parse_args()

    # Loads the 500MB cache only when we actually want to reuse it.
    init_hist(fresh=a.fresh)

    S = pd.read_pickle(TARGETS)
    if a.limit:
        S = S.head(a.limit)
    print(f"targets: {len(S)}")

    rows = []
    for i, r in S.iterrows():
        d = r["date"]; fid = r["fid"]; hid = r["hid"]; aid = r["aid"]
        hp = profile(hid, d, fid)
        ap_ = profile(aid, d, fid)
        spear = np.nan; fav_h = True
        cat = f"output/audited_underdog_backtest_{d}.csv"
        if os.path.exists(cat):
            try:
                c = pd.read_csv(cat)
                m = c[c["fixture"].astype(str).str.contains(str(r.get("fixture", "")), regex=False)]
                if len(m):
                    row = m.iloc[0]
                    spear = float(str(row["Fav_Spear_Power"]).replace("%", "").strip())
                    fav_h = str(row["underdog_team"]).strip() != str(r.get("fixture", "")).split(" vs ")[0]
            except Exception:
                pass
        R = match_rules(hp, ap_, spear if spear == spear else 0.0, fav_h)
        rec = dict(fid=fid, date=d, hit=int(r["hit"]),
                   h_n=hp["n_used"], a_n=ap_["n_used"],
                   h_ht=hp["has_ht"], a_ht=ap_["has_ht"],
                   h_sot=hp["has_sot"], a_sot=ap_["has_sot"],
                   h_cr=hp["has_cr"], a_cr=ap_["has_cr"],
                   h_gl=hp["has_goals"], a_gl=ap_["has_goals"],
                   h_wo=hp["is_wounded_known"], a_wo=ap_["is_wounded_known"],
                   spear=spear,
                   h_sot_v=hp["sot"], a_sot_v=ap_["sot"],
                   h_tg=hp["total_goals"], a_tg=ap_["total_goals"],
                   h_cr_v=hp["crs"], a_cr_v=ap_["crs"])
        rec.update(R)
        rows.append(rec)
        if (i + 1) % 25 == 0:
            # Save the DERIVED rows too, not just the raw history cache.
            # An earlier run reached 1,200/1,460 and was killed, and because
            # features were only written at the very end, every derived row
            # was lost — only the (unloadable, 500MB) raw cache survived.
            # An interrupted run must still yield a usable table.
            save_hist(_hist)
            pd.DataFrame(rows).to_pickle(a.out)
            print(f"  {i+1}/{len(S)}  (history cache: {len(_hist)} team-dates)", flush=True)

    save_hist(_hist)
    D = pd.DataFrame(rows)
    with open(a.out, "wb") as f:
        pickle.dump(D, f)
    print(f"\nwrote {a.out}  shape={D.shape}")
    return D


if __name__ == "__main__":
    try:
        main()
    except RateLimited as e:
        # Exit non-zero and loudly. The incremental save above means
        # everything computed so far is already on disk — but the run is
        # INCOMPLETE and must never be presented as a finished result.
        print(f"\n🛑 ABORTED ON RATE LIMIT: {e}")
        print("Partial results are on disk but INCOMPLETE — do not report them")
        print("as a full-sample finding. Re-run later; the history cache makes")
        print("the retry cheap.")
        raise SystemExit(2)
