import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis
import analysis_cache
import analysis_data
from analysis import batch_fetch_and_update, get_cached_batch_summaries
from main import build_cache_headers


def _build_daily_df(periods: int = 60) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=periods, freq="B")
    close = pd.Series([1.0 + i * 0.01 for i in range(periods)], index=index)
    return pd.DataFrame(
        {
            "Open": close - 0.01,
            "High": close + 0.02,
            "Low": close - 0.02,
            "Close": close,
            "Volume": 100000,
            "EMA5": close,
            "EMA20": close,
            "EMA50": close,
            "ADX": 20.0,
            "RSI_7": 50.0,
            "RSI_14": 50.0,
            "RSI_21": 50.0,
            "MACD_DIF": 0.1,
            "MACD_DEA": 0.05,
            "MACD_Hist": 0.05,
        },
        index=index,
    )


def _build_weekly_df() -> pd.DataFrame:
    index = pd.date_range("2026-01-04", periods=12, freq="W")
    close = pd.Series([1.0 + i * 0.02 for i in range(12)], index=index)
    return pd.DataFrame(
        {
            "Open": close - 0.01,
            "High": close + 0.02,
            "Low": close - 0.02,
            "Close": close,
            "Volume": 100000,
            "MA5_W": close,
            "MACD_W": 0.2,
            "MACD_Signal_W": 0.1,
            "MACD_Hist_W": 0.1,
        },
        index=index,
    )


