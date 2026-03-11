import unittest

import pandas as pd

from analysis import _calculate_weekly_indicators


class WeeklyIndicatorsTests(unittest.TestCase):
    def test_weekly_indicators_include_ema5_and_ema10(self):
        index = pd.date_range("2025-01-01", periods=220, freq="D")
        base = pd.Series(range(220), index=index, dtype="float64")
        df = pd.DataFrame(
            {
                "Open": 100 + base,
                "High": 101 + base,
                "Low": 99 + base,
                "Close": 100.5 + base,
                "Volume": 1000,
            },
            index=index,
        )

        weekly = _calculate_weekly_indicators(df)

        self.assertIn("EMA5", weekly.columns)
        self.assertIn("EMA10", weekly.columns)
        self.assertTrue(weekly["EMA5"].notna().any())
        self.assertTrue(weekly["EMA10"].notna().any())


if __name__ == "__main__":
    unittest.main()
