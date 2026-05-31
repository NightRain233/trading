import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { Bell, RefreshCw, ShieldAlert, Target } from 'lucide-react';

const API_BASE = '/api';

interface STCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  st_val: number | null;
  st_dir: number | null;
}

interface STItem {
  symbol: string;
  alias: string;
  state: 'bull_flip' | 'bear_flip' | 'bull' | 'bear';
  close: number | null;
  stVal: number | null;
  candles: STCandle[];
  weeklyState: 'bull_flip' | 'bear_flip' | 'bull' | 'bear' | null;
  weeklyStVal: number | null;
  weeklyCandles: STCandle[];
  justFlipped: boolean;
  weeklyJustFlipped: boolean;
  alertType: 'buy_candidate' | 'support_test' | 'sell_or_risk' | 'resistance_test' | 'hold_bull' | 'avoid_bear' | 'none';
  alertLabel: string;
  alertPriority: 'high' | 'medium' | 'low' | 'none';
  isActionable: boolean;
  keyLevelType: 'support' | 'resistance' | 'none';
  keyLevelPrice: number | null;
  signedDistanceToSupertrendPct: number | null;
  distanceToSupertrendPct: number | null;
  distanceToSupertrendAtr: number | null;
  alertReason: string;
  suggestedAction: string;
}

type FilterType = 'all' | STItem['state'] | 'actionable' | 'high_priority' | 'weekly_bull_daily_bear' | 'weekly_bear_daily_bull' | 'weekly_bull_daily_just_bull' | 'weekly_bear_daily_just_bear' | 'weekly_bull_daily_bull' | 'weekly_bear_daily_bear';

const STATE_LABEL: Record<STItem['state'], string> = {
  bull_flip: '金叉', bear_flip: '死叉', bull: '多头', bear: '空头',
};
const STATE_COLOR: Record<STItem['state'], string> = {
  bull_flip: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10',
  bear_flip: 'text-red-400 border-red-500/40 bg-red-500/10',
  bull: 'text-sky-400 border-sky-500/40 bg-sky-500/10',
  bear: 'text-zinc-500 border-zinc-700 bg-zinc-800/30',
};

const ALERT_COLOR: Record<STItem['alertType'], string> = {
  buy_candidate: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
  support_test: 'text-cyan-300 border-cyan-500/35 bg-cyan-500/10',
  sell_or_risk: 'text-red-300 border-red-500/40 bg-red-500/10',
  resistance_test: 'text-amber-300 border-amber-500/35 bg-amber-500/10',
  hold_bull: 'text-sky-300 border-sky-500/30 bg-sky-500/10',
  avoid_bear: 'text-zinc-400 border-zinc-700 bg-zinc-800/30',
  none: 'text-zinc-500 border-zinc-800 bg-zinc-900/40',
};

const PRIORITY_LABEL: Record<STItem['alertPriority'], string> = {
  high: '高',
  medium: '中',
  low: '低',
  none: '无',
};

const PRIORITY_RANK: Record<STItem['alertPriority'], number> = {
  high: 0,
  medium: 1,
  low: 2,
  none: 3,
};

const formatPrice = (value: number | null) => {
  if (value == null || !Number.isFinite(value)) return '-';
  if (Math.abs(value) >= 1000) return value.toFixed(2);
  if (Math.abs(value) >= 10) return value.toFixed(3);
  return value.toFixed(4);
};

const formatPct = (value: number | null) => (
  value == null || !Number.isFinite(value) ? '-' : `${value.toFixed(2)}%`
);

const formatAtr = (value: number | null) => (
  value == null || !Number.isFinite(value) ? '-' : `${value.toFixed(2)} ATR`
);

function renderSTLines(chart: ReturnType<typeof createChart>, candles: STCandle[]) {
  const stCandles = candles.filter(c => c.st_val != null);
  let i = 0;
  while (i < stCandles.length) {
    const dir = stCandles[i].st_dir;
    const seg: typeof stCandles = [];
    while (i < stCandles.length && stCandles[i].st_dir === dir) seg.push(stCandles[i++]);
    if (i < stCandles.length) seg.push(stCandles[i]);
    const s = chart.addSeries(LineSeries, {
      color: dir === 1 ? '#22c55e' : '#ef4444',
      lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
    });
    s.setData(seg.map(c => ({ time: c.time as Time, value: c.st_val! })));
  }
}

