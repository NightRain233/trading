import { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, createSeriesMarkers, ColorType, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import type { SeriesMarker, Time } from 'lightweight-charts';
import { RefreshCw, Search } from 'lucide-react';
import { useChartTheme, withAlpha, type ChartTheme } from '../chartTheme';
import { fetchHistoryTrades, fetchHistoryTradeSymbols } from '../utils';
import { getDefaultHistoryStartDate } from '../historyTradesDefaults.js';
import { DEFAULT_HISTORY_EXIT_MODE } from '../historyTradesQuery.js';
import type { Candle, HistorySupertrendExitMode, HistorySupertrendPoint, HistoryTradeSymbolOption, HistoryTradesResponse } from '../types';

const STRATEGIES = [
  { id: 'supertrend', label: 'SuperTrend' },
];

const EXIT_MODES: { id: HistorySupertrendExitMode; label: string }[] = [
  { id: 'baseline', label: '动态止损' },
  { id: 'reclaim', label: '止损收复' },
  { id: 'close_only', label: '仅翻空退出' },
];

const EXIT_REASON_LABEL: Record<string, string> = {
  st_flip: 'SuperTrend 翻空',
  stop: '触及动态止损',
  reclaim_st_flip: '收复再入后翻空',
  open: '持仓中',
};

const formatPrice = (value?: number | null) => {
  if (value == null || !Number.isFinite(value)) return '-';
  if (Math.abs(value) >= 1000) return value.toFixed(2);
  if (Math.abs(value) >= 10) return value.toFixed(3);
  return value.toFixed(4);
};

const formatPct = (value?: number | null) => (
  value == null || !Number.isFinite(value) ? '-' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
);

const formatRatio = (total?: number | null, drawdown?: number | null) => {
  if (total == null || drawdown == null || !Number.isFinite(total) || !Number.isFinite(drawdown) || drawdown <= 0) {
    return '-';
  }
  return (total / drawdown).toFixed(2);
};

function renderSupertrendSegments(chart: ReturnType<typeof createChart>, points: HistorySupertrendPoint[], theme: ChartTheme) {
  const segments: { dir: number; pts: { time: Time; value: number }[] }[] = [];
  for (const p of points) {
    if (!Number.isFinite(p.value)) continue;
    const pt = { time: p.time as Time, value: p.value };
    const last = segments[segments.length - 1];
    if (!last || last.dir !== p.direction) {
      segments.push({ dir: p.direction, pts: [pt] });
    } else {
      last.pts.push(pt);
    }
  }

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const pts = i > 0
      ? [segments[i - 1].pts[segments[i - 1].pts.length - 1], ...seg.pts]
      : seg.pts;
    const series = chart.addSeries(LineSeries, {
      color: seg.dir === 1 ? theme.rise : theme.fall,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(pts);
  }
}

function HistoryTradesChart({ result }: { result: HistoryTradesResponse | null }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const theme = useChartTheme();

  useEffect(() => {
    if (!chartRef.current || !result || result.candles.length === 0) return;

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: theme.text },
      grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } },
      width: chartRef.current.clientWidth,
      height: chartRef.current.clientHeight,
      timeScale: { borderColor: theme.border, timeVisible: false },
      rightPriceScale: { borderColor: theme.border, scaleMargins: { top: 0.08, bottom: 0.22 } },
      crosshair: { mode: 0 },
    });

    // A-share convention: rising candles red, falling green.
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: theme.rise,
      downColor: theme.fall,
      borderUpColor: theme.rise,
      borderDownColor: theme.fall,
      wickUpColor: theme.rise,
      wickDownColor: theme.fall,
    });
    candleSeries.setData(result.candles.map((c: Candle) => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    })));

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(result.candles.map((c: Candle) => ({
      time: c.time as Time,
      value: c.volume ?? 0,
      color: withAlpha(c.close >= c.open ? theme.rise : theme.fall, 0.25),
    })));

    renderSupertrendSegments(chart, result.supertrend, theme);

    if (result.markers.length > 0) {
      createSeriesMarkers(candleSeries, result.markers.map(m => ({
        time: m.time as Time,
        position: m.position,
        color: m.type === 'buy' ? theme.rise : theme.fall,
        shape: m.shape,
        text: m.type === 'buy' ? `B${m.tradeIndex}` : `S${m.tradeIndex}`,
      } as SeriesMarker<Time>)));
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth, height: chartRef.current.clientHeight });
    });
    ro.observe(chartRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [result, theme]);

  if (!result) return <div className="ui-lwc ui-note" style={{ display: 'grid', placeItems: 'center' }}>选择标的后运行复盘</div>;
  if (result.candles.length === 0) return <div className="ui-lwc ui-note" style={{ display: 'grid', placeItems: 'center' }}>当前区间没有可展示的 K 线</div>;
  return <div ref={chartRef} className="ui-lwc" />;
}

