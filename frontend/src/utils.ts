import type { StockData } from './types';

const API_BASE_URL = 'http://localhost:8000/api';

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

// WATCHLIST_SYMBOLS removed as it's now dynamic from backend

export async function fetchWatchlist(): Promise<StockData[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist`);
    if (!response.ok) return [];
    return await response.json();
  } catch (error) {
    console.error("Error fetching watchlist:", error);
    return [];
  }
}

export async function addTicker(symbol: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol })
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

// Helper for calculated EMA (now mostly done in backend, but kept if needed for interactions)
export function calculateEMA(candles: any[], period: number) {
    // If backend provides EMAs in the candle objects, we can just use that.
    // Or if we need to recalculate on client for some interaction.
    // For now, let's trust the backend data or if the chart needs arrays:
    const k = 2 / (period + 1);
    let ema = candles[0].close;
    const result = [{ time: candles[0].time, value: ema }];
  
    for (let i = 1; i < candles.length; i++) {
      ema = candles[i].close * k + ema * (1 - k);
      result.push({ time: candles[i].time, value: ema });
    }
    return result;
}

