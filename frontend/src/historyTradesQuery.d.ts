import type { HistorySupertrendExitMode } from './types';

export const DEFAULT_HISTORY_EXIT_MODE: HistorySupertrendExitMode;

export function buildHistoryTradesQuery(params: {
  symbol: string;
  strategy: string;
  exitMode?: HistorySupertrendExitMode;
  start?: string;
  end?: string;
  minAdxForEntry?: number | null;
  weeklyFilter?: boolean;
}): URLSearchParams;
