"""Small execution golden fixture, NOT a historical strategy baseline."""
from dataclasses import asdict
from datetime import date
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'backend'))
import pandas as pd
from portfolio_strategies.event_ledger import payload_hash
from portfolio_strategies.next_open_strategies import FrozenDecision, strategy_config_hash
from portfolio_strategies.registry import get_strategy
from portfolio_strategies.research_replay import replay_frozen_decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = get_strategy('core90_ma200_bull10')
    rows = [
        ('2021-04-01',10.,10.,True,True), ('2021-04-02',11.,11.,False,True),
        ('2021-04-06',12.,13.,True,True), ('2021-04-07',13.,14.,True,False),
        ('2021-04-08',14.,15.,True,True),
    ]
    frame = pd.DataFrame(rows, columns=['date','Open','Close','BuyOpenAllowed','SellOpenAllowed']).set_index('date')
    frame.index = pd.to_datetime(frame.index)
    frame['High'] = frame[['Open','Close']].max(axis=1)
    frame['Low'] = frame[['Open','Close']].min(axis=1)
    frame['Volume'] = 1_000_000.
    frame.to_csv(args.output / 'fixture_prices.csv')
    decisions = []
    for session, event in [('2021-04-01','BULL_FLIP_ENTRY'), ('2021-04-06','ST_BEAR_EXIT')]:
        item = {'symbol':'002119.SZ','market':'a_share','sleeve':'satellite',
                'event_type':event,'eligible':True,'target_weight':0.1 if event=='BULL_FLIP_ENTRY' else 0.,
                'priority':1.,'reason':'synthetic execution fixture','payload':{}}
        payload = {'items':[item]}
        decisions.append(FrozenDecision(
            run_type='BULL_DAILY:002119.SZ',market_data_date=date.fromisoformat(session),
            signal_date=date.fromisoformat(session),universe_version='synthetic_fixture',
            config_hash=strategy_config_hash(config),input_hash=payload_hash(payload),
            data_quality_status='OK',payload=payload,items=(item,),
            signal_contract_version='bull_flip_ma200_v1',
        ))
    (args.output/'fixture_decisions.json').write_text(json.dumps([asdict(d) for d in decisions],default=str,indent=2)+'\n')
    tables = replay_frozen_decisions(config, decisions, {'002119.SZ':frame},
        activation_date=date(2021,4,1),through_date=date(2021,4,8),db_path=args.output/'research.sqlite')
    artifacts = {}
    for name, table in tables.items():
        # Operational wall-clock timestamps are not economic replay outputs.
        columns = [c for c in table.columns if c not in {'created_at','updated_at','observed_at','processed_at','activated_at'}]
        destination = args.output/f'{name}.csv'
        table[columns].to_csv(destination,index=False)
        artifacts[destination.name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    sources = ['execution_rules.py','next_open_engine.py','next_open_strategies.py','research_replay.py',
               'event_ledger.py','ledger.py','registry.py','models.py','frozen_xquant.py','signal_contracts.py']
    manifest = {'kind':'synthetic_execution_fixture','currentHistoricalBaseline':False,
                'strategyConfig':{'strategyId':config.strategy_id,'version':config.version,
                    'initialNav':config.initial_nav,'baseCurrency':config.base_currency,
                    'execution':config.execution,'params':dict(config.params),
                    'assets':[asdict(a) for a in config.assets],
                    'costs':{'baseBps':config.costs.base_bps,'slippageBps':config.costs.slippage_bps,
                             'assetExtraBps':dict(config.costs.asset_extra_bps)}},'artifacts':artifacts,
                'sourceHashes':{p:hashlib.sha256((ROOT/'backend/portfolio_strategies'/p).read_bytes()).hexdigest() for p in sources}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,default=str,indent=2)+'\n')
    print('Exported decisions, orders, attempts, fills, positions and NAV using the paper kernel.')


if __name__=='__main__':
    main()
