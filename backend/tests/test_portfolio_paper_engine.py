from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from portfolio_strategies.ledger import PortfolioLedger, connect
from portfolio_strategies.market_data import PortfolioMarketData
from portfolio_strategies.models import (
    CalculationState,
    StrategyCalculation,
    StrategyObservation,
    TargetWeight,
)
from portfolio_strategies.paper_engine import PortfolioPaperEngine
from portfolio_strategies.registry import get_strategy


@pytest.fixture
def ledger(tmp_path: Path) -> PortfolioLedger:
    return PortfolioLedger(tmp_path / "portfolio_paper.sqlite")


def _calculation(
    config,
    *,
    signal_date: date,
    market_data_date: date,
    weights: dict[str, float],
) -> StrategyCalculation:
    return StrategyCalculation(
        strategy_id=config.strategy_id,
        strategy_version=config.version,
        state=CalculationState.READY,
        market_data_date=market_data_date,
        signal_date=signal_date,
        observation=StrategyObservation(
            as_of_date=market_data_date,
            state="READY",
            reason="formal check",
        ),
        target_weights=tuple(
            TargetWeight(
                symbol,
                weight,
                "cash" if symbol == "CASH" else config.asset(symbol).sleeve,
                "test target",
            )
            for symbol, weight in weights.items()
        ),
    )


def _market(config, rows: dict[date, dict[str, float]]) -> PortfolioMarketData:
    index = pd.to_datetime(list(rows))
    close = pd.DataFrame(
        [
            {
                symbol: values.get(symbol, 100.0)
                for symbol in config.symbols
            }
            for values in rows.values()
        ],
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


def _rows(ledger: PortfolioLedger, sql: str, params=()):
    with connect(ledger.db_path) as conn:
        return conn.execute(sql, params).fetchall()


def _bootstrap(
    engine: PortfolioPaperEngine,
    config,
    *,
    valuation_date=date(2026, 6, 25),
    weights=None,
    prices=None,
):
    weights = weights or {"510300.SS": 0.4, "CASH": 0.6}
    prices = prices or {"510300.SS": 4.0}
    calculation = _calculation(
        config,
        signal_date=date(2026, 6, 10),
        market_data_date=valuation_date,
        weights=weights,
    )
    market = _market(config, {valuation_date: prices})
    return engine.bootstrap(config, calculation, market, valuation_date)


def test_bootstrap_creates_latest_positions_and_nav_without_historical_trades(
    ledger,
):
    config = get_strategy("theme_alpha")
    engine = PortfolioPaperEngine(ledger)

    result = _bootstrap(engine, config)

    account = _rows(ledger, "SELECT * FROM paper_accounts")[0]
    signals = _rows(ledger, "SELECT * FROM signal_snapshots")
    positions = _rows(ledger, "SELECT * FROM position_snapshots")
    nav = _rows(ledger, "SELECT * FROM nav_snapshots")
    assert result["status"] == "BOOTSTRAPPED"
    assert account["bootstrap_signal_date"] == "2026-06-10"
    assert account["bootstrap_valuation_date"] == "2026-06-25"
    assert signals[0]["origin"] == "bootstrap"
    assert {row["valuation_date"] for row in positions} == {"2026-06-25"}
    assert positions[0]["quantity"] == pytest.approx(10_000.0)
    assert len(nav) == 1
    assert nav[0]["net_nav"] == pytest.approx(100_000.0)
    assert ledger.count_rows("paper_trades") == 0
    assert ledger.count_rows("rebalance_events") == 0


def test_pending_signal_executes_once_at_next_complete_close_with_costs(ledger):
    config = get_strategy("btc_supertrend_satellite")
    engine = PortfolioPaperEngine(ledger)
    _bootstrap(
        engine,
        config,
        weights={"510300.SS": 0.5, "513100.SS": 0.3, "518880.SS": 0.2},
        prices={"510300.SS": 5.0, "513100.SS": 3.0, "518880.SS": 4.0},
    )
    signal = _calculation(
        config,
        signal_date=date(2026, 6, 25),
        market_data_date=date(2026, 6, 25),
        weights={
            "510300.SS": 0.45,
            "513100.SS": 0.30,
            "518880.SS": 0.175,
            "BTC-USD": 0.075,
            "CASH": 0.0,
        },
    )

    pending = engine.queue_signal(config, signal)
    unchanged = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 25): {
                    "510300.SS": 5.0,
                    "513100.SS": 3.0,
                    "518880.SS": 4.0,
                    "BTC-USD": 60_000.0,
                }
            },
        ),
    )
    executed = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 25): {
                    "510300.SS": 5.0,
                    "513100.SS": 3.0,
                    "518880.SS": 4.0,
                    "BTC-USD": 60_000.0,
                },
                date(2026, 6, 26): {
                    "510300.SS": 5.2,
                    "513100.SS": 3.1,
                    "518880.SS": 4.1,
                    "BTC-USD": 61_000.0,
                },
            },
        ),
    )
    repeated = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 26): {
                    "510300.SS": 5.2,
                    "513100.SS": 3.1,
                    "518880.SS": 4.1,
                    "BTC-USD": 61_000.0,
                }
            },
        ),
    )

    trades = _rows(ledger, "SELECT * FROM paper_trades ORDER BY symbol")
    btc_trade = next(row for row in trades if row["symbol"] == "BTC-USD")
    assert pending["status"] == "pending"
    assert unchanged["status"] == "pending"
    assert executed["status"] == "executed"
    assert executed["execution_date"] == "2026-06-26"
    assert repeated["status"] == "idle"
    assert btc_trade["price"] == pytest.approx(61_000.0)
    assert btc_trade["quantity_delta"] > 0
    assert btc_trade["fees"] / btc_trade["gross_notional"] == pytest.approx(
        0.002
    )
    assert btc_trade["slippage"] / btc_trade["gross_notional"] == pytest.approx(
        0.001
    )
    assert ledger.count_rows("rebalance_events") == 1
    assert ledger.count_rows("nav_snapshots") == 2


