import tempfile
import unittest
from datetime import datetime
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

    def test_history_trade_symbols_default_to_watchlist_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_daily(tmpdir, "TEST")
            self._write_daily(tmpdir, "EXTRA")
            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "load_watchlist", return_value=[{"symbols": [{"symbol": "TEST", "alias": "测试ETF"}]}]):
                symbols = main.list_history_trade_symbols()

        self.assertEqual([item["symbol"] for item in symbols], ["TEST"])
        self.assertEqual(symbols[0]["displayName"], "TEST · 测试ETF")

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
                 patch.object(main, "load_watchlist", return_value=[{"symbols": [{"symbol": "TEST", "alias": "测试ETF"}]}]), \
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

    def test_precompute_history_trades_uses_watchlist_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_daily(tmpdir, "TEST")
            self._write_daily(tmpdir, "EXTRA")
            db_path = Path(tmpdir) / "history.sqlite"

            def build_payload(symbol, *_args, **kwargs):
                return {
                    "symbol": symbol,
                    "strategy": "supertrend",
                    "start": kwargs.get("start"),
                    "end": kwargs.get("end"),
                    "candles": [],
                    "supertrend": [],
                    "markers": [],
                    "trades": [],
                    "summary": {"tradeCount": 0},
                }

            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)), \
                 patch.object(main, "load_watchlist", return_value=[{"symbols": [{"symbol": "TEST", "alias": "测试ETF"}]}]), \
                 patch.object(main, "collect_history_trade_symbol_catalog", return_value={
                     "TEST": {"symbol": "TEST", "name": "测试ETF", "source": "watchlist"},
                     "EXTRA": {"symbol": "EXTRA", "name": "不应预计算", "source": "data"},
                 }) as broad_catalog, \
                 patch.object(main, "build_supertrend_history_review", side_effect=build_payload) as mock_review:
                result = main.precompute_history_trades(start="2026-01-01")

        broad_catalog.assert_not_called()
        self.assertEqual(result["computed"], 1)
        self.assertEqual([call.args[0] for call in mock_review.call_args_list], ["TEST"])

    def test_precompute_history_trades_downloads_missing_daily_data(self):
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
            db_path = Path(tmpdir) / "history.sqlite"

            def write_downloaded_data(symbols):
                for symbol in symbols:
                    self._write_daily(tmpdir, symbol)
                return {}

            with patch.object(main, "DATA_DIR", tmpdir), \
                 patch.object(main, "HISTORY_TRADES_CACHE_FILE", str(db_path)), \
                 patch.object(main, "load_watchlist", return_value=[{"symbols": [{"symbol": "TEST", "alias": "测试ETF"}]}]), \
                 patch.object(main, "batch_fetch_and_update", side_effect=write_downloaded_data) as mock_download, \
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

        mock_download.assert_called_once_with(["TEST"])
        self.assertEqual(result["downloaded"], 1)
        self.assertEqual(result["computed"], 1)
        self.assertEqual(cached, payload)

    def test_precompute_history_trades_defaults_to_five_years(self):
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                value = cls(2026, 5, 31, 12, 0, 0)
                return value.replace(tzinfo=tz) if tz else value

        payload = {
            "symbol": "TEST",
            "strategy": "supertrend",
            "start": "2021-05-31",
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
                 patch.object(main, "datetime", FrozenDatetime), \
                 patch.object(main, "load_watchlist", return_value=[{"symbols": [{"symbol": "TEST", "alias": "测试ETF"}]}]), \
                 patch.object(main, "build_supertrend_history_review", return_value=payload) as mock_review:
                result = main.precompute_history_trades(start=None)

        self.assertEqual(result["start"], "2021-05-31")
        self.assertEqual(mock_review.call_args.kwargs["start"], "2021-05-31")

    def test_history_precompute_cli_targets_single_symbol(self):
        with patch.object(main, "precompute_history_trades", return_value={"computed": 1}) as mock_precompute:
            exit_code = main.main(["--precompute-history-trades", "--symbol", "test"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_precompute.call_args.kwargs["symbols"], ["TEST"])


if __name__ == "__main__":
    unittest.main()
