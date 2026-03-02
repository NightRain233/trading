import React from 'react';
import type { StockData } from '../types';
import { clsx } from 'clsx';
import { ArrowUpDown, ChevronUp, ChevronDown } from 'lucide-react';

interface ColumnHeadersProps {
  sortConfig: {
    key: keyof StockData | 'weeklyStatus';
    direction: 'asc' | 'desc' | null;
  };
  toggleSort: (key: any) => void;
}

const SortIndicator = ({ active, direction }: { active: boolean; direction: 'asc' | 'desc' | null }) => {
  if (!active) return <ArrowUpDown size={10} className="text-zinc-700 opacity-0 group-hover/col:opacity-100 transition-opacity ml-1" />;
  return direction === 'asc'
    ? <ChevronUp size={12} className="text-emerald-400 ml-0.5" />
    : <ChevronDown size={12} className="text-emerald-400 ml-0.5" />;
};

export const ColumnHeaders: React.FC<ColumnHeadersProps> = ({ sortConfig, toggleSort }) => {
  return (
    <div className="hidden sm:grid grid-cols-12 gap-4 px-4 pb-3 pt-1 text-[10px] font-semibold text-zinc-600 uppercase tracking-widest select-none">
      <div
        className={clsx(
          "col-span-2 pl-5 cursor-pointer hover:text-zinc-400 transition-colors flex items-center gap-0.5 group/col",
          sortConfig.key === 'symbol' && "text-zinc-400"
        )}
        onClick={() => toggleSort('symbol')}
      >
        Symbol
        <SortIndicator active={sortConfig.key === 'symbol'} direction={sortConfig.direction} />
      </div>
      <div
        className={clsx(
          "col-span-2 text-right cursor-pointer hover:text-zinc-400 transition-colors flex items-center justify-end gap-0.5 group/col",
          sortConfig.key === 'price' && "text-zinc-400"
        )}
        onClick={() => toggleSort('price')}
      >
        Price
        <SortIndicator active={sortConfig.key === 'price'} direction={sortConfig.direction} />
      </div>
      <div
        className={clsx(
          "col-span-2 text-right cursor-pointer hover:text-zinc-400 transition-colors flex items-center justify-end gap-0.5 group/col",
          sortConfig.key === 'trend' && "text-zinc-400"
        )}
        onClick={() => toggleSort('trend')}
      >
        趋势
        <SortIndicator active={sortConfig.key === 'trend'} direction={sortConfig.direction} />
      </div>
      <div
        className={clsx(
          "col-span-2 text-right cursor-pointer hover:text-zinc-400 transition-colors flex items-center justify-end gap-0.5 group/col",
          sortConfig.key === 'signal' && "text-zinc-400"
        )}
        onClick={() => toggleSort('signal')}
      >
        Signal
        <SortIndicator active={sortConfig.key === 'signal'} direction={sortConfig.direction} />
      </div>
      <div
        className={clsx(
          "col-span-2 text-right cursor-pointer hover:text-zinc-400 transition-colors flex items-center justify-end gap-0.5 group/col",
          sortConfig.key === 'rsi' && "text-zinc-400"
        )}
        onClick={() => toggleSort('rsi')}
      >
        RSI
        <SortIndicator active={sortConfig.key === 'rsi'} direction={sortConfig.direction} />
      </div>
      <div
        className={clsx(
          "col-span-2 text-right cursor-pointer hover:text-zinc-400 transition-colors flex items-center justify-end gap-0.5 group/col",
          sortConfig.key === 'weeklyStatus' && "text-zinc-400"
        )}
        onClick={() => toggleSort('weeklyStatus')}
      >
        Weekly
        <SortIndicator active={sortConfig.key === 'weeklyStatus'} direction={sortConfig.direction} />
      </div>
    </div>
  );
};
