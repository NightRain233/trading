import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_a_share_weekly_daily_st_equal_weight.py"
SPEC = importlib.util.spec_from_file_location("research_a_share_weekly_daily_st_equal_weight", SCRIPT_PATH)
research_st_equal_weight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_st_equal_weight)


def _frame(values):
    dates = pd.date_range("2020-01-01", periods=len(values), freq="B")
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


def test_build_universes_keeps_core_and_conservative_broad_bucket():
    universes = research_st_equal_weight.build_universes()

    assert "510300.SS" in universes["a_share_broad"]
    assert "159915.SZ" in universes["a_share_broad"]
    assert "512760.SS" not in universes["a_share_broad"]
    assert "159552.SZ" not in universes["a_share_broad"]
    assert "512760.SS" in universes["a_share_core"]


def test_weekly_daily_st_signal_executes_on_next_trading_day(monkeypatch):
    frame = _frame([100.0, 100.0, 100.0, 100.0, 100.0, 110.0, 110.0, 110.0])

    def fake_supertrend_dir(source, length=7, multiplier=3.0):
        if len(source) < 5:
            return pd.Series([1] * len(source), index=source.index, dtype="float64")
        return pd.Series([-1] + [1] * (len(source) - 1), index=source.index, dtype="float64")

    monkeypatch.setattr(research_st_equal_weight, "_supertrend_dir", fake_supertrend_dir)

    result = research_st_equal_weight.simulate_weekly_daily_st_equal_weight(
        {"AAA": frame},
        start="2020-01-01",
        end="2020-01-10",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    by_date = {point["date"]: point for point in result["equityCurve"]}
    assert by_date["2020-01-06"]["openPositions"] == 0
    assert by_date["2020-01-07"]["openPositions"] == 1
    assert by_date["2020-01-07"]["holdings"] == ["AAA"]


def test_equal_weight_holds_all_eligible_symbols(monkeypatch):
    frames = {
        "AAA": _frame([100.0] * 8),
        "BBB": _frame([50.0] * 8),
    }

    def fake_supertrend_dir(source, length=7, multiplier=3.0):
        return pd.Series([1] * len(source), index=source.index, dtype="float64")

    monkeypatch.setattr(research_st_equal_weight, "_supertrend_dir", fake_supertrend_dir)

    result = research_st_equal_weight.simulate_weekly_daily_st_equal_weight(
        frames,
        start="2020-01-01",
        end="2020-01-10",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert result["equityCurve"][-1]["holdings"] == ["AAA", "BBB"]
    assert result["equityCurve"][-1]["openPositions"] == 2
