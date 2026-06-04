import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compare_supertrend_timeframes.py"
SPEC = importlib.util.spec_from_file_location("compare_supertrend_timeframes", SCRIPT_PATH)
compare_supertrend_timeframes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_supertrend_timeframes)


def _daily_prices() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0, 99.0, 100.0, 105.0, 111.0, 112.0],
            "High": [101.0, 100.0, 106.0, 112.0, 113.0, 114.0],
            "Low": [98.0, 97.0, 99.0, 104.0, 109.0, 110.0],
            "Close": [99.0, 98.0, 104.0, 110.0, 111.0, 113.0],
            "Volume": [1000] * 6,
        },
        index=index,
    )


def _weekly_prices() -> pd.DataFrame:
    index = pd.date_range("2023-12-31", periods=2, freq="W")
    return pd.DataFrame(
        {
            "Open": [95.0, 100.0],
            "High": [101.0, 114.0],
            "Low": [94.0, 97.0],
            "Close": [99.0, 113.0],
            "Volume": [5000, 5000],
        },
        index=index,
    )


def _fake_supertrend(high, low, close, *args, **kwargs):
    index = high.index
    if len(index) == 6:
        directions = [-1, -1, 1, 1, -1, -1]
        lines = [104.0, 103.0, 100.0, 101.0, 109.0, 110.0]
    else:
        directions = [1] * len(index)
        lines = [95.0] * len(index)
    return pd.DataFrame(
        {
            "SUPERT_7_3.0": lines,
            "SUPERTd_7_3.0": directions,
        },
        index=index,
    )


def _patch_indicators(monkeypatch, bb_rank=0.1, atr=5.0):
    def fake_bbands(close, *args, **kwargs):
        width = close * 0.1
        return pd.DataFrame(
            {
                "BBL_20_2.0": close - width / 2,
                "BBU_20_2.0": close + width / 2,
            },
            index=close.index,
        )

    monkeypatch.setattr(
        compare_supertrend_timeframes,
        "ta",
        SimpleNamespace(
            supertrend=_fake_supertrend,
            bbands=fake_bbands,
            atr=lambda high, low, close, *args, **kwargs: pd.Series([atr] * len(close), index=close.index),
        ),
    )
    monkeypatch.setattr(
        compare_supertrend_timeframes,
        "_rolling_percentile_rank",
        lambda series, window: pd.Series([bb_rank] * len(series), index=series.index),
        raising=False,
    )


def test_daily_st_strategy_executes_confirmed_flip_at_next_open(monkeypatch):
    _patch_indicators(monkeypatch)

    result = compare_supertrend_timeframes._daily_st_strategy(
        "TEST",
        _daily_prices(),
        _weekly_prices(),
        "2024-01-01",
        "2024-01-06",
    )

    assert result["tradeCount"] == 1
    assert result["trades"][0]["entryDate"] == "2024-01-04"
    assert result["trades"][0]["entryPrice"] == 105.0 * 1.0005


def test_bb_squeeze_filter_requires_bandwidth_rank_under_threshold(monkeypatch):
    _patch_indicators(monkeypatch, bb_rank=0.4)

    result = compare_supertrend_timeframes._daily_st_strategy(
        "TEST",
        _daily_prices(),
        _weekly_prices(),
        "2024-01-01",
        "2024-01-06",
        bb_squeeze_max_rank=0.2,
    )

    assert result["tradeCount"] == 0
    assert result["openPosition"] is None


def test_no_chase_filter_rejects_entry_too_far_above_st_line(monkeypatch):
    _patch_indicators(monkeypatch, atr=4.0)

    result = compare_supertrend_timeframes._daily_st_strategy(
        "TEST",
        _daily_prices(),
        _weekly_prices(),
        "2024-01-01",
        "2024-01-06",
        max_entry_distance_atr=1.0,
    )

    assert result["tradeCount"] == 0
    assert result["openPosition"] is None


def test_analyze_symbol_includes_weekly_daily_bb_squeeze_variant(monkeypatch):
    _patch_indicators(monkeypatch, bb_rank=0.1)
    monkeypatch.setattr(compare_supertrend_timeframes, "_load_daily", lambda symbol: _daily_prices())
    monkeypatch.setattr(compare_supertrend_timeframes, "_load_weekly", lambda symbol, daily: _weekly_prices())

    result = compare_supertrend_timeframes._analyze_symbol(
        {"symbol": "BTC-USD"},
        "2024-01-01",
        "2024-01-06",
    )

    assert result["weeklyDailyStBbSqueeze20"]["tradeCount"] == 1
    assert result["weeklyDailyStBbSqueeze20"]["trades"][0]["entryDate"] == "2024-01-04"


