import { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import type { StockData } from '../types';
import { calculateEMA } from '../utils';
import { X } from 'lucide-react';

interface ChartModalProps {
  stock: StockData | null;
  onClose: () => void;
}

export function ChartModal({ stock, onClose }: ChartModalProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!stock || !chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#18181b' }, // zinc-900
        textColor: '#d4d4d8',
      },
      grid: {
        vertLines: { color: '#27272a' },
        horzLines: { color: '#27272a' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: {
        borderColor: '#3f3f46',
      },
      rightPriceScale: {
        borderColor: '#3f3f46',
      },
    });

    // Candlestick Series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', // emerald-500
      downColor: '#f43f5e', // rose-500
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    const data = stock.candles.map(c => ({
      time: c.time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeries.setData(data);

    // EMA 20
    const ema20Series = chart.addSeries(LineSeries, {
      color: '#06b6d4', // cyan-500
      lineWidth: 2,
      // title property is not directly on LineSeries options in all versions, 
      // but usually supported or ignored. v5 uses explicit legend API often or we rely on primitives.
      // We'll leave it out of options if it causes type error, but standard LineSeriesOptions usually has it via SeriesOptionsCommon.
      // Wait, 'title' is valid in SeriesOptionsCommon? 
      // Actually v5 doesn't have built-in legend in the chart canvas, so title in options might be useless for display but okay for types.
      // I'll skip title in options to be safe and I handle legend in my HTML header.
    });
    const ema20Data = calculateEMA(stock.candles, 20).map(d => ({ time: d.time as Time, value: d.value }));
    ema20Series.setData(ema20Data);

    // EMA 50
    const ema50Series = chart.addSeries(LineSeries, {
      color: '#eab308', // yellow-500
      lineWidth: 2,
    });
    const ema50Data = calculateEMA(stock.candles, 50).map(d => ({ time: d.time as Time, value: d.value }));
    ema50Series.setData(ema50Data);
    
    // Fit content
    chart.timeScale().fitContent();

    // Handle Resize
    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [stock]);

  if (!stock) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 w-full max-w-4xl rounded-xl border border-zinc-800 shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-zinc-800 flex justify-between items-center bg-zinc-900/50">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              {stock.symbol} 
              <span className="text-zinc-500 text-sm font-normal">{stock.name}</span>
            </h2>
            <div className="flex gap-4 mt-1 text-sm text-zinc-400">
               <span className="flex items-center gap-1">
                 <span className="w-3 h-3 rounded bg-[#06b6d4]"></span> EMA 20
               </span>
               <span className="flex items-center gap-1">
                 <span className="w-3 h-3 rounded bg-[#eab308]"></span> EMA 50
               </span>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-2 hover:bg-zinc-800 rounded-lg transition-colors text-zinc-400 hover:text-white"
          >
            <X size={20} />
          </button>
        </div>

        {/* Chart */}
        <div className="w-full h-[400px] relative" ref={chartContainerRef}>
        </div>
      </div>
    </div>
  );
}
