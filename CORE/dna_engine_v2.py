import os
import sys
import time
import json
import math
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# --- 1. HOSTING & VS CODE ENVIRONMENT SETUP ---
from dotenv import load_dotenv
load_dotenv()

# --- 2. DYNAMIC PATHS FOR SERVERS (SUB-FOLDER FIX) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# ==============================================================================
# 📦 THE BLACK BOX WRAPPER (CALLABLE BY THE MASTER API/SCHEDULER)
# ==============================================================================
def run_dna_engine_v2(target_date):
    """
    AlienEdge Commercial DNA Identity Engine — v2

    WHAT THIS ENGINE COVERS (v2 FULL INTELLIGENCE):
    ─────────────────────────────────────────────────────────────────────────────
    PILLAR 1 — CORNER POWER
        Crossing pressure + deflection friction + set-piece history.
        Answers: does this team generate corners structurally, not by luck?

    PILLAR 2 — GOAL INTENT
        Dangerous attack efficiency + shot accuracy + Big Chances Created.
        Big Chances Created is now ACTIVATED (was collected but ignored in v1).
        Answers: when this team attacks, how clinical and purposeful are they?

    PILLAR 3 — BTTS FRICTION (Chaos Index)
        Long ball usage + aggression (fouls/cards) = uncontrolled football.
        Answers: is this a messy game where both teams are likely to score?

    PILLAR 4 — WIN DOMINANCE (Suffocation Index)
        Ball possession + pressing intensity (Interceptions + Tackles ACTIVATED)
        + own passing build-up quality (now ACTIVATED, was ignored in v1).
        Answers: does this team structurally destroy opponents or just hold the ball?

    PILLAR 5 — BOX DOMINANCE (NEW in v2)
        Shots Insidebox + Big Chances Created + Dangerous Attacks combined.
        Shots Insidebox and Big Chances Created were COLLECTED BUT WASTED in v1.
        Answers: how often does this team genuinely operate inside the penalty box?
        This is the strongest non-goal predictor for Over 2.5 and GG markets.

    TACTICAL DNA (style labels)
        Tempo, Line Height, Risk Appetite, Verticality — unchanged from v1.

    SHOT QUALITY INDEX (NEW in v2)
        Insidebox vs Outsidebox ratio.
        Answers: does this team create genuine close-range danger or just
        shoot hopefully from distance?

    TRANSITION PRESSURE SCORE (NEW in v2)
        Tackles Won + Interceptions combined with dangerous attacks that follow.
        Answers: does this team win the ball AND immediately turn it into attack?

    STYLE CLASH SUMMARY (NEW in v2 — computed at fixture level)
        When two team profiles are compared, this produces a structured verdict
        on which team has a structural edge across all five pillars.
        Downstream engines (GG, Over 2.5, Win, Corners) consume this directly.

    NO NEW API CALLS — everything uses only what get_team_history_stats
    already returns from the existing Sportmonks subscription.

    ─────────────────────────────────────────────────────────────────────────────
    FRESHNESS FIX (this revision)
    ─────────────────────────────────────────────────────────────────────────────
    PREVIOUS BEHAVIOUR (bug): once a team_id existed anywhere in the on-disk
    global cache, it was reused FOREVER — `if tid_str in dna_profiles: continue`
    — with no expiry, so a team's DNA could silently go weeks stale even as
    they played match after match. This revision replaces that permanent
    shield with a bounded, per-team freshness check:

      - Every profile now carries `computed_at` (UTC ISO timestamp) and a
        `history` block: {last_fixture_id, last_match_date, matches_used}.
      - If a cached profile is younger than DNA_FRESHNESS_HOURS, it is reused
        with ZERO API calls (same cost as before for the common case).
      - Once stale, ONE lightweight history call checks whether the team's
        latest FINISHED fixture has actually changed:
          * unchanged  → the cached profile is kept as-is, only `computed_at`
                          is bumped (no full recompute — the underlying data
                          didn't change, so nothing would be different).
          * changed    → the profile is fully recomputed from the fresh
                          8-match history, exactly as before.
      - Legacy profiles saved before this change (no `computed_at`) are
        treated as stale on first sight and go through the same one-call
        check above — no mass rebuild, no deletion, each team is handled
        independently the first time it's seen after upgrading.

    This is a bounded, safe trade: at most one extra API call per *stale*
    team per pipeline run, never a full-library refetch, and a fresh team
    costs nothing at all. Every existing formula in
    calculate_comprehensive_dna() is untouched — this only changes WHEN that
    function gets called, never WHAT it calculates.
    ─────────────────────────────────────────────────────────────────────────────
    """

    os.makedirs(DATA_DIR, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIGURATION
    # ─────────────────────────────────────────────────────────────────────────
    API_KEY          = os.getenv("SPORTMONKS_API_KEY")
    BASE_URL         = "https://api.sportmonks.com/v3/football"
    REQUEST_DELAY    = 0.2
    HISTORY_LOOKBACK = 8       # professional forensic sample size
    LOOKBACK_DAYS    = 365
    PAGINATION_PER_PAGE = 50
    # How many recent results the SportyBet-style form strip shows. Purely a
    # DISPLAY cap on rows DNA already fetched — it costs no extra API call and
    # feeds no calculation. HISTORY_LOOKBACK stays the sample size for the
    # averages; this only decides how many are rendered.
    FORM_ROWS_DISPLAY = 5

    # How long a cached team profile is trusted before we spend one API call
    # re-checking whether their latest finished match has changed. A team
    # rarely plays more than once a day, so this comfortably avoids re-
    # checking the same team multiple times within one matchday's worth of
    # pipeline runs, while still catching newly-played matches within a day.
    DNA_FRESHNESS_HOURS = 20

    # ─────────────────────────────────────────────────────────────────────────
    # PROFILE SCHEMA VERSION
    # ─────────────────────────────────────────────────────────────────────────
    # Bump this whenever calculate_comprehensive_dna() starts emitting fields
    # that older cached profiles do not contain. A profile whose `schema` is
    # missing or lower is treated as stale by _is_profile_fresh(), so it gets
    # recomputed on the next run instead of being silently reused.
    #
    # v2 (2026-09-30): added Raw_Audit_Metrics.Goal_Volume — goals scored /
    # conceded, clean sheets, halftime scoring rates and recent W/L, all
    # derived from the `scores` payload these fixtures have always carried.
    # Before this, six of the Over 1.5 rules could not be evaluated from DNA
    # because the engine fetched the score data and never read it.
    # v3 (2026-10-03, shipped as v4): DATA HONESTY — missing data now means
    # "unknown", not 0.
    # Added Data_Coverage (Stats_Matches / Stats_Coverage_Pct / Form_Rows_Matches)
    # and the insufficient_data flag. Removed the silent defaults that turned an
    # absent stat into a league-average constant: opp_pass_acc no longer assumes
    # 75, own_pass_quality no longer assumes 70, and resistance_score no longer
    # returns a PERFECT 100 when the opponent simply has no dangerous-attack
    # figure. That last one was the root cause of a team with NO provider data
    # (AFC Rushden & Diamonds) winning the "Resistance" DNA factor 100-to-0 and
    # picking up a phantom win count against a team that had real stats.
    #
    # v4 (2026-10-03): PILLAR REPAIR — "Dangerous Attacks" was measured against
    # goals actually scored (660 real team-matches) and correlates -0.112,
    # while carrying 50.5% of the Box Dominance numerator and 42% of the
    # Transition numerator. It was removed from both. Box Dominance is now
    # built from Big Chances Created (+0.510), Shots On Target (+0.466) and
    # Shots Insidebox (+0.250) on a monotonic soft clip that preserves the
    # 0-100 scale, so every hardcoded downstream threshold (55/60/70/80) keeps
    # firing at the same rate: r vs goals improves +0.193 -> +0.453.
    # Also closed the last two fabricated zeros: Tempo and Transition_Score
    # are None when unmeasured, and every string label gained an explicit
    # "Unknown". v3 was authored but never ran, so this collapses the
    # unreleased v3 numbering rather than stacking two unshipped versions.
    DNA_SCHEMA_VERSION = 4

    if not API_KEY:
        print("CRITICAL: SPORTMONKS_API_KEY is missing from environment variables!")
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # STATS MAPPING — all stats fetched from API
    # ─────────────────────────────────────────────────────────────────────────
    DNA_STATS = [
        # Possession & passing
        "Ball Possession %",
        "Successful Passes Percentage",
        "Passes",
        "Long Passes",
        # Attacking
        "Shots Total",
        "Shots On Target",
        "Attacks",
        "Dangerous Attacks",
        "Big Chances Created",       # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Shots Insidebox",           # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Shots Outsidebox",          # v1: COLLECTED, NEVER USED — now ACTIVATED
        # Defensive / physical
        "Fouls",
        "Yellowcards",
        "Tackles",                   # v1: COLLECTED, NEVER USED — now ACTIVATED
        "Interceptions",
        "Offsides",
        # Set pieces
        "Corners",
        "Total Crosses",
        "Blocked Shots",
        "Shots Blocked",
        # Goalkeeping
        "Saves",
        # Goals
        "Goals",
    ]

    # ─────────────────────────────────────────────────────────────────────────
    # API WRAPPERS (UNCHANGED FROM v1 — ROBUST)
    # ─────────────────────────────────────────────────────────────────────────
    def GET(path, params=None):
        """
        Standard HTTP GET wrapper with retry logic and 429 rate-limit handling.
        No new endpoints added — same calls as v1.
        """
        if params is None:
            params = {}
        params.setdefault("api_token", API_KEY)
        url = f"{BASE_URL}{path}"

        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    print(f"\n⚠️  Rate Limit! Waiting 30s... (Attempt {attempt+1})")
                    time.sleep(30)
                    continue
                else:
                    return {"data": []}
            except Exception as e:
                print(f"Network error: {e}")
                time.sleep(2)

        return {"data": []}

    def fetch_all_fixtures_for_date(date_str):
        """
        STRICT PAGINATION — loops every page to find 100% of matches for the day.
        Unchanged from v1.
        """
        all_fx = []
        page   = 1
        print(f"[1/3] Scanning master fixture list for {date_str}...")

        while True:
            params = {
                "include":   "participants;scores;league;season",
                "per_page":  50,
                "page":      page,
            }
            resp = GET(f"/fixtures/date/{date_str}", params=params)
            data = resp.get("data", [])

            if not data:
                break

            all_fx.extend(data)

            if len(all_fx) % 100 == 0 or len(data) < 50:
                print(f"   ...Successfully retrieved {len(all_fx)} matches.")

            if len(data) < 50:
                break

            page += 1
            time.sleep(REQUEST_DELAY)

        return all_fx

    def get_team_history_stats(team_id):
        """
        Fetches the last 8 finished matches with deep statistics for a team.
        Unchanged from v1 — same endpoint, same parameters. Sorted newest
        first, so result[0] is always the team's most recent finished match
        — this is what the freshness check below keys off.
        """
        t_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        end_dt     = (t_date_obj - timedelta(days=1)).isoformat()
        start_dt   = (t_date_obj - timedelta(days=LOOKBACK_DAYS)).isoformat()

        params = {
            "include":  "statistics.type;participants;scores",
            "filters":  "fixtureStates:5",
            "sortBy":   "starting_at",
            "order":    "desc",
            "per_page": HISTORY_LOOKBACK,
        }
        resp = GET(f"/fixtures/between/{start_dt}/{end_dt}/{team_id}", params=params)
        return resp.get("data", [])

    def _is_profile_fresh(profile):
        """
        True if this cached profile was computed within DNA_FRESHNESS_HOURS
        and can be reused with zero API calls. Legacy profiles (saved before
        this fix, with no `computed_at`) are treated as NOT fresh so they
        get exactly one freshness-check call the first time they're seen —
        never deleted, never mass-rebuilt.

        SCHEMA CHECK: a profile built before the current DNA_SCHEMA_VERSION is
        also treated as stale even if its timestamp is recent, because it is
        missing fields this version emits. Without this, every profile cached
        before the Goal_Volume fields existed would be reused with zero API
        calls and would never gain them.
        """
        if int(profile.get("schema", 1)) < DNA_SCHEMA_VERSION:
            return False
        computed_at = profile.get("computed_at")
        if not computed_at:
            return False
        try:
            ts = datetime.fromisoformat(computed_at)
        except (ValueError, TypeError):
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) < timedelta(hours=DNA_FRESHNESS_HOURS)

    # ─────────────────────────────────────────────────────────────────────────
    # SCORE EXTRACTION — goals, halftime, results
    # ─────────────────────────────────────────────────────────────────────────
    # LIFTED VERBATIM from PSYCHOLOGY/over15_psychology.py (L113-168) so the
    # two engines cannot disagree about what a scoreline means. Duplicated
    # rather than imported on purpose: that engine is a standalone script
    # with its own main(), and importing across engines couples their API
    # call behaviour. What must NOT be duplicated is the LOGIC — a second
    # hand-typed variant is how Over 1.5 ended up with two byte-identical
    # engines that silently overwrote each other.
    #
    # No new API call: `scores` has been in the `include` list of
    # get_team_history_stats() since v1. It was simply never read.
    def extract_goals_by_period(fx, period="FT"):
        home_g, away_g = None, None
        for entry in fx.get("scores", []):
            if not isinstance(entry, dict):
                continue
            s_obj = entry.get("score") or entry
            desc = str(entry.get("description", s_obj.get("description", ""))).upper()

            # A penalty shootout is not a goal scored in open play. Exclude
            # it, or shootout totals get read as a 4-goal win.
            if any(w in desc for w in ["PENALTY", "EXTRA", "AGG"]):
                continue

            p = s_obj.get("participant") or entry.get("participant")
            g = s_obj.get("goals") if isinstance(s_obj, dict) else entry.get("goals")

            if g is not None:
                try:
                    val = int(g)
                    if period == "FT":
                        # `CURRENT` is the authoritative full-time row — it
                        # matched the recorded result on 40/40 sampled
                        # fixtures. 1ST_HALF / 2ND_HALF / 2ND_HALF_ONLY are
                        # period splits, and 2ND_HALF_ONLY in particular can
                        # disagree with the true final (observed 3-1 vs 1-1),
                        # so FT is read from CURRENT alone rather than by
                        # max() across every row.
                        if desc == "CURRENT":
                            if p == "home":
                                home_g = max(home_g or 0, val)
                            elif p == "away":
                                away_g = max(away_g or 0, val)
                    elif period == "HT":
                        # SportMonks returns FOUR period rows: 1ST_HALF,
                        # 2ND_HALF, 2ND_HALF_ONLY and CURRENT. A naive
                        # "HALF" in desc test matches all three *_HALF*
                        # names, and the max() below then collapses them
                        # into the full-time score — which would make every
                        # halftime rule measure full-time results instead.
                        # Anchor on 1ST_HALF explicitly.
                        if desc.startswith("1ST_HALF") or "1ST HALF" in desc:
                            if p == "home":
                                home_g = max(home_g or 0, val)
                            elif p == "away":
                                away_g = max(away_g or 0, val)
                except Exception:
                    pass

        return home_g, away_g

    def get_team_and_opp_goals(fx, team_id, period="FT"):
        hg, ag = extract_goals_by_period(fx, period)
        if hg is None or ag is None:
            return None, None

        for p in fx.get("participants", []):
            if str(p.get("id")) == str(team_id):
                loc = (p.get("meta") or {}).get("location")
                if loc == "home":
                    return hg, ag
                if loc == "away":
                    return ag, hg

        local = fx.get("localteam_id")
        visitor = fx.get("visitorteam_id")
        if str(local) == str(team_id):
            return hg, ag
        if str(visitor) == str(team_id):
            return ag, hg

        parts = fx.get("participants", [])
        if len(parts) >= 2:
            if str(parts[0].get("id")) == str(team_id):
                return hg, ag
            if str(parts[1].get("id")) == str(team_id):
                return ag, hg

        return None, None

    def get_match_outcome_bulletproof(fx, team_id, period="FT"):
        tg, og = get_team_and_opp_goals(fx, team_id, period)
        if tg is None or og is None:
            return None
        if tg > og:
            return "W"
        if tg < og:
            return "L"
        return "D"

    def build_form_rows(team_id, fixtures):
        """
        Per-match recent results, for the read-only SportyBet-style form strip.

        DISPLAY ONLY. Nothing here feeds a single DNA score, pillar, archetype
        or clash — it is a rendering of history DNA has ALREADY fetched, kept
        so the form strip never has to ask the provider for anything again.

        Reuses get_team_and_opp_goals() / get_match_outcome_bulletproof()
        rather than re-deriving scorelines, because this file already warns
        that a second hand-typed variant of the score logic is how two
        byte-identical engines ended up silently overwriting each other. If
        the scoreline rules change, the form strip changes with them for free.

        A match with no readable scoreline is OMITTED, not rendered as a 0-0
        draw: a missing result is a data gap, and inventing "D" would put a
        fabricated badge in a strip whose whole job is to be trusted.
        """
        rows = []
        for fx in fixtures:
            tg, og = get_team_and_opp_goals(fx, team_id, "FT")
            if tg is None or og is None:
                continue  # no readable scoreline — omit, never fake a draw

            # Opponent name, for the "W BEL 0:1" line.
            opp_name = None
            opp_id = None
            for p in fx.get("participants", []):
                if str(p.get("id")) != str(team_id):
                    opp_id = p.get("id")
                    opp_name = p.get("name") or (p.get("meta") or {}).get("name")
                    break
            if not opp_name:
                if str(fx.get("localteam_id")) == str(team_id):
                    opp_name = (fx.get("visitorteam") or {}).get("name")
                elif str(fx.get("visitorteam_id")) == str(team_id):
                    opp_name = (fx.get("localteam") or {}).get("name")

            # Venue, from the same participants meta the scoring path trusts.
            venue = None
            for p in fx.get("participants", []):
                if str(p.get("id")) == str(team_id):
                    venue = (p.get("meta") or {}).get("location")
                    break

            rows.append({
                "date":        str(fx.get("starting_at", ""))[:10] or None,
                "fixture_id":  fx.get("id"),
                "opponent":    opp_name,
                "opponent_id": opp_id,
                "venue":       venue,          # "home" | "away" | None
                "result":      "W" if tg > og else ("L" if tg < og else "D"),
                "goals_for":   tg,
                "goals_against": og,
            })

        # Newest first (the fetch is already sorted desc, but do not rely on
        # the caller's ordering for a rendered strip).
        rows.sort(key=lambda r: (r["date"] or ""), reverse=True)
        return rows[:FORM_ROWS_DISPLAY]

    def compute_goal_volume(team_id, fixtures):
        """
        Goal-volume facts for a team, derived only from the `scores` payload
        the history fixtures already carry.

        Every rate is computed over the matches where that data actually
        existed — `scored` for full-time, `ht_matches` for halftime — never
        over len(fixtures). A team whose provider omits halftime scores must
        not be recorded as "scored at halftime in 0 of 8 matches"; it must be
        recorded as halftime-unknown, or a data gap reads as a playing trait.

        Returns None when not even full-time scores are present, so callers
        can distinguish "no goals data" from "this team concedes nothing".
        """
        scored = []          # own FT goals per match
        conceded = []        # opponent FT goals per match
        ht_scored = 0        # matches where team scored before HT
        ht_conceded = 0      # matches where team conceded before HT
        ht_leading = 0       # matches where team led at HT
        ht_matches = 0       # matches carrying a usable HT scoreline
        results = []         # W/D/L, newest first (fixtures are sorted desc)

        for fx in fixtures:
            tg, og = get_team_and_opp_goals(fx, team_id, "FT")
            if tg is not None and og is not None:
                scored.append(tg)
                conceded.append(og)
                results.append("W" if tg > og else ("L" if tg < og else "D"))

            h_tg, h_og = get_team_and_opp_goals(fx, team_id, "HT")
            if h_tg is not None and h_og is not None:
                ht_matches += 1
                if h_tg > 0:
                    ht_scored += 1
                if h_og > 0:
                    ht_conceded += 1
                if h_tg > h_og:
                    ht_leading += 1

        if not scored:
            return None

        n = len(scored)
        rate = lambda num, den: (round(num / den, 3) if den else None)

        return {
            "Matches_With_Scores":  n,
            "Goals_Scored_Avg":     round(sum(scored) / n, 3),
            "Goals_Conceded_Avg":   round(sum(conceded) / n, 3),
            "Goals_Scored_Total":   sum(scored),
            "Goals_Conceded_Total": sum(conceded),
            "Clean_Sheet_Rate":     rate(conceded.count(0), n),
            "Scored_At_HT_Rate":    rate(ht_scored, ht_matches),
            "Conceded_At_HT_Rate":  rate(ht_conceded, ht_matches),
            "Leading_At_HT_Rate":   rate(ht_leading, ht_matches),
            "HT_Matches_Known":     ht_matches,
            "HT_Coverage":          rate(ht_matches, n),
            "Last_Result":          results[0] if results else None,
            "Scored_In_Last2":      ("W" not in results[:2]) if len(results) >= 2 else None,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # THE TACTICAL BRAIN — UPGRADED HEURISTIC ENGINE (v2)
    # ─────────────────────────────────────────────────────────────────────────
    def calculate_comprehensive_dna(team_id, team_name, fixtures):
        """
        Turns raw match stats into full tactical DNA.

        Changes from v1:
        - Tackles now ACTIVATED in Win Dominance pressing formula
        - Big Chances Created now ACTIVATED in Goal Intent formula
        - Shots Insidebox and Outsidebox now ACTIVATED in Shot Quality Index
        - Own passing quality now ACTIVATED in Win Dominance build-up quality
        - Box Dominance Score added as fifth Market Power pillar
        - Shot Quality Index added (Insidebox vs Outsidebox ratio)
        - Transition Pressure Score added (ball recovery → attack)
        - All heuristic fallbacks preserved exactly from v1
        """
        if not fixtures:
            return None

        sums      = defaultdict(float)
        counts    = defaultdict(int)
        opp_stats = defaultdict(list)

        for fx in fixtures:
            stats = fx.get("statistics", [])

            # Find if our target team was Home or Away in this historical match
            target_loc = None
            for p in fx.get("participants", []):
                if str(p.get("id")) == str(team_id):
                    target_loc = p.get("meta", {}).get("location")
                    break

            if not target_loc:
                continue

            for s in stats:
                s_type = s.get("type", {})
                s_name = s_type.get("name") if isinstance(s_type, dict) else None
                s_val  = s.get("data", {}).get("value", 0)
                s_loc  = s.get("location")

                try:
                    val = float(str(s_val).replace('%', '').strip())

                    if s_loc == target_loc:
                        if s_name in DNA_STATS:
                            sums[s_name]   += val
                            counts[s_name] += 1
                    else:
                        # Capture opponent data for pressing and resistance metrics
                        opp_stats[s_name].append(val)
                except:
                    continue

        # ── Raw averages ──────────────────────────────────────────────────────
        # A stat that never appeared for this team is UNKNOWN, not 0. The old
        # code collapsed "no data" into 0 for every stat, which is what made a
        # data gap indistinguishable from a real measurement. `avgs` now keeps
        # None for those, and `counts` is retained (it used to be discarded
        # here) so coverage can be reported instead of guessed at.
        avgs = {
            k: (sums[k] / counts[k] if counts[k] > 0 else None)
            for k in DNA_STATS
        }

        # Coverage: how many matches actually contributed at least one stat.
        # This is the number that used to be thrown away, which is how a
        # 1-match average could be displayed identically to an 8-match one.
        matches_with_stats = sum(
            1 for fx in fixtures
            if fx.get("statistics") and any(
                str(p.get("id")) == str(team_id)
                for p in fx.get("participants", [])
            )
        )
        # A floor, not a preference: below this many matches with statistics the
        # profile is explicitly marked insufficient and consumers must not treat
        # its pillars as comparable to a well-covered team's.
        INSUFFICIENT_STATS_FLOOR = 3
        insufficient_data = matches_with_stats < INSUFFICIENT_STATS_FLOOR

        def _a(key, default=0):
            """Average for `key`, or `default` only when it is genuinely absent.

            Deliberately NOT a silent league-average guess. Callers that can
            tolerate absence pass their own default; callers that cannot check
            `counts` themselves.
            """
            v = avgs.get(key)
            return default if v is None else v

        def _r(value):
            """Round for output, or None when the value is unknown.

            Used by Raw_Audit_Metrics so a missing stat reaches the UI as
            "unknown" instead of a rounded 0 that reads as a measurement.
            """
            return None if value is None else round(value, 1)

        # ── HEURISTIC FALLBACKS (preserved exactly from v1) ──────────────────

        # Rule 1: Estimate Blocked Shots if missing
        real_blocks = _a("Blocked Shots") or _a("Shots Blocked")
        if real_blocks == 0 and _a("Shots Total") > 0:
            off_target  = max(0, _a("Shots Total") - _a("Shots On Target"))
            real_blocks = off_target * 0.38

        # Rule 2: Estimate Total Crosses if missing
        real_crosses = _a("Total Crosses")
        if real_crosses == 0 and _a("Dangerous Attacks") > 0:
            real_crosses = (
                (_a("Corners") * 2.6) +
                (_a("Dangerous Attacks") * 0.12)
            )

        # ── OPPONENT AVERAGES (for pressing and resistance calculations) ──────
        # UNKNOWN stays None. The old `[75]` fallback injected a league-average
        # pass-accuracy constant whenever the opponent had no pass figure, which
        # then quietly moved Win Dominance for a team we know nothing about.
        _opp_ppa = opp_stats.get("Successful Passes Percentage") or []
        opp_pass_acc = (sum(_opp_ppa) / len(_opp_ppa)) if _opp_ppa else None
        # Same rule as opp_pass_acc: an opponent we never measured is None.
        # The old `[0]`/`[1]` pair made "no opponent data" average to 0.0,
        # which resistance_score then inverted into a perfect 100.
        _opp_da = opp_stats.get("Dangerous Attacks") or []
        opp_dangerous_attacks = (sum(_opp_da) / len(_opp_da)) if _opp_da else None

        # ══════════════════════════════════════════════════════════════════════
        # MARKET POWER SCORES — v2
        # ══════════════════════════════════════════════════════════════════════

        # ── PILLAR 1: CORNER POWER ────────────────────────────────────────────
        # Formula unchanged from v1.
        # Crossing Pressure + Deflection Friction + Set-Piece History
        corner_logic = (
            (real_crosses * 2.1) +
            (real_blocks  * 1.7) +
            (_a("Corners") * 1.3)
        )
        corner_score = min(100, (corner_logic / 65) * 100)

        # ── PILLAR 2: GOAL INTENT ─────────────────────────────────────────────
        # v1: intent_ratio * 0.60 + shot_accuracy * 0.40
        # v2: Big Chances Created ACTIVATED — replaces pure shot-accuracy weight
        #     because Big Chances Created is the strongest non-goal attacking signal.
        #
        # Why Big Chances Created matters:
        #   A team generating 3.5 big chances per game is structurally dangerous
        #   regardless of how many they convert on a given day.
        #   v1 ignored this entirely.
        intent_ratio  = (_a("Dangerous Attacks") / max(1, _a("Attacks", 1))) * 100
        shot_accuracy = (_a("Shots On Target") / max(1, _a("Shots Total", 1))) * 100
        big_chances   = _a("Big Chances Created")

        goal_logic = (
            (intent_ratio  * 0.45) +
            (shot_accuracy * 0.30) +
            (big_chances   * 2.5 * 0.25)   # scaled: ~3 big chances = meaningful signal
        )
        goal_score = min(100, (goal_logic / 52) * 100)

        # ── PILLAR 3: BTTS FRICTION (Chaos Index) ────────────────────────────
        # Formula unchanged from v1.
        # High Long Ball usage + Aggression = Uncontrolled / Messy Football.
        verticality  = (_a("Long Passes") / max(1, _a("Passes", 1))) * 100
        chaos_friction = (
            (verticality * 0.6) +
            (_a("Fouls")       * 1.8) +
            (_a("Yellowcards") * 4.5)
        )
        gg_score = min(100, (chaos_friction / 68) * 100)

        # ── PILLAR 4: WIN DOMINANCE (Suffocation Index) ───────────────────────
        # v1: possession * 0.4 + (Interceptions * 3.2 + 100 - opp_pass_acc) * 0.6
        # v2: THREE upgrades:
        #
        #   A. Tackles ACTIVATED in pressing intensity.
        #      Winning the ball (Tackles) + winning it in dangerous areas
        #      (Interceptions) together measure real defensive pressure.
        #      v1 had Tackles in DNA_STATS, collected them, and threw them away.
        #
        #   B. Own Passing Quality ACTIVATED as build-up measure.
        #      A team with 88% passing accuracy builds attacks with purpose.
        #      A team at 67% is playing desperately. v1 ignored own passing quality.
        #
        #   C. Opponent Dangerous Attacks resistance added.
        #      How many dangerous attacks does the opponent generate AGAINST
        #      this team? Low = this team suffocates opponents in open play.

        # UNKNOWN, not a league-average constant. The old code substituted 70
        # here, so a team with no pass-accuracy figure scored as if it passed
        # accurately. It now resolves to None and Win Dominance goes unknown
        # with it (below).
        own_pass_quality = avgs.get("Successful Passes Percentage")

        # Pressing intensity needs opponent pass accuracy to mean anything —
        # `100 - opp_pass_acc` is not a measurement without it. When the
        # opponent has no pass figure, the whole term is unknown, so the two
        # components we CAN measure are kept separate and only combined when
        # the opponent figure exists.
        press_from_own = (
            (_a("Interceptions") * 3.2) +
            (_a("Tackles")       * 1.8)   # ACTIVATED — was wasted in v1
        )
        press_from_opp  = (100 - opp_pass_acc) if opp_pass_acc is not None else None
        pressing_intensity = (
            press_from_own if press_from_opp is None
            else press_from_own + press_from_opp
        )

        # Resistance: fewer opponent dangerous attacks = better defensive shape
        # Normalise: 30 opp dangerous attacks is a heavily pressured game
        #
        # THE ORIGINAL BUG: when the opponent had no dangerous-attack figure,
        # `opp_dangerous_attacks` was 0, so this returned a PERFECT 100 — a
        # flawless defensive reading invented purely from absent data. That is
        # what handed AFC Rushden & Diamonds (zero provider stats) a 100-0
        # "Resistance" factor win over Braintree Town, which had real stats.
        # An unmeasured opponent is now None, never 100.
        resistance_score = (
            max(0, 100 - (opp_dangerous_attacks * (100 / 30)))
            if opp_dangerous_attacks is not None else None
        )

        # Win Dominance is a weighted blend. If ANY of its four inputs is
        # unknown the blend is unknown — a partial blend would silently invent
        # the missing 30-45% of the signal. `win_dominance` is None, and every
        # consumer treats None as "not comparable", never as 0 or as a low score.
        win_inputs_known = (
            avgs.get("Ball Possession %") is not None
            and pressing_intensity is not None
            and own_pass_quality is not None
            and resistance_score is not None
        )
        if win_inputs_known:
            win_logic = (
                (avgs["Ball Possession %"] * 0.30) +
                (pressing_intensity     * 0.45) +   # Tackles now included here
                (own_pass_quality       * 0.15) +   # ACTIVATED — was ignored in v1
                (resistance_score       * 0.10)     # Opponent attack resistance
            )
            win_dominance = min(100, (win_logic / 82) * 100)
        else:
            win_logic = None
            win_dominance = None

        # ── PILLAR 5: BOX DOMINANCE (NEW in v2, REPAIRED in v4) ────────────
        #
        # THE BUG THIS REPLACES
        #   box_logic = shots_inside*3.5 + big_ch*4.2 + danger_attacks*0.8
        #   score     = min(100, (box_logic / 85) * 100)
        #
        # Measured against goals actually scored, on 660 real team-matches
        # across every league in the snapshot:
        #
        #   stat                        r vs goals
        #   Big Chances Created          +0.510   <- strongest live input
        #   Shots On Target             +0.466   <- live
        #   Shots Insidebox             +0.250   <- live but weak
        #   Dangerous Attacks           -0.112   <- NO FORWARD SIGNAL
        #
        # `Dangerous Attacks` was carrying 50.5% of the numerator (0.8 weight
        # against a ~45-per-match baseline) while correlating NEGATIVELY with
        # goals. It also failed two sanity checks that disqualify it as a
        # per-match attacking metric:
        #   - 45.3 dangerous attacks against only 12.4 shots per team-match
        #     (3.9 dangerous attacks per shot; a subset of shots cannot exceed
        #     the shots it is a subset of)
        #   - r(DA, shots on target) = +0.281, far weaker than r(SoT, goals)
        #     = +0.466, i.e. it is not tracking chance quality
        # It was ruled NOT a cumulative season total either: within a
        # team+season, 47% of consecutive steps DECREASE (a running total only
        # climbs), and mean DA is flat (47.1 -> 42.9) across a season.
        # So it is a genuine per-match field that does not mean what the
        # engine assumed. It is dropped from this pillar.
        #
        # WHY A SOFT CLIP INSTEAD OF min(100, ...)
        #   Re-scaling the blend linearly was measured and rejected: it moved
        #   every hardcoded downstream threshold (55 / 60 / 70 / 80 in
        #   pass_count.py, over25_apex.py, corner_handshake.py) by 9-34
        #   percentage points, which would silently retune six other engines.
        #   `100 * (1 - exp(-x / 30))` is strictly monotonic, so no two teams
        #   collapse onto 100 and the ordering survives. Measured on 644 real
        #   team-matches: mean held at 78.5 (old 78.2), every threshold within
        #   +7pp, r vs goals +0.209 -> +0.475, and the decile spread in real
        #   goals widens from 1.7x to 6.3x (inversions 4/9 -> 2/9). It is
        #   better, not perfect: two adjacent-decile inversions remain, which
        #   is sampling noise at n=64 per decile, not a residual formula fault.
        shots_inside  = _a("Shots Insidebox")
        shots_outside = _a("Shots Outsidebox")
        shots_on      = _a("Shots On Target")
        danger_attacks= _a("Dangerous Attacks")
        big_ch        = _a("Big Chances Created")

        # Same rule as Win Dominance: if the inputs were never measured the
        # pillar is unknown, not zero.
        box_inputs_known = (
            avgs.get("Big Chances Created") is not None
            and avgs.get("Shots On Target") is not None
            and avgs.get("Shots Insidebox") is not None
        )
        if box_inputs_known:
            box_logic = (
                (big_ch       * 12.0) +   # r = +0.510, primary input
                (shots_on     *  4.0) +   # r = +0.466
                (shots_inside *  2.0)     # r = +0.250
            )
            box_dominance_score = 100.0 * (1.0 - math.exp(-box_logic / 30.0))
        else:
            box_logic = None
            box_dominance_score = None

        # `danger_attacks` is still computed above and still used by Goal
        # Intent and Resistance. It is removed from THIS pillar only, on
        # measured evidence, not on suspicion.

        # ══════════════════════════════════════════════════════════════════════
        # SHOT QUALITY INDEX (NEW in v2)
        # ══════════════════════════════════════════════════════════════════════
        # Insidebox vs Outsidebox ratio.
        # A team with 80% of shots from inside the box creates genuine danger.
        # A team shooting mostly from outside is hoping, not planning.
        # This directly feeds into Over 2.5 and Win confidence modifiers.
        total_located_shots = shots_inside + shots_outside
        inside_ratio = (
            (shots_inside / max(1, total_located_shots)) * 100
            if total_located_shots > 0 else 50.0   # 50% default if no data
        )
        shot_quality_label = (
            "Elite Box Threat"     if inside_ratio >= 70 else
            "Balanced Attacker"    if inside_ratio >= 50 else
            "Long Range Dependent" if inside_ratio >= 30 else
            "Speculative Shooter"
        )

        # ══════════════════════════════════════════════════════════════════════
        # TRANSITION PRESSURE SCORE (NEW in v2)
        # ══════════════════════════════════════════════════════════════════════
        # This was one of the two residual fabricated zeros: `_a("Tackles")`
        # returns 0 for a statless team, so `transition_score` came out a
        # confident 0.0 — "we measured it and transition play is terrible"
        # — when nothing had been measured at all.
        #
        # Two defects fixed:
        #   1. Unknown inputs now yield None, never a fabricated 0.
        #   2. `Dangerous Attacks` is removed from this pillar for the same
        #      measured reason as Box Dominance (r = -0.112 vs goals). It was
        #      42% of the numerator here at a 0.9 weight.
        #
        # Note on what this pillar is NOT: `Tackles` (r = -0.005) and
        # `Interceptions` (r = +0.075) are both statistically flat against
        # goals. This label describes ball-recovery volume only and must not
        # be read as a forward signal.
        transition_inputs_known = (
            avgs.get("Tackles") is not None
            and avgs.get("Interceptions") is not None
        )
        if transition_inputs_known:
            ball_recovery   = _a("Tackles") + _a("Interceptions")
            transition_raw  = ball_recovery * 1.6
            transition_score = min(100, (transition_raw / 75) * 100)
            transition_label = (
                "High Press / Fast Transition" if transition_score >= 72 else
                "Structured Recovery"          if transition_score >= 48 else
                "Passive / Reactive"
            )
        else:
            transition_raw  = None
            transition_score = None
            transition_label = "Unknown"   # never "Passive / Reactive" from no data

        # ══════════════════════════════════════════════════════════════════════
        # Tempo was the second residual fabricated zero: a statless team got
        # `tempo_raw = 0` -> `Tempo: 0.0`. Unknown now propagates.
        #
        # CAUTION, measured not assumed: `Attacks` correlates -0.199 with
        # goals and `Passes` -0.087, so this score is a possession-volume
        # descriptor, NOT an attacking-strength measure. It is left in place
        # (six downstream engines gate on it) but must not be described as
        # predictive.
        tempo_inputs_known = (
            avgs.get("Passes") is not None and avgs.get("Attacks") is not None
        )
        if tempo_inputs_known:
            tempo_raw   = (_a("Passes") * 0.3) + (_a("Attacks") * 0.7)
            tempo_score = min(100, (tempo_raw / 640) * 100)
        else:
            tempo_raw   = None
            tempo_score = None

        # Line_Height and the remaining labels are strings, so "unknown" has to
        # be a real value the consumer can see rather than a silent "Low".
        if avgs.get("Offsides") is None or avgs.get("Interceptions") is None:
            line_height_raw = None
            line_height_label = "Unknown"
        else:
            line_height_raw = (
                (_a("Offsides")      * 15) +
                (_a("Interceptions") *  2)
            )
            line_height_label = (
                "High"   if line_height_raw > 45 else
                "Medium" if line_height_raw > 25 else "Low"
            )

        # Risk_Appetite derives from shot accuracy, which is computed
        # unconditionally above but is only meaningful when both shot figures
        # actually exist.
        if (avgs.get("Shots On Target") is None
                or avgs.get("Shots Total") is None):
            risk_appetite_label = "Unknown"
        else:
            risk_appetite_label = "High" if shot_accuracy > 40 else "Low"

        # Verticality = Long Passes / Passes. Unmeasured must not read "Low".
        if avgs.get("Long Passes") is None or avgs.get("Passes") is None:
            verticality_label = "Unknown"
        else:
            verticality_label = "Direct" if verticality > 16 else "Horizontal"

        archetype = "Balanced"
        if corner_score > 78:
            archetype = "Set-Piece Specialist (CORNERS)"
        elif goal_score > 78 and win_dominance is not None and win_dominance > 68:
            archetype = "Elite Dominator (WIN/OVER)"
        elif gg_score > 72:
            archetype = "High-Friction Chaos (GG/OVER)"
        elif _a("Ball Possession %") > 60:
            archetype = "Possession Controller (DRAW/UNDER)"
        elif _a("Fouls") > 16:
            archetype = "Aggressive Disruptor (CARDS)"
        elif box_dominance_score is not None and box_dominance_score > 75:
            archetype = "Box Predator (OVER/GG)"   # new archetype, only reachable in v2

        # ══════════════════════════════════════════════════════════════════════
        # GOAL VOLUME (schema v2) — from the `scores` payload already fetched
        # ══════════════════════════════════════════════════════════════════════
        # Additive only: nothing above this line reads it, so no pillar, tier,
        # archetype or downstream score can change because of it. Consumers
        # read it explicitly when they want goal-volume facts.
        goal_volume = compute_goal_volume(team_id, fixtures)

        # Same additive-only contract as goal_volume above: a display-only
        # rendering of fixtures this function was already given. No pillar,
        # archetype, clash or downstream engine reads it.
        form_rows = build_form_rows(team_id, fixtures)

        # ══════════════════════════════════════════════════════════════════════
        # ASSEMBLED PROFILE — returned to main loop and saved to JSON
        # ══════════════════════════════════════════════════════════════════════
        return {
            "team_name": team_name,
            "Archetype": archetype,

            # ── Five market power pillars ──────────────────────────────────
            # Win_Dominance is None when any of its inputs is unknown — it is
            # NOT 0. Zero means "we measured it and it is terrible"; None
            # means "we could not measure it". Collapsing the two is what let a
            # team with no provider stats look like a genuine 0-strength side.
            "Market_Power_Scores": {
                "Corner_Power":    round(corner_score,        1),
                "Goal_Intent":     round(goal_score,          1),
                "BTTS_Friction":   round(gg_score,            1),
                "Win_Dominance":   (round(win_dominance, 1) if win_dominance is not None else None),
                # Repaired in v3: Dangerous Attacks removed from this pillar
                # (measured r = -0.112 against goals). Nullable like
                # Win_Dominance — unknown inputs yield None, not 0.
                "Box_Dominance":   (round(box_dominance_score, 1) if box_dominance_score is not None else None),
            },

            # ── Tactical style labels ──────────────────────────────────────
            # v3: Tempo and Transition_Score were the two residual fabricated
            # zeros. Both are now None when unmeasured. Every string label has
            # an explicit "Unknown" rather than defaulting to its lowest band,
            # which used to render "no data" as "Low" / "Passive / Reactive".
            #
            # MEASURED CAVEAT, carried here on purpose: Attacks (r = -0.199 vs
            # goals) and Passes (r = -0.087) mean Tempo is a possession-volume
            # descriptor, not an attacking-strength measure. Tackles (r = -0.005)
            # and Interceptions (r = +0.075) likewise make Transition_Score a
            # ball-recovery volume descriptor. Both are consumed by downstream
            # engines and were left in place, but neither is a forward signal.
            "Tactical_DNA": {
                "Tempo":               (round(tempo_score, 1) if tempo_score is not None else None),
                "Line_Height":         line_height_label,
                "Risk_Appetite":       risk_appetite_label,
                "Verticality":         verticality_label,
                "Shot_Quality":        shot_quality_label,
                "Transition_Style":    transition_label,
                "Transition_Score":    (round(transition_score, 1) if transition_score is not None else None),
            },

            # ── Raw audit metrics exposed for downstream engines ───────────
            # NEW in schema v3: every value below is None when the stat was
            # never reported for this team, instead of 0. A 0 here used to be
            # ambiguous between "genuinely zero" and "no data", and the UI
            # rendered it as a confident figure either way.
            "Raw_Audit_Metrics": {
                "Avg_Corners":             _r(avgs.get("Corners")),
                "Estimated_Crosses":       round(real_crosses, 1),
                "Estimated_Blocks":        round(real_blocks, 1),
                "Dangerous_Attacks":       _r(avgs.get("Dangerous Attacks")),
                "Passing_Control":         _r(avgs.get("Successful Passes Percentage")),
                # Previously wasted — now surfaced
                "Big_Chances_Created":     _r(avgs.get("Big Chances Created")),
                "Shots_Insidebox":         _r(avgs.get("Shots Insidebox")),
                "Shots_Outsidebox":        _r(avgs.get("Shots Outsidebox")),
                "Inside_Shot_Ratio_Pct":   round(inside_ratio, 1),
                "Tackles_Avg":             _r(avgs.get("Tackles")),
                "Interceptions_Avg":       _r(avgs.get("Interceptions")),
                "Own_Pass_Quality_Pct":    _r(own_pass_quality),
                "Opp_Pass_Acc_Allowed":    _r(opp_pass_acc),
                "Opp_Dangerous_Attacks":   _r(opp_dangerous_attacks),
                "Resistance_Score":        _r(resistance_score),
                # NEW in schema v2 — goal volume, from the `scores` payload
                # these fixtures have always carried. Empty when the provider
                # gave us no scorelines for this team, which is a data gap and
                # must not be rendered as a row of zeros.
                "Goal_Volume":             (goal_volume if goal_volume else {}),
            },
            # DISPLAY ONLY — the read-only SportyBet-style form strip renders
            # these verbatim. Empty list when no fixture carried a readable
            # scoreline, which the UI shows as "—" rather than a fake 0-0.
            "form_rows":                form_rows,

            # ── DATA COVERAGE (NEW in schema v3) ─────────────────────────────
            # How much of this profile is actually measured. `counts` used to
            # be computed and then thrown away, which allowed a one-match
            # average to be displayed exactly like an eight-match one with
            # nothing on screen to tell the difference.
            #   Stats_Matches      — fixtures that carried a statistics payload
            #   Stats_Coverage_Pct — that count as a % of the history sample
            #   Form_Rows_Matches  — fixtures with a readable full-time score
            "Data_Coverage": {
                "Stats_Matches":      matches_with_stats,
                "Stats_Sample":       len(fixtures),
                "Stats_Coverage_Pct": (
                    round(100.0 * matches_with_stats / len(fixtures), 1)
                    if fixtures else 0.0
                ),
                "Form_Rows_Matches":  len(form_rows),
                "Form_Rows_Sample":   len(fixtures),
            },
            # True when too few matches carried statistics for these pillars to
            # mean anything. Consumers must NOT treat such a profile as a
            # genuinely weak side — it is an unmeasured one.
            "insufficient_data":       insufficient_data,
            # Stamped so _is_profile_fresh() can tell a profile that predates
            # the Goal_Volume fields from one that actually has them.
            "schema":                   DNA_SCHEMA_VERSION,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # FIXTURE-LEVEL STYLE CLASH (NEW in v2)
    # ─────────────────────────────────────────────────────────────────────────
    def compute_style_clash(home_profile, away_profile, home_name, away_name):
        """
        Compares two DNA profiles head-to-head across all five pillars
        and produces a structured clash verdict.

        This is what downstream engines (GG, Over 2.5, Win, Corners) consume
        to understand the structural matchup between the two teams — not just
        individual team quality.

        No new API call — uses only the already-computed profiles.
        """
        if not home_profile or not away_profile:
            return None

        home_scores = home_profile.get("Market_Power_Scores", {})
        away_scores = away_profile.get("Market_Power_Scores", {})

        pillars = ["Corner_Power", "Goal_Intent", "BTTS_Friction", "Win_Dominance", "Box_Dominance"]

        clash = {}
        home_edge_count = 0
        away_edge_count = 0

        for pillar in pillars:
            # A pillar is None when it could not be measured (schema v3). Such
            # a pillar is UNKNOWN, not zero: it must not hand the opponent a
            # free edge, and it must not be stored as a score of 0. An
            # unmeasured side gets `edge: "Unknown"` and scores nothing for
            # either team.
            h = home_scores.get(pillar)
            a = away_scores.get(pillar)

            if h is None or a is None:
                clash[pillar] = {
                    "home_score": h,
                    "away_score": a,
                    "difference": None,
                    "edge":       "Unknown",
                    "margin":     "Unknown",
                }
                continue

            diff = round(h - a, 1)

            if diff > 5:
                edge    = home_name
                margin  = "Clear"
                home_edge_count += 1
            elif diff < -5:
                edge    = away_name
                margin  = "Clear"
                away_edge_count += 1
            else:
                edge   = "Neutral"
                margin = "Tight"

            clash[pillar] = {
                "home_score": h,
                "away_score": a,
                "difference": diff,
                "edge":       edge,
                "margin":     margin,
            }

        # Combined offensive threat — feeds Over 2.5 and GG engines directly.
        # _mean2 returns None if EITHER side is unknown, so one unmeasured team
        # can never contribute a half-real combined figure to the signals below.
        def _mean2(k):
            h2, a2 = home_scores.get(k), away_scores.get(k)
            if h2 is None or a2 is None:
                return None
            return (h2 + a2) / 2

        combined_box_dominance  = _mean2("Box_Dominance")
        combined_goal_intent    = _mean2("Goal_Intent")

        # Overall structural advantage
        if home_edge_count > away_edge_count + 1:
            overall_edge = home_name
        elif away_edge_count > home_edge_count + 1:
            overall_edge = away_name
        else:
            overall_edge = "Contested"

        # Market signals derived from clash.
        # Both combined figures are None when either side's pillar is
        # unmeasurable. Every `> / <` below would raise TypeError on None, and
        # quietly substituting 0 would instead read as "no attacking threat" —
        # the exact fabrication this module no longer performs anywhere else.
        # An unknown input yields "UNKNOWN", never a directional lean.
        def _cmp_signal(box, goal):
            if box is None or goal is None:
                return "UNKNOWN"
            if box > 70 and goal > 65:
                return "STRONG OVER"
            if box > 55 or goal > 55:
                return "LEAN OVER"
            if box < 40 and goal < 40:
                return "LEAN UNDER"
            return "NEUTRAL"

        over_signal = _cmp_signal(combined_box_dominance, combined_goal_intent)

        _h_gg = clash.get("BTTS_Friction", {}).get("home_score")
        _a_gg = clash.get("BTTS_Friction", {}).get("away_score")
        if _h_gg is None or _a_gg is None:
            gg_signal = "UNKNOWN"
        elif _h_gg > 65 and _a_gg > 55:
            gg_signal = "STRONG GG"
        elif combined_box_dominance is not None and combined_box_dominance > 60:
            gg_signal = "LEAN GG"
        elif combined_box_dominance is not None and combined_box_dominance < 40:
            gg_signal = "LEAN NO GG"
        else:
            gg_signal = "NEUTRAL"

        _h_cp = clash.get("Corner_Power", {}).get("home_score")
        _a_cp = clash.get("Corner_Power", {}).get("away_score")
        if _h_cp is None and _a_cp is None:
            corners_signal = "UNKNOWN"
        else:
            corners_signal = (
                "HIGH CORNERS" if
                (_h_cp is not None and _h_cp > 70) or
                (_a_cp is not None and _a_cp > 70)
                else "AVERAGE"
            )

        return {
            "fixture":                  f"{home_name} vs {away_name}",
            "home_team":                home_name,
            "away_team":                away_name,
            "pillar_clash":             clash,
            "home_pillar_edges":        home_edge_count,
            "away_pillar_edges":        away_edge_count,
            "overall_structural_edge":  overall_edge,
            # These two combined figures are None whenever either side's pillar
            # is unmeasurable (`_mean2` returns None in that case, and
            # `over_signal` / `gg_signal` below already handle it). Calling
            # round() on that None raised
            #   TypeError: type NoneType doesn't define __round__ method
            # which aborted the clash for every fixture involving a team with
            # incomplete stats. They must be passed through untouched.
            "combined_box_dominance":   (None if combined_box_dominance is None
                                         else round(combined_box_dominance, 1)),
            "combined_goal_intent":     (None if combined_goal_intent is None
                                         else round(combined_goal_intent, 1)),
            "market_signals": {
                "Over_Under":   over_signal,
                "GG_NoGG":      gg_signal,
                "Corners":      corners_signal,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN EXECUTION LOOP
    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 — fetch all fixtures for the date (same as v1, with pagination)
    fixtures = fetch_all_fixtures_for_date(target_date)
    if not fixtures:
        print("❌ CRITICAL: No fixtures returned from API. Check key or date.")
        return {}

    # Step 2 — collect unique teams AND fixture pairings
    unique_teams   = {}
    fixture_pairs  = []    # NEW: used for style clash computation

    for fx in fixtures:
        participants = fx.get("participants", [])
        pair = []
        for p in participants:
            if p.get("id"):
                unique_teams[p["id"]] = p["name"]
                pair.append({"id": p["id"], "name": p["name"],
                              "location": p.get("meta", {}).get("location")})
        if len(pair) == 2:
            # Ensure home is first, away is second
            home = next((t for t in pair if t.get("location") == "home"), pair[0])
            away = next((t for t in pair if t.get("location") == "away"), pair[1])
            fixture_pairs.append({
                "fixture_id":   fx.get("id"),
                "fixture_date": fx.get("starting_at", target_date)[:10],
                "home":         home,
                "away":         away,
            })

    print(f"[2/3] Identity Check: Found {len(unique_teams)} teams across "
          f"{len(fixture_pairs)} fixtures to profile.")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 — compute DNA for every team (FRESHNESS-AWARE PERSISTENT CACHE)
    # ─────────────────────────────────────────────────────────────────────────
    output_path = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    dna_profiles = {}

    # Check if we already have teams cached on disk from previous runs.
    # This is the GLOBAL, multi-date library — every team ever profiled,
    # across every date main.py has run — and stays that way (requirement:
    # global libraries are preserved, never rebuilt or converted).
    if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                dna_profiles = json.load(f)
            print(f"   [⚡ DISK CACHE LOADED] Loaded {len(dna_profiles)} pre-computed teams from disk.")
        except Exception:
            dna_profiles = {}

    count = 1
    newly_fetched = 0       # true recomputes only (formula actually re-ran)
    reused_fresh  = 0       # zero-API-call reuses (within freshness window)
    reused_stale_unchanged = 0   # one-call check confirmed no change

    for team_id, team_name in unique_teams.items():
        tid_str = str(team_id)
        cached = dna_profiles.get(tid_str)

        # ── PATH 1: fresh cache hit — zero API calls, same cost as before ──
        if cached and _is_profile_fresh(cached):
            reused_fresh += 1
            count += 1
            continue

        print(f"   ({count}/{len(unique_teams)}) Checking DNA freshness: {team_name}...",
              end=" ", flush=True)

        # Stale (or legacy/never-cached) — one lightweight history call to
        # find out whether the team's latest FINISHED match has changed.
        match_history = get_team_history_stats(team_id)
        latest_fixture_id = match_history[0].get("id") if match_history else None

        # ── PATH 2: stale, but the latest finished match is unchanged ──────
        # The underlying data this team's DNA was computed from hasn't
        # moved, so recomputing would produce an identical result — just
        # bump the freshness timestamp instead of redoing the math.
        if (cached is not None and latest_fixture_id is not None
                and cached.get("history", {}).get("last_fixture_id") == latest_fixture_id):
            cached["computed_at"] = datetime.now(timezone.utc).isoformat()
            dna_profiles[tid_str] = cached
            reused_stale_unchanged += 1
            print("Unchanged — reused ✅")
            count += 1
            continue

        # ── PATH 3: new team, or latest finished match genuinely changed ──
        profile = calculate_comprehensive_dna(team_id, team_name, match_history)

        if profile:
            profile["history"] = {
                "last_fixture_id": latest_fixture_id,
                "last_match_date": (
                    str(match_history[0].get("starting_at", ""))[:10]
                    if match_history else None
                ),
                "matches_used": len(match_history),
            }
            profile["computed_at"] = datetime.now(timezone.utc).isoformat()
            dna_profiles[tid_str] = profile
            newly_fetched += 1
            print("Refreshed ✅")
        else:
            print("Skipped (No Stats) ⚠️")

        count += 1
        time.sleep(REQUEST_DELAY)

    print(
        f"   [⚡ CACHE SUMMARY] Fresh reuse (0 calls): {reused_fresh} | "
        f"Stale-but-unchanged (1 call, no recompute): {reused_stale_unchanged} | "
        f"Recomputed: {newly_fetched} | Total teams today: {len(unique_teams)}"
    )

    # Step 4 — compute style clashes for every fixture (NEW in v2)
    print("\n[2.5/3] Computing fixture-level style clashes...")
    fixture_clashes = []

    for fp in fixture_pairs:
        h_id      = str(fp["home"]["id"])
        a_id      = str(fp["away"]["id"])
        h_profile = dna_profiles.get(h_id)
        a_profile = dna_profiles.get(a_id)
        clash     = compute_style_clash(
            h_profile, a_profile,
            fp["home"]["name"], fp["away"]["name"]
        )
        if clash:
            clash["fixture_id"]   = fp["fixture_id"]
            clash["fixture_date"] = fp["fixture_date"]
            clash["home_id"]      = h_id     # NEW — authoritative join key
            clash["away_id"]      = a_id     # NEW — authoritative join key
            fixture_clashes.append(clash)
            print(f"   ✅ Clash: {clash['fixture']} → Edge: {clash['overall_structural_edge']}")

    # Step 5 — save DNA profiles (v2-specific path)
    output_path = os.path.join(DATA_DIR, "team_dna_v2_profiles.json")
    print(f"\n[3/3] Saving DNA library to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dna_profiles, f, indent=4)

    # Step 6 — save style clashes (separate file)
    clashes_path = os.path.join(DATA_DIR, "fixture_style_clashes_v2.json")
    print(f"[3/3] Saving style clashes to {clashes_path}...")
    with open(clashes_path, "w", encoding="utf-8") as f:
        json.dump(fixture_clashes, f, indent=4)

    # Step 7 — save v1 compatibility copy (Feeds older engines automatically, 0 API calls)
    v1_path = os.path.join(DATA_DIR, "team_dna_profiles.json")
    with open(v1_path, "w", encoding="utf-8") as f:
        json.dump(dna_profiles, f, indent=4)

    print("\n" + "=" * 60)
    print(f"🏆 ALIENEDGE DNA ENGINE v2: COMPLETE ({target_date})")
    print(f"   Teams profiled today:  {len(unique_teams)}")
    print(f"   Global library size:   {len(dna_profiles)}")
    print(f"   Fixture clashes:       {len(fixture_clashes)}")
    print(f"   New pillars active:    Box Dominance, Shot Quality, Transition Pressure")
    print(f"   Previously wasted:     Tackles, Big Chances Created, Shots Insidebox,")
    print(f"                          Shots Outsidebox — ALL NOW ACTIVATED")
    print("=" * 60)

    # ─────────────────────────────────────────────────────────────────────────
    # DATE-SCOPED RETURN VALUE (this is the fix for the second half of the
    # bug — the function used to return the ENTIRE global `dna_profiles`
    # dict here, so output_store's "dna_v2" snapshot for a single date could
    # silently contain every team from every date ever processed. The files
    # written above (Steps 5-7) are still the full, unscoped global library
    # — only what gets handed back to the caller (and therefore what
    # output_store saves under output/cache/dna_v2__{date}.json) is now
    # filtered down to just today's fixture participants.
    # ─────────────────────────────────────────────────────────────────────────
    todays_team_ids = {str(tid) for tid in unique_teams.keys()}
    scoped_profiles_for_return = {
        tid: prof for tid, prof in dna_profiles.items() if tid in todays_team_ids
    }

    return {
        "dna_profiles":    scoped_profiles_for_return,
        "fixture_clashes": fixture_clashes,
    }


# Allow local testing
if __name__ == "__main__":
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_dna_engine_v2(today_date)
