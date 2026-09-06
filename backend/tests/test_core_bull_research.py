from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
import numpy as np
import pandas as pd
import exchange_calendars as xcals

from portfolio_strategies.core_bull_research import run_current_contract
from portfolio_strategies.indicators import supertrend
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.service import PortfolioStrategyService


def price_fixture():
    sessions=xcals.get_calendar('XSHG').sessions_in_range('2013-01-02','2015-03-31')
    index=pd.DatetimeIndex(sessions).tz_localize(None)
    frames={}
    for i,symbol in enumerate(['510300.SS','513100.SS','518880.SS','512880.SS']):
        x=np.arange(len(index),dtype=float)
        close=100+0.08*x+8*np.sin(x/(9+i))
        frames[symbol]=pd.DataFrame({'Open':close*0.999,'High':close*1.01,'Low':close*0.99,
                                    'Close':close,'Volume':100_000_000.},index=index)
    return frames


def economic_tables(path):
    with sqlite3.connect(path) as conn:
        return {
            'fills':pd.read_sql_query('SELECT o.sleeve,o.symbol,e.signal_date,e.actual_execution_date,e.side,e.quantity_delta,e.execution_price,e.commission FROM paper_executions e JOIN paper_orders o ON o.id=e.order_id ORDER BY e.actual_execution_date,o.symbol,e.id',conn),
            'nav':pd.read_sql_query('SELECT valuation_date,net_nav FROM portfolio_nav_v2 WHERE authoritative=1 ORDER BY valuation_date',conn),
        }


def test_current_contract_research_matches_daily_paper_service(tmp_path):
    frames=price_fixture()
    config=get_strategy('core90_ma200_bull10')
    start,end=date(2015,1,2),date(2015,2,13)
    run_current_contract(config,frames,start=start,end=end,db_path=tmp_path/'research.sqlite')
    data=tmp_path/'data';data.mkdir()
    for symbol,frame in frames.items():frame.to_parquet(data/f'{symbol}.parquet')
    paper=PortfolioStrategyService(data_dir=data,db_path=tmp_path/'paper.sqlite')
    paper.next_open_engine.activate(config,activation_date=start-timedelta(days=1))
    for timestamp in frames['510300.SS'].loc[str(start):str(end)].index:
        paper._refresh_next_open(config,now=datetime.combine(timestamp.date()+timedelta(days=1),time(1),tzinfo=timezone.utc))
    historical=economic_tables(tmp_path/'research.sqlite')
    live=economic_tables(tmp_path/'paper.sqlite')
    pd.testing.assert_frame_equal(historical['fills'],live['fills'],atol=1e-9,rtol=1e-12)
    # Research also records cash on a requested holiday start. Compare every
    # calendar date with the paper ledger's carried valuation on closed days.
    index=sorted(set(historical['nav'].valuation_date)|set(live['nav'].valuation_date))
    left=historical['nav'].set_index('valuation_date').reindex(index).ffill()
    right=live['nav'].set_index('valuation_date').reindex(index).ffill()
    pd.testing.assert_frame_equal(left,right,atol=1e-9,rtol=1e-12)


def test_supertrend_preselection_is_prefix_causal_and_ignores_future_prices():
    frame=price_fixture()['512880.SS']
    full=supertrend(frame.High,frame.Low,frame.Close,atr_window=7,multiplier=3.)
    for end in [2,7,8,50,300]:
        prefix=frame.iloc[:end]
        actual=supertrend(prefix.High,prefix.Low,prefix.Close,atr_window=7,multiplier=3.)
        pd.testing.assert_frame_equal(actual,full.iloc[:end])
    modified=frame.copy();modified.iloc[300:,modified.columns.get_indexer(['High','Low','Close'])]*=100
    future=supertrend(modified.High,modified.Low,modified.Close,atr_window=7,multiplier=3.)
    pd.testing.assert_frame_equal(full.iloc[:300],future.iloc[:300])


def test_future_price_changes_do_not_rewrite_historical_decisions_or_fills(tmp_path):
    frames=price_fixture()
    config=get_strategy('core90_ma200_bull10')
    start,end=date(2015,1,2),date(2015,2,13)
    run_current_contract(config,frames,start=start,end=end,db_path=tmp_path/'first.sqlite')
    changed={s:f.copy() for s,f in frames.items()}
    for frame in changed.values():
        frame.loc[frame.index>pd.Timestamp(end),['Open','High','Low','Close']]*=100.
    run_current_contract(config,changed,start=start,end=end,db_path=tmp_path/'changed.sqlite')
    a,b=economic_tables(tmp_path/'first.sqlite'),economic_tables(tmp_path/'changed.sqlite')
    for key in a:pd.testing.assert_frame_equal(a[key],b[key])
    with sqlite3.connect(tmp_path/'first.sqlite') as first, sqlite3.connect(tmp_path/'changed.sqlite') as second:
        sql='SELECT run_type,signal_date,input_hash FROM decision_runs ORDER BY id'
        assert first.execute(sql).fetchall()==second.execute(sql).fetchall()


def test_outage_recovery_replays_core_and_satellite_to_same_state(tmp_path):
    frames=price_fixture()
    config=get_strategy('core90_ma200_bull10')
    start,end=date(2015,1,2),date(2015,2,13)
    run_current_contract(config,frames,start=start,end=end,db_path=tmp_path/'research.sqlite')
    data=tmp_path/'prices';data.mkdir()
    for symbol,frame in frames.items():frame.to_parquet(data/f'{symbol}.parquet')
    service=PortfolioStrategyService(data_dir=data,db_path=tmp_path/'outage.sqlite')
    service.next_open_engine.activate(config,activation_date=start-timedelta(days=1))
    for _ in range(2):
        service._refresh_next_open(config,now=datetime.combine(end+timedelta(days=1),time(1),tzinfo=timezone.utc))
    expected=economic_tables(tmp_path/'research.sqlite')
    actual=economic_tables(tmp_path/'outage.sqlite')
    for key in expected:pd.testing.assert_frame_equal(expected[key],actual[key])


def test_evening_waits_for_reference_closes_and_never_values_before_activation(tmp_path):
    frames=price_fixture()
    data=tmp_path/'data';data.mkdir()
    for symbol,frame in frames.items():frame.to_parquet(data/f'{symbol}.parquet')
    config=get_strategy('core90_ma200_bull10')
    service=PortfolioStrategyService(data_dir=data,db_path=tmp_path/'clock.sqlite')
    service.next_open_engine.activate(config,activation_date=date(2015,1,4))
    # Before today's CNY close, only pre-activation prices exist.
    service._refresh_next_open(config,now=datetime(2015,1,5,1,tzinfo=timezone.utc))
    with sqlite3.connect(service.db_path) as conn:
        assert conn.execute('SELECT MIN(valuation_date) FROM portfolio_nav_v2').fetchone()[0]=='2015-01-04'
    service._refresh_next_open(config,now=datetime(2015,1,5,15,tzinfo=timezone.utc))
    with sqlite3.connect(service.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM decision_runs').fetchone()[0]==0
    service._refresh_next_open(config,now=datetime(2015,1,6,0,tzinfo=timezone.utc))
    with sqlite3.connect(service.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM decision_runs WHERE signal_date='2015-01-05' AND run_type='CORE_REBALANCE'").fetchone()[0]==1
