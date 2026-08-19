import test from 'node:test';
import assert from 'node:assert/strict';

import { buildAssetRows, stateTone } from '../src/portfolioStrategies.js';

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
