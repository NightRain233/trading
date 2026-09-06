"""Offline FrozenDecision replay using the production paper execution/NAV kernel.

This adapter does not generate or reinterpret signals. Callers supply frozen
inputs. Its SQLite ledger must be a NEW file, never a live paper account.
"""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
import sqlite3
import pandas as pd
from .frozen_xquant import normalize_daily
from .ledger import PortfolioLedger
from .models import StrategyConfig
from .next_open_engine import NextOpenPaperEngine
from .next_open_strategies import FrozenDecision

EXPORT_TABLES = {
    'decisions': 'decision_runs', 'decision_items': 'decision_items',
    'orders': 'paper_orders', 'attempts': 'paper_order_attempts',
    'fills': 'paper_executions', 'positions': 'portfolio_positions_v2',
    'daily_nav': 'portfolio_nav_v2',
}


def replay_frozen_decisions(
    config: StrategyConfig, decisions: Sequence[FrozenDecision],
    prices: Mapping[str, pd.DataFrame], *, activation_date: date,
    through_date: date, db_path: Path,
) -> dict[str, pd.DataFrame]:
    """Advance each day's opens, freeze its decisions, then mark its close.

    History is truncated every day even for a batch research run. Today's full
    candle can value holdings but cannot gate today's opening order. Opening
    status must be known at the open, not inferred from today's H/L/C/Volume.
    """
    if db_path.exists():
        raise ValueError('Research replay requires a new ledger path')
    if through_date < activation_date:
        raise ValueError('Replay end precedes activation')
    by_date = defaultdict(list)
    for decision in decisions:
        if not activation_date <= decision.signal_date <= through_date:
            raise ValueError('Frozen decision outside replay window')
        if decision.market_data_date > decision.signal_date:
            raise ValueError('Frozen decision includes future market data')
        by_date[decision.signal_date].append(decision)
    frames = {symbol: normalize_daily(frame) for symbol, frame in prices.items()}
    calendar = sorted({activation_date, through_date, *by_date} | {
        timestamp.date() for frame in frames.values() for timestamp in frame.index
        if activation_date <= timestamp.date() <= through_date
    })
    ledger = PortfolioLedger(db_path)
    engine = NextOpenPaperEngine(ledger)
    engine.activate(config, activation_date=activation_date)
    for session in calendar:
        visible = {}
        for symbol, frame in frames.items():
            window = frame.loc[:pd.Timestamp(session)]
            if not window.empty:
                visible[symbol] = window
        engine.reconcile(config, visible, through_date=session)
        for decision in by_date.get(session, ()):
            engine.queue_decision(config, decision, visible)
        engine.value(config, visible, session)
    with sqlite3.connect(db_path) as conn:
        return {name: pd.read_sql_query(f'SELECT * FROM {table} ORDER BY id', conn)
                for name,table in EXPORT_TABLES.items()}
