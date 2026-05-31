import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createChart, createSeriesMarkers, ColorType, CandlestickSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import type { SeriesMarker, Time } from 'lightweight-charts';
import { CalendarDays, RefreshCw, Search, ShieldCheck, TrendingUp } from 'lucide-react';
import { fetchHistoryTrades } from '../utils';
import type { Candle, HistorySupertrendPoint, HistoryTradesResponse } from '../types';

const STRATEGIES = [
  { id: 'supertrend', label: 'SuperTrend' },
];

const EXIT_REASON_LABEL: Record<string, string> = {
  st_flip: 'SuperTrend 翻空',
  stop: '触及动态止损',
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

function renderSupertrendSegments(chart: ReturnType<typeof createChart>, points: HistorySupertrendPoint[]) {
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
      color: seg.dir === 1 ? '#22c55e' : '#ef4444',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    series.setData(pts);
  }
}

function HistoryTradesChart({ result }: { result: HistoryTradesResponse | null }) {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartRef.current || !result || result.candles.length === 0) return;

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#a1a1aa' },
      grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
      width: chartRef.current.clientWidth,
      height: 520,
      timeScale: { borderColor: '#3f3f46', timeVisible: false },
      rightPriceScale: { borderColor: '#3f3f46', scaleMargins: { top: 0.08, bottom: 0.22 } },
      crosshair: { mode: 0 },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
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
      color: c.close >= c.open ? '#10b98122' : '#ef444422',
    })));

    renderSupertrendSegments(chart, result.supertrend);

    if (result.markers.length > 0) {
      createSeriesMarkers(candleSeries, result.markers.map(m => ({
        time: m.time as Time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.type === 'buy' ? `B${m.tradeIndex}` : `S${m.tradeIndex}`,
      } as SeriesMarker<Time>)));
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    });
    ro.observe(chartRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [result]);

  if (!result) {
    return (
      <div className="h-[520px] border border-zinc-800 bg-zinc-900/35 rounded-lg flex items-center justify-center text-sm text-zinc-600">
        选择标的后运行复盘
      </div>
    );
  }

  if (result.candles.length === 0) {
    return (
      <div className="h-[520px] border border-zinc-800 bg-zinc-900/35 rounded-lg flex items-center justify-center text-sm text-zinc-600">
        当前区间没有可展示的 K 线
      </div>
    );
  }

  return <div ref={chartRef} className="h-[520px] border border-zinc-800 bg-zinc-900/35 rounded-lg overflow-hidden" />;
}

