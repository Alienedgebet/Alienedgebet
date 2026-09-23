"""
INTELLIGENT_PASS/pass_count.py — Intelligent Pass Count evaluator
═══════════════════════════════════════════════════════════════════════════════
A pure, read-only SECOND-LEVEL AUDIT over the intelligence AlienEdge already
produces. It answers one question per prediction row: "how many of the
applicable existing intelligence checks support this pick?" — expressed as a
compact count like "5/7".

HARD ARCHITECTURE RULES (user spec, all binding):
  • DISPLAY/AUDIT ONLY. It never changes, filters, re-grades or replaces the
    original prediction. Settlement / output_store / engines: 0 changes.
  • ZERO new SportMonks / live-API calls: every input is read from the same
    on-disk output/cache/{key}__{date}.json snapshots the API already serves
    (via output_store's documented convention). This module therefore imports
    nothing network-related and never calls an engine.
  • PER-FIXTURE three-state results: every check resolves to PASS / FAIL /
    NOT_AVAILABLE for that exact fixture. A genuinely unavailable intelligence
    NEVER becomes a fake FAIL. The DENOMINATOR IS FIXED per market: it is the
    market's full rule set (WIN=8, GG=4, …), so N/A outcomes lower the
    numerator only — the same pick always shows the same total (e.g. x/8),
    and only x varies (2/8, 5/8, 8/8 …).
  • No new intelligence is invented: each rule reads one pre-existing field or
    one pre-existing verdict/category produced by an existing engine. Where a
    rule cannot be backed by existing data it is intentionally NOT registered
    for that market (display-only stages keep an empty checklist).

RULE ORIGIN MAP (every threshold verified against the producing engine —
nothing here reinterprets or normalises a scale):
  ─ WIN SOT               PSYCHOLOGY/u2s_psychology.py per-side SOT
                           expectancy — the very columns the WIN page renders
                           as "SOT Expectancy (Dog)" / "SOT Expectancy (Fav)"
                           (Dog_Venue_SOT / Fav_Venue_SOT, last-3 venue SOT).
                           The predicted team's side is identified by the U2S
                           row's own Underdog column (fixture-level identity),
                           never by re-deriving favourite/underdog. The rule
                           is the engine's OWN Tier-A1 comparison (L607-620:
                           `if dog_v_sot > fav_v_sot … elif fav_v_sot >
                           dog_v_sot …` — equal totals award nothing): PASS
                           only when the predicted team's expectancy is
                           strictly greater than the opponent's. Match-level
                           Cerberus (Engine/sot_engine.py) has no per-side SOT
                           (Proj_SOT is a match total), so it is not the WIN
                           SOT source.
  ─ Corners card           The user's 2-check card (2026-09-23): the
                           underdog's per-team Spears % (gg_supreme /
                           gg_psychology "H:X%|A:Y%"; the dog's side comes
                           from the fixture label, then the win_forecast
                           side row — never assumed) must be > 60, and
                           the under-2.5 probability < 40% (unders
                           mc_u25_prob, else 100 - over25_forecast
                           poisson_over_prob_num). The old corner4
                           Friction / Corner Power card is gone.
  ─ WIN Corners            Per-team EXPECTED corners, nearest engine first:
                           corners_stage2 / corners_psychology / corners_catalyst
                           predicted_corners +/- diff (the exact formula the
                           aggregator stores as Home_Exp / Away_Exp) —
                           fixture-id join; then the aggregator
                           (Home_Exp / Away_Exp, else True_Corner_Fav) —
                           label join; then corners_stage1 (engine's own
                           team_more_corners verdict / lastN averages);
                           DNA corners intelligence (market factors, then
                           per-team profiles) is the documented last resort
                           for a fixture no corner engine produced. PASS:
                           predicted team's expectation > opponent's.
  ─ WIN Psychology         PSYCHOLOGY/win_psychology.py H_Base / A_Base are
                           the two sides' base scores; PASS requires the
                           predicted team's base to sit WIN_PSYCH_MIN_GAP
                           (+50) ABOVE the opponent's — stricter than the
                           engine's own LOCK floor (net >= 45). A
                           fixture-level audit net (Audit_Score, the picked
                           side's margin) uses the same gap when the side
                           pair is absent.
  ─ Underdog (U2S)         AGGREGATOR/master_underdog_audit.py Dog_Score_Prob
                           (0-100 "%") is the longshot gate; PASS < 50%. The
                           same producer's Engine/underdog_engine.py
                           dog_score_prob is the documented fallback (same
                           field, same scale, same engine family).
  ─ WIN Goal Intent        CORE/dna_v2_market_factors.py per-side Goal Intent
                           (home_value / away_value 0-100, produced off
                           DNA Market_Power_Scores). WIN rule: the predicted
                           team's Goal Intent > the opponent's → PASS.
                           Fallback for fixtures without a market-factor
                           entry: the same engine's per-team
                           Market_Power_Scores.Goal_Intent profiles
                           (data/team_dna_profiles.json / cache dna) for both
                           named teams — identical field, identical 0-100
                           scale, no new formula.
  ─ WIN Parity             Engine/win_forecast.py parity_score is ALREADY
                           SIGNED PER SIDE ("parity_score": parity_diff if
                           side=="home" else -parity_diff) — the selected
                           team's 5-game goal-involvement (venue+overall+H2H)
                           advantage vs this exact opponent. User rule: PASS
                           = parity_score >= +10 on the selected team's row.
  ─ WIN Form               ONE check, THREE legs: the predicted team must
                           have (a) more venue goals, (b) more venue wins,
                           and (c) less conceded at its venue than the
                           opponent (Engine/win_forecast.py + win_raw_engine.py
                           last_5_venue_goals_scored / last_5_wins_at_venue /
                           last_5_venue_goals_conceded — both sides are
                           always written by the same engine). All three =
                           FULL pass; two = HALF; one = LOW; the tier travels
                           on the payload and only FULL earns the count (the
                           check stays ONE rule of the WIN 8-rule set).
                           Snapshots without the venue fields fall back to
                           the saved overall counters.
  ─ Draw probability       Engine/draw_engine.py mc_draw_prob (0-1 Monte
                           Carlo) < 0.20 (user rule); dmi (Draw Magnet Index
                           0-1) >= 0.45 and parity (0-1) >= 0.6 are the
                           engine's own tier gates (L863/870) — reused
                           verbatim. A WIN pick whose fixture has no draw
                           row falls back to the pick's own
                           Monte_Draw_Prob (the WIN apex engine's own draw
                           risk, 0-100 %) against the same 20% cut.
  ─ DNA parity (draw)      data/dna_v2_market_factors.json markets.draw
                           factor win-count balance: |home_count-away_count|
                           in {0,1} (user rule; values outside 0/1 FAIL).
  ─ O2.5 / O1.5 cards      The user's six-question card at each market's own
                           level (2026-09-23): probability > 60% (O2.5 =
                           poisson_over_prob_num, O1.5 = stage3 Poisson% →
                           psychology Base_Poisson → gg_o15 mc_over15_prob);
                           council_votes >= 7 of 9; combined_gs_last_5 >
                           20 (O1.5: > 15); DNA Goal Intent BOTH sides > 50;
                           kill switch = last 3 H2H all over 2.5 (O1.5:
                           parsed from stage3 H2H_Record totals >= 2, NOT
                           the 2.5 flag); one team in the league top 10
                           (positions chained: corners_aggregator → corner
                           stage2/psych/catalyst → draw engine; none found
                           → NOT_AVAILABLE).
  ─ GG card                The ONE unified 4-check card on every GG table
                           (supreme / precision / O1.5 composite, user rules
                           2026-09-23): (1) BOTH teams' Spears % > 65
                           (gg_supreme / gg_psychology "H:X%|A:Y%"); (2)
                           BOTH teams' DNA Goal Intent > 60 (win pack
                           markets.gg factors); (3) combined_gs_last_5 > 8
                           (over25_forecast); (4) BOTH teams conceded
                           recently (win_forecast side rows'
                           opp_last_5_conceded_raw > 0 — each row's value
                           is the opposite team's conceded). The old
                           Precision 5-signal / lambda-composite cards are
                           gone.
  ─ Unders parity          O2.5/O1.5 parity_diff is a SIGNED league-position
                           parity (engine gate: > 0) — NOT a ±0.4 scale.
  ─ FHVI / SHVI            Engine/fhvi_engine.py / shvi_engine.py Category
                           gate: score >= 7 == "TIER 2 - GOOD" or better.
  ─ SOT card               The user's 2-check card (2026-09-23): match-level
                           psychology > 60 (gg_psychology Psych_Score, WIN
                           psychology Audit_Score fallback) and the OVER-2.5
                           probability > 60% (100 - unders mc_u25_prob, else
                           over25_forecast poisson_over_prob_num).
  ─ Dead rubbers           AGGREGATOR/corner4_aggregator.py Chaos_Rating
                           (0-100): <= 20 == nothing to play for.
  ─ U2S card               The user's card (2026-09-23), denominator 3 — or
                           4 when the venue check has a verdict (the one
                           deliberate variable denominator): (1) Psych_Score
                           > 60, the string VETOED = explicit FAIL; (2)
                           dog_att_strength >= 3 x fav_def_weakness
                           (three-fold: 9 vs 3 passes; leak 0 with attack 0
                           = no data → N/A, leak 0 with attack > 0 = wall →
                           FAIL); (3) attack x leak >= 2 double-strength
                           signal; (4) venue scoring — the underdog's
                           win_forecast last_5_wins_at_venue >= 3 of its
                           last 5; the full u2s_psychology venue sample
                           (Dog_Scoring_Consistency 3/3) is the surrogate,
                           a partial sample cannot disprove the rule and is
                           omitted, never a fake FAIL.

COMPOSITE CACHE FILES
  gg_o15 and unders store several market heads in one payload. Only the
  whitelisted head is read (_COMPOSITE_HEAD0_KEYS): gg_o15 head 0 = the GG
  supreme list the /api/gg/supreme route serves; unders head 0 = the u25
  list /api/unders serves. Parity / u35 / o15 heads are different markets
  and are never read by this evaluator.

IDENTITY
  fixture_id is the primary key wherever a source carries it (normalised to
  str() — cache files mix str/int, and a raw-int comparison against a
  str-keyed registry silently dropped the WIN side rows). Legacy name-only
  sources (psychology, sot, fhvi, shvi, corner4) use deterministic label
  normalisation — the same clean_n/get_match_key convention those engines
  already use, NOT fuzzy team matching. A fixture_id whose label-bearing
  sources disagree is resolved through label_by_id (majority label of the
  id-bearing engines on that date), so a row that stores the fixture with the
  sides swapped can still reach every name-keyed source. Composite cache files
  (draw, unders, gg_o15) are read head-0 only (their parity-list / u35 / o15
  heads are different markets).

CROSS-DAY SOURCE WINDOW  (why N/A was wrong for existing intelligence)
  main.py documents that the WIN Apex aggregator "takes NO date argument —
  it always reads the latest merged state", so the SAME apex payload is
  snapshotted under every date while its supporting engine rows live in the
  files of the day the apex engine actually read (verified 2026-09-21:
  189/191 apex picks resolve their U2S / psychology / corners / SOT rows in
  the 2026-09-20 caches, one day back; 14/15 on 2026-09-22). Auditing such a
  pick against the requested date alone produced NOT_AVAILABLE for
  intelligence that is saved on disk — the exact failure this module must not
  repeat. Every source join therefore resolves in a bounded date window
  (the requested date FIRST, then ±1..±MAX_SOURCE_LOOKBACK_DAYS), matching by
  fixture_id and, for id-less sources, by the label that date's own
  id-bearing engines confirm. The date that supplied every value is reported
  on the check itself (`source`), so the audit stays fully traceable.

PROVENANCE (how the user can see where each value comes from)
  Every check is {name, result, value, threshold, source, field, mapping}:
    source  — the engine key (cache file) + the date the row was read from;
    field   — the exact source field inside that engine's row;
    mapping — the team/side mapping used (e.g. "predicted=AtNé side=FAV");
  so no PASS/FAIL is ever unexplained.
"""
import json
import os
import re
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "output", "cache")

PASS = "PASS"
FAIL = "FAIL"
NOT_AVAILABLE = "NOT_AVAILABLE"

# ══════════════════════════════════════════════════════════════════════════════
# CENTRAL RULES CONFIGURATION — the single place every new threshold lives.
# Each entry was verified against the producing engine before being written
# (see module docstring for the origin map). Direction of every comparison is
# repo-native: nothing was inverted or normalised.
# ══════════════════════════════════════════════════════════════════════════════
INTELLIGENT_PASS_RULES = {
    # ── WIN ────────────────────────────────────────────────────────────────
    # Parity +10: win_raw/win_forecast parity_score is signed per side.
    "WIN_PARITY_THRESHOLD": 10,
    # WIN Draw Probability — the requested WIN cut (user rule): a WIN pick is
    # clean when the fixture's draw probability stays BELOW 20%. Both stored
    # representations of that same 20% are listed next to the field they
    # belong to (draw engine mc_draw_prob is a 0-1 Monte Carlo float; the WIN
    # apex row's Monte_Draw_Prob is the same quantity as a 0-100 number).
    "WIN_DRAW_PROB_MAX": 0.20,
    "WIN_DRAW_PROB_MAX_PCT": 20,
    # WIN Underdog — the longshot gate's own scale (0-100 "%"), PASS below it.
    "WIN_UNDERDOG_SCORE_PROB_MAX": 50,
    # Cross-day source window (see the module docstring): the requested date is
    # always tried first; only a genuine miss on that date looks at ±N days.
    "MAX_SOURCE_LOOKBACK_DAYS": 3,
    # Draw engine's own draw-candidate floor (Engine/draw_engine.py TIER2 gate
    # `mc_draw >= 0.22`). A WIN pick PASSES when the fixture is BELOW the
    # engine's draw-candidate floor; the DRAW page uses the same constant in
    # its native direction (>= floor = draw supported).
    "DRAW_MC_DRAW_PROB_FLOOR": 0.22,
    # Draw engine's own tier gates (L863): parity >= 0.6, dmi >= 0.45.
    "DRAW_PARITY_THRESHOLD": 0.6,
    "DRAW_DMI_THRESHOLD": 0.45,
    # DRAW — DNA factor-count parity balance (0 or 1 pass, else fail).
    "DRAW_DNA_PARITY_PASS_VALUES": {0, 1},
    # ── UNDERDOG (U2S) — user rules 2026-09-23 (4 checks) ────────────────────
    # 1) Psychology must be ABOVE this (u2s_psychology.Psych_Score scale);
    #    the string VETOED is an explicit FAIL verdict, never a N/A.
    "U2S_PSYCH_MIN": 60,
    # 2) Attack-vs-defence rule (user example: attack 9, defence 3 → PASS):
    #    dog_att_strength must beat the favourite's concession rate THREE-FOLD.
    "U2S_ATT_DEF_FOLD": 3,
    # 3) Attack + defence leak together (double-strength signal):
    #    dog_att_strength * fav_def_weakness >= 2.
    "U2S_ATT_LEAK_PRODUCT": 2,
    # 4) Venue scoring: the underdog's win_forecast side row must carry
    #    last_5_wins_at_venue >= 3 (scored/won in at least 3 of its last 5
    #    venue matches). Surrogate when no win row resolves: the full
    #    u2s_psychology Dog_Scoring_Consistency venue sample (scored in ALL
    #    of its last 3) PROVES the 3-of-5 rule; a partial sample cannot
    #    disprove it → the check is omitted (the card stays x/3).
    "U2S_VENUE_SCORE_MIN": 3,
    # Venue matches in the win_forecast counter (0-5).
    "U2S_VENUE_LOOKBACK": 5,
    # ── PSYCHOLOGY (signed base scores, NOT percentages) ────────────────────
    "PSYCHOLOGY_NET_SCORE_PASS": 0,
    # WIN psychology gate: the predicted team's base score must be this far
    # ABOVE the opponent's (PSYCHOLOGY/win_psychology.py H_Base / A_Base).
    "WIN_PSYCH_MIN_GAP": 50,
    # WIN corners: per-team expected corners, nearest engine first — the
    # corner engines' own paired predictions (stage2 predicted_corners ±
    # diff, aggregator Home_Exp/Away_Exp, stage1 per-team averages), then the
    # DNA corners factors / profiles as the last-resort data source for a
    # fixture no corner engine produced.
    "WIN_CORNER_SOURCES": ("corners_stage2", "corners_aggregator",
                           "corners_stage1"),
    # ── O2.5 / O1.5 — user rules 2026-09-23 (the same six-question card at
    # each market's own level; Engine/over25_forecast.py carries the fields) ──
    "O25_POISSON_VOTE_MIN": 60,         # probability > 60% (both markets)
    "O15_PROB_MIN": 60,                 # O1.5 probability > 60%
    "O25_COUNCIL_MIN": 7,               # council_votes >= 7 of 9
    "O25_GOAL_COUNT_MIN": 20,           # combined_gs_last_5 > 20 (O2.5)
    "O15_GOAL_COUNT_MIN": 15,           # combined_gs_last_5 > 15 (O1.5)
    "DNA_INTENT_SIDE_MIN": 50,          # both teams' DNA Goal Intent > 50
    "TOP10_LEAGUE_MAX": 10,             # one team must sit in the top 10
    # ── DNA engine v2 clash signals (CORE/dna_engine_v2.py L591-607) ───────
    "DNA_OVER_LEAN_CUT": 55,      # LEAN OVER: box_dominance > 55 or goal_intent > 55
    "DNA_LEAN_GG_BOX": 60,        # LEAN GG: combined box dominance > 60
    "DNA_HIGH_CORNERS_CUT": 70,   # HIGH CORNERS: either side Corner_Power > 70
    # ── GG precision engine (Engine/gg_precision_engine.py) ───────────────
    "GG_GK_LIABILITY_CPG": 1.10,  # gk_bonus gate: cpg <= 1.10 = not liable
    # ── GG — 4 checks on EVERY GG table (user rules 2026-09-23) ──────────────
    # 1) BOTH teams' psych score > 65%: parse the per-team Spears field
    #    (gg_supreme / gg_psychology: "H:X%|A:Y%"). Both X and Y must be > 65.
    "GG_BOTH_TEAMS_PSYCH_MIN": 65,
    # 2) BOTH teams' goal intent > 60%: DNA goal intent from win pack
    #    (dna_by_id[fixture]["gg"]["factors"] → "Goal Intent" home_value/away_value).
    "GG_BOTH_TEAMS_GOAL_INTENT_MIN": 60,
    # 3) Both teams combine goal in last 5 matches above 8:
    #    over25_forecast.combined_gs_last_5 (combined both teams) > 8.
    "GG_BOTH_TEAMS_LAST5_GOAL_MIN": 8,
    # 4) Both teams MUST concede in their last 3 recent matches:
    #    win_forecast two rows per fixture; opp_last_5_conceded_raw for each
    #    team's opponent > 0 (both teams conceded in their last 5; estimate
    #    last-3 from that). Both teams must have conceded.
    # ── SOT — 2 checks (user rules 2026-09-23) ──────────────────────────────
    # 1) Over 2.5 probability > 60%: over25_forecast.poisson_over_prob_num.
    "SOT_O25_PROB_MIN": 60,
    # 2) Psychology > 60%: gg_psychology / gg_supreme Psych_Score (blended
    #    fixture-level score) or the pick's side Spears %.
    "SOT_PSYCH_MIN": 60,
    # ── CORNER — 2 checks (user rules 2026-09-23) ────────────────────────────
    # 1) Underdog > 60%: parse the underdog team's per-team Spears % from
    #    gg_supreme / gg_psychology; must be > 60%.
    "CORNER_UNDERDOG_PSYCH_MIN": 60,
    # 2) Under 2.5 below 40%: unders.mc_u25_prob < 40 (i.e. over 2.5 > 60%).
    "CORNER_U25_PROB_MAX": 40,
         # ── FHVI/SHVI Category gate (>=7 == TIER 2 GOOD or better) ────────────
    "FHVI_TIER2_THRESHOLD": 7,
    "SHVI_TIER2_THRESHOLD": 7,
    # SOT engine Game_Script tags that structurally support a shots market.
    "SOT_SUPPORT_TAGS": ("GLASS CANNONS", "SLAUGHTER"),
    "SOT_DIAMOND_TOKEN": "DIAMOND",
}

