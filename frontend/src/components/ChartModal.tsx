import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, HistogramSeries, CrosshairMode } from 'lightweight-charts';
import type { Time, IChartApi, LineWidth } from 'lightweight-charts';
import type { StockData, Candle } from '../types';
import { X, Activity, Calendar } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { fetchStockData } from '../utils';

interface ChartModalProps {
  stock: StockData | null;
  onClose: () => void;
}

type MainInd = 'EMA' | 'BOLL';
type TFrame = 'D' | 'W';

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

  // Update mobile status on resize
  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 640);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Fetch fresh data when modal opens
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
    const charts: IChartApi[] = [];

    const commonOptions = {
      layout: {
        background: { type: ColorType.Solid, color: '#18181b' },
        textColor: '#d4d4d8',
        fontSize: isMobile ? 10 : 12,
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
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      crosshair: {
        mode: isMobile ? CrosshairMode.Magnet : CrosshairMode.Normal,
      },
      handleScroll: { vertTouchDrag: false },
    };

    // Responsive Heights
    const pHeight = isMobile ? 240 : 320;
    const sHeight = isMobile ? 100 : 140;

    charts[0] = createChart(priceRef.current, { ...commonOptions, height: pHeight });
    charts[1] = createChart(rsiRef.current, { ...commonOptions, height: sHeight });
    charts[2] = createChart(kdjRef.current, { ...commonOptions, height: sHeight });
    charts[3] = createChart(macdRef.current, { ...commonOptions, height: sHeight });
    charts[4] = createChart(atrRef.current, { ...commonOptions, height: sHeight, timeScale: { ...commonOptions.timeScale, visible: true } });

    // Data Source
    const candles = timeframe === 'D' ? stock.candles : (stock.weekly_candles || []);
    if (!candles || candles.length === 0) return;

    // Price
    const candleSeries = charts[0].addSeries(CandlestickSeries, { 
       upColor: '#10b981', 
       downColor: '#f43f5e', 
       borderVisible: false, 
       wickUpColor: '#10b981', 
       wickDownColor: '#f43f5e' 
    });
    const validCandles = candles.filter(c => c.open != null && c.high != null && c.low != null && c.close != null);
    candleSeries.setData(validCandles.map((c: Candle) => ({ 
      time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close 
    })));

    // Volume
    const volumeSeries = charts[0].addSeries(HistogramSeries, { 
      color: '#3f3f46', priceFormat: { type: 'volume' }, priceScaleId: 'volume' 
    });
    charts[0].priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeries.setData(validCandles.map((c: Candle) => ({ 
      time: c.time as Time, value: c.volume ?? 0, color: c.close >= c.open ? '#10b98133' : '#f43f5e33' 
    })));

    // Main Inds
    if (mainInd === 'EMA') {
      const e20 = charts[0].addSeries(LineSeries, { color: '#06b6d4', lineWidth: 1 as LineWidth });
      const e50 = charts[0].addSeries(LineSeries, { color: '#eab308', lineWidth: 1 as LineWidth });
      e20.setData(candles.filter(c => c.ema20 != null).map((c: Candle) => ({ time: c.time as Time, value: c.ema20! })));
      e50.setData(candles.filter(c => c.ema50 != null).map((c: Candle) => ({ time: c.time as Time, value: c.ema50! })));
    } else {
      const bup = charts[0].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth });
      const bmid = charts[0].addSeries(LineSeries, { color: '#71717a', lineWidth: 1 as LineWidth, lineStyle: 2 });
      const blow = charts[0].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth });
      bup.setData(candles.filter(c => c.boll_upper != null).map((c: Candle) => ({ time: c.time as Time, value: c.boll_upper! })));
      bmid.setData(candles.filter(c => c.boll_mid != null).map((c: Candle) => ({ time: c.time as Time, value: c.boll_mid! })));
      blow.setData(candles.filter(c => c.boll_lower != null).map((c: Candle) => ({ time: c.time as Time, value: c.boll_lower! })));
    }

    // RSI
    const rsiLine = charts[1].addSeries(LineSeries, { color: '#a855f7', lineWidth: 2 as LineWidth });
    rsiLine.setData(candles.filter(c => c.rsi != null).map((c: Candle) => ({ time: c.time as Time, value: c.rsi! })));
    const ob = charts[1].addSeries(LineSeries, { color: '#f43f5e', lineWidth: 1 as LineWidth, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
    const os = charts[1].addSeries(LineSeries, { color: '#10b981', lineWidth: 1 as LineWidth, lineStyle: 2, lastValueVisible: false, priceLineVisible: false });
    ob.setData(candles.map((c: Candle) => ({ time: c.time as Time, value: stock.rsiOverbought || 70 })));
    os.setData(candles.map((c: Candle) => ({ time: c.time as Time, value: stock.rsiOversold || 30 })));

    // KDJ
    const kLine = charts[2].addSeries(LineSeries, { color: '#ffffff', lineWidth: 1 as LineWidth, title: 'K' });
    const dLine = charts[2].addSeries(LineSeries, { color: '#eab308', lineWidth: 1 as LineWidth, title: 'D' });
    const jLine = charts[2].addSeries(LineSeries, { color: '#a855f7', lineWidth: 1 as LineWidth, title: 'J' });
    kLine.setData(candles.filter(c => c.k != null).map((c: Candle) => ({ time: c.time as Time, value: c.k! })));
    dLine.setData(candles.filter(c => c.d != null).map((c: Candle) => ({ time: c.time as Time, value: c.d! })));
    jLine.setData(candles.filter(c => c.j != null).map((c: Candle) => ({ time: c.time as Time, value: c.j! })));

    // MACD
    const macdHist = charts[3].addSeries(HistogramSeries, { title: 'Hist' });
    const macdDif = charts[3].addSeries(LineSeries, { color: '#60a5fa', lineWidth: 1 as LineWidth, title: 'DIF' });
    const macdDea = charts[3].addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1 as LineWidth, title: 'DEA' });
    macdHist.setData(candles.filter(c => c.macd_hist != null).map((c: Candle) => ({ 
      time: c.time as Time, value: c.macd_hist!, color: c.macd_hist! >= 0 ? '#10b98188' : '#f43f5e88' 
    })));
    macdDif.setData(candles.filter(c => c.macd_dif != null).map((c: Candle) => ({ time: c.time as Time, value: c.macd_dif! })));
    macdDea.setData(candles.filter(c => c.macd_dea != null).map((c: Candle) => ({ time: c.time as Time, value: c.macd_dea! })));

    // ATR
    const atrLine = charts[4].addSeries(LineSeries, { color: '#fb923c', lineWidth: 1 as LineWidth });
    atrLine.setData(candles.filter(c => c.atr != null).map((c: Candle) => ({ time: c.time as Time, value: c.atr! })));

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
      charts.forEach(c => c.remove());
    };
  }, [stock, timeframe, mainInd, isMobile]);

  if (!stock) return null;

  const TabButton = ({ active, onClick, children }: { active: boolean, onClick: () => void, children: React.ReactNode }) => (
    <button 
      onClick={onClick}
      className={`px-3 py-1 rounded-md text-[10px] sm:text-xs font-medium transition-all ${
        active ? 'bg-zinc-100 text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-300'
      }`}
    >
      {children}
    </button>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm sm:p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 w-full sm:max-w-5xl sm:rounded-xl border-x sm:border border-zinc-800 shadow-2xl overflow-hidden flex flex-col h-full sm:h-auto sm:max-h-[98vh]">
        
        {/* Header */}
        <div className="p-3 sm:p-4 border-b border-zinc-800 bg-zinc-900/50">
          <div className="flex justify-between items-start mb-3 sm:mb-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
                <h2 className="text-lg sm:text-2xl font-bold text-white uppercase truncate">{stock.symbol}</h2>
                <span className={`text-base sm:text-lg font-mono ${stock.changePercent >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                  {stock.price.toFixed(2)} ({stock.changePercent >= 0 ? '+' : ''}{stock.changePercent.toFixed(2)}%)
                </span>
              </div>
              
              <div className="flex flex-wrap gap-1.5 mt-1.5">
                <StatusBadge status={stock.trend} type="trend" />
                <StatusBadge status={stock.signal} type="signal" />
                {hoverDate && (
                   <div className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-mono">
                      <Calendar size={10} /> {hoverDate}
                   </div>
                )}
              </div>
            </div>

            <button onClick={onClose} className="p-2 -mr-2 hover:bg-zinc-800 rounded-lg text-zinc-400 hover:text-white transition-colors">
              <X size={24} />
            </button>
          </div>

          <div className="flex items-center gap-3 bg-zinc-950/50 p-1 rounded-lg border border-zinc-800/50 self-start">
             <div className="flex p-0.5 bg-zinc-900 rounded-md border border-zinc-800">
                <TabButton onClick={() => setTimeframe('D')} active={timeframe === 'D'}>日线</TabButton>
                <TabButton onClick={() => setTimeframe('W')} active={timeframe === 'W'}>周线</TabButton>
             </div>
             <div className="w-px h-3 bg-zinc-800"></div>
             <div className="flex p-0.5 bg-zinc-900 rounded-md border border-zinc-800">
                <TabButton onClick={() => setMainInd('EMA')} active={mainInd === 'EMA'}>EMA</TabButton>
                <TabButton onClick={() => setMainInd('BOLL')} active={mainInd === 'BOLL'}>BOLL</TabButton>
             </div>
          </div>
        </div>

        {/* Charts - Stacking */}
        <div className="flex-1 overflow-y-auto bg-zinc-900 custom-scrollbar pb-8">
           <div className="relative border-b border-zinc-800">
             <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none flex gap-2">
               <Activity size={12} /> PRICE & VOL ({mainInd})
             </div>
             <div className="w-full" ref={priceRef} />
           </div>

           <div className="relative border-b border-zinc-800">
             <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">RSI({timeframe === 'D' ? stock.rsiPeriod : 14})</div>
             <div className="w-full" ref={rsiRef} />
           </div>

           <div className="relative border-b border-zinc-800">
             <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">KDJ</div>
             <div className="w-full" ref={kdjRef} />
           </div>

           <div className="relative border-b border-zinc-800">
             <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">MACD</div>
             <div className="w-full" ref={macdRef} />
           </div>

           <div className="relative border-b border-zinc-800">
             <div className="absolute top-2 left-4 z-10 text-[10px] text-zinc-500 pointer-events-none">ATR</div>
             <div className="w-full" ref={atrRef} />
           </div>
        </div>
      </div>
    </div>
  );
}
