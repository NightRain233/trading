from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import analysis_data


def _ohlcv(index, close):
    close = pd.Series(close, index=pd.to_datetime(index), dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.02,
            "Low": close - 0.02,
            "Close": close,
            "Volume": 1000.0,
        },
        index=close.index,
    )


def test_merge_and_clean_data_sorts_merged_rows():
    now = datetime(2026, 6, 28)
    local = _ohlcv(["2026-06-25", "2026-06-26", "2026-06-27"], [1.0, 1.1, 1.2])
    downloaded = _ohlcv(["2026-06-25", "2026-06-27"], [1.05, 1.25])

    merged = analysis_data._merge_and_clean_data(local, downloaded, now)

    assert merged.index.is_monotonic_increasing
    assert list(merged.index) == list(pd.to_datetime(["2026-06-25", "2026-06-26", "2026-06-27"]))
    assert merged.loc[pd.Timestamp("2026-06-27"), "Close"] == 1.25


def test_load_local_data_sorts_legacy_parquet_before_finding_last_update(tmp_path):
    file_path = tmp_path / "TEST.parquet"
    unsorted = _ohlcv(
        ["2026-06-26", "2026-06-25", "2026-06-27"],
        [1.1, 1.0, 1.2],
    )
    unsorted.to_parquet(file_path)

    loaded, last_update = analysis_data._load_local_data(
        str(file_path),
        "TEST",
    )

    assert loaded.index.is_monotonic_increasing
    assert last_update == pd.Timestamp("2026-06-27")


def test_fetch_new_data_uses_full_retention_eastmoney_for_a_share():
    now = datetime(2026, 6, 28, 15, 30)
    last_update = datetime(2026, 6, 27)
    eastmoney_df = _ohlcv(["2026-06-26"], [1.08])

    with patch.object(
        analysis_data,
        "_fetch_eastmoney_daily",
        create=True,
        return_value=eastmoney_df,
    ) as mock_eastmoney, patch.object(analysis_data.yf, "Ticker") as mock_ticker:
        result = analysis_data._fetch_new_data("515880.SS", last_update, now)

    assert result.equals(eastmoney_df)
    mock_ticker.assert_not_called()
    start, end = mock_eastmoney.call_args.args[1:3]
    assert start == now - timedelta(days=analysis_data.DATA_RETENTION_DAYS)
    assert end == now + timedelta(days=1)


def test_price_integrity_rejects_false_split_crash():
    corrupt = _ohlcv(["2026-02-02", "2026-02-03", "2026-02-04"], [3.16, 1.084, 1.051])

    assert not analysis_data._has_valid_price_history(corrupt, "515880.SS")


def test_price_integrity_accepts_continuous_history():
    valid = _ohlcv(["2026-02-02", "2026-02-03", "2026-02-04"], [1.084, 1.084, 1.051])

    assert analysis_data._has_valid_price_history(valid, "515880.SS")


def test_source_metadata_marks_legacy_a_share_stale(tmp_path):
    parquet_path = tmp_path / "515880.SS.parquet"

    assert not analysis_data._has_current_data_source(str(parquet_path), "515880.SS")

    analysis_data._write_data_source_metadata(str(parquet_path), "515880.SS")
    assert analysis_data._has_current_data_source(str(parquet_path), "515880.SS")

    analysis_data._invalidate_data_source_metadata(str(parquet_path))
    assert not analysis_data._has_current_data_source(str(parquet_path), "515880.SS")


def test_non_a_share_does_not_require_source_metadata(tmp_path):
    parquet_path = tmp_path / "SPY.parquet"

    assert analysis_data._has_current_data_source(str(parquet_path), "SPY")


