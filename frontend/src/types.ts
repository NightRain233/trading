export interface Candle {
  time: string; // 'yyyy-mm-dd'
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema5?: number;
  ema10?: number;
  ema20?: number;
  ema50?: number;
  ma30?: number;
  rsi?: number;
  boll_upper?: number;
  boll_mid?: number;
  boll_lower?: number;
  k?: number;
  d?: number;
  j?: number;
  macd_dif?: number;
  macd_dea?: number;
  macd_hist?: number;
  atr?: number;
}

export interface StockData {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
  candles: Candle[]; // Daily candles
  weekly_candles?: Candle[]; // Weekly candles
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
  _loading?: boolean;
  // Weekly Statuses
  weeklyMA5?: number | null;
  weeklyMacdStatus?: '周线牛市' | '周线反弹' | '周线回调' | '周线熊市';
  weeklyPriceVsMA5?: '线上' | '线下';
  // Resonance Strategy
  resonanceInPool?: boolean;
  resonanceBuySignal?: boolean;
  resonancePoolReason?: string;
  resonanceBuyReason?: string;
  resonanceStrategyVersion?: string;
  resonancePoolType?: 'none' | 'earlyTrend' | 'establishedTrend';
  resonanceEntryScore?: number;
  resonanceRiskScore?: number;
  resonanceRiskLevel?: 'unknown' | 'low' | 'medium' | 'high';
  resonanceEntryPrice?: number | null;
  resonanceStopPrice?: number | null;
  resonanceRiskPercent?: number | null;
  resonanceTargetPrice?: number | null;
  resonanceRewardRiskRatio?: number | null;
  resonanceExitSignal?: boolean;
  resonanceExitLevel?: 'none' | 'warn' | 'hard';
  resonanceExitReason?: string;
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

export type Timeframe = '1D' | '1W';