def test_btc_threshold_skips_small_change_but_switch_is_always_recorded(ledger):
    config = get_strategy("btc_supertrend_satellite")
    engine = PortfolioPaperEngine(ledger)
    initial = {
        "510300.SS": 0.50,
        "513100.SS": 0.30,
        "518880.SS": 0.20,
        "BTC-USD": 0.0,
        "CASH": 0.0,
    }
    _bootstrap(
        engine,
        config,
        weights=initial,
        prices={symbol: 100.0 for symbol in config.symbols},
    )

    small = _calculation(
        config,
        signal_date=date(2026, 6, 25),
        market_data_date=date(2026, 6, 25),
        weights={
            "510300.SS": 0.505,
            "513100.SS": 0.295,
            "518880.SS": 0.20,
            "BTC-USD": 0.0,
            "CASH": 0.0,
        },
    )
    engine.queue_signal(config, small)
    skipped = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 25): {},
                date(2026, 6, 26): {},
            },
        ),
    )

    switch_config = replace(
        config,
        params={**config.params, "rebalance_threshold": 0.10},
    )
    switched = _calculation(
        switch_config,
        signal_date=date(2026, 6, 30),
        market_data_date=date(2026, 6, 30),
        weights={
            "510300.SS": 0.4625,
            "513100.SS": 0.2775,
            "518880.SS": 0.185,
            "BTC-USD": 0.075,
            "CASH": 0.0,
        },
    )
    engine.queue_signal(switch_config, switched)
    executed = engine.reconcile(
        switch_config,
        _market(
            switch_config,
            {
                date(2026, 6, 30): {},
                date(2026, 7, 1): {"BTC-USD": 60_000.0},
            },
        ),
    )

    assert skipped["status"] == "skipped"
    assert executed["status"] == "executed"
    assert any(
        row["symbol"] == "BTC-USD"
        for row in _rows(ledger, "SELECT * FROM paper_trades")
    )


def test_theme_threshold_and_per_asset_trade_cap_are_applied(ledger):
    config = get_strategy("theme_alpha")
    engine = PortfolioPaperEngine(ledger)
    _bootstrap(
        engine,
        config,
        weights={"510300.SS": 0.4, "CASH": 0.6},
        prices={"510300.SS": 4.0},
    )
    small = _calculation(
        config,
        signal_date=date(2026, 6, 25),
        market_data_date=date(2026, 6, 25),
        weights={"510300.SS": 0.41, "CASH": 0.59},
    )
    engine.queue_signal(config, small)
    skipped = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 25): {"510300.SS": 4.0},
                date(2026, 6, 26): {"510300.SS": 4.0},
            },
        ),
    )
    large = _calculation(
        config,
        signal_date=date(2026, 7, 10),
        market_data_date=date(2026, 7, 10),
        weights={"510300.SS": 0.70, "CASH": 0.30},
    )
    engine.queue_signal(config, large)
    executed = engine.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 7, 10): {"510300.SS": 4.0},
                date(2026, 7, 13): {"510300.SS": 4.0},
            },
        ),
    )

    trade = _rows(
        ledger,
        """
        SELECT paper_trades.* FROM paper_trades
        JOIN rebalance_events
          ON rebalance_events.id = paper_trades.rebalance_event_id
        WHERE rebalance_events.signal_id = ?
        """,
        (executed["signal_id"],),
    )[0]
    assert skipped["status"] == "skipped"
    assert executed["status"] == "executed"
    assert trade["weight_delta"] == pytest.approx(0.15)
    assert trade["fees"] / trade["gross_notional"] == pytest.approx(0.0025)


def test_valuation_updates_return_and_drawdown_from_bootstrap_only(ledger):
    config = get_strategy("theme_alpha")
    engine = PortfolioPaperEngine(ledger)
    _bootstrap(
        engine,
        config,
        weights={"510300.SS": 0.5, "CASH": 0.5},
        prices={"510300.SS": 100.0},
    )

    valued = engine.value(
        config,
        _market(
            config,
            {date(2026, 6, 26): {"510300.SS": 80.0}},
        ),
        date(2026, 6, 26),
    )

    assert valued["net_nav"] == pytest.approx(90_000.0)
    assert valued["daily_return"] == pytest.approx(-0.10)
    assert valued["cumulative_return"] == pytest.approx(-0.10)
    assert valued["drawdown"] == pytest.approx(-0.10)
    assert ledger.count_rows("nav_snapshots") == 2


def test_restart_resumes_pending_execution(ledger):
    config = get_strategy("theme_alpha")
    first_engine = PortfolioPaperEngine(ledger)
    _bootstrap(first_engine, config)
    signal = _calculation(
        config,
        signal_date=date(2026, 6, 25),
        market_data_date=date(2026, 6, 25),
        weights={"510300.SS": 0.55, "CASH": 0.45},
    )
    first_engine.queue_signal(config, signal)

    reopened = PortfolioPaperEngine(PortfolioLedger(ledger.db_path))
    result = reopened.reconcile(
        config,
        _market(
            config,
            {
                date(2026, 6, 25): {"510300.SS": 4.0},
                date(2026, 6, 26): {"510300.SS": 4.0},
            },
        ),
    )

    assert result["status"] == "executed"
    assert ledger.count_rows("paper_trades") == 1
