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
        )

        self.assertEqual(alert["alertType"], "buy_candidate")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "support")
        self.assertAlmostEqual(alert["distanceToSupertrendPct"], 4.7619, places=3)

    def test_bull_near_supertrend_support_is_support_test(self):
        alert = classify_supertrend_alert(
            state="bull",
            weekly_state="bull",
            close=101.0,
            st_val=100.0,
            atr=4.0,
            just_flipped=False,
        )

        self.assertEqual(alert["alertType"], "support_test")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "support")
        self.assertAlmostEqual(alert["distanceToSupertrendAtr"], 0.25)

    def test_bear_flip_is_high_priority_sell_or_risk(self):
        alert = classify_supertrend_alert(
            state="bear_flip",
            weekly_state="bear",
            close=96.0,
            st_val=100.0,
            atr=2.0,
            just_flipped=True,
        )

        self.assertEqual(alert["alertType"], "sell_or_risk")
        self.assertEqual(alert["alertPriority"], "high")
        self.assertTrue(alert["isActionable"])
        self.assertEqual(alert["keyLevelType"], "resistance")

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
