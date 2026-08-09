import sys
import types
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import analysis
import main


def test_supertrend_multitimeframe_context_returns_boll_and_volume_ratio():
    index = pd.bdate_range("2024-01-02", periods=460)
    close = pd.Series(range(100, 560), index=index, dtype=float)
    volume = pd.Series([100.0] * 459 + [200.0], index=index)
    daily = pd.DataFrame({"Close": close, "Volume": volume})

    context = main._st_multitimeframe_context(
        daily,
        symbol="510300.SS",
        now=datetime(2026, 8, 3, 16, 0, tzinfo=main.PREWARM_TZ),
    )

    assert context["weeklyBoll"]["mid"] is not None
    assert context["weeklyBoll"]["position"] == "upper_half"
    assert context["weeklyBoll"]["midDirection"] == "rising"
    assert context["weeklyBoll"]["midSlopePct"] > 0
    assert context["weeklyBoll"]["asOf"] == index[-1].date().isoformat()
    assert context["monthlyBoll"]["mid"] is not None
    assert context["monthlyBoll"]["position"] == "upper_half"
    assert context["monthlyBoll"]["midDirection"] == "rising"
    assert context["monthlyBoll"]["midSlopePct"] > 0
    assert context["monthlyBoll"]["asOf"] == index[-1].date().isoformat()
    assert context["volumeContext"]["current"] == 200.0
    assert context["volumeContext"]["ma20"] == 105.0
    assert context["volumeContext"]["ratio20"] == 200.0 / 105.0
    assert context["volumeContext"]["ratio20Completed"] == 200.0 / 105.0
    assert context["volumeContext"]["sessionComplete"] is True
    assert context["volumeContext"]["asOf"] == index[-1].date().isoformat()


def test_supertrend_boll_context_detects_falling_midline():
    close = pd.Series(
        [100.0] * 20 + [80.0],
        index=pd.date_range("2025-01-01", periods=21, freq="ME"),
    )

    context = main._st_boll_context(close)

    assert context["mid"] == 99.0
    assert context["midSlopePct"] == -1.0
    assert context["midDirection"] == "falling"
    assert context["slopeSampleSufficient"] is True


def test_supertrend_boll_context_marks_direction_history_at_exactly_twenty_samples():
    close = pd.Series(
        range(100, 120),
        index=pd.date_range("2024-01-31", periods=20, freq="ME"),
        dtype=float,
    )

    context = main._st_boll_context(close)

    assert context["mid"] is not None
    assert context["midDirection"] is None
    assert context["slopeSampleSufficient"] is False


def test_supertrend_monthly_decision_direction_uses_last_completed_month():
    index = pd.bdate_range(end="2026-08-07", periods=700)
    daily = pd.DataFrame(
        {"Close": range(100, 800), "Volume": [100.0] * 700},
        index=index,
    )

    context = main._st_multitimeframe_context(
        daily,
        symbol="510300.SS",
        now=datetime(2026, 8, 9, 11, 0, tzinfo=main.PREWARM_TZ),
    )

    assert context["monthlyBoll"]["periodComplete"] is False
    assert context["monthlyBoll"]["decisionMidDirection"] == "rising"
    assert context["monthlyBoll"]["decisionAsOf"] == "2026-07-31"


def test_supertrend_volume_context_excludes_incomplete_session_ratio():
    index = pd.to_datetime(["2026-08-02", "2026-08-03"])
    daily = pd.DataFrame(
        {"Close": [100.0, 101.0], "Volume": [100.0, 200.0]},
        index=index,
    )

    context = main._st_multitimeframe_context(
        daily,
        symbol="510300.SS",
        now=datetime(2026, 8, 3, 14, 0, tzinfo=main.PREWARM_TZ),
    )

    assert context["volumeContext"]["ratio20"] is not None
    assert context["volumeContext"]["ratio20Completed"] is None
    assert context["volumeContext"]["sessionComplete"] is False


