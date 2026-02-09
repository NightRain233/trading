import React from 'react';
import { clsx } from 'clsx';
import type { StockData } from '../types';

interface FilterBarProps {
  showFilters: boolean;
  activeFilters: string[];
  toggleFilter: (filter: string) => void;
  setActiveFilters: (filters: string[]) => void;
  sortConfig: {
    key: keyof StockData | 'weeklyStatus';
    direction: 'asc' | 'desc' | null;
  };
  toggleSort: (key: any) => void;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  showFilters,
  activeFilters,
  toggleFilter,
  setActiveFilters,
  sortConfig,
  toggleSort,
}) => {
  return (
    <>
      {/* Filter Toolbar */}
      {showFilters && (
        <div className="mb-6 p-4 bg-zinc-900/50 border border-zinc-800 rounded-xl flex flex-wrap gap-2 animate-in fade-in slide-in-from-top-2">
          <span className="text-xs text-zinc-500 w-full mb-1">筛选周线状态:</span>
          {['周线牛市', '周线反弹', '周线回调', '周线熊市'].map(f => (
            <button
              key={f}
              onClick={() => toggleFilter(f)}
              className={clsx(
                "px-3 py-1 rounded-full text-xs font-medium transition-all",
                activeFilters.includes(f) 
                  ? "bg-emerald-500 text-white" 
                  : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
              )}
            >
              {f}
            </button>
          ))}
          {activeFilters.length > 0 && (
            <button 
              onClick={() => setActiveFilters([])}
              className="px-3 py-1 text-xs text-rose-400 hover:text-rose-300"
            >
              清除全部
            </button>
          )}
        </div>
      )}

      {/* Mobile Sort Tabs */}
      <div className="flex sm:hidden overflow-x-auto gap-2 pb-4 mb-2 no-scrollbar items-center">
        <span className="text-[10px] text-zinc-500 whitespace-nowrap mr-1">排序:</span>
        {[
          { label: '代码', key: 'symbol' },
          { label: '价格', key: 'price' },
          { label: '趋势', key: 'trend' },
          { label: '信号', key: 'signal' },
          { label: 'RSI', key: 'rsi' },
          { label: '周线', key: 'weeklyStatus' },
        ].map(item => (
          <button
            key={item.key}
            onClick={() => toggleSort(item.key)}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap border transition-all flex items-center gap-1",
              sortConfig.key === item.key 
                ? "bg-emerald-500/10 border-emerald-500/50 text-emerald-400" 
                : "bg-zinc-900 border-zinc-800 text-zinc-500"
            )}
          >
            {item.label}
            {sortConfig.key === item.key && (
              <span className="text-[10px] leading-none">{sortConfig.direction === 'asc' ? '↑' : '↓'}</span>
            )}
          </button>
        ))}
      </div>
    </>
  );
};
