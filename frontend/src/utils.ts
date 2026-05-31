import type { Candle, HistoryTradeSymbolOption, HistoryTradesResponse, StockData, Timeframe, WatchlistGroup, WatchlistItem } from './types';
import { normalizeBatchSnapshot, parseBatchHeaders, parseBatchResponse } from './batchResponse.js';

// 自动根据环境判断 API 地址
// 开发环境下使用 hardcode 的 IP，生产环境下使用相对路径（由 Nginx 转发）
const API_BASE_URL = '/api';

export type BatchQuotesConditionalResult =
  | {
      status: 'not_modified';
      etag: string | null;
      updatedAt: string | null;
      stale: boolean;
      refreshTriggered: boolean;
    }
  | {
      status: 'updated';
      data: Record<string, StockData>;
      etag: string | null;
      updatedAt: string | null;
      stale: boolean;
      refreshTriggered: boolean;
    };

export type BatchQuotesSnapshot = {
  data: Record<string, StockData>;
  etag: string | null;
  updatedAt: string | null;
  stale: boolean;
  refreshTriggered: boolean;
};

export async function fetchStockData(symbol: string): Promise<StockData | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/quote/${symbol}`);
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error(`Error fetching ${symbol}:`, error);
    return null;
  }
}

export async function fetchBatchQuotes(symbols: string[]): Promise<Record<string, StockData>> {
  const snapshot = await fetchBatchQuotesSnapshot(symbols);
  return snapshot.data;
}

export async function fetchBatchQuotesSnapshot(symbols: string[]): Promise<BatchQuotesSnapshot> {
  try {
    // 优先使用 index.html 中预抓取的 Promise
    const prefetchPromise = (window as any).__BATCH_PROMISE__;
    if (prefetchPromise) {
      const snapshot = normalizeBatchSnapshot(await prefetchPromise);
      (window as any).__BATCH_PROMISE__ = null;
      if (Object.keys(snapshot.data).length > 0 || snapshot.updatedAt) return snapshot;
    }

    const response = await fetch(`${API_BASE_URL}/quotes/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols })
    });
    return normalizeBatchSnapshot(await parseBatchResponse(response)) as BatchQuotesSnapshot;
  } catch (error) {
    console.error('Error fetching batch quotes:', error);
    return normalizeBatchSnapshot(null) as BatchQuotesSnapshot;
  }
}

export async function fetchBatchQuotesConditional(
  symbols: string[],
  etag?: string
): Promise<BatchQuotesConditionalResult> {
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (etag) {
      headers['If-None-Match'] = etag;
    }

    const response = await fetch(`${API_BASE_URL}/quotes/batch`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ symbols }),
    });

    const meta = parseBatchHeaders(response.headers);
    if (response.status === 304) {
      return {
        status: 'not_modified',
        ...meta,
      };
    }

    if (!response.ok) {
      return {
        status: 'updated',
        data: {},
        etag: null,
        updatedAt: null,
        stale: true,
        refreshTriggered: false,
      };
    }

    const data = (await response.json()) as Record<string, StockData>;
    return {
      status: 'updated',
      data,
      ...meta,
    };
  } catch (error) {
    console.error('Error fetching conditional batch quotes:', error);
    return {
      status: 'updated',
      data: {},
      etag: null,
      updatedAt: null,
      stale: true,
      refreshTriggered: false,
    };
  }
}

export async function fetchBatchCharts(
  symbols: string[],
  timeframe: Timeframe = '1D'
): Promise<Record<string, Candle[]>> {
  try {
    const response = await fetch(`${API_BASE_URL}/quotes/batch/charts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols, timeframe })
    });
    if (!response.ok) return {};
    return await response.json();
  } catch (error) {
    console.error('Error fetching batch charts:', error);
    return {};
  }
}

export async function fetchWatchlist(): Promise<WatchlistGroup[]> {
  try {
    // 优先使用 index.html 中预抓取的 Promise
    const prefetchPromise = (window as any).__WATCHLIST_PROMISE__;
    if (prefetchPromise) {
      const data = await prefetchPromise;
      // 使用完后清除，防止后续刷新又用了旧的（或者由 loadData 自行决定）
      (window as any).__WATCHLIST_PROMISE__ = null;
      if (data) return data;
    }

    const response = await fetch(`${API_BASE_URL}/watchlist`);
    if (!response.ok) return [];
    return await response.json();
  } catch (error) {
    console.error("Error fetching watchlist:", error);
    return [];
  }
}

export async function addTicker(symbol: string, groupId?: string, alias?: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, groupId, alias })
    });
    return response.ok;
  } catch (error) {
    console.error(`Error adding ${symbol}:`, error);
    return false;
  }
}

export async function removeTicker(symbol: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist/${symbol}`, {
      method: 'DELETE'
    });
    return response.ok;
  } catch (error) {
    console.error(`Error removing ${symbol}:`, error);
    return false;
  }
}

export async function createGroup(name: string): Promise<WatchlistGroup | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/groups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error(`Error creating group:`, error);
    return null;
  }
}

export async function updateWatchlist(groups: { id: string; name: string; symbols: WatchlistItem[]; collapsed: boolean }[]): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groups })
    });
    return response.ok;
  } catch (error) {
    console.error(`Error updating watchlist:`, error);
    return false;
  }
}

export async function updateAlias(symbol: string, alias: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist/${symbol}/alias`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias })
    });
    return response.ok;
  } catch (error) {
    console.error(`Error updating alias for ${symbol}:`, error);
    return false;
  }
}

export async function fetchHistoryTrades(params: {
  symbol: string;
  strategy: string;
  start?: string;
  end?: string;
  minAdxForEntry?: number | null;
  weeklyFilter?: boolean;
}): Promise<HistoryTradesResponse> {
  const query = new URLSearchParams({
    symbol: params.symbol.trim().toUpperCase(),
    strategy: params.strategy,
  });
  if (params.start) query.set('start', params.start);
  if (params.end) query.set('end', params.end);
  if (params.minAdxForEntry != null && Number.isFinite(params.minAdxForEntry)) {
    query.set('min_adx_for_entry', String(params.minAdxForEntry));
  }
  if (params.weeklyFilter) query.set('weekly_filter', 'true');

  const response = await fetch(`${API_BASE_URL}/history-trades?${query.toString()}`);
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) message = payload.detail;
    } catch {
      // Keep status message when backend does not return JSON.
    }
    throw new Error(message);
  }
  return await response.json();
}

export async function fetchHistoryTradeSymbols(): Promise<HistoryTradeSymbolOption[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/history-trades/symbols`);
    if (!response.ok) return [];
    return await response.json();
  } catch (error) {
    console.error('Error fetching history trade symbols:', error);
    return [];
  }
}
