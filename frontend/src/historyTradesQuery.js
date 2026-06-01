export const DEFAULT_HISTORY_EXIT_MODE = 'close_only';

export function buildHistoryTradesQuery(params) {
  const query = new URLSearchParams({
    symbol: params.symbol.trim().toUpperCase(),
    strategy: params.strategy,
    exit_mode: params.exitMode || DEFAULT_HISTORY_EXIT_MODE,
  });
  if (params.start) query.set('start', params.start);
  if (params.end) query.set('end', params.end);
  if (params.minAdxForEntry != null && Number.isFinite(params.minAdxForEntry)) {
    query.set('min_adx_for_entry', String(params.minAdxForEntry));
  }
  if (params.weeklyFilter) query.set('weekly_filter', 'true');
  return query;
}
