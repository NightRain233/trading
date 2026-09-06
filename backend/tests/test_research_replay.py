from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from portfolio_strategies.research_replay import replay_frozen_decisions
from portfolio_strategies.registry import get_strategy
from test_next_open_engine import _bull_decision, _entry, _exit, _frame


def test_research_uses_paper_kernel_and_preserves_delayed_order_and_nav(tmp_path: Path):
    config = get_strategy('core90_ma200_bull10')
    frame = _frame([
        ('2021-04-01', 10., 10.), ('2021-04-02', 11., 11.),
        ('2021-04-06', 12., 13.), ('2021-04-07', 13., 14.), ('2021-04-08', 14., 15.),
    ])
    frame['BuyOpenAllowed'] = [True, False, True, True, True]
    frame['SellOpenAllowed'] = [True, True, True, False, True]
    decisions = [_bull_decision((_entry('002119.SZ', 'a_share'),)),
                 _exit('002119.SZ', 'a_share', date(2021,4,6))]
    result = replay_frozen_decisions(config, decisions, {'002119.SZ':frame},
        activation_date=date(2021,4,1), through_date=date(2021,4,8), db_path=tmp_path/'research.sqlite')
    fills = result['fills']
    assert list(fills['actual_execution_date']) == ['2021-04-06', '2021-04-08']
    assert list(fills['side']) == ['BUY','SELL']
    assert list(fills['actual_open']) == [12.,14.]
    assert fills.iloc[0]['execution_price'] == pytest.approx(12.006)
    assert fills.iloc[1]['execution_price'] == pytest.approx(13.993)
    assert set(result['attempts']['reason']) == {'BUY_OPEN_BLOCKED', 'SELL_OPEN_BLOCKED'}
    quantity = float(fills.iloc[0]['quantity_delta'])
    expected = config.initial_nav + quantity * (13.993 - 12.006) - float(fills['commission'].sum())
    nav = result['daily_nav'].query('authoritative == 1').sort_values('valuation_date')
    assert nav.iloc[-1]['net_nav'] == pytest.approx(expected)
    frame.loc['2021-04-06','Close'] = 99999.
    second = replay_frozen_decisions(config, decisions, {'002119.SZ':frame},
        activation_date=date(2021,4,1), through_date=date(2021,4,8), db_path=tmp_path/'mutated.sqlite')
    pd.testing.assert_frame_equal(fills[['actual_execution_date','quantity_delta','execution_price']],
                                  second['fills'][['actual_execution_date','quantity_delta','execution_price']])
    with pytest.raises(ValueError, match='new ledger'):
        replay_frozen_decisions(config, decisions, {}, activation_date=date(2021,4,1),
            through_date=date(2021,4,8), db_path=tmp_path/'research.sqlite')


def test_execution_artifacts_match_versioned_golden(tmp_path: Path):
    import subprocess
    import sys
    import hashlib
    import json
    root = Path(__file__).resolve().parents[2]
    fixture_root = root / 'backend/tests/fixtures/research_execution'
    output = tmp_path / 'export'
    subprocess.run([sys.executable, str(fixture_root/'replay_execution.py'), '--output', str(output)], check=True)
    manifest = json.loads((fixture_root/'execution_golden_2_1/manifest.json').read_text())
    for filename, expected in manifest['artifacts'].items():
        assert hashlib.sha256((output/filename).read_bytes()).hexdigest() == expected, filename
