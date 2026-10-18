import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';
import { useChartTheme, type ChartTheme } from '../chartTheme';
import type { Time } from 'lightweight-charts';
import { Bell, BriefcaseBusiness, CircleOff, Eye, RefreshCw, ShieldAlert, Target } from 'lucide-react';
import {
  deriveConfluenceLabel,
  deriveDisplaySignal,
  getWeakOpportunityHint,
  isDefaultVisible,
  sortSupertrendItems,
} from '../supertrendDisplay.js';
import { getSupertrendPollDelay, shouldRefreshOnVisibility } from '../pollingPolicy.js';

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
  weeklyProvisionalState?: 'bull_flip' | 'bear_flip' | 'bull' | 'bear' | null;
  weeklyPeriodComplete?: boolean | null;
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
  trendAgeBars?: number | null;
  opportunityStage: 'fresh_bull' | 'pullback_buy_zone' | 'wait_pullback' | 'extended_from_entry' | 'trend_watch' | 'invalidated' | 'neutral';
  opportunityLabel: string;
  opportunityAgeBars: number | null;
  opportunityReason: string;
  latestDataDate?: string | null;
  dataUpdatedAt?: string | null;
  cacheStale?: boolean;
  dataStale?: boolean;
  refreshTriggered?: boolean;
  dailySessionComplete?: boolean | null;
  market?: string;
  marketMode?: 'seek' | 'cautious' | 'survival' | 'insufficient';
  primaryGroup?: string;
  tags?: string[];
  decision?: {
    permission: 'buy' | 'wait' | 'watch' | 'risk' | 'blocked';
    label: string;
    setup: 'breakout' | 'pullback' | 'v_reversal' | 'yellow_watch' | 'risk' | 'none';
    stage: string;
    reasonCodes: string[];
    failedGates: string[];
    nextTrigger: string | null;
    invalidation: string | null;
    maxAcceptablePrice: number | null;
  };
  breakout?: {
    triggered: boolean;
    signalDate: string | null;
    previousState: string | null;
    currentState: string;
    distanceAtr: number | null;
    maxAcceptablePrice: number | null;
    stillExecutable: boolean;
  };
  dataIntegrity?: {
    hasGap: boolean;
    firstMissingDate: string | null;
    expectedLatestDate: string | null;
  };
}

interface STScanResponse {
  schemaVersion: number;
  policyVersion: string;
  generatedAt: string;
  coverage: {
    requested: number;
    returned: number;
    missing: string[];
  };
  items: STItem[];
}

type FilterType = 'all' | STItem['state'] | 'actionable' | 'high_priority' | 'weekly_bull_daily_bear' | 'weekly_bear_daily_bull' | 'weekly_bull_daily_just_bull' | 'weekly_bear_daily_just_bear' | 'weekly_bull_daily_bull' | 'weekly_bear_daily_bear';
type UserMark = 'none' | 'watch' | 'holding' | 'ignored';

const MARK_STORAGE_KEY = 'supertrend:user-marks:v1';

const STATE_LABEL: Record<STItem['state'], string> = {
  bull_flip: '金叉', bear_flip: '死叉', bull: '多头', bear: '空头',
};
const MARK_OPTIONS: { value: Exclude<UserMark, 'none'>; label: string; icon: typeof Eye }[] = [
  { value: 'watch', label: '关注', icon: Eye },
  { value: 'holding', label: '持有', icon: BriefcaseBusiness },
  { value: 'ignored', label: '忽略', icon: CircleOff },
];

// Chip styles from design.css; A-share colours (bullish red, bearish green).
const SIGNAL_CHIP: Record<string, string> = { emerald: 's2', cyan: 'ok', amber: 'warn', red: 's4' };

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

const formatDateLabel = (value: string | null) => {
  if (!value) return '-';
  return value;
};

const formatDateTimeLabel = (value: string | null) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
};

