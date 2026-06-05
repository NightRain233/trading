import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_a_share_etf_pure_st_portfolio.py"
SPEC = importlib.util.spec_from_file_location("research_a_share_etf_pure_st_portfolio", SCRIPT_PATH)
research_a_share_etf_pure_st_portfolio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_a_share_etf_pure_st_portfolio)


def _frame(closes):
    index = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=index, dtype="float64")
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": [1000] * len(close),
        },
        index=index,
    )


def test_latest_signal_state_uses_only_rows_up_to_as_of():
    signals = pd.Series(
        [-1, -1, 1],
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )

    assert research_a_share_etf_pure_st_portfolio._latest_signal_state(signals, "2024-01-02") == -1
    assert research_a_share_etf_pure_st_portfolio._latest_signal_state(signals, "2024-01-03") == 1
    assert research_a_share_etf_pure_st_portfolio._latest_signal_state(signals, "2023-12-31") is None


def test_equal_weight_weights_are_normalized():
    weights = research_a_share_etf_pure_st_portfolio._equal_weights(["AAA", "BBB", "CCC"])

    assert weights == {"AAA": 1 / 3, "BBB": 1 / 3, "CCC": 1 / 3}
    assert sum(weights.values()) == 1.0


def test_empty_signal_keeps_portfolio_in_cash():
    frames = {"AAA": _frame([100, 101, 102]), "BBB": _frame([50, 51, 52])}
    empty_signals = {
        "AAA": pd.Series([-1, -1, -1], index=frames["AAA"].index),
        "BBB": pd.Series([-1, -1, -1], index=frames["BBB"].index),
    }

    result = research_a_share_etf_pure_st_portfolio.simulate_weighted_portfolio(
        frames,
        daily_signals=empty_signals,
        weekly_signals={},
        strategy="daily_st_equal_weight",
        start="2024-01-01",
        end="2024-01-03",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert result["totalReturnPct"] == 0.0
    assert result["maxDrawdownPct"] == 0.0
    assert result["averageExposure"] == 0.0
    assert all(point["cashWeight"] == 1.0 for point in result["equityCurve"])


def test_portfolio_equity_and_drawdown_are_calculated_from_rebalanced_weights():
    frames = {"AAA": _frame([100, 110, 55, 66])}
    signals = {"AAA": pd.Series([1, 1, 1, 1], index=frames["AAA"].index)}

    result = research_a_share_etf_pure_st_portfolio.simulate_weighted_portfolio(
        frames,
        daily_signals=signals,
        weekly_signals={},
        strategy="daily_st_equal_weight",
        start="2024-01-01",
        end="2024-01-04",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert round(result["totalReturnPct"], 6) == -40.0
    assert round(result["maxDrawdownPct"], 6) == 50.0
    assert round(result["returnDrawdownRatio"], 6) == -0.8
