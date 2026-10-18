import test from 'node:test';
import assert from 'node:assert/strict';

import { btcSwitch, btcSwitchEvents, buildAssetRows, buildDailyVerdict, drawdownLabel, stateTone } from '../src/portfolioStrategies.js';

test('buildAssetRows aggregates cash held in independent sleeves', () => {
  const rows = buildAssetRows({
    currentWeights: [
      { symbol: 'CASH', weight: 0.04, sleeve: 'core' },
      { symbol: 'CASH', weight: 0.03, sleeve: 'satellite' },
      { symbol: '510300.SS', weight: 0.93, sleeve: 'core' },
    ],
    desiredWeights: [
      { symbol: 'CASH', weight: 0.05, sleeve: 'portfolio', reason: 'residual' },
      { symbol: '510300.SS', weight: 0.95, sleeve: 'core', reason: 'target' },
    ],
  });

  const cash = rows.find(row => row.symbol === 'CASH');
  assert.equal(cash.currentWeight, 0.07);
  assert.equal(cash.desiredWeight, 0.05);
  assert.ok(Math.abs(cash.delta + 0.02) < 1e-12);
});

test('stateTone presents pending execution as a warning', () => {
  assert.deepEqual(stateTone('PENDING_EXECUTION'), { tone: 'warning', label: '待执行' });
});

const btcSnapshot = (overrides = {}) => ({
  state: 'NOT_DUE',
  dates: { marketDataDate: '2026-10-16', signalDate: '2026-10-14', nextCheck: '2026-10-28' },
  diagnostics: [],
  observation: { values: { btc_close: 100000, supertrend_line: 95000, supertrend_on: true, formal_supertrend_on: true } },
  nav: { netNav: 100000 },
  operations: { orders: [], dataQualityEventCount: 0 },
  ...overrides,
});

test('calm day says no action and names the next check', () => {
  const verdict = buildDailyVerdict(btcSnapshot());
  assert.equal(verdict.kind, 'calm');
  assert.equal(verdict.verdict, '今天不用操作');
  assert.match(verdict.sub, /2026-10-28/);
});

test('a BTC flip between checks waits for the next check', () => {
  const verdict = buildDailyVerdict(btcSnapshot({
    observation: { values: { btc_close: 90000, supertrend_line: 95000, supertrend_on: false, formal_supertrend_on: true } },
  }));
  assert.equal(verdict.kind, 'btcFlip');
  assert.equal(verdict.verdict, '今天不用操作');
  assert.match(verdict.sub, /2026-10-28 检查时卖出 BTC/);
});

test('pending rebalance lists sells before buys with amounts from NAV', () => {
  const verdict = buildDailyVerdict(
    btcSnapshot({ operations: { orders: [{ symbol: 'BATCH', status: 'PENDING', due: true, expectedExecutionDate: '2026-10-19' }], dataQualityEventCount: 0 } }),
    [
      { symbol: '510300.SS', currentWeight: 0.28, desiredWeight: 0.31, delta: 0.03 },
      { symbol: '518880.SS', currentWeight: 0.44, desiredWeight: 0.40, delta: -0.04 },
      { symbol: 'CASH', currentWeight: 0.01, desiredWeight: 0, delta: -0.01 },
      { symbol: '513100.SS', currentWeight: 0.22, desiredWeight: 0.222, delta: 0.002 },
      { symbol: 'BTC-USD', currentWeight: 0.065, desiredWeight: 0.075, delta: 0.01 },
    ],
  );
  assert.equal(verdict.kind, 'rebalance');
  assert.equal(verdict.verdict, '今天要调仓');
  assert.deepEqual(verdict.todo.map(row => [row.side, row.symbol, Math.round(row.amount)]), [
    ['卖出', '518880.SS', 4000],
    ['买入', '510300.SS', 3000],
    ['买入', 'BTC-USD', 1000],
  ]);
});

test('blocked data tells the user not to trade', () => {
  assert.equal(buildDailyVerdict(btcSnapshot({ state: 'BLOCKED' })).kind, 'blocked');
  assert.equal(buildDailyVerdict(null).kind, 'empty');
});

test('btcSwitch is null for strategies without a BTC switch', () => {
  assert.equal(btcSwitch({ observation: { values: {} } }), null);
  assert.ok(Math.abs(btcSwitch(btcSnapshot()).distance - 0.05) < 1e-12);
});

test('drawdownLabel anchors on the backtest range', () => {
  assert.equal(drawdownLabel(-0.03), '正常范围');
  assert.equal(drawdownLabel(-0.12), '回测里出现过，按规则持有');
  assert.equal(drawdownLabel(-0.2), '比回测更深，按规则持有');
});

test('a fresh all-cash account waits for its first build', () => {
  const verdict = buildDailyVerdict(btcSnapshot({
    currentWeights: [{ symbol: 'CASH', weight: 1, sleeve: 'cash' }],
    desiredWeights: [{ symbol: '510300.SS', weight: 0.36, sleeve: 'core', reason: '' }],
  }));
  assert.equal(verdict.kind, 'awaitingBuild');
  assert.match(verdict.sub, /2026-10-28 检查时建仓/);
});

test('btcSwitchEvents lists only formal switch changes', () => {
  const p = (date, on, formalOn, check = false) => ({ date, close: 1, line: 1, on, check, formalOn });
  const events = btcSwitchEvents([
    p('d1', false, null),
    p('d2', true, true, true),
    p('d3', false, true),
    p('d4', false, false, true),
    p('d5', true, false),
    p('d6', true, true, true),
  ]);
  assert.deepEqual(events.map(e => [e.date, e.on]), [['d4', false], ['d6', true]]);
});
