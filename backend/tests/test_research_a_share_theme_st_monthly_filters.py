import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_a_share_theme_st_monthly_filters.py"
SPEC = importlib.util.spec_from_file_location("research_a_share_theme_st_monthly_filters", SCRIPT_PATH)
research_theme_st = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_theme_st)


def _frame(values, start="2020-01-01"):
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value + 1 for value in values],
            "Low": [value - 1 for value in values],
            "Close": values,
            "Volume": [1e9] * len(values),
        },
        index=dates,
    )


def _signal(values, dates):
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype="float64")


def test_completed_weekly_and_monthly_signals_ignore_unfinished_periods():
    daily_index = pd.DatetimeIndex(
        [
            "2020-01-06",
            "2020-01-07",
            "2020-01-08",
            "2020-01-09",
            "2020-01-10",
            "2020-01-13",
        ]
    )
    weekly = _signal([1], ["2020-01-10"])
    aligned_weekly = research_theme_st.align_completed_period_signal(
        daily_index,
        weekly,
        "W-FRI",
    )

    assert research_theme_st.latest_signal_state(aligned_weekly, "2020-01-09") is None
    assert research_theme_st.latest_signal_state(aligned_weekly, "2020-01-10") == 1
    assert research_theme_st.latest_signal_state(aligned_weekly, "2020-01-13") == 1

    month_index = pd.DatetimeIndex(["2020-01-29", "2020-01-30", "2020-02-03"])
    monthly = _signal([1, -1], ["2020-01-31", "2020-02-29"])
    aligned_monthly = research_theme_st.align_completed_period_signal(
        month_index,
        monthly,
        "ME",
    )

    assert research_theme_st.latest_signal_state(aligned_monthly, "2020-01-29") is None
    assert research_theme_st.latest_signal_state(aligned_monthly, "2020-01-30") == 1
    assert research_theme_st.latest_signal_state(aligned_monthly, "2020-02-03") == 1


def test_filtered_st_portfolio_executes_signal_on_next_trading_day():
    frame = _frame([100.0, 100.0, 100.0, 110.0, 110.0], start="2020-01-06")
    frames = {"AAA": frame}
    daily = {"AAA": _signal([-1, 1, 1, 1, 1], frame.index)}
    weekly = {"AAA": _signal([1, 1, 1, 1, 1], frame.index)}

    result = research_theme_st.simulate_filtered_st_equal_weight(
        frames,
        daily_signals=daily,
        weekly_signals=weekly,
        symbol_monthly_st_signals={},
        market_monthly_macd_signal=pd.Series(dtype="float64"),
        market_monthly_st_signal=pd.Series(dtype="float64"),
        strategy="weekly_daily_st_equal_weight",
        start="2020-01-06",
        end="2020-01-10",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    by_date = {point["date"]: point for point in result["equityCurve"]}
    assert by_date["2020-01-07"]["openPositions"] == 0
    assert by_date["2020-01-08"]["openPositions"] == 1
    assert by_date["2020-01-08"]["holdings"] == ["AAA"]


def test_scan_local_a_share_etf_symbols_from_parquet_names(tmp_path):
    for name in [
        "510300.SS.parquet",
        "159915.SZ.parquet",
        "588000.SS.parquet",
        "560000.SS.parquet",
        "513010.SS.parquet",
        "600000.SS.parquet",
        "SPY.parquet",
        "510300.SS_weekly.parquet",
        "515790.SS.csv",
    ]:
        (tmp_path / name).write_text("x")

    assert research_theme_st.scan_local_a_share_etf_symbols(tmp_path) == [
        "159915.SZ",
        "510300.SS",
        "513010.SS",
        "560000.SS",
        "588000.SS",
    ]


def test_monthly_filter_logic_for_market_macd_market_st_and_symbol_st():
    date = pd.Timestamp("2020-01-07")
    signal_as_of = pd.Timestamp("2020-01-06")
    frames = {
        "AAA": _frame([100.0, 101.0], start="2020-01-06"),
        "BBB": _frame([100.0, 101.0], start="2020-01-06"),
    }
    daily = {symbol: _signal([1], [signal_as_of]) for symbol in frames}
    weekly = {symbol: _signal([1], [signal_as_of]) for symbol in frames}
    symbol_monthly = {
        "AAA": _signal([1], [signal_as_of]),
        "BBB": _signal([-1], [signal_as_of]),
    }

    base_kwargs = {
        "date": date,
        "signal_as_of": signal_as_of,
        "frames": frames,
        "daily_signals": daily,
        "weekly_signals": weekly,
        "symbol_monthly_st_signals": symbol_monthly,
    }

    assert research_theme_st.eligible_symbols_for_strategy(
        strategy="weekly_daily_st_equal_weight",
        market_monthly_macd_signal=_signal([-1], [signal_as_of]),
        market_monthly_st_signal=_signal([-1], [signal_as_of]),
        **base_kwargs,
    ) == ["AAA", "BBB"]

    assert research_theme_st.eligible_symbols_for_strategy(
        strategy="market_monthly_macd_weekly_daily_st",
        market_monthly_macd_signal=_signal([-1], [signal_as_of]),
        market_monthly_st_signal=_signal([1], [signal_as_of]),
        **base_kwargs,
    ) == []
    assert research_theme_st.eligible_symbols_for_strategy(
        strategy="market_monthly_macd_weekly_daily_st",
        market_monthly_macd_signal=_signal([1], [signal_as_of]),
        market_monthly_st_signal=_signal([-1], [signal_as_of]),
        **base_kwargs,
    ) == ["AAA", "BBB"]

    assert research_theme_st.eligible_symbols_for_strategy(
        strategy="market_monthly_st_weekly_daily_st",
        market_monthly_macd_signal=_signal([1], [signal_as_of]),
        market_monthly_st_signal=_signal([-1], [signal_as_of]),
        **base_kwargs,
    ) == []

    assert research_theme_st.eligible_symbols_for_strategy(
        strategy="symbol_monthly_st_weekly_daily_st",
        market_monthly_macd_signal=_signal([-1], [signal_as_of]),
        market_monthly_st_signal=_signal([-1], [signal_as_of]),
        **base_kwargs,
    ) == ["AAA"]