const loadStoredMarks = (): Record<string, UserMark> => {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(MARK_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, UserMark>;
    return Object.fromEntries(
      Object.entries(parsed).filter(([, mark]) => mark === 'watch' || mark === 'holding' || mark === 'ignored')
    );
  } catch {
    return {};
  }
};

const saveStoredMarks = (marks: Record<string, UserMark>) => {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(MARK_STORAGE_KEY, JSON.stringify(marks));
};

function renderSTLines(chart: ReturnType<typeof createChart>, candles: STCandle[], theme: ChartTheme) {
  const stCandles = candles.filter(c => c.st_val != null);
  let i = 0;
  while (i < stCandles.length) {
    const dir = stCandles[i].st_dir;
    const seg: typeof stCandles = [];
    while (i < stCandles.length && stCandles[i].st_dir === dir) seg.push(stCandles[i++]);
    if (i < stCandles.length) seg.push(stCandles[i]);
    const s = chart.addSeries(LineSeries, {
      color: dir === 1 ? theme.rise : theme.fall,
      lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
    });
    s.setData(seg.map(c => ({ time: c.time as Time, value: c.st_val! })));
  }
}

function useMiniChart(ref: React.RefObject<HTMLDivElement | null>, candles: STCandle[], height: number, theme: ChartTheme) {
  useEffect(() => {
    if (!ref.current || candles.length === 0) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: theme.text, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
      width: ref.current.clientWidth,
      height,
      timeScale: { borderColor: theme.border, timeVisible: false },
      rightPriceScale: { borderColor: theme.border, scaleMargins: { top: 0.1, bottom: 0.1 } },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });
    const cs = chart.addSeries(CandlestickSeries, {
      upColor: theme.rise, downColor: theme.fall,
      borderUpColor: theme.rise, borderDownColor: theme.fall,
      wickUpColor: theme.rise, wickDownColor: theme.fall,
      priceLineVisible: false,
    });
    cs.setData(candles.map(c => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    renderSTLines(chart, candles, theme);
    chart.timeScale().fitContent();
    const node = ref.current;
    const ro = new ResizeObserver(() => chart.applyOptions({ width: node.clientWidth }));
    ro.observe(node);
    return () => { ro.disconnect(); chart.remove(); };
  }, [ref, candles, height, theme]);
}

function MiniSTChart({ candles, weeklyCandles }: { candles: STCandle[]; weeklyCandles: STCandle[] }) {
  const dailyRef = useRef<HTMLDivElement>(null);
  const weeklyRef = useRef<HTMLDivElement>(null);
  const theme = useChartTheme();
  useMiniChart(dailyRef, candles, 130, theme);
  useMiniChart(weeklyRef, weeklyCandles, 90, theme);
  return (
    <div className="ui-stack" style={{ gap: 4 }}>
      <div className="ui-muted" style={{ fontSize: 11 }}>日线</div>
      <div ref={dailyRef} />
      {weeklyCandles.length > 0 && (
        <>
          <div className="ui-muted" style={{ fontSize: 11 }}>周线</div>
          <div ref={weeklyRef} />
        </>
      )}
    </div>
  );
}