def test_fetch_eastmoney_daily_requests_qfq_and_normalizes_rows():
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2026-02-04,1.050,1.051,1.060,1.040,123",
                        "2026-02-03,1.084,1.084,1.090,1.070,456",
                    ]
                }
            }

    class FakeSession:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, params, timeout):
            captured.update(url=url, params=params, timeout=timeout, trust_env=self.trust_env)
            return FakeResponse()

    fake_requests = SimpleNamespace(Session=FakeSession)
    with patch.object(analysis_data, "requests", fake_requests, create=True):
        result = analysis_data._fetch_eastmoney_daily(
            "515880.SS",
            datetime(2026, 2, 1),
            datetime(2026, 2, 5),
        )

    assert captured["params"]["secid"] == "1.515880"
    assert captured["params"]["fqt"] == "1"
    assert result.index.is_monotonic_increasing
    assert list(result.columns) == ["Open", "Close", "High", "Low", "Volume"]
    assert result.loc[pd.Timestamp("2026-02-03"), "Volume"] == 45600


def test_fetch_stock_data_migrates_fresh_legacy_a_share_cache(tmp_path):
    legacy = _ohlcv(["2026-01-02", "2026-01-05"], [3.10, 3.16]).assign(
        EMA5=3.13,
        EMA20=3.13,
    )
    replacement = _ohlcv(["2026-02-02", "2026-02-03"], [1.084, 1.084])
    file_path = tmp_path / "515880.SS.parquet"
    legacy.to_parquet(file_path)
    calculated = replacement.assign(EMA5=1.084, EMA20=1.084)
    weekly = replacement.copy()

    with patch.object(analysis_data, "DATA_DIR", str(tmp_path)), patch.object(
        analysis_data,
        "_fetch_new_data",
        return_value=replacement,
    ) as mock_fetch, patch.object(
        analysis_data,
        "_calculate_daily_indicators",
        return_value=calculated,
    ), patch.object(
        analysis_data,
        "_calculate_weekly_indicators",
        return_value=weekly,
    ):
        daily_result, _ = analysis_data.fetch_stock_data("515880.SS")

    mock_fetch.assert_called_once()
    stored = pd.read_parquet(file_path)
    assert list(stored.index) == list(replacement.index)
    assert list(daily_result.index) == list(replacement.index)
    assert analysis_data._has_current_data_source(str(file_path), "515880.SS")


def test_fetch_stock_data_keeps_legacy_cache_when_eastmoney_fails(tmp_path):
    legacy = _ohlcv(["2026-01-02", "2026-01-05"], [3.10, 3.16]).assign(
        EMA5=3.13,
        EMA20=3.13,
    )
    file_path = tmp_path / "515880.SS.parquet"
    legacy.to_parquet(file_path)
    weekly = legacy.copy()

    with patch.object(analysis_data, "DATA_DIR", str(tmp_path)), patch.object(
        analysis_data,
        "_fetch_new_data",
        return_value=None,
    ) as mock_fetch, patch.object(
        analysis_data,
        "_calculate_daily_indicators",
        return_value=legacy,
    ), patch.object(
        analysis_data,
        "_calculate_weekly_indicators",
        return_value=weekly,
    ):
        daily_result, _ = analysis_data.fetch_stock_data("515880.SS")

    mock_fetch.assert_called_once()
    pd.testing.assert_frame_equal(daily_result, legacy, check_freq=False)
    assert not analysis_data._has_current_data_source(str(file_path), "515880.SS")


def test_fetch_stock_data_keeps_fresh_non_a_share_cache_behavior(tmp_path):
    cached = _ohlcv(["2026-01-02", "2026-01-05"], [100.0, 101.0]).assign(
        EMA5=100.5,
        EMA20=100.5,
    )
    file_path = tmp_path / "SPY.parquet"
    cached.to_parquet(file_path)

    with patch.object(analysis_data, "DATA_DIR", str(tmp_path)), patch.object(
        analysis_data,
        "_fetch_new_data",
    ) as mock_fetch, patch.object(
        analysis_data,
        "_calculate_weekly_indicators",
        return_value=cached,
    ):
        daily_result, _ = analysis_data.fetch_stock_data("SPY")

    mock_fetch.assert_not_called()
    pd.testing.assert_frame_equal(daily_result, cached, check_freq=False)
