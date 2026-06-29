import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
import requests

import analysis_data
from data_source_guard import ProviderBlockingError


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
        result = analysis_data._fetch_new_data(
            "515880.SS",
            last_update,
            now,
            df_local=None,
            file_path="/tmp/515880.SS.parquet",
        )

    assert isinstance(result, analysis_data.AShareRefreshResult)
    assert result.frame.equals(eastmoney_df)
    assert result.full_refresh is True
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

    refreshed_at = datetime(2026, 6, 20, tzinfo=timezone.utc)
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        "515880.SS",
        last_full_refresh_at=refreshed_at,
    )
    assert analysis_data._has_current_data_source(str(parquet_path), "515880.SS")
    metadata = analysis_data._read_data_source_metadata(
        str(parquet_path),
        "515880.SS",
    )
    assert metadata["sourceVersion"] == "eastmoney-qfq-v2"
    assert metadata["lastFullRefreshAt"] == refreshed_at.isoformat()

    analysis_data._invalidate_data_source_metadata(str(parquet_path))
    assert not analysis_data._has_current_data_source(str(parquet_path), "515880.SS")


def test_non_a_share_does_not_require_source_metadata(tmp_path):
    parquet_path = tmp_path / "SPY.parquet"

    assert analysis_data._has_current_data_source(str(parquet_path), "SPY")


def test_v1_source_metadata_is_stale_after_v2_upgrade(tmp_path):
    parquet_path = tmp_path / "515880.SS.parquet"
    metadata_path = tmp_path / "515880.SS.parquet.source.json"
    metadata_path.write_text(
        json.dumps(
            {
                "symbol": "515880.SS",
                "sourceVersion": "eastmoney-qfq-v1",
            }
        ),
        encoding="utf-8",
    )

    assert not analysis_data._has_current_data_source(
        str(parquet_path),
        "515880.SS",
    )


def test_recent_v2_metadata_uses_incremental_refresh(tmp_path):
    parquet_path = tmp_path / "515880.SS.parquet"
    now = datetime(2026, 6, 28, 15, 0)
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        "515880.SS",
        last_full_refresh_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )

    assert not analysis_data._a_share_needs_full_refresh(
        str(parquet_path),
        "515880.SS",
        now,
    )


def test_overdue_v2_metadata_requires_full_refresh(tmp_path):
    parquet_path = tmp_path / "515880.SS.parquet"
    now = datetime(2026, 6, 28, 15, 0)
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        "515880.SS",
        last_full_refresh_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert analysis_data._a_share_needs_full_refresh(
        str(parquet_path),
        "515880.SS",
        now,
    )


def test_stable_overlap_merges_incrementally_without_full_rebase(tmp_path):
    symbol = "515880.SS"
    now = datetime(2026, 6, 28, 15, 0)
    local = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [1.00, 1.01, 1.02, 1.03],
    )
    incremental = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27"],
        [1.00, 1.01, 1.02, 1.04, 1.05],
    )
    parquet_path = tmp_path / f"{symbol}.parquet"
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        symbol,
        last_full_refresh_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )

    with patch.object(
        analysis_data,
        "_fetch_eastmoney_daily",
        return_value=incremental,
    ) as mock_fetch:
        result = analysis_data._fetch_a_share_refresh(
            symbol,
            local,
            local.index[-1],
            str(parquet_path),
            now,
        )

    assert result is not None
    assert result.full_refresh is False
    assert result.frame.loc[pd.Timestamp("2026-06-27"), "Close"] == 1.05
    assert mock_fetch.call_count == 1
    start = mock_fetch.call_args.args[1]
    assert start == local.index[-1].to_pydatetime() - timedelta(
        days=analysis_data.EASTMONEY_INCREMENTAL_OVERLAP_DAYS
    )


def test_changed_completed_overlap_triggers_full_rebase(tmp_path):
    symbol = "515880.SS"
    now = datetime(2026, 6, 28, 15, 0)
    local = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [1.00, 1.01, 1.02, 1.03],
    )
    rebased_overlap = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [0.90, 0.91, 0.92, 1.04],
    )
    full_history = _ohlcv(
        ["2026-06-20", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [0.88, 0.90, 0.91, 0.92, 1.04],
    )
    parquet_path = tmp_path / f"{symbol}.parquet"
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        symbol,
        last_full_refresh_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )

    with patch.object(
        analysis_data,
        "_fetch_eastmoney_daily",
        side_effect=[rebased_overlap, full_history],
    ) as mock_fetch:
        result = analysis_data._fetch_a_share_refresh(
            symbol,
            local,
            local.index[-1],
            str(parquet_path),
            now,
        )

    assert result is not None
    assert result.full_refresh is True
    assert result.frame.equals(full_history)
    assert mock_fetch.call_count == 2


