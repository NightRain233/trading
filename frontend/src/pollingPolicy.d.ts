export const WATCHLIST_VISIBLE_POLL_DELAY_MS: number;
export const WATCHLIST_HIDDEN_POLL_DELAY_MS: number;
export const SUPERTREND_POLL_DELAY_MS: number;
export const SUPERTREND_REFRESH_RETRY_DELAY_MS: number;
export const SUPERTREND_MAX_REFRESH_RETRIES: number;

export function shouldPollWatchlist(activeTab: string): boolean;
export function getWatchlistPollDelay(options: {
  activeTab: string;
  visibilityState: DocumentVisibilityState;
}): number | null;
export function getSupertrendPollDelay(options: {
  refreshTriggered: boolean;
  retryCount: number;
}): number;
export function shouldRefreshOnVisibility(options: {
  lastLoadedAt: number | null;
  now: number;
  minIntervalMs?: number;
}): boolean;
