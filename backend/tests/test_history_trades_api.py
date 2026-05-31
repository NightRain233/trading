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
    def _write_daily(self, data_dir: str, symbol: str = "TEST") -> Path:
        data_path = Path(data_dir) / f"{symbol}.parquet"
        _build_daily_df().to_parquet(data_path)
        return data_path

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
            db_path = Path(tmpdir) / "history.sqlite"
            _build_daily_df().to_parquet(data_path)
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)), \
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

    def test_history_trades_uses_persistent_cache_when_fresh(self):
        payload = {
            "symbol": "TEST",
            "strategy": "supertrend",
            "start": "2026-01-01",
            "end": None,
            "candles": [{"time": "2026-01-01"}],
            "supertrend": [],
            "markers": [],
            "trades": [],
            "summary": {"tradeCount": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = self._write_daily(tmpdir)
            db_path = Path(tmpdir) / "history.sqlite"
            main.save_history_trade_cache(
                payload,
                data_mtime=data_path.stat().st_mtime,
                db_path=str(db_path),
            )
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)), \
                 patch.object(main, "build_supertrend_history_review") as mock_review:
                response = main.get_history_trades(
                    symbol="TEST",
                    strategy="supertrend",
                    start="2026-01-01",
                )

        self.assertEqual(response, payload)
        mock_review.assert_not_called()

    def test_history_trade_symbols_include_names_and_cache_state(self):
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
            data_path = self._write_daily(tmpdir)
            db_path = Path(tmpdir) / "history.sqlite"
            universe_path = Path(tmpdir) / "universe.json"
            universe_path.write_text(
                '{"symbols":[{"symbol":"TEST","name":"测试ETF"},{"symbol":"MISS","name":"缺失"}]}',
                encoding="utf-8",
            )
            main.save_history_trade_cache(
                payload,
                data_mtime=data_path.stat().st_mtime,
                db_path=str(db_path),
            )
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)):
                symbols = main.list_history_trade_symbols(universe_files=[str(universe_path)])

        test_item = next(item for item in symbols if item["symbol"] == "TEST")
        self.assertEqual(test_item["name"], "测试ETF")
        self.assertEqual(test_item["displayName"], "TEST · 测试ETF")
        self.assertTrue(test_item["hasCache"])
        self.assertTrue(test_item["hasData"])
        miss_item = next(item for item in symbols if item["symbol"] == "MISS")
        self.assertFalse(miss_item["hasData"])

    def test_precompute_history_trades_writes_sqlite_cache(self):
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
            self._write_daily(tmpdir)
            db_path = Path(tmpdir) / "history.sqlite"
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)), \
                 patch.object(main, "collect_history_trade_symbol_catalog", return_value={"TEST": {"symbol": "TEST", "name": "测试ETF", "source": "test"}}), \
                 patch.object(main, "build_supertrend_history_review", return_value=payload):
                result = main.precompute_history_trades(start="2026-01-01")

                cached = main.load_history_trade_cache(
                    "TEST",
                    "supertrend",
                    "2026-01-01",
                    None,
                    None,
                    False,
                    data_mtime=(Path(tmpdir) / "TEST.parquet").stat().st_mtime,
                    db_path=str(db_path),
                )

        self.assertEqual(result["computed"], 1)
        self.assertEqual(result["skippedMissingData"], 0)
        self.assertEqual(cached, payload)


if __name__ == "__main__":
    unittest.main()
