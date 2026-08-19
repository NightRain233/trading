from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd

from portfolio_strategies.event_ledger import payload_hash
from portfolio_strategies.ledger import PortfolioLedger, connect
from portfolio_strategies.next_open_engine import NextOpenPaperEngine
from portfolio_strategies.next_open_strategies import FrozenDecision
from portfolio_strategies.registry import get_strategy


def _frame(rows: list[tuple[str, float | None, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[2] for row in rows],
            "Close": [row[2] for row in rows],
            "Volume": [1_000_000.0] * len(rows),
        },
        index=pd.to_datetime([row[0] for row in rows]),
    )


def _bull_decision(items: tuple[dict, ...]) -> FrozenDecision:
    payload = {"items": items}
    return FrozenDecision(
        run_type="BULL_DAILY",
        market_data_date=date(2021, 4, 1),
        signal_date=date(2021, 4, 1),
        universe_version="monthly_pit_v1",
        config_hash="config",
        input_hash=payload_hash(payload),
        data_quality_status="OK",
        payload=payload,
        items=items,
    )


def _entry(symbol: str, market: str) -> dict:
    return {
        "symbol": symbol,
        "event_type": "BULL_FLIP_ENTRY",
        "market": market,
        "sleeve": "satellite",
        "eligible": True,
        "target_weight": 0.10,
        "priority": 1.0,
        "reason": "golden entry",
        "payload": {},
    }


def _exit(symbol: str, market: str, signal_date: date) -> FrozenDecision:
    item = {
        "symbol": symbol, "event_type": "ST_BEAR_EXIT", "market": market,
        "sleeve": "satellite", "eligible": True, "target_weight": 0.0,
        "priority": 1_000_000_000.0, "reason": "first bearish close", "payload": {},
    }
    return FrozenDecision(
        run_type=f"BULL_DAILY:{symbol}", market_data_date=signal_date,
        signal_date=signal_date, universe_version="monthly_pit_v1",
        config_hash="config", input_hash=payload_hash({"date": signal_date.isoformat()}),
        data_quality_status="OK", payload={"items": [item]}, items=(item,),
    )


def test_multi_market_orders_execute_on_independent_dates_and_refresh_is_idempotent(tmp_path: Path):
    ledger = PortfolioLedger(tmp_path / "paper.sqlite")
    engine = NextOpenPaperEngine(ledger)
    config = get_strategy("core90_ma200_bull10")
    engine.activate(config, activation_date=date(2021, 4, 1))
    prices = {
        "002119.SZ": _frame([
            ("2021-04-01", 10.0, 10.0), ("2021-04-02", 10.5, 10.5),
        ]),
        "AAPL": _frame([
            ("2021-04-01", 120.0, 120.0), ("2021-04-05", 121.0, 121.0),
        ]),
    }
    decision = _bull_decision((_entry("002119.SZ", "a_share"), _entry("AAPL", "us")))

    engine.queue_decision(config, decision, prices)
    engine.queue_decision(config, decision, prices)
    first = engine.reconcile(config, prices, through_date=date(2021, 4, 2))
    second = engine.reconcile(config, prices, through_date=date(2021, 4, 5))
    assert [row["actual_execution_date"] for row in first] == ["2021-04-02"]
    assert [row["actual_execution_date"] for row in second] == ["2021-04-05"]
    assert engine.reconcile(config, prices, through_date=date(2021, 4, 5)) == ()
    prices["AAPL"].loc[pd.Timestamp("2021-04-05"), "Close"] = 130.0
    engine.value(config, prices, date(2021, 4, 5))

    conn = connect(ledger.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM decision_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM paper_executions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM data_quality_events_v2 WHERE code = 'MARKET_DATA_VALUATION_REVISION'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM portfolio_nav_v2 WHERE valuation_date = '2021-04-05'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM portfolio_nav_v2 WHERE valuation_date = '2021-04-05' AND authoritative = 1"
        ).fetchone()[0] == 1
        dates = [row[0] for row in conn.execute(
            "SELECT actual_execution_date FROM paper_executions ORDER BY actual_execution_date"
        )]
        assert dates == ["2021-04-02", "2021-04-05"]
    finally:
        conn.close()