# WIN check name → the authoritative source field (provenance for rows that
# resolve with no pickable side, so even NOT_AVAILABLE says where it looked).
_WIN_FIELDS = {
    "SOT": "U2S Dog_Venue_SOT / Fav_Venue_SOT",
    "Corners": "corner engines per-team expected corners "
               "(stage2 predicted_corners±diff, aggregator Home_Exp/Away_Exp, "
               "stage1 lastN averages)",
    "Psychology": "win_psychology H_Base / A_Base (margin >= +50 for the pick)",
    "Underdog": "underdog Dog_Score_Prob",
    "Goal Intent": "DNA Goal Intent",
    "Draw Probability": "draw mc_draw_prob / apex Monte_Draw_Prob",
    "Parity +10": "win parity_score",
    "Form": "win venue goals / venue wins / venue conceded vs opponent",
}

# Markets whose pipeline stage carries no applicable second-level intelligence
# of its own: they intentionally render no Intelligent Pass column (the
# frontend hides the cell because the API attaches no audit object).
DISPLAY_ONLY_MARKETS = frozenset({
    "gg_psychology", "gg_forensics", "over25_psychology", "over15_psychology",
    "over25_gold", "over25_stage1", "over25_stage2", "over25_stage3",
    "over15_stage3", "corners_stage1", "corners_stage2",
    "corners_psychology", "corners_catalyst", "sh_gg_winner",
    "underdog_apex_display", "cross_verify",
})

# ── MARKET-KEYED REPORT ARCHITECTURE ────────────────────────────────────────
# The PICK is the primary object: the Team Intelligence page is a
# MARKET-SPECIFIC audit (team+date+market = the report identity), never a
# generic all-markets dashboard. Canonical keys below are what the report
# URL/API accept; aliases map them onto the evaluator's internal engine keys
# so a click from ANY table opens the report of the market that was clicked.
TEAM_INTELLIGENCE_MARKETS = {
    # canonical report key -> label shown by the report page
    "win": "Win",
    "win_psychology": "Win Psychology",
    "gg": "GG / BTTS Supreme",
    "gg_precision": "GG Precision",
    "gg_o15": "GG / Over 1.5 Composite",
    "over25": "Over 2.5",
    "over15": "Over 1.5",
    "corners": "Corners",
    "draw": "Draw",
    "unders": "Under 2.5",
    "u2s": "Underdog-to-Score",
    "fhvi": "FHVI",
    "shvi": "SHVI",
    "sot": "SOT",
}
_MARKET_EVALUATOR_ALIASES = {
    # canonical report key -> the evaluator engine key(s) that market audits with
    # "win" and "win_psychology" are the SAME pick (WIN pack): ONE checklist.
    "win": ("win_apex", "win_forecast", "win_raw"),
    "win_psychology": ("win_apex", "win_forecast", "win_raw"),
    "gg": ("gg_supreme",),
    "gg_precision": ("gg_precision",),
    "gg_o15": ("gg_o15",),
    "over25": ("over25_apex", "over25_forecast"),
    "over15": ("over15", "over15_stage3", "over15_apex"),
    "corners": ("corners_aggregator",),
    "draw": ("draw",),
    "unders": ("unders_u25",),
    "u2s": ("u2s",),
    "fhvi": ("fhvi",),
    "shvi": ("shvi",),
    "sot": ("sot",),
}
# ══════════════════════════════════════════════════════════════════════════════
# LOW-LEVEL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _norm(name):
    """Deterministic fixture/team label normalisation (repo clean_n
    convention: case/spacing/punctuation-insensitive, accent-folded).
    This is NOT fuzzy matching — both sides of a join come from the same
    SportMonks feed, so normalised labels are exact."""
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _num(v):
    """Best-effort numeric coercion; returns None when genuinely not a number
    (so the caller can emit NOT_AVAILABLE instead of a fake FAIL)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _frac(v):
    """Coerce a probability that may be stored as 0-1 float or "%"-string
    into a 0-1 float. None when unavailable."""
    f = _num(v)
    if f is None:
        return None
    return f / 100.0 if f > 1.5 else f


def _load(key, date):
    """Disk-only read of one engine snapshot (output_store's documented
    filename convention). Missing file → None (never raises, never computes).

    Composite cache files (gg_o15, unders) store several market heads in one
    payload; only the whitelisted head is ever read (never the parity /
    u35 / o15 heads, which belong to different markets)."""
    path = os.path.join(CACHE_DIR, f"{key}__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f).get("data")
    except Exception:
        return None
    if key in _COMPOSITE_HEAD0_KEYS and isinstance(data, list) and data \
            and isinstance(data[0], list):
        return data[0]
    return data


# Composite cache payloads whose HEAD 0 is the market the API serves for the
# key (verified 2026-09-20: gg_o15 head0 = GG supreme, unders head0 = u25).
_COMPOSITE_HEAD0_KEYS = frozenset({"gg_o15", "unders"})


def _load_heads(key, date):
    """Raw payload of a composite cache file (list of market heads), no
    head-0 shortcut — used where the evaluator needs a specific non-zero
    head (gg_o15 head1 == the Over-1.5 composite rows)."""
    path = os.path.join(CACHE_DIR, f"{key}__{date}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f).get("data")
    except Exception:
        return None
    return data


def _head_n(data, idx):
    if isinstance(data, list) and len(data) > idx and isinstance(data[idx], list):
        return [r for r in data[idx] if isinstance(r, dict)]
    return []


_DNA_PROFILE_MEMO = {"index": None}


def _index_dna_profiles(payload):
    """{normalised team name: DNA profile} from a dna payload
    ({team_id: profile}, CORE/dna_profiler.py)."""
    idx = {}
    if isinstance(payload, dict):
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            name = entry.get("team_name")
            if name:
                idx.setdefault(_norm(name), entry)
    return idx


def _dna_profiles(date):
    """Per-team DNA profiles for this date: the date's own dna cache payload
    when the pipeline produced one, otherwise the cumulative producer file
    data/team_dna_profiles.json (loaded once per process — it is the same
    engine store for every date, so the window never duplicates it)."""
    payload = _load("dna", date)
    if isinstance(payload, dict) and payload:
        return _index_dna_profiles(payload)
    if _DNA_PROFILE_MEMO["index"] is None:
        try:
            with open(os.path.join(ROOT, "data", "team_dna_profiles.json"),
                      "r", encoding="utf-8") as f:
                _DNA_PROFILE_MEMO["index"] = _index_dna_profiles(json.load(f))
        except Exception:
            _DNA_PROFILE_MEMO["index"] = {}
    return _DNA_PROFILE_MEMO["index"]


def _load_dna_factors(date):
    """DNA v2 market factors. Reads the API's served snapshot first
    (output/cache/dna_market_factors__{date}.json, dict {fixture_id: entry});
    falls back to the day's data/dna_v2_market_factors.json (same dict shape,
    same producer file) when the snapshot has not been generated yet.
    Disk-only either way."""
    dmf = _load("dna_market_factors", date)
    if isinstance(dmf, dict) and dmf:
        return dmf
    # Same payload shape ({fixture_id: entry}) either way: the day's dated
    # copy first, then the producer file as written by the LAST pipeline run.
    # Never read a dict-less stale fallback — a genuine miss returns None so
    # every check stays NOT_AVAILABLE instead of borrowing another date.
    path = os.path.join(ROOT, "data", "dna_v2_market_factors__%s.json" % date)
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    path = os.path.join(ROOT, "data", "dna_v2_market_factors.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _rows(data):
    """Flatten one envelope's data into flat dict rows (handles composite
    list-of-lists payloads defensively)."""
    out = []
    if isinstance(data, list):
        for grp in data:
            if isinstance(grp, list):
                out.extend(x for x in grp if isinstance(x, dict))
            elif isinstance(grp, dict):
                out.append(grp)
    elif isinstance(data, dict):
        out.append(data)
    return out


def _head0(data):
    """Head 0 of a composite cache file (draw → draw intelligence list,
    unders → u25 list). Parity/u35/o15 heads are different markets and are
    deliberately NOT read."""
    if isinstance(data, list) and data and isinstance(data[0], list):
        return [r for r in data[0] if isinstance(r, dict)]
    return _rows(data)
def _idstr(v):
    """Fixture identity as a string, or "" when the value is a placeholder.
    Cache files mix int and str ids ('19713004' vs 19713004) — every registry
    and comparison in this module uses this one normaliser, because an
    int-vs-str comparison against a str-keyed registry is exactly what let an
    apex row silently REPLACE the WIN side rows of its own fixture."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:      # NaN
        return ""
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "n/a", "na", "null", "-"}:
        return ""
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _id_index(rows):
    """{str(fixture_id): row} — fixture_id is the primary identity wherever
    a source carries it (cache files mix str/int ids)."""
    idx = {}
    for r in rows:
        fid = _idstr(r.get("fixture_id"))
        if fid:
            idx.setdefault(fid, r)
    return idx


_NAME_FIELDS = ("fixture", "Fixture", "Match", "fixture_name")


def _corner2_by_id(stage2_rows, cpsych_rows, ccat_rows):
    """The refiner-stage corner rows keyed by fixture id (stage2 preferred;
    psychology / catalyst rows carry the same fields for the same fixtures
    and are used when a stage2 row is absent). The source tag travels on
    `__source` so every check can report exactly where its values came from.
    """
    idx = {}
    for rows_, tag in ((stage2_rows, "corners_stage2"),
                       (cpsych_rows, "corners_psychology"),
                       (ccat_rows, "corners_catalyst")):
        for r in rows_ or []:
            if not isinstance(r, dict):
                continue
            fid = _idstr(r.get("fixture_id"))
            if fid and fid not in idx:
                idx[fid] = dict(r, __source=tag)
    return idx


def _name_index(rows):
    """{normalised fixture label: row} for legacy name-keyed sources."""
    idx = {}
    for r in rows:
        for f in _NAME_FIELDS:
            v = r.get(f)
            if v:
                idx.setdefault(_norm(v), r)
                break
    return idx


_VS_SPLIT = r"\s+vs\.?\s+"


