import unittest

import pandas as pd

from analysis import _build_candles, _build_mini_candles


class CandleOrderTests(unittest.TestCase):
    def _build_unsorted_df(self) -> pd.DataFrame:
        index = pd.to_datetime(["2026-02-22", "2026-02-13", "2026-02-24"])
        data = {
            "Open": [10.0, 9.0, 11.0],
            "High": [11.0, 10.0, 12.0],
            "Low": [9.5, 8.8, 10.5],
            "Close": [10.5, 9.2, 11.5],
            "Volume": [100, 120, 130],
        }
        return pd.DataFrame(data, index=index)

    def test_build_candles_returns_time_ascending(self):
        df = self._build_unsorted_df()
        candles = _build_candles(df, num_days=10)
        times = [c["time"] for c in candles]
        self.assertEqual(times, sorted(times))

    def test_build_mini_candles_returns_time_ascending(self):
        df = self._build_unsorted_df()
        candles = _build_mini_candles(df, num_days=10)
        times = [c["time"] for c in candles]
        self.assertEqual(times, sorted(times))


if __name__ == "__main__":
    unittest.main()
