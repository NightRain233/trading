import { useEffect, useMemo, useState } from 'react';
import { Settings2 } from 'lucide-react';
import type { Candle, StockData, WatchlistGroup } from '../types';
import { fetchStockData } from '../utils';
import { signed, stageColor, tone } from '../marketFormat';
import { useWidth } from '../useWidth';
import { Signals, StageChip } from './StageBits';
import { fmtNum } from '../portfolioStrategies.js';
import {
  BB_LABELS,
  MARKET_FILTERS,
  STAGE_NAMES,
  marketReading,
  matchesFilter,
  slopeArrow,
  sortByStrength,
} from '../marketView.js';

const MARKET_BENCHMARKS: Array<[string, string]> = [['000300.SS', 'A 股 · 沪深300'], ['SPY', '美股 · 标普500'], ['BTC-USD', '加密 · BTC']];
const SHOW_KEYS = [['bb', '布林带'], ['vol', '成交量'], ['rs', '相对强度'], ['macd', '周 MACD']] as const;
type ShowKey = typeof SHOW_KEYS[number][0];
type Show = Record<ShowKey, boolean>;

function loadShow(): Show {
  const fallback: Show = { bb: true, vol: true, rs: true, macd: true };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem('market.show') || '{}') };
  } catch {
    return fallback;
  }
}

const displayName = (stock: StockData) => stock.alias || stock.name || stock.symbol;

