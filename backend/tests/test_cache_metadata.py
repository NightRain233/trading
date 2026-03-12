import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import analysis
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

            with patch.object(analysis, "DATA_DIR", tmpdir):
                result = get_cached_batch_summaries(["TEST"])

            expected_ts = daily_df.index[-1].to_pydatetime().replace(tzinfo=timezone.utc).timestamp()
            self.assertEqual(result["latest_data_ts"], expected_ts)

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

            with patch.object(analysis, "DATA_DIR", tmpdir):
                batch_fetch_and_update(["TEST"])

            self.assertIn("TEST", analysis._memory_cache)
            self.assertEqual(analysis._memory_cache["TEST"]["timestamp"], old_mtime)


if __name__ == "__main__":
    unittest.main()