def test_summary_groups_rows_by_asset_bucket():
    rows = [
        {
            "symbol": "BTC-USD",
            "assetBucket": "crypto",
            "buyHold": {"returnPct": 10.0, "returnDrawdownRatio": 1.0},
            "dailySt": {"returnPct": 20.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 4.0},
            "weeklySt": {"returnPct": 15.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 3.0},
            "weeklyDailySt": {"returnPct": 12.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 2.4},
            "weeklyDailyStBbSqueeze20": {"returnPct": 24.0, "maxDrawdownPct": 4.0, "returnDrawdownRatio": 6.0},
            "dailyStBbSqueeze20": {"returnPct": 25.0, "maxDrawdownPct": 4.0, "returnDrawdownRatio": 6.25},
            "dailyStBbSqueeze30": {"returnPct": 22.0, "maxDrawdownPct": 4.0, "returnDrawdownRatio": 5.5},
            "dailyStNoChaseAtr1": {"returnPct": 18.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 3.6},
        },
        {
            "symbol": "SPY",
            "assetBucket": "us_etf",
            "buyHold": {"returnPct": 30.0, "returnDrawdownRatio": 3.0},
            "dailySt": {"returnPct": 10.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 2.0},
            "weeklySt": {"returnPct": 8.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 1.6},
            "weeklyDailySt": {"returnPct": 7.0, "maxDrawdownPct": 5.0, "returnDrawdownRatio": 1.4},
            "weeklyDailyStBbSqueeze20": {"returnPct": 4.0, "maxDrawdownPct": 3.0, "returnDrawdownRatio": 1.33},
            "dailyStBbSqueeze20": {"returnPct": 5.0, "maxDrawdownPct": 3.0, "returnDrawdownRatio": 1.67},
            "dailyStBbSqueeze30": {"returnPct": 6.0, "maxDrawdownPct": 3.0, "returnDrawdownRatio": 2.0},
            "dailyStNoChaseAtr1": {"returnPct": 9.0, "maxDrawdownPct": 4.0, "returnDrawdownRatio": 2.25},
        },
    ]

    summary = compare_supertrend_timeframes._summarize(rows)

    assert summary["byAssetBucket"]["crypto"]["symbolCount"] == 1
    assert summary["byAssetBucket"]["crypto"]["dailyStBbSqueeze20"]["avgReturnPct"] == 25.0
    assert summary["byAssetBucket"]["us_etf"]["dailySt"]["beatBuyHoldReturnCount"] == 0


def test_asset_bucket_separates_a_share_etfs_from_stocks():
    bucket = compare_supertrend_timeframes._asset_bucket

    assert bucket({"symbol": "510500.SS"}) == "a_share_etf"
    assert bucket({"symbol": "159869.SZ"}) == "a_share_etf"
    assert bucket({"symbol": "600487.SS"}) == "a_share_stock"
    assert bucket({"symbol": "002796.SZ"}) == "a_share_stock"


def test_add_supertrend_passes_custom_parameters_to_indicator(monkeypatch):
    calls = []

    def fake_supertrend(high, low, close, *args, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "SUPERT_10_4.0": [100.0] * len(close),
                "SUPERTd_10_4.0": [1] * len(close),
            },
            index=close.index,
        )

    monkeypatch.setattr(
        compare_supertrend_timeframes,
        "ta",
        SimpleNamespace(supertrend=fake_supertrend),
    )

    result = compare_supertrend_timeframes._add_supertrend(
        _daily_prices(),
        "_daily",
        st_length=10,
        st_multiplier=4.0,
    )

    assert calls == [{"length": 10, "multiplier": 4.0}]
    assert result["_daily_dir"].tolist() == [1] * 6
    assert result["_daily_line"].tolist() == [100.0] * 6


def _strategy_payload(return_pct, ratio):
    return {
        "returnPct": return_pct,
        "maxDrawdownPct": 10.0,
        "returnDrawdownRatio": ratio,
        "tradeCount": 1,
    }


def _grid_row(symbol, bucket, return_pct, ratio):
    row = {
        "symbol": symbol,
        "assetBucket": bucket,
        "buyHold": {"returnPct": 0.0, "returnDrawdownRatio": 0.0},
    }
    for key in compare_supertrend_timeframes.STRATEGY_KEYS:
        row[key] = _strategy_payload(return_pct, ratio)
    return row


