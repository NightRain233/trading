from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pandas as pd
import pytest

from portfolio_strategies.indicators import supertrend
from portfolio_strategies.frozen_xquant import frozen_membership_snapshot
from portfolio_strategies.next_open_strategies import (
    calculate_core_open_rebalance,
    calculate_risk_parity_decision,
    core_signal_due,
    market_ma_state,
    policy_eligible_bull_flip,
)
from portfolio_strategies.registry import get_strategy


FIXTURE = Path(__file__).parent / "fixtures/portfolio_strategies/xquant_next_open_golden_v1.json"


def _golden() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _risk_frames(case: dict) -> dict[str, pd.DataFrame]:
    index = pd.to_datetime(case["dates"])
    return {
        symbol: pd.DataFrame(
            {"Close": values, "Open": values}, index=index,
        )
        for symbol, values in case["close"].items()
    }


def test_frozen_risk_parity_weights_match_xquant():
    case = _golden()["riskParity"]
    decision = calculate_risk_parity_decision(
        get_strategy("risk_parity_core_next_open"), _risk_frames(case),
        signal_date=date.fromisoformat(case["signalDate"]),
    )
    assert decision.payload["targetWeights"] == pytest.approx(case["targetWeights"], abs=1e-14)
    assert core_signal_due(
        _risk_frames(case), date.fromisoformat(case["signalDate"]),
        anchor_signal_date=date(2026, 7, 1), every=10,
    )


def test_non_rebalance_drift_and_open_gap_turnover_match_xquant():
    case = _golden()["riskParity"]
    closes = {symbol: values[-2] for symbol, values in case["close"].items()}
    quantities = {
        symbol: case["priorCloseWeights"][symbol] * 1_000_000 / closes[symbol]
        for symbol in closes
    }
    result = calculate_core_open_rebalance(
        quantities, 0.0, case["executionOpen"], case["targetWeights"], cost_bps=10,
    )
    assert {
        symbol: result.open_weights[symbol] for symbol in case["openGapWeights"]
    } == pytest.approx(case["openGapWeights"], abs=1e-10)
    assert result.turnover == pytest.approx(case["turnover"], abs=1e-10)
    assert result.open_weights != pytest.approx(case["priorCloseWeights"], abs=1e-6)


def test_supertrend_7_3_bull_flip_matches_xquant_date():
    case = _golden()["supertrend73"]
    index = pd.to_datetime(case["dates"])
    trend = supertrend(
        pd.Series(case["high"], index=index),
        pd.Series(case["low"], index=index),
        pd.Series(case["close"], index=index),
        atr_window=7, multiplier=3,
    )
    flip = trend["direction"] & ~trend["direction"].shift(1, fill_value=False)
    assert flip.index[flip][-1].date().isoformat() == case["flipDate"]


def test_policy_breakout_does_not_require_formal_permission():
    assert policy_eligible_bull_flip({
        "state": "bull_flip",
        "decision": {"setup": "breakout", "permission": "watch"},
        "dataStale": False,
        "dataIntegrity": {"hasGap": False},
    })


def test_frozen_monthly_pit_membership_matches_xquant_latest_snapshot():
    snapshot = frozen_membership_snapshot(date(2026, 7, 1))
    assert snapshot is not None
    assert snapshot["snapshotDate"] == "2026-06-30"
    assert len(snapshot["selectedSymbols"]) == 49
    assert "AAPL" in snapshot["selectedSymbols"]
    assert "513100.SS" not in snapshot["selectedSymbols"]


@pytest.mark.parametrize("case_index", [0, 1])
def test_ma200_gate_matches_xquant_reference_values(case_index: int):
    case = _golden()["ma200Cases"][case_index]
    prior = (case["ma"] * 200.0 - case["close"]) / 199.0
    index = pd.date_range(end=case["date"], periods=200, freq="D")
    frame = pd.DataFrame({"Close": [prior] * 199 + [case["close"]]}, index=index)
    result = market_ma_state(frame, date.fromisoformat(case["date"]), window=200)
    assert result["referenceClose"] == pytest.approx(case["close"])
    assert result["referenceMa"] == pytest.approx(case["ma"], abs=1e-10)
    assert result["riskOn"] is case["allowed"]
