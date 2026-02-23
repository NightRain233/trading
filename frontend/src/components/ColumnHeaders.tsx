import React from 'react';
import type { StockData } from '../types';

interface ColumnHeadersProps {
  sortConfig: {
    key: keyof StockData | 'weeklyStatus';
    direction: 'asc' | 'desc' | null;
  };
  toggleSort: (key: any) => void;
}

export const ColumnHeaders: React.FC<ColumnHeadersProps> = ({ sortConfig, toggleSort }) => {
  return (
    <div className="hidden sm:grid grid-cols-12 gap-4 px-4 pb-2 text-xs font-semibold text-zinc-500 uppercase tracking-wider select-none">
      <div className="col-span-4 sm:col-span-2 pl-4 cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('symbol')}>
        Symbol {sortConfig.key === 'symbol' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
      <div className="col-span-3 sm:col-span-2 text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('price')}>
        Price {sortConfig.key === 'price' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
      <div className="col-span-3 sm:col-span-2 text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('trend')}>
        趋势 {sortConfig.key === 'trend' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
      <div className="col-span-2 hidden sm:block text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('signal')}>
        Signal {sortConfig.key === 'signal' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
      <div className="col-span-2 hidden sm:block text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('rsi')}>
        RSI {sortConfig.key === 'rsi' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
      <div className="col-span-2 hidden sm:block text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('weeklyStatus')}>
        Weekly {sortConfig.key === 'weeklyStatus' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
      </div>
    </div>
  );
};
