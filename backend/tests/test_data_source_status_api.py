import os
import time
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import HTTPException

import analysis_data
import main
from data_source_guard import (
    MarketDataUnavailableError,
    ProviderCircuitOpenError,
)


def _cached_daily():
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    close = pd.Series(
        [1.0 + index_value * 0.01 for index_value in range(60)],
        index=index,
    )
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.02,
            "Low": close - 0.02,
            "Close": close,
            "Volume": 1000.0,
            "EMA5": close,
            "EMA20": close,
            "EMA50": close,
            "ADX": 25.0,
        },
        index=index,
    )


def test_data_source_status_endpoint_returns_both_providers(monkeypatch):
    payload = {
        "tickflow": {
            "provider": "tickflow",
            "enabled": True,
            "circuitState": "closed",
        },
        "yahoo": {
            "provider": "yahoo",
            "enabled": True,
            "circuitState": "closed",
        },
    }
    monkeypatch.setattr(
        main,
        "get_data_source_status",
        lambda: payload,
        raising=False,
    )

    assert main.api_data_source_status() == payload


def test_quote_maps_market_data_unavailable_to_503_with_retry_after():
    error = MarketDataUnavailableError(
        "tickflow is cooling down",
        provider="tickflow",
        category="circuit_open",
        retry_after=120,
    )

    with patch.object(main, "analyze_stock", side_effect=error):
        with pytest.raises(HTTPException) as exc_info:
            main.get_quote("588890.SS")

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "120"}
    assert "tickflow" in exc_info.value.detail


def test_quote_keeps_404_for_genuine_missing_or_insufficient_symbol():
    with patch.object(main, "analyze_stock", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            main.get_quote("NOT-A-SYMBOL")

    assert exc_info.value.status_code == 404


def test_provider_failure_returns_existing_stale_cache_without_rewriting(
    tmp_path,
):
    symbol = "588890.SS"
    daily = _cached_daily()
    file_path = tmp_path / f"{symbol}.parquet"
    daily.to_parquet(file_path)
    analysis_data._write_data_source_metadata(
        str(file_path),
        symbol,
    )
    stale_mtime = time.time() - analysis_data.CACHE_DURATION_SECONDS - 60
    os.utime(file_path, (stale_mtime, stale_mtime))

    provider_error = ProviderCircuitOpenError(
        "circuit open",
        provider="tickflow",
        key=symbol,
        category="circuit_open",
        retry_after=300,
    )
    weekly = daily.copy()

    with patch.object(
        analysis_data,
        "DATA_DIR",
        str(tmp_path),
    ), patch.object(
        analysis_data,
        "_fetch_new_data",
        side_effect=provider_error,
    ), patch.object(
        analysis_data,
        "_calculate_weekly_indicators",
        return_value=weekly,
    ):
        returned_daily, _ = analysis_data.fetch_stock_data(symbol)

    pd.testing.assert_frame_equal(returned_daily, daily, check_freq=False)
    assert os.path.getmtime(file_path) == stale_mtime


def test_provider_failure_without_cache_raises_market_data_unavailable(
    tmp_path,
):
    symbol = "588890.SS"
    provider_error = ProviderCircuitOpenError(
        "circuit open",
        provider="tickflow",
        key=symbol,
        category="circuit_open",
        retry_after=300,
    )

    with patch.object(
        analysis_data,
        "DATA_DIR",
        str(tmp_path),
    ), patch.object(
        analysis_data,
        "_fetch_new_data",
        side_effect=provider_error,
    ):
        with pytest.raises(MarketDataUnavailableError) as exc_info:
            analysis_data.fetch_stock_data(symbol)

    assert exc_info.value.provider == "tickflow"
    assert exc_info.value.retry_after == 300