const isWeeklyBull = (s: STItem) => s.weeklyState === 'bull' || s.weeklyState === 'bull_flip';
const isWeeklyBear = (s: STItem) => s.weeklyState === 'bear' || s.weeklyState === 'bear_flip';
const isDailyBull = (s: STItem) => s.state === 'bull' || s.state === 'bull_flip';
const isDailyBear = (s: STItem) => s.state === 'bear' || s.state === 'bear_flip';
const isPinnedMark = (mark: UserMark | undefined) => mark === 'watch' || mark === 'holding';
const isFocusItem = (s: STItem, mark: UserMark | undefined) => (
  Boolean(deriveDisplaySignal(s)) || (isPinnedMark(mark) && s.alertPriority === 'high')
);

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
  const [marks, setMarks] = useState<Record<string, UserMark>>(() => loadStoredMarks());
  const lastLoadedAtRef = useRef<number | null>(null);
  const refreshRetryCountRef = useRef(0);

  const load = useCallback(async ({ force = false, background = false }: { force?: boolean; background?: boolean } = {}) => {
    if (!background) setLoading(true);
    try {
      const params = new URLSearchParams({ include_candles: 'true' });
      if (force) params.set('force', '1');
      const r = await fetch(`${API_BASE}/supertrend/scan?${params.toString()}`);
      const payload = await r.json() as STScanResponse;
      setItems(payload.items);
      lastLoadedAtRef.current = Date.now();
      return payload.items.some(item => item.refreshTriggered);
    } finally {
      if (!background) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let timerId: number | null = null;

    const clearTimer = () => {
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
    };

    const scheduleNext = (refreshTriggered: boolean) => {
      if (disposed) return;
      const retryCount = refreshRetryCountRef.current;
      const delay = getSupertrendPollDelay({ refreshTriggered, retryCount });
      if (refreshTriggered && retryCount < 2) {
        refreshRetryCountRef.current = retryCount + 1;
      } else {
        refreshRetryCountRef.current = 0;
      }
      timerId = window.setTimeout(async () => {
        const nextRefreshTriggered = await load({ background: true });
        if (!disposed) scheduleNext(Boolean(nextRefreshTriggered));
      }, delay);
    };

    const run = async (background = false) => {
      const refreshTriggered = await load({ background });
      if (!disposed) scheduleNext(Boolean(refreshTriggered));
    };

    void run(false);

    const handleVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return;
      if (!shouldRefreshOnVisibility({ lastLoadedAt: lastLoadedAtRef.current, now: Date.now() })) return;
      clearTimer();
      void run(true);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      disposed = true;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [load]);

  function updateMark(symbol: string, nextMark: UserMark) {
    setMarks(prev => {
      const updated = { ...prev };
      if (nextMark === 'none') {
        delete updated[symbol];
      } else {
        updated[symbol] = nextMark;
      }
      saveStoredMarks(updated);
      return updated;
    });
  }

  const displayed = sortSupertrendItems(items.filter(i => matchFilter(i, filter)), marks);
  const otherCount = filter === 'all' ? displayed.filter(i => !isDefaultVisible(i, marks[i.symbol])).length : 0;
  const visibleDisplayed = filter === 'all' && !showLowPriority
    ? displayed.filter(i => isDefaultVisible(i, marks[i.symbol]))
    : displayed;
  const onlyFoldedOther = filter === 'all' && !showLowPriority && visibleDisplayed.length === 0 && otherCount > 0;
  const signalCounts = items.reduce<Record<string, number>>((acc, item) => {
    const signal = deriveDisplaySignal(item);
    if (signal) acc[signal.key] = (acc[signal.key] || 0) + 1;
    return acc;
  }, {});
  const dataStatus = useMemo(() => {
    const latestDataDate = items
      .map(item => item.latestDataDate)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null;
    const latestUpdatedAt = items
      .map(item => item.dataUpdatedAt)
      .filter((value): value is string => Boolean(value))
      .sort((a, b) => Date.parse(a) - Date.parse(b))
      .at(-1) ?? null;
    const cacheStaleCount = items.filter(item => item.cacheStale).length;
    const dataStaleCount = items.filter(item => item.dataStale).length;
    const gapCount = items.filter(item => item.dataIntegrity?.hasGap).length;
    const refreshingCount = items.filter(item => item.refreshTriggered).length;
    return { latestDataDate, latestUpdatedAt, cacheStaleCount, dataStaleCount, gapCount, refreshingCount };
  }, [items]);

  const statusIssues = [
    dataStatus.refreshingCount > 0 && `${dataStatus.refreshingCount} 个正在刷新`,
    dataStatus.cacheStaleCount > 0 && `${dataStatus.cacheStaleCount} 个缓存偏旧`,
    dataStatus.dataStaleCount > 0 && `${dataStatus.dataStaleCount} 个数据可能延迟`,
    dataStatus.gapCount > 0 && `${dataStatus.gapCount} 个可能有缺口`,
  ].filter(Boolean).join(' · ');
  const statusWarn = dataStatus.dataStaleCount > 0 || dataStatus.gapCount > 0;
  const focusCount = items.filter(item => isDefaultVisible(item, marks[item.symbol])).length;
  const filterGroups: Array<[string, Array<{ key: FilterType; label: string }>]> = [
    ['日线', (['bull_flip', 'bear_flip', 'bull', 'bear'] as const).map(key => ({ key, label: STATE_LABEL[key] }))],
    ['提醒', ALERT_FILTERS],
    ['共振', CROSS_FILTERS],
  ];

  return (
    <main className="ui-page" style={{ maxWidth: 1240 }}>
      <section className="ui-hero">
        <div className="ui-row" style={{ justifyContent: 'space-between' }}>
          <span className="ui-eyebrow">SuperTrend · 日线趋势扫描 · 学习观察</span>
          <button type="button" className="ui-btn" onClick={() => void load({ force: true })} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />{loading ? '扫描中' : '刷新'}
          </button>
        </div>
        <h1 className="ui-verdict" style={{ fontSize: 'clamp(26px, 4vw, 36px)' }}>
          {items.length === 0 ? 'SuperTrend 扫描' : focusCount > 0 ? `今晚有 ${focusCount} 个值得看` : '今晚没有新信号'}
        </h1>
        <p className="ui-verdict-sub">
          数据截至 {formatDateLabel(dataStatus.latestDataDate)} · 更新 {formatDateTimeLabel(dataStatus.latestUpdatedAt)}。
          这里只是学习观察，主策略的 BTC 开关用的是自己的参数，看首页。
        </p>
        {statusIssues && <p className={`ui-note ${statusWarn ? 'warn' : ''}`}>{statusIssues}</p>}
      </section>

      <section className="ui-stats">
        <div className="ui-stat"><span>刚翻多</span><b className="ui-num ui-rise">{signalCounts.fresh_bull || 0}</b></div>
        <div className="ui-stat"><span>回踩观察</span><b className="ui-num" style={{ color: 'var(--ui-accent)' }}>{signalCounts.pullback_watch || 0}</b></div>
        <div className="ui-stat"><span>预备翻多</span><b className="ui-num" style={{ color: 'var(--ui-warn)' }}>{signalCounts.pre_bull || 0}</b></div>
        <div className="ui-stat"><span>风控</span><b className="ui-num ui-fall">{signalCounts.risk || 0}</b></div>
      </section>

      <div className="ui-stack" style={{ gap: 8 }}>
        {filterGroups.map(([label, options]) => (
          <div key={label} className="ui-row" style={{ gap: 10 }}>
            <span className="ui-muted" style={{ fontSize: 12, width: 28 }}>{label}</span>
            <div className="ui-seg" role="group" aria-label={label}>
              {options.map(({ key, label: text }) => (
                <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(filter === key ? 'all' : key)}>{text}</button>
              ))}
            </div>
          </div>
        ))}
      </div>

      {filter === 'all' && (
        <div className="ui-note ui-row" style={{ justifyContent: 'space-between' }}>
          <span>默认只显示刚翻多、回踩观察、预备翻多、风控，以及你标了关注/持有且有高优先级信号的。</span>
          <button type="button" className="ui-btn" onClick={() => setShowLowPriority(v => !v)}>
            {showLowPriority ? '收起其他' : `展开其他 ${otherCount}`}
          </button>
        </div>
      )}
      {filter !== 'all' && (
        <button type="button" className="ui-btn" style={{ alignSelf: 'flex-start' }} onClick={() => setFilter('all')}>清除筛选</button>
      )}

      {loading && items.length === 0 && <div className="ui-skeleton" />}

      <div className="ui-scan-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {visibleDisplayed.map(item => {
          const displaySignal = deriveDisplaySignal(item);
          const weakHint = getWeakOpportunityHint(item);
          const confluenceLabel = deriveConfluenceLabel(item);
          const mark = marks[item.symbol];
          const focus = isFocusItem(item, mark);
          const atRisk = item.opportunityStage === 'invalidated' || item.alertType === 'sell_or_risk';

          return (
            <article key={item.symbol} className="ui-panel ui-scan-card" style={{ opacity: mark === 'ignored' ? 0.55 : focus ? 1 : 0.85, borderColor: focus ? 'var(--ui-ink-3)' : undefined }}>
              <header className="ui-scan-head">
                <div style={{ minWidth: 0 }}>
                  <b>{item.alias || item.symbol}</b>
                  {item.alias && <small className="ui-num">{item.symbol}</small>}
                </div>
                <span className={`ui-muted ${item.state === 'bull_flip' ? 'ui-rise' : item.state === 'bear_flip' ? 'ui-fall' : ''}`} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{confluenceLabel}</span>
              </header>
              <div className="ui-row" style={{ gap: 6 }}>
                {displaySignal ? (
                  <span className={`ui-chip ${SIGNAL_CHIP[displaySignal.tone]}`}>
                    {displaySignal.key === 'risk' ? <ShieldAlert size={12} /> : <Bell size={12} />}{displaySignal.label}
                  </span>
                ) : (
                  <span className="ui-chip s1"><Target size={12} />{item.alertLabel || '观察'}</span>
                )}
                {item.alertPriority === 'high' && <span className="ui-chip warn">高优先级</span>}
                {weakHint && <span className="ui-muted" style={{ fontSize: 12 }}>{weakHint}</span>}
              </div>
              <div className="ui-toggles" role="group" aria-label="我的标记">
                {MARK_OPTIONS.map(({ value, label, icon: Icon }) => {
                  const active = mark === value;
                  return (
                    <button key={value} type="button" aria-pressed={active} onClick={() => updateMark(item.symbol, active ? 'none' : value)}>
                      <Icon size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />{label}
                    </button>
                  );
                })}
              </div>
              <dl className="ui-scan-nums">
                <div><dt>收盘</dt><dd className="ui-num">{formatPrice(item.close)}</dd></div>
                <div><dt>{item.keyLevelType === 'resistance' ? '阻力' : '支撑'}</dt><dd className="ui-num">{formatPrice(item.keyLevelPrice ?? item.stVal)}</dd></div>
                <div><dt>距离</dt><dd className="ui-num">{formatPct(item.distanceToSupertrendPct)}</dd></div>
              </dl>
              <p className="ui-muted" style={{ margin: 0, fontSize: 12.5 }}>{item.alertReason}（{formatAtr(item.distanceToSupertrendAtr)}）</p>
              {mark === 'holding' && (
                <p className={`ui-note ${atRisk ? 'warn' : ''}`}>
                  持有中：{atRisk ? '已触发风控' : '跟踪'}，ST 止损 <span className="ui-num">{formatPrice(item.keyLevelPrice ?? item.stVal)}</span>，距离 <span className="ui-num">{formatPct(item.distanceToSupertrendPct)}</span>
                </p>
              )}
              {item.isActionable && <p style={{ margin: 0, fontSize: 13, color: 'var(--ui-ink-2)' }}>{item.suggestedAction}</p>}
              {item.candles.length > 0
                ? <MiniSTChart candles={item.candles} weeklyCandles={item.weeklyCandles} />
                : <p className="ui-muted" style={{ margin: 0 }}>无数据</p>}
            </article>
          );
        })}
      </div>

      {!loading && visibleDisplayed.length === 0 && (
        <p className="ui-muted" style={{ textAlign: 'center', padding: '40px 0' }}>
          {onlyFoldedOther ? '当前只有其他观察，已默认折叠。' : '暂无符合条件的标的。'}
        </p>
      )}
      <p className="ui-muted" style={{ fontSize: 11.5, margin: 0 }}>
        K 线图由 <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>TradingView</a> Lightweight Charts 绘制。
      </p>
    </main>
  );
}
