import test from 'node:test';
import assert from 'node:assert/strict';

import {
  deriveConfluenceLabel,
  deriveDisplaySignal,
  getWeakOpportunityHint,
  isDefaultVisible,
  sortSupertrendItems,
} from '../src/supertrendDisplay.js';

function item(overrides = {}) {
  return {
    symbol: 'BASE',
    state: 'bear',
    weeklyState: 'bull',
    justFlipped: false,
    alertType: 'avoid_bear',
    alertPriority: 'low',
    isActionable: false,
    opportunityStage: 'invalidated',
    distanceToSupertrendAtr: 1.2,
    ...overrides,
  };
}

test('pre-bull is only weekly-bull daily-bear near resistance', () => {
  const ready = item({
    symbol: 'READY',
    state: 'bear',
    weeklyState: 'bull',
    alertType: 'resistance_test',
    alertPriority: 'medium',
    isActionable: true,
  });
  const tooFar = item({
    symbol: 'FAR',
    state: 'bear',
    weeklyState: 'bull',
    alertType: 'avoid_bear',
  });

  assert.deepEqual(deriveDisplaySignal(ready), {
    key: 'pre_bull',
    label: '预备翻多',
    tone: 'amber',
    rank: 2,
  });
  assert.equal(deriveDisplaySignal(tooFar), null);
});

test('fresh bull and pullback buy are the strongest buy-point labels', () => {
  assert.deepEqual(
    deriveDisplaySignal(item({ state: 'bull_flip', weeklyState: 'bull', alertType: 'buy_candidate', alertPriority: 'high', justFlipped: true })),
    { key: 'fresh_bull', label: '刚翻多', tone: 'emerald', rank: 0 },
  );
  assert.deepEqual(
    deriveDisplaySignal(item({ state: 'bull', weeklyState: 'bull', alertType: 'support_test', alertPriority: 'high' })),
    { key: 'pullback_buy', label: '回踩买点', tone: 'cyan', rank: 1 },
  );
});

test('invalidated and extended opportunity stages do not become primary labels', () => {
  assert.equal(
    deriveDisplaySignal(item({ state: 'bear', alertType: 'avoid_bear', opportunityStage: 'invalidated' })),
    null,
  );
  assert.equal(
    deriveDisplaySignal(item({ state: 'bull', alertType: 'hold_bull', opportunityStage: 'extended_from_entry' })),
    null,
  );
  assert.equal(getWeakOpportunityHint(item({ state: 'bull', opportunityStage: 'wait_pullback', distanceToSupertrendAtr: 2.34 })), '离支撑 2.34 ATR，等回踩');
});

test('default visibility keeps buy queue and hides ordinary observations', () => {
  assert.equal(isDefaultVisible(item({ state: 'bull_flip', weeklyState: 'bull', alertType: 'buy_candidate' })), true);
  assert.equal(isDefaultVisible(item({ state: 'bear', weeklyState: 'bull', alertType: 'resistance_test' })), true);
  assert.equal(isDefaultVisible(item({ state: 'bear', weeklyState: 'bear', alertType: 'avoid_bear' })), false);
  assert.equal(isDefaultVisible(item({ state: 'bull', alertType: 'hold_bull' }), 'holding'), false);
  assert.equal(isDefaultVisible(item({ state: 'bull', alertType: 'hold_bull', alertPriority: 'high' }), 'holding'), true);
});

test('default sorting forms the evening review opportunity queue', () => {
  const rows = [
    item({ symbol: 'OTHER', state: 'bear', weeklyState: 'bear', alertType: 'avoid_bear', alertPriority: 'low' }),
    item({ symbol: 'RISK', state: 'bear_flip', weeklyState: 'bear', alertType: 'sell_or_risk', alertPriority: 'high' }),
    item({ symbol: 'PRE', state: 'bear', weeklyState: 'bull', alertType: 'resistance_test', alertPriority: 'medium' }),
    item({ symbol: 'MARKED', state: 'bull', alertType: 'hold_bull', alertPriority: 'high' }),
    item({ symbol: 'PULL', state: 'bull', weeklyState: 'bull', alertType: 'support_test', alertPriority: 'high' }),
    item({ symbol: 'FRESH', state: 'bull_flip', weeklyState: 'bull', alertType: 'buy_candidate', alertPriority: 'high', justFlipped: true }),
  ];

  const sorted = sortSupertrendItems(rows, { MARKED: 'watch' });

  assert.deepEqual(sorted.map(row => row.symbol), ['FRESH', 'PULL', 'PRE', 'RISK', 'MARKED', 'OTHER']);
});

test('confluence label keeps weekly and daily state without colored pills', () => {
  assert.equal(deriveConfluenceLabel(item({ weeklyState: 'bull', state: 'bear' })), '周多 · 日空');
  assert.equal(deriveConfluenceLabel(item({ weeklyState: 'bull', state: 'bull_flip' })), '周多 · 日刚多');
  assert.equal(deriveConfluenceLabel(item({ weeklyState: null, state: 'bear_flip' })), '日刚空');
});
