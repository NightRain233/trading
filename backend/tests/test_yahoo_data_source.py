from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

import analysis
import analysis_cache
import analysis_data
from data_source_guard import ProviderDisabledError


def _ohlcv(index, close):
    close = pd.Series(close, index=pd.to_datetime(index), dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1000.0,
        },
        index=close.index,
    )


class RecordingGuard:
    def __init__(self):
        self.keys = []

    def call(self, key, operation):
        self.keys.append(key)
        return operation()


def test_single_symbol_yahoo_history_runs_through_guard():
    guard = RecordingGuard()
    downloaded = _ohlcv(["2026-06-26"], [100.0])

    class FakeTicker:
        def history(self, **_kwargs):
            return downloaded

    with patch.object(
        analysis_data,
        "yahoo_guard",
        guard,
    ), patch.object(
        analysis_data.yf,
        "Ticker",
        return_value=FakeTicker(),
    ):
        result = analysis_data._fetch_new_data(
            "SPY",
            datetime(2026, 6, 25),
            datetime(2026, 6, 28),
        )

    assert guard.keys == ["SPY"]
    assert result.equals(downloaded)


def test_single_symbol_yahoo_disabled_error_propagates():
    class DisabledGuard:
        def call(self, key, _operation):
            raise ProviderDisabledError(
                "disabled",
                provider="yahoo",
                key=key,
                category="disabled",
            )

    with patch.object(analysis_data, "yahoo_guard", DisabledGuard()):
        with pytest.raises(ProviderDisabledError):
            analysis_data._fetch_new_data(
                "SPY",
                None,
                datetime(2026, 6, 28),
            )


def test_yahoo_batch_uses_guard_with_deterministic_key(tmp_path):
    guard = RecordingGuard()
    downloaded = _ohlcv(["2026-06-26"], [100.0])
    weekly = downloaded.assign(MACD_W=0.0)
    calculated = downloaded.assign(EMA5=100.0, EMA20=100.0)

    # Earlier full-suite tests may leave SPY in the process-wide memory cache.
    # This case exercises the download path, so isolate it from that shared state.
    with analysis._memory_cache_lock:
        analysis._memory_cache.pop("SPY", None)

    with patch.object(
        analysis,
        "DATA_DIR",
        str(tmp_path),
    ), patch.object(
        analysis_data,
        "DATA_DIR",
        str(tmp_path),
    ), patch.object(
        analysis_cache,
        "DATA_DIR",
        str(tmp_path),
    ), patch.object(
        analysis,
        "yahoo_guard",
        guard,
        create=True,
    ), patch.object(
        analysis.yf,
        "download",
        return_value=downloaded,
    ), patch.object(
        analysis,
        "_calculate_daily_indicators",
        return_value=calculated,
    ), patch.object(
        analysis,
        "_calculate_weekly_indicators",
        return_value=weekly,
    ), patch.object(
        analysis,
        "analyze_stock_summary",
        return_value={"symbol": "SPY"},
    ):
        analysis.batch_fetch_and_update(["SPY"])

    assert guard.keys == ["batch:SPY"]
    assert (tmp_path / "SPY.parquet").exists()


def test_yahoo_batch_key_is_sorted_and_deduplicated():
    assert analysis._yahoo_batch_request_key(
        ["QQQ", "SPY", "QQQ"]
    ) == "batch:QQQ,SPY"