function MiniSTChart({ candles, weeklyCandles }: { candles: STCandle[]; weeklyCandles: STCandle[] }) {
  const dailyRef = useRef<HTMLDivElement>(null);
  const weeklyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dailyRef.current || candles.length === 0) return;
    const chart = createChart(dailyRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
      grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
      width: dailyRef.current.clientWidth,
      height: 130,
      timeScale: { borderColor: '#3f3f46', timeVisible: false },
      rightPriceScale: { borderColor: '#3f3f46', scaleMargins: { top: 0.1, bottom: 0.1 } },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });
    const cs = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderUpColor: '#10b981', borderDownColor: '#ef4444',
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    cs.setData(candles.map(c => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    renderSTLines(chart, candles);
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (dailyRef.current) chart.applyOptions({ width: dailyRef.current.clientWidth });
    });
    ro.observe(dailyRef.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [candles]);

  useEffect(() => {
    if (!weeklyRef.current || weeklyCandles.length === 0) return;
    const chart = createChart(weeklyRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
      grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
      width: weeklyRef.current.clientWidth,
      height: 90,
      timeScale: { borderColor: '#3f3f46', timeVisible: false },
      rightPriceScale: { borderColor: '#3f3f46', scaleMargins: { top: 0.1, bottom: 0.1 } },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });
    const cs = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderUpColor: '#10b981', borderDownColor: '#ef4444',
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    cs.setData(weeklyCandles.map(c => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    renderSTLines(chart, weeklyCandles);
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (weeklyRef.current) chart.applyOptions({ width: weeklyRef.current.clientWidth });
    });
    ro.observe(weeklyRef.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [weeklyCandles]);

  return (
    <div>
      <div ref={dailyRef} className="w-full" />
      {weeklyCandles.length > 0 && (
        <>
          <div className="px-2 pt-1 pb-0.5 text-[9px] text-zinc-600 uppercase tracking-widest">周线</div>
          <div ref={weeklyRef} className="w-full" />
        </>
      )}
    </div>
  );
}

const isWeeklyBull = (s: STItem) => s.weeklyState === 'bull' || s.weeklyState === 'bull_flip';
const isWeeklyBear = (s: STItem) => s.weeklyState === 'bear' || s.weeklyState === 'bear_flip';
const isDailyBull = (s: STItem) => s.state === 'bull' || s.state === 'bull_flip';
const isDailyBear = (s: STItem) => s.state === 'bear' || s.state === 'bear_flip';
const isLowPriorityObservation = (s: STItem) => !s.isActionable && (s.alertPriority === 'low' || s.alertPriority === 'none');
const isFocusItem = (s: STItem) => s.alertPriority === 'high' || s.isActionable;

const CROSS_FILTERS: { key: FilterType; label: string }[] = [
  { key: 'weekly_bull_daily_bull', label: '周多日多' },
  { key: 'weekly_bear_daily_bear', label: '周空日空' },
  { key: 'weekly_bull_daily_bear', label: '周多日空' },
  { key: 'weekly_bear_daily_bull', label: '周空日多' },
  { key: 'weekly_bull_daily_just_bull', label: '周多日刚翻多' },
  { key: 'weekly_bear_daily_just_bear', label: '周空日刚翻空' },
];

const ALERT_FILTERS: { key: FilterType; label: string }[] = [
  { key: 'actionable', label: '可操作' },
  { key: 'high_priority', label: '高优先级' },
];

function matchFilter(item: STItem, filter: FilterType): boolean {
  if (filter === 'all') return true;
  if (filter === 'weekly_bull_daily_bull') return isWeeklyBull(item) && isDailyBull(item);
  if (filter === 'weekly_bear_daily_bear') return isWeeklyBear(item) && isDailyBear(item);
  if (filter === 'weekly_bull_daily_bear') return isWeeklyBull(item) && isDailyBear(item);
  if (filter === 'weekly_bear_daily_bull') return isWeeklyBear(item) && isDailyBull(item);
  if (filter === 'weekly_bull_daily_just_bull') return isWeeklyBull(item) && item.justFlipped && isDailyBull(item);
  if (filter === 'weekly_bear_daily_just_bear') return isWeeklyBear(item) && item.justFlipped && isDailyBear(item);
  if (filter === 'actionable') return item.isActionable;
  if (filter === 'high_priority') return item.alertPriority === 'high';
  return item.state === filter;
}

