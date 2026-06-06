import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "research_dynamic_a_share_theme_etf_st.py"
)
SPEC = importlib.util.spec_from_file_location(
    "research_dynamic_a_share_theme_etf_st",
    SCRIPT_PATH,
)
research = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research)


def _frame(closes, opens=None, volumes=None, start="2024-01-01"):
    index = pd.date_range(start, periods=len(closes), freq="B")
    close = pd.Series(closes, index=index, dtype="float64")
    open_ = pd.Series(opens if opens is not None else closes, index=index, dtype="float64")
    volume = pd.Series(
        volumes if volumes is not None else [1_000_000] * len(closes),
        index=index,
        dtype="float64",
    )
    return pd.DataFrame(
        {
            "Open": open_,
            "High": pd.concat([open_, close], axis=1).max(axis=1) + 1,
            "Low": pd.concat([open_, close], axis=1).min(axis=1) - 1,
            "Close": close,
            "Volume": volume,
        },
        index=index,
    )


def _signal(values, dates):
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype="float64")


def test_etf_cannot_enter_before_first_data_or_minimum_history():
    frame = _frame([10.0] * 6)
    eligibility = research.build_symbol_eligibility(
        frame,
        min_history_bars=3,
        liquidity_lookback=2,
        min_avg_amount=1.0,
    )

    assert research.is_symbol_eligible(eligibility, "2023-12-29") is False
    assert research.is_symbol_eligible(eligibility, frame.index[1]) is False
    assert research.is_symbol_eligible(eligibility, frame.index[2]) is True


def test_etf_fails_fixed_liquidity_rule_using_only_trailing_data():
    frame = _frame(
        [10.0, 10.0, 10.0, 10.0],
        volumes=[100.0, 100.0, 10_000.0, 10_000.0],
    )
    eligibility = research.build_symbol_eligibility(
        frame,
        min_history_bars=2,
        liquidity_lookback=2,
        min_avg_amount=50_000.0,
    )

    assert research.is_symbol_eligible(eligibility, frame.index[1]) is False
    assert research.is_symbol_eligible(eligibility, frame.index[2]) is True


def test_latest_signal_state_never_reads_after_as_of():
    signal = _signal([-1, -1, 1], ["2024-01-01", "2024-01-02", "2024-01-03"])

    assert research.latest_signal_state(signal, "2024-01-02") == -1
    assert research.latest_signal_state(signal, "2024-01-03") == 1
    assert research.latest_signal_state(signal, "2023-12-31") is None


def test_weekly_signal_excludes_unfinished_week():
    daily_index = pd.DatetimeIndex(
        ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-15"]
    )
    raw_weekly = _signal([1, -1], ["2024-01-12", "2024-01-19"])

    aligned = research.align_completed_period_signal(
        daily_index,
        raw_weekly,
        "W-FRI",
    )

    assert aligned.empty


def test_close_signal_executes_at_next_trading_day_open():
    frame = _frame(
        [100.0, 100.0, 120.0],
        opens=[100.0, 110.0, 120.0],
    )
    frames = {"AAA": frame}
    eligibility = {
        "AAA": research.build_symbol_eligibility(
            frame,
            min_history_bars=1,
            liquidity_lookback=1,
            min_avg_amount=1.0,
        )
    }
    daily = {"AAA": _signal([1, 1, 1], frame.index)}

    result = research.simulate_dynamic_portfolio(
        frames=frames,
        eligibility=eligibility,
        pool_symbols=["AAA"],
        strategy="daily_st_equal_weight",
        daily_signals=daily,
        weekly_signals={},
        start=str(frame.index[0].date()),
        end=str(frame.index[-1].date()),
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert result["trades"][0]["date"] == str(frame.index[1].date())
    assert result["trades"][0]["rawPrice"] == 110.0
    assert round(result["totalReturnPct"], 8) == round((120.0 / 110.0 - 1) * 100, 8)


def test_st_gated_rs_ranks_only_symbols_in_same_day_dynamic_pool():
    frames = {
        "AAA": _frame([100.0, 100.0, 110.0]),
        "BBB": _frame([100.0, 100.0, 150.0]),
        "CCC": _frame([100.0, 100.0, 130.0]),
    }
    as_of = frames["AAA"].index[-1]
    pool = ["AAA", "CCC"]
    daily = {
        "AAA": _signal([1], [as_of]),
        "BBB": _signal([1], [as_of]),
        "CCC": _signal([-1], [as_of]),
    }

    selected = research.rank_dynamic_candidates(
        frames,
        pool,
        as_of=as_of,
        lookback_bars=1,
        top_n=2,
        daily_signals=daily,
        require_daily_st=True,
    )

    assert selected == ["AAA"]


def test_metadata_classification_ignores_future_return_fields():
    base = [
        {"symbol": "510300.SS", "bucket": "broad"},
        {"symbol": "512760.SS", "bucket": "sector"},
    ]
    contaminated = [
        {**base[0], "futureReturnPct": -99_999},
        {**base[1], "futureReturnPct": 99_999},
    ]

    assert research.build_metadata_groups(base) == research.build_metadata_groups(contaminated)
    assert research.build_metadata_groups(base) == {
        "broad": ["510300.SS"],
        "theme_proxy": ["512760.SS"],
    }
