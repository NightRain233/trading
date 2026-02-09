import { memo } from 'react';
import type { StockData, Candle, WatchlistGroup } from '../types';
import { SortableStockRow } from './SortableStockRow';
import { GripVertical, ChevronDown, ChevronRight } from 'lucide-react';
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

  return (
    <div ref={setNodeRef} style={style} className="mb-4">
      {/* Group Header */}
      <div
        className="flex items-center gap-2 p-3 bg-zinc-800/50 rounded-t-lg cursor-pointer hover:bg-zinc-800 transition-colors border border-zinc-700/50"
      >
        <div {...attributes} {...listeners} className="cursor-grab">
          <GripVertical className="text-zinc-600" size={16} />
        </div>
        <div onClick={() => onToggleCollapse(group.id)} className="flex items-center gap-2 flex-1">
          {group.collapsed ? (
            <ChevronRight className="text-zinc-400" size={18} />
          ) : (
            <ChevronDown className="text-zinc-400" size={18} />
          )}
          <span className="font-medium text-zinc-200">{group.name}</span>
          <span className="text-xs text-zinc-500 ml-2">({group.stocks?.length || 0})</span>
        </div>
      </div>

      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/50 rounded-b-lg overflow-hidden">
          {group.stocks?.length === 0 ? (
            <div className="p-4 text-center text-zinc-600 text-sm">
              拖拽股票到此分组
            </div>
          ) : (
            <SortableContextAny items={(group.stocks || []).map(s => s.symbol)} strategy={verticalListSortingStrategy}>
              <div className="divide-y divide-zinc-800/50">
                {group.stocks?.map(stock => (
                  <SortableStockRow
                    key={stock.symbol}
                    stock={stock}
                    onStockClick={onStockClick}
                    onRemoveStock={onRemoveStock}
                    onEditAlias={onEditAlias}
                    miniCandles={chartData[stock.symbol]}
                    emaMode={emaMode}
                    showCharts={showCharts}
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