export function SupertrendPage() {
  const [items, setItems] = useState<STItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterType>('all');
  const [showLowPriority, setShowLowPriority] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/supertrend/scan`);
      setItems(await r.json());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const ORDER: STItem['state'][] = ['bull_flip', 'bear_flip', 'bull', 'bear'];
  const displayed = items
    .filter(i => matchFilter(i, filter))
    .sort((a, b) => {
      const priorityDiff = PRIORITY_RANK[a.alertPriority] - PRIORITY_RANK[b.alertPriority];
      if (priorityDiff !== 0) return priorityDiff;
      return ORDER.indexOf(a.state) - ORDER.indexOf(b.state);
    });
  const lowPriorityCount = filter === 'all' ? displayed.filter(isLowPriorityObservation).length : 0;
  const visibleDisplayed = filter === 'all' && !showLowPriority
    ? displayed.filter(i => !isLowPriorityObservation(i))
    : displayed;
  const onlyFoldedLowPriority = filter === 'all' && !showLowPriority && visibleDisplayed.length === 0 && lowPriorityCount > 0;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <span className="text-sm font-semibold text-zinc-300">SuperTrend 扫描</span>
        <button
          onClick={load}
          title="刷新"
          className={`ml-auto p-2 rounded-xl text-zinc-500 hover:text-emerald-400 btn-glass active:scale-[0.98] ${loading ? 'animate-spin' : ''}`}
        >
          <RefreshCw size={15} />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        <div className="border border-zinc-800 bg-zinc-900/45 rounded-lg px-3 py-2">
          <div className="text-[10px] text-zinc-600 uppercase tracking-widest">可操作</div>
          <div className="text-lg font-semibold text-zinc-100">{items.filter(i => i.isActionable).length}</div>
        </div>
        <div className="border border-zinc-800 bg-zinc-900/45 rounded-lg px-3 py-2">
          <div className="text-[10px] text-zinc-600 uppercase tracking-widest">高优先级</div>
          <div className="text-lg font-semibold text-red-300">{items.filter(i => i.alertPriority === 'high').length}</div>
        </div>
        <div className="border border-zinc-800 bg-zinc-900/45 rounded-lg px-3 py-2">
          <div className="text-[10px] text-zinc-600 uppercase tracking-widest">支撑回踩</div>
          <div className="text-lg font-semibold text-cyan-300">{items.filter(i => i.alertType === 'support_test').length}</div>
        </div>
        <div className="border border-zinc-800 bg-zinc-900/45 rounded-lg px-3 py-2">
          <div className="text-[10px] text-zinc-600 uppercase tracking-widest">风控</div>
          <div className="text-lg font-semibold text-amber-300">{items.filter(i => i.alertType === 'sell_or_risk').length}</div>
        </div>
      </div>

      {/* 日线状态过滤 */}
      <div className="flex gap-1.5 flex-wrap mb-2">
        <span className="text-[10px] text-zinc-600 self-center mr-1">日线</span>
        {(['all', 'bull_flip', 'bear_flip', 'bull', 'bear'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
              filter === f
                ? f === 'all' ? 'bg-zinc-700 border-zinc-600 text-zinc-200' : STATE_COLOR[f as STItem['state']]
                : 'btn-glass text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {f === 'all' ? '全部' : STATE_LABEL[f as STItem['state']]}
          </button>
        ))}
      </div>

      {/* 提醒过滤 */}
      <div className="flex gap-1.5 flex-wrap mb-2">
        <span className="text-[10px] text-zinc-600 self-center mr-1">提醒</span>
        {ALERT_FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(filter === key ? 'all' : key)}
            className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all active:scale-[0.98] ${
              filter === key
                ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                : 'btn-glass text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 共振过滤 */}
      <div className="flex gap-1.5 flex-wrap mb-6">
        <span className="text-[10px] text-zinc-600 self-center mr-1">共振</span>
        {CROSS_FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(filter === key ? 'all' : key)}
            className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
              filter === key
                ? 'bg-violet-500/15 border-violet-500/40 text-violet-300'
                : 'btn-glass text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {filter === 'all' && (
        <div className="mb-5 rounded-xl border border-zinc-800/90 bg-zinc-950/45 px-3 py-3 sm:px-4">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex-1">
              <div className="text-xs font-semibold text-zinc-300">日常视图：保留全量扫描，折叠低优先级观察</div>
              <div className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                近五年精简层没有同时满足收益回撤比保留 85%、总收益保留 70%、交易数下降；默认只收起低优先级卡片，不改变底层扫描覆盖。
              </div>
            </div>
            <button
              onClick={() => setShowLowPriority(v => !v)}
              className="shrink-0 rounded-lg border border-zinc-700 bg-zinc-900/70 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-all hover:border-zinc-600 hover:text-zinc-100 active:scale-[0.98]"
            >
              {showLowPriority ? '收起低优先级' : `展开低优先级 ${lowPriorityCount}`}
            </button>
          </div>
        </div>
      )}

      {loading && items.length === 0 && (
        <div className="text-zinc-500 text-sm text-center py-16">扫描中…</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {visibleDisplayed.map(item => (
          <div
            key={item.symbol}
            className={`rounded-xl border overflow-hidden transition-all ${
              isFocusItem(item)
                ? 'border-emerald-500/25 bg-zinc-900/75 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
                : 'border-zinc-800 bg-zinc-900/45 opacity-80'
            }`}
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-zinc-200">{item.symbol}</span>
                {item.alias && <span className="text-xs text-zinc-500">{item.alias}</span>}
              </div>
              <div className="flex items-center gap-2">
                {item.weeklyState && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ${STATE_COLOR[item.weeklyState]}`}>
                    周{STATE_LABEL[item.weeklyState]}
                  </span>
                )}
                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ${STATE_COLOR[item.state]}`}>
                  {STATE_LABEL[item.state]}
                </span>
              </div>
            </div>
            <div className="px-3 py-2 border-b border-zinc-800/80">
              <div className="flex items-center justify-between gap-2">
                <span className={`inline-flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-md border font-semibold ${ALERT_COLOR[item.alertType]}`}>
                  {item.alertType === 'sell_or_risk' ? <ShieldAlert size={11} /> : item.isActionable ? <Bell size={11} /> : <Target size={11} />}
                  {item.alertLabel || '无信号'}
                </span>
                <span className="text-[10px] text-zinc-500">优先级 {PRIORITY_LABEL[item.alertPriority]}</span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]">
                <div>
                  <div className="text-zinc-600">收盘</div>
                  <div className="font-mono text-zinc-300">{formatPrice(item.close)}</div>
                </div>
                <div>
                  <div className="text-zinc-600">{item.keyLevelType === 'resistance' ? '阻力' : '支撑'}</div>
                  <div className="font-mono text-zinc-300">{formatPrice(item.keyLevelPrice ?? item.stVal)}</div>
                </div>
                <div>
                  <div className="text-zinc-600">距离</div>
                  <div className="font-mono text-zinc-300">{formatPct(item.distanceToSupertrendPct)}</div>
                </div>
              </div>
              <div className="mt-2 flex items-start justify-between gap-3">
                <p className="text-[11px] leading-relaxed text-zinc-500">{item.alertReason}</p>
                <span className="shrink-0 font-mono text-[10px] text-zinc-600">{formatAtr(item.distanceToSupertrendAtr)}</span>
              </div>
              {item.isActionable && (
                <div className="mt-2 text-[11px] leading-relaxed text-zinc-400 border-t border-zinc-800/70 pt-2">
                  {item.suggestedAction}
                </div>
              )}
            </div>
            <div className="px-1 py-1">
              {item.candles.length > 0
                ? <MiniSTChart candles={item.candles} weeklyCandles={item.weeklyCandles} />
                : <div className="h-40 flex items-center justify-center text-zinc-600 text-xs">无数据</div>
              }
            </div>
          </div>
        ))}
      </div>

      {!loading && visibleDisplayed.length === 0 && (
        <div className="text-zinc-600 text-sm text-center py-16">
          {onlyFoldedLowPriority ? '当前只有低优先级观察，已默认折叠' : '暂无符合条件的标的'}
        </div>
      )}
    </div>
  );
}