def _reverse_label(label):
    """The same fixture with its two sides swapped ("A vs B" → "B vs A").
    Deterministic, not fuzzy: the two labels describe the identical fixture,
    only the stored orientation differs between engines. Used ONLY after the
    exact label and the date's canonical label both missed."""
    parts = re.split(_VS_SPLIT, str(label or "").strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return ""
    return f"{parts[1].strip()} vs {parts[0].strip()}"


def _canonical_label(snap, fid):
    """The fixture's label as stored by that date's ID-BEARING engines
    (win_raw/win_forecast, underdog, draw, unders, over25, fhvi/shvi, DNA
    market factors). Apex rows are known to store the fixture with the sides
    swapped (verified: apex 'Atlético Nacional vs Llaneros' == side rows'
    'Llaneros vs Atlético Nacional'), so the id-bearing majority label — not
    the calling row's own string — is what the name-keyed engines are joined
    on."""
    fid = _idstr(fid)
    if not fid:
        return ""
    return (snap.get("label_by_id") or {}).get(fid, "")


def _resolve(snap, prefix, fid, fxn):
    """Resolve a source row: fixture_id first, then the exact label, then the
    date's canonical label for that id, then the reversed label. Indexes are
    per-source, so an id hit is always same-file, and every fallback is an
    exact normalised string comparison (never fuzzy matching)."""
    by_id = snap.get(prefix + "_by_id") or {}
    by_name = snap.get(prefix + "_by_name") or {}
    fid_s = _idstr(fid)
    if fid_s and fid_s in by_id:
        return by_id[fid_s]
    if fxn:
        key = _norm(fxn)
        if key in by_name:
            return by_name[key]
    canon = _canonical_label(snap, fid_s)
    if canon:
        key = _norm(canon)
        if key in by_name:
            return by_name[key]
        rev = _norm(_reverse_label(canon))
        if rev and rev in by_name:
            return by_name[rev]
    if fxn:
        rev = _norm(_reverse_label(fxn))
        if rev and rev in by_name:
            return by_name[rev]
    return None


def _fixture_label(row):
    for f in _NAME_FIELDS:
        v = row.get(f)
        if v:
            return str(v)
    return ""


def _split_fixture(label):
    parts = re.split(_VS_SPLIT, str(label or "").strip())
    return (parts[0], parts[1]) if len(parts) == 2 else ("", "")
# ══════════════════════════════════════════════════════════════════════════════
# PER-DATE SNAPSHOT (lazy memo — one dict of references to already-on-disk rows
# per date; the cross-day window keeps at most _MAX_WINDOW_SNAPSHOTS dates)
# ══════════════════════════════════════════════════════════════════════════════

_SNAPSHOTS = {}
_SNAP_FRESH_AT = {}  # date → monotonic ts of the last freshness validation
# Freshness validations are THROTTLED per date: each one scans the whole
# cache dir (~660 entries), and evaluate_market re-enters _snapshot ~20× per
# row via internal source lookups — unthrottled that was 13,000+ stat() calls
# per row (~0.19 s). A 2 s TTL keeps a mid-request pipeline save visible
# within ≤2 s while making every other entry a dict lookup.
_FRESH_VALIDATE_SECONDS = 2.0
# Per-date staleness metadata for the memo above: the cache dir's own mtime
# (changes on every atomic save / file create / delete) plus the mtime of
# every cache file the build actually touched (absent files recorded with
# None so a later creation is detected). A long-lived API worker must never
# serve a pre-pipeline snapshot as current data.
_SNAP_META = {}
# Bounded window cache: enough for the requested date plus the FULL ±lookback
# window the cross-day payloads walk (±3 days = 7 dates) — a cap smaller than
# the window made every single row evict and rebuild full snapshots
# (~0.27 s each), which turned a 191-row apex response into a ~90 s request
# and timed the WIN Pick Pack out on full dates.
_MAX_WINDOW_SNAPSHOTS = 8
# Hermetic-test seam for _seal_date() below: when set, cross-day source
# lookups are restricted to exactly these dates, so an injected snapshot can
# never silently fall through to real cache files on disk.
_WINDOW_DATES_OVERRIDE = None


def _seal_date(*dates):
    """Hermetic-test seam: PIN cross-day joins to exactly the given dates.

    Offline suites inject synthetic snapshots, but the evaluator's source
    window would otherwise fall through to REAL cache files on neighbouring
    dates (fortuitous hits/flaky misses). Every suite must call this with its
    synthetic date right after injecting — the window then touches nothing
    else."""
    global _WINDOW_DATES_OVERRIDE
    _WINDOW_DATES_OVERRIDE = list(dates)


def clear_cache():
    """Test/ops hook — drop every memoised per-date snapshot. Also UNSEALS
    the date window (the next call re-seals as needed)."""
    global _WINDOW_DATES_OVERRIDE
    _SNAPSHOTS.clear()
    _WINDOW_DATES_OVERRIDE = None
    _SNAP_META.clear()
    _SNAP_FRESH_AT.clear()


def _window_dates(date):
    """The dates a source join may look at, in priority order: the requested
    date first, then the nearer neighbours (±1 … ±MAX_SOURCE_LOOKBACK_DAYS).
    Bounded by construction — the module never scans the whole archive."""
    if _WINDOW_DATES_OVERRIDE is not None:
        return list(_WINDOW_DATES_OVERRIDE)
    from datetime import date as _d, timedelta as _td
    try:
        base = _d.fromisoformat(str(date))
    except (TypeError, ValueError):
        return [date]
    span = int(INTELLIGENT_PASS_RULES["MAX_SOURCE_LOOKBACK_DAYS"])
    out = [base.strftime("%Y-%m-%d")]
    for step in range(1, span + 1):
        out.append((base - _td(days=step)).strftime("%Y-%m-%d"))
        out.append((base + _td(days=step)).strftime("%Y-%m-%d"))
    return out


def _trim_window_cache(keep):
    """Evict the least-recently-inserted snapshot once the window cache is
    full (plain FIFO — the requested date of the current call is always the
    most recent insertion, so it can never be evicted mid-evaluation)."""
    while len(_SNAPSHOTS) > _MAX_WINDOW_SNAPSHOTS:
        for key in list(_SNAPSHOTS):
            if key != keep:
                _SNAPSHOTS.pop(key, None)
                _SNAP_META.pop(key, None)
                break
        else:
            break


def _record_snapshot_meta():
    """Fingerprint the cache dir cheaply: the dir's own mtime (changes on
    every atomic engine save / file create / delete) plus the mtime of every
    file in it. ~1 ms for a few hundred files — negligible next to the
    ~0.3 s snapshot rebuild it guards."""
    try:
        st = os.stat(CACHE_DIR)
        meta = {"dir": st.st_mtime_ns, "files": {}}
        with os.scandir(CACHE_DIR) as it:
            for entry in it:
                try:
                    meta["files"][entry.name] = entry.stat().st_mtime_ns
                except OSError:
                    meta["files"][entry.name] = None
        return meta
    except OSError:
        return None


def _snapshot_is_fresh(meta):
    """True when the dir mtime AND every recorded file mtime are unchanged
    since the fingerprint was taken. Missing/absent files (None) are
    compared by name so a later creation is detected."""
    try:
        st = os.stat(CACHE_DIR)
        if st.st_mtime_ns != meta.get("dir"):
            return False
        prev = meta.get("files") or {}
        with os.scandir(CACHE_DIR) as it:
            seen = set()
            for entry in it:
                seen.add(entry.name)
                try:
                    m = entry.stat().st_mtime_ns
                except OSError:
                    m = None
                if prev.get(entry.name, object()) != m:
                    return False
        return len(prev) == len(seen)
    except OSError:
        return False


def _snapshot(date):
    snap = _SNAPSHOTS.get(date)
    if snap is not None:
        # mtime-validated memo: the cache dir's mtime changes on EVERY
        # atomic engine save (file create/replace/delete), and per-file
        # mtimes catch in-place edits. Unchanged mtimes → the memo IS the
        # current disk state, so the ~0.3 s rebuild is skipped per row.
        # Freshness checks are THROTTLED to one full dir scan per date per
        # _FRESH_VALIDATE_SECONDS — evaluate_market re-enters _snapshot
        # ~20× per row, and an unthrottled scan on every entry is thousands
        # of stat() calls per row. A mid-request pipeline save becomes
        # visible within ≤2 s of the next evaluation.
        now = time.monotonic()
        if now - _SNAP_FRESH_AT.get(date, 0.0) >= _FRESH_VALIDATE_SECONDS:
            _SNAP_FRESH_AT[date] = now
            meta = _SNAP_META.get(date)
            # meta None → a test/ops-injected memo (never built from disk):
            # trusted as-is. Real builds always record a fingerprint.
            if meta is not None and not _snapshot_is_fresh(meta):
                _SNAPSHOTS.pop(date, None)
                _SNAP_META.pop(date, None)
                snap = None
        if snap is not None:
            return snap

    # Capture disk mtimes BEFORE reading: if the pipeline saves while this
    # build runs, the dir mtime no longer matches the recorded one and the
    # next call rebuilds — a mid-build change can never be memoised as fresh.
    meta0 = _record_snapshot_meta()
    # WIN side rows: win_raw and win_forecast share the win_forecast engine's
    # row shape (same producer) and BOTH store parity_score signed per side —
    # so a row for the selected team is the row whose team_name matches.
    # win_apex rows are APPENDED to the registry (not the side rows): when a
    # pipeline run produced apex picks but not the win side (or vice versa),
    # the team-intelligence fixture locator must still resolve the fixture —
    # the report page must never say "no fixture" for a fixture the engines
    # clearly saved. Apex rows carry fixture_id + label (fixture-level).
    #
    # ID NORMALISATION (bug fix): the apex registry check MUST compare the
    # normalised key, otherwise an apex row (fixture_id stored as int) sees
    # "19713004 not in {'19713004': [...]}" and REPLACES the side rows of its
    # own fixture — which is what silently turned Parity/Form into N/A.
    win_side_rows = _rows(_load("win_raw", date)) + _rows(_load("win_forecast", date))
    win_apex_rows = _rows(_load("win_apex", date))
    win_by_id, win_by_name = {}, {}
    for r in win_side_rows:
        fid = _idstr(r.get("fixture_id"))
        if fid:
            win_by_id.setdefault(fid, []).append(r)
        label = _fixture_label(r)
        if label:
            win_by_name.setdefault(_norm(label), []).append(r)
    for r in win_apex_rows:
        fid = _idstr(r.get("fixture_id"))
        label = _fixture_label(r)
        if not fid or not label:
            continue
        if fid not in win_by_id:  # side rows take priority (they carry team_name)
            win_by_id[fid] = [r]
        key = _norm(label)
        if key not in win_by_name:
            win_by_name[key] = [r]

    u2s_rows = _rows(_load("u2s_psychology", date))
    corner_rows = _rows(_load("corners_aggregator", date))
    dmf = _load_dna_factors(date)
    # DNA v2 engine output: per-fixture clash rows carrying the engine's OWN
    # market verdicts (market_signals) for fixtures it covered that day.
    dna_v2 = _load_heads("dna_v2", date)
    dna_clash_rows = []
    if isinstance(dna_v2, dict):
        dna_clash_rows = [r for r in (dna_v2.get("fixture_clashes") or [])
                          if isinstance(r, dict)]

    # Composite files can be served nested (engine assembly) or flat (cache
    # rewrite) depending on pipeline timing. Row-shape filters keep each
    # checklist joined to the CORRECT market head in both layouts:
    #   draw   head = rows carrying the draw engine's Monte-Carlo fields;
    #   unders u25 = rows WITHOUT the u35 tier marker.
    draw_rows = [r for r in _head0(_load("draw", date))
                 if "mc_draw_prob" in r or "composite_draw_score" in r]
    unders_rows = [r for r in _head0(_load("unders", date))
                   if "u35_tier" not in r]

    # O2.5 forecast rows (Engine/over25_forecast.py) — the source of the
    # O2.5 engine's own council gates, joined by fixture for apex picks.
    o25f_rows = _rows(_load("over25_forecast", date))
    # gg_o15 composite heads: head0 = GG BTTS rows (sig1_mc_btts..sig5),
    # head1 = Over 1.5 rows (sig1_combined_lambda..sig5_fatigue_penalty).
    gg_o15_heads = _load_heads("gg_o15", date)
    ggc_rows = _head_n(gg_o15_heads, 0)
    o15c_rows = _head_n(gg_o15_heads, 1)
    # GG supreme rows themselves — the gg branch's psychology verdict lives
    # on the supreme row's own Psych_Score field (not on the composite head).
    gg_rows = _rows(_load("gg_supreme", date))
    # O1.5 stage-3 / psychology rows — the O1.5 card's probability source
    # (Poisson%) and its H2H_Record kill-switch sample (parsed scores).
    o15s_rows = _rows(_load("over15_stage3", date))
    o15p_rows = _rows(_load("over15_psychology", date))

    # Corner pipeline rows for the WIN Corners rule chain: stage2 (refiner),
    # psychology and catalyst share the same fixture universe and the same
    # per-fixture id (fixture_name = the day's label). Stage1 (miner) carries
    # the per-team lastN corner averages + the engine's own team_more_corners
    # verdict, but only for the qualified subset. All are read here (disk
    # only) and merged per fixture below.
    stage2_rows = _rows(_load("corners_stage2", date))
    cpsych_rows = _rows(_load("corners_psychology", date))
    ccat_rows = _rows(_load("corners_catalyst", date))
    stage1_rows = _rows(_load("corners_stage1", date))

    # ── ID → CANONICAL LABEL REGISTRY ────────────────────────────────────────
    # Built from the engines that store BOTH the fixture id and a real
    # 'home vs away' label; the id-bearing majority wins, apex rows are added
    # LAST (they can store the fixture with its sides swapped), so a fixture
    # whose only saved row is an apex row still gets a label.
    underdog_base_rows = _rows(_load("underdog_base", date))
    underdog_audit_rows = _rows(_load("underdog_audit", date))
    fhvi_rows = _rows(_load("fhvi", date))
    shvi_rows = _rows(_load("shvi", date))
    label_cand = {}

    def _add_label(r):
        fid = _idstr(r.get("fixture_id"))
        label = _fixture_label(r)
        if not fid or not label:
            return
        bucket = label_cand.setdefault(fid, {})
        key = _norm(label)
        bucket[key] = (label, bucket.get(key, ("", 0))[1] + 1)

    for rows in (win_side_rows, underdog_base_rows, underdog_audit_rows,
                 draw_rows, unders_rows, o25f_rows, ggc_rows, o15c_rows,
                 gg_rows, dna_clash_rows, fhvi_rows, shvi_rows):
        for r in rows or []:
            _add_label(r)
    for fid, entry in (dmf or {}).items():
        if isinstance(entry, dict) and _fixture_label(entry):
            _add_label(dict(entry, fixture_id=fid))
    for r in win_apex_rows:
        _add_label(r)
    label_by_id = {
        fid: max(bucket.items(), key=lambda kv: kv[1][1])[1][0]
        for fid, bucket in label_cand.items() if bucket
    }

    dna_factors_by_id, dna_factors_by_name = {}, {}
    dna_draw_by_id, dna_draw_by_name = {}, {}
    if isinstance(dmf, dict):
        for fid, entry in dmf.items():
            if not isinstance(entry, dict):
                continue
            markets = entry.get("markets") or {}
            fkey = _idstr(fid)
            dna_factors_by_id[fkey] = markets
            label = entry.get("fixture")
            if label:
                key = _norm(label)
                dna_factors_by_name.setdefault(key, markets)
                dna_draw_by_id[fkey] = markets.get("draw") or {}
                dna_draw_by_name.setdefault(key, markets.get("draw") or {})

    snap = {
        # the date this snapshot was read from (every check reports it)
        "date": date,
        # fixture_id → canonical 'home vs away' label for this date
        "label_by_id": label_by_id,
        # per-side WIN rows
        "win_by_id": win_by_id,
        "win_by_name": win_by_name,
        # legacy name-keyed sources (id-less engines, existing convention)
        "wps_by_id": {}, "wps_by_name": _name_index(_rows(_load("win_psychology", date))),
        "gps_by_id": {}, "gps_by_name": _name_index(_rows(_load("gg_psychology", date))),
        "ops_by_id": {}, "ops_by_name": _name_index(_rows(_load("over25_psychology", date))),
        "u2s_by_id": {}, "u2s_by_name": _name_index(u2s_rows),
        "sot_by_id": {}, "sot_by_name": _name_index(_rows(_load("sot", date))),
        "fhvi_by_id": {}, "fhvi_by_name": _name_index(fhvi_rows),
        "shvi_by_id": {}, "shvi_by_name": _name_index(shvi_rows),
        "cagg_by_id": {}, "cagg_by_name": _name_index(corner_rows),
        # id-keyed sources (id may be str or int on disk — normalised to str)
        "ud_by_id": _id_index(underdog_base_rows),
        "ud_by_name": _name_index(underdog_base_rows),
        "uda_by_id": _id_index(underdog_audit_rows),
        "uda_by_name": _name_index(underdog_audit_rows),
        # Market-filtered composite rows (see shape filters above)
        "draw_by_id": _id_index(draw_rows),
        "draw_by_name": _name_index(draw_rows),
        "un_by_id": _id_index(unders_rows),
        "un_by_name": _name_index(unders_rows),
        # DNA v2 market factors (data/dna_v2_market_factors.json — disk-only)
        "dna_by_id": dna_factors_by_id,
        "dna_by_name": dna_factors_by_name,
        "dna_draw_by_id": dna_draw_by_id,
        "dna_draw_by_name": dna_draw_by_name,
        # per-team DNA profiles (Market_Power_Scores.Goal_Intent) — the WIN
        # Goal Intent fallback for fixtures without a market-factor entry
        "dna_prof_by_name": _dna_profiles(date),
        # O2.5 engine forecast rows + GG/O1.5 composite heads
        "o25f_by_id": _id_index(o25f_rows),
        "o25f_by_name": _name_index(o25f_rows),
        "ggc_by_id": _id_index(ggc_rows),
        "ggc_by_name": _name_index(ggc_rows),
        "o15c_by_id": _id_index(o15c_rows),
        "o15c_by_name": _name_index(o15c_rows),
        # GG supreme rows themselves (the gg branch's psychology verdict
        # lives on the supreme row's own Psych_Score field)
        "gsup_by_id": _id_index(gg_rows),
        "gsup_by_name": _name_index(gg_rows),
        # O1.5 stage-3 / psychology rows (name-keyed: they carry Match /
        # Fixture labels but no fixture_id)
        "o15s_by_id": {}, "o15s_by_name": _name_index(o15s_rows),
        "o15p_by_id": {}, "o15p_by_name": _name_index(o15p_rows),
        # DNA engine's own per-fixture clash verdicts
        "dna_clash_by_id": _id_index(dna_clash_rows),
        "dna_clash_by_name": _name_index(dna_clash_rows),
        # corner engines per fixture (stage2/psychology/catalyst keyed by
        # fixture_id for the WIN Corners rule chain)
        "c2_by_id": _corner2_by_id(stage2_rows, cpsych_rows, ccat_rows),
        "c1_by_id": _id_index(stage1_rows),
        # raw per-fixture underdog identity rows (from the U2S feed itself)
        "u2s_rows": u2s_rows,
        "corner_rows": corner_rows,
    }
    _SNAPSHOTS[date] = snap
    _SNAP_META[date] = meta0
    _SNAP_FRESH_AT[date] = time.monotonic()
    _trim_window_cache(date)
    return snap
# ══════════════════════════════════════════════════════════════════════════════
# CROSS-DAY SOURCE RESOLUTION — the requested date is tried FIRST; only a
# genuine miss looks at the window (see the module docstring). Every helper
# returns the date that supplied the row so the check can report it.
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_any(date, prefix, fid, fxn):
    """(row, source_date) for one source across the date window, or (None, "").

    Cross-fixture guard: when a neighbouring date knows the SAME label under a
    DIFFERENT fixture id (two-legged ties, double-headers), that date is
    skipped — its row belongs to another fixture, not to this pick."""
    fid_s = _idstr(fid)
    for d in _window_dates(date):
        snap = _snapshot(d)
        if d != date and fid_s:
            known = snap.get("label_by_id") or {}
            if fxn:
                mapped = _label_fixture_id(snap, fxn)
                if mapped and mapped != fid_s:
                    continue
            elif known:
                continue
        row = _resolve(snap, prefix, fid_s, fxn)
        if row is not None:
            return row, d
    return None, ""


def _label_fixture_id(snap, label):
    """The fixture id a date's own id-bearing engines give a label (either
    orientation), or "" when that date has no such fixture."""
    key = _norm(label)
    if not key:
        return ""
    rev = _norm(_reverse_label(label))
    for fid, lab in (snap.get("label_by_id") or {}).items():
        k = _norm(lab)
        if k == key or (rev and k == rev):
            return fid
    return ""


def _canonical_label_any(date, fid, fxn):
    """(canonical label, source_date) for a fixture across the source window —
    the label that date's id-bearing engines agree on. Falls back to the
    calling row's own label when no date knows the fixture id."""
    fid_s = _idstr(fid)
    if fid_s:
        for d in _window_dates(date):
            lab = (_snapshot(d).get("label_by_id") or {}).get(fid_s, "")
            if lab:
                return lab, d
    return (fxn or ""), date


def _win_rows_any(date, fid, fxn):
    """(side_rows, source_date) for a fixture's WIN side rows. The canonical
    label of the supplying date is used when the calling row stored the
    fixture with its sides swapped."""
    fid_s = _idstr(fid)
    for d in _window_dates(date):
        snap = _snapshot(d)
        rows = []
        if fid_s:
            rows = list((snap.get("win_by_id") or {}).get(fid_s, []))
        if not rows and fxn:
            label = ""
            if fid_s:
                label = (snap.get("label_by_id") or {}).get(fid_s, "")
            if not label:
                label = fxn
            for key in (_norm(label), _norm(_reverse_label(label)), _norm(fxn)):
                if not key:
                    continue
                rows = list((snap.get("win_by_name") or {}).get(key, []))
                if rows:
                    break
        side_rows = [r for r in rows if r.get("team_name")]
        if side_rows:
            return side_rows, d
    return [], ""


def _win_side_trio(date, fid, fxn, team):
    """(selected row, opponent row, source_date) for one team's WIN side rows.

    The pair is the engine's own output shape: Engine/win_forecast.py always
    writes BOTH sides of a fixture, so the opponent's own row (its
    last_5_wins_overall / parity_score) is reachable from the same source."""
    rows, d = _win_rows_any(date, fid, fxn)
    if not rows:
        return None, None, ""
    t = _norm(team or "")
    if not t:
        return rows[0], None, d
    mine = next((r for r in rows if _norm(r.get("team_name") or "") == t), None)
    theirs = next((r for r in rows if _norm(r.get("team_name") or "") != t), None)
    return mine, theirs, d


def _win_side_row_any(date, fid, fxn, team):
    row, _opp, d = _win_side_trio(date, fid, fxn, team)
    return row, d
# ══════════════════════════════════════════════════════════════════════════════
# RULE EVALUATION PRIMITIVES (one pre-existing field/verdict each)
# ══════════════════════════════════════════════════════════════════════════════

def _psych_side(snap, prefix, fid, fxn, side):
    """Psychology signed net score for ONE side of a fixture (PSYCHOLOGY
    engines compute H_Base and A_Base per fixture — the net score is signed
    toward the home or away team, NOT a 0-100 percentage). Fixture-level
    audits (side=None) fall back to the row's OWN psych verdict when the
    side base pair is absent (e.g. gg_psychology rows carry Psych_Score but
    no H_Base/A_Base) — the intelligence EXISTS, so it must not read N/A."""
    row = _resolve(snap, prefix, fid, fxn)
    if not row:
        return NOT_AVAILABLE
    if side in ("home", "away"):
        h, a = _num(row.get("H_Base")), _num(row.get("A_Base"))
        if h is None or a is None:
            return NOT_AVAILABLE
        if side == "home":
            return PASS if (h - a) > 0 else FAIL
        return PASS if (a - h) > 0 else FAIL
    # Market/fixture-level row (no side): its own signed audit score is the
    # verdict. Coerce — psych engines store numeric strings ("+162").
    ps = _num(row.get("Psych_Score"))
    if ps is None:
        ps = _num(row.get("Audit_Score"))
    if ps is None:
        return NOT_AVAILABLE
    return PASS if ps > INTELLIGENT_PASS_RULES["PSYCHOLOGY_NET_SCORE_PASS"] else FAIL


def _dna_factors(snap, fid, fxn, market):
    """Factor list of one existing DNA v2 market (win/gg/over25/over15/
    unders/draw/corners) for this fixture, from the market-factors breakdown
    produced by CORE/dna_v2_market_factors.py off Market_Power_Scores."""
    markets = _resolve(snap, "dna", fid, fxn)
    if not markets:
        return None
    mv = markets.get(market) or {}
    factors = mv.get("factors") or []
    return factors or None


def _dna_factor(factors, name):
    return next((f for f in factors if f.get("name") == name), None)


def _win_res(result, value=None, threshold=None, source="", field="", mapping=""):
    """One WIN check's payload — the rule result plus its provenance
    (source engine + date, source field, team/side mapping) so the report can
    show exactly where every value came from."""
    return {"result": result, "value": value, "threshold": threshold,
            "source": source, "field": field, "mapping": mapping}


def _win_goal_intent_check(date, fid, fxn, target):
    """WIN Goal Intent — the predicted team's existing DNA Goal Intent (0-100)
    must beat its opponent's. Preferred source: the fixture's own market-factor
    breakdown (CORE/dna_v2_market_factors.py, over25 → "Goal Intent"
    home_value/away_value). Fallback for fixtures that pass did not cover: the
    same engine's per-team profiles (Market_Power_Scores.Goal_Intent) for both
    named sides — identical field and scale, so no normalisation is added."""
    canon, _cd = _canonical_label_any(date, fid, fxn)
    label = canon or fxn or ""
    home, away = _split_fixture(label)
    t_n, h_n, a_n = _norm(target), _norm(home), _norm(away)
    if not t_n or t_n not in (h_n, a_n):
        return _win_res(NOT_AVAILABLE,
                        source="dna_market_factors / dna profiles",
                        field="Goal Intent",
                        mapping=f"{target} = neither side of '{label}'")
    markets, d = _resolve_any(date, "dna", fid, label)
    goal = _dna_factor((markets or {}).get("over25", {}).get("factors") or [],
                       "Goal Intent")
    if goal:
        tv = _num(goal.get("home_value") if t_n == h_n else goal.get("away_value"))
        ov = _num(goal.get("away_value") if t_n == h_n else goal.get("home_value"))
        if tv is not None and ov is not None:
            return _win_res(PASS if tv > ov else FAIL,
                            value={"team": tv, "opp": ov},
                            threshold="team Goal Intent > opponent (0-100)",
                            source=f"dna_market_factors @ {d}",
                            field="Goal Intent (home_value/away_value)",
                            mapping=f"{target} = {'home' if t_n == h_n else 'away'}")
    prof = _snapshot(d or date).get("dna_prof_by_name") or {}
    opp_name = away if t_n == h_n else home
    pt, po = prof.get(t_n), prof.get(_norm(opp_name))
    if pt and po:
        tv = _num((pt.get("Market_Power_Scores") or {}).get("Goal_Intent"))
        ov = _num((po.get("Market_Power_Scores") or {}).get("Goal_Intent"))
        if tv is not None and ov is not None:
            return _win_res(PASS if tv > ov else FAIL,
                            value={"team": tv, "opp": ov},
                            threshold="team Goal Intent > opponent (0-100)",
                            source=f"dna profiles @ {d or date}",
                            field="Market_Power_Scores.Goal_Intent",
                            mapping=f"{target} vs {opp_name}")
    return _win_res(NOT_AVAILABLE,
                    source="dna_market_factors / dna profiles",
                    field="Goal Intent",
                    mapping=f"{target} = no DNA Goal Intent in the window")


def _win_sot_check(date, fid, fxn, target):
    """WIN SOT — the predicted team's OWN side SOT expectancy from the U2S
    engine (the WIN page's "SOT Expectancy (Dog)/(Fav)" columns:
    Dog_Venue_SOT / Fav_Venue_SOT), evaluated with the engine's own Tier-A1
    comparison (a side's expectancy must be strictly greater; a tie awards
    nothing). The row's Underdog column names the dog, so the predicted team's
    side is read, never re-derived from odds."""
    row, d = _resolve_any(date, "u2s", fid, fxn)
    if not row:
        return _win_res(NOT_AVAILABLE, source="u2s_psychology",
                        field="Dog_Venue_SOT / Fav_Venue_SOT",
                        mapping=f"{target} = no U2S row in the source window")
    dog = str(row.get("Underdog") or "")
    t_n, dog_n = _norm(target), _norm(dog)
    canon, _cd = _canonical_label_any(date, fid, fxn)
    home, away = _split_fixture(canon or fxn or "")
    if not t_n or t_n not in (_norm(home), _norm(away)):
        return _win_res(NOT_AVAILABLE, source=f"u2s_psychology @ {d}",
                        field="Dog_Venue_SOT / Fav_Venue_SOT",
                        mapping=f"{target} = not a side of '{canon or fxn}'")
    side = "dog" if t_n == dog_n else "fav"
    t_field = "Dog_Venue_SOT" if side == "dog" else "Fav_Venue_SOT"
    o_field = "Fav_Venue_SOT" if side == "dog" else "Dog_Venue_SOT"
    tv, ov = _num(row.get(t_field)), _num(row.get(o_field))
    if tv is None or ov is None:
        return _win_res(NOT_AVAILABLE, source=f"u2s_psychology @ {d}",
                        field=t_field, mapping=f"{target} = {side.upper()}")
    return _win_res(PASS if tv > ov else FAIL,
                    value={"side": side, "team_sot": tv, "opp_sot": ov},
                    threshold="team SOT expectancy > opponent (U2S Tier A1)",
                    source=f"u2s_psychology @ {d}",
                    field=f"{t_field} vs {o_field}",
                    mapping=f"{target} = {side.upper()} (U2S Underdog={dog})")


def _dna_clash_signal(snap, fid, fxn, market_signals_key):
    """The DNA engine's OWN per-fixture verdict (CORE/dna_engine_v2.py
    `market_signals` on the fixture clash row): Over_Under / GG_NoGG /
    Corners. Returns (verdict_string, clash_row) or (None, None)."""
    clash = _resolve(snap, "dna_clash", fid, fxn)
    if not clash:
        return None, None
    ms = clash.get("market_signals") or {}
    v = ms.get(market_signals_key)
    if v is None:
        return None, None
    return str(v).strip(), clash


def _dna_over_signal(snap, fid, fxn, market="over25"):
    """The DNA engine's own Over/Under verdict for this fixture.
    PRIMARY source: the engine's clash `market_signals.Over_Under`
    (STRONG OVER / LEAN OVER / LEAN UNDER / NEUTRAL) — a verbatim verdict,
    no arithmetic at all.
    FALLBACK (fixture absent from the clash set): the engine's documented
    aggregation of its own Market_Power_Scores — combined_goal_intent and
    combined_box_dominance are the two sides' average, and the engine's own
    LEAN OVER line is `box > 55 or intent > 55` (dna_engine_v2 L576-593).
    Returns (result, value).
    """
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "Over_Under")
    if verdict is not None:
        up = verdict.upper()
        is_over = up in ("STRONG OVER", "LEAN OVER")
        value = {"dna_signal": verdict}
        if clash:
            value["combined_goal_intent"] = clash.get("combined_goal_intent")
            value["combined_box_dominance"] = clash.get("combined_box_dominance")
        return (PASS if is_over else FAIL), value

    factors = _dna_factors(snap, fid, fxn, market)
    if not factors:
        return NOT_AVAILABLE, None
    gi = _dna_factor(factors, "Goal Intent")
    bd = _dna_factor(factors, "Box Dominance")
    if not gi and not bd:
        return NOT_AVAILABLE, None

    def _avg(f):
        if not f:
            return None
        hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
        if hv is None and av is None:
            return None
        return ((hv or 0) + (av or 0)) / 2.0

    intent_avg, box_avg = _avg(gi), _avg(bd)
    if intent_avg is None and box_avg is None:
        return NOT_AVAILABLE, None
    cut = INTELLIGENT_PASS_RULES["DNA_OVER_LEAN_CUT"]
    is_over = (box_avg is not None and box_avg > cut) or \
              (intent_avg is not None and intent_avg > cut)
    signal = ("STRONG OVER" if (box_avg or 0) > 70 and (intent_avg or 0) > 65
              else "LEAN OVER" if is_over else "NOT OVER")
    value = {"combined_goal_intent": None if intent_avg is None else round(intent_avg, 1),
             "combined_box_dominance": None if box_avg is None else round(box_avg, 1),
             "dna_signal": signal}
    return (PASS if is_over else FAIL), value


