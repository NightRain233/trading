import type { StockData, WatchlistGroup, WatchlistItem } from './types';

// 自动根据环境判断 API 地址
// 开发环境下使用 hardcode 的 IP，生产环境下使用相对路径（由 Nginx 转发）
const API_BASE_URL = import.meta.env.PROD 
  ? '/api' 
  : 'http://localhost:8000/api';

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

export async function fetchWatchlist(): Promise<WatchlistGroup[]> {
  try {
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

// Helper for calculated EMA (kept for chart interactions if needed)
export function calculateEMA(candles: any[], period: number) {
    const k = 2 / (period + 1);
    let ema = candles[0].close;
    const result = [{ time: candles[0].time, value: ema }];
  
    for (let i = 1; i < candles.length; i++) {
      ema = candles[i].close * k + ema * (1 - k);
      result.push({ time: candles[i].time, value: ema });
    }
    return result;
}
