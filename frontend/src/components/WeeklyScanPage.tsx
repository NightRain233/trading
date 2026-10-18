import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { WatchlistGroup, WeinsteinScanItem } from '../types';
import { fetchWeinsteinScan } from '../utils';
import { cached, invalidate, peek } from '../swrCache.js';
import { STAGE_NAMES, marketOf, ruleState } from '../marketView.js';
import { signed, stageColor, tone } from '../marketFormat';
import { useWidth } from '../useWidth';
import { Signals, StageChip } from './StageBits';

const SCAN_KEY = 'weinstein-scan';
type Market = 'us' | 'crypto' | 'cn' | 'other';
const MARKETS: Array<[Market, string]> = [['us', '美股'], ['crypto', '加密'], ['cn', 'A 股 · 港股'], ['other', '其他']];
const MARKET_NOTES: Record<Market, string> = {
  us: '学习重点。回测里温斯坦规则在美股指数上能明显降低回撤，可以照规则做纸面练习。',
  crypto: 'BTC 主仓位已经由日线 SuperTrend 管理，这里只作周线参考。',
  cn: '只看状态，不照着操作：回测里 A 股所有择时规则都跑输一直持有。',
  other: '商品等品种没有对比基准，只看阶段。',
};
const RULE_ORDER = ['entry', 'exit', 'caution', 'hold', 'wait', 'out'];
const RULE_CHIP: Record<string, string> = { entry: 's2', hold: 'ok', exit: 's4', caution: 'warn', out: 's1', wait: 's1' };

