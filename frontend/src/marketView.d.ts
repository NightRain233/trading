import type { StockData, WeinsteinView } from './types';

export declare const STAGE_NAMES: { readonly 1: '第一阶段'; readonly 2: '第二阶段'; readonly 3: '第三阶段'; readonly 4: '第四阶段' };
export declare const STAGE_HINTS: { readonly 1: '筑底'; readonly 2: '上涨'; readonly 3: '做顶'; readonly 4: '下跌' };
export declare const BB_LABELS: Record<WeinsteinView['bbState'], string>;
export declare const MARKET_FILTERS: ReadonlyArray<readonly [string, string]>;
export declare function matchesFilter(stock: StockData, filter: string): boolean;
export declare function sortByStrength(stocks: StockData[]): StockData[];
export declare function slopeArrow(slope: number | null | undefined): string;
export declare function marketReading(view: WeinsteinView | null | undefined): string;

export declare function marketOf(symbol: string): 'us' | 'crypto' | 'cn' | 'other';
export declare function ruleState(view: WeinsteinView | null | undefined): {
  key: 'entry' | 'hold' | 'exit' | 'caution' | 'out' | 'wait';
  label: string;
  hint: string;
};
