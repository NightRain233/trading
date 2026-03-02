import { memo, lazy, Suspense } from 'react';
import type { StockData, Candle } from '../types';
const MiniChart = lazy(() => import('./MiniChart').then(m => ({ default: m.MiniChart })));
import { StatusBadge } from './StatusBadge';
import { GripVertical, Trash2, Pencil } from 'lucide-react';
import { clsx } from 'clsx';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

interface SortableStockRowProps {
  stock: StockData;
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
  onEditAlias: (stock: StockData) => void;
  miniCandles?: Candle[];
  emaMode: 'long' | 'short';
  showCharts: boolean;
  index?: number;
}

export const SortableStockRow = memo(function SortableStockRow({
  stock,
  onStockClick,
  onRemoveStock,
  onEditAlias,
  miniCandles,
  emaMode,
  showCharts,
  index = 0
}: SortableStockRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stock.symbol });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const isPositive = (stock.changePercent || 0) >= 0;
  const resonanceExitLabel = stock.resonanceExitLevel === 'hard' ? '共振离场' : '离场预警';

  return (
    <div ref={setNodeRef} style={style}>
      <div
        className={clsx(
          "stock-row stock-row-hover animate-fade-in-up",
          "flex flex-col sm:grid sm:grid-cols-12 gap-2 sm:gap-4 px-4 py-4 sm:py-5 items-start sm:items-center",
          "cursor-pointer group relative",
          "border-b border-zinc-800/20 last:border-b-0",
          "hover:bg-gradient-to-r hover:from-emerald-500/[0.02] hover:to-transparent",
          "transition-all duration-200"
        )}
        style={{ animationDelay: `${index * 35}ms` }}
        onClick={() => onStockClick(stock)}
      >
        {/* Drag Handle */}
        <div
          className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 sm:block hidden cursor-grab transition-opacity duration-200"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="text-zinc-700 hover:text-zinc-500" size={14} />
        </div>

        {/* Symbol & Name */}
        <div className="flex items-center justify-between w-full sm:col-span-2 sm:pl-5">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1.5 group/title">
              <div className="font-bold text-zinc-100 group-hover:text-emerald-400 transition-colors duration-200 truncate text-sm">
                {stock.alias || stock.symbol}
                {stock.alias && (
                  <span className="ml-1 text-[10px] text-zinc-600 font-normal font-mono">
                    ({stock.symbol})
                  </span>
                )}
              </div>
              <button
                className="opacity-0 group-hover/title:opacity-100 p-0.5 text-zinc-700 hover:text-zinc-400 transition-all duration-200"
                onClick={(e) => {
                  e.stopPropagation();
                  onEditAlias(stock);
                }}
                title="编辑别名"
              >
                <Pencil size={11} />
              </button>
            </div>
            <div className="text-[10px] sm:text-xs text-zinc-600 truncate max-w-[120px] sm:max-w-none font-medium">
              {stock.name}
            </div>
          </div>

          {/* Mobile Price Display */}
          <div className="sm:hidden text-right leading-tight">
            {stock._loading ? (
              <div className="space-y-1.5">
                <div className="h-4 w-16 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
                <div className="h-3 w-12 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
              </div>
            ) : (<>
              <div className="font-mono text-zinc-100 tabular-nums font-semibold">
                ${(stock.price || 0).toFixed(2)}
              </div>
              <div className={clsx(
                "text-[10px] font-mono tabular-nums font-semibold",
                isPositive ? "price-up" : "price-down"
              )}>
                {isPositive ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
              </div>
            </>)}
          </div>
        </div>

        {/* Desktop Price */}
        <div className="hidden sm:block sm:col-span-2 text-right">
          {stock._loading ? (
            <div className="space-y-1.5">
              <div className="h-4 w-16 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
              <div className="h-3 w-12 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
            </div>
          ) : (<>
            <div className="font-mono text-zinc-100 tabular-nums font-semibold text-sm">
              ${(stock.price || 0).toFixed(2)}
            </div>
            <div className={clsx(
              "text-xs font-mono tabular-nums font-medium",
              isPositive ? "price-up" : "price-down"
            )}>
              {isPositive ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
            </div>
          </>)}
        </div>

        {/* Trend Badge */}
        <div className="flex items-center justify-between sm:justify-end w-full sm:col-span-2 gap-2">
          {stock._loading ? (
            <div className="h-6 w-16 bg-zinc-800/50 rounded-lg animate-pulse ml-auto" />
          ) : (<>
            {/* Mobile extra info */}
            <div className="sm:hidden flex items-center gap-1.5 flex-wrap">
              {stock.signal && stock.signal !== '观望' && (
                <span className={clsx(
                  "px-2 py-0.5 rounded-md text-[10px] font-bold whitespace-nowrap",
                  stock.signal === '强烈信号'
                    ? "bg-emerald-500/90 text-white badge-glow-green"
                    : "bg-amber-500/90 text-zinc-900 badge-glow-amber"
                )}>
                  {stock.signal}
                </span>
              )}
              {stock.resonanceBuySignal && (
                <span className="px-2 py-0.5 rounded-md text-[10px] font-bold whitespace-nowrap bg-cyan-500/85 text-zinc-950">
                  共振买点
                </span>
              )}
              {stock.resonanceExitSignal && (
                <span
                  className={clsx(
                    "px-2 py-0.5 rounded-md text-[10px] font-bold whitespace-nowrap",
                    stock.resonanceExitLevel === 'hard'
                      ? "bg-rose-500/90 text-white"
                      : "bg-amber-500/90 text-zinc-900"
                  )}
                  title={stock.resonanceExitReason || ''}
                >
                  {resonanceExitLabel}
                </span>
              )}
              {!stock._loading && (
                <span
                  className={clsx(
                    "px-1.5 py-0.5 rounded-md text-[10px] font-mono tabular-nums whitespace-nowrap",
                    stock.rsiStatus === '超买' ? "text-rose-400 bg-rose-500/10 border border-rose-500/20" :
                      stock.rsiStatus === '超卖' ? "text-emerald-400 bg-emerald-500/10 border border-emerald-500/20" :
                        "text-zinc-500 bg-zinc-800/30 border border-zinc-700/20"
                  )}
                  title={`RSI: ${stock.rsi?.toFixed(1) || 'N/A'} (${stock.rsiPeriod || 14})`}
                >
                  RSI {stock.rsi?.toFixed(1) || 'N/A'}
                  {stock.rsiStatus && stock.rsiStatus !== '中性' && (
                    <span className="ml-0.5 text-[9px] opacity-80">{stock.rsiStatus}</span>
                  )}
                </span>
              )}
              {stock.weeklyMacdStatus && (
                <span className={clsx(
                  "text-[10px] font-bold whitespace-nowrap",
                  stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" :
                    stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
                      stock.weeklyMacdStatus === '周线回调' ? "text-amber-400" :
                        "text-rose-400"
                )}>
                  {stock.weeklyMacdStatus}
                </span>
              )}
            </div>
            <StatusBadge status={stock.trend} type="trend" />
          </>)}
        </div>

        {/* Signal */}
        <div className="col-span-2 hidden sm:flex sm:justify-end">
          {stock._loading ? (
            <div className="h-6 w-14 bg-zinc-800/50 rounded-lg animate-pulse" />
          ) : (
            <div className="flex flex-wrap justify-end gap-1.5 max-w-[170px]">
              {stock.signal === '强烈信号' || stock.signal === '谨慎信号' ? (
                <span className={clsx(
                  "px-2.5 py-1 rounded-lg text-xs font-bold transition-all",
                  stock.signal === '强烈信号'
                    ? "bg-emerald-500/90 text-white badge-glow-green"
                    : "bg-amber-500/90 text-zinc-900 badge-glow-amber"
                )}>
                  {stock.signal}
                </span>
              ) : (
                <span className="text-zinc-700 text-xs font-medium">观望</span>
              )}

              {stock.resonanceBuySignal && (
                <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-cyan-500/85 text-zinc-950">
                  共振买点
                </span>
              )}

              {stock.resonanceExitSignal && (
                <span
                  className={clsx(
                    "px-2.5 py-1 rounded-lg text-xs font-bold",
                    stock.resonanceExitLevel === 'hard'
                      ? "bg-rose-500/90 text-white"
                      : "bg-amber-500/90 text-zinc-900"
                  )}
                  title={stock.resonanceExitReason || ''}
                >
                  {resonanceExitLabel}
                </span>
              )}
            </div>
          )}
        </div>

        {/* RSI */}
        <div className="col-span-2 hidden sm:flex sm:justify-end">
          {stock._loading ? (
            <div className="h-6 w-16 bg-zinc-800/50 rounded-lg animate-pulse" />
          ) : (
            <span
              className={clsx(
                "font-mono tabular-nums text-sm px-2.5 py-0.5 rounded-lg inline-flex items-center gap-1",
                stock.rsiStatus === '超买'
                  ? "text-rose-400 bg-rose-500/10 border border-rose-500/15 badge-glow-red"
                  : stock.rsiStatus === '超卖'
                    ? "text-emerald-400 bg-emerald-500/10 border border-emerald-500/15 badge-glow-green"
                    : "text-zinc-400 bg-zinc-800/30 border border-zinc-700/20"
              )}
              title={`阈值: ${stock.rsiOversold || '?'}-${stock.rsiOverbought || '?'}`}
            >
              {stock.rsi?.toFixed(1) || 'N/A'}
              <span className="text-[10px] text-zinc-600">({stock.rsiPeriod || 14})</span>
              {stock.rsiStatus && stock.rsiStatus !== '中性' && (
                <span className="text-[10px] opacity-75 font-semibold">{stock.rsiStatus}</span>
              )}
            </span>
          )}
        </div>

        {/* Weekly Status */}
        <div className="col-span-2 hidden sm:flex sm:justify-end">
          {stock._loading ? (
            <div className="space-y-1.5">
              <div className="h-4 w-14 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
              <div className="h-3 w-10 bg-zinc-800/50 rounded-md animate-pulse ml-auto" />
            </div>
          ) : stock.weeklyMacdStatus ? (
            <div className="flex flex-col items-end leading-tight">
              <span className={clsx(
                "text-xs font-bold",
                stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" :
                  stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
                    stock.weeklyMacdStatus === '周线回调' ? "text-amber-400" :
                      "text-rose-400"
              )}>
                {stock.weeklyMacdStatus}
              </span>
              <span className={clsx(
                "text-[10px] font-medium",
                stock.weeklyPriceVsMA5 === '线上' ? "text-emerald-500/60" : "text-rose-500/60"
              )}>
                5W{stock.weeklyPriceVsMA5}
              </span>
            </div>
          ) : (
            <span className="text-zinc-700 text-xs">-</span>
          )}
        </div>

        {/* Delete Action */}
        <div className="absolute right-2 opacity-0 group-hover:opacity-100 transition-all duration-200 flex items-center h-full top-0">
          <button
            onClick={(e) => onRemoveStock(e, stock.symbol)}
            className="p-2 bg-zinc-900/90 backdrop-blur hover:bg-rose-500/15 hover:text-rose-400 text-zinc-600 rounded-xl shadow-xl border border-zinc-700/30 transition-all duration-200 active:scale-95"
            title="从列表中移除"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Mini Chart */}
      {showCharts && miniCandles && miniCandles.length > 0 && (
        <div className="px-4 pb-3" onClick={() => onStockClick(stock)}>
          <Suspense fallback={<div className="h-[120px] bg-zinc-900/20 rounded-xl animate-pulse" />}>
            <MiniChart candles={miniCandles} emaMode={emaMode} />
          </Suspense>
        </div>
      )}
    </div>
  );
});
