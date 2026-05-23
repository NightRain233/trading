import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries, CrosshairMode, LineStyle } from 'lightweight-charts';
import type { Time, IChartApi, LineWidth } from 'lightweight-charts';
import type { StockData, Candle } from '../types';
import { X, Activity, Calendar, LayoutGrid, Info } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { fetchStockData } from '../utils';

interface ChartModalProps {
  stock: StockData | null;
  onClose: () => void;
}

type MainInd = 'EMA' | 'BOLL';
type TFrame = 'D' | 'W';

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const isValidDateString = (value: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));

const isBusinessDay = (value: unknown): value is Time =>
  typeof value === 'object' &&
  value !== null &&
  isFiniteNumber((value as any).year) &&
  isFiniteNumber((value as any).month) &&
  isFiniteNumber((value as any).day);

const isValidTime = (value: unknown): value is Time =>
  (typeof value === 'string' && isValidDateString(value)) ||
  (typeof value === 'number' && Number.isFinite(value)) ||
  isBusinessDay(value);

const isValidCandle = (c: Candle) =>
  isValidTime(c.time) &&
  isFiniteNumber(c.open) &&
  isFiniteNumber(c.high) &&
  isFiniteNumber(c.low) &&
  isFiniteNumber(c.close) &&
  c.close > 0;

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-[10px] sm:text-xs font-semibold transition-all duration-200 ${active ? 'bg-zinc-100 text-zinc-950 shadow-sm' : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50'}`}
    >
      {children}
    </button>
  );
}

