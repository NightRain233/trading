from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pandas as pd
import pytest

from portfolio_strategies.indicators import supertrend
from portfolio_strategies.frozen_xquant import frozen_membership_snapshot, frozen_universe
from portfolio_strategies.next_open_strategies import (
    calculate_core_open_rebalance,
    calculate_bull_decision,
    calculate_risk_parity_decision,
    core_signal_due,
    market_ma_state,
)
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.signal_contracts import BULL_FLIP_SIGNAL_CONTRACT_VERSION


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


def test_frozen_bull_flip_contract_is_computed_from_ohlc_not_scan_fields(monkeypatch):
    signal_date = date(2026, 7, 1)
    symbol = "513100.SS"
    symbol_index = pd.to_datetime(["2026-06-30", "2026-07-01"])
    reference_index = pd.date_range(end=signal_date, periods=200, freq="D")
    prices = {
        symbol: pd.DataFrame({
            "Open": [100.0, 101.0], "High": [101.0, 102.0],
            "Low": [99.0, 100.0], "Close": [100.0, 101.0],
            "Volume": [1_000_000.0, 1_000_000.0],
        }, index=symbol_index),
        "SPY": pd.DataFrame({
            "Open": [100.0] * 200, "High": [101.0] * 200,
            "Low": [99.0] * 200, "Close": [100.0] * 199 + [120.0],
            "Volume": [1_000_000.0] * 200,
        }, index=reference_index),
    }

    monkeypatch.setattr(
        "portfolio_strategies.next_open_strategies.supertrend",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"direction": [False, True]}, index=symbol_index,
        ),
    )
    monkeypatch.setenv("TRADING_BUILD_SHA", "abc123")

    decision = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices,
        {symbol: {"effectiveDate": "2026-07-01", "liquidityRank": 1}},
        symbol=symbol, signal_date=signal_date,
    )

    assert len(decision.items) == 1
    assert decision.items[0]["event_type"] == "BULL_FLIP_ENTRY"
    assert decision.items[0]["eligible"] is True
    assert decision.payload["signalContractVersion"] == BULL_FLIP_SIGNAL_CONTRACT_VERSION
    assert decision.payload["signalCodeHash"]
    assert decision.payload["signalCodeCommitSha"] == "abc123"
    assert decision.payload["priceSnapshotHash"]
    assert decision.signal_contract_version == BULL_FLIP_SIGNAL_CONTRACT_VERSION
    assert decision.signal_code_commit_sha == "abc123"
    assert decision.signal_code_hash == decision.payload["signalCodeHash"]
    assert decision.price_snapshot_hash == decision.payload["priceSnapshotHash"]


def test_ma200_blocked_flip_is_not_bought_later_when_market_recovers(monkeypatch):
    symbol = "513100.SS"
    symbol_index = pd.to_datetime(["2026-06-30", "2026-07-01", "2026-07-02"])
    reference_index = pd.date_range(end="2026-07-02", periods=201, freq="D")
    prices = {
        symbol: pd.DataFrame({
            "Open": [100.0, 101.0, 102.0], "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0], "Close": [100.0, 101.0, 102.0],
            "Volume": [1_000_000.0] * 3,
        }, index=symbol_index),
        "SPY": pd.DataFrame({
            "Open": [100.0] * 201, "High": [101.0] * 201,
            "Low": [99.0] * 201,
            "Close": [100.0] * 199 + [90.0, 120.0],
            "Volume": [1_000_000.0] * 201,
        }, index=reference_index),
    }

    monkeypatch.setattr(
        "portfolio_strategies.next_open_strategies.supertrend",
        lambda high, *_args, **_kwargs: pd.DataFrame(
            {"direction": [False, True] + ([True] if len(high) == 3 else [])},
            index=high.index,
        ),
    )
    membership = {symbol: {"effectiveDate": "2026-07-01", "liquidityRank": 1}}

    blocked = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices, membership,
        symbol=symbol, signal_date=date(2026, 7, 1),
    )
    recovered = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices, membership,
        symbol=symbol, signal_date=date(2026, 7, 2),
    )

    assert blocked.items[0]["event_type"] == "BULL_FLIP_ENTRY"
    assert blocked.items[0]["eligible"] is False
    assert blocked.items[0]["reason"] == "market_at_or_below_ma"
    assert recovered.items == ()


