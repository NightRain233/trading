import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

import main


def _build_daily_df() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=3, freq="B")
    return pd.DataFrame(
        {
            "Open": [10.0, 10.2, 10.4],
            "High": [10.5, 10.7, 10.9],
            "Low": [9.8, 10.0, 10.2],
            "Close": [10.3, 10.5, 10.7],
            "Volume": [1000, 1100, 1200],
        },
        index=dates,
    )


class HistoryTradesApiTests(unittest.TestCase):
    def test_history_trades_rejects_unknown_strategy(self):
        with self.assertRaises(HTTPException) as exc:
            main.get_history_trades(symbol="TEST", strategy="unknown")

        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("Unsupported strategy", exc.exception.detail)

    def test_history_trades_returns_404_when_symbol_cache_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(main, "DATA_DIR", tmpdir):
            with self.assertRaises(HTTPException) as exc:
                main.get_history_trades(symbol="TEST", strategy="supertrend")

        self.assertEqual(exc.exception.status_code, 404)
        self.assertIn("No cached data", exc.exception.detail)

    def test_history_trades_returns_replay_payload(self):
        payload = {
            "symbol": "TEST",
            "strategy": "supertrend",
            "start": "2026-01-01",
            "end": None,
            "candles": [],
            "supertrend": [],
            "markers": [],
            "trades": [],
            "summary": {"tradeCount": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "TEST.parquet"
            _build_daily_df().to_parquet(data_path)
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "build_supertrend_history_review", return_value=payload) as mock_review:
                response = main.get_history_trades(
                    symbol="test",
                    strategy="supertrend",
                    start="2026-01-01",
                )

        self.assertEqual(response, payload)
        args, kwargs = mock_review.call_args
        self.assertEqual(args[0], "TEST")
        self.assertEqual(kwargs["start"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
