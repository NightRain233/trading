import unittest

from supertrend_alerts import classify_supertrend_alert


class SupertrendAlertTests(unittest.TestCase):
    def test_bull_flip_is_high_priority_buy_candidate(self):
        alert = classify_supertrend_alert(
            state="bull_flip",
            weekly_state="bull",
            close=105.0,
            st_val=100.0,
            atr=3.0,
            just_flipped=True,
            trend_age_bars=1,
        )

        self.assertEqual(alert["alertType"], "buy_candidate")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "support")
        self.assertAlmostEqual(alert["distanceToSupertrendPct"], 4.7619, places=3)
        self.assertEqual(alert["opportunityStage"], "fresh_bull")
        self.assertEqual(alert["opportunityLabel"], "刚翻多 D1")

    def test_bull_near_supertrend_support_is_support_test(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=101.0,
            st_val=100.0,
            atr=4.0,
            just_flipped=False,
            trend_age_bars=8,
        )

        self.assertEqual(alert["alertType"], "support_test")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "support")
        self.assertAlmostEqual(alert["distanceToSupertrendAtr"], 0.25)
        self.assertEqual(alert["opportunityStage"], "pullback_buy_zone")
        self.assertEqual(alert["opportunityLabel"], "回踩支撑")

    def test_recent_bull_trend_remains_in_fresh_watch_window(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=104.0,
            st_val=100.0,
            atr=4.0,
            just_flipped=False,
            trend_age_bars=3,
        )

        self.assertEqual(alert["alertType"], "hold_bull")
        self.assertEqual(alert["opportunityStage"], "fresh_bull")
        self.assertEqual(alert["opportunityLabel"], "刚翻多 D3")
        self.assertIn("有效观察期", alert["opportunityReason"])

    def test_bull_trend_far_from_support_is_extended_from_entry_zone(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=112.0,
            st_val=100.0,
            atr=4.0,
            just_flipped=False,
            trend_age_bars=6,
        )

        self.assertEqual(alert["alertType"], "hold_bull")
        self.assertEqual(alert["opportunityStage"], "extended_from_entry")
        self.assertEqual(alert["opportunityLabel"], "已弹离买点")
        self.assertIn("避免追高", alert["opportunityReason"])

    def test_atr_only_extension_waits_for_pullback_without_overstating_missed_entry(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=738.81,
            st_val=710.52,
            atr=9.91,
            just_flipped=False,
            trend_age_bars=38,
        )

        self.assertEqual(alert["alertType"], "hold_bull")
        self.assertEqual(alert["opportunityStage"], "wait_pullback")
        self.assertEqual(alert["opportunityLabel"], "等待回踩")
        self.assertIn("趋势仍在", alert["opportunityReason"])

    def test_bear_flip_is_high_priority_sell_or_risk(self):
        alert = classify_supertrend_alert(
            state="bear_flip",
            weekly_state="bear",
            close=96.0,
            st_val=100.0,
            atr=2.0,
            just_flipped=True,
            trend_age_bars=1,
        )

        self.assertEqual(alert["alertType"], "sell_or_risk")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "resistance")
        self.assertEqual(alert["opportunityStage"], "invalidated")
        self.assertEqual(alert["opportunityLabel"], "机会失效")

    def test_bear_near_supertrend_resistance_is_resistance_test(self):
        alert = classify_supertrend_alert(
            state="bear",
            weekly_state="bear",
            close=99.0,
            st_val=100.0,
            atr=2.0,
            just_flipped=False,
        )

        self.assertEqual(alert["alertType"], "resistance_test")
        self.assertEqual(alert["alertPriority"], "medium")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "resistance")

    def test_missing_price_or_supertrend_returns_none_alert(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=None,
            st_val=100.0,
            atr=2.0,
            just_flipped=False,
        )

        self.assertEqual(alert["alertType"], "none")
        self.assertEqual(alert["alertPriority"], "none")
        self.assertFalse(alert["isActionable"])
        self.assertIsNone(alert["distanceToSupertrendPct"])


if __name__ == "__main__":
    unittest.main()
