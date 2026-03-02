import { ChevronDown, ChevronRight, GripVertical } from 'lucide-react';
import type { WatchlistGroup, StockData } from '../types';

interface StockGroupProps {
  group: WatchlistGroup;
  onToggleCollapse: (groupId: string) => void;
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
  renderStockRow: (stock: StockData) => React.ReactNode;
}

export function StockGroup({
  group,
  onToggleCollapse,
  renderStockRow
}: StockGroupProps) {
  return (
    <div className="mb-4">
      {/* Group Header */}
      <div
        className="flex items-center gap-2 p-3.5 bg-zinc-800/30 backdrop-blur-sm rounded-t-xl cursor-pointer hover:bg-zinc-800/50 transition-all border border-zinc-700/30 border-b-0 group/group-header"
        onClick={() => onToggleCollapse(group.id)}
      >
        <GripVertical className="text-zinc-600 cursor-grab group-hover/group-header:text-zinc-400 transition-colors" size={16} />
        {group.collapsed ? (
          <ChevronRight className="text-zinc-400" size={18} />
        ) : (
          <ChevronDown className="text-zinc-400" size={18} />
        )}
        <span className="font-semibold text-zinc-100 tracking-tight">{group.name}</span>
        <span className="text-xs text-zinc-500 ml-2">({(group.stocks || []).length})</span>
      </div>

      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/30 rounded-b-xl overflow-hidden bg-zinc-900/10">
          {(group.stocks || []).length === 0 ? (
            <div className="p-4 text-center text-zinc-600 text-sm">
              拖拽股票到此分组
            </div>
          ) : (
            <div className="divide-y divide-zinc-800/50">
              {(group.stocks || []).map(stock => renderStockRow(stock))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
