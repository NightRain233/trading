/**
 * Portfolio strategy helpers — deterministic business logic covered by Node tests.
 */

import type {
  PortfolioSnapshot,
  PortfolioWeightItem,
  PortfolioPositionItem,
} from './types';

export declare const PANEL_KEYS: readonly [
  'dates',
  'diagnostics',
  'signal',
  'holdings',
  'targets',
  'diff',
  'nav',
  'ledger',
  'next',
];

export declare function stateTone(
  state: PortfolioSnapshot['state']
): { tone: 'positive' | 'neutral' | 'warning' | 'danger' | 'info'; label: string };

export declare function buildAssetRows(
  snapshot: PortfolioSnapshot
): Array<{
  symbol: string;
  sleeve: string;
  currentWeight: number;
  desiredWeight: number;
  delta: number;
  reason: string;
}>;

export declare function fmtDate(dateStr: string | null | undefined): string;
export declare function fmtPct(value: number | null | undefined, decimals?: number): string;
export declare function fmtNum(value: number | null | undefined, decimals?: number): string;

export declare function assetLabel(symbol: string): { name: string; code: string };
export declare function fmtSignedPct(value: number | null | undefined, decimals?: number): string;
export declare function drawdownLabel(drawdown: number | null | undefined): string;

export interface BtcSwitch {
  latestOn: boolean;
  formalOn: boolean;
  close: number;
  line: number;
  distance: number | null;
  flipPending: boolean;
}
export declare function btcSwitch(snapshot: PortfolioSnapshot | null | undefined): BtcSwitch | null;

export interface DailyVerdict {
  kind: 'empty' | 'blocked' | 'rebalance' | 'awaitingBuild' | 'btcFlip' | 'calm';
  verdict: string;
  sub: string;
  chips: Array<{ tone: 'ok' | 'warn' | 'bad'; text: string }>;
  todo: Array<{ side: '买入' | '卖出'; symbol: string; name: string; amount: number | null }>;
}
export declare function buildDailyVerdict(
  snapshot: PortfolioSnapshot | null | undefined,
  diffRows?: import('./types').PortfolioDiffRow[]
): DailyVerdict;
