"""Historical current-contract decisions and execution through the paper kernel.

No legacy decisions, trades or NAV are inputs. Source frames are cut off at each
session. Empty/non-action days are omitted from the decision ledger; a daily
research checkpoint records that those days were evaluated.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from dataclasses import replace
from collections.abc import Callable, Mapping
import json
import sqlite3
import pandas as pd

from .frozen_xquant import frozen_universe, normalize_daily
from .indicators import InsufficientDataError
from .event_ledger import payload_hash
from . import next_open_strategies as signal_functions
from .models import StrategyConfig
from .next_open_strategies import (
    CORE_SYMBOLS, calculate_bull_decision, calculate_risk_parity_decision,
    core_common_sessions, core_signal_due,
)
from .service import PortfolioStrategyService


def run_current_contract(
    config: StrategyConfig,
    prices: Mapping[str, pd.DataFrame], *, start: date, end: date,
    db_path: Path, progress: Callable[[dict], None] | None = None,
    include_bull: bool = True,
    core_supertrend_filter: bool = False,
    execution_delay_sessions: int = 0,
) -> None:
    """Cash activation the day before start, no pre-activation holdings/signals.

    Config is used unchanged, including current FX blocking. Only the activation
    date is historical. A precomputed causal ST series schedules candidate calls;
    every recorded decision still recomputes its inputs with production code.
    """
    if db_path.exists():
        raise ValueError('Historical replay requires a new research ledger')
    universe = frozen_universe()
    frames = {s:normalize_daily(f) for s,f in prices.items() if s in universe.symbols}
    if not set(CORE_SYMBOLS).issubset(frames):
        raise ValueError('Missing core price inputs')
    activation = (pd.Timestamp(start)-pd.Timedelta(days=1)).date()
    service = PortfolioStrategyService(data_dir=db_path.parent/'unused-price-directory', db_path=db_path)
    engine = service.next_open_engine
    engine.activate(config, activation_date=activation)
    advance_current_contract(service, config, frames, through_date=end, progress=progress,
        include_bull=include_bull, core_supertrend_filter=core_supertrend_filter,
        execution_delay_sessions=execution_delay_sessions)


def advance_current_contract(service, config, prices, *, through_date, progress=None,
                             include_bull=True, core_supertrend_filter=False,
                             execution_delay_sessions=0):
    """Shared chronological session loop, restartable via an account checkpoint."""
    universe = frozen_universe()
    frames = {s:normalize_daily(f) for s,f in prices.items() if s in universe.symbols and not f.empty}
    engine = service.next_open_engine
    account = service.ledger.get_account(config)
    activation = service.events.activation(account['id'])
    with service.ledger.transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS next_open_session_checkpoints (
            account_id INTEGER NOT NULL, session_date TEXT NOT NULL, decision_count INTEGER NOT NULL,
            PRIMARY KEY(account_id,session_date))""")
        row=conn.execute('SELECT MAX(session_date) FROM next_open_session_checkpoints WHERE account_id=?',(account['id'],)).fetchone()
        after=date.fromisoformat(row[0] or activation['activation_date'])
        last=conn.execute("SELECT MAX(signal_date) FROM decision_runs WHERE account_id=? AND authoritative=1 AND run_type='CORE_REBALANCE'",(account['id'],)).fetchone()[0]
    start=(pd.Timestamp(after)+pd.Timedelta(days=1)).date()
    end=through_date
    if start>end:
        return
    candidates = {}
    bearish = {}
    if include_bull:
        for symbol, frame in frames.items():
            numeric = frame[['High','Low','Close']].apply(pd.to_numeric, errors='coerce')
            trend = signal_functions.supertrend(numeric.High, numeric.Low, numeric.Close,
                atr_window=int(config.params['supertrend_atr_window']), multiplier=float(config.params['supertrend_multiplier']))
            directions = trend['direction']
            candidates[symbol] = set(directions.index[directions & ~directions.shift(1,fill_value=False)])
            bearish[symbol] = set(directions.index[~directions])
    core_bearish = {}
    if core_supertrend_filter:
        for symbol in CORE_SYMBOLS:
            frame = frames[symbol]
            numeric = frame[['High','Low','Close']].apply(pd.to_numeric, errors='coerce')
            trend = signal_functions.supertrend(numeric.High, numeric.Low, numeric.Close,
                atr_window=int(config.params['core_supertrend_atr_window']),
                multiplier=float(config.params['core_supertrend_multiplier']))
            core_bearish[symbol] = {value.date() for value in trend.index[~trend['direction']]}
    calendar = sorted({pd.Timestamp(start),pd.Timestamp(end)} | {
        d for f in frames.values() for d in f.index if start <= d.date() <= end
    })
    common = core_common_sessions(frames)
    common_set = set(common)
    last_core = date.fromisoformat(last) if last else None
    membership_month = None
    membership = {}
    for timestamp in calendar:
        session = timestamp.date()
        visible = {s:f.loc[:timestamp] for s,f in frames.items() if f.index.min() <= timestamp}
        engine.reconcile(config,visible,through_date=session)
        state = engine.current_state(config)
        account = service.ledger.get_account(config)
        pending = service.events.pending_orders(account['id'])
        pending_core = any(o['order_type']=='CORE_REBALANCE' for o in pending)
        count = 0
        if timestamp in common_set and not pending_core:
            has_core = bool(state.held_symbols('core'))
            due = not has_core or (last_core is not None and core_signal_due(
                visible,session,anchor_signal_date=last_core,every=int(config.params['rebalance_sessions'])))
            if due:
                try:
                    decision = calculate_risk_parity_decision(config,visible,signal_date=session)
                    if core_supertrend_filter:
                        active = [item for item in decision.items
                                  if item['symbol'] not in core_bearish or session not in core_bearish[item['symbol']]]
                        if not active:
                            decision = None
                        else:
                            total = sum(float(item['target_weight']) for item in active)
                            items = tuple({**item, 'target_weight': float(item['target_weight']) / total,
                                       'payload': {**item.get('payload', {}), 'coreSuperTrendEligible': True}}
                                     for item in active)
                            active_symbols = {item['symbol'] for item in items}
                            items += tuple({
                            'symbol': symbol, 'event_type': 'CORE_REBALANCE', 'market': 'a_share',
                            'sleeve': 'core', 'eligible': True, 'target_weight': 0.0,
                            'priority': 0.0, 'reason': 'core SuperTrend filter blocked',
                            'payload': {'targetWeight': 0.0, 'coreSuperTrendEligible': False},
                            } for symbol in CORE_SYMBOLS if symbol not in active_symbols)
                            payload = {**decision.payload, 'targetWeights': {item['symbol']: item['target_weight'] for item in items},
                                       'coreSuperTrendFilter': True}
                            decision = replace(decision, items=items, payload=payload)
                except InsufficientDataError as exc:
                    service.events.record_data_quality(
                        account_id=account['id'], strategy_id=config.strategy_id,
                        strategy_version=config.version,
                        event_key=payload_hash([config.strategy_id,config.version,"CORE_INPUT_BLOCKED",session.isoformat()]),
                        observed_at=session.isoformat(), market_data_date=session,
                        code="CORE_INPUT_BLOCKED", message=str(exc), details={},
                    )
                else:
                    if decision is not None:
                        engine.queue_decision(config,decision,visible)
                        last_core=session
                        count+=1
        if not include_bull:
            engine.value(config,visible,session)
            with service.ledger.transaction() as conn:
                conn.execute('INSERT INTO next_open_session_checkpoints VALUES (?,?,?)',(account['id'],session.isoformat(),count))
            continue
        # Same universe production service: reconstruct month-end selection from
        # the visible OHLCV. The one frozen snapshot override remains audited.
        month = (session.year,session.month)
        if membership_month != month:
            service._ensure_current_universe(visible,session)
            selected = service._active_membership(session)
            if selected and pd.Timestamp(next(iter(selected.values()))['effectiveDate']).month == session.month:
                membership_month=month
            membership=selected
        held=state.held_symbols('satellite')
        pending_symbols={o['symbol'] for o in pending if o['order_type']!='CORE_REBALANCE'}
        for symbol in sorted(frames):
            if symbol in pending_symbols or timestamp not in frames[symbol].index:
                continue
            if timestamp not in candidates[symbol] and not (symbol in held and timestamp in bearish[symbol]):
                continue
            decision=calculate_bull_decision(config,visible,membership,symbol=symbol,
                signal_date=session,held_symbols=tuple(held),run_type=f'BULL_DAILY:{symbol}')
            engine.queue_decision(config,decision,visible)
            count+=1
        engine.value(config,visible,session)
        with service.ledger.transaction() as conn:
            conn.execute('INSERT INTO next_open_session_checkpoints VALUES (?,?,?)',(account['id'],session.isoformat(),count))
        if progress and (timestamp.month==1 and timestamp.day<=3 or timestamp==calendar[-1]):
            progress({'date':session.isoformat(),'decisionCount':count})
