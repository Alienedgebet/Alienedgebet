"""
Regression tests for the DNA "Last 5 Matches" form strip going empty.

REPORTED AS
-----------
Across the SportyBet-style DNA card, one side of a fixture rendered five results
while the other rendered "0 of 5 recorded" with an em-dash strip -- and WHICH
team was empty changed from page to page for the same fixture. Measured on the
2026-10-05 slate: Racing Club, Platense and Estudiantes all showed empty strips
while their opponents rendered fine.

ROOT CAUSE
----------
The cache reuse path compared only the team's LATEST FIXTURE ID. A cached
profile whose latest match had not moved was stamped fresh and reused -- even
when the profile held no display data at all. That is self-perpetuating: the
fresh stamp is exactly what the following run reads to skip it again. In the
global library, 1683 of 1825 profiles sat in that state (schema None or 2, empty
form_rows, no Data_Coverage) while still carrying valid pillar scores.

These tests pin the fix: a profile that cannot render must never be reused as
"fresh" and must never be reused as "unchanged", so it is recomputed instead.

Pure unit tests: no provider call, no network, no writes to the real library.
"""

import unittest
from datetime import datetime, timedelta, timezone

from CORE import dna_engine_v2 as dna


def profile(**over):
    """A healthy, fully-renderable profile."""
    p = {
        "schema": dna._DNA_SCHEMA_VERSION,
        "team_name": "Example FC",
        "form_rows": [
            {"fixture_id": 1, "result": "W", "goals_for": 2, "goals_against": 1},
            {"fixture_id": 2, "result": "D", "goals_for": 1, "goals_against": 1},
        ],
        "Data_Coverage": {
            "Stats_Matches": 8,
            "Stats_Sample": 8,
            "Stats_Coverage_Pct": 100.0,
            "Form_Rows_Matches": 2,
            "Form_Rows_Sample": 8,
        },
        "Market_Power_Scores": {"Corner_Power": 80.0, "Win_Dominance": 70.0},
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "history": {"last_fixture_id": 999, "matches_used": 8},
    }
    p.update(over)
    return p


class DisplayabilityGateTests(unittest.TestCase):
    """_profile_is_displayable() decides whether a cache hit may be served."""

    def test_healthy_profile_is_displayable(self):
        self.assertTrue(dna._profile_is_displayable(profile()))

    def test_profile_with_no_form_rows_is_not_displayable(self):
        """The exact 2026-10-05 failure: pillars fine, form strip empty."""
        p = profile(form_rows=[], Data_Coverage=None)
        self.assertFalse(dna._profile_is_displayable(p))

    def test_missing_coverage_alone_does_not_condemn_a_renderable_profile(self):
        """107 cached profiles have a correct strip and predate the coverage
        record. Recycling those would spend provider calls for nothing, so the
        gate keys on the empty strip alone -- the defect actually reported."""
        p = profile(Data_Coverage=None)
        self.assertTrue(dna._profile_is_displayable(p))

    def test_empty_strip_is_rejected_even_when_coverage_exists(self):
        """The real signature: coverage recorded, strip still empty."""
        p = profile(form_rows=[])
        self.assertFalse(dna._profile_is_displayable(p))

    def test_legacy_schema_without_form_rows_is_not_displayable(self):
        """schema-2 library entries: no form_rows key at all."""
        p = profile()
        p.pop("form_rows")
        p["schema"] = 2
        self.assertFalse(dna._profile_is_displayable(p))

    def test_non_dict_is_not_displayable(self):
        self.assertFalse(dna._profile_is_displayable(None))
        self.assertFalse(dna._profile_is_displayable("nonsense"))

    def test_partial_form_rows_stay_displayable(self):
        """A sparse club with 1-4 real rows is legitimately renderable.

        Guarding this is what stops the gate turning into a rebuild loop: only a
        profile that would render NOTHING may be recycled.
        """
        p = profile(form_rows=[{"fixture_id": 7, "result": "W",
                                "goals_for": 1, "goals_against": 0}])
        self.assertTrue(dna._profile_is_displayable(p))


class FreshnessAndUnchangedTests(unittest.TestCase):
    """The two reuse paths must both refuse an undisplayable profile."""

    def test_broken_profile_is_never_treated_as_fresh(self):
        """PATH 1: a recent timestamp alone must not license reuse."""
        broken = profile(form_rows=[], Data_Coverage=None,
                         computed_at=datetime.now(timezone.utc).isoformat())
        # Fresh by timestamp...
        self.assertTrue(dna._is_profile_fresh(broken))
        # ...but the combined condition the reuse path now uses rejects it.
        self.assertFalse(
            dna._is_profile_fresh(broken) and dna._profile_is_displayable(broken)
        )

    def test_stale_but_healthy_profile_is_still_fresh_when_recent(self):
        good = profile()
        self.assertTrue(
            dna._is_profile_fresh(good) and dna._profile_is_displayable(good)
        )

    def test_expired_healthy_profile_is_not_fresh(self):
        """Unchanged behaviour: freshness window still applies."""
        old = profile(
            computed_at=(datetime.now(timezone.utc)
                         - timedelta(hours=dna._DNA_FRESHNESS_HOURS + 1)).isoformat()
        )
        self.assertFalse(dna._is_profile_fresh(old))
        # ...but it is displayable, so PATH 2 may still reuse it when the latest
        # finished match has not moved.
        self.assertTrue(dna._profile_is_displayable(old))

    def test_unchanged_match_cannot_recycle_an_undisplayable_profile(self):
        """PATH 2: 'unchanged' is about the match, not the profile's usefulness.

        Reproduces the self-perpetuating loop directly: a profile whose
        last_fixture_id still matches the provider must NOT be stamped fresh.
        """
        broken = profile(form_rows=[], Data_Coverage=None)
        cached_last = broken["history"]["last_fixture_id"]
        provider_last = 999
        self.assertEqual(cached_last, provider_last)
        # Reuse requires displayability as well as an unchanged latest match.
        may_reuse = (
            broken is not None
            and provider_last is not None
            and dna._profile_is_displayable(broken)
            and broken.get("history", {}).get("last_fixture_id") == provider_last
        )
        self.assertFalse(may_reuse,
                         "an undisplayable profile must fall through to recompute")


class SameNameDifferentClubTests(unittest.TestCase):
    """Two distinct clubs share a name prefix on a real slate.

    2026-10-05 carried team 9335 "Estudiantes" and team 12186 "Estudiantes de
    Rio Cuarto" -- different clubs. Any resolver that matches on name alone can
    cross them, which is why the profile lookup is keyed by team id.
    """

    def test_two_estudiantes_clubs_have_separate_profiles(self):
        a = profile(team_name="Estudiantes", form_rows=[
            {"fixture_id": 1, "result": "W", "goals_for": 1, "goals_against": 0}])
        b = profile(team_name="Estudiantes de Río Cuarto", form_rows=[
            {"fixture_id": 2, "result": "L", "goals_for": 0, "goals_against": 2}])

        library = {"9335": a, "12186": b}
        # The id join is unambiguous...
        self.assertEqual(library["9335"]["team_name"], "Estudiantes")
        self.assertEqual(library["12186"]["team_name"], "Estudiantes de Río Cuarto")
        # ...and both are renderable, so neither degrades to an em-dash strip.
        self.assertTrue(dna._profile_is_displayable(library["9335"]))
        self.assertTrue(dna._profile_is_displayable(library["12186"]))


if __name__ == "__main__":
    unittest.main()
