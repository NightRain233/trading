import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_a_share_dca_timing.py"
SPEC = importlib.util.spec_from_file_location("research_a_share_dca_timing", SCRIPT_PATH)
research_dca = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_dca)


def _frame(values, start="2020-01-01"):
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value + 1 for value in values],
            "Low": [value - 1 for value in values],
            "Close": values,
            "Volume": [1_000_000.0] * len(values),
        },
        index=dates,
    )


def _signal(values, dates):
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype="float64")


def test_monthly_contribution_only_runs_on_first_trading_day_of_month():
    frame = _frame(
        [100.0, 101.0, 102.0, 110.0, 111.0],
        start="2020-01-30",
    )

    result = research_dca.simulate_dca(
        {"AAA": frame},
        start="2020-01-30",
        end="2020-02-05",
        monthly_budget=100.0,
        allocation_mode="single",
        target_symbol="AAA",
        market_signal=pd.Series(dtype="float64"),
        multiplier_policy="fixed_100",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert [flow["date"] for flow in result["cashFlows"]] == ["2020-01-30", "2020-02-03"]
    assert result["cashFlows"][0]["amount"] == 100.0
    assert result["cashFlows"][1]["amount"] == 100.0


def test_monthly_signal_ignores_unfinished_month_until_first_trading_day_after_completion():
    daily_index = pd.DatetimeIndex(["2020-01-30", "2020-02-03"])
    monthly = _signal([1.0, -1.0], ["2020-01-31", "2020-02-29"])

    aligned = research_dca.align_completed_month_signal(daily_index, monthly)

    assert research_dca.latest_signal_state(aligned, "2020-01-30") is None
    assert research_dca.latest_signal_state(aligned, "2020-02-03") == 1


def test_completed_month_signal_alignment_applies_to_macd_ma10_and_supertrend_inputs():
    daily_index = pd.DatetimeIndex(["2020-01-30", "2020-02-03"])
    raw_signals = {
        "macd": _signal([1.0, -1.0], ["2020-01-31", "2020-02-29"]),
        "ma10": _signal([-1.0, 1.0], ["2020-01-31", "2020-02-29"]),
        "supertrend": _signal([1.0, -1.0], ["2020-01-31", "2020-02-29"]),
    }

    for raw in raw_signals.values():
        aligned = research_dca.align_completed_month_signal(daily_index, raw)
        assert research_dca.latest_signal_state(aligned, "2020-01-30") is None
        assert research_dca.latest_signal_state(aligned, "2020-02-03") in {1, -1}


def test_market_breadth_200dma_uses_only_data_on_or_before_signal_date():
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
    frames = {
        "AAA": pd.DataFrame({"Close": [100.0, 90.0, 130.0], "MA200": [95.0, 95.0, 95.0]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0, 90.0, 130.0], "MA200": [95.0, 95.0, 95.0]}, index=dates),
    }

    signal = research_dca.market_breadth_200dma_signal(frames, ["AAA", "BBB"], threshold=0.5)

    assert research_dca.latest_signal_state(signal, "2020-01-01") == 1
    assert research_dca.latest_signal_state(signal, "2020-01-02") == -1
    assert research_dca.latest_signal_state(signal, "2020-01-03") == 1


def test_market_regime_multiplier_policy_maps_states_to_contribution_amounts():
    assert research_dca.contribution_multiplier("fixed_100", None) == 1.0
    assert research_dca.contribution_multiplier("macd_pause_bear", 1) == 1.0
    assert research_dca.contribution_multiplier("macd_pause_bear", -1) == 0.0
    assert research_dca.contribution_multiplier("macd_half_bear", 1) == 1.0
    assert research_dca.contribution_multiplier("macd_half_bear", -1) == 0.5
    assert research_dca.contribution_multiplier("macd_half_bear", None) == 1.0
    assert research_dca.contribution_multiplier("ma10_pause_bear", -1) == 0.0
    assert research_dca.contribution_multiplier("ma10_half_bear", -1) == 0.5
    assert research_dca.contribution_multiplier("st_pause_bear", -1) == 0.0
    assert research_dca.contribution_multiplier("st_half_bear", -1) == 0.5
    assert research_dca.contribution_multiplier("breadth_pause_bear", -1) == 0.0
    assert research_dca.contribution_multiplier("breadth_half_bear", -1) == 0.5


def test_combined_macd_breadth_state_mappings_are_explicit():
    assert research_dca.combined_multiplier("both_strong_step", 1, 1) == 1.0
    assert research_dca.combined_multiplier("both_strong_step", 1, -1) == 0.5
    assert research_dca.combined_multiplier("both_strong_step", -1, 1) == 0.5
    assert research_dca.combined_multiplier("both_strong_step", -1, -1) == 0.0

    assert research_dca.combined_multiplier("any_weak_pause", 1, 1) == 1.0
    assert research_dca.combined_multiplier("any_weak_pause", 1, -1) == 0.0
    assert research_dca.combined_multiplier("any_weak_half", 1, -1) == 0.5
    assert research_dca.combined_multiplier("any_weak_half", -1, -1) == 0.5


def test_dca_summary_separates_principal_return_drawdown_and_calendar_year_extremes():
    dates = pd.date_range("2020-12-30", periods=5, freq="B")
    frame = pd.DataFrame(
        {
            "Open": [100.0, 120.0, 120.0, 120.0, 60.0],
            "High": [121.0, 121.0, 121.0, 121.0, 61.0],
            "Low": [99.0, 119.0, 119.0, 59.0, 59.0],
            "Close": [120.0, 120.0, 120.0, 60.0, 60.0],
            "Volume": [1_000_000.0] * 5,
        },
        index=dates,
    )

    result = research_dca.simulate_dca(
        {"AAA": frame},
        start="2020-12-30",
        end="2021-01-05",
        monthly_budget=100.0,
        allocation_mode="single",
        target_symbol="AAA",
        market_signal=pd.Series(dtype="float64"),
        multiplier_policy="fixed_100",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    summary = research_dca.summarize_dca_result(result)

    assert summary["investedPrincipal"] == 200.0
    assert summary["principalReturnPct"] == -45.0
    assert summary["accountMaxDrawdownPct"] == 50.0
    assert summary["cashDeploymentRatio"] == 1.0
    assert summary["bestCalendarYear"]["year"] == "2020"
    assert summary["bestCalendarYear"]["principalReturnPct"] == 20.0
    assert summary["bestCalendarYear"]["accountMaxDrawdownPct"] == 0.0
    assert summary["worstCalendarYear"]["year"] == "2021"
    assert summary["worstCalendarYear"]["principalReturnPct"] == -50.0
    assert summary["worstRolling3y"] is None
    assert summary["worstRolling5y"] is None