function niceTicks(lo: number, hi: number, count: number) {
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

const priceLabel = (v: number) => (v >= 1000 ? v.toFixed(0) : v >= 100 ? v.toFixed(1) : v.toFixed(3));

function WeeklyChart({ candles, show }: { candles: Candle[]; show: Show }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const s = candles.slice(-110);
  const n = s.length;
  const W = Math.max(width, 280);
  const narrow = W < 520;
  const PH = narrow ? 210 : 250, SH = 8, VH = 40, RH = 58, MH = 70, GAP = 16, L = 4, R = 54, T = 6;
  const panels: Array<[ShowKey, number]> = [];
  let yy = T + PH + 8;
  const stageY = yy;
  yy += SH;
  if (show.vol) { yy += GAP; panels.push(['vol', yy]); yy += VH; }
  if (show.rs) { yy += GAP; panels.push(['rs', yy]); yy += RH; }
  if (show.macd) { yy += GAP; panels.push(['macd', yy]); yy += MH; }
  const H = yy + 20;
  const cw = (W - L - R) / Math.max(n, 1);
  const x = (i: number) => L + cw * (i + 0.5);
  const lows = s.map(b => Math.min(b.low, show.bb && b.boll_lower ? b.boll_lower : b.low));
  const highs = s.map(b => Math.max(b.high, show.bb && b.boll_upper ? b.boll_upper : b.high));
  const lo = Math.min(...lows) * 0.97, hi = Math.max(...highs) * 1.02;
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * PH;
  const shown = hover ?? n - 1;

  if (n < 2) return <div ref={ref} className="ui-note">周线数据不足。</div>;
  const b = s[shown];
  const prev = shown > 0 ? s[shown - 1] : b;
  const change = b.close / prev.close - 1;
  const path = (key: keyof Candle, yf: (v: number) => number) => {
    const pts = s.map((c, i) => (c[key] != null && Number.isFinite(c[key] as number) ? `${x(i)},${yf(c[key] as number)}` : null)).filter(Boolean);
    return pts.length ? `M${pts.join('L')}` : '';
  };
  const ribbons: Array<{ start: number; end: number; stage: number }> = [];
  s.forEach((c, i) => {
    const st = c.stage ?? 0;
    const last = ribbons[ribbons.length - 1];
    if (last && last.stage === st) last.end = i; else ribbons.push({ start: i, end: i, stage: st });
  });

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const px = ((event.clientX - rect.left) * W) / rect.width;
    setHover(Math.max(0, Math.min(n - 1, Math.round((px - L) / cw - 0.5))));
  };

  return (
    <div className="ui-stack" style={{ gap: 10 }}>
      <div className="ui-readout-bar" aria-live="off">
        <span><em>{b.time.slice(5)} 当周</em>{b.stage ? <span className={`ui-chip s${b.stage}`} style={{ padding: '1px 8px' }}><i />{STAGE_NAMES[b.stage as 1 | 2 | 3 | 4]}</span> : null}</span>
        <span><em>收盘</em><span className={`ui-num ${tone(change)}`}>{priceLabel(b.close)} {signed(change)}</span></span>
        <span><em>30 周线</em><span className="ui-num" style={{ color: 'var(--ui-accent)' }}>{b.ma30 ? priceLabel(b.ma30) : '—'}</span></span>
        {show.bb && <span><em>布林</em><span className="ui-num">{b.boll_lower && b.boll_upper ? `${priceLabel(b.boll_lower)}–${priceLabel(b.boll_upper)}` : '—'}</span></span>}
        {show.rs && <span><em>相对强度</em><span className={`ui-num ${tone(b.rs26)}`}>{signed(b.rs26)}</span></span>}
        {show.macd && <span><em>MACD 柱</em><span className={`ui-num ${tone(b.macd_hist)}`}>{b.macd_hist != null ? b.macd_hist.toFixed(3) : '—'}</span></span>}
      </div>
      <div className="ui-chart" ref={ref}>
        <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img" aria-label="周线图">
          {niceTicks(lo, hi, 4).map(v => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--ui-line)" />
              <text x={W - R + 6} y={y(v) + 4}>{priceLabel(v)}</text>
            </g>
          ))}
          {show.bb && (() => {
            const pts = s.map((c, i) => (c.boll_upper && c.boll_lower ? i : -1)).filter(i => i >= 0);
            if (pts.length < 2) return null;
            const up = pts.map(i => `${x(i)},${y(s[i].boll_upper!)}`);
            const down = pts.map(i => `${x(i)},${y(s[i].boll_lower!)}`);
            return (
              <g>
                <path d={`M${up.join('L')}L${[...down].reverse().join('L')}Z`} fill="var(--ui-ink-3)" opacity={0.09} />
                <path d={`M${up.join('L')}`} fill="none" stroke="var(--ui-ink-3)" strokeWidth={0.8} opacity={0.7} />
                <path d={`M${down.join('L')}`} fill="none" stroke="var(--ui-ink-3)" strokeWidth={0.8} opacity={0.7} />
              </g>
            );
          })()}
          {s.map((c, i) => {
            const color = c.close >= c.open ? 'var(--ui-rise)' : 'var(--ui-fall)';
            const top = y(Math.max(c.open, c.close));
            const h = Math.max(1, Math.abs(y(c.open) - y(c.close)));
            return (
              <g key={c.time}>
                <line x1={x(i)} x2={x(i)} y1={y(c.high)} y2={y(c.low)} stroke={color} />
                <rect x={x(i) - cw * 0.34} y={top} width={cw * 0.68} height={h} rx={1}
                  fill={c.close >= c.open ? 'none' : color} stroke={color} />
              </g>
            );
          })}
          <path d={path('boll_mid', y)} fill="none" stroke="var(--ui-ink-3)" strokeWidth={1.2} strokeDasharray="4 3" />
          <path d={path('ma30', y)} fill="none" stroke="var(--ui-accent)" strokeWidth={2.2} />
          {ribbons.filter(r => r.stage).map(r => (
            <rect key={r.start} x={L + cw * r.start} y={stageY} width={cw * (r.end - r.start + 1) - 1} height={SH} rx={2}
              fill={stageColor(r.stage)} opacity={r.stage === 1 ? 0.5 : 0.8} />
          ))}
          {panels.map(([kind, y0]) => {
            if (kind === 'vol') {
              const vmax = Math.max(...s.map(c => c.volume || 0)) || 1;
              const avg = (i: number) => {
                const prior = s.slice(Math.max(0, i - 10), i);
                return prior.length ? prior.reduce((sum, c) => sum + (c.volume || 0), 0) / prior.length : 0;
              };
              return (
                <g key={kind}>
                  <text x={L} y={y0 + 10}>成交量（深色 = 量比 &gt; 1.8）</text>
                  {s.map((c, i) => {
                    const h = ((c.volume || 0) / vmax) * VH;
                    const strong = avg(i) > 0 && (c.volume || 0) / avg(i) > 1.8;
                    return <rect key={c.time} x={x(i) - cw * 0.34} y={y0 + VH - h} width={cw * 0.68} height={h}
                      fill={c.close >= c.open ? 'var(--ui-rise)' : 'var(--ui-fall)'} opacity={strong ? 0.85 : 0.3} />;
                  })}
                </g>
              );
            }
            if (kind === 'rs') {
              const values = s.map(c => c.rs26 ?? 0);
              const rlo = Math.min(...values, -0.05), rhi = Math.max(...values, 0.05);
              const ry = (v: number) => y0 + ((rhi - v) / (rhi - rlo)) * RH;
              const pts = s.map((c, i) => `${x(i)},${ry(c.rs26 ?? 0)}`);
              const hasRs = s.some(c => c.rs26 != null);
              return (
                <g key={kind}>
                  <text x={L} y={y0 + 10}>{hasRs ? '相对强度（26 周，对比大盘）' : '相对强度：这个品种没有对比基准'}</text>
                  <line x1={L} x2={W - R} y1={ry(0)} y2={ry(0)} stroke="var(--ui-ink-3)" strokeDasharray="2 3" />
                  <text x={W - R + 6} y={ry(0) + 4}>0</text>
                  {hasRs && <path d={`M${pts.join('L')}L${x(n - 1)},${ry(0)}L${x(0)},${ry(0)}Z`} fill="var(--ui-accent)" opacity={0.1} />}
                  {hasRs && <path d={`M${pts.join('L')}`} fill="none" stroke="var(--ui-accent)" strokeWidth={1.8} />}
                </g>
              );
            }
            const values = s.flatMap(c => [c.macd_dif ?? 0, c.macd_dea ?? 0, c.macd_hist ?? 0]).map(Math.abs);
            const m = Math.max(...values) || 1;
            const my = (v: number) => y0 + MH / 2 - (v / m) * (MH / 2);
            return (
              <g key={kind}>
                <text x={L} y={y0 + 10}>周线 MACD（实线 DIF，虚线 DEA）</text>
                <line x1={L} x2={W - R} y1={my(0)} y2={my(0)} stroke="var(--ui-line)" />
                {s.map((c, i) => {
                  const v = c.macd_hist ?? 0;
                  return <rect key={c.time} x={x(i) - cw * 0.3} y={Math.min(my(0), my(v))} width={cw * 0.6}
                    height={Math.max(1, Math.abs(my(v) - my(0)))} fill={v >= 0 ? 'var(--ui-rise)' : 'var(--ui-fall)'} opacity={0.45} />;
                })}
                <path d={path('macd_dif', my)} fill="none" stroke="var(--ui-ink)" strokeWidth={1.3} />
                <path d={path('macd_dea', my)} fill="none" stroke="var(--ui-ink-3)" strokeWidth={1.3} strokeDasharray="4 3" />
              </g>
            );
          })}
          {[0, Math.floor(n / 2), n - 1].map(i => (
            <text key={i} x={x(i)} y={H - 4} textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>{s[i].time.slice(0, 7)}</text>
          ))}
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - 20} stroke="var(--ui-ink-3)" strokeDasharray="3 3" />}
          <rect x={0} y={0} width={W} height={H} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      </div>
    </div>
  );
}

