import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { Candle, PortfolioDiffRow, PortfolioNavPoint, PortfolioSnapshot, PortfolioStrategyItem } from '../types';
import {
  fetchPortfolioNav,
  fetchPortfolioRebalanceDiff,
  fetchPortfolioSnapshot,
  fetchPortfolioStrategies,
  fetchStockData,
  refreshPortfolioStrategy,
} from '../utils';
import {
  assetLabel,
  btcSwitch,
  buildAssetRows,
  buildDailyVerdict,
  drawdownLabel,
  fmtNum,
  fmtPct,
  fmtSignedPct,
} from '../portfolioStrategies.js';

const ASSET_COLORS: Record<string, string> = {
  '518880.SS': 'var(--ui-gold)',
  '510300.SS': 'var(--ui-csi)',
  '513100.SS': 'var(--ui-ndx)',
  'BTC-USD': 'var(--ui-btc)',
  CASH: 'var(--ui-cash)',
};
const ASSET_ORDER = ['518880.SS', '510300.SS', '513100.SS', 'BTC-USD', 'CASH'];

const toneClass = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) || value === 0 ? '' : value > 0 ? 'ui-rise' : 'ui-fall';
const money = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? '—' : Math.round(value).toLocaleString('zh-CN');

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    setWidth(Math.floor(node.getBoundingClientRect().width));
    const observer = new ResizeObserver(entries => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function niceTicks(lo: number, hi: number, count: number) {
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

/** Hover readout shared by the small charts: nearest index to the pointer. */
function useHover(n: number, x: (i: number) => number, width: number) {
  const [index, setIndex] = useState<number | null>(null);
  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const px = ((event.clientX - rect.left) * width) / rect.width;
    let best = 0;
    for (let i = 1; i < n; i++) if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    setIndex(best);
  };
  return { index, onMove, onLeave: () => setIndex(null) };
}

function DrawdownChart({ points }: { points: PortfolioNavPoint[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(width, 280), H = 170, L = 6, R = 44, T = 10, B = 22;
  const n = points.length;
  const lo = Math.min(-0.16, ...points.map(p => p.drawdown - 0.01));
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(n - 1, 1);
  const y = (v: number) => T + (v / lo) * (H - T - B);
  const hover = useHover(n, x, W);
  if (n < 2) return <p className="ui-note">净值记录还不够画图。</p>;
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.drawdown)}`).join('');
  const shown = hover.index ?? n - 1;
  const ticks = [0, -0.05, -0.1, -0.15].filter(v => v >= lo);
  return (
    <div className="ui-chart" ref={ref}>
      <div className="ui-readout">
        {points[shown].valuationDate} · 回撤 <span className="ui-num">{fmtPct(points[shown].drawdown, 1)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img" aria-label="回撤走势">
        <rect x={L} y={y(-0.1)} width={W - L - R} height={Math.max(0, y(lo) - y(-0.1))} fill="var(--ui-sunken)" />
        {ticks.map(v => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--ui-line)" />
            <text x={W - R + 6} y={y(v) + 4}>{(v * 100).toFixed(0)}%</text>
          </g>
        ))}
        <text x={L + 6} y={y(-0.1) + 15}>超过 -10%：回测里也出现过，按规则持有</text>
        <path d={`${line}L${x(n - 1)},${y(0)}L${x(0)},${y(0)}Z`} fill="var(--ui-fall)" opacity={0.16} />
        <path d={line} fill="none" stroke="var(--ui-fall)" strokeWidth={2} strokeLinejoin="round" />
        <circle cx={x(shown)} cy={y(points[shown].drawdown)} r={4} fill="var(--ui-fall)" stroke="var(--ui-surface)" strokeWidth={2} />
        <text x={L} y={H - 4}>{points[0].valuationDate}</text>
        <text x={W - R} y={H - 4} textAnchor="end">{points[n - 1].valuationDate}</text>
        <rect x={0} y={0} width={W} height={H} fill="transparent" onPointerMove={hover.onMove} onPointerLeave={hover.onLeave} />
      </svg>
    </div>
  );
}

/** BTC closes from the quote feed, with the satellite's own ST line as a level. */
function BtcChart({ candles, stLine, stUp }: { candles: Candle[]; stLine: number; stUp: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(width, 260), H = 150, L = 4, R = 54, T = 8, B = 20;
  const bars = candles.slice(-90);
  const n = bars.length;
  const values = [...bars.map(b => b.close), stLine].filter(Number.isFinite);
  const lo = Math.min(...values) * 0.98, hi = Math.max(...values) * 1.02;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(n - 1, 1);
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const hover = useHover(n, x, W);
  if (n < 2) return null;
  const shown = hover.index ?? n - 1;
  const stroke = stUp ? 'var(--ui-rise)' : 'var(--ui-fall)';
  return (
    <div className="ui-chart" ref={ref}>
      <div className="ui-readout">
        {bars[shown].time} · BTC <span className="ui-num">{fmtNum(bars[shown].close, 0)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img" aria-label="BTC 近 90 日收盘价">
        {niceTicks(lo, hi, 3).map(v => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--ui-line)" />
            <text x={W - R + 6} y={y(v) + 4}>{(v / 1000).toFixed(0)}k</text>
          </g>
        ))}
        {Number.isFinite(stLine) && (
          <line x1={L} x2={W - R} y1={y(stLine)} y2={y(stLine)} stroke={stroke} strokeWidth={2} strokeDasharray="4 3" />
        )}
        <path d={bars.map((b, i) => `${i ? 'L' : 'M'}${x(i)},${y(b.close)}`).join('')} fill="none" stroke="var(--ui-ink)" strokeWidth={1.6} />
        <circle cx={x(shown)} cy={y(bars[shown].close)} r={4} fill="var(--ui-ink)" stroke="var(--ui-surface)" strokeWidth={2} />
        <text x={L} y={H - 4}>{bars[0].time}</text>
        <text x={W - R} y={H - 4} textAnchor="end">{bars[n - 1].time}</text>
        <rect x={0} y={0} width={W} height={H} fill="transparent" onPointerMove={hover.onMove} onPointerLeave={hover.onLeave} />
      </svg>
    </div>
  );
}

function BtcPanel({ snapshot, candles }: { snapshot: PortfolioSnapshot; candles: Candle[] }) {
  const btc = btcSwitch(snapshot);
  if (!btc) return null;
  const formalText = btc.formalOn ? '持有 BTC' : 'BTC 仓位为现金';
  return (
    <section className="ui-panel ui-stack" aria-labelledby="h-btc">
      <div className="ui-sec-head">
        <div>
          <h2 className="ui-h2" id="h-btc">BTC 日线 SuperTrend</h2>
          <div className={`ui-big-state ${btc.flipPending ? (btc.latestOn ? 'ui-rise' : 'ui-fall') : btc.latestOn ? 'ui-rise' : 'ui-fall'}`}>
            {btc.flipPending ? `已转${btc.latestOn ? '向上' : '向下'}` : btc.latestOn ? '向上' : '向下'}
          </div>
        </div>
        <span className={`ui-chip ${btc.flipPending ? 'warn' : 'ok'}`}><i />正式开关：{formalText}</span>
      </div>
      {candles.length > 1 && <BtcChart candles={candles} stLine={btc.line} stUp={btc.latestOn} />}
      <div className="ui-legend">
        <span><i style={{ background: 'var(--ui-ink)' }} />BTC 收盘</span>
        <span><i style={{ background: btc.latestOn ? 'var(--ui-rise)' : 'var(--ui-fall)' }} />卫星 ST 线（10, 3）当前位置</span>
      </div>
      <dl className="ui-kv">
        <dt>BTC 收盘</dt><dd className="ui-num">{fmtNum(btc.close, 0)}</dd>
        <dt>ST 线</dt><dd className="ui-num">{fmtNum(btc.line, 0)}</dd>
        <dt>距 ST 线</dt><dd className={`ui-num ${toneClass(btc.distance)}`}>{fmtSignedPct(btc.distance, 1)}</dd>
        <dt>上次 / 下次检查</dt><dd className="ui-num">{snapshot.dates.signalDate ?? '—'} / {snapshot.dates.nextCheck ?? '—'}</dd>
      </dl>
      <p className={`ui-note ${btc.flipPending ? 'warn' : ''}`}>
        {btc.flipPending
          ? `规则只在检查日生效：${snapshot.dates.nextCheck ?? '下次检查'} 检查时${btc.latestOn ? '买回 BTC' : '卖出 BTC，换成现金'}。`
          : btc.latestOn
            ? '价格在 ST 线上方，趋势向上。离 ST 线越近，越要留意转向。'
            : '价格在 ST 线下方，这 7.5% 按规则持有现金。'}
      </p>
    </section>
  );
}

function Holdings({ snapshot }: { snapshot: PortfolioSnapshot }) {
  const rows = buildAssetRows(snapshot)
    .filter(row => row.currentWeight > 0.0005 || row.desiredWeight > 0.0005)
    .sort((a, b) => {
      const ia = ASSET_ORDER.indexOf(a.symbol), ib = ASSET_ORDER.indexOf(b.symbol);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  const values = new Map<string, number>();
  for (const position of snapshot.currentWeights) values.set(position.symbol, (values.get(position.symbol) ?? 0) + position.value);
  return (
    <section className="ui-panel ui-stack" aria-labelledby="h-alloc">
      <div className="ui-sec-head"><h2 className="ui-h2" id="h-alloc">持仓</h2><p>目标比例每 10 个交易日更新</p></div>
      <div className="ui-alloc-bar" role="img" aria-label="当前持仓比例">
        {rows.map(row => (
          <div key={row.symbol} style={{ width: `${row.currentWeight * 100}%`, background: ASSET_COLORS[row.symbol] ?? 'var(--ui-ink-3)' }} />
        ))}
      </div>
      <div>
        {rows.map(row => {
          const label = assetLabel(row.symbol);
          return (
            <div className="ui-alloc-row" key={row.symbol}>
              <span className="ui-swatch" style={{ background: ASSET_COLORS[row.symbol] ?? 'var(--ui-ink-3)' }} />
              <span className="name"><b>{label.name}</b>{label.code && <small>{label.code}</small>}</span>
              <span className="pct ui-num">{fmtPct(row.currentWeight, 1)}</span>
              <span className="tgt ui-num">
                {row.symbol === 'CASH' ? `${money(values.get('CASH'))} 元` : `目标 ${fmtPct(row.desiredWeight, 1)}`}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function PortfolioStrategiesPage() {
  const [strategies, setStrategies] = useState<PortfolioStrategyItem[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, PortfolioSnapshot>>({});
  const [navPoints, setNavPoints] = useState<PortfolioNavPoint[]>([]);
  const [diffRows, setDiffRows] = useState<PortfolioDiffRow[]>([]);
  const [btcCandles, setBtcCandles] = useState<Candle[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const primary = useMemo(() => strategies.find(item => item.isPrimary) ?? null, [strategies]);
  const snapshot = primary ? snapshots[primary.strategyId] ?? null : null;

  const loadPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchPortfolioStrategies();
      setStrategies(list);
      const entries = await Promise.all(list.filter(item => item.paperEnabled).map(async item => {
        try {
          const snap = await fetchPortfolioSnapshot(item.strategyId);
          return snap ? ([item.strategyId, snap] as const) : null;
        } catch {
          return null;
        }
      }));
      setSnapshots(Object.fromEntries(entries.filter((entry): entry is readonly [string, PortfolioSnapshot] => entry !== null)));
    } catch {
      setError('组合数据加载失败，请检查后端服务是否在运行。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadPage(); }, [loadPage]);

  useEffect(() => {
    if (!primary) return;
    let active = true;
    fetchPortfolioNav(primary.strategyId)
      .then(series => { if (active) setNavPoints(series?.points.slice(-250) ?? []); })
      .catch(() => { if (active) setNavPoints([]); });
    fetchPortfolioRebalanceDiff(primary.strategyId)
      .then(diff => { if (active) setDiffRows(diff?.rows ?? []); })
      .catch(() => { if (active) setDiffRows([]); });
    return () => { active = false; };
  }, [primary, snapshot]);

  useEffect(() => {
    if (!btcSwitch(snapshot)) return;
    let active = true;
    fetchStockData('BTC-USD')
      .then(stock => { if (active) setBtcCandles(stock?.candles ?? []); })
      .catch(() => { if (active) setBtcCandles([]); });
    return () => { active = false; };
  }, [snapshot]);

  const handleRefresh = useCallback(async () => {
    if (!primary) return;
    setRefreshing(true);
    setError(null);
    try {
      const next = await refreshPortfolioStrategy(primary.strategyId);
      if (!next) throw new Error('refresh failed');
      setSnapshots(current => ({ ...current, [primary.strategyId]: next }));
    } catch {
      setError('刷新失败，账本没有写入重复的信号或订单。');
    } finally {
      setRefreshing(false);
    }
  }, [primary]);

  if (loading) {
    return <main className="ui-page"><div className="ui-skeleton" /><div className="ui-skeleton" /></main>;
  }

  const verdict = buildDailyVerdict(snapshot, diffRows);
  const nav = snapshot?.nav;
  const comparisons = strategies.filter(item => !item.isPrimary && item.paperEnabled);
  const todayGain = nav?.netNav != null && nav.dailyReturn != null ? (nav.netNav * nav.dailyReturn) / (1 + nav.dailyReturn) : null;
  const orders = snapshot?.operations?.orders ?? [];

  return (
    <main className="ui-page">
      {error && <div className="ui-error" role="alert">{error}</div>}

      <section className="ui-hero" aria-labelledby="verdict">
        <div className="ui-row"><span className="ui-eyebrow">{primary?.displayName ?? '主策略'}</span></div>
        <h1 className="ui-verdict" id="verdict">{verdict.verdict}</h1>
        <p className="ui-verdict-sub">{verdict.sub}</p>
        {verdict.todo.length > 0 && (
          <ul className="ui-todo">
            {verdict.todo.map(row => (
              <li key={row.symbol}>
                <span className={`side ${row.side === '买入' ? 'ui-rise' : 'ui-fall'}`}>{row.side}</span>
                <span>{row.name} <span className="ui-muted">{assetLabel(row.symbol).code}</span></span>
                <span className="ui-num">{row.amount != null ? `约 ${money(row.amount)} 元` : '—'}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="ui-row">
          {verdict.chips.map(chip => <span key={chip.text} className={`ui-chip ${chip.tone}`}><i />{chip.text}</span>)}
        </div>
      </section>

      {snapshot && nav && (
        <section className="ui-stats" aria-label="账户概况">
          <div className="ui-stat"><span>账户净值</span><b className="ui-num">{money(nav.netNav)}</b><small>现金 {money(nav.cash)}</small></div>
          <div className="ui-stat"><span>今天</span><b className={`ui-num ${toneClass(nav.dailyReturn)}`}>{fmtSignedPct(nav.dailyReturn)}</b><small>{todayGain != null ? `${todayGain >= 0 ? '+' : ''}${money(todayGain)} 元` : '—'}</small></div>
          <div className="ui-stat"><span>累计收益</span><b className={`ui-num ${toneClass(nav.cumulativeReturn)}`}>{fmtSignedPct(nav.cumulativeReturn, 1)}</b><small>纸面账户启用以来</small></div>
          <div className="ui-stat"><span>当前回撤</span><b className={`ui-num ${toneClass(nav.drawdown)}`}>{fmtPct(nav.drawdown, 1)}</b><small>{drawdownLabel(nav.drawdown)}</small></div>
        </section>
      )}

      {snapshot && (
        <div className="ui-grid-2">
          <Holdings snapshot={snapshot} />
          <BtcPanel snapshot={snapshot} candles={btcCandles} />
        </div>
      )}

      {navPoints.length > 1 && (
        <section className="ui-panel ui-stack" aria-labelledby="h-dd">
          <div className="ui-sec-head"><h2 className="ui-h2" id="h-dd">回撤走势</h2><p>从前高跌了多少 · 回测里最深一次约 -13%</p></div>
          <DrawdownChart points={navPoints} />
        </section>
      )}

      {snapshot && (
        <details className="ui-details">
          <summary>账本细节 · 订单、日期、数据检查</summary>
          <div className="ui-stack" style={{ marginTop: 12 }}>
            <dl className="ui-kv">
              <dt>行情日期</dt><dd className="ui-num">{snapshot.dates.marketDataDate ?? '—'}</dd>
              <dt>信号日期</dt><dd className="ui-num">{snapshot.dates.signalDate ?? '—'}</dd>
              <dt>下次检查</dt><dd className="ui-num">{snapshot.dates.nextCheck ?? '—'}</dd>
              <dt>账户状态</dt><dd>{snapshot.state}</dd>
              <dt>数据质量事件</dt><dd className="ui-num">{snapshot.operations?.dataQualityEventCount ?? 0}</dd>
            </dl>
            {orders.length > 0 && orders.map(order => (
              <div className="ui-list-row" key={order.orderId}>
                <span>{order.symbol} · {order.side}</span>
                <span className="ui-num">{order.expectedExecutionDate ?? order.nextAttemptDate ?? '—'}</span>
                <span>{order.delayReason || order.status}</span>
              </div>
            ))}
            {snapshot.diagnostics.map((diagnostic, index) => (
              <p className="ui-note warn" key={`${diagnostic.code}-${index}`}>{diagnostic.code}：{diagnostic.message}</p>
            ))}
            <div><button type="button" className="ui-btn" onClick={handleRefresh} disabled={refreshing}><RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />重新计算主策略</button></div>
          </div>
        </details>
      )}

      {comparisons.length > 0 && (
        <details className="ui-details">
          <summary>后台对照账户 · {comparisons.length} 个，只记录不操作</summary>
          <div style={{ marginTop: 8 }}>
            {comparisons.map(item => {
              const snap = snapshots[item.strategyId];
              return (
                <div className="ui-list-row" key={item.strategyId}>
                  <span>{item.displayName}</span>
                  <span className={`ui-num ${toneClass(snap?.nav?.cumulativeReturn)}`}>{fmtSignedPct(snap?.nav?.cumulativeReturn, 1)}</span>
                  <span className={`ui-num ${toneClass(snap?.nav?.drawdown)}`}>{fmtPct(snap?.nav?.drawdown, 1)}</span>
                </div>
              );
            })}
            <p className="ui-muted" style={{ fontSize: 12, margin: '8px 0 0' }}>左列为累计收益，右列为当前回撤。各账户启用日期不同，不能直接比高低。</p>
          </div>
        </details>
      )}
    </main>
  );
}
