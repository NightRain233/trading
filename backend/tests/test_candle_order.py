import json
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

    def test_build_mini_candles_is_json_compliant_with_missing_optional_indicators(self):
        index = pd.to_datetime(["2026-01-01", "2026-01-02"])
        df = pd.DataFrame(
            {
                "Open": [10.0, 11.0],
                "High": [10.5, 11.5],
                "Low": [9.8, 10.6],
                "Close": [10.2, 11.2],
                "EMA20": [float("nan"), 10.9],
            },
            index=index,
        )

        candles = _build_mini_candles(df, num_days=10)

        try:
            json.dumps({"AAPL": candles}, allow_nan=False)
        except ValueError as exc:
            self.fail(f"mini candles should not contain NaN for JSON serialization: {exc}")


if __name__ == "__main__":
    unittest.main()
