import { useEffect, useRef, useState, useMemo, memo } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries, CrosshairMode } from 'lightweight-charts';
import type { IChartApi, Time, MouseEventParams } from 'lightweight-charts';
import type { Candle, Timeframe } from '../types';
import { clsx } from 'clsx';
import { TrendingUp, TrendingDown, Calendar, Activity } from 'lucide-react';

interface MiniChartProps {
  candles: Candle[];
  timeframe: Timeframe;
  emaMode: 'long' | 'short' | 'boll';
  height?: number;
}

const splitTimeKey = (time: Time): string | null => {
  if (typeof time === 'string') return time;
  if (typeof time === 'number') {
    const d = new Date(time * 1000);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString().slice(0, 10);
  }
  if (typeof time === 'object' && time !== null && 'year' in time && 'month' in time && 'day' in time) {
    const year = (time as any).year;
    const month = (time as any).month;
    const day = (time as any).day;
    if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
    return `${String(year)}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }
  return null;
};

export const MiniChart = memo(function MiniChart({ candles, timeframe, emaMode: propsEmaMode, height = 170 }: MiniChartProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  // Stabilize candles reference — only update when content actually changes
  const candlesRef = useRef(candles);
  const stableCandles = useMemo(() => {
    const prev = candlesRef.current;
    if (prev.length === candles.length && prev[0]?.time === candles[0]?.time && prev[prev.length - 1]?.close === candles[candles.length - 1]?.close) {
      return prev;
    }
    candlesRef.current = candles;
    return candles;
  }, [candles]);

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
    bollUpper?: number;
    bollLower?: number;
    ma30?: number;
    macdDif?: number;
    macdDea?: number;
    macdHist?: number;
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

  const ema1Key = internalEmaMode === 'long' ? 'ema20' : internalEmaMode === 'short' ? 'ema5' : null;
  const ema2Key = internalEmaMode === 'long' ? 'ema50' : internalEmaMode === 'short' ? 'ema10' : null;

  // Sync with global mode whenever it changes
  useEffect(() => {
    setInternalEmaMode(propsEmaMode);
  }, [propsEmaMode]);

  const macdPaneHeight = Math.max(56, Math.round(height * 0.4));
  const mainPaneHeight = Math.max(86, height - macdPaneHeight - 6);
  const totalChartHeight = mainPaneHeight + macdPaneHeight + 6;

  // Memoize data to prevent unnecessary recalculations
  const {
    candleData,
    ema1Data,
    ema2Data,
    bollUpperData,
    bollLowerData,
    ma30Data,
    macdHistData,
    macdDifData,
    macdDeaData,
    candleByTime,
    firstDate,
    lastDate,
    maxPrice,
    minPrice,
    changePercent,
  } = useMemo(() => {
    const validCandles = stableCandles.filter(isValidCandle);

    if (validCandles.length === 0) {
      return {
        candleData: [],
        ema1Data: [],
        ema2Data: [],
        bollUpperData: [],
        bollLowerData: [],
        ma30Data: [],
        macdHistData: [],
        macdDifData: [],
        macdDeaData: [],
        candleByTime: new Map<string, Candle>(),
        changePercent: 0,
        firstDate: '',
        lastDate: '',
        maxPrice: 0,
        minPrice: 0,
      };
    }

    const cData = validCandles.map(c => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const e1Data = ema1Key
      ? validCandles.filter(c => isFiniteNumber(c[ema1Key])).map(c => ({ time: c.time as Time, value: c[ema1Key]! }))
      : [];

    const e2Data = ema2Key
      ? validCandles.filter(c => isFiniteNumber(c[ema2Key])).map(c => ({ time: c.time as Time, value: c[ema2Key]! }))
      : [];

    const bUpperData = validCandles
      .filter(c => isFiniteNumber(c.boll_upper))
      .map(c => ({ time: c.time as Time, value: c.boll_upper! }));

    const bLowerData = validCandles
      .filter(c => isFiniteNumber(c.boll_lower))
      .map(c => ({ time: c.time as Time, value: c.boll_lower! }));

    const m30Data = validCandles
      .filter(c => isFiniteNumber(c.ma30))
      .map(c => ({ time: c.time as Time, value: c.ma30! }));

    const mHistData = validCandles
      .filter(c => isFiniteNumber(c.macd_hist))
      .map(c => ({
        time: c.time as Time,
        value: c.macd_hist!,
        color: c.macd_hist! >= 0 ? '#ef444466' : '#22c55e66',
      }));

    const mDifData = validCandles
      .filter(c => isFiniteNumber(c.macd_dif))
      .map(c => ({ time: c.time as Time, value: c.macd_dif! }));

    const mDeaData = validCandles
      .filter(c => isFiniteNumber(c.macd_dea))
      .map(c => ({ time: c.time as Time, value: c.macd_dea! }));

    const byTime = new Map<string, Candle>();
    validCandles.forEach(c => {
      byTime.set(c.time, c);
    });

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
      } catch (_e) {
        return d;
      }
    };

    const prices = validCandles.flatMap(c => [c.high, c.low]);

    return {
      candleData: cData,
      ema1Data: e1Data,
      ema2Data: e2Data,
      bollUpperData: bUpperData,
      bollLowerData: bLowerData,
      ma30Data: m30Data,
      macdHistData: mHistData,
      macdDifData: mDifData,
      macdDeaData: mDeaData,
      candleByTime: byTime,
      changePercent: changePct,
      firstDate: formatDate(first.time),
      lastDate: formatDate(last.time),
      maxPrice: Math.max(...prices),
      minPrice: Math.min(...prices),
    };
  }, [stableCandles, ema1Key, ema2Key]);

  useEffect(() => {
    if (!mainContainerRef.current || !macdContainerRef.current || !wrapperRef.current || candleData.length === 0) return;

    if (mainChartRef.current) {
      mainChartRef.current.remove();
      mainChartRef.current = null;
    }
    if (macdChartRef.current) {
      macdChartRef.current.remove();
      macdChartRef.current = null;
    }

    const commonChartOptions: any = {
      width: wrapperRef.current.clientWidth,
      layout: {
        background: { type: ColorType.Solid as const, color: 'transparent' },
        textColor: '#71717a',
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
        barSpacing: 4,
        minBarSpacing: 2,
      },
      rightPriceScale: {
        visible: false,
        borderVisible: false,
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
    };

    const mainChart = createChart(mainContainerRef.current, {
      ...commonChartOptions,
      height: mainPaneHeight,
      rightPriceScale: {
        ...commonChartOptions.rightPriceScale,
        scaleMargins: {
          top: 0.15,
          bottom: 0.15,
        },
      },
    });

    const macdChart = createChart(macdContainerRef.current, {
      ...commonChartOptions,
      height: macdPaneHeight,
      crosshair: {
        ...commonChartOptions.crosshair,
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        ...commonChartOptions.rightPriceScale,
        scaleMargins: {
          top: 0.18,
          bottom: 0.18,
        },
      },
    });

    mainChartRef.current = mainChart;
    macdChartRef.current = macdChart;

    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    candleSeries.setData(candleData);

    const ema1Color = internalEmaMode === 'long' ? '#f59e0b' : '#38bdf8';
    const ema2Color = internalEmaMode === 'long' ? '#8b5cf6' : '#fb923c';

    if (internalEmaMode === 'boll') {
      const bollOpts = {
        lineWidth: 1 as const,
        lineStyle: 2,
        crosshairMarkerVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
        autoscaleInfoProvider: () => null,
      };
      if (bollUpperData.length > 0) {
        const bUp = mainChart.addSeries(LineSeries, { ...bollOpts, color: '#f87171' });
        bUp.setData(bollUpperData);
      }
      if (bollLowerData.length > 0) {
        const bLow = mainChart.addSeries(LineSeries, { ...bollOpts, color: '#34d399' });
        bLow.setData(bollLowerData);
      }
      if (ma30Data.length > 0) {
        const m30 = mainChart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
        m30.setData(ma30Data);
      }
    } else {
      if (ema1Data.length > 0) {
        const line1 = mainChart.addSeries(LineSeries, { color: ema1Color, lineWidth: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
        line1.setData(ema1Data);
      }
      if (ema2Data.length > 0) {
        const line2 = mainChart.addSeries(LineSeries, { color: ema2Color, lineWidth: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
        line2.setData(ema2Data);
      }
    }

    const macdHistSeries = macdChart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
      base: 0,
    });
    macdHistSeries.setData(macdHistData);

    const macdZeroSeries = macdChart.addSeries(LineSeries, {
      color: '#71717a66',
      lineWidth: 1,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdZeroSeries.setData(candleData.map(c => ({ time: c.time, value: 0 })));

    const macdDifSeries = macdChart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 1,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdDifSeries.setData(macdDifData);

    const macdDeaSeries = macdChart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    macdDeaSeries.setData(macdDeaData);

    mainChart.timeScale().fitContent();
    macdChart.timeScale().fitContent();

    const updateHover = (param: MouseEventParams) => {
      const container = wrapperRef.current;
      if (
        !param.time ||
        param.point === undefined ||
        param.point.x === undefined ||
        param.point.y === undefined ||
        !Number.isFinite(param.point.x) ||
        !Number.isFinite(param.point.y) ||
        !container
      ) {
        setHoverData(null);
        return;
      }

      const timeKey = splitTimeKey(param.time);
      if (!timeKey) {
        setHoverData(null);
        return;
      }

      const dataPoint = candleByTime.get(timeKey);
      if (!dataPoint) {
        setHoverData(null);
        return;
      }

      setHoverData({
        date: timeKey,
        price: dataPoint.close,
        open: dataPoint.open,
        high: dataPoint.high,
        low: dataPoint.low,
        ema1: ema1Key && isFiniteNumber(dataPoint[ema1Key]) ? dataPoint[ema1Key] : undefined,
        ema2: ema2Key && isFiniteNumber(dataPoint[ema2Key]) ? dataPoint[ema2Key] : undefined,
        bollUpper: isFiniteNumber(dataPoint.boll_upper) ? dataPoint.boll_upper : undefined,
        bollLower: isFiniteNumber(dataPoint.boll_lower) ? dataPoint.boll_lower : undefined,
        ma30: isFiniteNumber(dataPoint.ma30) ? dataPoint.ma30 : undefined,
        macdDif: isFiniteNumber(dataPoint.macd_dif) ? dataPoint.macd_dif : undefined,
        macdDea: isFiniteNumber(dataPoint.macd_dea) ? dataPoint.macd_dea : undefined,
        macdHist: isFiniteNumber(dataPoint.macd_hist) ? dataPoint.macd_hist : undefined,
        x: param.point.x,
        y: param.point.y,
      });
    };

    mainChart.subscribeCrosshairMove(updateHover);
    macdChart.subscribeCrosshairMove(updateHover);

    const resizeObserver = new ResizeObserver(entries => {
      if (entries.length === 0 || !entries[0].contentRect) return;
      const { width } = entries[0].contentRect;
      if (mainChartRef.current) {
        mainChartRef.current.applyOptions({ width });
      }
      if (macdChartRef.current) {
        macdChartRef.current.applyOptions({ width });
      }
    });
    resizeObserver.observe(wrapperRef.current);

    return () => {
      if (mainChartRef.current) {
        mainChartRef.current.unsubscribeCrosshairMove(updateHover);
        mainChartRef.current.remove();
        mainChartRef.current = null;
      }
      if (macdChartRef.current) {
        macdChartRef.current.unsubscribeCrosshairMove(updateHover);
        macdChartRef.current.remove();
        macdChartRef.current = null;
      }
      resizeObserver.disconnect();
    };
  }, [
    candleData,
    ema1Data,
    ema2Data,
    bollUpperData,
    bollLowerData,
    ma30Data,
    macdHistData,
    macdDifData,
    macdDeaData,
    candleByTime,
    ema1Key,
    ema2Key,
    internalEmaMode,
    mainPaneHeight,
    macdPaneHeight,
  ]);

  if (candleData.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-zinc-600 text-xs bg-zinc-900/30 rounded-lg border border-zinc-800/50"
        style={{ height: totalChartHeight }}
      >
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
            <span className="text-zinc-500">{candleData.length}{timeframe === '1W' ? 'W' : 'D'}</span>
          </div>

          <button
            onClick={(e) => {
              e.stopPropagation();
              setInternalEmaMode(prev => prev === 'long' ? 'short' : prev === 'short' ? 'boll' : 'long');
            }}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-md border border-zinc-700/50 bg-zinc-800/20 text-[10px] text-zinc-500 hover:text-zinc-200 hover:border-zinc-600 hover:bg-zinc-800/50 transition-all group/ema"
            title="点击切换当前股票均线模式"
          >
            <Activity size={10} className="text-zinc-600 group-hover/ema:text-emerald-500 transition-colors" />
            <span className="font-mono tracking-tighter">{internalEmaMode === 'long' ? '20/50' : internalEmaMode === 'short' ? '5/10' : 'BOLL'}</span>
          </button>
        </div>

        <div
          className={clsx(
            'flex items-center gap-1 text-[10px] sm:text-xs font-mono font-bold px-2 py-0.5 rounded-md border transition-colors',
            isPositive
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
              : 'bg-rose-500/10 text-rose-400 border-rose-500/20'
          )}
        >
          {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          {isPositive ? '+' : ''}
          {changePercent.toFixed(2)}%
        </div>
      </div>

      {/* Chart Container */}
      <div className="relative" ref={wrapperRef}>
        <div ref={mainContainerRef} className="w-full relative z-10 box-border" style={{ height: mainPaneHeight }} />
        <div className="h-1.5" />
        <div ref={macdContainerRef} className="w-full relative z-10 box-border" style={{ height: macdPaneHeight }} />

        {/* Main pane price labels */}
        <div className="absolute top-0 right-1 text-[9px] text-zinc-600/50 font-mono pointer-events-none select-none z-0">
          H: {maxPrice.toFixed(2)}
        </div>
        <div
          className="absolute right-1 text-[9px] text-zinc-600/50 font-mono pointer-events-none select-none z-0"
          style={{ top: Math.max(0, mainPaneHeight - 12) }}
        >
          L: {minPrice.toFixed(2)}
        </div>

        <div
          className="absolute right-1 text-[9px] text-zinc-600/60 font-mono pointer-events-none select-none z-0"
          style={{ top: mainPaneHeight + 8 }}
        >
          MACD
        </div>

        {/* Tooltip */}
        {hoverData && (() => {
          const tooltipWidth = 148;
          const chartWidth = wrapperRef.current?.offsetWidth || 0;
          const leftPos = Math.max(0, Math.min(chartWidth - tooltipWidth, hoverData.x - tooltipWidth / 2));
          const arrowPos = Math.max(10, Math.min(tooltipWidth - 14, hoverData.x - leftPos));

          return (
            <div
              className="absolute z-50 pointer-events-none flex flex-col items-start transition-all duration-75 ease-out"
              style={{
                top: -10,
                transform: 'translateY(-100%)',
                left: leftPos,
                width: tooltipWidth,
              }}
            >
              <div className="w-full bg-zinc-950/90 border border-zinc-700/80 rounded-lg shadow-xl shadow-black/60 p-2 text-[10px] backdrop-blur-md animate-in fade-in zoom-in-95 leading-tight">
                <div className="flex justify-between items-center mb-1 pb-1 border-b border-zinc-800">
                  <span className="text-zinc-400 font-medium whitespace-nowrap">{hoverData.date}</span>
                  <span
                    className={clsx(
                      'font-bold ml-2',
                      hoverData.price >= hoverData.open ? 'text-emerald-400' : 'text-rose-400'
                    )}
                  >
                    {(((hoverData.price - hoverData.open) / hoverData.open) * 100).toFixed(2)}%
                  </span>
                </div>

                <div className="space-y-0.5">
                  <div className="flex justify-between items-center">
                    <span className="text-zinc-500">Close</span>
                    <span
                      className={clsx(
                        'font-mono font-medium',
                        hoverData.price >= hoverData.open ? 'text-emerald-400' : 'text-rose-400'
                      )}
                    >
                      {hoverData.price.toFixed(2)}
                    </span>
                  </div>

                  {hoverData.ema1 !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: internalEmaMode === 'long' ? '#f59e0b' : '#38bdf8' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {internalEmaMode === 'long' ? 'EMA20' : 'EMA5'}
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.ema1.toFixed(2)}</span>
                    </div>
                  )}

                  {hoverData.ema2 !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: internalEmaMode === 'long' ? '#8b5cf6' : '#fb923c' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {internalEmaMode === 'long' ? 'EMA50' : 'EMA10'}
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.ema2.toFixed(2)}</span>
                    </div>
                  )}

                  {internalEmaMode === 'boll' && hoverData.bollUpper !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: '#f87171' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        上轨
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.bollUpper.toFixed(2)}</span>
                    </div>
                  )}

                  {internalEmaMode === 'boll' && hoverData.bollLower !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: '#34d399' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        下轨
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.bollLower.toFixed(2)}</span>
                    </div>
                  )}

                  {internalEmaMode === 'boll' && hoverData.ma30 !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5" style={{ color: '#f59e0b' }}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        MA30
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.ma30.toFixed(2)}</span>
                    </div>
                  )}

                  {hoverData.macdDif !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5 text-sky-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        DIF
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.macdDif.toFixed(3)}</span>
                    </div>
                  )}

                  {hoverData.macdDea !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className="flex items-center gap-1.5 text-amber-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        DEA
                      </span>
                      <span className="font-mono text-zinc-300">{hoverData.macdDea.toFixed(3)}</span>
                    </div>
                  )}

                  {hoverData.macdHist !== undefined && (
                    <div className="flex justify-between items-center">
                      <span className={clsx('text-zinc-500', hoverData.macdHist >= 0 ? 'text-rose-400' : 'text-emerald-400')}>
                        MACD
                      </span>
                      <span className={clsx('font-mono', hoverData.macdHist >= 0 ? 'text-rose-300' : 'text-emerald-300')}>
                        {hoverData.macdHist.toFixed(3)}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div
                className="w-2 h-2 bg-zinc-950 border-r border-b border-zinc-700/80 rotate-45 -mt-1 z-50 relative"
                style={{ left: arrowPos }}
              />
            </div>
          );
        })()}
      </div>
    </div>
  );
});
