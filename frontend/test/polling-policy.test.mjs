import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getSupertrendPollDelay,
  getWatchlistPollDelay,
  shouldPollWatchlist,
} from '../src/pollingPolicy.js';

test('watchlist quotes only poll while the watchlist tab is active', () => {
  assert.equal(shouldPollWatchlist('watchlist'), true);
  assert.equal(shouldPollWatchlist('st'), false);
  assert.equal(shouldPollWatchlist('rs'), false);
  assert.equal(shouldPollWatchlist('history'), false);
});

test('watchlist polling keeps existing visible and hidden delays', () => {
  assert.equal(getWatchlistPollDelay({ activeTab: 'watchlist', visibilityState: 'visible' }), 30_000);
  assert.equal(getWatchlistPollDelay({ activeTab: 'watchlist', visibilityState: 'hidden' }), 300_000);
  assert.equal(getWatchlistPollDelay({ activeTab: 'st', visibilityState: 'visible' }), null);
});

test('supertrend polling uses low frequency unless backend refresh is in flight', () => {
  assert.equal(getSupertrendPollDelay({ refreshTriggered: false, retryCount: 0 }), 15 * 60_000);
  assert.equal(getSupertrendPollDelay({ refreshTriggered: true, retryCount: 0 }), 5_000);
  assert.equal(getSupertrendPollDelay({ refreshTriggered: true, retryCount: 1 }), 5_000);
  assert.equal(getSupertrendPollDelay({ refreshTriggered: true, retryCount: 2 }), 15 * 60_000);
});
