import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { RefreshCw } from 'lucide-react';

const API_BASE = '/api';

interface WeeklyCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  boll_upper: number | null;
  boll_mid: number | null;
  boll_lower: number | null;
  ma30: number | null;
  ma5: number | null;
  macd_dif: number | null;
  macd_dea: number | null;
  macd_hist: number | null;
}

interface BreakoutItem {
  symbol: string;
  alias: string;
  state: 'breakout' | 'squeeze' | 'exit' | 'neutral';
  stopPrice: number | null;
  candles: WeeklyCandle[];
}

const STATE_LABEL: Record<string, string> = {
  breakout: '突破', squeeze: '挤压', exit: '离场', neutral: '观望',
};
const STATE_COLOR: Record<string, string> = {
  breakout: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10',
  squeeze: 'text-amber-400 border-amber-500/40 bg-amber-500/10',
  exit: 'text-red-400 border-red-500/40 bg-red-500/10',
  neutral: 'text-zinc-500 border-zinc-700 bg-zinc-800/30',
};

function MiniWeeklyChart({ candles, showMid, showMacd, showMa5 }: { candles: WeeklyCandle[]; showMid: boolean; showMacd: boolean; showMa5: boolean }) {
  const priceRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!priceRef.current || candles.length === 0) return;

    const priceChart = createChart(priceRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
      grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
      width: priceRef.current.clientWidth,
      height: 160,
      timeScale: { borderColor: '#3f3f46', timeVisible: false, visible: !showMacd },
      rightPriceScale: { borderColor: '#3f3f46', scaleMargins: { top: 0.1, bottom: 0.1 } },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });

    const candleSeries = priceChart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderUpColor: '#10b981', borderDownColor: '#ef4444',
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    candleSeries.setData(candles.map(c => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));

    const upperS = priceChart.addSeries(LineSeries, { color: '#6366f1', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    upperS.setData(candles.filter(c => c.boll_upper != null).map(c => ({ time: c.time as Time, value: c.boll_upper! })));

    const lowerS = priceChart.addSeries(LineSeries, { color: '#6366f1', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    lowerS.setData(candles.filter(c => c.boll_lower != null).map(c => ({ time: c.time as Time, value: c.boll_lower! })));

    if (showMid) {
      const midS = priceChart.addSeries(LineSeries, { color: '#a78bfa', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
      midS.setData(candles.filter(c => c.boll_mid != null).map(c => ({ time: c.time as Time, value: c.boll_mid! })));
    }

    const ma30S = priceChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    ma30S.setData(candles.filter(c => c.ma30 != null).map(c => ({ time: c.time as Time, value: c.ma30! })));

    if (showMa5) {
      const ma5S = priceChart.addSeries(LineSeries, { color: '#34d399', lineWidth: 1, lineStyle: 1, priceLineVisible: false, lastValueVisible: false });
      ma5S.setData(candles.filter(c => c.ma5 != null).map(c => ({ time: c.time as Time, value: c.ma5! })));
    }

    priceChart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (priceRef.current) priceChart.applyOptions({ width: priceRef.current.clientWidth });
    });
    ro.observe(priceRef.current);

    // MACD chart
    let macdChart: ReturnType<typeof createChart> | null = null;
    let macdRo: ResizeObserver | null = null;
    if (showMacd && macdRef.current) {
      macdChart = createChart(macdRef.current, {
        layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
        grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
        width: macdRef.current.clientWidth,
        height: 70,
        timeScale: { borderColor: '#3f3f46', timeVisible: false },
        rightPriceScale: { borderColor: '#3f3f46', scaleMargins: { top: 0.1, bottom: 0.1 } },
        crosshair: { mode: 0 },
        handleScroll: false,
        handleScale: false,
      });

      const histS = macdChart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false });
      histS.setData(
        candles
          .filter(c => c.macd_hist != null)
          .map(c => ({ time: c.time as Time, value: c.macd_hist!, color: c.macd_hist! >= 0 ? '#10b981' : '#ef4444' }))
      );

      const difS = macdChart.addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      difS.setData(candles.filter(c => c.macd_dif != null).map(c => ({ time: c.time as Time, value: c.macd_dif! })));

      const deaS = macdChart.addSeries(LineSeries, { color: '#f97316', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      deaS.setData(candles.filter(c => c.macd_dea != null).map(c => ({ time: c.time as Time, value: c.macd_dea! })));

      macdChart.timeScale().fitContent();

      macdRo = new ResizeObserver(() => {
        if (macdRef.current && macdChart) macdChart.applyOptions({ width: macdRef.current.clientWidth });
      });
      macdRo.observe(macdRef.current);
    }

    return () => {
      ro.disconnect();
      priceChart.remove();
      macdRo?.disconnect();
      macdChart?.remove();
    };
  }, [candles, showMid, showMacd, showMa5]);

  return (
    <div className="w-full">
      <div ref={priceRef} className="w-full" />
      {showMacd && <div ref={macdRef} className="w-full border-t border-zinc-800/60" />}
    </div>
  );
}

export function WeeklyBreakoutPage() {
  const [items, setItems] = useState<BreakoutItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showMid, setShowMid] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [showMa5, setShowMa5] = useState(false);
  const [filter, setFilter] = useState<'all' | 'breakout' | 'squeeze' | 'exit'>('all');

  async function load() {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/weekly-breakout/scan`);
      setItems(await r.json());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const ORDER: BreakoutItem['state'][] = ['breakout', 'squeeze', 'exit', 'neutral'];
  const displayed = items
    .filter(i => filter === 'all' || i.state === filter)
    .sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state));

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <span className="text-sm font-semibold text-zinc-300">周线BB突破扫描</span>
        <div className="flex gap-1.5">
          {(['all', 'breakout', 'squeeze', 'exit'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
                filter === f
                  ? f === 'all' ? 'bg-zinc-700 border-zinc-600 text-zinc-200' : STATE_COLOR[f]
                  : 'btn-glass text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {f === 'all' ? '全部' : STATE_LABEL[f]}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowMid(v => !v)}
          className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
            showMid ? 'bg-violet-500/10 border-violet-500/40 text-violet-400' : 'btn-glass text-zinc-500 hover:text-zinc-300'
          }`}
        >
          BB中轨
        </button>
        <button
          onClick={() => setShowMa5(v => !v)}
          className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
            showMa5 ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400' : 'btn-glass text-zinc-500 hover:text-zinc-300'
          }`}
        >
          MA5
        </button>
        <button
          onClick={() => setShowMacd(v => !v)}
          className={`px-2.5 py-1 text-xs rounded-lg border font-medium transition-all ${
            showMacd ? 'bg-blue-500/10 border-blue-500/40 text-blue-400' : 'btn-glass text-zinc-500 hover:text-zinc-300'
          }`}
        >
          MACD
        </button>
        <button
          onClick={load}
          className={`ml-auto p-2 rounded-xl text-zinc-500 hover:text-emerald-400 btn-glass ${loading ? 'animate-spin' : ''}`}
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {loading && items.length === 0 && (
        <div className="text-zinc-500 text-sm text-center py-16">扫描中…</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {displayed.map(item => (
          <div key={item.symbol} className="rounded-xl border border-zinc-800 bg-zinc-900/60 overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold text-zinc-200">{item.symbol}</span>
                {item.alias && <span className="text-xs text-zinc-500">{item.alias}</span>}
              </div>
              <div className="flex items-center gap-2">
                {item.stopPrice != null && (
                  <span className="text-[10px] text-zinc-500 font-mono">止损 {item.stopPrice.toFixed(3)}</span>
                )}
                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ${STATE_COLOR[item.state]}`}>
                  {STATE_LABEL[item.state]}
                </span>
              </div>
            </div>
            <div className="px-1 py-1">
              {item.candles.length > 0
                ? <MiniWeeklyChart candles={item.candles} showMid={showMid} showMacd={showMacd} showMa5={showMa5} />
                : <div className="h-40 flex items-center justify-center text-zinc-600 text-xs">无数据</div>
              }
            </div>
          </div>
        ))}
      </div>

      {!loading && displayed.length === 0 && (
        <div className="text-zinc-600 text-sm text-center py-16">暂无符合条件的标的</div>
      )}
    </div>
  );
}
