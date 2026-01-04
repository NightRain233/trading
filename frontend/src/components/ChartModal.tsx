import { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries } from 'lightweight-charts';
import type { Time, IChartApi } from 'lightweight-charts';
import type { StockData } from '../types';
import { X, TrendingUp, TrendingDown, Activity, Calendar } from 'lucide-react';
import { StatusBadge } from './StatusBadge';

interface ChartModalProps {
  stock: StockData | null;
  onClose: () => void;
}

export function ChartModal({ stock, onClose }: ChartModalProps) {
  const priceChartContainerRef = useRef<HTMLDivElement>(null);
  const rsiChartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<{ price: IChartApi; rsi: IChartApi } | null>(null);

  useEffect(() => {
    if (!stock || !priceChartContainerRef.current || !rsiChartContainerRef.current) return;

    const commonOptions = {
      layout: {
        background: { type: ColorType.Solid, color: '#18181b' },
        textColor: '#d4d4d8',
      },
      grid: {
        vertLines: { color: '#27272a' },
        horzLines: { color: '#27272a' },
      },
      timeScale: {
        borderColor: '#3f3f46',
        visible: false,
      },
      rightPriceScale: {
        borderColor: '#3f3f46',
      },
      crosshair: {
        mode: 0,
      },
    };

    // Price Chart
    const priceChart = createChart(priceChartContainerRef.current, {
      ...commonOptions,
      width: priceChartContainerRef.current.clientWidth,
      height: 300,
    });

    // RSI Chart
    const rsiChart = createChart(rsiChartContainerRef.current, {
      ...commonOptions,
      width: rsiChartContainerRef.current.clientWidth,
      height: 120,
      timeScale: {
        ...commonOptions.timeScale,
        visible: true,
      },
    });

    chartRef.current = { price: priceChart, rsi: rsiChart };

    // --- Series ---
    const pc = priceChart;
    const rc = rsiChart;

    // 1. Price
    const candleSeries = pc.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    // 2. EMAs
    const ema20Series = pc.addSeries(LineSeries, { color: '#06b6d4', lineWidth: 2 });
    const ema50Series = pc.addSeries(LineSeries, { color: '#eab308', lineWidth: 2 });

    // 3. Volume
    const volumeSeries = pc.addSeries(HistogramSeries, {
      color: '#3f3f46',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    pc.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // 4. RSI
    const rsiSeries = rc.addSeries(LineSeries, { color: '#a855f7', lineWidth: 2 });
    
    // RSI Threshold lines
    const overboughtLine = rc.addSeries(LineSeries, { 
      color: '#f43f5e', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false 
    });
    const oversoldLine = rc.addSeries(LineSeries, { 
      color: '#10b981', lineWidth: 1, lineStyle: 2, lastValueVisible: false, priceLineVisible: false 
    });

    // --- Data ---
    const candles = stock.candles;
    
    // Main Price
    candleSeries.setData(candles.map(c => ({ 
      time: c.time as Time, 
      open: c.open, 
      high: c.high, 
      low: c.low, 
      close: c.close 
    })));

    // EMAs - Filter out nulls
    const ema20Data = candles
      .filter(c => c.ema20 !== null && c.ema20 !== undefined)
      .map(c => ({ time: c.time as Time, value: c.ema20! }));
    if (ema20Data.length > 0) ema20Series.setData(ema20Data);

    const ema50Data = candles
      .filter(c => c.ema50 !== null && c.ema50 !== undefined)
      .map(c => ({ time: c.time as Time, value: c.ema50! }));
    if (ema50Data.length > 0) ema50Series.setData(ema50Data);

    // Volume
    volumeSeries.setData(candles.map(c => ({ 
      time: c.time as Time, 
      value: c.volume, 
      color: c.close >= c.open ? '#10b98144' : '#f43f5e44' 
    })));

    // RSI
    const rsiData = candles
      .filter(c => c.rsi !== null && c.rsi !== undefined)
      .map(c => ({ time: c.time as Time, value: c.rsi! }));
    
    if (rsiData.length > 0) {
      rsiSeries.setData(rsiData);
      overboughtLine.setData(rsiData.map(d => ({ time: d.time, value: stock.rsiOverbought })));
      oversoldLine.setData(rsiData.map(d => ({ time: d.time, value: stock.rsiOversold })));
    }

    // --- Sync & Finalize ---
    let isSyncing = false;

    // Use a frame delay to let charts initialize their internal scales with data
    const animId = requestAnimationFrame(() => {
      if (!priceChart || !rsiChart) return;

      priceChart.timeScale().fitContent();
      rsiChart.timeScale().fitContent();

      // Use LogicalRange for more robust syncing between two charts with identical time points
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (isSyncing || !range) return;
        isSyncing = true;
        rsiChart.timeScale().setVisibleLogicalRange(range);
        isSyncing = false;
      });

      rsiChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (isSyncing || !range) return;
        isSyncing = true;
        priceChart.timeScale().setVisibleLogicalRange(range);
        isSyncing = false;
      });
    });

    const handleResize = () => {
      if (priceChartContainerRef.current && rsiChartContainerRef.current) {
        priceChart.applyOptions({ width: priceChartContainerRef.current.clientWidth });
        rsiChart.applyOptions({ width: rsiChartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      priceChart.remove();
      rsiChart.remove();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      priceChart.remove();
      rsiChart.remove();
    };
  }, [stock]);

  if (!stock) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 w-full max-w-5xl rounded-xl border border-zinc-800 shadow-2xl overflow-hidden flex flex-col max-h-[98vh]">
        {/* Header */}
        <div className="p-3 sm:p-4 border-b border-zinc-800 bg-zinc-900/50">
          <div className="flex justify-between items-start mb-4">
            <div>
              <div className="flex items-center gap-3">
                <h2 className="text-xl sm:text-2xl font-bold text-white uppercase tracking-tight">
                  {stock.symbol}
                </h2>
                <span className="text-zinc-500 text-sm font-normal hidden sm:inline">{stock.name}</span>
                <span className={`text-lg font-mono ${stock.changePercent >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                  {stock.price.toFixed(2)} ({stock.changePercent >= 0 ? '+' : ''}{stock.changePercent.toFixed(2)}%)
                </span>
              </div>
              
              <div className="flex flex-wrap gap-2 mt-2">
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs">
                  <Activity size={14} className="text-purple-400" />
                  ADX: <span className="text-white font-medium">{stock.adx.toFixed(1)}</span>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs">
                  <div className="w-2 h-2 rounded-full bg-purple-500"></div>
                  RSI({stock.rsiPeriod}): <span className="text-white font-medium">{stock.rsi.toFixed(1)}</span>
                </div>
                <StatusBadge status={stock.trend} type="trend" />
                <StatusBadge status={stock.signal} type="signal" />
              </div>
            </div>

            <button 
              onClick={onClose}
              className="p-2 hover:bg-zinc-800 rounded-lg transition-colors text-zinc-400 hover:text-white"
            >
              <X size={24} />
            </button>
          </div>

          {/* Weekly Context Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 rounded-lg bg-zinc-950/50 border border-zinc-800/50">
             <div className="flex items-center gap-2">
               <Calendar size={16} className="text-zinc-500" />
               <span className="text-xs text-zinc-400">周线趋势:</span>
               <span className={`text-xs font-bold ${
                 stock.weeklyMacdStatus?.includes('牛') || stock.weeklyMacdStatus?.includes('反弹') ? 'text-emerald-500' : 'text-rose-500'
               }`}>
                 {stock.weeklyMacdStatus}
               </span>
             </div>
             <div className="flex items-center gap-2">
               {stock.weeklyPriceVsMA5 === '线上' ? <TrendingUp size={16} className="text-emerald-500" /> : <TrendingDown size={16} className="text-rose-500" />}
               <span className="text-xs text-zinc-400">周 MA5:</span>
               <span className={`text-xs font-bold ${stock.weeklyPriceVsMA5 === '线上' ? 'text-emerald-500' : 'text-rose-500'}`}>
                 {stock.weeklyPriceVsMA5}
               </span>
             </div>
             <div className="flex items-center gap-2 sm:col-span-1">
               <span className="text-xs text-zinc-400">EMA 20/50:</span>
               <div className="flex gap-1">
                 <div className="w-3 h-3 rounded bg-[#06b6d4]"></div>
                 <div className="w-3 h-3 rounded bg-[#eab308]"></div>
               </div>
             </div>
             <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-400 md:inline hidden">MACD 能量:</span>
                <div className={`h-1.5 w-16 bg-zinc-800 rounded-full overflow-hidden flex ${stock.weeklyMacdHist! >= 0 ? 'justify-start' : 'justify-end'}`}>
                   <div 
                    className={`h-full ${stock.weeklyMacdHist! >= 0 ? 'bg-emerald-500' : 'bg-rose-500'}`} 
                    style={{ width: `${Math.min(100, Math.abs(stock.weeklyMacdHist! * 20))}%` }}
                   />
                </div>
             </div>
          </div>
        </div>

        {/* Charts Container */}
        <div className="flex-1 overflow-y-auto min-h-0 bg-zinc-900 custom-scrollbar">
           <div className="w-full h-[300px] relative" ref={priceChartContainerRef}>
              <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">价格 & 成交量</div>
           </div>
           <div className="w-full h-[120px] border-t border-zinc-800 relative" ref={rsiChartContainerRef}>
              <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">RSI({stock.rsiPeriod})</div>
           </div>
        </div>
      </div>
    </div>
  );
}
