export interface Candle {
  time: string; // 'yyyy-mm-dd'
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema20?: number;
  ema50?: number;
  rsi?: number;
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
  rsi: number;
  rsiPeriod: number; // Dynamic period
  rsiStatus: '超买' | '超卖' | '中性';
  rsiOverbought: number;
  rsiOversold: number;
  // Computed statuses
  trend: '强势多头' | '回调多头' | '潜在转空' | '强势空头' | '反弹空头' | '潜在转多' | '震荡';
  signal: '强烈信号' | '谨慎信号' | '观望' | 'WAIT';
  alias?: string;
  // Weekly Indicators
  weeklyMA5?: number;
  weeklyMacdStatus?: '周线牛市' | '周线反弹' | '周线回调' | '周线熊市';
  weeklyPriceVsMA5?: '线上' | '线下';
  weeklyMacdHist?: number;
}

export interface WatchlistItem {
  symbol: string;
  alias?: string;
}

export interface WatchlistGroup {
  id: string;
  name: string;
  collapsed: boolean;
  symbols: WatchlistItem[]; 
  stocks?: StockData[]; // Optional, populated after fetching
}

export type Timeframe = '1D' | '4H';
