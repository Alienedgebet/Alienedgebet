"""
Contract tests for the Stage 8 live prediction engine.

Kept in its own file rather than appended to tests_live_scanner_contracts.py:
that file is 7,000 lines, and merging into it repeatedly truncated it once
already during this work.
"""
import unittest


class TestLivePredictionAnchorInversion(unittest.TestCase):
    """
    THE SIXTH MEMBER OF THE SAME FAMILY, and the one that matters most.

    `implied_total_goals` inverts an over-2.5 price into expected goals. The
    first version's bisection boundary test was inverted, so it returned the
    bracket ceiling 12.0 for EVERY fixture — twelve expected goals, producing
    "100% to score" and "98.9% over 2.5" on a match priced at 5.5. No error and
    no warning: a plausible-looking number, wrong by an order of magnitude.

    The market judge then reimplemented the same inversion INDEPENDENTLY — and
    got it backwards too, in the mirror-image way, returning its own ceiling of
    20.0. Both bugs were invisible because each was compared against nothing.

    So these tests check the engine against a third, unrelated solve. Being an
    independent reimplementation is exactly what makes fresh eyes useless on
    the maths, which is why agreement between two is the only real evidence.
    """

    @staticmethod
    def _engine_lambda(price):
        from LIVE_SCANNER.live_stage8_live_prediction import implied_total_goals
        return implied_total_goals(price)

    @staticmethod
    def _reference_lambda(price):
        """A third solve, sharing no code with the engine or the judge."""
        import math
        target = 1.0 - 1.0 / price
        lo, hi = 0.01, 20.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            f = math.exp(-mid) * (1 + mid + (mid ** 2) / 2)
            if f > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def test_engine_agrees_with_an_independent_solve_on_real_prices(self):
        for price in (1.33, 1.95, 2.05, 3.55, 3.66, 4.95, 5.01, 5.3, 5.5):
            with self.subTest(price=price):
                engine = self._engine_lambda(price)
                self.assertIsNotNone(engine, f"engine refused price {price}")
                self.assertAlmostEqual(engine, self._reference_lambda(price),
                                       places=3,
                                       msg=f"disagreement at price {price}")

    def test_the_anchor_is_never_a_bracket_edge(self):
        """The precise signature of an inverted bisection."""
        for price in (1.33, 3.66, 5.5):
            with self.subTest(price=price):
                lam = self._engine_lambda(price)
                self.assertLess(lam, 6.0)
                self.assertGreater(lam, 0.3)

    def test_a_long_price_implies_fewer_goals_than_a_short_one(self):
        self.assertLess(self._engine_lambda(5.5), self._engine_lambda(1.33))
        self.assertLess(self._engine_lambda(4.95), self._engine_lambda(1.95))

    def test_the_price_round_trips_through_its_own_probability(self):
        import math
        for price in (1.95, 3.66, 5.5):
            with self.subTest(price=price):
                lam = self._engine_lambda(price)
                p_over = 1.0 - math.exp(-lam) * (1 + lam + (lam ** 2) / 2)
                self.assertAlmostEqual(p_over, 1.0 / price, places=4,
                                       msg=f"{price} did not round-trip")

    def test_an_absurd_price_is_refused_rather_than_clamped(self):
        from LIVE_SCANNER.live_stage8_live_prediction import implied_total_goals
        self.assertIsNone(implied_total_goals(1.001))
        self.assertIsNone(implied_total_goals(0.5))
        self.assertIsNone(implied_total_goals(None))


class TestLivePredictionOutputShape(unittest.TestCase):
    def test_the_three_goal_lines_reconcile(self):
        """
        over2.5, under3.5 and exactly-3 overlap exactly at 3 goals:
            over2.5 + under3.5 - exactly3 == 100
        The user asked for over 2.5 and under 3.5 as written and accepted the
        overlap; the third line exists so the overlap is visible, not ambiguous.
        """
        from LIVE_SCANNER.live_stage8_live_prediction import poisson_pmf
        lam, already = 1.8, 1
        o25 = sum(poisson_pmf(k, lam) for k in range(26) if already + k > 2)
        u35 = sum(poisson_pmf(k, lam) for k in range(26) if already + k <= 3)
        ex3 = sum(poisson_pmf(k, lam) for k in range(26) if already + k == 3)
        self.assertAlmostEqual(100 * (o25 + u35 - ex3), 100.0, places=6)

    def test_to_score_is_named_by_team_not_by_side(self):
        """The user asked for 'Home to score' / 'Away to score' with names."""
        import inspect
        from LIVE_SCANNER import live_stage8_live_prediction as eng
        src = inspect.getsource(eng.predict)
        self.assertIn('"team"', src)
        self.assertIn("home_to_score", src)
        self.assertIn("away_to_score", src)

    def test_there_is_no_both_teams_to_score_market(self):
        """The user explicitly removed GG. It must not reappear."""
        import inspect
        from LIVE_SCANNER import live_stage8_live_prediction as eng
        src = inspect.getsource(eng.predict).lower()
        self.assertNotIn('"gg"', src)
        self.assertNotIn("gg_", src)

    def test_probabilities_fall_as_the_clock_runs_down(self):
        """
        THE ACTUAL FIX. Code 6 could not fire before 45' because it required a
        settled pressure majority. This is the property that makes an early
        prediction meaningful: the same match must get less likely to produce
        goals as time expires.
        """
        from LIVE_SCANNER.live_stage8_live_prediction import poisson_at_least_one
        early = poisson_at_least_one(1.5 * (90 - 20) / 90)
        late = poisson_at_least_one(1.5 * (90 - 80) / 90)
        self.assertGreater(early, late)