def _dna_gg_signal(snap, fid, fxn):
    """The DNA engine's own GG/No-GG verdict (market_signals.GG_NoGG)."""
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "GG_NoGG")
    if verdict is None:
        return NOT_AVAILABLE, None
    up = verdict.upper()
    value = {"dna_signal": verdict}
    if clash:
        value["combined_goal_intent"] = clash.get("combined_goal_intent")
        value["combined_box_dominance"] = clash.get("combined_box_dominance")
    return (PASS if up in ("STRONG GG", "LEAN GG") else FAIL), value


def _dna_corners_signal(snap, fid, fxn):
    """The DNA engine's own corners verdict (market_signals.Corners)."""
    verdict, clash = _dna_clash_signal(snap, fid, fxn, "Corners")
    if verdict is None:
        return NOT_AVAILABLE, None
    value = {"dna_signal": verdict}
    if clash:
        value["combined_box_dominance"] = clash.get("combined_box_dominance")
        value["overall_structural_edge"] = clash.get("overall_structural_edge")
    return (PASS if verdict.upper() == "HIGH CORNERS" else FAIL), value


def _dna_side_factor_check(snap, fid, fxn, market, factor_name, home_cut, away_cut):
    """Generic per-side DNA factor gate reusing a producing engine's own
    thresholds (home_cut / away_cut). Returns (result, value)."""
    factors = _dna_factors(snap, fid, fxn, market)
    f = _dna_factor(factors or [], factor_name)
    if not f:
        return NOT_AVAILABLE, None
    hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
    if hv is None or av is None:
        return NOT_AVAILABLE, None
    return (PASS if hv > home_cut and av > away_cut else FAIL), \
        {"home_value": f.get("home_value"), "away_value": f.get("away_value")}


def _dna_corner_power(snap, fid, fxn):
    """Reuses the DNA engine's HIGH CORNERS gate (L606-607): either side's
    Corner_Power > 70. Returns (result, value)."""
    factors = _dna_factors(snap, fid, fxn, "corners")
    f = _dna_factor(factors or [], "Corner Power")
    if not f:
        return NOT_AVAILABLE, None
    hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
    if hv is None and av is None:
        return NOT_AVAILABLE, None
    cut = INTELLIGENT_PASS_RULES["DNA_HIGH_CORNERS_CUT"]
    return (PASS if (hv or 0) > cut or (av or 0) > cut else FAIL), \
        {"home_value": f.get("home_value"), "away_value": f.get("away_value")}


def _gg_unified_checks(snap, row, fid, fxn, date):
    """The ONE GG card — every GG table (supreme / precision / O1.5
    composite) runs these same 4 checks (user rules 2026-09-23):
      1 Both Teams Psych    — BOTH teams' per-team Spears % > 65%
                         (gg_supreme / gg_psychology "Spears: H:X%|A:Y%").
                         The single Psych_Score is NOT used.
      2 Both Teams Goal Intent — BOTH teams' Goal Intent > 60%
                         (DNA goal intent from win pack, dna_by_id[gg factors]).
      3 Both Teams Last-5 Goal — combined last-5 goals > 8
                         (over25_forecast.combined_gs_last_5).
      4 Both Teams Conceded Last-3 — both teams conceded > 0
                         (win_forecast opp_last_5_conceded_raw, both rows).
    Every check carries source/field provenance."""
    rules = INTELLIGENT_PASS_RULES
    checks = []

    # 1) BOTH teams' psych > 65% — parse the per-team Spears field:
    #    gg_supreme / gg_psychology row field "Spears: \"H:73.83%|A:92.24%\"".
    spears_thr = "both teams > %d%% (gg Spears H:X%%|A:Y%%)" % rules["GG_BOTH_TEAMS_PSYCH_MIN"]
    spears_chain = [("calling row", row.get("Spears"))]
    gsup_s, d1s = _resolve_any(date, "gsup", fid, fxn)
    if gsup_s:
        spears_chain.append(("gg_supreme @ %s" % d1s, gsup_s.get("Spears")))
    gps_s, d2s = _resolve_any(date, "gps", fid, fxn)
    if gps_s:
        spears_chain.append(("gg_psychology @ %s" % d2s, gps_s.get("Spears")))
    spears_res, spears_val, spears_src, spears_field = None, None, "", ""
    for src, raw in spears_chain:
        h, a = _parse_spears(raw)
        if h is not None and a is not None:
            spears_src, spears_field = src, "Spears (H:X%|A:Y%)"
            spears_val = {"home_spear": h, "away_spear": a}
            if h > rules["GG_BOTH_TEAMS_PSYCH_MIN"] and a > rules["GG_BOTH_TEAMS_PSYCH_MIN"]:
                spears_res = PASS
                spears_map = f"home {h}% > 65 AND away {a}% > 65"
            else:
                spears_res = FAIL
                spears_map = f"home {h}% > 65 AND away {a}% > 65"
            break
    if spears_res is None:
        checks.append({"name": "Both Teams Psych", "result": NOT_AVAILABLE,
                       "value": None, "threshold": spears_thr,
                       "source": "gg_supreme / gg_psychology", "field": "Spears",
                       "mapping": "no valid Spears field found"})
    else:
        checks.append({"name": "Both Teams Psych", "result": spears_res,
                       "value": spears_val, "threshold": spears_thr,
                       "source": spears_src, "field": spears_field, "mapping": spears_map})

    # 3) Both teams' goal intent > 60% (DNA goal intent from win pack).
    gi_factors = _dna_factors(snap, fid, fxn, "gg")
    gi_factor = _dna_factor(gi_factors or [], "Goal Intent")
    if not gi_factor:
        checks.append({"name": "Both Teams Goal Intent", "result": NOT_AVAILABLE,
                       "value": None, "threshold": "both > %d (DNA Goal Intent)" % rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"],
                       "source": "dna_by_id[gg factors]", "field": "Goal Intent",
                       "mapping": "no Goal Intent factor found"})
    else:
        gi_h, gi_a = _num(gi_factor.get("home_value")), _num(gi_factor.get("away_value"))
        gi_val = {"home_value": gi_factor.get("home_value"), "away_value": gi_factor.get("away_value")}
        if gi_h is None or gi_a is None:
            checks.append({"name": "Both Teams Goal Intent", "result": NOT_AVAILABLE,
                           "value": gi_val, "threshold": "both > %d (DNA Goal Intent)" % rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"],
                           "source": "dna_by_id[gg factors]", "field": "Goal Intent",
                           "mapping": "missing home or away goal intent"})
        elif gi_h > rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"] and gi_a > rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"]:
            checks.append({"name": "Both Teams Goal Intent", "result": PASS,
                           "value": gi_val,
                           "threshold": "both > %d (DNA Goal Intent)" % rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"],
                           "source": "dna_by_id[gg factors]", "field": "Goal Intent",
                           "mapping": f"home {gi_h} > 60 AND away {gi_a} > 60"})
        else:
            checks.append({"name": "Both Teams Goal Intent", "result": FAIL,
                           "value": gi_val,
                           "threshold": "both > %d (DNA Goal Intent)" % rules["GG_BOTH_TEAMS_GOAL_INTENT_MIN"],
                           "source": "dna_by_id[gg factors]", "field": "Goal Intent",
                           "mapping": f"home {gi_h} > 60 AND away {gi_a} > 60"})


    # 3) Both teams combine goal in last 5 > 8 (over25_forecast).
    o25r4, od4 = _resolve_any(date, "o25f", fid, fxn)
    if not o25r4:
        checks.append({"name": "Both Teams Last-5 Goal", "result": NOT_AVAILABLE,
                       "value": None, "threshold": "combined_gs_last_5 > %d (over25_forecast)" % rules["GG_BOTH_TEAMS_LAST5_GOAL_MIN"],
                       "source": "over25_forecast", "field": "combined_gs_last_5",
                       "mapping": "no over25_forecast row in source window"})
    else:
        gv4 = _num(o25r4.get("combined_gs_last_5"))
        gv4_val = {"combined_gs_last_5": o25r4.get("combined_gs_last_5")}
        if gv4 is None:
            checks.append({"name": "Both Teams Last-5 Goal", "result": NOT_AVAILABLE,
                           "value": gv4_val, "threshold": "combined_gs_last_5 > %d (over25_forecast)" % rules["GG_BOTH_TEAMS_LAST5_GOAL_MIN"],
                           "source": "over25_forecast @ %s" % od4, "field": "combined_gs_last_5",
                           "mapping": "missing combined_gs_last_5 value"})
        elif gv4 > rules["GG_BOTH_TEAMS_LAST5_GOAL_MIN"]:
            checks.append({"name": "Both Teams Last-5 Goal", "result": PASS,
                           "value": gv4_val,
                           "threshold": "combined_gs_last_5 > %d (over25_forecast)" % rules["GG_BOTH_TEAMS_LAST5_GOAL_MIN"],
                           "source": "over25_forecast @ %s" % od4, "field": "combined_gs_last_5",
                           "mapping": f"combined {gv4} > 8"})
        else:
            checks.append({"name": "Both Teams Last-5 Goal", "result": FAIL,
                           "value": gv4_val,
                           "threshold": "combined_gs_last_5 > %d (over25_forecast)" % rules["GG_BOTH_TEAMS_LAST5_GOAL_MIN"],
                           "source": "over25_forecast @ %s" % od4, "field": "combined_gs_last_5",
                           "mapping": f"combined {gv4} > 8"})

    # 4) Both Teams Conceded Last-3 — win_forecast side rows. Each row's
    #    opp_last_5_conceded_raw is the OTHER team's conceded count (the
    #    home row's value belongs to the away team), so the pair is
    #    re-attributed before labelling; both > 0 → PASS.
    wrows = _resolve(snap, "win", fid, fxn) or []
    if isinstance(wrows, dict):
        wrows = [wrows]
    h_row = next((r for r in wrows
                  if str(r.get("side") or "").lower() == "home"), None)
    a_row = next((r for r in wrows
                  if str(r.get("side") or "").lower() == "away"), None)
    if (not h_row or not a_row) and fxn:
        h_name, a_name = _split_fixture(fxn)
        h_n, a_n = _norm(h_name), _norm(a_name)
        if h_n and not h_row:
            h_row = next((r for r in wrows
                          if _norm(r.get("team_name")) == h_n), None)
        if a_n and not a_row:
            a_row = next((r for r in wrows
                          if _norm(r.get("team_name")) == a_n), None)
    if not h_row or not a_row:
        checks.append({"name": "Both Teams Conceded Last-3", "result": NOT_AVAILABLE,
                       "value": None, "threshold": "both teams conceded last 5 (estimate last 3) > 0",
                       "source": "win_forecast (win_by_id)", "field": "opp_last_5_conceded_raw",
                       "mapping": "need both home and away rows; not both found"})
    else:
        home_c = _num(a_row.get("opp_last_5_conceded_raw"))
        away_c = _num(h_row.get("opp_last_5_conceded_raw"))
        cv = {"home_team_conceded": home_c, "away_team_conceded": away_c}
        if home_c is None or away_c is None:
            checks.append({"name": "Both Teams Conceded Last-3", "result": NOT_AVAILABLE,
                           "value": cv, "threshold": "both teams conceded last 5 (estimate last 3) > 0",
                           "source": "win_forecast @ %s" % date,
                           "field": "opp_last_5_conceded_raw",
                           "mapping": "missing conceded value for one or both teams"})
        elif home_c > 0 and away_c > 0:
            checks.append({"name": "Both Teams Conceded Last-3", "result": PASS,
                           "value": cv,
                           "threshold": "both teams conceded last 5 (estimate last 3) > 0",
                           "source": "win_forecast @ %s" % date,
                           "field": "opp_last_5_conceded_raw",
                           "mapping": f"home conceded {home_c}, away conceded {away_c} — both > 0"})
        else:
            checks.append({"name": "Both Teams Conceded Last-3", "result": FAIL,
                           "value": cv,
                           "threshold": "both teams conceded last 5 (estimate last 3) > 0",
                           "source": "win_forecast @ %s" % date,
                           "field": "opp_last_5_conceded_raw",
                           "mapping": f"home conceded {home_c}, away conceded {away_c} — both must be > 0"})
    return checks


def _parse_spears(spears_str):
    """Parse "H:73.83%|A:92.24%" into (home_pct, away_pct) or (None, None)."""
    if not spears_str:
        return None, None
    m = re.search(r"H\s*:\s*([\d.]+)%\s*\|\s*A\s*:\s*([\d.]+)%", str(spears_str))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def _u2s_row_for(snap, fid, fxn, row_id, row_fixture):
    """The fixture's U2S psychology row + its named underdog team. The U2S
    feed itself is the identity source (its 'Underdog' field names the dog) —
    no cross-file team guessing."""
    row = _resolve(snap, "u2s", row_id, row_fixture or fxn)
    if not row:
        return None, None
    return row, row.get("Underdog")


def _dna_parity_eval(snap, fid, fxn):
    """DRAW DNA parity: |home_count - away_count| over the existing draw
    market factor counts. 0/1 → PASS, anything else → FAIL (user rule)."""
    mk = _resolve(snap, "dna_draw", fid, fxn)
    if not mk:
        return NOT_AVAILABLE
    h, a = _num(mk.get("home_count")), _num(mk.get("away_count"))
    if h is None or a is None:
        return NOT_AVAILABLE
    return PASS if int(abs(h - a)) in INTELLIGENT_PASS_RULES["DRAW_DNA_PARITY_PASS_VALUES"] else FAIL


def _win_side_row(snap, fid, fxn, team):
    """The WIN side row for the selected team (parity_score is signed per
    side by the producer)."""
    fid = str(fid) if fid not in (None, "") else ""
    if fid:
        for r in (snap.get("win_by_id") or {}).get(fid, []):
            if _norm(r.get("team_name") or "") == _norm(team or ""):
                return r
    fx_key = _norm(fxn or "")
    for r in (snap.get("win_by_name") or {}).get(fx_key, []):
        if _norm(r.get("team_name") or "") == _norm(team or ""):
            return r
    return None


