import sys
import types
import time
from pathlib import Path

import pandas as pd

import analysis
import main


def test_supertrend_scan_returns_daily_candles_time_ascending(monkeypatch):
    index = pd.to_datetime(["2026-05-31", "2026-05-29", "2026-06-01"])
    daily = pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0],
            "High": [11.0, 10.0, 12.0],
            "Low": [9.5, 8.8, 10.5],
            "Close": [10.5, 9.2, 11.5],
            "ATR": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    st = pd.DataFrame(
        {
            "SUPERT_7_3.0": [9.0, 8.0, 10.0],
            "SUPERTd_7_3.0": [1, 1, 1],
        },
        index=index,
    )

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(supertrend=lambda *args, **kwargs: st, atr=lambda *args, **kwargs: pd.Series([1.0] * len(daily), index=index)),
    )
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "TEST", "alias": ""}]}])
    monkeypatch.setattr(main.os.path, "exists", lambda path: path.endswith("TEST.parquet"))
    monkeypatch.setattr(pd, "read_parquet", lambda path: daily.copy())
    main._st_scan_cache = {"data": None, "ts": 0.0}

    result = main.supertrend_scan()

    times = [candle["time"] for candle in result[0]["candles"]]
    assert times == sorted(times)


def test_supertrend_scan_fetches_missing_watchlist_parquet_before_scanning(monkeypatch, tmp_path):
    index = pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"])
    daily = pd.DataFrame(
        {
            "Open": [9.0, 10.0, 11.0],
            "High": [10.0, 11.0, 12.0],
            "Low": [8.8, 9.5, 10.5],
            "Close": [9.2, 10.5, 11.5],
            "ATR": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    st = pd.DataFrame(
        {
            "SUPERT_7_3.0": [8.0, 9.0, 10.0],
            "SUPERTd_7_3.0": [1, 1, 1],
        },
        index=index,
    )
    fetched = []

    def fake_fetch(symbols):
        fetched.extend(symbols)
        daily.to_parquet(Path(tmp_path) / "MISSING.SZ.parquet")
        return {}

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(supertrend=lambda *args, **kwargs: st, atr=lambda *args, **kwargs: pd.Series([1.0] * len(daily), index=index)),
    )
    monkeypatch.setattr(analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "MISSING.SZ", "alias": "缺失票"}]}])
    monkeypatch.setattr(main, "batch_fetch_and_update", fake_fetch)
    main._st_scan_cache = {"data": None, "ts": 0.0}

    result = main.supertrend_scan()

    assert fetched == ["MISSING.SZ"]
    assert result[0]["symbol"] == "MISSING.SZ"
    assert result[0]["alias"] == "缺失票"


def test_supertrend_scan_refreshes_existing_stale_watchlist_parquet_before_scanning(monkeypatch, tmp_path):
    stale_daily = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.5],
            "Close": [10.5],
            "ATR": [1.0],
        },
        index=pd.to_datetime(["2026-06-01"]),
    )
    refreshed_daily = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [11.0, 12.0],
            "Low": [9.5, 10.5],
            "Close": [10.5, 11.5],
            "ATR": [1.0, 1.0],
        },
        index=pd.to_datetime(["2026-06-01", "2026-06-02"]),
    )
    st = pd.DataFrame(
        {
            "SUPERT_7_3.0": [9.0, 10.0],
            "SUPERTd_7_3.0": [1, 1],
        },
        index=refreshed_daily.index,
    )
    daily_path = Path(tmp_path) / "STALE.SZ.parquet"
    stale_daily.to_parquet(daily_path)
    old_mtime = time.time() - (analysis.CACHE_DURATION_SECONDS + 60)
    main.os.utime(daily_path, (old_mtime, old_mtime))
    fetched = []

    def fake_fetch(symbols):
        fetched.extend(symbols)
        refreshed_daily.to_parquet(daily_path)
        return {}

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(supertrend=lambda *args, **kwargs: st, atr=lambda *args, **kwargs: pd.Series([1.0] * len(refreshed_daily), index=refreshed_daily.index)),
    )
    monkeypatch.setattr(analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "STALE.SZ", "alias": "旧数据"}]}])
    monkeypatch.setattr(main, "batch_fetch_and_update", fake_fetch)
    main._st_scan_cache = {"data": None, "ts": 0.0}

    result = main.supertrend_scan()

    assert fetched == ["STALE.SZ"]
    assert result[0]["candles"][-1]["time"] == "2026-06-02"


