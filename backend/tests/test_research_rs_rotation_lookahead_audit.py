import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_rs_rotation_lookahead_audit.py"
SPEC = importlib.util.spec_from_file_location("research_rs_rotation_lookahead_audit", SCRIPT_PATH)
research_rs_rotation_lookahead_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_rs_rotation_lookahead_audit)


def _frame(close_values, open_values=None, start="2024-01-01"):
    index = pd.date_range(start, periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=index)
    open_ = pd.Series(open_values or close_values, index=index)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": pd.concat([open_, close], axis=1).max(axis=1) + 1,
            "Low": pd.concat([open_, close], axis=1).min(axis=1) - 1,
            "Close": close,
            "Volume": [1_000_000_000] * len(index),
        },
        index=index,
    )


def test_next_open_simulation_does_not_buy_on_signal_day(monkeypatch):
    frames = {"AAA": _frame([100, 110, 120], open_values=[100, 111, 121])}

    monkeypatch.setattr(
        research_rs_rotation_lookahead_audit.backtest,
        "_rs_rank_symbols",
        lambda *args, **kwargs: ["AAA"],
    )

    result = research_rs_rotation_lookahead_audit.simulate_rs_rotation_next_open(
        frames,
        top_n=1,
        rebalance_days=20,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        fee_bps=0,
        slippage_bps=0,
    )

    assert result["equityCurve"][0]["holdings"] == []
    assert result["equityCurve"][1]["holdings"] == ["AAA"]
    assert result["equityCurve"][1]["executionDate"] == "2024-01-02"


def test_next_open_simulation_ignores_future_symbol_at_signal_date(monkeypatch):
    old = _frame([100, 101, 102])
    future = _frame([10, 1000], start="2024-02-01")

    def ranker(frames, as_of, *args, **kwargs):
        assert as_of == pd.Timestamp("2024-01-01")
        return ["OLD"]

    monkeypatch.setattr(research_rs_rotation_lookahead_audit.backtest, "_rs_rank_symbols", ranker)

    result = research_rs_rotation_lookahead_audit.simulate_rs_rotation_next_open(
        {"OLD": old, "FUTURE": future},
        top_n=1,
        rebalance_days=20,
        lookback_bars=1,
        min_history_bars=0,
        min_avg_volume=0,
        fee_bps=0,
        slippage_bps=0,
        start="2024-01-01",
        end="2024-01-03",
    )

    assert result["equityCurve"][1]["holdings"] == ["OLD"]


def test_monthly_macd_filter_does_not_use_current_month_end_before_month_is_complete():
    market = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0, 100.0],
            "MACD_DIF": [-1.0, -1.0, 1.0, 1.0],
            "MACD_DEA": [0.0, 0.0, 0.0, 0.0],
        },
        index=pd.to_datetime(["2020-01-31", "2020-02-03", "2020-02-14", "2020-02-28"]),
    )

    assert not research_rs_rotation_lookahead_audit.backtest._rs_market_is_bullish(
        market,
        "monthly_macd",
        pd.Timestamp("2020-02-14"),
        {},
    )
    assert research_rs_rotation_lookahead_audit.backtest._rs_market_is_bullish(
        market,
        "monthly_macd",
        pd.Timestamp("2020-03-02"),
        {},
    )
