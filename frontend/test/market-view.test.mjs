import test from 'node:test';
import assert from 'node:assert/strict';

import { marketOf, marketReading, matchesFilter, ruleState, slopeArrow, sortByStrength } from '../src/marketView.js';

const stock = (symbol, view) => ({ symbol, weinstein: view });
const view = overrides => ({ stage: 2, ma30Distance: 0.05, bbState: 'none', rs26: 0.1, ...overrides });

test('filters by stage, Bollinger state and position against the 30-week average', () => {
  assert.equal(matchesFilter(stock('A', view()), 's2'), true);
  assert.equal(matchesFilter(stock('A', view({ stage: 3 })), 's2'), false);
  assert.equal(matchesFilter(stock('A', view({ bbState: 'squeeze' })), 'bb'), true);
  assert.equal(matchesFilter(stock('A', view({ ma30Distance: -0.02 })), 'below'), true);
  assert.equal(matchesFilter(stock('A', null), 's2'), false);
  assert.equal(matchesFilter(stock('A', null), 'all'), true);
});

test('sorts stronger relative strength first and missing data last', () => {
  const sorted = sortByStrength([
    stock('NONE', view({ rs26: null })),
    stock('WEAK', view({ rs26: -0.1 })),
    stock('STRONG', view({ rs26: 0.3 })),
  ]);
  assert.deepEqual(sorted.map(s => s.symbol), ['STRONG', 'WEAK', 'NONE']);
});

test('slope arrows use the same flat band as the stage rule', () => {
  assert.equal(slopeArrow(0.01), '↗');
  assert.equal(slopeArrow(-0.01), '↘');
  assert.equal(slopeArrow(0.002), '→');
  assert.equal(slopeArrow(null), '');
});

test('market reading tells the user whether to look for entries', () => {
  assert.match(marketReading(view({ stage: 4 })), /只看不买/);
  assert.equal(marketReading(null), '数据不足');
});

test('marketOf buckets symbols for the weekly scan', () => {
  assert.equal(marketOf('QQQ'), 'us');
  assert.equal(marketOf('BTC-USD'), 'crypto');
  assert.equal(marketOf('510300.SS'), 'cn');
  assert.equal(marketOf('2800.HK'), 'cn');
  assert.equal(marketOf('GC=F'), 'other');
});

test('ruleState follows the plain Weinstein buy and sell rules', () => {
  const v = (stage, weeksInStage, rs26, ma30Distance) => ({ stage, weeksInStage, rs26, ma30Distance });
  assert.equal(ruleState(v(2, 2, 0.05, 0.03)).key, 'entry');
  assert.equal(ruleState(v(2, 2, -0.05, 0.03)).key, 'hold');
  assert.equal(ruleState(v(2, 12, 0.05, 0.03)).key, 'hold');
  assert.equal(ruleState(v(3, 1, 0, -0.02)).key, 'exit');
  assert.equal(ruleState(v(3, 1, 0, 0.02)).key, 'caution');
  assert.equal(ruleState(v(4, 9, -0.1, -0.1)).key, 'out');
  assert.equal(ruleState(v(1, 3, null, 0.01)).key, 'wait');
  assert.equal(ruleState(null).label, '数据不足');
});