def _win_parity_eval(date, fid, fxn, team, src_row=None):
    """WIN Parity +10 — the selected team's OWN row already carries its signed
    advantage vs this opponent (Engine/win_forecast.py stores
    parity_diff if side==home else -parity_diff). PASS = >= +10.
    When the calling row itself is that side row (win_forecast/win_raw rows
    are), its own value is authoritative and the join is skipped — otherwise
    the fixture's side rows are resolved across the source window."""
    v = _num(src_row.get("parity_score")) if isinstance(src_row, dict) else None
    if v is not None:
        return _win_res(PASS if v >= INTELLIGENT_PASS_RULES["WIN_PARITY_THRESHOLD"] else FAIL,
                        value=v, threshold=">= +10",
                        source="calling row", field="parity_score",
                        mapping=f"{team} = the row's own side")
    r, d = _win_side_row_any(date, fid, fxn, team)
    if not r:
        return _win_res(NOT_AVAILABLE, threshold=">= +10",
                        source="win_raw/win_forecast", field="parity_score",
                        mapping=f"{team} = no saved side row in the window")
    v = _num(r.get("parity_score"))
    if v is None:
        return _win_res(NOT_AVAILABLE, threshold=">= +10",
                        source=f"win_raw/win_forecast @ {d}", field="parity_score")
    return _win_res(PASS if v >= INTELLIGENT_PASS_RULES["WIN_PARITY_THRESHOLD"] else FAIL,
                    value=v, threshold=">= +10",
                    source=f"win_raw/win_forecast @ {d}", field="parity_score",
                    mapping=f"{team} = {r.get('side') or 'selected'} side row")


def _win_form_eval(date, fid, fxn, team, src_row=None):
    """WIN Form — ONE check, THREE legs: the predicted team must have (a) more
    venue goals, (b) more venue wins, and (c) less conceded at its venue than
    the opponent (Engine/win_forecast.py + win_raw_engine.py
    last_5_venue_goals_scored / last_5_wins_at_venue /
    last_5_venue_goals_conceded — both sides are always written by the same
    engine, so the opponent's own row carries ITS counters). All three =
    FULL pass; two = HALF; one = LOW — the tier travels on the payload, and
    only a FULL pass earns the count (the check itself stays ONE rule of the
    WIN 8-rule set). Snapshots written before the venue fields existed fall
    back to the saved overall counters for goals/conceded (the venue-wins
    leg has always been saved)."""
    mine, opp, d = _win_side_trio(date, fid, fxn, team)

    def _side_rows():
        rows = []
        if isinstance(mine, dict):
            rows.append(("mine", mine))
        if isinstance(opp, dict):
            rows.append(("opp", opp))
        if isinstance(src_row, dict):
            rows.append(("call", src_row))
        return rows

    def _venue_pair(field, field_opp_fallback_self=None,
                    cross_fallback_self=None, higher=True):
        """(team_val, opp_val, basis) for one leg: exact venue pair first,
        documented fallback second, None when genuinely unavailable."""
        t_s = [r for n, r in _side_rows() if n in ("mine", "call")]
        o_s = [r for n, r in _side_rows() if n in ("opp",)]
        t_d = t_s[0] if t_s else None
        o_d = o_s[0] if o_s else None
        # Primary: the engines' saved venue counters, both sides.
        if t_d is not None and o_d is not None:
            tv, ov = _num(t_d.get(field)), _num(o_d.get(field))
            if tv is not None and ov is not None:
                return tv, ov, "venue"
        # Fallback: saved overall counters (cross-read via the pair, exactly
        # how the old Form rule read the opponent's own row).
        if field_opp_fallback_self is not None and isinstance(mine, dict):
            tv = _num(mine.get(field_opp_fallback_self))
            ov = None
            if opp is not None:
                ov = _num(opp.get(cross_fallback_self or field_opp_fallback_self))
            else:
                ov = _num(mine.get(field_opp_fallback_self.replace(
                    "last_5_", "opp_last_5_")))
            if tv is not None and ov is not None:
                return tv, ov, "overall"
        return None, None, "missing"

    # Leg 1 — venue goals: team v_gs > opponent v_gs.
    tv, ov, b1 = _venue_pair("last_5_venue_goals_scored",
                             "last_5_goals_scored")
    # Leg 2 — venue wins: team venue wins > opponent venue wins.
    wv, wo, _ = _venue_pair("last_5_wins_at_venue")
    if wv is None or wo is None and opp is not None:
        # wins counter is always saved; read the pair explicitly.
        wv = _num(mine.get("last_5_wins_at_venue")) if isinstance(mine, dict) else None
        wo = _num(opp.get("last_5_wins_at_venue")) if isinstance(opp, dict) else None
        if wv is None and isinstance(src_row, dict):
            wv = _num(src_row.get("last_5_wins_at_venue"))
    # Leg 3 — venue conceded: team v_gc < opponent v_gc; overall fallback
    # cross-reads both rows (the opponent's row carries OUR conceded).
    cv, co, b3 = _venue_pair("last_5_venue_goals_conceded")
    if cv is None or co is None:
        my_c = _num(opp.get("opp_last_5_conceded_raw")) \
            if isinstance(opp, dict) else None
        their_c = _num(mine.get("opp_last_5_conceded_raw")) \
            if isinstance(mine, dict) else None
        if my_c is not None and their_c is not None:
            cv, co, b3 = my_c, their_c, "overall"
    src = "win_raw/win_forecast @ %s" % d if d else "win_raw/win_forecast"

    legs, passed = [], 0
    for name, a, b, higher, basis, field in (
            ("goals", tv, ov, True, b1, "last_5_venue_goals_scored"),
            ("wins", wv, wo, True, "venue", "last_5_wins_at_venue"),
            ("conceded", cv, co, False, b3, "last_5_venue_goals_conceded")):
        if a is None or b is None:
            legs.append({"leg": name, "result": NOT_AVAILABLE, "basis": basis,
                         "field": field})
            continue
        ok = (a > b) if higher else (a < b)
        legs.append({"leg": name, "result": PASS if ok else FAIL,
                     "team": a, "opp": b, "basis": basis, "field": field})
        if ok:
            passed += 1
    evaluated = [m for m in legs if m["result"] != NOT_AVAILABLE]
    tier = {3: "FULL", 2: "HALF", 1: "LOW"}.get(passed, "NONE")
    if not evaluated:
        return _win_res(NOT_AVAILABLE,
                        source="win_raw/win_forecast",
                        field="last_5_venue_goals_scored",
                        mapping="%s = no saved side row in the window" % team)
    return _win_res(PASS if passed == 3 else FAIL,
                    value={"legs": legs, "legs_passed": passed,
                           "legs_total": len(evaluated), "tier": tier},
                    threshold="all 3: venue goals >, venue wins >, "
                              "venue conceded < (FULL=3/3, HALF=2/3, LOW=1/3)",
                    source=src,
                    field="last_5_venue_goals_scored / last_5_wins_at_venue / "
                          "last_5_venue_goals_conceded",
                    mapping="%s form trio: %s" % (team, tier))



def _corner_expected_pair(row, target, fxn):
    """(team_exp, opp_exp) — per-team EXPECTED corners for the predicted
    team vs its opponent from one corner-pipeline row. Refiner-stage rows
    carry predicted_corners (total) + diff (signed home-minus-away of that
    total), so per-team expectation is (total +/- diff)/2 — the exact
    formula the aggregator stores as Home_Exp / Away_Exp. Returns
    (None, None) when the row cannot compare the two teams' expectations."""
    t_n = _norm(target)
    home, away = _split_fixture(
        row.get("fixture_name") or row.get("Fixture") or row.get("fixture")
        or fxn or "")
    total = _num(row.get("predicted_corners"))
    diff = _num(row.get("diff"))
    if t_n and total is not None and diff is not None:
        h_exp, a_exp = (total + diff) / 2.0, (total - diff) / 2.0
        if t_n == _norm(home):
            return (h_exp, a_exp)
        if t_n == _norm(away):
            return (a_exp, h_exp)
    return (None, None)


def _corner_stage1_pair(row, target, fxn):
    """Per-team lastN corner averages (+ the miner's own team_more_corners
    verdict) from a stage1 row, mapped to (team, opp, verdict_name)."""
    t_n = _norm(target)
    t, o = None, None
    home, away = _split_fixture(
        row.get("fixture") or row.get("fixture_name") or fxn or "")
    if t_n:
        h = (row.get("home_team") or {})
        a = (row.get("away_team") or {})
        ht, at = _num(h.get("lastN_corners_avg")), _num(a.get("lastN_corners_avg"))
        if t_n == _norm(home):
            t, o = ht, at
        elif t_n == _norm(away):
            t, o = at, ht
    return t, o, str(row.get("team_more_corners") or "")


def _dna_corners_pair(snap, fid_s, fxn, target):
    """(team, opp, field, mapping) from the DNA corners intelligence for the
    predicted team vs opponent — the market-factors 'Avg Corners'/'Corner
    Power' entries first, then the same engine's per-team profiles. A value
    of 0/absent means 'that team's profile carries no corner data' (e.g. a
    profile computed from matches without corner stats), NOT 'zero corners',
    so a pair containing one is NOT_AVAILABLE instead of a free pass."""
    home, away = _split_fixture(fxn or "")
    t_n = _norm(target)
    if not t_n or t_n not in (_norm(home), _norm(away)):
        return None, None, "Corner_Power / Avg_Corners", \
            f"{target} = neither side of '{fxn or '?'}'"
    my_side = "home" if t_n == _norm(home) else "away"
    opp_name = away if t_n == _norm(home) else home
    markets = _resolve(snap, "dna", fid_s, fxn)
    if markets is not None:
        factors = (markets.get("corners") or {}).get("factors") or []
        for factor_name in ("Avg Corners", "Corner Power"):
            f = _dna_factor(factors, factor_name)
            if not f:
                continue
            hv, av = _num(f.get("home_value")), _num(f.get("away_value"))
            if hv is None or av is None or hv <= 0 or av <= 0:
                continue
            tv, ov = (hv, av) if my_side == "home" else (av, hv)
            return tv, ov, factor_name, f"{target} = {my_side} " \
                                     "(dna_market_factors)"
    # Fallback: the same engine's per-team profiles for both named sides.
    prof = snap.get("dna_prof_by_name") or {}
    pt, po = prof.get(t_n), prof.get(_norm(opp_name))
    if pt and po:
        for section, field in (("Raw_Audit_Metrics", "Avg_Corners"),
                               ("Market_Power_Scores", "Corner_Power")):
            tv = _num((pt.get(section) or {}).get(field))
            ov = _num((po.get(section) or {}).get(field))
            if tv is None or ov is None or tv <= 0 or ov <= 0:
                continue
            return tv, ov, "%s.%s" % (section, field), \
                f"{target} vs {opp_name} (dna profiles)"
    return None, None, "Corner_Power / Avg_Corners", \
        f"{target} = no DNA corner data for both sides"


def _win_corners_check(date, fid, fxn, target):
    """WIN Corners — the predicted-to-win team must EXPECT more corners than
    its opponent (per-team expected corners, nearest engine first):
      1. the corner pipeline's own predicted pair
         (corners_stage2 / corners_psychology / corners_catalyst rows carry
         the same predicted_corners +/- diff the aggregator stores as
         Home_Exp / Away_Exp) — resolved by fixture_id;
      2. the aggregator row itself (Home_Exp / Away_Exp, else the engine's
         own True_Corner_Fav) — the only id-less corner output, label join;
      3. the stage1 miner row (the engine's own team_more_corners verdict /
         per-team lastN averages) — by fixture_id;
      4. the DNA corners intelligence (per-fixture factors, then per-team
         profiles) — the last-resort source for a fixture no corner engine
         produced.
    PASS only when the predicted team's expectation strictly exceeds the
    opponent's. A 0/absent DNA value is 'no data', never a free pass."""
    dates = [date] + [d for d in _window_dates(date) if d != date]
    fid_s = _idstr(fid)
    for d in dates:
        snap = _snapshot(d)
        row = (snap.get("c2_by_id") or {}).get(fid_s)
        if not row:
            continue
        t, o = _corner_expected_pair(row, target, fxn)
        if t is None or o is None:
            continue
        src = row.get("__source", "corners_stage2")
        return _win_res(PASS if t > o else FAIL,
                        value={"team_exp": t, "opp_exp": o,
                               "predicted_corners": row.get("predicted_corners"),
                               "diff": row.get("diff")},
                        threshold="team expected corners > opponent "
                                  "(corner engines' predicted pair)",
                        source="%s @ %s" % (src, d),
                        field="predicted_corners/diff (per-team expected corners)",
                        mapping="%s vs rival corner expectation" % target)
    home, away = _split_fixture(fxn or "")
    t_n = _norm(target)
    c, d = _resolve_any(date, "cagg", fid, fxn)
    if c:
        h_team, a_team = c.get("Home_Team"), c.get("Away_Team")
        he, ae = _num(c.get("Home_Exp")), _num(c.get("Away_Exp"))
        # 2a. Per-team expected corners (the direct "more corners" measure).
        if he is not None and ae is not None and t_n in (_norm(h_team),
                                                       _norm(a_team)):
            my_home = _norm(h_team) == t_n
            t, o = (he, ae) if my_home else (ae, he)
            return _win_res(PASS if t > o else FAIL,
                            value={"team_exp": t, "opp_exp": o,
                                   "Total_Exp": c.get("Total_Exp")},
                            threshold="team Home_Exp/Away_Exp > opponent "
                                      "(corner aggregator)",
                            source="corners_aggregator @ %s" % d,
                            field="Home_Exp / Away_Exp",
                            mapping="%s vs rival corner expectation" % target)
        # 2b. The engine's own True_Corner_Fav resolution.
        fav = str(c.get("True_Corner_Fav") or "")
        if fav and t_n in (_norm(h_team), _norm(a_team), ""):
            is_home = _norm(h_team) == t_n or (
                not h_team and t_n == _norm(home))
            t_score = c.get("Home_Score") if is_home else c.get("Away_Score")
            o_score = c.get("Away_Score") if is_home else c.get("Home_Score")
            return _win_res(PASS if t_n == _norm(fav) else FAIL,
                            value={"true_corner_fav": fav,
                                   "team_corner_score": t_score,
                                   "opp_corner_score": o_score,
                                   "Total_Exp": c.get("Total_Exp")},
                            threshold="predicted team == True_Corner_Fav",
                            source="corners_aggregator @ %s" % d,
                            field="True_Corner_Fav (Home_Score vs Away_Score)",
                            mapping="%s vs corner favourite '%s'"
                                    % (target, fav))
    # 3. Stage1 miner (fixture-id join, exact).
    for d in dates:
        snap = _snapshot(d)
        row = (snap.get("c1_by_id") or {}).get(fid_s)
        if not row:
            continue
        t, o, fav = _corner_stage1_pair(row, target, fxn)
        if fav and _norm(fav) == t_n:
            return _win_res(PASS,
                            value={"team_more_corners": fav, "team_avg": t,
                                   "opp_avg": o},
                            threshold="engine's own team_more_corners verdict",
                            source="corners_stage1 @ %s" % d,
                            field="team_more_corners (lastN corner averages)",
                            mapping="%s = the engine's more-corners side"
                                    % target)
        if t is not None and o is not None:
            return _win_res(PASS if t > o else FAIL,
                            value={"team_avg": t, "opp_avg": o},
                            threshold="team lastN corner average > opponent",
                            source="corners_stage1 @ %s" % d,
                            field="lastN_corners_avg (home_team/away_team)",
                            mapping="%s vs rival corner averages" % target)
    # 4. DNA corners intelligence — last resort (fixtures no corner
    # engine produced at all).
    for d in dates:
        snap = _snapshot(d)
        t, o, field, mapping = _dna_corners_pair(snap, fid_s, fxn, target)
        if t is None or o is None:
            continue
        return _win_res(PASS if t > o else FAIL,
                        value={"team": t, "opp": o},
                        threshold="team corner strength > opponent (DNA corners)",
                        source="dna corners @ %s" % d, field=field,
                        mapping=mapping)
    return _win_res(NOT_AVAILABLE, source="corners_stage2 / corners_aggregator / "
                                         "corners_stage1 / DNA corners",
                    field="per-team corner expectation",
                    mapping="%s = no corner row in the source window" % target)


def _win_psych_check(date, fid, fxn, target, side, src_row=None):
    """WIN Psychology — the predicted team's base score must sit at least
    `WIN_PSYCH_MIN_GAP` ABOVE the opponent's (PSYCHOLOGY/win_psychology.py
    H_Base / A_Base). The engine's own LOCK tier is net >= 45, so the check
    demands the stricter +50 margin for the pick. A fixture-level audit net
    is the documented fallback when the side pair is unavailable."""
    gap = INTELLIGENT_PASS_RULES["WIN_PSYCH_MIN_GAP"]

    def _side_margin(srow):
        h, a = _num(srow.get("H_Base")), _num(srow.get("A_Base"))
        if side not in ("home", "away") or h is None or a is None:
            return None, None, None
        if side == "home":
            return h, a, h - a
        return a, h, a - h

    if isinstance(src_row, dict):
        v, o, margin = _side_margin(src_row)
        if margin is not None:
            return _win_res(PASS if margin >= gap else FAIL,
                            value={"team": v, "opp": o, "margin": margin},
                            threshold=f"picked side base >= opponent base + {gap}",
                            source="calling row", field="H_Base/A_Base",
                            mapping=f"{target} = {side} side margin")
    row, d = _resolve_any(date, "wps", fid, fxn)
    if row:
        v, o, margin = _side_margin(row)
        if margin is not None:
            return _win_res(PASS if margin >= gap else FAIL,
                            value={"team": v, "opp": o, "margin": margin},
                            threshold=f"picked side base >= opponent base + {gap}",
                            source=f"win_psychology @ {d}", field="H_Base/A_Base",
                            mapping=f"{target} = {side} side margin")
        # Fixture-level net (the engine's Audit_Score IS the picked side's
        # margin for that fixture) — same gap, no invented normalisation.
        for src, srow in (("calling row", src_row), (f"win_psychology @ {d}", row)):
            if not isinstance(srow, dict):
                continue
            for val in ("Audit_Score", "Psych_Score"):
                v = _num(srow.get(val))
                if v is not None:
                    return _win_res(PASS if v >= gap else FAIL,
                                    value={"team": v, "opp": None, "margin": v},
                                    threshold=f"picked side net >= +{gap}",
                                    source=src, field=val,
                                    mapping=f"{target} (fixture-level net)")
    return _win_res(NOT_AVAILABLE, source="win_psychology",
                    field="H_Base/A_Base",
                    mapping=f"{target} = no psychology row in the source window")


def _win_underdog_check(date, fid, fxn):
    """WIN Underdog — the existing longshot gate on the fixture's dog
    (master_underdog_audit Dog_Score_Prob, 0-100 "%"): PASS when the underdog
    scores less than half the time. underdog_engine's dog_score_prob is the
    same field of the same engine family, used when the audit row is absent."""
    cut = INTELLIGENT_PASS_RULES["WIN_UNDERDOG_SCORE_PROB_MAX"]
    for prefix, field, label in (("uda", "Dog_Score_Prob", "underdog_audit"),
                                 ("ud", "dog_score_prob", "underdog_base")):
        row, d = _resolve_any(date, prefix, fid, fxn)
        if not row:
            continue
        p = _frac(row.get(field))
        if p is None:
            continue
        return _win_res(PASS if p < cut / 100.0 else FAIL,
                        value=row.get(field), threshold=f"< {cut}%",
                        source=f"{label} @ {d}", field=field,
                        mapping=f"dog = {row.get('underdog_team') or 'the fixture underdog'}")
    return _win_res(NOT_AVAILABLE,
                    source="underdog_audit / underdog_base",
                    field="Dog_Score_Prob",
                    mapping="fixture not covered by the underdog engines")


