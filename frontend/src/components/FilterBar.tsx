import React from 'react';
import { clsx } from 'clsx';
import type { StockData } from '../types';
import { X } from 'lucide-react';

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
        <div className="mb-5 p-5 glass-card rounded-2xl animate-slide-down shadow-xl">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold">周线状态</span>
            {activeFilters.length > 0 && (
              <button
                onClick={() => setActiveFilters([])}
                className="flex items-center gap-1 px-2 py-0.5 text-[10px] text-rose-400 hover:text-rose-300 bg-rose-500/5 hover:bg-rose-500/10 rounded-md transition-all"
              >
                <X size={10} />
                清除全部
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-2 mb-4">
            {['周线牛市', '周线反弹', '周线回调', '周线熊市'].map(f => (
              <button
                key={f}
                onClick={() => toggleFilter(f)}
                className={clsx(
                  "px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 border",
                  activeFilters.includes(f)
                    ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-400 shadow-[0_0_16px_-4px_rgba(16,185,129,0.25)]"
                    : "bg-zinc-800/30 border-zinc-700/25 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 hover:border-zinc-600/40"
                )}
              >
                {f}
              </button>
            ))}
          </div>

          <span className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold block mb-2">趋势状态</span>
          <div className="flex flex-wrap gap-2">
            {['强势多头', '潜在转多', '强势空头', '潜在转空'].map(f => (
              <button
                key={f}
                onClick={() => toggleFilter(f)}
                className={clsx(
                  "px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 border",
                  activeFilters.includes(f)
                    ? "bg-sky-500/15 border-sky-500/40 text-sky-400 shadow-[0_0_16px_-4px_rgba(14,165,233,0.25)]"
                    : "bg-zinc-800/30 border-zinc-700/25 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 hover:border-zinc-600/40"
                )}
              >
                {f}
              </button>
            ))}
          </div>

          <span className="text-[10px] text-zinc-500 uppercase tracking-widest font-semibold block mt-4 mb-2">共振策略</span>
          <div className="flex flex-wrap gap-2">
            {['共振买点', '离场预警', '共振离场'].map(f => (
              <button
                key={f}
                onClick={() => toggleFilter(f)}
                className={clsx(
                  "px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-200 border",
                  activeFilters.includes(f)
                    ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-300 shadow-[0_0_16px_-4px_rgba(34,211,238,0.25)]"
                    : "bg-zinc-800/30 border-zinc-700/25 text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50 hover:border-zinc-600/40"
                )}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Mobile Sort Tabs */}
      <div className="flex sm:hidden overflow-x-auto gap-1.5 pb-4 mb-2 no-scrollbar items-center">
        <span className="text-[10px] text-zinc-600 whitespace-nowrap mr-1 font-medium">排序</span>
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
              "px-3 py-1.5 rounded-xl text-xs font-medium whitespace-nowrap border transition-all duration-200 flex items-center gap-1",
              sortConfig.key === item.key
                ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400"
                : "bg-zinc-900/50 border-zinc-800/50 text-zinc-500 hover:text-zinc-300"
            )}
          >
            {item.label}
            {sortConfig.key === item.key && (
              <span className="text-[10px] leading-none font-bold">{sortConfig.direction === 'asc' ? '↑' : '↓'}</span>
            )}
          </button>
        ))}
      </div>
    </>
  );
};
