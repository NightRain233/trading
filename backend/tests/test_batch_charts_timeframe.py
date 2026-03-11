import unittest
from unittest.mock import patch

import pandas as pd

from main import BatchQuoteRequest, get_batch_charts


class BatchChartsTimeframeTests(unittest.TestCase):
    @staticmethod
    def _build_results():
        daily_index = pd.to_datetime(["2026-01-02", "2026-01-03"])
        weekly_index = pd.to_datetime(["2026-01-04", "2026-01-11"])

        daily_df = pd.DataFrame(
            {
                "Open": [10.0, 11.0],
                "High": [10.5, 11.5],
                "Low": [9.8, 10.6],
                "Close": [10.2, 11.2],
                "EMA5": [10.1, 10.9],
                "EMA10": [10.0, 10.7],
                "EMA20": [9.9, 10.5],
                "EMA50": [9.6, 10.1],
                "MACD_DIF": [0.05, 0.12],
                "MACD_DEA": [0.03, 0.08],
                "MACD_Hist": [0.02, 0.04],
            },
            index=daily_index,
        )

        weekly_df = pd.DataFrame(
            {
                "Open": [20.0, 21.0],
                "High": [20.5, 21.5],
                "Low": [19.8, 20.6],
                "Close": [20.2, 21.2],
                "EMA5": [20.1, 20.9],
                "EMA10": [20.0, 20.7],
                "EMA20": [19.9, 20.5],
                "EMA50": [19.6, 20.1],
                "MACD_DIF": [0.15, 0.22],
                "MACD_DEA": [0.13, 0.18],
                "MACD_Hist": [0.02, 0.04],
            },
            index=weekly_index,
        )

        return {"AAPL": (daily_df, weekly_df, {})}

    @patch("main.batch_fetch_and_update")
    def test_batch_charts_uses_daily_by_default(self, mock_batch):
        mock_batch.return_value = self._build_results()

        payload = get_batch_charts(BatchQuoteRequest(symbols=["AAPL"]))
        self.assertIn("AAPL", payload)
        first = payload["AAPL"][0]
        self.assertEqual(first["open"], 10.0)

    @patch("main.batch_fetch_and_update")
    def test_batch_charts_uses_weekly_when_timeframe_1w(self, mock_batch):
        mock_batch.return_value = self._build_results()

        payload = get_batch_charts(
            BatchQuoteRequest.model_validate(
                {"symbols": ["AAPL"], "timeframe": "1W"}
            )
        )
        self.assertIn("AAPL", payload)
        first = payload["AAPL"][0]
        self.assertEqual(first["open"], 20.0)
        self.assertIn("ema5", first)
        self.assertIn("ema10", first)
        self.assertIn("macd_dif", first)


if __name__ == "__main__":
    unittest.main()
