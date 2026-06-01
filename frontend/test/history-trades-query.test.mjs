import test from 'node:test';
import assert from 'node:assert/strict';

import { buildHistoryTradesQuery } from '../src/historyTradesQuery.js';

test('buildHistoryTradesQuery defaults the selected exit mode to close_only', () => {
  const query = buildHistoryTradesQuery({
    symbol: 'test',
    strategy: 'supertrend',
  });

  assert.equal(query.get('symbol'), 'TEST');
  assert.equal(query.get('strategy'), 'supertrend');
  assert.equal(query.get('exit_mode'), 'close_only');
});

test('buildHistoryTradesQuery preserves explicit baseline exit mode', () => {
  const query = buildHistoryTradesQuery({
    symbol: 'TEST',
    strategy: 'supertrend',
    exitMode: 'baseline',
  });

  assert.equal(query.get('exit_mode'), 'baseline');
});