export function ChartModal({ stock: initialStock, onClose }: ChartModalProps) {
  const [stock, setStock] = useState<StockData | null>(initialStock);
  const [timeframe, setTimeframe] = useState<TFrame>('D');
  const [mainInd, setMainInd] = useState<MainInd>('EMA');
  const [hoverDate, setHoverDate] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 640);

  // Container refs
  const priceRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const kdjRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const atrRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 640);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (!initialStock) return;
    let isMounted = true;
    fetchStockData(initialStock.symbol).then(data => {
      if (data && isMounted) setStock(data);
    });
    return () => { isMounted = false; };
  }, [initialStock?.symbol]);

  useEffect(() => {
    if (!stock || !priceRef.current || !rsiRef.current || !kdjRef.current || !macdRef.current || !atrRef.current) return;

    const containers = [priceRef.current, rsiRef.current, kdjRef.current, macdRef.current, atrRef.current];

    // CRITICAL FIX: Clear the containers explicitly before creating new charts
    // This prevents double rendering when useEffect triggers multiple times
    containers.forEach(container => {
      if (container) container.innerHTML = '';
    });

    const charts: IChartApi[] = [];

    const commonOptions = {
      layout: {
        background: { type: ColorType.Solid, color: '#09090b' },
        textColor: '#a1a1aa',
        fontSize: isMobile ? 10 : 11,
        fontFamily: 'Inter, system-ui, sans-serif',
      },
      grid: {
        vertLines: { color: '#18181b', style: LineStyle.Dashed },
        horzLines: { color: '#18181b', style: LineStyle.Dashed },
      },
      timeScale: {
        borderColor: '#27272a',
        visible: false,
        barSpacing: 4,
        minBarSpacing: 2,
      },
      rightPriceScale: {
        borderColor: '#27272a',
        scaleMargins: { top: 0.1, bottom: 0.15 },
        autoScale: true,
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: '#52525b', width: 1 as LineWidth, style: LineStyle.LargeDashed },
        horzLine: { color: '#52525b', width: 1 as LineWidth, style: LineStyle.LargeDashed },
      },
      handleScroll: { vertTouchDrag: false },
    };

    // Responsive Heights
    const pHeight = isMobile ? 280 : 400;
    const sHeight = isMobile ? 100 : 130;

    charts[0] = createChart(priceRef.current, { ...commonOptions, height: pHeight });
    charts[1] = createChart(rsiRef.current, { ...commonOptions, height: sHeight });
    charts[2] = createChart(kdjRef.current, { ...commonOptions, height: sHeight });
    charts[3] = createChart(macdRef.current, { ...commonOptions, height: sHeight });
    charts[4] = createChart(atrRef.current, { ...commonOptions, height: sHeight, timeScale: { ...commonOptions.timeScale, visible: true } });

    const candles = timeframe === 'D' ? stock.candles : (stock.weekly_candles || []);
    if (!candles || candles.length === 0) return;

    // Filter valid data to avoid 0-scaling artifacts
    const validCandles = candles.filter(isValidCandle);

    // 1. Price
    const candleSeries = charts[0].addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderVisible: false,
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e'
    });
    candleSeries.setData(validCandles.map((c: Candle) => ({
      time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close
    })));

    // 2. Volume
    const volumeSeries = charts[0].addSeries(HistogramSeries, {
      color: '#3f3f46',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    charts[0].priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 }
    });
    volumeSeries.setData(validCandles.map((c: Candle) => {
      const volume = isFiniteNumber(c.volume) ? c.volume : 0;
      return {
        time: c.time as Time,
        value: volume,
        color: c.close >= c.open ? '#ef444422' : '#22c55e22'
      };
    }));

    // 3. Technical Indicators
    if (mainInd === 'EMA') {
      const e20 = charts[0].addSeries(LineSeries, { color: '#0ea5e9', lineWidth: 1 as LineWidth, priceLineVisible: false });
      const e50 = charts[0].addSeries(LineSeries, { color: '#eab308', lineWidth: 1 as LineWidth, priceLineVisible: false });
      e20.setData(validCandles.filter(c => isFiniteNumber(c.ema20) && c.ema20 > 0).map((c: Candle) => ({ time: c.time as Time, value: c.ema20! })));
      e50.setData(validCandles.filter(c => isFiniteNumber(c.ema50) && c.ema50 > 0).map((c: Candle) => ({ time: c.time as Time, value: c.ema50! })));
    } else {
      const bup = charts[0].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth, priceLineVisible: false });
      const bmid = charts[0].addSeries(LineSeries, { color: '#71717a', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dashed, priceLineVisible: false });
      const blow = charts[0].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth, priceLineVisible: false });
      bup.setData(validCandles.filter(c => isFiniteNumber(c.boll_upper) && c.boll_upper > 0).map((c: Candle) => ({ time: c.time as Time, value: c.boll_upper! })));
      bmid.setData(validCandles.filter(c => isFiniteNumber(c.boll_mid) && c.boll_mid > 0).map((c: Candle) => ({ time: c.time as Time, value: c.boll_mid! })));
      blow.setData(validCandles.filter(c => isFiniteNumber(c.boll_lower) && c.boll_lower > 0).map((c: Candle) => ({ time: c.time as Time, value: c.boll_lower! })));
    }

    // RSI
    const rsiLine = charts[1].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth });
    rsiLine.setData(validCandles.filter(c => isFiniteNumber(c.rsi) && c.rsi > 0).map((c: Candle) => ({ time: c.time as Time, value: c.rsi! })));
    const ob = charts[1].addSeries(LineSeries, { color: '#f43f5e', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false });
    const os = charts[1].addSeries(LineSeries, { color: '#10b981', lineWidth: 1 as LineWidth, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false });
    ob.setData(validCandles.map((c: Candle) => ({ time: c.time as Time, value: stock.rsiOverbought || 70 })));
    os.setData(validCandles.map((c: Candle) => ({ time: c.time as Time, value: stock.rsiOversold || 30 })));

    // KDJ
    const kLine = charts[2].addSeries(LineSeries, { color: '#ffffff', lineWidth: 1 as LineWidth });
    const dLine = charts[2].addSeries(LineSeries, { color: '#eab308', lineWidth: 1 as LineWidth });
    const jLine = charts[2].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth });
    kLine.setData(validCandles.filter(c => isFiniteNumber(c.k) && c.k > 0).map((c: Candle) => ({ time: c.time as Time, value: c.k! })));
    dLine.setData(validCandles.filter(c => isFiniteNumber(c.d) && c.d > 0).map((c: Candle) => ({ time: c.time as Time, value: c.d! })));
    jLine.setData(validCandles.filter(c => isFiniteNumber(c.j) && c.j > 0).map((c: Candle) => ({ time: c.time as Time, value: c.j! })));

    // MACD
    const macdHist = charts[3].addSeries(HistogramSeries, { lastValueVisible: false });
    const macdZero = charts[3].addSeries(LineSeries, {
      color: '#71717a88',
      lineWidth: 1 as LineWidth,
      lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const macdDif = charts[3].addSeries(LineSeries, { color: '#38bdf8', lineWidth: 1 as LineWidth });
    const macdDea = charts[3].addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1 as LineWidth });
    macdZero.setData(validCandles.map((c: Candle) => ({ time: c.time as Time, value: 0 })));
    macdHist.setData(validCandles.filter(c => isFiniteNumber(c.macd_hist)).map((c: Candle) => ({
      time: c.time as Time, value: c.macd_hist!, color: c.macd_hist! >= 0 ? '#ef444466' : '#22c55e66'
    })));
    macdDif.setData(validCandles.filter(c => isFiniteNumber(c.macd_dif)).map((c: Candle) => ({ time: c.time as Time, value: c.macd_dif! })));
    macdDea.setData(validCandles.filter(c => isFiniteNumber(c.macd_dea)).map((c: Candle) => ({ time: c.time as Time, value: c.macd_dea! })));

    // ATR
    const atrLine = charts[4].addSeries(LineSeries, { color: '#fb923c', lineWidth: 1 as LineWidth });
    atrLine.setData(validCandles.filter(c => isFiniteNumber(c.atr) && c.atr > 0).map((c: Candle) => ({ time: c.time as Time, value: c.atr! })));

    // Sync
    let isBroadcasting = false;
    charts.forEach((sourceChart, sourceIdx) => {
      sourceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (isBroadcasting || !range) return;
        isBroadcasting = true;
        charts.forEach((targetChart, targetIdx) => {
          if (sourceIdx !== targetIdx) targetChart.timeScale().setVisibleLogicalRange(range);
        });
        isBroadcasting = false;
      });

      sourceChart.subscribeCrosshairMove(param => {
        if (isBroadcasting) return;
        isBroadcasting = true;
        const time = param.time;
        if (time) setHoverDate(time as string);
        charts.forEach((targetChart, targetIdx) => {
          if (sourceIdx !== targetIdx) {
            if (!param.point || !time) targetChart.clearCrosshairPosition();
            else targetChart.setCrosshairPosition(0, time, (targetChart as any)._series && (targetChart as any)._series[0] ? (targetChart as any)._series[0] : undefined);
          }
        });
        isBroadcasting = false;
      });
    });

    requestAnimationFrame(() => charts.forEach(c => c.timeScale().fitContent()));

    const handleResize = () => {
      charts.forEach((c, idx) => {
        if (containers[idx]) c.applyOptions({ width: containers[idx].clientWidth });
      });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      charts.forEach(c => {
        try { c.remove(); } catch (e) { }
      });
    };
  }, [stock, timeframe, mainInd, isMobile]);

  if (!stock) return null;

  return (
    <div className="modal-overlay fixed inset-0 z-50 flex items-center justify-center sm:p-4 animate-fade-in-scale">
      <div className="bg-zinc-950 w-full sm:max-w-6xl sm:rounded-2xl border-x sm:border border-zinc-800/50 shadow-2xl overflow-hidden flex flex-col h-full sm:h-[95vh]">

        {/* Compact Header */}
        {/* Top accent line */}
        <div className="h-[1px] bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />

        <div className="px-4 py-3 border-b border-zinc-800/50 bg-zinc-900/20 backdrop-blur-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-4 min-w-0">
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <h2 className="text-xl sm:text-2xl font-black text-white uppercase tracking-tight">{stock.symbol}</h2>
                <div className="px-2 py-0.5 rounded-lg bg-zinc-800/60 text-[10px] text-zinc-400 font-mono tracking-wider border border-zinc-700/30">{stock.name}</div>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`text-lg sm:text-xl font-mono font-bold ${(stock.changePercent || 0) >= 0 ? 'price-up' : 'price-down'}`}>
                  {(stock.price || 0).toFixed(2)}
                </span>
                <span className={`text-xs font-mono font-medium ${(stock.changePercent || 0) >= 0 ? 'text-emerald-500/80' : 'text-rose-500/80'}`}>
                  {(stock.changePercent || 0) >= 0 ? '▲' : '▼'} {Math.abs(stock.changePercent || 0).toFixed(2)}%
                </span>
              </div>
            </div>

            <div className="hidden sm:flex h-8 w-px bg-zinc-800/50 mx-2"></div>

            <div className="flex flex-wrap gap-2">
              <StatusBadge status={stock.trend} type="trend" />
              <StatusBadge status={stock.signal} type="signal" />
              {hoverDate && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-emerald-500/5 border border-emerald-500/20 text-emerald-400 text-[10px] font-mono shadow-inner">
                  <Calendar size={12} className="opacity-70" /> {hoverDate}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 bg-zinc-900/50 p-1 rounded-xl border border-zinc-800/50">
              <div className="flex p-0.5 bg-zinc-950/50 rounded-lg">
                <TabButton onClick={() => setTimeframe('D')} active={timeframe === 'D'}>D</TabButton>
                <TabButton onClick={() => setTimeframe('W')} active={timeframe === 'W'}>W</TabButton>
              </div>
              <div className="w-px h-4 bg-zinc-800/50"></div>
              <div className="flex p-0.5 bg-zinc-950/50 rounded-lg">
                <TabButton onClick={() => setMainInd('EMA')} active={mainInd === 'EMA'}>EMA</TabButton>
                <TabButton onClick={() => setMainInd('BOLL')} active={mainInd === 'BOLL'}>BOLL</TabButton>
              </div>
            </div>

            <button onClick={onClose} className="p-2 hover:bg-zinc-800/80 rounded-xl text-zinc-500 hover:text-white transition-all duration-200 border border-transparent hover:border-zinc-700/30">
              <X size={22} />
            </button>
          </div>
        </div>

        {/* Charts - Stacking */}
        <div className="flex-1 overflow-y-auto bg-zinc-950 custom-scrollbar">
          <div className="relative border-b border-zinc-900">
            <div className="absolute top-3 left-4 z-10 text-[10px] uppercase tracking-widest text-zinc-600 font-bold pointer-events-none flex items-center gap-2">
              <Activity size={12} className="text-emerald-500/50" /> Price & Volume
            </div>
            <div className="w-full" ref={priceRef} />
          </div>

          <div className="relative border-b border-zinc-900">
            <div className="absolute top-3 left-4 z-10 text-[10px] uppercase tracking-widest text-zinc-600 font-bold pointer-events-none flex items-center gap-2">
              <LayoutGrid size={12} className="text-purple-500/50" /> RSI
            </div>
            <div className="w-full" ref={rsiRef} />
          </div>

          <div className="relative border-b border-zinc-900">
            <div className="absolute top-3 left-4 z-10 text-[10px] uppercase tracking-widest text-zinc-600 font-bold pointer-events-none flex items-center gap-2">
              <LayoutGrid size={12} className="text-amber-500/50" /> KDJ
            </div>
            <div className="w-full" ref={kdjRef} />
          </div>

          <div className="relative border-b border-zinc-900">
            <div className="absolute top-3 left-4 z-10 text-[10px] uppercase tracking-widest text-zinc-600 font-bold pointer-events-none flex items-center gap-2">
              <LayoutGrid size={12} className="text-blue-500/50" /> MACD
            </div>
            <div className="w-full" ref={macdRef} />
          </div>

          <div className="relative">
            <div className="absolute top-3 left-4 z-10 text-[10px] uppercase tracking-widest text-zinc-600 font-bold pointer-events-none flex items-center gap-2">
              <Info size={12} className="text-orange-500/50" /> ATR
            </div>
            <div className="w-full" ref={atrRef} />
          </div>

          <div className="h-10 invisible" />
        </div>
      </div>
    </div>
  );
}