function DetailPanel({ stock, show, setShow, onClose, open }: {
  stock: StockData; show: Show; setShow: (next: Show) => void; onClose: () => void; open: boolean;
}) {
  const [full, setFull] = useState<{ symbol: string; data: StockData | null } | null>(null);
  useEffect(() => {
    let active = true;
    fetchStockData(stock.symbol, { chartOnly: true })
      .then(data => { if (active) setFull({ symbol: stock.symbol, data }); })
      .catch(() => { if (active) setFull({ symbol: stock.symbol, data: null }); });
    return () => { active = false; };
  }, [stock.symbol]);
  const view = stock.weinstein;
  const loaded = full?.symbol === stock.symbol ? full.data : undefined;
  const toggle = (key: ShowKey) => {
    const next = { ...show, [key]: !show[key] };
    try { localStorage.setItem('market.show', JSON.stringify(next)); } catch { /* per-viewer preference only */ }
    setShow(next);
  };
  return (
    <section className={`ui-panel ui-stack ui-detail ${open ? 'sheet-open' : ''}`} aria-live="polite">
      <button type="button" className="ui-back" onClick={onClose}>‹ 返回列表</button>
      <div className="ui-sec-head">
        <div>
          <h2 className="ui-h2" style={{ fontSize: 20 }}>{displayName(stock)} {displayName(stock) !== stock.symbol && <span className="ui-num ui-muted" style={{ fontSize: 14, fontWeight: 400 }}>{stock.symbol}</span>}</h2>
          <div style={{ marginTop: 6 }}><StageChip view={view} /></div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="ui-num" style={{ fontSize: 22 }}>{fmtNum(stock.price, stock.price >= 100 ? 2 : 3)}</div>
          <div className={`ui-num ${tone(stock.changePercent)}`} style={{ fontSize: 13 }}>今日 {stock.changePercent > 0 ? '+' : ''}{fmtNum(stock.changePercent, 2)}%</div>
        </div>
      </div>
      <div className="ui-toggles" role="group" aria-label="图上显示">
        {SHOW_KEYS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={show[key]} onClick={() => toggle(key)}>{label}</button>
        ))}
      </div>
      {loaded === undefined ? <div className="ui-skeleton" style={{ height: 320 }} />
        : loaded?.weekly_candles?.length ? <WeeklyChart candles={loaded.weekly_candles} show={show} />
          : <p className="ui-note">周线数据加载失败。</p>}
      <div className="ui-legend">
        <span><i style={{ background: 'var(--ui-accent)' }} />30 周线</span>
        <span><i style={{ background: 'var(--ui-ink-3)' }} />20 周线（布林中轨）</span>
        <span>阶段条：
          {[1, 2, 3, 4].map(st => <i key={st} style={{ background: stageColor(st), height: 8, width: 10, marginLeft: 4, opacity: 0.8 }} />)}
          &nbsp;一 二 三 四
        </span>
      </div>
      {view && (
        <dl className="ui-kv">
          <dt>30 周线（止损参考）</dt><dd className="ui-num">{view.ma30 ? priceLabel(view.ma30) : '—'}，距离 {signed(view.ma30Distance)}</dd>
          <dt>当前阶段已持续</dt><dd className="ui-num">{view.weeksInStage} 周</dd>
          <dt>相对强度（26 周）</dt><dd className={`ui-num ${tone(view.rs26)}`}>{view.rsBenchmark ? `${signed(view.rs26)}，对比 ${view.rsBenchmark}` : '无对比基准'}</dd>
          <dt>布林带</dt><dd>{BB_LABELS[view.bbState]}</dd>
          <dt>本周量比</dt><dd className="ui-num">{view.volumeRatio != null ? view.volumeRatio.toFixed(1) : '—'}</dd>
        </dl>
      )}
      <p className="ui-muted" style={{ fontSize: 12, margin: 0 }}>按最新周线计算，包含本周尚未收盘的数据。回测显示这些规则在 A 股上跑不赢持有，只作看盘参考。</p>
    </section>
  );
}

