import test from 'node:test';
import assert from 'node:assert/strict';

import { getDefaultHistoryStartDate } from '../src/historyTradesDefaults.js';

test('getDefaultHistoryStartDate returns the same calendar date five years earlier', () => {
  assert.equal(getDefaultHistoryStartDate(new Date(2026, 4, 31)), '2021-05-31');
});

test('getDefaultHistoryStartDate handles leap day by falling back to February 28', () => {
  assert.equal(getDefaultHistoryStartDate(new Date(2024, 1, 29)), '2019-02-28');
});
