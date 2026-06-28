from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_strategies.btc_satellite import (
    build_btc_target_weights,
    calculate_btc_satellite,
)
from portfolio_strategies.market_data import PortfolioMarketData
from portfolio_strategies.models import CalculationState, StrategyMode
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.schedules import xshg_sessions


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "portfolio_strategies"


def _price_path(
    length: int,
    *,
    drift: float,
    variation: float,
    phase: float = 0.0,
) -> np.ndarray:
    steps = np.arange(length)
    log_returns = drift + variation * np.sin(steps * 0.37 + phase)
    return 100.0 * np.exp(np.cumsum(log_returns))


def _btc_market() -> PortfolioMarketData:
    index = xshg_sessions(date(2025, 7, 1), date(2026, 6, 26))
    close = pd.DataFrame(
        {
            "510300.SS": _price_path(
                len(index), drift=0.0007, variation=0.0030
            ),
            "513100.SS": _price_path(
                len(index), drift=0.0009, variation=0.0050, phase=0.4
            ),
            "518880.SS": _price_path(
                len(index), drift=0.0005, variation=0.0020, phase=0.8
            ),
            "BTC-USD": _price_path(
                len(index), drift=0.0030, variation=0.0120, phase=1.2
            ),
        },
        index=index,
    )
    high = close.copy()
    low = close.copy()
    high["BTC-USD"] *= 1.015
    low["BTC-USD"] *= 0.985
    return PortfolioMarketData(
        open=close.copy(),
        high=high,
        low=low,
        close=close,
        sessions=index,
        market_data_date=index[-1].date(),
        diagnostics=(),
    )


def _weights(calculation):
    return {item.symbol: item.weight for item in calculation.target_weights}


def test_btc_fixture_keeps_only_latest_decision_parameters_and_provenance():
    snapshot = json.loads(
        (FIXTURE_DIR / "btc_snapshot_2026-06-26.json").read_text()
    )
    config = get_strategy("btc_supertrend_satellite")

    assert snapshot["sourceRepository"] == "xquant"
    assert snapshot["sourceCommit"] == "1d1b36e0fd22239767d3e2293f750ce7a01ffb61"
    assert snapshot["parameters"]["btcCap"] == config.params["btc_cap"]
    assert snapshot["parameters"]["riskParityWindow"] == (
        config.params["risk_parity_window"]
    )
    assert snapshot["frozenReferenceSignalDate"] == (
        config.params["schedule_reference_date"]
    )
    assert not (FIXTURE_DIR / "xquant_market_payload.txt").exists()
    assert not (FIXTURE_DIR / "market_data").exists()


def test_btc_latest_observation_preserves_the_last_formal_target():
    market = _btc_market()

    latest = calculate_btc_satellite(
        get_strategy("btc_supertrend_satellite"),
        market,
        date(2026, 6, 26),
    )
    formal = calculate_btc_satellite(
        get_strategy("btc_supertrend_satellite"),
        market,
        date(2026, 6, 15),
    )

    assert latest.state is CalculationState.NOT_DUE
    assert latest.signal_date == date(2026, 6, 15)
    assert latest.observation.as_of_date == date(2026, 6, 26)
    assert latest.observation.values["btc_close"] == pytest.approx(
        market.close.at[pd.Timestamp("2026-06-26"), "BTC-USD"]
    )
    assert np.isfinite(latest.observation.values["supertrend_line"])
    assert _weights(latest) == pytest.approx(_weights(formal))


def test_btc_formal_signal_is_ready_on_scheduled_date():
    result = calculate_btc_satellite(
        get_strategy("btc_supertrend_satellite"),
        _btc_market(),
        date(2026, 6, 15),
    )

    assert result.state is CalculationState.READY
    assert result.signal_date == date(2026, 6, 15)
    assert isinstance(result.observation.values["formal_supertrend_on"], bool)


def test_btc_cap_goes_to_btc_when_on_and_cash_when_off():
    core = {"510300.SS": 0.5, "513100.SS": 0.3, "518880.SS": 0.2}

    on = build_btc_target_weights(core, cap=0.075, btc_on=True)
    off = build_btc_target_weights(core, cap=0.075, btc_on=False)

    assert on["BTC-USD"] == 0.075
    assert on["CASH"] == 0.0
    assert off["BTC-USD"] == 0.0
    assert off["CASH"] == 0.075
    assert on["510300.SS"] == pytest.approx(0.5 * 0.925)


def test_btc_latest_decision_snapshot_preserves_xquant_weight_composition():
    snapshot = json.loads(
        (FIXTURE_DIR / "btc_snapshot_2026-06-26.json").read_text()
    )
    expected = snapshot["targetWeights"]
    cap = snapshot["parameters"]["btcCap"]
    core = {
        symbol: expected[symbol] / (1.0 - cap)
        for symbol in ("510300.SS", "513100.SS", "518880.SS")
    }

    target = build_btc_target_weights(
        core,
        cap=cap,
        btc_on=snapshot["formalSignal"]["btcSupertrendOn"],
    )

    assert target == pytest.approx(expected, abs=1e-10)


@pytest.mark.parametrize(
    ("strategy_id", "cap"),
    [
        ("btc_supertrend_satellite_5", 0.05),
        ("btc_supertrend_satellite_10", 0.10),
    ],
)
def test_btc_comparison_variants_calculate_without_becoming_paper_accounts(
    strategy_id,
    cap,
):
    config = get_strategy(strategy_id)

    result = calculate_btc_satellite(
        config,
        _btc_market(),
        date(2026, 6, 26),
    )

    assert config.mode is StrategyMode.COMPARISON
    assert result.strategy_id == strategy_id
    assert _weights(result)["BTC-USD"] == pytest.approx(cap)
    assert sum(_weights(result).values()) == pytest.approx(1.0)
