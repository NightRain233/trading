export const WATCHLIST_VISIBLE_POLL_DELAY_MS = 30_000;
export const WATCHLIST_HIDDEN_POLL_DELAY_MS = 300_000;
export const SUPERTREND_POLL_DELAY_MS = 15 * 60_000;
export const SUPERTREND_REFRESH_RETRY_DELAY_MS = 5_000;
export const SUPERTREND_MAX_REFRESH_RETRIES = 2;

export function shouldPollWatchlist(activeTab) {
  return activeTab === 'watchlist';
}

export function getWatchlistPollDelay({ activeTab, visibilityState }) {
  if (!shouldPollWatchlist(activeTab)) return null;
  return visibilityState === 'visible'
    ? WATCHLIST_VISIBLE_POLL_DELAY_MS
    : WATCHLIST_HIDDEN_POLL_DELAY_MS;
}

export function getSupertrendPollDelay({ refreshTriggered, retryCount }) {
  if (refreshTriggered && retryCount < SUPERTREND_MAX_REFRESH_RETRIES) {
    return SUPERTREND_REFRESH_RETRY_DELAY_MS;
  }
  return SUPERTREND_POLL_DELAY_MS;
}

export function shouldRefreshOnVisibility({ lastLoadedAt, now, minIntervalMs = 60_000 }) {
  if (!lastLoadedAt) return true;
  return now - lastLoadedAt >= minIntervalMs;
}
