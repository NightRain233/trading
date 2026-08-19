from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from portfolio_strategies.event_ledger import payload_hash
from portfolio_strategies.ledger import PortfolioLedger, connect
from portfolio_strategies.next_open_engine import NextOpenPaperEngine
from portfolio_strategies.next_open_strategies import FrozenDecision
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.service import PortfolioStrategyService


def _frame(dates: list[str], price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [price] * len(dates), "High": [price + 1] * len(dates),
            "Low": [price - 1] * len(dates), "Close": [price] * len(dates),
            "Volume": [1_000_000.0] * len(dates),
        },
        index=pd.to_datetime(dates),
    )


def _entry_decision(symbol: str, market: str, signal_date: date) -> FrozenDecision:
    item = {
        "symbol": symbol, "event_type": "BULL_FLIP_ENTRY", "market": market,
        "sleeve": "satellite", "eligible": True, "target_weight": 0.10,
        "priority": 1.0, "reason": "seed holding", "payload": {},
    }
    return FrozenDecision(
        run_type=f"BULL_DAILY:{symbol}", market_data_date=signal_date,
        signal_date=signal_date, universe_version="monthly_pit_v1",
        config_hash="config", input_hash=payload_hash(item),
        data_quality_status="OK", payload={"items": [item]}, items=(item,),
    )


def _pending(service: PortfolioStrategyService, account_id: int):
    conn = connect(service.db_path)
    try:
        return conn.execute(
            """SELECT * FROM paper_orders WHERE account_id = ?
            AND status IN ('PENDING', 'WAITING_OPEN')""", (account_id,),
        ).fetchall()
    finally:
        conn.close()


def test_held_symbols_advance_on_own_dates_catch_up_and_do_not_duplicate(
    tmp_path: Path, monkeypatch,
):
    ledger = PortfolioLedger(tmp_path / "paper.sqlite")
    engine = NextOpenPaperEngine(ledger)
    config = get_strategy("core90_ma200_bull10")
    engine.activate(config, activation_date=date(2021, 3, 31))
    frames = {
        "002119.SZ": _frame(["2021-04-01", "2021-04-02", "2021-04-05", "2021-04-06"], 10),
        "AAPL": _frame(["2021-04-01", "2021-04-05"], 120),
    }
    engine.queue_decision(
        config, _entry_decision("002119.SZ", "a_share", date(2021, 4, 1)), frames,
    )
    engine.queue_decision(
        config, _entry_decision("AAPL", "us", date(2021, 4, 1)), frames,
    )
    engine.reconcile(config, frames, through_date=date(2021, 4, 5))

    service = PortfolioStrategyService(data_dir=tmp_path, db_path=ledger.db_path)
    account = ledger.get_account(config)
    assert account is not None
    state = engine.current_state(config)
    assert state is not None and state.held_symbols("satellite") == {"002119.SZ", "AAPL"}

    def fake_bearish(frame, **_kwargs):
        latest = frame.index[-1].date()
        return (latest,)

    monkeypatch.setattr("portfolio_strategies.service.bearish_signal_dates", fake_bearish)
    service._refresh_bull_symbols(
        config, account, state, _pending(service, account["id"]), frames, (),
        activation_date=date(2021, 3, 31),
    )

    conn = connect(ledger.db_path)
    try:
        exits = conn.execute(
            """SELECT symbol, signal_date FROM paper_orders
            WHERE order_type = 'ST_BEAR_EXIT' ORDER BY symbol"""
        ).fetchall()
        assert [(row["symbol"], row["signal_date"]) for row in exits] == [
            ("002119.SZ", "2021-04-06"), ("AAPL", "2021-04-05"),
        ]
        # The China holding catches up over two intervening completed sessions.
        china_dates = [row[0] for row in conn.execute(
            """SELECT signal_date FROM decision_runs
            WHERE run_type = 'BULL_DAILY:002119.SZ' AND signal_date > '2021-04-01'
            ORDER BY signal_date"""
        )]
        assert china_dates == ["2021-04-02", "2021-04-05", "2021-04-06"]
        before = tuple(conn.execute(
            "SELECT COUNT(*) FROM decision_runs UNION ALL SELECT COUNT(*) FROM paper_orders"
        ).fetchall())
    finally:
        conn.close()

    # Existing pending exits and authoritative symbol/date decisions make retry inert.
    service._refresh_bull_symbols(
        config, account, state, _pending(service, account["id"]), frames, (),
        activation_date=date(2021, 3, 31),
    )
    conn = connect(ledger.db_path)
    try:
        after = tuple(conn.execute(
            "SELECT COUNT(*) FROM decision_runs UNION ALL SELECT COUNT(*) FROM paper_orders"
        ).fetchall())
        assert after == before
        assert conn.execute(
            "SELECT COUNT(*) FROM paper_orders WHERE order_type = 'ST_BEAR_EXIT'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_bull_flip_uses_each_symbols_own_latest_decision_as_of(
    tmp_path: Path, monkeypatch,
):
    service = PortfolioStrategyService(data_dir=tmp_path, db_path=tmp_path / "paper.sqlite")
    config = get_strategy("core90_ma200_bull10")
    service.next_open_engine.activate(config, activation_date=date(2021, 3, 31))
    account = service.ledger.get_account(config)
    assert account is not None
    state = service.next_open_engine.current_state(config)
    assert state is not None
    frames = {
        "002119.SZ": _frame(["2021-04-01", "2021-04-02"], 10),
        "AAPL": _frame(["2021-04-01"], 120),
    }
    items = (
        {"symbol": "002119.SZ", "decisionAsOf": "2021-04-02", "state": "bull_flip"},
        {"symbol": "AAPL", "decisionAsOf": "2021-04-01", "state": "bull_flip"},
    )
    calls: list[tuple[str, date, str]] = []

    def fake_calculate(_config, decision_items, _prices, _membership, *, signal_date, run_type, **_kwargs):
        symbol = str(decision_items[0]["symbol"])
        calls.append((symbol, signal_date, str(decision_items[0]["decisionAsOf"])))
        return FrozenDecision(
            run_type=run_type, market_data_date=signal_date, signal_date=signal_date,
            universe_version="monthly_pit_v1", config_hash="config",
            input_hash=payload_hash([symbol, signal_date.isoformat()]), data_quality_status="OK",
            payload={}, items=(),
        )

    monkeypatch.setattr(service, "_active_membership", lambda _date: {
        "002119.SZ": {"effectiveDate": "2021-04-01"},
        "AAPL": {"effectiveDate": "2021-04-01"},
    })
    monkeypatch.setattr("portfolio_strategies.service.calculate_bull_decision", fake_calculate)
    service._refresh_bull_symbols(
        config, account, state, (), frames, items,
        activation_date=date(2021, 3, 31),
    )
    assert calls == [
        ("002119.SZ", date(2021, 4, 2), "2021-04-02"),
        ("AAPL", date(2021, 4, 1), "2021-04-01"),
    ]

    # A foreign-market date presented for AAPL is ignored, not coerced.
    calls.clear()
    service._refresh_bull_symbols(
        config, account, state, (), frames,
        ({"symbol": "AAPL", "decisionAsOf": "2021-04-02", "state": "bull_flip"},),
        activation_date=date(2021, 3, 31),
    )
    assert calls == []