interface MarketPageProps {
  groups: WatchlistGroup[];
  updatedAt?: string | null;
  onManage: () => void;
}

export function MarketPage({ groups, updatedAt, onManage }: MarketPageProps) {
  const [groupId, setGroupId] = useState('all');
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [show, setShow] = useState<Show>(loadShow);

  const allStocks = useMemo(() => {
    const seen = new Map<string, StockData>();
    groups.forEach(group => group.stocks?.forEach(stock => { if (!seen.has(stock.symbol)) seen.set(stock.symbol, stock); }));
    return seen;
  }, [groups]);
  const rows = useMemo(() => {
    const pool = groupId === 'all'
      ? [...allStocks.values()]
      : (groups.find(group => group.id === groupId)?.stocks ?? []);
    return sortByStrength(pool.filter(stock => matchesFilter(stock, filter)));
  }, [allStocks, groups, groupId, filter]);
  const current = (selected && allStocks.get(selected)) || rows[0] || null;
  const loading = allStocks.size === 0 || [...allStocks.values()].every(stock => stock._loading);

  return (
    <main className="ui-page">
      <section className="ui-hero">
        <div className="ui-row" style={{ justifyContent: 'space-between' }}>
          <span className="ui-eyebrow">大盘环境 · 周线{updatedAt ? ` · 行情更新至 ${updatedAt}` : ''}</span>
          <button type="button" className="ui-btn" onClick={onManage}><Settings2 size={14} />管理自选</button>
        </div>
        <div className="ui-mkt">
          {MARKET_BENCHMARKS.map(([symbol, label]) => {
            const stock = allStocks.get(symbol);
            return (
              <button type="button" className="ui-panel ui-mkt-card" key={symbol} disabled={!stock}
                aria-pressed={current?.symbol === symbol}
                onClick={() => { setGroupId('all'); setFilter('all'); setSelected(symbol); setSheetOpen(true); }}>
                <h3>{label} <StageChip view={stock?.weinstein} compact /></h3>
                <p>{stock ? marketReading(stock.weinstein) : '自选里没有这个品种'}</p>
                {stock?.weinstein && (
                  <p className="ui-muted">距 30 周线 <span className={`ui-num ${tone(stock.weinstein.ma30Distance)}`}>{signed(stock.weinstein.ma30Distance)}</span> {slopeArrow(stock.weinstein.ma30Slope)}{stock.weeklyMacdStatus ? ` · 周线 MACD ${stock.weeklyMacdStatus.replace('周线', '')}` : ''}</p>
                )}
              </button>
            );
          })}
        </div>
      </section>

      <div className="ui-filters">
        <div className="ui-seg" role="group" aria-label="自选分组">
          <button type="button" aria-pressed={groupId === 'all'} onClick={() => setGroupId('all')}>全部</button>
          {groups.map(group => (
            <button key={group.id} type="button" aria-pressed={groupId === group.id} onClick={() => setGroupId(group.id)}>{group.name}</button>
          ))}
        </div>
        <div className="ui-seg" role="group" aria-label="筛选">
          {MARKET_FILTERS.map(([key, label]) => (
            <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>
          ))}
        </div>
      </div>

      <div className="ui-split">
        <section className="ui-panel" aria-label="自选列表" style={{ padding: '14px 18px' }}>
          <p className="ui-muted" style={{ fontSize: 12, margin: '0 0 8px' }}>按相对强度从强到弱。不同市场对比的基准不同，跨市场排序只作参考。</p>
          <div className="ui-tbl-wrap">
            <table className="ui-watch">
              <thead>
                <tr><th>名称</th><th>阶段</th><th className="r">距 30 周线</th><th className="r hide-sm">相对强度</th><th className="hide-sm">信号</th></tr>
              </thead>
              <tbody>
                {rows.map(stock => {
                  const view = stock.weinstein;
                  const rs = view?.rs26 ?? null;
                  const barWidth = rs == null ? 0 : Math.min(Math.abs(rs) / 0.3, 1) * 23;
                  return (
                    <tr key={stock.symbol} tabIndex={0} aria-selected={current?.symbol === stock.symbol}
                      onClick={() => { setSelected(stock.symbol); setSheetOpen(true); }}
                      onKeyDown={event => { if (event.key === 'Enter') { setSelected(stock.symbol); setSheetOpen(true); } }}>
                      <td className="nm">
                        <b>{displayName(stock)}</b>
                        <small className="ui-num">{displayName(stock) === stock.symbol ? '' : `${stock.symbol} · `}今日 <span className={tone(stock.changePercent)}>{stock._loading ? '…' : `${stock.changePercent > 0 ? '+' : ''}${fmtNum(stock.changePercent, 2)}%`}</span></small>
                      </td>
                      <td><StageChip view={view} compact /></td>
                      <td className={`r ui-num ${tone(view?.ma30Distance)}`}>{signed(view?.ma30Distance)} <span className="ui-muted">{slopeArrow(view?.ma30Slope)}</span></td>
                      <td className="r hide-sm ui-num">
                        {rs != null && <span className="ui-rsbar"><i style={{ background: rs >= 0 ? 'var(--ui-rise)' : 'var(--ui-fall)', [rs >= 0 ? 'left' : 'right']: 23, width: barWidth }} /></span>}
                        {signed(rs, 0)}
                      </td>
                      <td className="hide-sm"><Signals view={view} /></td>
                    </tr>
                  );
                })}
                {!rows.length && (
                  <tr><td colSpan={5} className="ui-muted">{loading ? '行情加载中…' : '这个筛选下暂时没有品种。'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
        {current && <DetailPanel stock={current} show={show} setShow={setShow} open={sheetOpen} onClose={() => setSheetOpen(false)} />}
      </div>
    </main>
  );
}
