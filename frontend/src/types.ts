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
  st_val?: number;
  st_dir?: number;
}

export interface MacdDivergenceSignal {
  type: 'bullish' | 'bearish';
  status: 'candidate' | 'confirmed';
  timeframe: 'daily' | 'weekly';
  firstPivotDate: string;
  secondPivotDate: string;
  firstDifDate: string;
  secondDifDate: string;
  confirmedAt: string | null;
  priceChangePct: number;
  difChangeNormalizedPct: number;
  firstDif: number;
  secondDif: number;
  histogramConfirms: boolean | null;
  zeroAxisContext: 'same_side' | 'mixed';
  confidence: 'strong' | 'standard';
  missingRightBars: number;
  expiresAfterBars: number;
  decisionRole:
    | 'display_only'
    | 'risk_warning_only'
    | 'wait_for_trend_confirmation';
}

export interface MacdDivergenceTimeframe {
  asOf: string | null;
  confirmed: MacdDivergenceSignal | null;
  candidate: MacdDivergenceSignal | null;
}

export interface MacdDivergenceSummary {
  daily: MacdDivergenceTimeframe;
  weekly: MacdDivergenceTimeframe;
  policy: {
    confirmedOnlyForDecision: true;
    candidateDecisionRole: 'display_only';
    bullishDecisionRole: 'wait_for_trend_confirmation';
    bearishDecisionRole: 'risk_warning_only';
  };
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
  macdDivergence?: MacdDivergenceSummary;
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

export interface SymbolResolveCandidate {
  symbol: string;
  displayCode: string;
  name: string;
  market: string;
  confidence: 'exact' | 'rule' | 'special';
}

export type Timeframe = '1D' | '1W';

export interface HistorySupertrendPoint {
  time: string;
  value: number;
  direction: 1 | -1;
}

export interface HistoryTradeMarker {
  time: string;
  type: 'buy' | 'sell';
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
  tradeIndex: number;
  price: number;
  exitReason?: string;
}

export type HistorySupertrendExitMode = 'baseline' | 'reclaim' | 'close_only';

export interface HistoryTrade {
  tradeIndex: number;
  symbol: string;
  strategy: string;
  entryDate: string;
  exitDate: string | null;
  entryPrice: number;
  exitPrice: number | null;
  currentDate?: string | null;
  currentPrice?: number | null;
  stopPrice?: number | null;
  returnPct: number;
  holdingDays: number;
  exitReason: string;
  entryAdx?: number | null;
  isOpen?: boolean;
}

export interface HistoryTradesSummary {
  tradeCount: number;
  winRate: number;
  averageReturnPct: number;
  totalReturnPct: number;
  maxDrawdownPct: number;
  averageHoldingDays: number;
  exitReasonCounts: Record<string, number>;
}

export interface HistoryBenchmarkSummary {
  id: string;
  label: string;
  totalReturnPct: number;
  maxDrawdownPct: number;
}

export interface HistoryStrategyComparison extends HistoryTradesSummary {
  id: HistorySupertrendExitMode;
  label: string;
}

export interface HistoryTradesResponse {
  symbol: string;
  strategy: string;
  exitMode: HistorySupertrendExitMode;
  start?: string | null;
  end?: string | null;
  candles: Candle[];
  supertrend: HistorySupertrendPoint[];
  markers: HistoryTradeMarker[];
  trades: HistoryTrade[];
  summary: HistoryTradesSummary;
  benchmark: HistoryBenchmarkSummary;
  strategyComparisons: HistoryStrategyComparison[];
}

export interface HistoryTradeSymbolOption {
  symbol: string;
  name: string;
  displayName: string;
  source: string;
  hasData: boolean;
  hasCache: boolean;
  cachedAt?: string | null;
  cacheCount: number;
}

// Portfolio Strategy Types

export interface PortfolioStrategyItem {
  strategyId: string;
  version: string;
  displayName: string;
  description: string;
  mode: 'paper' | 'comparison';
  execution: string;
  baseCurrency: string;
  initialNav: number;
  paperEnabled: boolean;
  bootstrapped: boolean;
  bootstrapSignalDate?: string | null;
  bootstrapValuationDate?: string | null;
}

export interface PortfolioWeightItem {
  symbol: string;
  weight: number;
  sleeve: string;
  reason: string;
}

export interface PortfolioPositionItem {
  symbol: string;
  weight: number;
  quantity: number;
  price: number | null;
  value: number;
}

export interface PortfolioDiagnosticItem {
  code: string;
  message: string;
  symbol?: string | null;
  details: Record<string, unknown>;
}

export interface PortfolioAssetMeta {
  symbol: string;
  alias: string;
  sleeve: string;
  syntheticProxy: boolean;
}

export interface PortfolioSnapshot {
  strategyId: string;
  strategyVersion: string;
  state: string;
  assets: PortfolioAssetMeta[];
  dates: {
    marketDataDate: string | null;
    signalDate: string | null;
    executionDate: string | null;
    nextCheck: string | null;
  };
  diagnostics: PortfolioDiagnosticItem[];
  observation: {
    asOfDate: string | null;
    state: string | null;
    reason: string | null;
    values: Record<string, unknown>;
  };
  currentWeights: PortfolioPositionItem[];
  desiredWeights: PortfolioWeightItem[];
  executableWeights: PortfolioWeightItem[];
  deltaWeights: Array<{ symbol: string; currentWeight: number; desiredWeight: number; delta: number }>;
  sleeveWeights: Record<string, PortfolioWeightItem[]>;
  nav: {
    valuationDate?: string | null;
    grossNav?: number | null;
    netNav?: number | null;
    cash?: number | null;
    dailyReturn?: number | null;
    cumulativeReturn?: number | null;
    drawdown?: number | null;
  };
  ledger: {
    status: string;
    rebalanceId?: number | null;
    signalDate?: string | null;
  };
  calcError?: string | null;
}

export interface PortfolioTargetWeights {
  strategyId: string;
  desired: PortfolioWeightItem[];
  executable: PortfolioWeightItem[];
}

export interface PortfolioDiffRow {
  symbol: string;
  currentWeight: number;
  desiredWeight: number;
  delta: number;
}

export interface PortfolioRebalanceDiff {
  strategyId: string;
  rows: PortfolioDiffRow[];
}

export interface PortfolioLedgerEvent {
  type: string;
  id: number;
  eventDate: string | null;
  state: string | null;
  reason: string | null;
  createdAt: string | null;
}

export interface PortfolioLedgerEvents {
  strategyId: string;
  events: PortfolioLedgerEvent[];
  nextCursor: number | null;
}

export interface PortfolioNavPoint {
  valuationDate: string;
  grossNav: number;
  netNav: number;
  cash: number;
  dailyReturn: number;
  cumulativeReturn: number;
  drawdown: number;
}

export interface PortfolioNavSeries {
  strategyId: string;
  points: PortfolioNavPoint[];
}
