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
}

export const SortableStockRow = memo(function SortableStockRow({
  stock,
  onStockClick,
  onRemoveStock,
  onEditAlias,
  miniCandles,
  emaMode,
  showCharts
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

  return (
    <div ref={setNodeRef} style={style}>
    <div
      className="flex flex-col sm:grid sm:grid-cols-12 gap-2 sm:gap-4 p-4 items-start sm:items-center hover:bg-zinc-800/50 transition-colors cursor-pointer group relative bg-zinc-900/30 border-b border-zinc-800/30 sm:border-none"
      onClick={() => onStockClick(stock)}
    >
      {/* Drag Handle */}
      <div
        className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 sm:block hidden cursor-grab"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="text-zinc-600" size={14} />
      </div>

      <div className="flex items-center justify-between w-full sm:col-span-2 sm:pl-4">
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-1 group/title">
            <div className="font-bold text-white group-hover:text-emerald-400 transition-colors truncate">
              {stock.alias || stock.symbol}
              {stock.alias && <span className="ml-1 text-[10px] text-zinc-500 font-normal">({stock.symbol})</span>}
            </div>
            <button
              className="opacity-0 group-hover/title:opacity-100 p-0.5 text-zinc-600 hover:text-zinc-300 transition-opacity"
              onClick={(e) => {
                e.stopPropagation();
                onEditAlias(stock);
              }}
              title="Edit Alias"
            >
              <Pencil size={12} />
            </button>
          </div>
          <div className="text-[10px] sm:text-xs text-zinc-500 truncate max-w-[120px] sm:max-w-none">{stock.name}</div>
        </div>

        {/* Mobile Price Display */}
        <div className="sm:hidden text-right leading-tight">
          {stock._loading ? (
            <div className="space-y-1">
              <div className="h-4 w-16 bg-zinc-700/50 rounded animate-pulse ml-auto" />
              <div className="h-3 w-12 bg-zinc-700/50 rounded animate-pulse ml-auto" />
            </div>
          ) : (<>
            <div className="font-mono text-zinc-200">${(stock.price || 0).toFixed(2)}</div>
            <div className={clsx("text-[10px] font-mono", (stock.changePercent || 0) >= 0 ? "text-emerald-400" : "text-rose-400")}>
              {(stock.changePercent || 0) >= 0 ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
            </div>
          </>)}
        </div>
      </div>

      <div className="hidden sm:block sm:col-span-2 text-right">
        {stock._loading ? (
          <div className="space-y-1">
            <div className="h-4 w-16 bg-zinc-700/50 rounded animate-pulse ml-auto" />
            <div className="h-3 w-12 bg-zinc-700/50 rounded animate-pulse ml-auto" />
          </div>
        ) : (<>
          <div className="font-mono text-zinc-200">${(stock.price || 0).toFixed(2)}</div>
          <div className={clsx("text-xs font-mono", (stock.changePercent || 0) >= 0 ? "text-emerald-400" : "text-rose-400")}>
            {(stock.changePercent || 0) >= 0 ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
          </div>
        </>)}
      </div>

      {/* Badges/Status Row */}
      <div className="flex items-center justify-between sm:justify-end w-full sm:col-span-2 gap-2">
        {stock._loading ? (
          <div className="h-5 w-16 bg-zinc-700/50 rounded animate-pulse ml-auto" />
        ) : (<>
          <div className="sm:hidden flex items-center gap-2">
            {stock.signal && stock.signal !== '观望' && (
              <span className={clsx(
                "px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap",
                stock.signal === '强烈信号' ? "bg-emerald-500 text-white" : "bg-yellow-500 text-zinc-900"
              )}>
                {stock.signal}
              </span>
            )}
            {stock.weeklyMacdStatus && (
              <span className={clsx(
                "text-[10px] font-bold whitespace-nowrap",
                stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" :
                stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
                stock.weeklyMacdStatus === '周线回调' ? "text-yellow-500" :
                "text-rose-400"
              )}>
                {stock.weeklyMacdStatus}
              </span>
            )}
          </div>
          <StatusBadge status={stock.trend} type="trend" />
        </>)}
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        {stock._loading ? (
          <div className="h-5 w-12 bg-zinc-700/50 rounded animate-pulse ml-auto" />
        ) : stock.signal === '强烈信号' || stock.signal === '谨慎信号' ? (
          <span className={clsx(
            "px-2 py-1 rounded text-xs font-bold",
            stock.signal === '强烈信号' ? "bg-emerald-500 text-white" : "bg-yellow-500 text-zinc-900"
          )}>
            {stock.signal}
          </span>
        ) : (
          <span className="text-zinc-600 text-xs">观望</span>
        )}
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        {stock._loading ? (
          <div className="h-5 w-16 bg-zinc-700/50 rounded animate-pulse ml-auto" />
        ) : (
          <span
            className={clsx(
              "font-mono text-sm px-2 py-0.5 rounded",
              stock.rsiStatus === '超买' ? "text-rose-400 bg-rose-500/10" :
              stock.rsiStatus === '超卖' ? "text-emerald-400 bg-emerald-500/10" :
              "text-zinc-400"
            )}
            title={`阈值: ${stock.rsiOversold || '?'}-${stock.rsiOverbought || '?'}`}
          >
            {stock.rsi?.toFixed(1) || 'N/A'}
            <span className="ml-1 text-[10px] text-zinc-600">({stock.rsiPeriod || 14})</span>
            {stock.rsiStatus && stock.rsiStatus !== '中性' && (
              <span className="ml-1 text-xs opacity-75">{stock.rsiStatus}</span>
            )}
          </span>
        )}
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        {stock._loading ? (
          <div className="space-y-1">
            <div className="h-4 w-14 bg-zinc-700/50 rounded animate-pulse ml-auto" />
            <div className="h-3 w-10 bg-zinc-700/50 rounded animate-pulse ml-auto" />
          </div>
        ) : stock.weeklyMacdStatus ? (
          <div className="flex flex-col items-end leading-tight">
            <span className={clsx(
              "text-xs font-bold",
              stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" :
              stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
              stock.weeklyMacdStatus === '周线回调' ? "text-yellow-500" :
              "text-rose-400"
            )}>
              {stock.weeklyMacdStatus}
            </span>
            <span className={clsx(
              "text-[10px]",
              stock.weeklyPriceVsMA5 === '线上' ? "text-emerald-500/80" : "text-rose-500/80"
            )}>
              5W{stock.weeklyPriceVsMA5}
            </span>
          </div>
        ) : (
          <span className="text-zinc-600 text-xs">-</span>
        )}
      </div>

      {/* Delete Action */}
      <div className="absolute right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center h-full top-0">
        <button
          onClick={(e) => onRemoveStock(e, stock.symbol)}
          className="p-2 bg-zinc-800 hover:bg-rose-500/20 hover:text-rose-400 text-zinc-500 rounded-lg shadow-lg border border-zinc-700"
          title="Remove from Watchlist"
        >
          <Trash2 size={16} />
        </button>
      </div>
    </div>
      {showCharts && miniCandles && miniCandles.length > 0 && (
        <div className="px-4 pb-4" onClick={() => onStockClick(stock)}>
          <Suspense fallback={<div className="h-[120px] bg-zinc-900/30 rounded-lg animate-pulse" />}>
            <MiniChart candles={miniCandles} emaMode={emaMode} />
          </Suspense>
        </div>
      )}
    </div>
  );
});