def _win_draw_check(date, fid, fxn, src_row=None):
    """WIN Draw Probability — below 20% the win side is clean. Primary source:
    the draw engine's own Monte Carlo mc_draw_prob (0-1 float). When the
    fixture has no draw row, the pick's OWN Monte_Draw_Prob (the WIN apex
    engine's draw risk, stored as a 0-100 number) is compared against the same
    20% cut in its own representation."""
    r, d = _resolve_any(date, "draw", fid, fxn)
    if r is not None:
        f = _frac(r.get("mc_draw_prob"))
        if f is None:
            return _win_res(NOT_AVAILABLE, source=f"draw @ {d}",
                            field="mc_draw_prob")
        return _win_res(PASS if f < INTELLIGENT_PASS_RULES["WIN_DRAW_PROB_MAX"] else FAIL,
                        value=r.get("mc_draw_prob"), threshold="< 0.20 (20%)",
                        source=f"draw @ {d}", field="mc_draw_prob",
                        mapping="fixture-level Monte Carlo draw probability")
    if isinstance(src_row, dict):
        raw = _num(src_row.get("Monte_Draw_Prob"))
        if raw is not None:
            return _win_res(PASS if raw < INTELLIGENT_PASS_RULES["WIN_DRAW_PROB_MAX_PCT"] else FAIL,
                            value=raw,
                            threshold=f"< {INTELLIGENT_PASS_RULES['WIN_DRAW_PROB_MAX_PCT']} (20%)",
                            source="calling row (WIN apex)",
                            field="Monte_Draw_Prob",
                            mapping="the pick's own draw risk (0-100 scale)")
    return _win_res(NOT_AVAILABLE, source="draw / Monte_Draw_Prob",
                    field="mc_draw_prob / Monte_Draw_Prob",
                    mapping="no draw intelligence for this fixture in the window")


def _u2s_base_pair(snap, date, row, fid, fxn):
    """(attack, leak, source) for the U2S attack-vs-defence checks: the
    calling row when it IS the underdog_base row (the underdog page's base
    table), otherwise the fixture's underdog_base row across the window."""
    if "dog_att_strength" in row or "fav_def_weakness" in row:
        return (_num(row.get("dog_att_strength")),
                _num(row.get("fav_def_weakness")), "calling row")
    r, d = _resolve_any(date, "ud", fid, fxn)
    if not r:
        return None, None, "underdog_base (no row in the source window)"
    return (_num(r.get("dog_att_strength")),
            _num(r.get("fav_def_weakness")),
            "underdog_base @ %s" % d)


def _u2s_venue_check(snap, row, u_row, fid, fxn, date):
    """The 4th U2S check — the underdog must have SCORED/WON in at least
    U2S_VENUE_SCORE_MIN of its last 5 venue matches. Existing fields only:
      1. win_forecast side row for the underdog (the U2S feed's own
         "Underdog" identity), field "last_5_wins_at_venue" → verdict
         (>= 3 PASS, below FAIL).
      2. Surrogate when no win row resolves: u2s_psychology's own
         "Dog_Scoring_Consistency" venue sample. Scored in ALL of its last
         3 venue games PROVES scoring in >= 3 of the last 5 (the last 3 are
         a subset); a full last-5 sample IS the rule. A partial sample
         cannot disprove the 3-of-5 rule and is left out — never a fake
         FAIL.
    Returns the check dict, or None when no source can give a verdict (the
    card then stays x/3 — the one deliberate variable denominator)."""
    rules = INTELLIGENT_PASS_RULES
    dog = (row.get("Underdog") or row.get("underdog_team")
           or (u_row or {}).get("Underdog") or "")
    dog_n = _norm(dog)
    if dog_n:
        wrows, wdate = _resolve_any(date, "win", fid, fxn)
        if isinstance(wrows, dict):          # a single saved side row
            wrows = [wrows]
        for r in (wrows or []):
            if _norm(r.get("team_name")) != dog_n:
                continue
            vw = _num(r.get("last_5_wins_at_venue"))
            if vw is None:
                continue
            ok = vw >= rules["U2S_VENUE_SCORE_MIN"]
            return {"name": "Venue Scoring",
                    "result": PASS if ok else FAIL,
                    "value": {"venue_wins_last_5": vw,
                              "win_threshold": rules["U2S_VENUE_SCORE_MIN"]},
                    "threshold": "underdog scored/won in >= %d of its last %d "
                                 "venue matches (win_forecast)" % (
                                     rules["U2S_VENUE_SCORE_MIN"],
                                     rules["U2S_VENUE_LOOKBACK"]),
                    "source": "win_forecast (win_by_id) @ %s" % (wdate or date),
                    "field": "last_5_wins_at_venue",
                    "mapping": "underdog venue wins last %d: %s (threshold %d)" % (
                        rules["U2S_VENUE_LOOKBACK"], vw,
                        rules["U2S_VENUE_SCORE_MIN"])}
    # Surrogate: the U2S feed's own venue scoring sample (calling row first,
    # then the joined u2s_psychology row).
    raw, raw_src = None, ""
    for src_row, tag in ((row, "calling row"),
                         (u_row, "u2s_psychology")):
        v = (src_row or {}).get("Dog_Scoring_Consistency")
        if v is not None and str(v).strip().upper() not in ("", "N/A", "NONE"):
            raw, raw_src = v, tag
            break
    if raw is not None:
        m = re.search(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)", str(raw))
        if m:
            scored, total = int(m.group(1)), int(m.group(2))
            if total >= rules["U2S_VENUE_LOOKBACK"]:
                # a full last-5 venue sample IS the rule → verdict
                result = (PASS if scored >= rules["U2S_VENUE_SCORE_MIN"]
                          else FAIL)
                mapping = ("underdog scored in %d/%d venue games "
                           "(full last-%d sample)" % (scored, total, total))
            elif scored >= rules["U2S_VENUE_SCORE_MIN"]:
                # a full short sample (3/3, 3/4, 4/4) can only PROVE
                # the 3-of-5 rule — never disprove it
                result = PASS
                mapping = ("underdog scored in %d/%d venue games — proves "
                           ">= %d of the last %d" % (
                               scored, total,
                               rules["U2S_VENUE_SCORE_MIN"],
                               rules["U2S_VENUE_LOOKBACK"]))
            else:
                return None
            return {"name": "Venue Scoring",
                    "result": result,
                    "value": raw,
                    "threshold": "underdog scored in >= %d of its last %d "
                                 "venue matches (u2s_psychology surrogate)" % (
                                     rules["U2S_VENUE_SCORE_MIN"],
                                     rules["U2S_VENUE_LOOKBACK"]),
                    "source": raw_src,
                    "field": "Dog_Scoring_Consistency",
                    "mapping": mapping}
    return None


def _parse_council_votes(raw):
    """(votes, of) parsed from Engine/over25_forecast council_votes ("7/9"),
    or (None, None) when the field is absent/unparseable."""
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", str(raw or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _league_top10_check(snap, date, fid, fxn):
    """O2.5/O1.5 'one team must sit in the league top 10' — the forecast
    rows do not store positions, so they are chained from existing caches
    by fixture (user-approved source order):
      corners_aggregator (Home_Pos/Away_Pos) → the merged corner
      stage-2/psychology/catalyst rows (home_position/away_position) →
      the draw engine rows (standings-backed home/away_position).
    Unknown sentinels (>= 99) never count as data. Either side <= 10 →
    PASS; a complete pair with both > 10 → FAIL; nothing usable → N/A."""
    top = INTELLIGENT_PASS_RULES["TOP10_LEAGUE_MAX"]
    thr = "either team in the league top %d (user rule)" % top
    fail_res = None
    for prefix, hk, ak, src in (
            ("cagg", "Home_Pos", "Away_Pos", "corners_aggregator"),
            ("c2", "home_position", "away_position",
             "corner stage2/psych/catalyst"),
            ("draw", "home_position", "away_position", "draw engine")):
        r, d = _resolve_any(date, prefix, fid, fxn)
        if not r:
            continue
        h, a = _num(r.get(hk)), _num(r.get(ak))
        valid = [v for v in (h, a) if v is not None and 1 <= v < 99]
        if not valid:
            continue
        if any(v <= top for v in valid):
            return _win_res(PASS, value={"home_pos": h, "away_pos": a},
                            threshold=thr, source="%s @ %s" % (src, d),
                            field="%s / %s" % (hk, ak))
        if len(valid) == 2:
            fail_res = _win_res(FAIL, value={"home_pos": h, "away_pos": a},
                                threshold=thr, source="%s @ %s" % (src, d),
                                field="%s / %s" % (hk, ak))
    return fail_res or _win_res(NOT_AVAILABLE, threshold=thr,
                                source="corners_aggregator / corner stage2 / "
                                       "draw engine",
                                field="home/away league position",
                                mapping="no usable position pair in the "
                                        "source window")


def _o15_probability_check(snap, date, fid, fxn):
    """O1.5 'probability > 60%' — chain: over15_stage3 Poisson% →
    over15_psychology Base_Poisson → gg_o15 head1 mc_over15_prob.
    _frac normalises percent-strings and 0-1 fractions alike."""
    for prefix, field, src in (
            ("o15s", "Poisson%", "over15_stage3"),
            ("o15p", "Base_Poisson", "over15_psychology"),
            ("o15c", "mc_over15_prob", "gg_o15 composite")):
        r, d = _resolve_any(date, prefix, fid, fxn)
        if not r:
            continue
        f = _frac(r.get(field))
        if f is None:
            continue
        return _win_res(PASS if f * 100.0 > INTELLIGENT_PASS_RULES["O15_PROB_MIN"]
                        else FAIL, value=round(f * 100.0, 1),
                        threshold="> %d%% (user rule)"
                                  % INTELLIGENT_PASS_RULES["O15_PROB_MIN"],
                        source="%s @ %s" % (src, d), field=field)
    return _win_res(NOT_AVAILABLE,
                    threshold="> %d%% (user rule)"
                              % INTELLIGENT_PASS_RULES["O15_PROB_MIN"],
                    source="over15_stage3 / over15_psychology / gg_o15",
                    field="Poisson% / Base_Poisson / mc_over15_prob")


def _o15_kill_switch_check(snap, date, fid, fxn):
    """O1.5-level kill switch (user rule: the 1.5 flag, NOT the 2.5 one) —
    the stage-3 row's H2H_Record holds the last meetings' scorelines
    (e.g. "['1-2', '4-1', '2-2']"). PASS only with the FULL 3-meeting
    sample and every total >= 2 goals (over 1.5); a partial sample is
    honest NOT_AVAILABLE."""
    thr = ("last 3 H2H meetings all over 1.5 goals "
           "(O1.5-level kill switch, user rule)")
    r, d = _resolve_any(date, "o15s", fid, fxn)
    if not r:
        return _win_res(NOT_AVAILABLE, threshold=thr,
                        source="over15_stage3", field="H2H_Record",
                        mapping="no stage-3 row in the source window")
    raw = r.get("H2H_Record")
    scores = re.findall(r"(\d+)\s*-\s*(\d+)", str(raw or ""))
    if len(scores) != 3:
        return _win_res(NOT_AVAILABLE, value=raw, threshold=thr,
                        source="over15_stage3 @ %s" % d, field="H2H_Record",
                        mapping="needs the full 3-meeting sample "
                                "(%d found)" % len(scores))
    totals = [int(a) + int(b) for a, b in scores]
    return _win_res(PASS if all(t >= 2 for t in totals) else FAIL,
                    value=raw, threshold=thr,
                    source="over15_stage3 @ %s" % d, field="H2H_Record",
                    mapping="scoreline totals %s" % totals)
# ══════════════════════════════════════════════════════════════════════════════
# MARKET CHECKLISTS — the denominator is FIXED per market: it is ALWAYS the
# branch's full rule set, regardless of whether a given fixture's inputs exist.
# Missing intelligence → NOT_AVAILABLE, which lowers the NUMERATOR only (never
# a fake FAIL and never a smaller denominator): the same market always shows
# the same total (WIN=x/8, GG=x/4 …) and only x varies per pick.
# SOLE EXCEPTION (user rule 2026-09-23): U2S emits its 4th check (Venue
# Scoring) ONLY when u2s_psychology carries the full last-3 venue sample —
# the underdog card is x/3 without that data and x/4 with it.
# ══════════════════════════════════════════════════════════════════════════════