function MiniStageChart({ item }: { item: WeinsteinScanItem }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const h = item.history;
  const n = h.length;
  const W = Math.max(width, 200), PH = 84, RB = 6, T = 4;
  const H = T + PH + 4 + RB;
  const values = h.flatMap(p => [p.close, p.ma30 ?? p.close]);
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = (i: number) => (i * W) / Math.max(n - 1, 1);
  const y = (v: number) => T + ((hi - v) / (hi - lo || 1)) * PH;
  if (n < 2) return null;
  const ma = h.map((p, i) => (p.ma30 != null ? `${x(i)},${y(p.ma30)}` : null)).filter(Boolean);
  const step = W / Math.max(n - 1, 1);
  const shown = hover ?? n - 1;
  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
    const px = ((event.clientX - rect.left) * W) / rect.width;
    setHover(Math.max(0, Math.min(n - 1, Math.round(px / step))));
  };
  return (
    <div className="ui-chart" ref={ref}>
      <div className="ui-readout" style={{ fontSize: 11.5 }}>
        <span className="ui-num">{h[shown].time}</span> · 收盘 <span className="ui-num">{h[shown].close.toFixed(h[shown].close >= 100 ? 1 : 3)}</span>
        {h[shown].stage ? <> · <span style={{ color: stageColor(h[shown].stage) }}>{STAGE_NAMES[h[shown].stage!]}</span></> : null}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} height={H} role="img" aria-label={`${item.symbol} 近 ${n} 周收盘与 30 周线`}>
        {ma.length > 1 && <path d={`M${ma.join('L')}`} fill="none" stroke="var(--ui-accent)" strokeWidth={1.6} />}
        <path d={h.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.close)}`).join('')} fill="none" stroke="var(--ui-ink)" strokeWidth={1.4} strokeLinejoin="round" />
        {h.map((p, i) => (
          <rect key={p.time} x={x(i) - step / 2} y={T + PH + 4} width={Math.max(1, step - 0.5)} height={RB} fill={stageColor(p.stage)} opacity={p.stage ? 0.85 : 0.2} />
        ))}
        <line x1={x(shown)} x2={x(shown)} y1={T} y2={T + PH} stroke="var(--ui-ink-3)" strokeDasharray="2 3" />
        <circle cx={x(shown)} cy={y(h[shown].close)} r={3} fill="var(--ui-ink)" stroke="var(--ui-surface)" strokeWidth={1.5} />
        <rect x={0} y={0} width={W} height={H} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
    </div>
  );
}

function ScanCard({ item, name, statusOnly }: { item: WeinsteinScanItem; name: string; statusOnly: boolean }) {
  const rule = ruleState(item);
  return (
    <article className="ui-panel ui-scan-card">
      <header className="ui-scan-head">
        <div style={{ minWidth: 0 }}>
          <b>{name}</b>
          {name !== item.symbol && <small className="ui-num">{item.symbol}</small>}
        </div>
        <StageChip view={item} compact />
      </header>
      {!statusOnly && <div className="ui-row" style={{ gap: 6 }}><span className={`ui-chip ${RULE_CHIP[rule.key]}`}><i />{rule.label}</span><Signals view={item} /></div>}
      {statusOnly && <Signals view={item} />}
      <MiniStageChart item={item} />
      <dl className="ui-scan-nums">
        <div><dt>距 30 周线</dt><dd className={`ui-num ${tone(item.ma30Distance)}`}>{signed(item.ma30Distance)}</dd></div>
        <div><dt>本阶段</dt><dd className="ui-num">{item.weeksInStage} 周</dd></div>
        <div><dt>相对强度</dt><dd className={`ui-num ${tone(item.rs26)}`}>{item.rsBenchmark ? signed(item.rs26, 0) : '—'}</dd></div>
      </dl>
      {!statusOnly && <p className="ui-muted" style={{ margin: 0, fontSize: 12.5 }}>{rule.hint}</p>}
    </article>
  );
}

export function WeeklyScanPage({ groups }: { groups: WatchlistGroup[] }) {
  const [items, setItems] = useState<WeinsteinScanItem[] | null>(() => peek<WeinsteinScanItem[]>(SCAN_KEY) ?? null);
  const [error, setError] = useState<string | null>(null);
  const [market, setMarket] = useState<Market>('us');
  const [loading, setLoading] = useState(() => peek(SCAN_KEY) === undefined);

  const fetchItems = useCallback(() => cached(SCAN_KEY, fetchWeinsteinScan, 5 * 60_000)
    .then(next => { setItems(next); setError(null); })
    .catch(() => setError('扫描失败，稍后再试。'))
    .finally(() => setLoading(false)), []);
  useEffect(() => { fetchItems(); }, [fetchItems]);
  const load = () => { setLoading(true); invalidate(SCAN_KEY); fetchItems(); };

  const names = useMemo(() => {
    const map = new Map<string, string>();
    groups.forEach(group => group.stocks?.forEach(stock => map.set(stock.symbol.toUpperCase(), stock.alias || stock.name || stock.symbol)));
    return map;
  }, [groups]);
  const nameOf = (symbol: string) => names.get(symbol) || symbol;

  const byMarket = useMemo(() => {
    const out: Record<Market, WeinsteinScanItem[]> = { us: [], crypto: [], cn: [], other: [] };
    (items ?? []).forEach(item => out[marketOf(item.symbol)].push(item));
    Object.values(out).forEach(list => list.sort((a, b) =>
      RULE_ORDER.indexOf(ruleState(a).key) - RULE_ORDER.indexOf(ruleState(b).key) || (b.rs26 ?? -9) - (a.rs26 ?? -9)));
    return out;
  }, [items]);
  const changes = (items ?? []).filter(item => item.previousStage != null && item.previousStage !== item.stage);
  const spy = items?.find(item => item.symbol === 'SPY');
  const qqq = items?.find(item => item.symbol === 'QQQ');
  const weekLabel = items?.[0]?.weekLabel;
  const headline = spy
    ? spy.stage === 2 ? '美股大盘在上涨阶段' : spy.stage === 4 ? '美股大盘在下跌阶段' : spy.stage === 3 ? '美股大盘涨势松动' : '美股大盘在筑底'
    : '周线扫描';
  const visible = byMarket[market];

  return (
    <main className="ui-page">
      <section className="ui-hero">
        <div className="ui-row" style={{ justifyContent: 'space-between' }}>
          <span className="ui-eyebrow">周线扫描 · 周末复盘{weekLabel ? ` · 最新一周 ${weekLabel}` : ''}</span>
          <button type="button" className="ui-btn" onClick={load} disabled={loading}><RefreshCw size={14} />{loading ? '扫描中' : '重新扫描'}</button>
        </div>
        <h1 className="ui-verdict">{headline}</h1>
        <p className="ui-verdict-sub">
          {spy && <>标普500 {STAGE_NAMES[spy.stage]}，距 30 周线 {signed(spy.ma30Distance)}{qqq ? `；纳指100 ${STAGE_NAMES[qqq.stage]}，距 ${signed(qqq.ma30Distance)}` : ''}。</>}
          这是练习用的纸面观察，不影响主策略。
        </p>
      </section>

      {error && <p className="ui-error">{error}</p>}
      {items === null && !error && <div className="ui-skeleton" />}

      {items && (
        <section className="ui-panel ui-stack" aria-labelledby="h-chg">
          <div className="ui-sec-head"><h2 className="ui-h2" id="h-chg">本周换阶段</h2><p>和上一周相比</p></div>
          {changes.length === 0 ? <p className="ui-muted" style={{ margin: 0 }}>本周没有品种换阶段。</p> : (
            <ul className="ui-change-list">
              {changes.map(item => (
                <li key={item.symbol}>
                  <span><b>{nameOf(item.symbol)}</b> <small className="ui-muted">{marketOf(item.symbol) === 'cn' ? '只看状态' : ruleState(item).label}</small></span>
                  <span className="ui-row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                    <StageChip view={{ stage: item.previousStage! }} compact /><span className="ui-muted">→</span><StageChip view={item} compact />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {items && (
        <details className="ui-details">
          <summary>温斯坦规则 · 我按什么判断</summary>
          <dl className="ui-kv" style={{ marginTop: 12, gridTemplateColumns: 'auto minmax(0, 1fr)' }}>
            <dt>买入</dt><dd style={{ textAlign: 'left' }}>周收盘站上 30 周线，30 周线向上，最好放量，且 26 周相对强度为正。只在刚进第二阶段的前 4 周算"新进"。</dd>
            <dt>卖出</dt><dd style={{ textAlign: 'left' }}>周收盘跌破 30 周线就走，不等反弹。</dd>
            <dt>阶段</dt><dd style={{ textAlign: 'left' }}>一 筑底 · 二 上涨 · 三 做顶 · 四 下跌。30 周线 4 周变化不到 0.4% 算走平。</dd>
            <dt>数据</dt><dd style={{ textAlign: 'left' }}>最新一周可能还没收盘，周五收盘后的结果才算数。</dd>
          </dl>
        </details>
      )}

      {items && (
        <section className="ui-stack" aria-label="逐个品种">
          <div className="ui-seg" role="group" aria-label="市场" style={{ alignSelf: 'flex-start' }}>
            {MARKETS.filter(([key]) => byMarket[key].length > 0).map(([key, label]) => (
              <button key={key} type="button" aria-pressed={market === key} onClick={() => setMarket(key)}>{label} {byMarket[key].length}</button>
            ))}
          </div>
          <p className="ui-note">{MARKET_NOTES[market]}</p>
          {visible.length === 0 ? <p className="ui-muted">自选里没有这个市场的品种。</p> : (
            <div className="ui-scan-grid">
              {visible.map(item => <ScanCard key={item.symbol} item={item} name={nameOf(item.symbol)} statusOnly={market === 'cn' || market === 'other'} />)}
            </div>
          )}
          <div className="ui-legend">
            <span><i style={{ background: 'var(--ui-ink)' }} />周收盘</span>
            <span><i style={{ background: 'var(--ui-accent)' }} />30 周线</span>
            <span>底部条：{[1, 2, 3, 4].map(st => <i key={st} style={{ background: stageColor(st), height: 6, width: 10, marginLeft: 4 }} />)}&nbsp;一 二 三 四 阶段</span>
          </div>
        </section>
      )}
    </main>
  );
}
