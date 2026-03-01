import { useEffect, useRef, useState, useMemo, memo } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, CrosshairMode } from 'lightweight-charts';
import type { IChartApi, Time, MouseEventParams } from 'lightweight-charts';
import type { Candle } from '../types';
import { clsx } from 'clsx';
import { TrendingUp, TrendingDown, Calendar, Activity } from 'lucide-react';

interface MiniChartProps {
  candles: Candle[];
  emaMode: 'long' | 'short';
  height?: number;
}

export const MiniChart = memo(function MiniChart({ candles, emaMode: propsEmaMode, height = 120 }: MiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // Local state for EMA mode to allow per-stock overrides
  const [internalEmaMode, setInternalEmaMode] = useState(propsEmaMode);

  const [hoverData, setHoverData] = useState<{
    date: string;
    price: number;
    open: number;
    high: number;
    low: number;
    ema1?: number;
    ema2?: number;
    x: number;
    y: number;
  } | null>(null);

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
    isFiniteNumber(c.close);

  // Sync with global mode whenever it changes
  useEffect(() => {
    setInternalEmaMode(propsEmaMode);
  }, [propsEmaMode]);

  // Memoize data to prevent unnecessary recalculations
  const {
    candleData,
    ema1Data,
    ema2Data,
    firstDate,
    lastDate,
    maxPrice,
    minPrice,
    changePercent
  } = useMemo(() => {
    const validCandles = candles.filter(isValidCandle);

    if (validCandles.length === 0) {
      return {
        candleData: [], ema1Data: [], ema2Data: [],
        periodChange: 0, firstDate: '', lastDate: '',
        maxPrice: 0, minPrice: 0, changePercent: 0
      };
    }

    const cData = validCandles.map(c => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const ema1Key = internalEmaMode === 'long' ? 'ema20' : 'ema5';
    const ema2Key = internalEmaMode === 'long' ? 'ema50' : 'ema10';

    const e1Data = validCandles
      .filter(c => isFiniteNumber(c[ema1Key]))
      .map(c => ({ time: c.time as Time, value: c[ema1Key]! }));

    const e2Data = validCandles
      .filter(c => isFiniteNumber(c[ema2Key]))
      .map(c => ({ time: c.time as Time, value: c[ema2Key]! }));

    // Meta calculations
    const first = validCandles[0];
    const last = validCandles[validCandles.length - 1];
    const change = last.close - first.open;
    const changePct = (change / first.open) * 100;

    // Format dates
    const formatDate = (d: string) => {
      try {
        const date = new Date(d);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      } catch (e) {
        return d;
      }
    };

    const prices = validCandles.flatMap(c => [c.high, c.low]);

    return {
      candleData: cData,
      ema1Data: e1Data,
      ema2Data: e2Data,
      periodChange: change,
      changePercent: changePct,
      firstDate: formatDate(first.time),
      lastDate: formatDate(last.time),
      maxPrice: Math.max(...prices),
      minPrice: Math.min(...prices)
    };
  }, [candles, internalEmaMode]);

  useEffect(() => {
    if (!containerRef.current || candleData.length === 0) return;

    // Cleanup old chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#71717a', // zinc-500
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      timeScale: {
        visible: false,
        borderVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      rightPriceScale: {
        visible: false,
        borderVisible: false,
        scaleMargins: {
          top: 0.2, // increased margin for labels
          bottom: 0.2,
        }
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: {
          width: 1,
          color: 'rgba(255, 255, 255, 0.1)',
          style: 3,
          labelVisible: false,
        },
        horzLine: {
          visible: false,
          labelVisible: false,
        },
      },
      handleScroll: false,
      handleScale: false,
      kineticScroll: { touch: false, mouse: false },
    });

    chartRef.current = chart;

    // Candle Series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', // emerald-500
      downColor: '#f43f5e', // rose-500
      borderUpColor: '#10b981',
      borderDownColor: '#f43f5e',
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });
    candleSeries.setData(candleData);

    // EMA Lines
    const ema1Color = internalEmaMode === 'long' ? '#f59e0b' : '#38bdf8'; // amber-500 : sky-400
    const ema2Color = internalEmaMode === 'long' ? '#8b5cf6' : '#fb923c'; // violet-500 : orange-400

    let line1: any = null;
    if (ema1Data.length > 0) {
      line1 = chart.addSeries(LineSeries, {
        color: ema1Color,
        lineWidth: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line1.setData(ema1Data);
    }

    let line2: any = null;
    if (ema2Data.length > 0) {
      line2 = chart.addSeries(LineSeries, {
        color: ema2Color,
        lineWidth: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line2.setData(ema2Data);
    }

    chart.timeScale().fitContent();

    // Crosshair Handler
    const handleCrosshairMove = (param: MouseEventParams) => {
      const container = containerRef.current;
      if (
        !param.time ||
        param.point === undefined ||
        !param.point.x ||
        !param.point.y ||
        !container
      ) {
        setHoverData(null);
        return;
      }

      const dataPoint = param.seriesData.get(candleSeries) as any;
      if (!dataPoint) {
        setHoverData(null);
        return;
      }

      const ema1Val = line1 ? param.seriesData.get(line1) : undefined;
      const ema2Val = line2 ? param.seriesData.get(line2) : undefined;

      // Note: param.point is relative to the chart canvas
      setHoverData({
        date: dataPoint.time.toString(),
        price: dataPoint.close,
        open: dataPoint.open,
        high: dataPoint.high,
        low: dataPoint.low,
        ema1: ema1Val ? (ema1Val as any).value : undefined,
        ema2: ema2Val ? (ema2Val as any).value : undefined,
        x: param.point.x,
        y: param.point.y,
      });
    };

    chart.subscribeCrosshairMove(handleCrosshairMove);

    // Resize Observer to handle container resizing
    const resizeObserver = new ResizeObserver(entries => {
      if (entries.length === 0 || !entries[0].contentRect || !chartRef.current) return;
      const { width } = entries[0].contentRect;
      chartRef.current.applyOptions({ width });
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      if (chartRef.current) {
        chartRef.current.unsubscribeCrosshairMove(handleCrosshairMove);
        chartRef.current.remove();
        chartRef.current = null;
      }
      resizeObserver.disconnect();
    };
  }, [candleData, ema1Data, ema2Data, internalEmaMode, height]);

  if (candleData.length === 0) {
    return (
      <div className="h-[120px] flex items-center justify-center text-zinc-600 text-xs bg-zinc-900/30 rounded-lg border border-zinc-800/50">
        No Data
      </div>
    );
  }

  const isPositive = changePercent >= 0;

  return (
    <div className="relative group/chart p-3 rounded-xl bg-zinc-900/30 border border-zinc-800/50 backdrop-blur-sm transition-all hover:bg-zinc-900/50 hover:border-zinc-700/50 hover:shadow-lg hover:shadow-black/20">
      {/* Header Info */}
      <div className="flex justify-between items-center mb-2 px-1">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-[10px] sm:text-xs text-zinc-400 font-medium bg-zinc-800/50 px-2 py-0.5 rounded-md border border-zinc-700/30">
            <Calendar size={12} className="text-zinc-500" />
            <span>{firstDate} - {lastDate}</span>
            <span className="text-zinc-600 mx-1">|</span>
            <span className="text-zinc-500">{candleData.length}D</span>
          </div>

          <button
            onClick={(e) => {
              e.stopPropagation();
              setInternalEmaMode(prev => prev === 'long' ? 'short' : 'long');
            }}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-md border border-zinc-700/50 bg-zinc-800/20 text-[10px] text-zinc-500 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-800/50 transition-all group/ema"
            title="点击切换当前股票均线模式"
          >
            <Activity size={10} className="text-zinc-600 group-hover/ema:text-emerald-500 transition-colors" />
            <span className="font-mono tracking-tighter">{internalEmaMode === 'long' ? '20/50' : '5/10'}</span>
          </button>
        </div>

        <div className={clsx(
          "flex items-center gap-1 text-[10px] sm:text-xs font-mono font-bold px-2 py-0.5 rounded-md border transition-colors",
          isPositive
            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
            : "bg-rose-500/10 text-rose-400 border-rose-500/20"
        )}>
          {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {isPositive ? '+' : ''}{changePercent.toFixed(2)}%
        </div>
      </div>

      {/* Chart Container */}
      <div className="relative">
        <div ref={containerRef} className="w-full relative z-10 box-border" style={{ height }} />

        {/* Min/Max Price Labels (Background) - Positioned inside chart area */}
        <div className="absolute top-0 right-1 text-[9px] text-zinc-600/50 font-mono pointer-events-none select-none z-0">
          H: {maxPrice.toFixed(2)}
        </div>
        <div className="absolute bottom-0 right-1 text-[9px] text-zinc-600/50 font-mono pointer-events-none select-none z-0">
          L: {minPrice.toFixed(2)}
        </div>

        {/* Improved Tooltip */}
        {hoverData && (() => {
          const tooltipWidth = 140; // Approximate width
          const chartWidth = containerRef.current?.offsetWidth || 0;

          // Calculate tooltip position
          const leftPos = Math.max(0, Math.min(chartWidth - tooltipWidth, hoverData.x - (tooltipWidth / 2)));

          // Calculate arrow position relative to tooltip
          const arrowPos = Math.max(10, Math.min(tooltipWidth - 14, hoverData.x - leftPos));

          return (
            <div
              className="absolute z-50 pointer-events-none flex flex-col items-start transition-all duration-75 ease-out"
              style={{
                top: -10,
                transform: 'translateY(-100%)',
                left: leftPos,
                width: tooltipWidth
              }}
            >
              <div className="w-full bg-zinc-950/90 border border-zinc-700/80 rounded-lg shadow-xl shadow-black/60 p-2 text-[10px] backdrop-blur-md animate-in fade-in zoom-in-95 leading-tight">
                <div className="flex justify-between items-center mb-1 pb-1 border-b border-zinc-800">
                  <span className="text-zinc-400 font-medium whitespace-nowrap">{hoverData.date}</span>
                  <span className={clsx("font-bold ml-2",
                    hoverData.price >= hoverData.open ? "text-emerald-400" : "text-rose-400"
                  )}>
                    {((hoverData.price - hoverData.open) / hoverData.open * 100).toFixed(2)}%
                  </span>
                </div>

                <div className="space-y-0.5">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Close</span>
                    <span className={clsx("font-mono font-medium", hoverData.price >= hoverData.open ? "text-emerald-400" : "text-rose-400")}>
                      {hoverData.price.toFixed(2)}
                    </span>
                  </div>

                  {hoverData.ema1 && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: internalEmaMode === 'long' ? '#f59e0b' : '#38bdf8' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {internalEmaMode === 'long' ? 'EMA20' : 'EMA5'}
                      </span>
                      <span className="font-mono text-zinc-300">
                        {hoverData.ema1.toFixed(2)}
                      </span>
                    </div>
                  )}

                  {hoverData.ema2 && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: internalEmaMode === 'long' ? '#8b5cf6' : '#fb923c' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {internalEmaMode === 'long' ? 'EMA50' : 'EMA10'}
                      </span>
                      <span className="font-mono text-zinc-300">
                        {hoverData.ema2.toFixed(2)}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Tooltip Arrow */}
              <div
                className="w-2 h-2 bg-zinc-950 border-r border-b border-zinc-700/80 rotate-45 -mt-1 z-50 relative"
                style={{
                  left: arrowPos
                }}
              />
            </div>
          );
        })()}
      </div>
    </div>
  );
});
