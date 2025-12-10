import { useState } from 'react';
import { ChevronDown, ChevronRight, GripVertical } from 'lucide-react';
import type { WatchlistGroup, StockData } from '../types';
import { clsx } from 'clsx';

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
        className="flex items-center gap-2 p-3 bg-zinc-800/50 rounded-t-lg cursor-pointer hover:bg-zinc-800 transition-colors border border-zinc-700/50"
        onClick={() => onToggleCollapse(group.id)}
      >
        <GripVertical className="text-zinc-600 cursor-grab" size={16} />
        {group.collapsed ? (
          <ChevronRight className="text-zinc-400" size={18} />
        ) : (
          <ChevronDown className="text-zinc-400" size={18} />
        )}
        <span className="font-medium text-zinc-200">{group.name}</span>
        <span className="text-xs text-zinc-500 ml-2">({group.stocks.length})</span>
      </div>
      
      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/50 rounded-b-lg overflow-hidden">
          {group.stocks.length === 0 ? (
            <div className="p-4 text-center text-zinc-600 text-sm">
              拖拽股票到此分组
            </div>
          ) : (
            <div className="divide-y divide-zinc-800/50">
              {group.stocks.map(stock => renderStockRow(stock))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
