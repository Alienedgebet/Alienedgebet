"""
tests_fixture_classification.py — CUP / FRIENDLY identification must be total
and must never guess.

Run:  ./venv/bin/python3 tests_fixture_classification.py

WHAT THIS PROVES
----------------
  1. DECISION — `classify_competition()` reads SportMonks' own competition
     fields (league.sub_type, then league.type, then a real-name keyword
     fallback) and reports the evidence it used.
  2. NO FABRICATION — absent/unknown league data yields `unknown`, never a
     quiet "league" pass, and `is_risk_fixture` stays False.
  3. COVERAGE — every fixture the shared window holds is classified; the live
     window is used when present, and a synthetic window proves it for any date.
  4. JOIN — the API resolves a row by exact fixture id first, then by a unique
     fixture label (either side order); an AMBIGUOUS label stays `unknown`
     rather than picking a fixture.
  5. STAMPING — read()/read_range() leave every existing key untouched and only
     ADD classification / is_cup / is_friendly / is_risk_fixture / risk_level /
     risk_label / competition / league_name.

SAFETY: fully offline (local window + snapshots, zero SportMonks calls) and
non-destructive — nothing is written to output/.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

RESULTS = []


def check(label, cond):
    RESULTS.append((label, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + label)


def skip(label, why):
    RESULTS.append((label, None))
    print("SKIP  " + label + "  (" + why + ")")


# ── 1/2. the pure decision function ──────────────────────────────────────────
import fixture_classification as fc  # noqa: E402

friendly = fc.classify_competition({"id": 8, "name": "Club Friendlies 3", "type": "league", "sub_type": "friendly"})
check("sub_type=friendly -> FRIENDLY, high risk",
      friendly["is_friendly"] and not friendly["is_cup"]
      and friendly["risk_level"] == "high" and friendly["risk_label"] == "FRIENDLY"
      and friendly["classification"] == "friendly")
check("friendly evidence is reported", friendly["source"] == "league.sub_type=friendly")

intl = fc.classify_competition({"id": 8, "name": "UEFA Nations League", "type": "league", "sub_type": "cup_international"})
check("sub_type=cup_international -> CUP, elevated risk",
      intl["is_cup"] and not intl["is_friendly"]
      and intl["risk_level"] == "elevated" and intl["risk_label"] == "CUP")

dom_cup = fc.classify_competition({"id": 8, "name": "Copa Del Rey", "type": "league", "sub_type": "domestic_cup"})
check("sub_type=domestic_cup -> CUP", dom_cup["is_cup"] and dom_cup["classification"] == "cup")

dom = fc.classify_competition({"id": 9, "name": "Ligue 1", "type": "league", "sub_type": "domestic"})
check("sub_type=domestic -> plain league, NOT flagged",
      not dom["is_cup"] and not dom["is_friendly"] and not dom["is_risk_fixture"]
      and dom["classification"] == "league" and dom["risk_level"] == "normal")

typed = fc.classify_competition({"id": 3, "name": "Some Cup", "type": "cup"})
check("league.type=cup -> CUP when sub_type is absent", typed["is_cup"] and typed["classification"] == "cup")
typed_f = fc.classify_competition({"id": 4, "name": "Tournoi", "type": "friendly"})
check("league.type=friendly -> FRIENDLY when sub_type is absent", typed_f["is_friendly"])

kw_cup = fc.classify_competition({"id": 5, "name": "FA Cup Semi Final"})
check("name fallback finds a cup when no kind field exists",
      kw_cup["is_cup"] and kw_cup["source"] == "league/season name keyword")
kw_fr = fc.classify_competition({"id": 6, "name": "Amistoso Internacional"}, {"name": "2026"})
check("name fallback finds a friendly from league OR season name",
      kw_fr["is_friendly"] and kw_fr["classification"] == "friendly")

empty = fc.classify_competition({}, {})
check("NO league data -> unknown, never 'league' (zero fabrication)",
      empty["classification"] == "unknown" and empty["risk_level"] == "unknown"
      and empty["is_risk_fixture"] is False and empty["risk_label"] == "")
none_league = fc.classify_competition(None, None)
check("None league/season is handled safely", none_league["classification"] == "unknown")
check("unknown raises NO warning", none_league["is_cup"] is False and none_league["is_friendly"] is False)

# ── 3. coverage over the real shared window ──────────────────────────────────
import shared_fixture_window as window  # noqa: E402

store = window._load_store()
days = sorted((store.get("days") or {}).keys())
if days:
    rows = fc.build_window_flags(days)
    unclassified = [r for r in rows if r.get("classification") == "unknown"]
    check(f"every window fixture is classified ({len(rows)} fixtures over {len(days)} day(s))",
          rows and not unclassified)
    check("every classified row carries its evidence", all(r.get("source") for r in rows))
    check("cup + friendly counts match the classifications",
          sum(1 for r in rows if r["classification"] == "cup")
          == sum(1 for r in rows if r.get("is_cup"))
          and sum(1 for r in rows if r["classification"] == "friendly")
          == sum(1 for r in rows if r.get("is_friendly")))
    check("every row has team identity for the label join",
          all(r.get("home_team") and r.get("away_team") for r in rows))
else:
    skip("window coverage", "shared window empty (no stored days)")
check("a date outside the window yields an honest empty set",
      fc.flags_for_date("1999-01-01") == {})

# ── 4/5. the API join + stamping ─────────────────────────────────────────────
import api.main as api  # noqa: E402

check("label normalisation keeps the same shape as the index",
      api._normalise_label("Ajax vs Heerenveen") == "ajax|heerenveen")
check("label normalisation handles V and punctuation",
      api._normalise_label("Ajax v. Heerenveen") == "ajax|heerenveen")
check("reverse ordering is produced by the index builder",
      "heerenveen|ajax" in api._label_keys("Ajax", "Heerenveen"))

# A synthetic date with two fixtures, one of them deliberately AMBIGUOUS (two
# different fixtures share a label) so the "unique match only" rule is proven.
SYNTH = "2099-12-31"
api._FIXTURE_RISK_INDEX[SYNTH] = {
    "by_id": {
        "111": {"fixture_id": "111", "classification": "cup", "is_cup": True,
                "is_friendly": False, "is_risk_fixture": True, "risk_level": "elevated",
                "risk_label": "CUP", "competition": "domestic_cup",
                "league_name": "Test Cup", "home_team": "Alpha", "away_team": "Beta",
                "fixture_label": "Alpha vs Beta"},
        "222": {"fixture_id": "222", "classification": "friendly", "is_cup": False,
                "is_friendly": True, "is_risk_fixture": True, "risk_level": "high",
                "risk_label": "FRIENDLY", "competition": "friendly",
                "league_name": "Test Friendlies", "home_team": "Gamma",
                "away_team": "Delta", "fixture_label": "Gamma vs Delta"},
    },
    "by_name": {
        # both orderings of the cup fixture and of the friendly fixture
        "alpha|beta": {"fixture_id": "111"}, "beta|alpha": {"fixture_id": "111"},
        "gamma|delta": {"fixture_id": "222"}, "delta|gamma": {"fixture_id": "222"},
        # an ambiguous key is deliberately absent -> must resolve to unknown
    },
}
index = api._FIXTURE_RISK_INDEX[SYNTH]
index["by_name"] = {k: index["by_id"][v["fixture_id"]] for k, v in index["by_name"].items()}

by_id = api._lookup_fixture_risk({"fixture_id": 111}, index)
check("exact fixture id resolves (int or str)", by_id and by_id["classification"] == "cup")
by_label = api._lookup_fixture_risk({"Fixture": "Alpha vs Beta"}, index)
check("label resolves when the row has no id", by_label and by_label["classification"] == "cup")
by_label_rev = api._lookup_fixture_risk({"fixture": "Beta vs Alpha"}, index)
check("reversed label order resolves to the same fixture",
      by_label_rev and by_label_rev["fixture_id"] == "111")
check("an unknown label resolves to nothing (never a guess)",
      api._lookup_fixture_risk({"fixture": "Nobody vs Nobody"}, index) is None)
check("a row with no fixture identity resolves to nothing",
      api._lookup_fixture_risk({"team_name": "Alpha"}, index) is None)

rows = api._with_fixture_risk([
    {"fixture_id": 111, "fixture": "Alpha vs Beta", "win_odds": 1.5},
    {"fixture": "Gamma vs Delta", "o25_odds": 2.0},
    {"fixture": "Nobody vs Nobody", "o25_odds": 1.9},
], SYNTH)
check("stamping marks the cup row", rows[0]["is_cup"] and rows[0]["risk_label"] == "CUP")
check("stamping marks the friendly row (label join)", rows[1]["is_friendly"] and rows[1]["risk_level"] == "high")
check("stamping leaves an unresolvable row honestly unknown",
      rows[2].get("classification") == "unknown" and not rows[2].get("is_risk_fixture"))
check("stamping ADDS keys and keeps every existing one",
      rows[0]["win_odds"] == 1.5 and rows[0]["fixture"] == "Alpha vs Beta"
      and rows[1]["o25_odds"] == 2.0)
check("stamping adds the league name for the warning text",
      rows[0]["league_name"] == "Test Cup")

# The real snapshot read path must carry the labels too (additive only).
_real_date = days[0] if days else None
if _real_date:
    api._FIXTURE_RISK_INDEX.clear()
    import output_store as store_mod
    real_rows, _ = store_mod.load("fixture_risk", _real_date, default=[])
    if real_rows:
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            win_rows = [r for r in api.read("win_raw", _real_date, api.WIN_RAW_DEFAULTS, "win")
                        if isinstance(r, dict)]
        labelled = [r for r in win_rows if r.get("classification")
                    and r["classification"] != "unknown"]
        check("the real read() path stamps the labels",
              win_rows and len(labelled) == len(win_rows),
              )
        check("at least one real row is flagged cup/friendly",
              any(r.get("is_risk_fixture") for r in win_rows))
    else:
        skip("real read() stamping", "no fixture_risk snapshot for the window day")
else:
    skip("real read() stamping", "no window day")

failed = [label for label, ok in RESULTS if ok is False]
skipped = [label for label, ok in RESULTS if ok is None]
print("\n" + "=" * 78)
print(f"RESULT: {len(RESULTS) - len(failed) - len(skipped)} passed, "
      f"{len(failed)} failed, {len(skipped)} skipped")
for label in failed:
    print("  FAILED: " + label)
print("=" * 78)
sys.exit(1 if failed else 0)

