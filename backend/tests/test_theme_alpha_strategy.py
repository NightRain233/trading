from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_strategies.market_data import PortfolioMarketData
from portfolio_strategies.models import CalculationState
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.schedules import xshg_sessions
from portfolio_strategies.theme_alpha import (
    apply_core_defense,
    calculate_theme_alpha,
    combine_sleeve_weights,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "portfolio_strategies"


def _price_path(
    length: int,
    *,
    drift: float,
    variation: float,
    phase: float = 0.0,
) -> np.ndarray:
    steps = np.arange(length)
    log_returns = drift + variation * np.sin(steps * 0.41 + phase)
    return 100.0 * np.exp(np.cumsum(log_returns))


def _theme_market() -> PortfolioMarketData:
    index = xshg_sessions(date(2025, 7, 1), date(2026, 6, 26))
    series = {
        "510300.SS": (0.0008, 0.0020, 0.0),
        "513100.SS": (0.0010, 0.0008, 0.4),
        "518880.SS": (0.0005, 0.0040, 0.8),
        "512400.SS": (-0.0004, 0.0025, 1.2),
        "159995.SZ": (-0.0003, 0.0030, 1.6),
        "515880.SS": (0.0009, 0.0012, 2.0),
        "510880.SS": (-0.0002, 0.0015, 2.4),
        "159930.SZ": (-0.0005, 0.0035, 2.8),
        "512880.SS": (0.0007, 0.0004, 3.2),
        "513180.SS": (-0.0003, 0.0045, 3.6),
        "512170.SS": (-0.0006, 0.0020, 4.0),
    }
    close = pd.DataFrame(
        {
            symbol: _price_path(
                len(index),
                drift=drift,
                variation=variation,
                phase=phase,
            )
            for symbol, (drift, variation, phase) in series.items()
        },
        index=index,
    )
    return PortfolioMarketData(
        open=close.copy(),
        high=close.copy(),
        low=close.copy(),
        close=close,
        sessions=index,
        market_data_date=index[-1].date(),
        diagnostics=(),
    )


def _weights(items):
    return {item.symbol: item.weight for item in items}


def test_theme_fixture_keeps_only_latest_decision_parameters_and_provenance():
    snapshot = json.loads(
        (FIXTURE_DIR / "theme_alpha_snapshot_2026-06-25.json").read_text()
    )
    config = get_strategy("theme_alpha")

    assert snapshot["sourceRepository"] == "xquant"
    assert snapshot["sourceCommit"] == "1d1b36e0fd22239767d3e2293f750ce7a01ffb61"
    assert snapshot["parameters"]["coreAllocation"] == (
        config.params["core_allocation"]
    )
    assert snapshot["parameters"]["lvtAllocation"] == (
        config.params["lvt_allocation"]
    )
    assert snapshot["parameters"]["defenseMaWindow"] == (
        config.params["defense_ma_window"]
    )
    assert not (FIXTURE_DIR / "xquant_market_payload.txt").exists()
    assert not (FIXTURE_DIR / "market_data").exists()


def test_theme_alpha_uses_core80_lvt20_and_preserves_last_formal_target():
    market = _theme_market()

    latest = calculate_theme_alpha(
        get_strategy("theme_alpha"),
        market,
        date(2026, 6, 26),
    )
    formal = calculate_theme_alpha(
        get_strategy("theme_alpha"),
        market,
        date(2026, 6, 25),
    )

    assert latest.state is CalculationState.NOT_DUE
    assert latest.signal_date == date(2026, 6, 25)
    assert latest.observation.values["selected_lvt"] == (
        "512880.SS",
        "513100.SS",
        "515880.SS",
    )
    assert _weights(latest.target_weights) == pytest.approx(
        _weights(formal.target_weights)
    )
    assert sum(_weights(latest.sleeve_weights["core"]).values()) == pytest.approx(
        1.0
    )
    assert sum(_weights(latest.sleeve_weights["lvt"]).values()) == pytest.approx(
        1.0
    )
    assert sum(_weights(latest.target_weights).values()) == pytest.approx(1.0)


def test_theme_alpha_is_ready_on_shifted_bimonthly_signal_date():
    result = calculate_theme_alpha(
        get_strategy("theme_alpha"),
        _theme_market(),
        date(2026, 6, 25),
    )

    assert result.state is CalculationState.READY
    assert result.signal_date == date(2026, 6, 25)
    assert result.observation.values["core_risk_on"] == {
        "510300.SS": True,
        "513100.SS": True,
    }


def test_core_defense_moves_each_failed_equity_weight_to_cash_independently():
    core = {
        "510300.SS": 0.45,
        "513100.SS": 0.25,
        "518880.SS": 0.30,
        "CASH": 0.0,
    }

    defended = apply_core_defense(
        core,
        {"510300.SS": False, "513100.SS": True},
    )

    assert defended == pytest.approx(
        {
            "510300.SS": 0.0,
            "513100.SS": 0.25,
            "518880.SS": 0.30,
            "CASH": 0.45,
        }
    )


def test_theme_latest_decision_snapshot_preserves_xquant_sleeve_composition():
    snapshot = json.loads(
        (FIXTURE_DIR / "theme_alpha_snapshot_2026-06-25.json").read_text()
    )

    target = combine_sleeve_weights(
        snapshot["coreSleeveWeights"],
        snapshot["lvtSleeveWeights"],
        symbols=get_strategy("theme_alpha").symbols,
        core_allocation=snapshot["parameters"]["coreAllocation"],
        lvt_allocation=snapshot["parameters"]["lvtAllocation"],
    )

    assert target == pytest.approx(snapshot["targetWeights"], abs=1e-10)