class CacheMetadataTests(unittest.TestCase):
    def setUp(self):
        analysis._memory_cache.clear()

    def test_build_cache_headers_uses_latest_data_timestamp_for_updated_at(self):
        latest_mtime = datetime(2026, 3, 11, 22, 3, 33, tzinfo=timezone.utc).timestamp()
        latest_data_ts = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc).timestamp()

        headers = build_cache_headers(
            etag='"etag"',
            latest_mtime=latest_mtime,
            latest_data_ts=latest_data_ts,
            data_stale=False,
            refresh_triggered=False,
        )

        self.assertEqual(headers["X-Data-Updated-At"], "2026-03-04T00:00:00+00:00")

    def test_get_cached_batch_summaries_reports_latest_bar_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            daily_df = _build_daily_df()
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "TEST.parquet"
            weekly_path = data_dir / "TEST_weekly.parquet"
            daily_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            fake_mtime = datetime(2026, 3, 11, 22, 3, 33, tzinfo=timezone.utc).timestamp()
            Path(daily_path).touch()
            Path(weekly_path).touch()
            import os
            os.utime(daily_path, (fake_mtime, fake_mtime))
            os.utime(weekly_path, (fake_mtime, fake_mtime))

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir):
                result = get_cached_batch_summaries(["TEST"])

            expected_ts = daily_df.index[-1].to_pydatetime().replace(tzinfo=timezone.utc).timestamp()
            self.assertEqual(result["latest_data_ts"], expected_ts)

    def test_analyze_stock_summary_converts_nan_weekly_values_to_none(self):
        daily_df = _build_daily_df()
        weekly_df = _build_weekly_df()
        weekly_df.loc[weekly_df.index[-1], "MA5_W"] = float("nan")
        weekly_df.loc[weekly_df.index[-1], "MACD_Hist_W"] = float("nan")

        summary = analysis.analyze_stock_summary("TEST", daily_df, weekly_df)

        try:
            json.dumps(summary, allow_nan=False)
        except ValueError as exc:
            self.fail(f"summary should not contain NaN for JSON serialization: {exc}")

        self.assertIsNone(summary["weeklyMA5"])
        self.assertIsNone(summary["weeklyMacdHist"])

    def test_analyze_stock_summary_ignores_incomplete_trailing_daily_row(self):
        daily_df = _build_daily_df()
        weekly_df = _build_weekly_df()

        trailing_index = daily_df.index[-1] + pd.offsets.BDay()
        trailing_row = pd.DataFrame(
            {
                "Open": [float("nan")],
                "High": [float("nan")],
                "Low": [float("nan")],
                "Close": [float("nan")],
                "Volume": [float("nan")],
                "EMA5": [float("nan")],
                "EMA20": [float("nan")],
                "EMA50": [float("nan")],
                "ADX": [float("nan")],
            },
            index=[trailing_index],
        )
        daily_df = pd.concat([daily_df, trailing_row])

        summary = analysis.analyze_stock_summary("TEST", daily_df, weekly_df)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["price"], daily_df.iloc[-2]["Close"])
        try:
            json.dumps(summary, allow_nan=False)
        except ValueError as exc:
            self.fail(f"summary should stay JSON-safe when trailing row is incomplete: {exc}")

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "TEST", "price": 1.23})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_does_not_refresh_timestamp_when_download_is_unchanged(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            daily_df = _build_daily_df()
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "TEST.parquet"
            weekly_path = data_dir / "TEST_weekly.parquet"
            daily_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            raw_download_df = daily_df[["Open", "High", "Low", "Close", "Volume"]].copy()
            raw_download_df.index.name = "Date"
            mock_download.return_value = raw_download_df
            mock_daily_indicators.side_effect = lambda df: daily_df.copy()
            mock_weekly_indicators.side_effect = lambda df: weekly_df.copy()

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir):
                batch_fetch_and_update(["TEST"])

            self.assertIn("TEST", analysis._memory_cache)
            self.assertEqual(analysis._memory_cache["TEST"]["timestamp"], old_mtime)

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "TEST", "price": 10.7})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_handles_single_symbol_price_ticker_multiindex_download(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            index = pd.date_range("2026-01-01", periods=3, freq="B")
            columns = pd.MultiIndex.from_product(
                [["TEST"], ["Open", "High", "Low", "Close", "Volume"]],
                names=["Ticker", "Price"],
            )
            raw_download_df = pd.DataFrame(
                [
                    [10.0, 10.5, 9.8, 10.3, 1000],
                    [10.2, 10.7, 10.0, 10.5, 1100],
                    [10.4, 10.9, 10.2, 10.7, 1200],
                ],
                columns=columns,
                index=index,
            )
            daily_df = _build_daily_df(periods=3)
            daily_df.index = index
            weekly_df = _build_weekly_df()
            mock_download.return_value = raw_download_df
            mock_daily_indicators.side_effect = lambda df: df.assign(EMA20=df["Close"])
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir):
                batch_fetch_and_update(["TEST"])

                stored = pd.read_parquet(Path(tmpdir) / "TEST.parquet")

            self.assertIn("Close", stored.columns)
            self.assertAlmostEqual(float(stored["Close"].iloc[-1]), 10.7)

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "TEST", "price": 1.23})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_uses_next_day_end_to_include_latest_daily_bar(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 2, 21, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            daily_df = _build_daily_df()
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "TEST.parquet"
            weekly_path = data_dir / "TEST_weekly.parquet"
            daily_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            mock_download.return_value = daily_df[["Open", "High", "Low", "Close", "Volume"]].copy()
            mock_daily_indicators.side_effect = lambda df: daily_df.copy()
            mock_weekly_indicators.side_effect = lambda df: weekly_df.copy()

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "datetime", FixedDateTime):
                batch_fetch_and_update(["TEST"])

        self.assertEqual(mock_download.call_args.kwargs["end"], FixedDateTime.now() + timedelta(days=1))

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "512890.SS", "price": 1.164})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_replaces_a_share_history_with_eastmoney(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            daily_df = _build_daily_df()
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "512890.SS.parquet"
            weekly_path = data_dir / "512890.SS_weekly.parquet"
            daily_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            yfinance_df = pd.DataFrame(
                {
                    "Open": [1.166, 1.180],
                    "High": [1.184, 1.180],
                    "Low": [1.158, 1.163],
                    "Close": [1.181, 1.164],
                    "Volume": [818364328, 464471901],
                },
                index=pd.to_datetime(["2026-06-01", "2026-06-03"]),
            )
            eastmoney_df = pd.DataFrame(
                {
                    "Open": [1.179],
                    "High": [1.191],
                    "Low": [1.178],
                    "Close": [1.182],
                    "Volume": [737393600],
                },
                index=pd.to_datetime(["2026-06-02"]),
            )
            mock_download.return_value = yfinance_df
            mock_daily_indicators.side_effect = lambda df: df
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "_fetch_new_data", return_value=eastmoney_df) as mock_eastmoney:
                batch_fetch_and_update(["512890.SS"])

                stored = pd.read_parquet(daily_path)

            stored_dates = {pd.Timestamp(ts).date().isoformat() for ts in stored.index}
            self.assertIn("2026-06-02", stored_dates)
            self.assertAlmostEqual(float(stored.loc[pd.Timestamp("2026-06-02"), "Close"]), 1.182)
            mock_eastmoney.assert_called_once()
            mock_download.assert_not_called()

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "512890.SS", "price": 1.182})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_uses_eastmoney_when_yahoo_would_lag(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 2, 21, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            daily_df = _build_daily_df()
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "512890.SS.parquet"
            weekly_path = data_dir / "512890.SS_weekly.parquet"
            daily_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            yfinance_df = pd.DataFrame(
                {
                    "Open": [1.166],
                    "High": [1.184],
                    "Low": [1.158],
                    "Close": [1.181],
                    "Volume": [818364328],
                },
                index=pd.to_datetime(["2026-06-01"]),
            )
            eastmoney_df = pd.DataFrame(
                {
                    "Open": [1.179],
                    "High": [1.191],
                    "Low": [1.178],
                    "Close": [1.182],
                    "Volume": [737393600],
                },
                index=pd.to_datetime(["2026-06-02"]),
            )
            mock_download.return_value = yfinance_df
            mock_daily_indicators.side_effect = lambda df: df
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "datetime", FixedDateTime), \
                 patch.object(analysis, "_fetch_new_data", return_value=eastmoney_df) as mock_eastmoney:
                batch_fetch_and_update(["512890.SS"])

                stored = pd.read_parquet(daily_path)

            stored_dates = {pd.Timestamp(ts).date().isoformat() for ts in stored.index}
            self.assertIn("2026-06-02", stored_dates)
            mock_eastmoney.assert_called_once()
            mock_download.assert_not_called()

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "512890.SS", "price": 1.164})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_replaces_local_a_share_cache_instead_of_merging(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 3, 21, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            local_df = _build_daily_df(periods=5)
            local_df.index = pd.date_range("2026-05-25", periods=5, freq="B")
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "512890.SS.parquet"
            weekly_path = data_dir / "512890.SS_weekly.parquet"
            local_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            yfinance_df = pd.DataFrame(
                {
                    "Open": [1.180],
                    "High": [1.180],
                    "Low": [1.163],
                    "Close": [1.164],
                    "Volume": [464471901],
                },
                index=pd.to_datetime(["2026-06-03"]),
            )
            eastmoney_df = pd.DataFrame(
                {
                    "Open": [1.166, 1.179, 1.180],
                    "High": [1.184, 1.191, 1.180],
                    "Low": [1.158, 1.178, 1.163],
                    "Close": [1.181, 1.182, 1.164],
                    "Volume": [818364300, 737393600, 490919700],
                },
                index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
            )
            mock_download.return_value = yfinance_df
            mock_daily_indicators.side_effect = lambda df: df
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "datetime", FixedDateTime), \
                 patch.object(analysis, "_fetch_new_data", return_value=eastmoney_df) as mock_eastmoney:
                batch_fetch_and_update(["512890.SS"])

                stored = pd.read_parquet(daily_path)

            stored_dates = {pd.Timestamp(ts).date().isoformat() for ts in stored.index}
            self.assertIn("2026-06-01", stored_dates)
            self.assertIn("2026-06-02", stored_dates)
            self.assertAlmostEqual(float(stored.loc[pd.Timestamp("2026-06-02"), "Close"]), 1.182)
            mock_eastmoney.assert_called_once()
            mock_download.assert_not_called()

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "512890.SS", "price": 1.164})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_requests_full_a_share_refresh_when_local_gap_exists(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 6, 3, 21, 30)

        with tempfile.TemporaryDirectory() as tmpdir:
            close = pd.Series([1.15, 1.16, 1.17, 1.18], index=pd.to_datetime([
                "2026-05-28",
                "2026-05-29",
                "2026-06-01",
                "2026-06-03",
            ]))
            local_df = pd.DataFrame(
                {
                    "Open": close - 0.01,
                    "High": close + 0.01,
                    "Low": close - 0.02,
                    "Close": close,
                    "Volume": 100000,
                    "EMA5": close,
                    "EMA20": close,
                    "EMA50": close,
                    "ADX": 20.0,
                },
                index=close.index,
            )
            weekly_df = _build_weekly_df()
            data_dir = Path(tmpdir)
            daily_path = data_dir / "512890.SS.parquet"
            weekly_path = data_dir / "512890.SS_weekly.parquet"
            local_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)

            old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
            import os
            os.utime(daily_path, (old_mtime, old_mtime))
            os.utime(weekly_path, (old_mtime, old_mtime))

            mock_download.return_value = pd.DataFrame(
                {
                    "Open": [1.180],
                    "High": [1.180],
                    "Low": [1.163],
                    "Close": [1.164],
                    "Volume": [464471901],
                },
                index=pd.to_datetime(["2026-06-03"]),
            )
            eastmoney_df = pd.DataFrame(
                {
                    "Open": [1.179],
                    "High": [1.191],
                    "Low": [1.178],
                    "Close": [1.182],
                    "Volume": [737393600],
                },
                index=pd.to_datetime(["2026-06-02"]),
            )
            mock_daily_indicators.side_effect = lambda df: df
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "datetime", FixedDateTime), \
                 patch.object(analysis, "_fetch_new_data", return_value=eastmoney_df) as mock_eastmoney:
                batch_fetch_and_update(["512890.SS"])

                stored = pd.read_parquet(daily_path)

            mock_eastmoney.assert_called_once()
            stored_dates = {pd.Timestamp(ts).date().isoformat() for ts in stored.index}
            self.assertIn("2026-06-02", stored_dates)
            mock_download.assert_not_called()

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "515880.SS", "price": 1.08})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_uses_eastmoney_without_yfinance_for_a_share(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            eastmoney_df = _build_daily_df()[["Open", "High", "Low", "Close", "Volume"]]
            weekly_df = _build_weekly_df()
            mock_daily_indicators.side_effect = lambda df: df.assign(
                EMA5=df["Close"],
                EMA20=df["Close"],
            )
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "_fetch_new_data", return_value=eastmoney_df) as mock_fetch:
                batch_fetch_and_update(["515880.SS"])

            mock_fetch.assert_called_once()
            mock_download.assert_not_called()
            stored = pd.read_parquet(Path(tmpdir) / "515880.SS.parquet")
            self.assertEqual(list(stored.index), list(eastmoney_df.index))
            self.assertTrue(
                analysis_data._has_current_data_source(
                    str(Path(tmpdir) / "515880.SS.parquet"),
                    "515880.SS",
                )
            )

    @patch.object(analysis, "analyze_stock_summary", return_value={"symbol": "515880.SS", "price": 1.08})
    @patch.object(analysis, "_calculate_weekly_indicators")
    @patch.object(analysis, "_calculate_daily_indicators")
    @patch.object(analysis.yf, "download")
    def test_batch_fetch_migrates_fresh_legacy_a_share_cache(
        self,
        mock_download,
        mock_daily_indicators,
        mock_weekly_indicators,
        _mock_summary,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_df = _build_daily_df()
            replacement = legacy_df[["Open", "High", "Low", "Close", "Volume"]].copy()
            replacement["Close"] += 0.5
            replacement["Open"] = replacement["Close"] - 0.01
            replacement["High"] = replacement["Close"] + 0.02
            replacement["Low"] = replacement["Close"] - 0.02
            weekly_df = _build_weekly_df()
            daily_path = Path(tmpdir) / "515880.SS.parquet"
            weekly_path = Path(tmpdir) / "515880.SS_weekly.parquet"
            legacy_df.to_parquet(daily_path)
            weekly_df.to_parquet(weekly_path)
            mock_daily_indicators.side_effect = lambda df: df.assign(
                EMA5=df["Close"],
                EMA20=df["Close"],
            )
            mock_weekly_indicators.return_value = weekly_df

            with patch.object(analysis_cache, "DATA_DIR", tmpdir), \
                 patch.object(analysis_data, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "DATA_DIR", tmpdir), \
                 patch.object(analysis, "_fetch_new_data", return_value=replacement) as mock_fetch:
                batch_fetch_and_update(["515880.SS"])

            mock_fetch.assert_called_once()
            mock_download.assert_not_called()
            stored = pd.read_parquet(daily_path)
            self.assertAlmostEqual(float(stored["Close"].iloc[-1]), float(replacement["Close"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