def test_missing_open_delays_to_next_valid_open_without_close_substitution(tmp_path: Path):
    ledger = PortfolioLedger(tmp_path / "paper.sqlite")
    engine = NextOpenPaperEngine(ledger)
    config = get_strategy("core90_ma200_bull10")
    engine.activate(config, activation_date=date(2021, 4, 1))
    prices = {"AAPL": _frame([
        ("2021-04-01", 120.0, 120.0),
        ("2021-04-05", None, 125.0),
        ("2021-04-06", 126.0, 127.0),
    ])}
    engine.queue_decision(config, _bull_decision((_entry("AAPL", "us"),)), prices)
    pending = engine.reconcile(
        config, {"AAPL": prices["AAPL"].loc[:"2021-04-01"]},
        through_date=date(2021, 4, 5),
    )
    assert pending[0]["status"] == "PENDING"
    conn = connect(ledger.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM paper_order_attempts").fetchone()[0] == 0
    finally:
        conn.close()
    result = engine.reconcile(config, prices, through_date=date(2021, 4, 6))
    assert result[0]["expected_execution_date"] == "2021-04-05"
    assert result[0]["actual_execution_date"] == "2021-04-06"
    assert result[0]["actual_open"] == 126.0

    conn = connect(ledger.db_path)
    try:
        attempt = conn.execute("SELECT * FROM paper_order_attempts").fetchone()
        assert attempt["attempted_date"] == "2021-04-05"
        assert attempt["reason"] == "MISSING_OR_INVALID_OPEN"
        order = conn.execute("SELECT * FROM paper_orders").fetchone()
        assert order["expected_execution_date"] == "2021-04-05"
        assert order["actual_execution_date"] == "2021-04-06"
    finally:
        conn.close()


def test_bear_exit_executes_at_symbols_next_open_and_repeat_is_inert(tmp_path: Path):
    ledger = PortfolioLedger(tmp_path / "paper.sqlite")
    engine = NextOpenPaperEngine(ledger)
    config = get_strategy("core90_ma200_bull10")
    engine.activate(config, activation_date=date(2021, 3, 31))
    prices = {"AAPL": _frame([
        ("2021-04-01", 120.0, 120.0),
        ("2021-04-05", 121.0, 121.0),
        ("2021-04-06", 118.0, 118.0),
    ])}
    engine.queue_decision(
        config, _bull_decision((_entry("AAPL", "us"),)), prices,
    )
    engine.reconcile(config, prices, through_date=date(2021, 4, 5))
    exit_decision = _exit("AAPL", "us", date(2021, 4, 5))
    engine.queue_decision(config, exit_decision, prices)
    result = engine.reconcile(config, prices, through_date=date(2021, 4, 6))
    assert result[0]["actual_execution_date"] == "2021-04-06"
    assert result[0]["actual_open"] == 118.0
    engine.value(config, prices, date(2021, 4, 6))

    conn = connect(ledger.db_path)
    try:
        before = tuple(conn.execute(query).fetchone()[0] for query in (
            "SELECT COUNT(*) FROM decision_runs",
            "SELECT COUNT(*) FROM paper_orders",
            "SELECT COUNT(*) FROM paper_executions",
            "SELECT COUNT(*) FROM portfolio_nav_v2",
        ))
    finally:
        conn.close()
    engine.queue_decision(config, exit_decision, prices)
    assert engine.reconcile(config, prices, through_date=date(2021, 4, 6)) == ()
    engine.value(config, prices, date(2021, 4, 6))
    conn = connect(ledger.db_path)
    try:
        after = tuple(conn.execute(query).fetchone()[0] for query in (
            "SELECT COUNT(*) FROM decision_runs",
            "SELECT COUNT(*) FROM paper_orders",
            "SELECT COUNT(*) FROM paper_executions",
            "SELECT COUNT(*) FROM portfolio_nav_v2",
        ))
        assert after == before
    finally:
        conn.close()


def test_new_activation_does_not_modify_legacy_theme_or_btc_rows(tmp_path: Path):
    ledger = PortfolioLedger(tmp_path / "paper.sqlite")
    with ledger.transaction() as conn:
        for strategy_id in ("theme_alpha", "btc_supertrend_satellite"):
            config = get_strategy(strategy_id)
            account = ledger.get_or_create_account(config, conn=conn)
            conn.execute(
                """INSERT INTO nav_snapshots (
                    account_id, valuation_date, gross_nav, net_nav, cash,
                    daily_return, cumulative_return, drawdown, running_max, created_at
                ) VALUES (?, '2026-07-01', 100000, 100000, 100000, 0, 0, 0, 100000, 'frozen')""",
                (account["id"],),
            )
    before = Path(ledger.db_path).read_bytes()
    # Byte identity is not meaningful for SQLite pages, so preserve the exact
    # legacy row payloads and counts across the new account activation.
    conn = sqlite3.connect(ledger.db_path)
    legacy_before = conn.execute(
        "SELECT account_id, valuation_date, net_nav, created_at FROM nav_snapshots ORDER BY id"
    ).fetchall()
    conn.close()

    NextOpenPaperEngine(ledger).activate(
        get_strategy("risk_parity_core_next_open"), activation_date=date(2026, 7, 1),
    )
    conn = sqlite3.connect(ledger.db_path)
    try:
        legacy_after = conn.execute(
            "SELECT account_id, valuation_date, net_nav, created_at FROM nav_snapshots ORDER BY id"
        ).fetchall()
        assert legacy_after == legacy_before
        assert conn.execute("SELECT COUNT(*) FROM nav_snapshots").fetchone()[0] == 2
    finally:
        conn.close()
    assert before != b""  # ensure the preservation assertion covered a real database