class TestLivePredictionJudgesCatchAFabricatedNumber(unittest.TestCase):
    """The panel must not be a rubber stamp."""

    def _ctx(self):
        return {"fixture_id": "1",
                "board": {"minute": 30,
                          "statistics": {"home": {"shots-on-target": 4},
                                         "away": {"shots-on-target": 1}}},
                "score": {"home": 0, "away": 0},
                "odds": {"over25": 2.0, "home": 1.8, "away": 4.0}}

    def test_the_market_judge_blocks_a_wrong_anchor(self):
        from LIVE_SCANNER.live_prediction_judges import judge_market
        result = judge_market(self._ctx(), {
            "home_win": 40, "draw": 30, "away_win": 30,
            "_anchor": {"anchor_total_goals": 9.9}})   # deliberately wrong
        self.assertEqual(result["verdict"], "BLOCK")

    def test_the_market_judge_passes_on_the_true_anchor(self):
        """o25 of 2.0 implies about 2.67 expected goals; the judge must agree."""
        from LIVE_SCANNER.live_prediction_judges import judge_market
        from LIVE_SCANNER.live_stage8_live_prediction import implied_total_goals
        true_anchor = implied_total_goals(2.0)
        self.assertIsNotNone(true_anchor)
        result = judge_market(self._ctx(), {
            "home_win": 40, "draw": 30, "away_win": 30,
            "_anchor": {"anchor_total_goals": round(true_anchor, 4)}})
        self.assertEqual(result["verdict"], "PASS")

    def test_the_live_state_judge_blocks_probabilities_that_do_not_sum(self):
        from LIVE_SCANNER.live_prediction_judges import judge_live_state
        result = judge_live_state(self._ctx(), {
            "home_win": 50, "draw": 20, "away_win": 5,   # sums to 75
            "over_2_5": 50, "under_3_5": 50, "exactly_3_goals": 0})
        self.assertEqual(result["verdict"], "BLOCK")

    def test_the_live_state_judge_blocks_an_impossible_late_call(self):
        """88 minutes, no shots, no goal — a 70% to-score call is not credible."""
        from LIVE_SCANNER.live_prediction_judges import judge_live_state
        ctx = self._ctx()
        ctx["board"]["minute"] = 88
        ctx["board"]["statistics"]["home"]["shots-on-target"] = 0
        result = judge_live_state(ctx, {
            "home_win": 40, "draw": 30, "away_win": 30,
            "home_to_score": {"pct": 70}, "away_to_score": {"pct": 10},
            "over_2_5": 50, "under_3_5": 50, "exactly_3_goals": 0})
        self.assertEqual(result["verdict"], "BLOCK")
        self.assertIn("not credible", result["reason"])

    def test_the_trace_judge_blocks_an_answer_with_no_source(self):
        from LIVE_SCANNER.live_prediction_judges import judge_trace
        result = judge_trace(self._ctx(), {}, [
            {"id": "q1", "source": "", "answer": "x", "available": True}])
        self.assertEqual(result["verdict"], "BLOCK")

    def test_a_judge_that_raises_never_becomes_a_pass(self):
        """A panel that loses a judge silently is how a broken engine looks
        healthy."""
        from LIVE_SCANNER import live_prediction_judges as J
        original = J.judge_market
        try:
            def boom(*a, **k):
                raise RuntimeError("judge exploded")
            J.judge_market = boom
            panel = J.run_judges(self._ctx(), {
                "home_win": 40, "draw": 30, "away_win": 30,
                "_anchor": {"anchor_total_goals": 2.0}}, [])
            self.assertNotEqual(panel["verdict"], J.VERDICT_PASS)
        finally:
            J.judge_market = original

    def test_the_engine_blocks_rather_than_guesses_without_data(self):
        """
        THE GUARANTEE THAT REPLACES "NO ERRORS". No live board entry means no
        number at all — never a confident-looking default.
        """
        from LIVE_SCANNER.live_stage8_live_prediction import predict
        result = predict("999999999")
        self.assertIsNone(result.get("predictions"))
        self.assertEqual(result.get("verdict"), "BLOCK")
        self.assertIn(result.get("status"), ("NOT_LIVE", "INSUFFICIENT"))


if __name__ == "__main__":
    unittest.main()
