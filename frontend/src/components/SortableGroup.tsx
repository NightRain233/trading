import { memo } from 'react';
import type { StockData, Candle, Timeframe, WatchlistGroup } from '../types';
import { SortableStockRow } from './SortableStockRow';
import { GripVertical, ChevronDown, ChevronRight, Layers } from 'lucide-react';
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

const SortableContextAny = SortableContext as any;

interface SortableGroupProps {
  group: WatchlistGroup;
  onToggleCollapse: (groupId: string) => void;
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
  onEditAlias: (stock: StockData) => void;
  chartData: Record<string, Candle[]>;
  chartTimeframe: Timeframe;
  emaMode: 'long' | 'short';
  showCharts: boolean;
}

export const SortableGroup = memo(function SortableGroup({
  group,
  onToggleCollapse,
  onStockClick,
  onRemoveStock,
  onEditAlias,
  chartData,
  chartTimeframe,
  emaMode,
  showCharts
}: SortableGroupProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: group.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const stockCount = group.stocks?.length || 0;
  const bullCount = group.stocks?.filter(s =>
    s.trend === '强势多头' || s.trend === '回调多头'
  ).length || 0;
  const bearCount = group.stocks?.filter(s =>
    s.trend === '强势空头' || s.trend === '反弹空头'
  ).length || 0;

  return (
    <div ref={setNodeRef} style={style} className="mb-5 animate-fade-in-up">
      {/* Group Header */}
      <div className="group-header flex items-center gap-2.5 px-4 py-3.5 rounded-t-2xl cursor-pointer border border-zinc-700/30 border-b-0 transition-all duration-200">
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab hover:text-zinc-300 transition-colors"
        >
          <GripVertical className="text-zinc-600" size={16} />
        </div>
        <div
          onClick={() => onToggleCollapse(group.id)}
          className="flex items-center gap-2.5 flex-1"
        >
          <div className="text-zinc-400 transition-transform duration-200">
            {group.collapsed ? (
              <ChevronRight size={18} />
            ) : (
              <ChevronDown size={18} />
            )}
          </div>
          <div className="flex items-center gap-2">
            <Layers size={14} className="text-zinc-500" />
            <span className="font-semibold text-zinc-100 tracking-tight text-sm">
              {group.name}
            </span>
          </div>
          <div className="flex items-center gap-1.5 ml-1">
            <span className="text-[10px] text-zinc-500 bg-zinc-800/50 px-1.5 py-0.5 rounded-md font-medium">
              {stockCount}
            </span>
            {bullCount > 0 && (
              <span className="text-[10px] text-emerald-500/70 bg-emerald-500/5 px-1.5 py-0.5 rounded-md font-medium">
                ↑{bullCount}
              </span>
            )}
            {bearCount > 0 && (
              <span className="text-[10px] text-rose-500/70 bg-rose-500/5 px-1.5 py-0.5 rounded-md font-medium">
                ↓{bearCount}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/20 rounded-b-2xl overflow-hidden bg-zinc-900/10">
          {stockCount === 0 ? (
            <div className="p-8 text-center text-zinc-600 text-sm">
              <div className="text-zinc-700 mb-1">📦</div>
              拖拽股票到此分组
            </div>
          ) : (
            <SortableContextAny items={(group.stocks || []).map(s => s.symbol)} strategy={verticalListSortingStrategy}>
              <div>
                {group.stocks?.map((stock, index) => (
                  <SortableStockRow
                    key={stock.symbol}
                    stock={stock}
                    onStockClick={onStockClick}
                    onRemoveStock={onRemoveStock}
                    onEditAlias={onEditAlias}
                    miniCandles={chartData[stock.symbol]}
                    chartTimeframe={chartTimeframe}
                    emaMode={emaMode}
                    showCharts={showCharts}
                    index={index}
                  />
                ))}
              </div>
            </SortableContextAny>
          )}
        </div>
      )}
    </div>
  );
});