export function HistoryTradesPage() {
  const [symbol, setSymbol] = useState('');
  const [symbolOptions, setSymbolOptions] = useState<HistoryTradeSymbolOption[]>([]);
  const [strategy, setStrategy] = useState('supertrend');
  const [exitMode, setExitMode] = useState<HistorySupertrendExitMode>(DEFAULT_HISTORY_EXIT_MODE);
  const [start, setStart] = useState(() => getDefaultHistoryStartDate());
  const [end, setEnd] = useState('');
  const [weeklyFilter, setWeeklyFilter] = useState(false);
  const [minAdx, setMinAdx] = useState('');
  const [result, setResult] = useState<HistoryTradesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const summary = result?.summary;
  const exitReasons = useMemo(() => {
    if (!summary?.exitReasonCounts) return [];
    return Object.entries(summary.exitReasonCounts);
  }, [summary]);

  async function load(targetSymbol = symbol) {
    if (!targetSymbol.trim()) {
      setError('请输入标的代码');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchHistoryTrades({
        symbol: targetSymbol,
        strategy,
        exitMode,
        start,
        end,
        weeklyFilter,
        minAdxForEntry: minAdx ? Number(minAdx) : null,
      });
      setResult(payload);
    } catch (e: unknown) {
      setResult(null);
      setError(e instanceof Error ? e.message : '复盘请求失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let disposed = false;
    async function loadSymbols() {
      const options = await fetchHistoryTradeSymbols();
      if (disposed) return;
      setSymbolOptions(options);
      const preferred =
        options.find(option => option.symbol === '510500.SS' && option.hasCache)
        || options.find(option => option.hasCache)
        || options.find(option => option.hasData)
        || options[0];
      if (preferred) {
        setSymbol(preferred.symbol);
        await load(preferred.symbol);
      }
    }
    void loadSymbols();
    return () => { disposed = true; };
    // The initial symbol catalog chooses the first cached symbol once on page entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tone = (value?: number | null) => (value == null || value === 0 ? '' : value > 0 ? 'ui-rise' : 'ui-fall');

  return (
    <main className="ui-page" style={{ maxWidth: 1240 }}>
      <section className="ui-hero">
        <span className="ui-eyebrow">复盘 · 历史买卖点</span>
        <h1 className="ui-verdict" style={{ fontSize: 'clamp(26px, 4vw, 36px)' }}>如果一直按 SuperTrend 做，会怎样？</h1>
        <p className="ui-verdict-sub">选一个品种，把日线 SuperTrend 规则在过去重放一遍：每一笔在哪买、在哪卖、赚了多少，再和一直拿着比。</p>
      </section>

      <form
        className="ui-panel ui-form"
        onSubmit={(event) => {
          event.preventDefault();
          void load();
        }}
      >
        <label className="ui-field" style={{ gridColumn: 'span 2' }}>
          品种
          <select value={symbol} onChange={e => setSymbol(e.target.value)} className="ui-input">
            {symbolOptions.length === 0 && <option value="">加载中...</option>}
            {symbolOptions.map(option => (
              <option key={option.symbol} value={option.symbol}>
                {option.displayName}{option.hasCache ? '' : option.hasData ? ' · 未预计算' : ' · 无数据'}
              </option>
            ))}
          </select>
        </label>
        <label className="ui-field">
          策略
          <select value={strategy} onChange={e => setStrategy(e.target.value)} className="ui-input">
            {STRATEGIES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <label className="ui-field">
          离场方式
          <select value={exitMode} onChange={e => setExitMode(e.target.value as HistorySupertrendExitMode)} className="ui-input">
            {EXIT_MODES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <label className="ui-field">
          开始
          <input type="date" value={start} onChange={e => setStart(e.target.value)} className="ui-input" />
        </label>
        <label className="ui-field">
          结束
          <input type="date" value={end} onChange={e => setEnd(e.target.value)} className="ui-input" />
        </label>
        <label className="ui-field">
          ADX 下限
          <input type="number" min="0" step="1" value={minAdx} onChange={e => setMinAdx(e.target.value)} className="ui-input" placeholder="可选" />
        </label>
        <label className="ui-check">
          <input type="checkbox" checked={weeklyFilter} onChange={e => setWeeklyFilter(e.target.checked)} />
          周线过滤
        </label>
        <button type="submit" disabled={loading} className="ui-btn primary">
          {loading ? <RefreshCw size={15} className="animate-spin" /> : <Search size={15} />}
          运行复盘
        </button>
      </form>

      {error && <p className="ui-error">{error}</p>}

      <section className="ui-stats cols-5">
        <Metric label="交易次数" value={summary?.tradeCount ?? '—'} />
        <Metric label="胜率" value={summary ? `${(summary.winRate * 100).toFixed(0)}%` : '—'} />
        <Metric label="总收益" value={summary ? formatPct(summary.totalReturnPct) : '—'} tone={tone(summary?.totalReturnPct)} />
        <Metric label="最大回撤" value={summary ? `-${summary.maxDrawdownPct.toFixed(2)}%` : '—'} tone="ui-fall" />
        <Metric label="平均持仓" value={summary ? `${summary.averageHoldingDays.toFixed(1)} 天` : '—'} />
      </section>

      {result && (
        <section className="ui-panel ui-stack" aria-labelledby="h-cmp">
          <div className="ui-sec-head">
            <h2 className="ui-h2" id="h-cmp">和一直拿着比</h2>
            <p>一直拿着：收益 <span className={`ui-num ${tone(result.benchmark.totalReturnPct)}`}>{formatPct(result.benchmark.totalReturnPct)}</span>，回撤 <span className="ui-num ui-fall">-{result.benchmark.maxDrawdownPct.toFixed(2)}%</span>，收益/回撤 <span className="ui-num">{formatRatio(result.benchmark.totalReturnPct, result.benchmark.maxDrawdownPct)}</span></p>
          </div>
          <div className="ui-tbl-wrap">
            <table className="ui-table">
              <thead><tr><th>离场方式</th><th className="r">收益</th><th className="r">回撤</th><th className="r">收益/回撤</th><th className="r">交易</th><th className="r">胜率</th></tr></thead>
              <tbody>
                {result.strategyComparisons.map(item => (
                  <tr key={item.id} className={item.id === result.exitMode ? 'on' : undefined}>
                    <td>{item.label}{item.id === result.exitMode && <span className="ui-muted">（当前）</span>}</td>
                    <td className={`r ui-num ${tone(item.totalReturnPct)}`}>{formatPct(item.totalReturnPct)}</td>
                    <td className="r ui-num ui-fall">-{item.maxDrawdownPct.toFixed(2)}%</td>
                    <td className="r ui-num">{formatRatio(item.totalReturnPct, item.maxDrawdownPct)}</td>
                    <td className="r ui-num">{item.tradeCount}</td>
                    <td className="r ui-num">{(item.winRate * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="ui-chart-split">
        <section className="ui-panel ui-stack" aria-label="K 线与买卖点">
          <div className="ui-sec-head">
            <h2 className="ui-h2">{result ? result.symbol : 'K 线'}</h2>
            <div className="ui-legend">
              <span><i style={{ background: 'var(--ui-rise)' }} />ST 向上 · B 买入</span>
              <span><i style={{ background: 'var(--ui-fall)' }} />ST 向下 · S 卖出</span>
            </div>
          </div>
          <HistoryTradesChart result={result} />
        </section>

        <aside className="ui-panel ui-stack" aria-labelledby="h-trades">
          <div className="ui-sec-head"><h2 className="ui-h2" id="h-trades">逐笔交易</h2>{result && <p>{result.trades.length} 笔</p>}</div>
          {!result && !loading && <p className="ui-muted" style={{ margin: 0 }}>运行复盘后显示交易列表。</p>}
          {result && result.trades.length === 0 && <p className="ui-muted" style={{ margin: 0 }}>当前区间没有交易。</p>}
          {result && result.trades.length > 0 && (
            <div className="ui-trades">
              {[...result.trades].reverse().map(trade => {
                const isOpen = Boolean(trade.isOpen || !trade.exitDate);
                const exitDate = isOpen ? trade.currentDate : trade.exitDate;
                const exitPrice = isOpen ? trade.currentPrice : trade.exitPrice;
                return (
                  <div key={`${trade.tradeIndex}-${isOpen ? 'open' : 'closed'}`} className="ui-trade">
                    <div className="ui-row" style={{ justifyContent: 'space-between' }}>
                      <span className="ui-row" style={{ gap: 8 }}>
                        <span className="ui-num ui-muted">#{trade.tradeIndex}</span>
                        {isOpen && <span className="ui-chip warn"><i />持仓中</span>}
                      </span>
                      <span className={`ui-num ${tone(trade.returnPct)}`} style={{ fontSize: 15, fontWeight: 600 }}>
                        {isOpen && <small className="ui-muted" style={{ fontWeight: 400, marginRight: 4 }}>浮盈</small>}{formatPct(trade.returnPct)}
                      </span>
                    </div>
                    <dl className="ui-trade-grid">
                      <div><dt>买入</dt><dd className="ui-num">{trade.entryDate} · {formatPrice(trade.entryPrice)}</dd></div>
                      <div><dt>{isOpen ? '当前' : '卖出'}</dt><dd className="ui-num">{exitDate || '—'} · {formatPrice(exitPrice)}</dd></div>
                      <div><dt>持仓</dt><dd className="ui-num">{trade.holdingDays} 天</dd></div>
                      <div><dt>原因</dt><dd>{EXIT_REASON_LABEL[trade.exitReason] || trade.exitReason}</dd></div>
                    </dl>
                  </div>
                );
              })}
            </div>
          )}
          {exitReasons.length > 0 && (
            <div className="ui-row" style={{ gap: 6 }}>
              {exitReasons.map(([reason, count]) => (
                <span key={reason} className="ui-chip s1">{EXIT_REASON_LABEL[reason] || reason} {count}</span>
              ))}
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function Metric({ label, value, tone = '' }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="ui-stat"><span>{label}</span><b className={`ui-num ${tone}`}>{value}</b></div>
  );
}
