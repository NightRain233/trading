import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_st_position_sizing.py"
SPEC = importlib.util.spec_from_file_location("research_st_position_sizing", SCRIPT_PATH)
research_st_position_sizing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_st_position_sizing)


def test_market_exposure_uses_daily_and_weekly_supertrend_state():
    assert research_st_position_sizing._market_exposure(1, 1) == 1.0
    assert research_st_position_sizing._market_exposure(1, -1) == 0.5
    assert research_st_position_sizing._market_exposure(-1, 1) == 0.5
    assert research_st_position_sizing._market_exposure(-1, -1) == 0.25
    assert research_st_position_sizing._market_exposure(None, 1) == 0.5


def test_symbol_exposure_suppresses_daily_bear_symbols():
    assert research_st_position_sizing._symbol_exposure(1) == 1.0
    assert research_st_position_sizing._symbol_exposure(-1) == 0.0
    assert research_st_position_sizing._symbol_exposure(None) == 0.0


def test_latest_st_dir_uses_only_rows_up_to_as_of():
    dirs = pd.Series(
        [-1, -1, 1],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )

    assert research_st_position_sizing._latest_st_dir(dirs, "2024-01-02") == -1
    assert research_st_position_sizing._latest_st_dir(dirs, "2024-01-03") == 1
    assert research_st_position_sizing._latest_st_dir(dirs, "2023-12-31") is None


def _price_frame(symbol_shift=0.0):
    index = pd.date_range("2024-01-01", periods=8, freq="D")
    close = pd.Series([100 + symbol_shift, 101 + symbol_shift, 102 + symbol_shift, 103 + symbol_shift, 104 + symbol_shift, 105 + symbol_shift, 106 + symbol_shift, 107 + symbol_shift], index=index)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": [1000] * len(index),
        },
        index=index,
    )


def test_market_st_exposure_leaves_uninvested_cash(monkeypatch):
    frames = {"AAA": _price_frame(), "BBB": _price_frame(10)}
    market_dirs = pd.Series([1] * 8, index=frames["AAA"].index)
    weak_dirs = pd.Series([-1] * 8, index=frames["AAA"].index)

    monkeypatch.setattr(
        research_st_position_sizing.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA", "BBB"],
    )
    monkeypatch.setattr(
        research_st_position_sizing,
        "_supertrend_dir",
        lambda df, timeframe="daily": market_dirs if timeframe == "daily" else weak_dirs,
    )

    result = research_st_position_sizing.simulate_rs_rotation_with_st_exposure(
        frames,
        market_df=frames["AAA"],
        top_n=2,
        rebalance_days=20,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        exposure_mode="market",
    )

    first = result["equityCurve"][0]
    assert first["targetExposure"] == 0.5
    assert first["cash"] > 0.45
    assert first["openPositions"] == 2


def test_symbol_st_exposure_suppresses_daily_bear_symbol(monkeypatch):
    frames = {"AAA": _price_frame(), "BBB": _price_frame(10)}
    bull_dirs = pd.Series([1] * 8, index=frames["AAA"].index)
    bear_dirs = pd.Series([-1] * 8, index=frames["AAA"].index)

    monkeypatch.setattr(
        research_st_position_sizing.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA", "BBB"],
    )

    def fake_supertrend_dir(df, timeframe="daily"):
        if timeframe == "weekly":
            return bull_dirs
        return bear_dirs if float(df.iloc[0]["Close"]) > 105 else bull_dirs

    monkeypatch.setattr(research_st_position_sizing, "_supertrend_dir", fake_supertrend_dir)

    result = research_st_position_sizing.simulate_rs_rotation_with_st_exposure(
        frames,
        market_df=frames["AAA"],
        top_n=2,
        rebalance_days=20,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        exposure_mode="market_symbol",
    )

    first = result["equityCurve"][0]
    assert first["targetExposure"] == 1.0
    assert first["holdings"] == ["AAA"]
    assert first["cash"] > 0.45
