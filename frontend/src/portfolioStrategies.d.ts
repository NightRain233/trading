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