def test_parameter_grid_selects_best_config_by_asset_bucket(monkeypatch):
    include_variant_flags = []

    def fake_prepare_symbol_data(metas):
        return [
            {"meta": meta, "daily": _daily_prices(), "weekly": _weekly_prices()}
            for meta in metas
        ]

    def fake_analyze_symbol_from_data(meta, daily, weekly, start, end, st_length=7, st_multiplier=3.0, include_variants=True):
        assert daily is not None
        assert weekly is not None
        include_variant_flags.append(include_variants)
        bucket = compare_supertrend_timeframes._asset_bucket(meta)
        score = 1.0
        if bucket == "crypto" and st_length == 10 and st_multiplier == 4.0:
            score = 5.0
        if bucket == "us_etf" and st_length == 5 and st_multiplier == 2.0:
            score = 4.0
        return _grid_row(meta["symbol"], bucket, score * 10.0, score)

    monkeypatch.setattr(compare_supertrend_timeframes, "_prepare_symbol_data", fake_prepare_symbol_data)
    monkeypatch.setattr(compare_supertrend_timeframes, "_analyze_symbol_from_data", fake_analyze_symbol_from_data)

    result = compare_supertrend_timeframes._run_parameter_grid(
        [{"symbol": "BTC-USD"}, {"symbol": "SPY"}],
        "2024-01-01",
        "2024-12-31",
        [5, 10],
        [2.0, 4.0],
    )

    assert result["bestByAssetBucket"]["crypto"]["stLength"] == 10
    assert result["bestByAssetBucket"]["crypto"]["stMultiplier"] == 4.0
    assert result["bestByAssetBucket"]["us_etf"]["stLength"] == 5
    assert result["bestByAssetBucket"]["us_etf"]["stMultiplier"] == 2.0
    assert include_variant_flags == [False] * 8


def test_year_windows_clip_to_requested_start_and_end():
    windows = compare_supertrend_timeframes._year_windows("2022-06-01", "2024-03-10")

    assert windows == [
        {"year": "2022", "start": "2022-06-01", "end": "2022-12-31"},
        {"year": "2023", "start": "2023-01-01", "end": "2023-12-31"},
        {"year": "2024", "start": "2024-01-01", "end": "2024-03-10"},
    ]


def test_weekly_dirs_align_to_latest_closed_week():
    daily_index = pd.date_range("2024-01-01", periods=8, freq="D")
    weekly = pd.DataFrame(
        {"_weekly_dir": [1.0, -1.0]},
        index=pd.to_datetime(["2023-12-31", "2024-01-07"]),
    )

    aligned = compare_supertrend_timeframes._weekly_dirs_for_index(daily_index, weekly)

    assert aligned == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, -1.0, -1.0]


def test_annual_summary_runs_each_year_window(monkeypatch):
    calls = []

    def fake_analyze_symbol(meta, start, end, st_length=7, st_multiplier=3.0):
        calls.append((meta["symbol"], start, end, st_length, st_multiplier))
        return _grid_row(meta["symbol"], "crypto", 10.0, 1.0)

    monkeypatch.setattr(compare_supertrend_timeframes, "_analyze_symbol", fake_analyze_symbol)

    result = compare_supertrend_timeframes._build_annual_summary(
        [{"symbol": "BTC-USD"}],
        "2022-06-01",
        "2023-03-10",
        st_length=10,
        st_multiplier=4.0,
    )

    assert [row["year"] for row in result] == ["2022", "2023"]
    assert calls == [
        ("BTC-USD", "2022-06-01", "2022-12-31", 10, 4.0),
        ("BTC-USD", "2023-01-01", "2023-03-10", 10, 4.0),
    ]


def test_analyze_symbol_reuses_indicator_context_for_variants(monkeypatch):
    calls = {"supertrend": 0, "bbands": 0, "atr": 0}

    def fake_supertrend(high, low, close, *args, **kwargs):
        calls["supertrend"] += 1
        return _fake_supertrend(high, low, close, *args, **kwargs)

    def fake_bbands(close, *args, **kwargs):
        calls["bbands"] += 1
        width = close * 0.1
        return pd.DataFrame(
            {
                "BBL_20_2.0": close - width / 2,
                "BBU_20_2.0": close + width / 2,
            },
            index=close.index,
        )

    def fake_atr(high, low, close, *args, **kwargs):
        calls["atr"] += 1
        return pd.Series([5.0] * len(close), index=close.index)

    monkeypatch.setattr(compare_supertrend_timeframes, "_load_daily", lambda symbol: _daily_prices())
    monkeypatch.setattr(compare_supertrend_timeframes, "_load_weekly", lambda symbol, daily: _weekly_prices())
    monkeypatch.setattr(
        compare_supertrend_timeframes,
        "ta",
        SimpleNamespace(supertrend=fake_supertrend, bbands=fake_bbands, atr=fake_atr),
    )
    monkeypatch.setattr(
        compare_supertrend_timeframes,
        "_rolling_percentile_rank",
        lambda series, window: pd.Series([0.1] * len(series), index=series.index),
    )

    compare_supertrend_timeframes._analyze_symbol(
        {"symbol": "BTC-USD"},
        "2024-01-01",
        "2024-01-06",
    )

    assert calls == {"supertrend": 2, "bbands": 1, "atr": 1}
