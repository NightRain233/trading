// @ts-check
/**
 * Portfolio strategy helpers — deterministic business logic covered by Node tests.
 * Keep presentation mapping outside React components.
 */

/** @typedef {import('./types').PortfolioSnapshot} PortfolioSnapshot */
/** @typedef {import('./types').PortfolioWeightItem} PortfolioWeightItem */
/** @typedef {import('./types').PortfolioPositionItem} PortfolioPositionItem */

export const PANEL_KEYS = /** @type {const} */ ([
  'dates',
  'diagnostics',
  'signal',
  'holdings',
  'targets',
  'diff',
  'nav',
  'ledger',
  'next',
]);

/**
 * @param {PortfolioSnapshot['state']} state
 * @returns {{ tone: 'positive' | 'neutral' | 'warning' | 'danger' | 'info', label: string }}
 */
export function stateTone(state) {
  switch (state) {
    case 'READY':
    case 'NOT_DUE':
      return { tone: 'positive', label: state === 'READY' ? '就绪' : '未到调仓日' };
    case 'BOOTSTRAPPED':
      return { tone: 'info', label: '已初始化' };
    case 'PENDING_EXECUTION':
      return { tone: 'warning', label: '待执行' };
    case 'BLOCKED':
      return { tone: 'danger', label: '数据阻塞' };
    case 'EMPTY':
      return { tone: 'neutral', label: '空' };
    default:
      if (state?.startsWith('BLOCKED')) {
        return { tone: 'danger', label: state };
      }
      return { tone: 'neutral', label: state || '未知' };
  }
}

/**
 * Ordered list of asset rows for the expanded asset table.
 * @param {PortfolioSnapshot} snapshot
 * @returns {Array<{ symbol: string; sleeve: string; currentWeight: number; desiredWeight: number; delta: number; reason: string }>}
 */
export function buildAssetRows(snapshot) {
  const currentMap = new Map();
  const desiredMap = new Map();
  const reasonMap = new Map();
  const sleeveMap = new Map();

  for (const c of (snapshot.currentWeights || [])) {
    currentMap.set(c.symbol, c.weight);
  }
  for (const d of (snapshot.desiredWeights || [])) {
    desiredMap.set(d.symbol, d.weight);
    reasonMap.set(d.symbol, d.reason);
    sleeveMap.set(d.symbol, d.sleeve);
  }

  const allSymbols = new Set([...currentMap.keys(), ...desiredMap.keys()]);
  const rows = [];
  for (const symbol of allSymbols) {
    const cw = currentMap.get(symbol) ?? 0;
    const dw = desiredMap.get(symbol) ?? 0;
    rows.push({
      symbol,
      sleeve: sleeveMap.get(symbol) || '',
      currentWeight: cw,
      desiredWeight: dw,
      delta: dw - cw,
      reason: reasonMap.get(symbol) || '',
    });
  }
  rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  return rows;
}

/**
 * @param {string | null | undefined} dateStr
 * @returns {string}
 */
export function fmtDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch {
    return dateStr;
  }
}

/**
 * @param {number | null | undefined} value
 * @param {number} decimals
 * @returns {string}
 */
export function fmtPct(value, decimals = 2) {
  if (value == null || !Number.isFinite(value)) return '—';
  return (value * 100).toFixed(decimals) + '%';
}

/**
 * @param {number | null | undefined} value
 * @param {number} decimals
 * @returns {string}
 */
export function fmtNum(value, decimals = 2) {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toFixed(decimals);
}
