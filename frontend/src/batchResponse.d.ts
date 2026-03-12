import type { StockData } from './types';

export type BatchSnapshot = {
  data: Record<string, StockData>;
  updatedAt: string | null;
  stale: boolean;
  refreshTriggered: boolean;
  etag: string | null;
};

export function parseBatchHeaders(headers: { get(name: string): string | null }): Omit<BatchSnapshot, 'data'>;
export function normalizeBatchSnapshot(
  snapshot:
    | Partial<BatchSnapshot>
    | {
        data?: Record<string, unknown> | null;
        updatedAt?: string | null;
        stale?: boolean;
        refreshTriggered?: boolean;
        etag?: string | null;
      }
    | null
    | undefined
): BatchSnapshot;
export function parseBatchResponse(response: Response): Promise<BatchSnapshot>;
