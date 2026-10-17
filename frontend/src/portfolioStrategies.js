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
    currentMap.set(c.symbol, (currentMap.get(c.symbol) || 0) + c.weight);
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

/** @typedef {import('./types').PortfolioDiffRow} PortfolioDiffRow */

const ASSET_LABELS = /** @type {Record<string, { name: string; code: string }>} */ ({
  '510300.SS': { name: '沪深300ETF', code: '510300' },
  '513100.SS': { name: '纳指ETF', code: '513100' },
  '518880.SS': { name: '黄金ETF', code: '518880' },
  'BTC-USD': { name: 'BTC', code: '' },
  CASH: { name: '现金', code: '' },
});

/**
 * @param {string} symbol
 * @returns {{ name: string; code: string }}
 */
export function assetLabel(symbol) {
  return ASSET_LABELS[symbol] || { name: symbol, code: '' };
}

/**
 * Formats a ratio with an explicit sign, e.g. 0.0234 -> "+2.34%".
 * @param {number | null | undefined} value
 * @param {number} decimals
 * @returns {string}
 */
export function fmtSignedPct(value, decimals = 2) {
  if (value == null || !Number.isFinite(value)) return '—';
  return (value > 0 ? '+' : '') + (value * 100).toFixed(decimals) + '%';
}

/**
 * Plain-language reading of a unit-NAV drawdown, anchored on the backtest range.
 * @param {number | null | undefined} drawdown
 * @returns {string}
 */
export function drawdownLabel(drawdown) {
  if (drawdown == null || !Number.isFinite(drawdown)) return '—';
  if (drawdown > -0.10) return '正常范围';
  if (drawdown > -0.15) return '回测里出现过，按规则持有';
  return '比回测更深，按规则持有';
}

/**
 * BTC SuperTrend switch from the satellite snapshot; null for other strategies.
 * @param {PortfolioSnapshot | null | undefined} snapshot
 */
export function btcSwitch(snapshot) {
  const values = snapshot?.observation?.values || {};
  if (!('supertrend_on' in values)) return null;
  const latestOn = Boolean(values.supertrend_on);
  const formalOn = Boolean(values.formal_supertrend_on);
  const close = Number(values.btc_close);
  const line = Number(values.supertrend_line);
  const distance = Number.isFinite(close) && close !== 0 && Number.isFinite(line) ? (close - line) / close : null;
  return { latestOn, formalOn, close, line, distance, flipPending: latestOn !== formalOn };
}

const ACTIVE_ORDER_STATUSES = new Set(['PENDING', 'WAITING_OPEN', 'DELAYED']);

/**
 * The one-sentence answer to "do I need to act today?" for the primary account.
 * @param {PortfolioSnapshot | null | undefined} snapshot
 * @param {PortfolioDiffRow[]} [diffRows]
 */
export function buildDailyVerdict(snapshot, diffRows = []) {
  /** @type {Array<{ tone: 'ok' | 'warn' | 'bad'; text: string }>} */
  const chips = [];
  /** @type {Array<{ side: '买入' | '卖出'; symbol: string; name: string; amount: number | null }>} */
  const todo = [];
  if (!snapshot || snapshot.state === 'EMPTY') {
    return { kind: 'empty', verdict: '主策略还没有启用', sub: '纸面账户尚未激活。启用后，这里每天告诉你要不要操作。', chips, todo };
  }
  const dataDate = snapshot.dates?.marketDataDate;
  const dateChip = dataDate ? [{ tone: /** @type {const} */ ('ok'), text: `数据更新至 ${dataDate}` }] : [];
  if (snapshot.state?.startsWith('BLOCKED')) {
    return {
      kind: 'blocked',
      verdict: '数据有问题，先别操作',
      sub: '行情或账本被阻断。修复之前，不要按页面上的数字下单。',
      chips: [{ tone: /** @type {const} */ ('bad'), text: '数据阻塞' }, ...dateChip],
      todo,
    };
  }
  const problems = (snapshot.diagnostics?.length || 0) + (snapshot.operations?.dataQualityEventCount || 0);
  const problemChip = problems ? [{ tone: /** @type {const} */ ('warn'), text: `${problems} 条数据提醒` }] : [];
  const nextCheck = snapshot.dates?.nextCheck;
  const btc = btcSwitch(snapshot);
  const orders = (snapshot.operations?.orders || []).filter(order => order.due || ACTIVE_ORDER_STATUSES.has(order.status));

  if (orders.length) {
    const nav = snapshot.nav?.netNav;
    // sells first (cash for the buys), then larger trades first
    for (const row of [...diffRows].sort((a, b) => (Math.sign(a.delta) - Math.sign(b.delta)) || (Math.abs(b.delta) - Math.abs(a.delta)))) {
      if (row.symbol === 'CASH' || Math.abs(row.delta) < 0.005) continue;
      todo.push({
        side: row.delta > 0 ? '买入' : '卖出',
        symbol: row.symbol,
        name: assetLabel(row.symbol).name,
        amount: nav != null && Number.isFinite(nav) ? Math.abs(row.delta) * nav : null,
      });
    }
    const due = orders.some(order => order.due);
    const when = orders[0].expectedExecutionDate || orders[0].nextAttemptDate;
    return {
      kind: 'rebalance',
      verdict: due ? '今天要调仓' : '有一次调仓等待执行',
      sub: `按目标比例调整${todo.length ? '下面几笔' : '持仓'}。${when ? `计划在 ${when} 执行。` : ''}`,
      chips: [{ tone: /** @type {const} */ ('warn'), text: `${orders.length} 笔待执行` }, ...problemChip, ...dateChip],
      todo,
    };
  }
  if (btc?.flipPending) {
    const action = btc.latestOn ? '买回 BTC' : '卖出 BTC，换成现金';
    return {
      kind: 'btcFlip',
      verdict: '今天不用操作',
      sub: `BTC 日线 ST 已转${btc.latestOn ? '向上' : '向下'}。按规则，${nextCheck || '下次检查'} 检查时${action}。现在不用提前动手。`,
      chips: [{ tone: /** @type {const} */ ('warn'), text: 'BTC 日线已转向' }, ...problemChip, ...dateChip],
      todo,
    };
  }
  return {
    kind: 'calm',
    verdict: '今天不用操作',
    sub: `三组合${btc ? '和 BTC ' : ''}都按规则持有。${nextCheck ? `下次检查是 ${nextCheck}。` : ''}`,
    chips: [{ tone: /** @type {const} */ ('ok'), text: '主策略正常' }, ...problemChip, ...dateChip],
    todo,
  };
}