def test_foreign_proxy_signal_is_blocked_without_cny_fx_conversion(monkeypatch):
    signal_date = date(2026, 7, 1)
    symbol_index = pd.to_datetime(["2026-06-30", "2026-07-01"])
    reference_index = pd.date_range(end=signal_date, periods=200, freq="B")
    prices = {
        "AAPL": pd.DataFrame({
            "Open": [100.0, 101.0], "High": [101.0, 102.0],
            "Low": [99.0, 100.0], "Close": [100.0, 101.0],
            "Volume": [1_000_000.0] * 2,
        }, index=symbol_index),
        "SPY": pd.DataFrame({
            "Open": [100.0] * 200, "High": [101.0] * 200,
            "Low": [99.0] * 200, "Close": [100.0] * 199 + [120.0],
            "Volume": [1_000_000.0] * 200,
        }, index=reference_index),
    }
    monkeypatch.setattr(
        "portfolio_strategies.next_open_strategies.supertrend",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"direction": [False, True]}, index=symbol_index,
        ),
    )

    decision = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices,
        {"AAPL": {"effectiveDate": "2026-07-01", "liquidityRank": 1}},
        symbol="AAPL", signal_date=signal_date,
    )

    assert decision.items[0]["eligible"] is False
    assert decision.items[0]["reason"] == "fx_data_required"
    assert decision.items[0]["payload"]["quoteCurrency"] == "USD"
    assert decision.items[0]["payload"]["baseCurrency"] == "CNY"
    assert decision.items[0]["payload"]["fxPair"] == "USDCNY=X"
    assert decision.data_quality_status == "FX_DATA_BLOCKED"


def test_stale_ma_reference_does_not_emit_a_block_without_an_entry_signal(monkeypatch):
    signal_date = date(2026, 7, 1)
    symbol_index = pd.to_datetime(["2026-06-30", "2026-07-01"])
    reference_index = pd.bdate_range(end="2026-06-29", periods=200)
    prices = {
        "513100.SS": pd.DataFrame({
            "Open": [100.0, 101.0], "High": [101.0, 102.0],
            "Low": [99.0, 100.0], "Close": [100.0, 101.0],
            "Volume": [1_000_000.0] * 2,
        }, index=symbol_index),
        "SPY": pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": 100.0, "Volume": 1_000_000.0,
        }, index=reference_index),
    }
    monkeypatch.setattr(
        "portfolio_strategies.next_open_strategies.supertrend",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"direction": [True, True]}, index=symbol_index,
        ),
    )

    decision = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices, {},
        symbol="513100.SS", signal_date=signal_date,
    )

    assert decision.items == ()
    assert decision.data_quality_status == "OK"


def test_stale_ma_reference_takes_precedence_over_missing_fx(monkeypatch):
    signal_date = date(2026, 7, 1)
    symbol_index = pd.to_datetime(["2026-06-30", "2026-07-01"])
    reference_index = pd.bdate_range(end="2026-06-29", periods=200)
    prices = {
        "AAPL": pd.DataFrame({
            "Open": [100.0, 101.0], "High": [101.0, 102.0],
            "Low": [99.0, 100.0], "Close": [100.0, 101.0],
            "Volume": [1_000_000.0] * 2,
        }, index=symbol_index),
        "SPY": pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": 100.0, "Volume": 1_000_000.0,
        }, index=reference_index),
    }
    monkeypatch.setattr(
        "portfolio_strategies.next_open_strategies.supertrend",
        lambda *_args, **_kwargs: pd.DataFrame(
            {"direction": [False, True]}, index=symbol_index,
        ),
    )

    decision = calculate_bull_decision(
        get_strategy("core90_ma200_bull10"), prices,
        {"AAPL": {"effectiveDate": "2026-07-01", "liquidityRank": 1}},
        symbol="AAPL", signal_date=signal_date,
    )

    assert decision.items[0]["reason"] == "ma200_data_blocked"
    assert decision.data_quality_status == "MA200_DATA_BLOCKED"


def test_primary_strategy_uses_a_new_versioned_signal_contract():
    config = get_strategy("core90_ma200_bull10")

    assert config.version == "2.0.0"
    assert config.params["signal_contract_version"] == BULL_FLIP_SIGNAL_CONTRACT_VERSION
    assert "policy_version" not in config.params


def test_frozen_monthly_pit_membership_matches_xquant_latest_snapshot():
    snapshot = frozen_membership_snapshot(date(2026, 7, 1))
    assert snapshot is not None
    assert snapshot["snapshotDate"] == "2026-06-30"
    assert len(snapshot["selectedSymbols"]) == 49
    assert "AAPL" in snapshot["selectedSymbols"]
    assert "513100.SS" not in snapshot["selectedSymbols"]
    assert frozen_universe().universe_scope == "limited_observable_universe"


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
