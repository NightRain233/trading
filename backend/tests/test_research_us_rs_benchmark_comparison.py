import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research_us_rs_benchmark_comparison.py"
SPEC = importlib.util.spec_from_file_location("research_us_rs_benchmark_comparison", SCRIPT_PATH)
research_us_rs_benchmark_comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research_us_rs_benchmark_comparison)


def _frame(values, start="2020-01-01"):
    return pd.DataFrame(
        {"Close": values},
        index=pd.date_range(start, periods=len(values), freq="B"),
    )


def test_build_benchmark_specs_keeps_spy_ief_and_tlt_fallback_separate():
    specs = {spec["name"]: spec for spec in research_us_rs_benchmark_comparison.build_benchmark_specs()}

    assert specs["spy_ief_60_40"]["symbols"] == ["SPY", "IEF"]
    assert specs["spy_tlt_60_40"]["symbols"] == ["SPY", "TLT"]
    assert specs["spy_ief_60_40"]["weights"] == {"SPY": 0.6, "IEF": 0.4}


def test_simulate_buy_hold_builds_curve_and_drawdown():
    result = research_us_rs_benchmark_comparison.simulate_buy_hold(
        "AAA",
        _frame([100.0, 120.0, 90.0, 130.0]),
        start="2020-01-01",
        end="2020-01-10",
        fee_bps=0.0,
        slippage_bps=0.0,
    )

    assert result["symbol"] == "AAA"
    assert result["totalReturnPct"] == pytest.approx(30.0)
    assert result["maxDrawdownPct"] == pytest.approx(25.0)


def test_equal_weight_rebalance_adds_symbols_when_they_become_available():
    frames = {
        "AAA": _frame([100.0, 110.0, 120.0, 130.0]),
        "BBB": _frame([50.0, 55.0, 60.0], start="2020-01-03"),
    }

    result = research_us_rs_benchmark_comparison.simulate_rebalanced_portfolio(
        frames,
        start="2020-01-01",
        end="2020-01-10",
        weight_provider=research_us_rs_benchmark_comparison.equal_weight_provider,
        rebalance_days=1,
        fee_bps=0.0,
        slippage_bps=0.0,
        mode="equal_weight_test",
    )

    assert result["usedSymbols"] == ["AAA", "BBB"]
    assert any(point["holdings"] == ["AAA", "BBB"] for point in result["equityCurve"])


def test_missing_required_symbols_are_reported_as_skipped(tmp_path):
    data_dir = tmp_path
    _frame([100.0, 101.0, 102.0]).to_parquet(data_dir / "SPY.parquet")

    payload = research_us_rs_benchmark_comparison.build_us_rs_benchmark_comparison(
        start="2020-01-01",
        end="2020-01-10",
        data_dir=data_dir,
    )

    assert payload["skippedBenchmarks"]["spy_ief_60_40"]["missingSymbols"] == ["IEF"]
    assert payload["skippedBenchmarks"]["spy_tlt_60_40"]["missingSymbols"] == ["TLT"]
    assert "spy_buy_hold" in payload["benchmarks"]