export function HistoryTradesPage() {
  const [symbol, setSymbol] = useState('510300.SS');
  const [strategy, setStrategy] = useState('supertrend');
  const [start, setStart] = useState('2023-01-01');
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

  async function load() {
    if (!symbol.trim()) {
      setError('请输入标的代码');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchHistoryTrades({
        symbol,
        strategy,
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
    void load();
    // Run once with the default form values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-zinc-100 font-semibold">
            <TrendingUp size={18} className="text-emerald-400" />
            历史买卖点复盘
          </div>
          <p className="mt-1 text-xs text-zinc-500">单标的策略 replay，查看历史入场、离场和每笔收益。</p>
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void load();
          }}
          className="grid grid-cols-2 md:grid-cols-6 xl:grid-cols-8 gap-2 items-end"
        >
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1">
            <span className="text-[10px] text-zinc-500">标的</span>
            <input
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              className="input-glass rounded-lg px-3 py-2 text-sm font-mono text-zinc-100 focus:outline-none"
              placeholder="510300.SS"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-zinc-500">策略</span>
            <select
              value={strategy}
              onChange={e => setStrategy(e.target.value)}
              className="input-glass rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none"
            >
              {STRATEGIES.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-zinc-500">开始</span>
            <input
              type="date"
              value={start}
              onChange={e => setStart(e.target.value)}
              className="input-glass rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-zinc-500">结束</span>
            <input
              type="date"
              value={end}
              onChange={e => setEnd(e.target.value)}
              className="input-glass rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] text-zinc-500">ADX 下限</span>
            <input
              type="number"
              min="0"
              step="1"
              value={minAdx}
              onChange={e => setMinAdx(e.target.value)}
              className="input-glass rounded-lg px-3 py-2 text-sm text-zinc-100 focus:outline-none"
              placeholder="可选"
            />
          </label>
          <label className="h-9 flex items-center gap-2 px-3 rounded-lg border border-zinc-800 bg-zinc-900/45 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={weeklyFilter}
              onChange={e => setWeeklyFilter(e.target.checked)}
              className="accent-emerald-500"
            />
            周线过滤
          </label>
          <button
            type="submit"
            disabled={loading}
            className="h-9 inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-sm font-semibold text-emerald-300 hover:bg-emerald-500/15 active:scale-[0.98] disabled:opacity-50"
          >
            {loading ? <RefreshCw size={15} className="animate-spin" /> : <Search size={15} />}
            运行
          </button>
        </form>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        <Metric label="交易次数" value={summary?.tradeCount ?? '-'} />
        <Metric label="胜率" value={summary ? `${(summary.winRate * 100).toFixed(0)}%` : '-'} color="text-sky-300" />
        <Metric label="总收益" value={summary ? formatPct(summary.totalReturnPct) : '-'} color={(summary?.totalReturnPct ?? 0) >= 0 ? 'text-emerald-300' : 'text-red-300'} />
        <Metric label="平均持仓" value={summary ? `${summary.averageHoldingDays.toFixed(1)} 天` : '-'} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-4">
        <HistoryTradesChart result={result} />

        <aside className="border border-zinc-800 bg-zinc-900/35 rounded-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-zinc-200">交易明细</span>
            {result && <span className="text-[10px] font-mono text-zinc-500">{result.symbol}</span>}
          </div>

          {!result && !loading && (
            <div className="p-6 text-sm text-zinc-600">运行复盘后显示交易列表。</div>
          )}

          {result && result.trades.length === 0 && (
            <div className="p-6 text-sm text-zinc-600">当前区间没有完成交易。</div>
          )}

          {result && result.trades.length > 0 && (
            <div className="max-h-[520px] overflow-auto divide-y divide-zinc-800/80">
              {result.trades.map(trade => (
                <div key={trade.tradeIndex} className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-zinc-500">#{trade.tradeIndex}</span>
                    <span className={`font-mono text-sm font-semibold ${trade.returnPct >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                      {formatPct(trade.returnPct)}
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                    <TradeField icon={<CalendarDays size={12} />} label="买入" value={`${trade.entryDate} · ${formatPrice(trade.entryPrice)}`} />
                    <TradeField icon={<CalendarDays size={12} />} label="卖出" value={`${trade.exitDate} · ${formatPrice(trade.exitPrice)}`} />
                    <TradeField icon={<ShieldCheck size={12} />} label="持仓" value={`${trade.holdingDays} 天`} />
                    <TradeField icon={<ShieldCheck size={12} />} label="原因" value={EXIT_REASON_LABEL[trade.exitReason] || trade.exitReason} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {exitReasons.length > 0 && (
            <div className="border-t border-zinc-800 px-3 py-2">
              <div className="text-[10px] text-zinc-600 mb-1">退出原因统计</div>
              <div className="flex flex-wrap gap-1.5">
                {exitReasons.map(([reason, count]) => (
                  <span key={reason} className="rounded-md border border-zinc-800 bg-zinc-950/40 px-2 py-1 text-[10px] text-zinc-400">
                    {EXIT_REASON_LABEL[reason] || reason}: {count}
                  </span>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function Metric({ label, value, color = 'text-zinc-100' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/35 px-3 py-2">
      <div className="text-[10px] text-zinc-600">{label}</div>
      <div className={`mt-1 font-mono text-lg font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function TradeField({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-zinc-600">{icon}{label}</div>
      <div className="mt-0.5 font-mono text-zinc-300">{value}</div>
    </div>
  );
}
