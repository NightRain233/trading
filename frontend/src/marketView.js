// @ts-check
/**
 * Watchlist market view helpers — filtering, sorting and plain-language labels
 * for the Weinstein fields. Pure functions, covered by Node tests.
 */

/** @typedef {import('./types').StockData} StockData */
/** @typedef {import('./types').WeinsteinView} WeinsteinView */

export const STAGE_NAMES = /** @type {const} */ ({ 1: '第一阶段', 2: '第二阶段', 3: '第三阶段', 4: '第四阶段' });
export const STAGE_HINTS = /** @type {const} */ ({ 1: '筑底', 2: '上涨', 3: '做顶', 4: '下跌' });

export const BB_LABELS = /** @type {const} */ ({
  none: '—',
  squeeze: '收窄中',
  squeeze_breakout: '收窄后突破',
  above_upper: '上轨之上',
});

export const MARKET_FILTERS = /** @type {const} */ ([
  ['all', '全部'],
  ['s2', '第二阶段'],
  ['bb', '布林收窄/突破'],
  ['below', '跌破 30 周线'],
]);

/**
 * @param {StockData} stock
 * @param {string} filter
 */
export function matchesFilter(stock, filter) {
  const view = stock.weinstein;
  if (filter === 'all') return true;
  if (!view) return false;
  if (filter === 's2') return view.stage === 2;
  if (filter === 'bb') return view.bbState !== 'none';
  if (filter === 'below') return view.ma30Distance != null && view.ma30Distance < 0;
  return true;
}

/**
 * Stronger relative strength first; rows without data sink to the bottom.
 * @param {StockData[]} stocks
 */
export function sortByStrength(stocks) {
  const score = (/** @type {StockData} */ s) => {
    const rs = s.weinstein?.rs26;
    return rs == null || !Number.isFinite(rs) ? -Infinity : rs;
  };
  return [...stocks].sort((a, b) => score(b) - score(a) || a.symbol.localeCompare(b.symbol));
}

/**
 * Direction arrow for the 30-week average's 4-week change.
 * @param {number | null | undefined} slope
 */
export function slopeArrow(slope) {
  if (slope == null || !Number.isFinite(slope)) return '';
  if (slope > 0.004) return '↗';
  if (slope < -0.004) return '↘';
  return '→';
}

/**
 * One-line reading of the market's stage for the top strip.
 * @param {WeinsteinView | null | undefined} view
 */
export function marketReading(view) {
  if (!view) return '数据不足';
  switch (view.stage) {
    case 2: return '上涨阶段，可以找比它强的候选';
    case 3: return '涨势松动，新仓要谨慎';
    case 4: return '下跌阶段，只看不买';
    default: return '筑底阶段，等待站稳 30 周线';
  }
}
