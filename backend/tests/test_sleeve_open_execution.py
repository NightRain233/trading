from dataclasses import replace
from datetime import date
import sqlite3
import pandas as pd
import pytest

from portfolio_strategies.ledger import PortfolioLedger
from portfolio_strategies.next_open_engine import NextOpenPaperEngine
from portfolio_strategies.registry import get_strategy
from test_next_open_engine import _bull_decision, _entry, _frame


def run_case(tmp_path, *, suspended=False, altered_close=False):
    config=get_strategy('core90_ma200_bull10')
    engine=NextOpenPaperEngine(PortfolioLedger(tmp_path/'ledger.sqlite'))
    engine.activate(config,activation_date=date(2021,4,1))
    frames={s:_frame([('2021-04-01',10.,10.),('2021-04-02',10.,10.),
                     ('2021-04-06',20.,21.),('2021-04-07',22.,23.)])
            for s in ['510300.SS','513100.SS','518880.SS','512880.SS']}
    frames['512880.SS']['OpenSuspended']=[False,False,suspended,False]
    if altered_close:
        for frame in frames.values(): frame.loc['2021-04-06','Close']=99999.
    engine.queue_decision(config,_bull_decision((_entry('512880.SS','a_share'),)),frames)
    engine.reconcile(config,frames,through_date=date(2021,4,2))
    items=tuple({'symbol':s,'event_type':'CORE_REBALANCE','market':'a_share','sleeve':'core',
                 'eligible':True,'target_weight':0.3,'priority':0.,'reason':'frozen allocation','payload':{}}
                for s in ['510300.SS','513100.SS','518880.SS'])
    decision=replace(_bull_decision(items),run_type='CORE_REBALANCE',signal_date=date(2021,4,2),
                     market_data_date=date(2021,4,2))
    engine.queue_decision(config,decision,frames)
    engine.reconcile(config,frames,through_date=date(2021,4,6))
    with sqlite3.connect(tmp_path/'ledger.sqlite') as conn:
        at_six=conn.execute('SELECT COUNT(*) FROM paper_executions').fetchone()[0]
    engine.reconcile(config,frames,through_date=date(2021,4,7))
    assert engine.reconcile(config,frames,through_date=date(2021,4,7))==()
    engine.value(config,frames,date(2021,4,7))
    with sqlite3.connect(tmp_path/'ledger.sqlite') as conn:
        fills=pd.read_sql_query('SELECT o.sleeve,o.symbol,o.order_type,e.actual_execution_date,e.quantity_delta,e.execution_price,e.commission FROM paper_executions e JOIN paper_orders o ON e.order_id=o.id ORDER BY e.id',conn)
        positions=pd.read_sql_query("SELECT sleeve,symbol,quantity FROM portfolio_positions_v2 WHERE authoritative=1 AND valuation_date='2021-04-07'",conn)
    noncash=positions[positions.symbol!='CASH'].set_index(['sleeve','symbol']).quantity
    reconstructed=fills.groupby(['sleeve','symbol']).quantity_delta.sum()
    pd.testing.assert_series_equal(noncash.sort_index(),reconstructed.sort_index(),check_names=False,atol=1e-9)
    expected_cash=config.initial_nav-(fills.quantity_delta*fills.execution_price).sum()-fills.commission.sum()
    assert positions[positions.symbol=='CASH'].quantity.sum()==pytest.approx(expected_cash,abs=1e-8)
    resize=fills[fills.order_type=='SLEEVE_RESIZE']
    assert len(resize)==1
    assert resize.execution_price.iloc[0]==(22. if suspended else 20.)
    return fills,at_six


def test_resize_fills_and_cash_conserve_capital_through_open_gap(tmp_path):
    fills,_=run_case(tmp_path/'base')
    altered,_=run_case(tmp_path/'altered',altered_close=True)
    pd.testing.assert_frame_equal(fills,altered)


def test_atomic_resize_waits_for_suspended_satellite_open(tmp_path):
    fills,at_six=run_case(tmp_path,suspended=True)
    assert at_six==1
    assert set(fills[fills.order_type!='BULL_FLIP_ENTRY'].actual_execution_date)=={'2021-04-07'}


def test_exit_unblocks_basket_without_backdating_core_fill(tmp_path):
    from test_next_open_engine import _exit
    config=get_strategy('core90_ma200_bull10')
    engine=NextOpenPaperEngine(PortfolioLedger(tmp_path/'ledger.sqlite'))
    engine.activate(config,activation_date=date(2021,4,1))
    frames={s:_frame([('2021-04-01',10.,10.),('2021-04-02',10.,10.),
                     ('2021-04-06',11.,11.),('2021-04-07',12.,12.)])
            for s in ['510300.SS','513100.SS','518880.SS','512880.SS']}
    frames['512880.SS']['BuyOpenAllowed']=[True,True,False,False]
    engine.queue_decision(config,_bull_decision((_entry('512880.SS','a_share'),)),frames)
    engine.reconcile(config,frames,through_date=date(2021,4,2))
    items=tuple({'symbol':s,'event_type':'CORE_REBALANCE','market':'a_share','sleeve':'core',
        'eligible':True,'target_weight':0.3,'priority':0.,'reason':'allocation','payload':{}}
        for s in ['510300.SS','513100.SS','518880.SS'])
    core=replace(_bull_decision(items),run_type='CORE_REBALANCE',signal_date=date(2021,4,2),market_data_date=date(2021,4,2))
    engine.queue_decision(config,core,frames)
    engine.reconcile(config,frames,through_date=date(2021,4,6))
    engine.queue_decision(config,_exit('512880.SS','a_share',date(2021,4,6)),frames)
    engine.reconcile(config,frames,through_date=date(2021,4,7))
    with sqlite3.connect(tmp_path/'ledger.sqlite') as conn:
        dates=conn.execute("SELECT e.actual_execution_date FROM paper_executions e JOIN paper_orders o ON o.id=e.order_id WHERE o.order_type='CORE_REBALANCE'").fetchall()
    assert dates==[('2021-04-07',)]*3