def test_supertrend_scan_cache_is_scoped_to_watchlist_symbols(monkeypatch):
    index = pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"])
    daily = pd.DataFrame(
        {
            "Open": [9.0, 10.0, 11.0],
            "High": [10.0, 11.0, 12.0],
            "Low": [8.8, 9.5, 10.5],
            "Close": [9.2, 10.5, 11.5],
            "ATR": [1.0, 1.0, 1.0],
        },
        index=index,
    )
    st = pd.DataFrame(
        {
            "SUPERT_7_3.0": [8.0, 9.0, 10.0],
            "SUPERTd_7_3.0": [1, 1, 1],
        },
        index=index,
    )

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(supertrend=lambda *args, **kwargs: st, atr=lambda *args, **kwargs: pd.Series([1.0] * len(daily), index=index)),
    )
    monkeypatch.setattr(main.os.path, "exists", lambda path: path.endswith(".parquet"))
    monkeypatch.setattr(pd, "read_parquet", lambda path: daily.copy())
    main._st_scan_cache = {"data": [{"symbol": "OLD"}], "ts": 9999999999, "symbols": ["OLD"]}
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "NEW", "alias": ""}]}])

    result = main.supertrend_scan()

    assert [item["symbol"] for item in result] == ["NEW"]


def test_supertrend_scan_cache_invalidates_when_daily_parquet_mtime_changes(monkeypatch, tmp_path):
    index = pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"])

    def build_daily(close):
        return pd.DataFrame(
            {
                "Open": [9.0, 10.0, close],
                "High": [10.0, 11.0, close + 1.0],
                "Low": [8.8, 9.5, close - 1.0],
                "Close": [9.2, 10.5, close],
                "ATR": [1.0, 1.0, 1.0],
            },
            index=index,
        )

    def fake_supertrend(high, low, close, *args, **kwargs):
        return pd.DataFrame(
            {
                "SUPERT_7_3.0": close - 1.0,
                "SUPERTd_7_3.0": [1] * len(close),
            },
            index=close.index,
        )

    daily_path = Path(tmp_path) / "TEST.parquet"
    build_daily(11.5).to_parquet(daily_path)
    first_mtime = time.time()
    main.os.utime(daily_path, (first_mtime, first_mtime))

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(supertrend=fake_supertrend, atr=lambda *args, **kwargs: pd.Series([1.0] * len(index), index=index)),
    )
    monkeypatch.setattr(analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "TEST", "alias": ""}]}])
    monkeypatch.setattr(main, "batch_fetch_and_update", lambda symbols: {})
    main._st_scan_cache = {"data": None, "ts": 0.0}

    first_result = main.supertrend_scan()

    build_daily(22.5).to_parquet(daily_path)
    second_mtime = first_mtime + 10
    main.os.utime(daily_path, (second_mtime, second_mtime))
    second_result = main.supertrend_scan()

    assert first_result[0]["close"] == 11.5
    assert second_result[0]["close"] == 22.5


def test_supertrend_scan_returns_data_freshness_metadata(monkeypatch, tmp_path):
    index = pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"])
    daily = pd.DataFrame(
        {
            "Open": [9.0, 10.0, 11.0],
            "High": [10.0, 11.0, 12.0],
            "Low": [8.8, 9.5, 10.5],
            "Close": [9.2, 10.5, 11.5],
            "ATR": [1.0, 1.0, 1.0],
        },
        index=index,
    )

    def fake_supertrend(high, low, close, *args, **kwargs):
        return pd.DataFrame(
            {
                "SUPERT_7_3.0": close - 1.0,
                "SUPERTd_7_3.0": [1] * len(close),
            },
            index=close.index,
        )

    daily_path = Path(tmp_path) / "TEST.parquet"
    daily.to_parquet(daily_path)
    data_mtime = time.time()
    main.os.utime(daily_path, (data_mtime, data_mtime))

    monkeypatch.setitem(
        sys.modules,
        "pandas_ta",
        types.SimpleNamespace(fake_supertrend=fake_supertrend, supertrend=fake_supertrend, atr=lambda *args, **kwargs: pd.Series([1.0] * len(index), index=index)),
    )
    monkeypatch.setattr(analysis, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "load_watchlist", lambda: [{"symbols": [{"symbol": "TEST", "alias": ""}]}])
    monkeypatch.setattr(main, "batch_fetch_and_update", lambda symbols: {})
    main._st_scan_cache = {"data": None, "ts": 0.0}

    result = main.supertrend_scan()

    item = result[0]
    assert item["latestDataDate"] == "2026-06-02"
    assert item["dataUpdatedAt"] is not None
    assert item["cacheStale"] is False
    assert item["dataStale"] is False
    assert item["dataIntegrity"] == {
        "hasGap": False,
        "firstMissingDate": None,
        "expectedLatestDate": None,
    }
