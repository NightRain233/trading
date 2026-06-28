import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_strategies.indicators import (
    InsufficientDataError,
    inverse_volatility_weights,
    select_low_vol_trend,
    supertrend,
    true_range,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_strategies"
    / "xquant_indicator_cases.json"
)


def test_true_range_includes_overnight_gaps():
    high = pd.Series([10.0, 12.0, 11.0])
    low = pd.Series([8.0, 9.0, 7.0])
    close = pd.Series([9.0, 10.0, 8.0])

    assert true_range(high, low, close).tolist() == [2.0, 3.0, 4.0]


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["cases"])
def test_supertrend_direction_matches_xquant_fixture(case):
    result = supertrend(
        pd.Series(case["high"], dtype=float),
        pd.Series(case["low"], dtype=float),
        pd.Series(case["close"], dtype=float),
        atr_window=case["atrWindow"],
        multiplier=case["multiplier"],
    )

    assert result["direction"].tolist() == case["direction"]


def test_inverse_volatility_weights_sum_to_one_and_favor_lower_volatility():
    returns = pd.DataFrame(
        {
            "A": [0.01, -0.01, 0.01, -0.01],
            "B": [0.02, -0.02, 0.02, -0.02],
        }
    )

    weights = inverse_volatility_weights(returns, ["A", "B"], window=4)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights == pytest.approx({"A": 2 / 3, "B": 1 / 3})


def test_inverse_volatility_cap_redistributes_excess():
    returns = pd.DataFrame(
        {
            "A": [0.005, -0.005, 0.005, -0.005],
            "B": [0.01, -0.01, 0.01, -0.01],
            "C": [0.02, -0.02, 0.02, -0.02],
        }
    )

    weights = inverse_volatility_weights(
        returns,
        ["A", "B", "C"],
        window=4,
        cap=0.50,
    )

    assert weights == pytest.approx({"A": 0.50, "B": 1 / 3, "C": 1 / 6})
    assert max(weights.values()) <= 0.50


def test_inverse_volatility_rejects_all_zero_volatility():
    returns = pd.DataFrame({"A": [0.0] * 4, "B": [0.0] * 4})

    with pytest.raises(InsufficientDataError):
        inverse_volatility_weights(returns, ["A", "B"], window=4)


def test_low_vol_trend_filters_trend_and_selects_lowest_volatility():
    index = pd.date_range("2026-01-01", periods=70)
    step = np.arange(70)
    close = pd.DataFrame(
        {
            "SMOOTH": np.linspace(100, 112, 70),
            "CHOPPY": np.linspace(100, 120, 70) + np.sin(step) * 4,
            "STEADY": np.linspace(100, 116, 70) + np.sin(step) * 0.4,
            "FALLING": np.linspace(120, 90, 70),
        },
        index=index,
    )

    selected = select_low_vol_trend(
        close,
        close.pct_change(),
        index[-1],
        close.columns,
        ma_window=60,
        momentum_window=63,
        volatility_window=60,
        top_n=2,
    )

    assert selected == ["SMOOTH", "STEADY"]


def test_low_vol_trend_breaks_equal_volatility_ties_by_symbol():
    index = pd.date_range("2026-01-01", periods=70)
    values = np.linspace(100, 120, 70)
    close = pd.DataFrame({"B": values, "A": values}, index=index)

    selected = select_low_vol_trend(
        close,
        close.pct_change(),
        index[-1],
        ["B", "A"],
        ma_window=60,
        momentum_window=63,
        volatility_window=60,
        top_n=1,
    )

    assert selected == ["A"]