def _checks_for_market(market, snap, row, fid, fxn, date=None):
    """Return [{name, result, value, threshold, source, field, mapping}]."""
    rules = INTELLIGENT_PASS_RULES
    req_date = date or snap.get("date") or ""
    home, away = _split_fixture(fxn)
    fid_s = _idstr(fid)
    checks = []

    def add(name, result, value=None, threshold=None,
            source="", field="", mapping=""):
        checks.append({"name": name, "result": result, "value": value,
                       "threshold": threshold, "source": source,
                       "field": field, "mapping": mapping})

    # ── WIN (apex/forecast/raw/psychology picks: the predicted team, by id) ──
    if market in ("win_apex", "win_forecast", "win_raw", "win_psychology"):
        target = str(row.get("Target") or row.get("team_name")
                     or row.get("Master_Pick") or "")
        # Resolve the fixture's canonical 'home vs away' label from the
        # id-bearing engines before any side or name join is made.
        canon, _label_date = _canonical_label_any(req_date, fid_s, fxn)
        if canon:
            fxn = canon
            home, away = _split_fixture(fxn)
        if not fxn and target:
            # Row carries no fixture label (some side rows are keyed by id
            # only) — take the label from the fixture's WIN side row.
            probe = _win_side_row(snap, fid_s, "", target)
            if probe:
                fxn = _fixture_label(probe)
                home, away = _split_fixture(fxn)
        side = ("home" if _norm(target) == _norm(home)
                else "away" if target and _norm(target) == _norm(away) else None)
        if target and side is None:
            # First-leg rows carry 'PSG (agg lead)' style labels (append_leg2)
            # — the anchor 'X vs Y' still identifies the side (same fixture).
            side = ("home" if _norm(home) and _norm(home) in _norm(target)
                    else "away" if _norm(away) and _norm(away) in _norm(target) else None)
        if not target or (not side):
            # FIXED DENOMINATOR: even with no pickable side, the WIN audit
            # always carries its FULL 8-rule set (see the rule order below) —
            # the denominator must never depend on row shape.
            for _name in ("SOT", "Corners", "Psychology", "Underdog",
                          "Goal Intent", "Draw Probability", "Parity +10",
                          "Form"):
                add(_name, NOT_AVAILABLE,
                    source="row itself (no pick/side on this row)",
                    field=_WIN_FIELDS.get(_name, ""),
                    mapping=f"{target or '?'} = no side mapping")
            return checks
        # 1. SOT expectancy (U2S per-side intelligence, matched by fav/dog)
        r = _win_sot_check(req_date, fid_s, fxn, target)
        add("SOT", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        # 2. Corners (predicted team must be the True_Corner_Fav)
        r = _win_corners_check(req_date, fid_s, fxn, target)
        add("Corners", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        # 3. Psychology — the predicted team's OWN signed side net
        r = _win_psych_check(req_date, fid_s, fxn, target, side, row)
        add("Psychology", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 4. Underdog gate (existing dog_score_prob "<50%" longshot rule)
        r = _win_underdog_check(req_date, fid_s, fxn)
        add("Underdog", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 5. Goal Intent (predicted team's DNA Goal Intent vs opponent's)
        r = _win_goal_intent_check(req_date, fid_s, fxn, target)
        add("Goal Intent", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 6. Draw probability — PASS below 20% (user rule), existing field
        r = _win_draw_check(req_date, fid_s, fxn, row)
        add("Draw Probability", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 7. Parity +10 (win_forecast engine's signed parity_score, own row)
        r = _win_parity_eval(req_date, fid_s, fxn, target, row)
        add("Parity +10", r["result"], value=r["value"],
            threshold=r["threshold"], source=r["source"], field=r["field"],
            mapping=r["mapping"])
        # 8. Form (existing last-5 counters, team vs opponent)
        r = _win_form_eval(req_date, fid_s, fxn, target, row)
        add("Form", r["result"], value=r["value"], threshold=r["threshold"],
            source=r["source"], field=r["field"], mapping=r["mapping"])
        return checks

    # ── WIN PSYCHOLOGY — same WIN pick, same ONE WIN checklist ────────────────
    # The WIN page's psychology table is another WIN pick (Master_Pick), and
    # supporting-engine identity must never pick the checklist (§15). Its
    # audit is therefore the COMPLETE WIN ruleset above: seed the predicted
    # team from this row and run the same eight checks.
    if market == "win_psychology":
        target = str(row.get("Master_Pick") or row.get("Target")
                     or row.get("team_name") or "")
        if target:
            row = dict(row, Target=target)
        return _checks_for_market("win_apex", snap, row, fid, fxn, date=req_date)
    # ── GG / BTTS ────────────────────────────────────────────────────────────
    # ── GG — EVERY GG table (supreme / precision / O1.5 composite) runs the
    # ONE unified 4-check card (user rule 2026-09-23): match psych > 65,
    # goalkeeper as-is, BTTS both > 50, Goal Intent both > 60. The 5-signal
    # Precision card and the mixed lambda composite card are gone — all GG
    # tables share this single card, each check with source/field provenance.
    if market in ("gg_supreme", "gg_precision", "gg_o15"):
        checks.extend(_gg_unified_checks(snap, row, fid_s, fxn, req_date))
        return checks

    # ── O2.5 — the user's six-question card (2026-09-23): probability > 60,
    # council >= 7/9, goal count > 20, DNA Goal Intent both > 50, the
    # engine's own kill switch (last 3 H2H all over 2.5), and one team in
    # the league top 10. Apex picks join the fixture's over25_forecast row
    # (council / goal count live there too).
    if market in ("over25_forecast", "over25_apex"):
        if market == "over25_forecast":
            r, rsrc = row, "calling row"
        else:
            r, rd = _resolve_any(req_date, "o25f", fid_s, fxn)
            rsrc = ("over25_forecast @ %s" % rd) if r else ""
        r = r or {}
        ks = r.get("kill_switch_pass")
        if ks is None:
            add("Kill Switch", NOT_AVAILABLE,
                threshold="last 3 H2H all over 2.5 (user rule)",
                source=rsrc, field="kill_switch_pass")
        else:
            add("Kill Switch", PASS if ks else FAIL,
                value=r.get("kill_switch_pass"),
                threshold="last 3 H2H all over 2.5 (user rule)",
                source=rsrc, field="kill_switch_pass")
        po = _num(r.get("poisson_over_prob_num"))
        if po is None:
            add("Poisson Gate", NOT_AVAILABLE,
                threshold="> %d%% (user rule)" % rules["O25_POISSON_VOTE_MIN"],
                source=rsrc, field="poisson_over_prob_num")
        else:
            add("Poisson Gate", PASS if po > rules["O25_POISSON_VOTE_MIN"] else FAIL,
                value=r.get("poisson_over_prob_num"),
                threshold="> %d%% (user rule)" % rules["O25_POISSON_VOTE_MIN"],
                source=rsrc, field="poisson_over_prob_num")
        votes, of = _parse_council_votes(r.get("council_votes"))
        council_thr = ">= %d of 9 (user rule)" % rules["O25_COUNCIL_MIN"]
        if votes is None or of != 9:
            add("Council Votes", NOT_AVAILABLE, value=r.get("council_votes"),
                threshold=council_thr, source=rsrc, field="council_votes")
        else:
            add("Council Votes",
                PASS if votes >= rules["O25_COUNCIL_MIN"] else FAIL,
                value=r.get("council_votes"), threshold=council_thr,
                source=rsrc, field="council_votes")
        g = _num(r.get("combined_gs_last_5"))
        goal_thr = ("> %d (both teams' last-5 goals summed, user rule)"
                    % rules["O25_GOAL_COUNT_MIN"])
        if g is None:
            add("Goal Count", NOT_AVAILABLE, threshold=goal_thr,
                source=rsrc, field="combined_gs_last_5")
        else:
            add("Goal Count", PASS if g > rules["O25_GOAL_COUNT_MIN"] else FAIL,
                value=r.get("combined_gs_last_5"), threshold=goal_thr,
                source=rsrc, field="combined_gs_last_5")
        gi_res, gi_val = _dna_side_factor_check(
            snap, fid_s, fxn, "over25", "Goal Intent",
            rules["DNA_INTENT_SIDE_MIN"], rules["DNA_INTENT_SIDE_MIN"])
        add("Goal Intent", gi_res, value=gi_val,
            threshold="both teams > %d (user rule)" % rules["DNA_INTENT_SIDE_MIN"],
            source="dna_market_factors", field="Goal Intent home/away_value")
        t10 = _league_top10_check(snap, req_date, fid_s, fxn)
        add("League Top 10", t10["result"], value=t10["value"],
            threshold=t10["threshold"], source=t10["source"],
            field=t10["field"], mapping=t10.get("mapping"))
        return checks

    # ── O1.5 — the SAME six-question card at the 1.5 level (user rule
    # 2026-09-23): probability > 60 (stage3 Poisson% → psychology
    # Base_Poisson → gg_o15 mc), council >= 7/9 and goal count > 15 (both
    # joined from the fixture's over25_forecast row), DNA Goal Intent both
    # > 50, the O1.5-level kill switch (stage3 H2H_Record scorelines, NOT
    # the 2.5 flag), and one team in the league top 10.
    if market in ("over15", "over15_stage3", "over15_apex"):
        prob = _o15_probability_check(snap, req_date, fid_s, fxn)
        add("Probability Gate", prob["result"], value=prob["value"],
            threshold=prob["threshold"], source=prob["source"],
            field=prob["field"], mapping=prob.get("mapping"))
        r25, d25 = _resolve_any(req_date, "o25f", fid_s, fxn)
        r25_src = ("over25_forecast @ %s" % d25) if r25 else ""
        r25 = r25 or {}
        votes, of = _parse_council_votes(r25.get("council_votes"))
        council_thr = ">= %d of 9 (user rule)" % rules["O25_COUNCIL_MIN"]
        if votes is None or of != 9:
            add("Council Votes", NOT_AVAILABLE, value=r25.get("council_votes"),
                threshold=council_thr, source=r25_src, field="council_votes")
        else:
            add("Council Votes",
                PASS if votes >= rules["O25_COUNCIL_MIN"] else FAIL,
                value=r25.get("council_votes"), threshold=council_thr,
                source=r25_src, field="council_votes")
        g = _num(r25.get("combined_gs_last_5"))
        goal_thr = ("> %d (both teams' last-5 goals summed, user rule)"
                    % rules["O15_GOAL_COUNT_MIN"])
        if g is None:
            add("Goal Count", NOT_AVAILABLE, threshold=goal_thr,
                source=r25_src, field="combined_gs_last_5")
        else:
            add("Goal Count", PASS if g > rules["O15_GOAL_COUNT_MIN"] else FAIL,
                value=r25.get("combined_gs_last_5"), threshold=goal_thr,
                source=r25_src, field="combined_gs_last_5")
        gi_res, gi_val = _dna_side_factor_check(
            snap, fid_s, fxn, "over15", "Goal Intent",
            rules["DNA_INTENT_SIDE_MIN"], rules["DNA_INTENT_SIDE_MIN"])
        add("Goal Intent", gi_res, value=gi_val,
            threshold="both teams > %d (user rule)" % rules["DNA_INTENT_SIDE_MIN"],
            source="dna_market_factors", field="Goal Intent home/away_value")
        ks15 = _o15_kill_switch_check(snap, req_date, fid_s, fxn)
        add("Kill Switch", ks15["result"], value=ks15["value"],
            threshold=ks15["threshold"], source=ks15["source"],
            field=ks15["field"], mapping=ks15.get("mapping"))
        t10 = _league_top10_check(snap, req_date, fid_s, fxn)
        add("League Top 10", t10["result"], value=t10["value"],
            threshold=t10["threshold"], source=t10["source"],
            field=t10["field"], mapping=t10.get("mapping"))
        return checks

    # ── Corners — the user's 2-check card (2026-09-23): the underdog's own
    # Spears % > 60 (gg_supreme / gg_psychology) and under-2.5 < 40% (unders
    # mc_u25_prob; over25_forecast Poisson-complement fallback). The old
    # friction / Corner Power card is gone. ──────────────────────────────
    if market == "corners_aggregator":
        # 1) Underdog > 60%: parse the underdog team's per-team Spears % from
        #    gg_supreme / gg_psychology ("Spears: H:X%|A:Y%"). The underdog is
        #    identified from the calling row's "Underdog" field (or from the
        #    U2S row). That team's % must be > 60.
        rules_corner = INTELLIGENT_PASS_RULES
        # Find the underdog name
        dog = row.get("Underdog") or row.get("underdog_team") or ""
        if not dog:
            # Try to find underdog from U2S row
            u2s_row, u_dog = _u2s_row_for(snap, fid_s, fxn,
                                           row.get("fixture_id"),
                                           row.get("fixture") or row.get("Fixture"))
            if u2s_row and u_dog:
                dog = u_dog
        # Parse Spears from gg_supreme or gg_psychology
        spears_chain = [("calling row", row.get("Spears"))]
        gsup_cs, d1cs = _resolve_any(req_date, "gsup", fid_s, fxn)
        if gsup_cs:
            spears_chain.append(("gg_supreme @ %s" % d1cs, gsup_cs.get("Spears")))
        gps_cs, d2cs = _resolve_any(req_date, "gps", fid_s, fxn)
        if gps_cs:
            spears_chain.append(("gg_psychology @ %s" % d2cs, gps_cs.get("Spears")))
        underdog_spears_res = None
        underdog_spears_val = None
        underdog_spears_src = ""
        underdog_spears_field = ""
        # The underdog's side is decided by the calling fixture label first
        # (its canonical home/away orientation), then confirmed by the
        # win_forecast side row. When neither identifies the team the check
        # stays NOT_AVAILABLE — the away side is never assumed.
        dog_side = ""
        dog_n = _norm(dog)
        if dog_n:
            h_lab, a_lab = _split_fixture(fxn)
            if dog_n == _norm(h_lab):
                dog_side = "home"
            elif dog_n == _norm(a_lab):
                dog_side = "away"
        if not dog_side and dog_n:
            wrows_cs, _wd = _resolve_any(req_date, "win", fid_s, fxn)
            if isinstance(wrows_cs, dict):
                wrows_cs = [wrows_cs]
            for r in (wrows_cs or []):
                if _norm(r.get("team_name")) == dog_n:
                    side_v = str(r.get("side") or "").strip().lower()
                    if side_v in ("home", "away"):
                        dog_side = side_v
                    break
        for cs, raw in spears_chain:
            h, a = _parse_spears(raw)
            if h is None or a is None or not dog_side:
                continue
            underdog_pct = h if dog_side == "home" else a
            underdog_spears_val = {"home_spear": h, "away_spear": a,
                                   "underdog": dog, "underdog_pct": underdog_pct}
            underdog_spears_src = cs
            underdog_spears_field = ("Spears (H:X%%|A:Y%%) — underdog %d%%"
                                     % underdog_pct)
            underdog_spears_res = (
                PASS if underdog_pct > rules_corner["CORNER_UNDERDOG_PSYCH_MIN"]
                else FAIL)
            underdog_spears_map = (
                f"underdog {dog} psych: {underdog_pct}% > "
                f"{rules_corner['CORNER_UNDERDOG_PSYCH_MIN']}")
            break
        if underdog_spears_res is None:
            add("Underdog Psych", NOT_AVAILABLE,
                value=None,
                threshold="underdog Spears %% > %d (gg Spears)" % rules_corner["CORNER_UNDERDOG_PSYCH_MIN"],
                source="gg_supreme / gg_psychology", field="Spears",
                mapping="could not determine underdog's Spears %%")
        else:
            add("Underdog Psych", underdog_spears_res,
                value=underdog_spears_val,
                threshold="underdog Spears %% > %d (gg Spears)" % rules_corner["CORNER_UNDERDOG_PSYCH_MIN"],
                source=underdog_spears_src, field=underdog_spears_field,
                mapping=underdog_spears_map)

        # 2) Under 2.5 < 40%: unders.mc_u25_prob < 40 (i.e. over 2.5 > 60%)
        unr2, ud2 = _resolve_any(req_date, "un", fid_s, fxn)
        if unr2:
            f2 = _frac(unr2.get("mc_u25_prob"))
            if f2 is not None:
                u25_pct = f2 * 100.0
                add("Under 2.5 < 40%",
                    PASS if u25_pct < rules_corner["CORNER_U25_PROB_MAX"] else FAIL,
                    value=round(u25_pct, 1),
                    threshold="under 2.5 % < 40% (i.e. over 2.5 > 60%) — unders.mc_u25_prob",
                    source="unders @ %s" % ud2,
                    field="mc_u25_prob",
                    mapping=f"under 2.5: {u25_pct:.1f}% {'< 40 ✓' if u25_pct < rules_corner['CORNER_U25_PROB_MAX'] else '>= 40 ✗'}")
                return checks
        # Fallback: over25_forecast poisson_over_prob_num (over 2.5 > 60% = under 2.5 < 40%)
        o25r2, od2 = _resolve_any(req_date, "o25f", fid_s, fxn)
        if o25r2:
            po25 = _num(o25r2.get("poisson_over_prob_num"))
            if po25 is not None:
                u25_pct2 = 100.0 - po25
                add("Under 2.5 < 40%",
                    PASS if u25_pct2 < rules_corner["CORNER_U25_PROB_MAX"] else FAIL,
                    value=round(u25_pct2, 1),
                    threshold="under 2.5 % < 40% (i.e. over 2.5 > 60%) — over25_forecast",
                    source="over25_forecast @ %s" % od2,
                    field="100 - poisson_over_prob_num",
                    mapping=f"under 2.5: {u25_pct2:.1f}% {'< 40 ✓' if u25_pct2 < rules_corner['CORNER_U25_PROB_MAX'] else '>= 40 ✗'}")
                return checks
        add("Under 2.5 < 40%", NOT_AVAILABLE,
            value=None,
            threshold="under 2.5 % < 40% (unders.mc_u25_prob / over25_forecast)",
            source="unders / over25_forecast", field="mc_u25_prob / poisson_over_prob_num",
            mapping="no under 2.5 probability data available")
        return checks

    # ── Draw (engine's own tier gates + the new DNA parity check) ────────────
    if market == "draw":
        # Native direction: a DRAW pick is supported when mc_draw_prob reaches
        # the draw engine's own draw-candidate floor (>= 0.22, TIER2 gate).
        mp = _frac(row.get("mc_draw_prob"))
        if mp is None:
            add("Draw Probability", NOT_AVAILABLE)
        else:
            add("Draw Probability", PASS if mp >= rules["DRAW_MC_DRAW_PROB_FLOOR"] else FAIL,
                value=row.get("mc_draw_prob"), threshold=">= 0.22 (draw engine floor)")
        par = _num(row.get("parity"))
        if par is None:
            add("Psychology Parity", NOT_AVAILABLE)
        else:
            add("Psychology Parity", PASS if par >= rules["DRAW_PARITY_THRESHOLD"] else FAIL,
                value=row.get("parity"), threshold=">=0.6")
        dmi = _num(row.get("dmi"))
        if dmi is None:
            add("Draw Magnet", NOT_AVAILABLE)
        else:
            add("Draw Magnet", PASS if dmi >= rules["DRAW_DMI_THRESHOLD"] else FAIL,
                value=row.get("dmi"), threshold=">=0.45")
        add("DNA Parity", _dna_parity_eval(snap, fid_s, fxn))
        return checks

    # ── Unders (u25 head rows from the unders composite file) ─────────────────
    if market == "unders_u25":
        # gg_precision_engine: sig1_raw saturates at combined_lambda 2.5 —
        # below that, neither side carries O1.5+ firepower → supports U2.5.
        lam = _num(row.get("combined_lambda"))
        if lam is None:
            add("Goal Gap", NOT_AVAILABLE)
        else:
            add("Goal Gap", PASS if lam <= 2.5 else FAIL,
                value=row.get("combined_lambda"), threshold="<= 2.5 (O1.5 λ saturation)")
        # Goalkeeper — gg_precision_engine gk_bonus: both GKs NOT liable
        # (cpg <= 1.10) suppresses goals → supports U2.5.
        hc, ac = _num(row.get("home_gk_cpg")), _num(row.get("away_gk_cpg"))
        if hc is None and ac is None:
            add("Goalkeeper", NOT_AVAILABLE)
        else:
            add("Goalkeeper", PASS if (hc or 0) <= 1.10 and (ac or 0) <= 1.10 else FAIL,
                value={"home_gk_cpg": row.get("home_gk_cpg"),
                       "away_gk_cpg": row.get("away_gk_cpg")}, threshold="both <= 1.10")
        return checks
    # ── Underdog To Score — the user's card (2026-09-23): psych > 60
    # (VETOED = FAIL, never N/A), attack beating the fav's concession rate
    # three-fold (9 vs 3 → PASS), the double-strength product, and — ONLY
    # when u2s_psychology carries the full last-3 venue sample — venue
    # scoring. Denominator 3 without venue data, 4 with it (the one
    # deliberate variable denominator in this evaluator).
    if market == "u2s":
        u_row, dog = _u2s_row_for(snap, fid_s, fxn,
                                  row.get("fixture_id"), row.get("fixture") or row.get("Fixture"))
        if u_row and not dog:
            dog = row.get("Underdog") or row.get("underdog_team")
        # 1) Psychology — the calling row's own score first (the win-U2S
        # table rows carry it), else the joined U2S row's. VETOED → FAIL.
        raw_ps = row.get("Psych_Score")
        ps_src = "calling row"
        if raw_ps is None and u_row is not None:
            raw_ps, ps_src = u_row.get("Psych_Score"), "u2s_psychology"
        psych_thr = "> %d (user rule)" % rules["U2S_PSYCH_MIN"]
        if raw_ps is None:
            add("Psychology", NOT_AVAILABLE, threshold=psych_thr,
                source="u2s_psychology", field="Psych_Score")
        elif "VETO" in str(raw_ps).upper():
            add("Psychology", FAIL, value=raw_ps, threshold=psych_thr,
                source=ps_src, field="Psych_Score",
                mapping="VETOED = explicit FAIL verdict, never N/A")
        else:
            ps = _num(raw_ps)
            if ps is None:
                add("Psychology", NOT_AVAILABLE, value=raw_ps,
                    threshold=psych_thr, source=ps_src, field="Psych_Score")
            else:
                add("Psychology",
                    PASS if ps > rules["U2S_PSYCH_MIN"] else FAIL,
                    value=raw_ps, threshold=psych_thr,
                    source=ps_src, field="Psych_Score")
        # 2/3) attack vs the favourite's defensive leak (underdog_base row).
        att, leak, base_src = _u2s_base_pair(snap, req_date, row, fid_s, fxn)
        fold = rules["U2S_ATT_DEF_FOLD"]
        prod_min = rules["U2S_ATT_LEAK_PRODUCT"]
        fold_thr = ("dog attack >= %dx fav defensive leak "
                    "(user example: attack 9 vs leak 3)" % fold)
        prod_thr = "attack x leak >= %d (double-strength signal)" % prod_min
        if att is None or leak is None:
            add("Attack vs Defense", NOT_AVAILABLE, threshold=fold_thr,
                source=base_src, field="dog_att_strength / fav_def_weakness")
            add("Attack × Leak", NOT_AVAILABLE, threshold=prod_thr,
                source=base_src, field="dog_att_strength * fav_def_weakness")
        else:
            no_data = (leak == 0 and att == 0)
            # leak 0 with attack > 0 = the fav conceded NOTHING (a wall the
            # dog cannot beat three-fold) → FAIL; both 0 = no data → N/A.
            add("Attack vs Defense",
                NOT_AVAILABLE if no_data else
                (FAIL if leak == 0 else
                 PASS if att >= fold * leak else FAIL),
                value={"attack": att, "leak": leak},
                threshold=fold_thr, source=base_src,
                field="dog_att_strength / fav_def_weakness",
                mapping="leak = fav's concession rate; 0+0 = no data, "
                        "wall (leak 0, attack > 0) = FAIL")
            add("Attack × Leak",
                NOT_AVAILABLE if no_data else
                PASS if att * leak >= prod_min else FAIL,
                value={"attack": att, "leak": leak,
                       "product": round(att * leak, 2)},
                threshold=prod_thr, source=base_src,
                field="dog_att_strength * fav_def_weakness")
        # 4) venue scoring — the 4th check (win_forecast's own
        #    last_5_wins_at_venue >= 3 of 5; the full u2s_psychology venue
        #    sample is the surrogate). APPENDED only when a source can give
        #    a verdict; otherwise the card stays x/3 (the one deliberate
        #    variable denominator of this evaluator). Source provenance is
        #    set by the check itself — never overwritten here.
        venue_check = _u2s_venue_check(snap, row, u_row, fid_s, fxn, req_date)
        if venue_check is not None:
            checks.append(venue_check)
        return checks

    # ── SOT — the user's 2-check card (2026-09-23): match-level psychology
    # above 60 (gg_psychology's one-score-per-match, WIN psychology
    # fallback) and OVER 2.5 probability above 60% (100 - unders' u25
    # probability, or poisson_over_prob_num directly, fallback).
    if market == "sot":
        # 1) match-level psychology chain
        raw_ps, ps_src = None, ""
        gps_row, gd = _resolve_any(req_date, "gps", fid_s, fxn)
        if gps_row and str(gps_row.get("Psych_Score") or "").strip().upper() \
                not in ("", "N/A", "NONE"):
            raw_ps, ps_src = gps_row.get("Psych_Score"), \
                "gg_psychology @ %s" % gd
        if raw_ps is None:
            wps_row, wd = _resolve_any(req_date, "wps", fid_s, fxn)
            if wps_row:
                for fld in ("Psych_Score", "Audit_Score"):
                    if str(wps_row.get(fld) or "").strip().upper() \
                            not in ("", "N/A", "NONE"):
                        raw_ps, ps_src = wps_row.get(fld), \
                            "win_psychology @ %s (%s)" % (wd, fld)
                        break
        psych_thr = "> %d (user rule)" % rules["SOT_PSYCH_MIN"]
        if raw_ps is None:
            add("Psychology", NOT_AVAILABLE, threshold=psych_thr,
                source="gg_psychology / win_psychology", field="Psych_Score")
        elif "VETO" in str(raw_ps).upper():
            add("Psychology", FAIL, value=raw_ps, threshold=psych_thr,
                source=ps_src, field="Psych_Score",
                mapping="VETOED = explicit FAIL verdict, never N/A")
        else:
            pv = _num(raw_ps)
            if pv is None:
                add("Psychology", NOT_AVAILABLE, value=raw_ps,
                    threshold=psych_thr, source=ps_src, field="Psych_Score")
            else:
                add("Psychology",
                    PASS if pv > rules["SOT_PSYCH_MIN"] else FAIL,
                    value=raw_ps, threshold=psych_thr,
                    source=ps_src, field="Psych_Score")
        # 2) OVER-2.5 probability chain: unders MC (over = 100 - u25) →
        #    over25_forecast Poisson directly. prob_thr is defined UP FRONT:
        #    the unders path must never depend on the fallback branch having
        #    run (that was an UnboundLocalError that silently unaudited SOT).
        prob_thr = "> %d%% (user rule)" % rules["SOT_O25_PROB_MIN"]
        pct, psrc, pfield = None, "", ""
        unr, ud = _resolve_any(req_date, "un", fid_s, fxn)
        if unr:
            f = _frac(unr.get("mc_u25_prob"))
            if f is not None:
                pct, psrc, pfield = f * 100.0, "unders @ %s" % ud, "mc_u25_prob"
        if pct is None:
            o25r, od = _resolve_any(req_date, "o25f", fid_s, fxn)
            if o25r:
                po25 = _num(o25r.get("poisson_over_prob_num"))
                if po25 is not None:
                    pct = 100.0 - po25
                    psrc = "over25_forecast @ %s" % od
                    pfield = "100 - poisson_over_prob_num"
        if pct is None:
            add("Over 2.5 Probability", NOT_AVAILABLE, threshold=prob_thr,
                source="unders mc_u25_prob / over25_forecast poisson",
                field="mc_u25_prob / poisson_over_prob_num")
        else:
            # pct is the UNDER 2.5 probability; Over 2.5 = 100 - pct.
            o25_pct = 100.0 - pct
            add("Over 2.5 Probability",
                PASS if o25_pct > rules["SOT_O25_PROB_MIN"] else FAIL,
                value=round(o25_pct, 1), threshold=prob_thr,
                source=psrc, field=pfield)
        return checks

    # ── FHVI / SHVI (>=7 == TIER 2 GOOD or better, per-file Category gate) ───
    if market in ("fhvi", "shvi"):
        key = "FHVI" if market == "fhvi" else "SHVI"
        field = "fhvi_score" if market == "fhvi" else "shvi_score"
        score = _num(row.get(field))
        if score is None:
            add(key, NOT_AVAILABLE)
        else:
            thr = rules["FHVI_TIER2_THRESHOLD" if market == "fhvi" else "SHVI_TIER2_THRESHOLD"]
            add(key, PASS if score >= thr else FAIL, value=row.get(field), threshold=">= 7")
        return checks

    # Display-only stages carry no applicable intelligence of their own — no
    # checks at all, so the audit is withheld (ipc None) and the frontend
    # hides the cell. A placeholder check would render "0/1" under the
    # fixed-denominator rule, which is why none is emitted.
    return checks
# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_market(market_key, rows, date):
    """Attach an additive `intelligent_pass_count` object to every row of one
    market snapshot. Returns the SAME list (rows mutated additively — no key
    is ever removed, renamed or re-ordered, so settlement/ensure_defaults and
    the frontend's existing fields are untouched).

    The value is a dict {"passed","total","checks"} — the FRONTEND-visible
    counterpart of this module's fixed-denominator rule (total = the market's
    full rule set). It is None only when the market is display-only / has no
    evaluator branch at all, so the frontend simply hides the cell.
    """
    if market_key in DISPLAY_ONLY_MARKETS:
        return rows
    snap = _snapshot(date)
    for row in rows:
        if not isinstance(row, dict):
            continue
        fxn = _fixture_label(row)
        fid = row.get("fixture_id")
        checks = _checks_for_market(market_key, snap, row, fid, fxn, date=date)
        # FIXED-DENOMINATOR RULE: the denominator is the market's FULL rule
        # set — every check the branch defines, whether its data exists or
        # not (WIN=8, GG=4, O2.5=6, …). N/A never shrinks the total; only
        # the numerator (PASSes) varies. Only a market whose branch emitted
        # NO rules at all has no audit (ipc None).
        row["intelligent_pass_count"] = {
            # The market key travels with the audit so the drill-down can
            # open THIS pick's report (pick = the primary object).
            "market": market_key,
            "passed": sum(1 for c in checks if c["result"] == PASS),
            "total": len(checks),
            "checks": checks,
        } if checks else None
    return rows


def evaluate_market_safe(market_key, rows, date):
    """Crash-isolated wrapper: an evaluator failure must never take down a
    picks route. On any exception the rows are returned UNCHANGED (the
    Intelligent Pass column simply renders empty)."""
    try:
        return evaluate_market(market_key, rows, date)
    except Exception:
        return rows


def _team_context(snap, fid_s, fxn, team_name):
    """Raw EXISTING intelligence values for the Team Intelligence page — the
    numbers behind each PASS/FAIL. Read-only passthrough of engine fields:
    nothing is recomputed, nothing is fabricated (missing → None)."""
    ctx = {}
    home, away = _split_fixture(fxn)

    # WIN side row (parity_score, form counters) — the selected team's own row
    side = _win_side_row(snap, fid_s, fxn, team_name)
    if side:
        ctx["win_side"] = {
            "parity_score": side.get("parity_score"),
            "last_5_wins_overall": side.get("last_5_wins_overall"),
            "last_5_wins_at_venue": side.get("last_5_wins_at_venue"),
            "last_5_goals_scored": side.get("last_5_goals_scored"),
            "opp_last_5_goals_scored": side.get("opp_last_5_goals_scored"),
            "opp_last_5_losses": side.get("opp_last_5_losses"),
            "win_odds": side.get("win_odds"),
            "side": side.get("side"),
        }

    # DNA v2 market factors — every existing market section for this fixture
    markets = _resolve(snap, "dna", fid_s, fxn)
    if markets:
        dna = {}
        for mkey, mv in markets.items():
            factors = (mv or {}).get("factors") or []
            dna[mkey] = {
                "home_count": (mv or {}).get("home_count"),
                "away_count": (mv or {}).get("away_count"),
                "factors": [
                    {"name": f.get("name"), "home_value": f.get("home_value"),
                     "away_value": f.get("away_value"), "winner": f.get("winner")}
                    for f in factors
                ],
            }
        ctx["dna_market_factors"] = dna

    # DNA engine's own clash verdicts for this fixture (market signals)
    clash = _resolve(snap, "dna_clash", fid_s, fxn)
    if clash:
        ctx["dna_clash"] = {
            "market_signals": clash.get("market_signals"),
            "combined_goal_intent": clash.get("combined_goal_intent"),
            "combined_box_dominance": clash.get("combined_box_dominance"),
            "overall_structural_edge": clash.get("overall_structural_edge"),
            "home_team": clash.get("home_team"),
            "away_team": clash.get("away_team"),
        }

    # SOT row (verdict / game script / totals)
    s = _resolve(snap, "sot", fid_s, fxn)
    if s:
        ctx["sot"] = {k: s.get(k) for k in (
            "Verdict", "Game_Script", "Proj_SOT", "Consistency", "Momentum",
            "Proj_Goals", "Tempo") if k in s}

    # Corner aggregator (friction / chaos / expected corners)
    c = _resolve(snap, "cagg", None, fxn)
    if c:
        ctx["corners"] = {k: c.get(k) for k in (
            "Friction", "Chaos_Rating", "Total_Exp", "Master_Score", "Tier",
            "Match_Flow", "True_Corner_Fav") if k in c}

    # WIN psychology row (signed nets)
    w = _resolve(snap, "wps", fid_s, fxn)
    if w:
        ctx["win_psychology"] = {k: w.get(k) for k in (
            "H_Base", "A_Base", "Audit_Score", "Psych_Score", "Audit_Verdict",
            "Quality_Grade", "Spear") if k in w}

    # Underdog rows (identity + the two multipliers + longshot probability)
    ud = _resolve(snap, "ud", fid_s, fxn)
    if ud:
        ctx["underdog_base"] = {k: ud.get(k) for k in (
            "underdog_team", "dog_att_strength", "fav_def_weakness",
            "dog_score_prob", "dog_is_hot", "dog_due_goal", "fav_cs_streak",
            "dog_venue_wins", "parity_gap") if k in ud}
    uda = _resolve(snap, "uda", fid_s, fxn)
    if uda:
        ctx["underdog_audit"] = {k: uda.get(k) for k in (
            "underdog_team", "Dog_Score_Prob", "Audit_Verdict",
            "Audit_Real_Prob", "parity_gap", "Dominance_Gap") if k in uda}

    # Draw row (Monte-Carlo draw probability + engine tier gates)
    d = _resolve(snap, "draw", fid_s, fxn)
    if d:
        ctx["draw"] = {k: d.get(k) for k in (
            "mc_draw_prob", "parity", "dmi", "composite_draw_score", "tier",
            "value_edge", "most_likely_draw_score") if k in d}

    # Unders u25 row (expected goals + keepers)
    un = _resolve(snap, "un", fid_s, fxn)
    if un:
        ctx["unders"] = {k: un.get(k) for k in (
            "combined_lambda", "mc_u25_prob", "u25_score", "u25_tier",
            "u25_signals_fired", "home_gk_cpg", "away_gk_cpg") if k in un}

    # O2.5 forecast row (the engine's own council inputs)
    o25 = _resolve(snap, "o25f", fid_s, fxn)
    if o25:
        ctx["over25"] = {k: o25.get(k) for k in (
            "kill_switch_pass", "poisson_over_prob_num", "council_votes",
            "pos_gap", "parity_diff", "h2h_overs_last_5",
            "combined_gs_last_5", "o25_odds") if k in o25}

    # GG / O1.5 composite rows (heads 0 and 1)
    ggc = _resolve(snap, "ggc", fid_s, fxn)
    if ggc:
        ctx["gg"] = {k: ggc.get(k) for k in (
            "gg_score", "gg_tier", "gg_signals_fired", "mc_btts_prob",
            "h2h_btts_rate", "home_gk_cpg", "away_gk_cpg",
            "home_gk_liable", "away_gk_liable") if k in ggc}
    o15 = _resolve(snap, "o15c", fid_s, fxn)
    if o15:
        ctx["over15"] = {k: o15.get(k) for k in (
            "o15_score", "o15_tier", "combined_lambda", "lambda_home",
            "lambda_away", "mc_over15_prob", "home_gk_liable",
            "away_gk_liable") if k in o15}

    # FHVI / SHVI rows
    for mk, key, field in (("fhvi", "fhvi", "fhvi_score"),
                           ("shvi", "shvi", "shvi_score")):
        r = _resolve(snap, mk, fid_s, fxn)
        if r:
            ctx[mk] = {k: r.get(k) for k in (
                field, "Category", "fhvi_label", "shvi_label",
                "fh_pressure", "sh_pressure", "comb_fh_r", "comb_sh_r",
                "ht_score", "ft_score", "country") if k in r}
    return ctx


def _locate_fixture(date, snap, team_name):
    """Find a team's fixture via the WIN-side registry — across the source
    window, because the WIN pack is cross-day: the requested date is tried
    first, then the neighbours. Strong match: a row naming the team
    (team_name on side rows, Target on apex rows, Master_Pick on psychology
    rows). Weak fallback: a fixture-level row (no team identity) whose label
    contains the team — this keeps the report resolvable for fixtures whose
    ONLY saved rows are fixture-level (e.g. apex-only runs). Returns
    (fixture_id, rows, canonical fixture_label).
    IMPORTANT: the returned label is always the date's CANONICAL 'home vs
    away' label from the id-bearing engines — never a swapped apex label —
    so every name-keyed join downstream resolves."""
    t = _norm(team_name or "")
    if not t:
        return "", [], ""

    def _row_names(r):
        return [n for n in (r.get("team_name"), r.get("Target"),
                            r.get("Master_Pick")) if n]

    for d in _window_dates(date):
        dsnap = snap if d == date else _snapshot(d)
        # First pass: exact team-side match.
        for fid, rows in sorted((dsnap.get("win_by_id") or {}).items()):
            hit = next((r for r in rows
                        if any(_norm(n) == t for n in _row_names(r))), None)
            if hit:
                canon = (dsnap.get("label_by_id") or {}).get(fid, "")
                return fid, rows, canon or _fixture_label(hit)
        # Second pass: label-side fallback. A fixture-level row names at most
        # ONE participant (apex rows carry Target); the other side exists only
        # in the label. Match the fixture label's SIDES (exact normalised
        # equality) — containment would let 'Arsenal' resolve an
        # 'Arsenal U21 vs Brighton U21' fixture.
        for fid, rows in sorted((dsnap.get("win_by_id") or {}).items()):
            for r in rows:
                label = _fixture_label(r) or ""
                if not label:
                    continue
                parts = re.split(r"\s+vs\.?\s+", label, flags=re.I)
                if any(_norm(p) == t for p in parts if p.strip()):
                    canon = (dsnap.get("label_by_id") or {}).get(fid, "")
                    return fid, rows, canon or label
    return "", [], ""


def _opponent_from(rows, fxn, team_name):
    """The other side of the fixture: from side rows when present, else
    derived from the fixture label."""
    t = _norm(team_name or "")
    for r in rows:
        n = r.get("team_name")
        if n and _norm(n) != t:
            return n
    parts = [p.strip() for p in re.split(r"\s+vs\.?\s+", fxn or "", flags=re.I) if p.strip()]
    return next((p for p in parts if _norm(p) != t and _norm(t) not in _norm(p)), "")


def _get_market_intelligence(team_name, date, market):
    """SINGLE-MARKET report payload — the pick is the primary object.

    Identity: fixture/date + team + market. Only the requested market's
    evaluator branch runs, so no other market's checks can appear here (the
    payload carries `score` + `checks`, never a `markets` map). Reads the
    SAME on-disk snapshots as the market pages — zero new data acquisition,
    zero fabricated values (missing intelligence stays NOT_AVAILABLE and can
    only lower the numerator; the denominator stays the market's full rule
    set)."""
    snap = _snapshot(date)

    # Locate the team's fixture via the WIN-side fixture registry (side rows
    # carry team_name; apex rows carry Target; fixture-level-only fixtures
    # resolve by label containment — the engines saved, so it must resolve).
    # Window-aware: the WIN pack is cross-day, so the fixture may live in a
    # neighbouring date's registry — but the report always plays back the
    # REQUESTED date's story, and every source join happens over the window.
    fixture_id, side_rows_hit, fxn = _locate_fixture(date, snap, team_name)
    base = {"team": team_name, "date": date, "market": market,
            "market_label": TEAM_INTELLIGENCE_MARKETS[market]}
    if not fxn:
        return dict(base, fixture="", fixture_id="", fixture_found=False,
                    opponent="", prediction=None, score=None, checks=[])

    fid_s = _idstr(fixture_id)
    opp = _opponent_from(side_rows_hit, fxn, team_name)

    # THE PAGE/MARKET IS AUTHORITATIVE: run ONLY this market's evaluator
    # branch, seeded with the same per-fixture row shape the market tables use.
    engine_key = _MARKET_EVALUATOR_ALIASES[market][0]
    if market in ("win", "win_psychology"):
        row = {"Target": team_name}          # the pick: {team} to win
    elif market == "u2s":
        row = {"fixture_id": fid_s, "fixture": fxn}
    elif market == "draw":
        row = _resolve(snap, "draw", fid_s, fxn) or {}
    elif market == "unders":
        row = _resolve(snap, "un", fid_s, fxn) or {}
    elif market == "fhvi":
        row = _resolve(snap, "fhvi", fid_s, fxn) or {}
    elif market == "shvi":
        row = _resolve(snap, "shvi", fid_s, fxn) or {}
    elif market == "gg":
        # The gg branch reads its psychology verdict from the GG supreme row
        # itself (Psych_Score) — seed it exactly as the GG table rows do.
        row = _resolve(snap, "gsup", fid_s, fxn) or {}
    else:
        # gg_precision / gg_o15 / over25 / over15:
        # their branches join the fixture's own engine rows internally.
        row = {}
    checks = _checks_for_market(engine_key, snap, row, fid_s, fxn, date=date)
    # FIXED-DENOMINATOR RULE (matches evaluate_market): total is the market's
    # FULL rule set; N/A never shrinks it — only the numerator varies.
    score = {
        "passed": sum(1 for c in checks if c["result"] == PASS),
        "total": len(checks),
    }
    return dict(base, fixture=fxn, fixture_id=fixture_id, fixture_found=True,
                opponent=opp,
                prediction=team_name if market in ("win", "win_psychology") else None,
                score=score, checks=checks)


def get_team_intelligence(team_name, date, market=None):
    """Read-only composition for the Team Intelligence page.

    market=None → legacy all-markets payload (unchanged behaviour).
    market=<canonical key> → SINGLE-MARKET report (the requested
    architecture): fixture/date + team + market identity, only that market's
    checks. An unknown market raises ValueError (API maps it to 400).
    ZERO network calls — pure local file reads of the same snapshots the
    fixture pages use."""
    # MARKET-SPECIFIC REPORT: the pick is the primary object. Only the
    # requested market's evaluator runs — no cross-market composition.
    if market is not None:
        if market not in TEAM_INTELLIGENCE_MARKETS:
            raise ValueError(
                "unknown market %r — expected one of %s"
                % (market, sorted(TEAM_INTELLIGENCE_MARKETS)))
        return _get_market_intelligence(team_name, date, market)
    snap = _snapshot(date)

    # Same locator as the single-market report: side rows carry team_name,
    # apex rows carry Target, fixture-level-only rows resolve by label.
    fixture_id, side_rows_hit, fxn = _locate_fixture(date, snap, team_name)
    if not fxn:
        return {"team": team_name, "date": date, "fixture": "",
                "fixture_id": "", "fixture_found": False, "markets": {}}

    fid_s = str(fixture_id)
    opp = _opponent_from(side_rows_hit, fxn, team_name)
    markets = {}

    def _mark(key, checks):
        # FIXED-DENOMINATOR RULE: total = the market's full rule set, N/A
        # checks included; only the numerator (PASSes) varies.
        markets[key] = {
            "passed": sum(1 for c in checks if c["result"] == PASS),
            "total": len(checks),
            "checks": checks,
        }

    _mark("win", _checks_for_market("win_apex", snap, {"Target": team_name}, fid_s, fxn, date=date))
    _mark("win_psychology", _checks_for_market("win_apex", snap,
                                                {"Target": team_name}, fid_s, fxn, date=date))
    _mark("gg", _checks_for_market("gg_supreme", snap, {}, fid_s, fxn, date=date))
    _mark("gg_precision", _checks_for_market("gg_precision", snap, {}, fid_s, fxn, date=date))
    _mark("over25", _checks_for_market("over25_apex", snap, {}, fid_s, fxn, date=date))
    _mark("over15", _checks_for_market("over15", snap, {}, fid_s, fxn, date=date))
    _mark("corners", _checks_for_market("corners_aggregator", snap, {}, fid_s, fxn, date=date))
    _mark("draw", _checks_for_market(
        "draw", snap, _resolve(snap, "draw", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("unders", _checks_for_market(
        "unders_u25", snap, _resolve(snap, "un", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("u2s", _checks_for_market("u2s", snap, {"fixture_id": fid_s, "fixture": fxn}, fid_s, fxn, date=date))
    _mark("fhvi", _checks_for_market(
        "fhvi", snap, _resolve(snap, "fhvi", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("shvi", _checks_for_market(
        "shvi", snap, _resolve(snap, "shvi", fid_s, fxn) or {}, fid_s, fxn, date=date))
    _mark("sot", _checks_for_market(
        "sot", snap, _resolve(snap, "sot", fid_s, fxn) or {}, fid_s, fxn, date=date))
    return {
        "team": team_name, "date": date, "fixture": fxn, "fixture_id": fixture_id,
        "opponent": opp, "fixture_found": True, "markets": markets,
        "context": _team_context(snap, fid_s, fxn, team_name),
    }