def test_supertrend_volume_session_completion_uses_market_clock():
    shanghai = main.PREWARM_TZ
    new_york = main.ZoneInfo("America/New_York")

    assert main._st_volume_session_complete(
        "510300.SS", "2026-08-03", datetime(2026, 8, 3, 15, 9, tzinfo=shanghai)
    ) is False
    assert main._st_volume_session_complete(
        "510300.SS", "2026-08-03", datetime(2026, 8, 3, 15, 10, tzinfo=shanghai)
    ) is True
    assert main._st_volume_session_complete(
        "SPY", "2026-08-03", datetime(2026, 8, 3, 16, 9, tzinfo=new_york)
    ) is False
    assert main._st_volume_session_complete(
        "SPY", "2026-08-03", datetime(2026, 8, 3, 16, 10, tzinfo=new_york)
    ) is True
    assert main._st_volume_session_complete(
        "BTC-USD", "2026-08-03", datetime(2026, 8, 3, 23, 59, tzinfo=main.timezone.utc)
    ) is False
    assert main._st_volume_session_complete(
        "BTC-USD", "2026-08-03", datetime(2026, 8, 4, 0, 0, tzinfo=main.timezone.utc)
    ) is True


def test_supertrend_multitimeframe_context_marks_insufficient_boll_history():
    index = pd.bdate_range("2026-01-02", periods=30)
    daily = pd.DataFrame(
        {"Close": range(100, 130), "Volume": [100.0] * 30},
        index=index,
    )

    context = main._st_multitimeframe_context(daily)

    assert context["weeklyBoll"]["mid"] is None
    assert context["weeklyBoll"]["midDirection"] is None
    assert context["weeklyBoll"]["sampleSize"] < 20
    assert context["monthlyBoll"]["mid"] is None
    assert context["monthlyBoll"]["midDirection"] is None
    assert context["monthlyBoll"]["sampleSize"] < 20


def test_supertrend_scan_returns_daily_candles_time_ascending(monkeypatch):
    index = pd.to_datetime(["2026-05-31", "2026-05-29", "2026-06-01"])
    daily = pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0],
            "High": [11.0, 10.0, 12.0],
            "Low": [9.5, 8.8, 10.5],
            "Close": [10.5, 9.2, 11.5],
            "ATR": [1.0, 1.0, 1.0],
            "MACD_Hist": [0.2, 0.1, 0.3],
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

    result = main.supertrend_scan(include_candles=True)

    item = result["items"][0]
    times = [candle["time"] for candle in item["candles"]]
    assert times == sorted(times)
    assert item["indicators"]["macdHistPrev"] == 0.2
    assert item["indicators"]["macdHistDelta"] == pytest.approx(0.1)
    assert item["macdDivergence"]["daily"]["confirmed"] is None
    assert item["macdDivergence"]["policy"]["confirmedOnlyForDecision"] is True


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

    result = main.supertrend_scan(include_candles=True)

    assert fetched == ["MISSING.SZ"]
    assert result["items"][0]["symbol"] == "MISSING.SZ"
    assert result["items"][0]["alias"] == "缺失票"


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

    result = main.supertrend_scan(include_candles=True)

    assert fetched == ["STALE.SZ"]
    assert result["items"][0]["candles"][-1]["time"] == "2026-06-02"


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

    result = main.supertrend_scan(include_candles=True)

    assert [item["symbol"] for item in result["items"]] == ["NEW"]


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

    first_result = main.supertrend_scan(include_candles=True)

    build_daily(22.5).to_parquet(daily_path)
    second_mtime = first_mtime + 10
    main.os.utime(daily_path, (second_mtime, second_mtime))
    second_result = main.supertrend_scan(include_candles=True)

    assert first_result["items"][0]["close"] == 11.5
    assert second_result["items"][0]["close"] == 22.5


def test_supertrend_scan_returns_data_freshness_metadata(monkeypatch, tmp_path):
    latest_date = pd.Timestamp.now().normalize()
    index = pd.date_range(end=latest_date, periods=3, freq="D")
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

    result = main.supertrend_scan(include_candles=True)

    item = result["items"][0]
    assert item["latestDataDate"] == latest_date.date().isoformat()
    assert item["dataUpdatedAt"] is not None
    assert item["cacheStale"] is False
    assert item["dataStale"] is False
    assert item["dataIntegrity"] == {
        "hasGap": False,
        "firstMissingDate": None,
        "expectedLatestDate": None,
    }