def test_newest_overlap_change_does_not_trigger_full_rebase(tmp_path):
    symbol = "515880.SS"
    now = datetime(2026, 6, 28, 15, 0)
    local = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [1.00, 1.01, 1.02, 1.03],
    )
    incremental = _ohlcv(
        ["2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"],
        [1.00, 1.01, 1.02, 1.04],
    )
    parquet_path = tmp_path / f"{symbol}.parquet"
    analysis_data._write_data_source_metadata(
        str(parquet_path),
        symbol,
        last_full_refresh_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )

    with patch.object(
        analysis_data,
        "_fetch_eastmoney_daily",
        return_value=incremental,
    ) as mock_fetch:
        result = analysis_data._fetch_a_share_refresh(
            symbol,
            local,
            local.index[-1],
            str(parquet_path),
            now,
        )

    assert result is not None
    assert result.full_refresh is False
    assert mock_fetch.call_count == 1


def test_fetch_eastmoney_daily_requests_qfq_and_normalizes_rows():
    captured = {"sessions": 0, "guard_keys": []}

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

        def __init__(self):
            captured["sessions"] += 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, params, timeout):
            captured.update(url=url, params=params, timeout=timeout, trust_env=self.trust_env)
            return FakeResponse()

    class FakeGuard:
        def call(self, key, operation):
            captured["guard_keys"].append(key)
            return operation()

    fake_requests = SimpleNamespace(Session=FakeSession)
    with patch.object(
        analysis_data,
        "requests",
        fake_requests,
        create=True,
    ), patch.object(
        analysis_data,
        "eastmoney_guard",
        FakeGuard(),
        create=True,
    ), patch.object(
        analysis_data,
        "EASTMONEY_PROXY_MODE",
        "direct",
        create=True,
    ):
        result = analysis_data._fetch_eastmoney_daily(
            "515880.SS",
            datetime(2026, 2, 1),
            datetime(2026, 2, 5),
        )

    assert captured["params"]["secid"] == "1.515880"
    assert captured["params"]["fqt"] == "1"
    assert captured["guard_keys"] == ["515880.SS"]
    assert captured["sessions"] == 1
    assert captured["trust_env"] is False
    assert result.index.is_monotonic_increasing
    assert list(result.columns) == ["Open", "Close", "High", "Low", "Volume"]
    assert result.loc[pd.Timestamp("2026-02-03"), "Volume"] == 45600


def test_fetch_eastmoney_daily_environment_route_uses_trust_env():
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2026-02-03,1.084,1.084,1.090,1.070,456",
                    ]
                }
            }

    class FakeSession:
        trust_env = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            captured["trust_env"] = self.trust_env
            return FakeResponse()

    class FakeGuard:
        def call(self, _key, operation):
            return operation()

    with patch.object(
        analysis_data.requests,
        "Session",
        FakeSession,
    ), patch.object(
        analysis_data,
        "eastmoney_guard",
        FakeGuard(),
        create=True,
    ), patch.object(
        analysis_data,
        "EASTMONEY_PROXY_MODE",
        "environment",
        create=True,
    ):
        result = analysis_data._fetch_eastmoney_daily(
            "515880.SS",
            datetime(2026, 2, 1),
            datetime(2026, 2, 5),
        )

    assert result is not None
    assert captured["trust_env"] is True


@pytest.mark.parametrize(
    "message",
    [
        "Remote end closed connection without response",
        "Empty reply from server",
        "Connection reset by peer",
    ],
)
def test_fetch_eastmoney_daily_classifies_silent_disconnect_as_blocking(message):
    class FakeSession:
        trust_env = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            raise requests.ConnectionError(message)

    class PassThroughGuard:
        def call(self, _key, operation):
            return operation()

    with patch.object(
        analysis_data.requests,
        "Session",
        FakeSession,
    ), patch.object(
        analysis_data,
        "eastmoney_guard",
        PassThroughGuard(),
        create=True,
    ):
        with pytest.raises(ProviderBlockingError):
            analysis_data._fetch_eastmoney_daily(
                "515880.SS",
                datetime(2026, 2, 1),
                datetime(2026, 2, 5),
            )


@pytest.mark.parametrize("status_code", [403, 429])
def test_fetch_eastmoney_daily_classifies_http_block_as_blocking(status_code):
    class FakeResponse:
        def raise_for_status(self):
            response = requests.Response()
            response.status_code = status_code
            raise requests.HTTPError(
                f"{status_code} blocked",
                response=response,
            )

    class FakeSession:
        trust_env = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    class PassThroughGuard:
        def call(self, _key, operation):
            return operation()

    with patch.object(
        analysis_data.requests,
        "Session",
        FakeSession,
    ), patch.object(
        analysis_data,
        "eastmoney_guard",
        PassThroughGuard(),
    ):
        with pytest.raises(ProviderBlockingError):
            analysis_data._fetch_eastmoney_daily(
                "515880.SS",
                datetime(2026, 2, 1),
                datetime(2026, 2, 5),
            )


def test_data_source_protection_defaults_are_safe():
    assert analysis_data.EASTMONEY_PROXY_MODE == "direct"
    assert analysis_data.EASTMONEY_MIN_INTERVAL_SECONDS == 1.5
    assert analysis_data.EASTMONEY_CIRCUIT_COOLDOWN_SECONDS == 1800
    assert analysis_data.YAHOO_MIN_INTERVAL_SECONDS == 1.0


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
