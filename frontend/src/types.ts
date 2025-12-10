export interface Candle {
  time: string; // 'yyyy-mm-dd'
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface StockData {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
  candles: Candle[]; // Daily candles
  ema20: number;
  ema50: number;
  adx: number;
  // Computed statuses
  trend: 'LONG' | 'SHORT' | 'NEUTRAL';
  trendStrength: 'STRONG' | 'WEAK'; // Based on ADX
  signal: 'WAIT' | 'ENTRY_Long' | 'ENTRY_Short' | 'NONE'; 
}

export type Timeframe = '1D' | '4H';
