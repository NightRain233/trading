from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from portfolio_strategies.ledger import connect
from portfolio_strategies.market_data import PortfolioMarketData
from portfolio_strategies.models import CalculationState, StrategyCalculation, StrategyObservation
from portfolio_strategies.next_open_data import _completed_through
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.service import PortfolioStrategyService


def test_service_seeds_frozen_july_pit_snapshot_without_xquant_runtime(tmp_path: Path):
    service = PortfolioStrategyService(
        data_dir=Path(__file__).parents[1] / "data",
        db_path=tmp_path / "paper.sqlite",
        decision_provider=lambda _symbols: {"items": []},
        clock=lambda: datetime(2026, 7, 1, 22, 0),
    )
    service.activate(
        "risk_parity_core_next_open", activation_date=date(2026, 6, 30),
        now=datetime(2026, 7, 1, 22, 0),
    )
    service.activate(
        "core90_ma200_bull10", activation_date=date(2026, 6, 30),
        now=datetime(2026, 7, 1, 22, 0),
    )
    service.refresh(
        "risk_parity_core_next_open", now=datetime(2026, 7, 1, 22, 0),
    )
    snapshot = service.refresh(
        "core90_ma200_bull10", now=datetime(2026, 7, 1, 22, 0),
    )
    assert snapshot["state"] == "PENDING_EXECUTION"
    assert snapshot["operations"]["pendingOrderCount"] == 3
    assert snapshot["operations"]["dueOrderCount"] == 0
    assert snapshot["operations"]["grossExposure"] == 0.0
    assert snapshot["operations"]["benchmark"]["benchmarkNav"] == 100_000.0
    assert len(service.target_weights("core90_ma200_bull10")["desired"]) == 3
    assert service.rebalance_diff("core90_ma200_bull10")["rows"]
    assert service.ledger_events("core90_ma200_bull10")["events"]
    assert service.nav_series("core90_ma200_bull10")["points"]

    conn = connect(service.db_path)
    try:
        universe = conn.execute("SELECT * FROM universe_snapshots").fetchone()
        assert universe["snapshot_date"] == "2026-06-30"
        assert universe["effective_date"] == "2026-07-01"
        selected = conn.execute(
            "SELECT COUNT(*) FROM universe_memberships WHERE selected = 1"
        ).fetchone()[0]
        assert selected == 49
    finally:
        conn.close()


def test_refresh_does_not_implicitly_activate_an_account(tmp_path: Path):
    service = PortfolioStrategyService(
        data_dir=Path(__file__).parents[1] / "data",
        db_path=tmp_path / "paper.sqlite",
        decision_provider=lambda _symbols: {"items": []},
        clock=lambda: datetime(2026, 7, 1, 22, 0),
    )
    assert service.refresh("risk_parity_core_next_open")["state"] == "EMPTY"
    assert service.ledger.get_account(get_strategy("risk_parity_core_next_open")) is None


