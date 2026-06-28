from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from portfolio_strategies.ledger import PortfolioLedger, connect
from portfolio_strategies.registry import ComparisonStrategyError, get_strategy


@pytest.fixture
def ledger(tmp_path: Path) -> PortfolioLedger:
    return PortfolioLedger(tmp_path / "portfolio_paper.sqlite")


def _account(ledger: PortfolioLedger):
    return ledger.get_or_create_account(get_strategy("theme_alpha"))


def _signal(
    ledger: PortfolioLedger,
    account_id: int,
    *,
    signal_date: date = date(2026, 6, 25),
    conn=None,
):
    return ledger.get_or_create_signal(
        account_id,
        get_strategy("theme_alpha"),
        signal_date=signal_date,
        market_data_date=date(2026, 6, 26),
        origin="live",
        state="READY",
        reason="formal check",
        config_hash="config-v1",
        input_hash="input-v1",
        weights={
            "510300.SS": (0.4, "core", "risk parity"),
            "CASH": (0.6, "cash", "defense"),
        },
        conn=conn,
    )


def test_database_connection_enables_required_sqlite_safety(tmp_path: Path):
    path = tmp_path / "portfolio_paper.sqlite"
    PortfolioLedger(path)

    with connect(path) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_creating_same_account_twice_returns_one_account(ledger):
    config = get_strategy("theme_alpha")

    first = ledger.get_or_create_account(config)
    second = ledger.get_or_create_account(config)

    assert first["id"] == second["id"]
    assert ledger.count_rows("paper_accounts") == 1


def test_comparison_strategy_cannot_create_paper_account(ledger):
    with pytest.raises(ComparisonStrategyError):
        ledger.get_or_create_account(
            get_strategy("btc_supertrend_satellite_5")
        )


def test_duplicate_signal_and_weights_are_idempotent(ledger):
    account = _account(ledger)

    first = _signal(ledger, account["id"])
    second = _signal(ledger, account["id"])

    assert first["id"] == second["id"]
    assert ledger.count_rows("signal_snapshots") == 1
    assert ledger.count_rows("signal_weights") == 2


def test_duplicate_rebalance_and_trade_are_idempotent(ledger):
    account = _account(ledger)
    signal = _signal(ledger, account["id"])

    first_event = ledger.get_or_create_rebalance(
        account["id"],
        signal["id"],
        status="pending",
        reason="next close",
    )
    second_event = ledger.get_or_create_rebalance(
        account["id"],
        signal["id"],
        status="pending",
        reason="next close",
    )
    first_trade = ledger.get_or_create_trade(
        first_event["id"],
        symbol="510300.SS",
        side="BUY",
        price=4.2,
        weight_delta=0.4,
        gross_notional=40_000.0,
        fees=100.0,
        slippage=0.0,
    )
    second_trade = ledger.get_or_create_trade(
        first_event["id"],
        symbol="510300.SS",
        side="BUY",
        price=4.2,
        weight_delta=0.4,
        gross_notional=40_000.0,
        fees=100.0,
        slippage=0.0,
    )

    assert first_event["id"] == second_event["id"]
    assert first_trade["id"] == second_trade["id"]
    assert ledger.count_rows("rebalance_events") == 1
    assert ledger.count_rows("paper_trades") == 1


def test_position_and_nav_snapshots_are_unique_per_account_and_date(ledger):
    account = _account(ledger)

    ledger.save_position(
        account["id"],
        valuation_date=date(2026, 6, 26),
        symbol="510300.SS",
        quantity=10_000.0,
        price=4.0,
        value=40_000.0,
        weight=0.4,
    )
    ledger.save_position(
        account["id"],
        valuation_date=date(2026, 6, 26),
        symbol="510300.SS",
        quantity=10_000.0,
        price=4.0,
        value=40_000.0,
        weight=0.4,
    )
    ledger.save_nav(
        account["id"],
        valuation_date=date(2026, 6, 26),
        gross_nav=100_000.0,
        net_nav=100_000.0,
        cash=60_000.0,
        daily_return=0.0,
        cumulative_return=0.0,
        drawdown=0.0,
        running_max=100_000.0,
    )
    ledger.save_nav(
        account["id"],
        valuation_date=date(2026, 6, 26),
        gross_nav=100_000.0,
        net_nav=100_000.0,
        cash=60_000.0,
        daily_return=0.0,
        cumulative_return=0.0,
        drawdown=0.0,
        running_max=100_000.0,
    )

    assert ledger.count_rows("position_snapshots") == 1
    assert ledger.count_rows("nav_snapshots") == 1


def test_transaction_rolls_back_signal_rebalance_and_trade_together(ledger):
    account = _account(ledger)

    with pytest.raises(RuntimeError):
        with ledger.transaction() as conn:
            signal = _signal(ledger, account["id"], conn=conn)
            event = ledger.get_or_create_rebalance(
                account["id"],
                signal["id"],
                status="executed",
                reason="next close",
                conn=conn,
            )
            ledger.get_or_create_trade(
                event["id"],
                symbol="510300.SS",
                side="BUY",
                price=4.2,
                weight_delta=0.4,
                gross_notional=40_000.0,
                fees=100.0,
                slippage=0.0,
                conn=conn,
            )
            raise RuntimeError("force rollback")

    assert ledger.count_rows("signal_snapshots") == 0
    assert ledger.count_rows("rebalance_events") == 0
    assert ledger.count_rows("paper_trades") == 0


def test_two_repository_instances_create_one_signal(tmp_path: Path):
    path = tmp_path / "portfolio_paper.sqlite"
    first = PortfolioLedger(path)
    second = PortfolioLedger(path)
    account = first.get_or_create_account(get_strategy("theme_alpha"))

    def insert(repository):
        return _signal(repository, account["id"])["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(insert, (first, second)))

    assert ids[0] == ids[1]
    assert first.count_rows("signal_snapshots") == 1