def test_activation_is_cash_only_idempotent_and_rejects_date_change(tmp_path: Path):
    service = PortfolioStrategyService(
        data_dir=tmp_path / "data", db_path=tmp_path / "paper.sqlite",
        clock=lambda: datetime(2026, 8, 19, 10, 0),
    )
    first = service.activate(
        "core90_ma200_bull10", activation_date=date(2026, 8, 18),
    )
    second = service.activate(
        "core90_ma200_bull10", activation_date=date(2026, 8, 18),
    )
    assert first["nav"]["netNav"] == second["nav"]["netNav"] == 100_000.0
    conn = connect(service.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM strategy_activations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM paper_executions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM portfolio_nav_v2").fetchone()[0] == 1
    finally:
        conn.close()
    with pytest.raises(ValueError, match="already activated"):
        service.activate(
            "core90_ma200_bull10", activation_date=date(2026, 8, 17),
        )


def test_legacy_refresh_does_not_value_before_activation_date(tmp_path: Path, monkeypatch):
    service = PortfolioStrategyService(
        data_dir=tmp_path / "data", db_path=tmp_path / "paper.sqlite",
        clock=lambda: datetime(2026, 8, 20, 0, 30),
    )
    service.activate(
        "theme_alpha", activation_date=date(2026, 8, 20),
        now=datetime(2026, 8, 20, 0, 30),
    )
    market = PortfolioMarketData(
        open=pd.DataFrame(), high=pd.DataFrame(), low=pd.DataFrame(),
        close=pd.DataFrame(), sessions=pd.DatetimeIndex([]),
        market_data_date=date(2026, 8, 19), diagnostics=(),
    )
    calculation = StrategyCalculation(
        strategy_id="theme_alpha", strategy_version="1.0.0",
        state=CalculationState.NOT_DUE, market_data_date=date(2026, 8, 19),
        signal_date=date(2026, 8, 10),
        observation=StrategyObservation(
            as_of_date=date(2026, 8, 19), state="NOT_DUE", reason="test",
        ),
    )
    valued: list[date] = []
    monkeypatch.setattr(service, "_refresh_and_load", lambda _config: market)
    monkeypatch.setattr("portfolio_strategies.service._calculate", lambda *_args: calculation)
    monkeypatch.setattr(service.engine, "reconcile", lambda *_args: ())
    monkeypatch.setattr(
        service.engine, "value", lambda _config, _market, valuation_date: valued.append(valuation_date),
    )
    service.refresh("theme_alpha", now=datetime(2026, 8, 20, 0, 30))
    assert valued == []


def test_stale_core_does_not_block_fresh_us_satellite_signal(tmp_path: Path, monkeypatch):
    service = PortfolioStrategyService(
        data_dir=tmp_path, db_path=tmp_path / "paper.sqlite",
        decision_provider=lambda _symbols: {"items": [{
            "symbol": "AAPL", "decisionAsOf": "2026-07-01",
            "state": "bull_flip", "decision": {
                "setup": "breakout", "permission": "watch", "readinessScore": 1,
            },
            "dataStale": False, "dataIntegrity": {"hasRecentGap": False},
        }]},
        clock=lambda: datetime(2026, 7, 2, 22, 0),
    )
    service.activate(
        "core90_ma200_bull10", activation_date=date(2026, 6, 30),
        now=datetime(2026, 7, 2, 22, 0),
    )

    def frame(index, value):
        return pd.DataFrame({
            "Open": value, "High": value + 1, "Low": value - 1,
            "Close": value, "Volume": 1_000_000.0,
        }, index=pd.to_datetime(index))

    core_dates = pd.bdate_range("2026-05-20", "2026-07-01")
    reference_dates = pd.date_range(end="2026-07-01", periods=220)
    frames = {
        symbol: frame(core_dates, 100.0 + offset)
        for offset, symbol in enumerate(("510300.SS", "513100.SS", "518880.SS"))
    }
    frames["AAPL"] = frame(["2026-06-30", "2026-07-01"], 200.0)
    frames["SPY"] = frame(reference_dates, 100.0)
    frames["SPY"].loc[pd.Timestamp("2026-07-01"), "Close"] = 120.0
    monkeypatch.setattr(service, "_next_open_frames", lambda *_args, **_kwargs: (frames, {}))
    monkeypatch.setattr(service, "_ensure_current_universe", lambda *_args: None)
    monkeypatch.setattr(service, "_active_membership", lambda _date: {
        "AAPL": {"effectiveDate": "2026-07-01", "liquidityRank": 1},
    })

    snapshot = service.refresh(
        "core90_ma200_bull10", now=datetime(2026, 7, 2, 22, 0),
    )
    assert any(
        order["symbol"] == "AAPL" and order["orderType"] == "BULL_FLIP_ENTRY"
        for order in snapshot["operations"]["orders"]
    )
    assert any(item["code"] == "MISSING_OPTIONAL_MARKET_DATA" for item in snapshot["diagnostics"])


def test_completed_bar_cutoffs_are_market_specific():
    china_evening = datetime(2026, 7, 1, 22, 0)
    assert _completed_through("510300.SS", china_evening) == date(2026, 7, 1)
    assert _completed_through("AAPL", china_evening) == date(2026, 6, 30)
    assert _completed_through("BTC-USD", china_evening) == date(2026, 6, 30)
    assert _completed_through("AAPL", datetime(2026, 7, 2, 6, 30)) == date(2026, 7, 1)
