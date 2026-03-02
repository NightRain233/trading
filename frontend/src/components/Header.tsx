import React from 'react';
import { TrendingUp, Plus, FolderPlus, Search, RefreshCw, LineChart, SlidersHorizontal } from 'lucide-react';
import { clsx } from 'clsx';

interface HeaderProps {
  newTicker: string;
  setNewTicker: (val: string) => void;
  handleAddStock: (e: React.FormEvent) => void;
  setShowNewGroupInput: (val: boolean) => void;
  searchTerm: string;
  setSearchTerm: (val: string) => void;
  showFilters: boolean;
  setShowFilters: (val: boolean) => void;
  activeFilters: string[];
  emaMode: 'long' | 'short';
  setEmaMode: (val: 'long' | 'short' | ((prev: 'long' | 'short') => 'long' | 'short')) => void;
  showCharts: boolean;
  setShowCharts: (val: boolean) => void;
  loading: boolean;
  handleRefresh: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  newTicker,
  setNewTicker,
  handleAddStock,
  setShowNewGroupInput,
  searchTerm,
  setSearchTerm,
  showFilters,
  setShowFilters,
  activeFilters,
  emaMode,
  setEmaMode,
  showCharts,
  setShowCharts,
  loading,
  handleRefresh,
}) => {
  return (
    <header className="header-gradient border-b border-zinc-800/50 sticky top-0 z-20">
      {/* Subtle top accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />

      <div className="max-w-6xl mx-auto px-4 py-2.5 sm:h-16 flex flex-wrap items-center justify-between gap-2 sm:gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2.5 sm:gap-3">
          <div className="relative">
            <div className="bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 p-2 rounded-xl border border-emerald-500/20 shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)]">
              <TrendingUp className="text-emerald-400" size={20} />
            </div>
            <div className="absolute -inset-1 bg-emerald-500/5 rounded-xl blur-md -z-10" />
          </div>
          <h1 className="text-xl sm:text-2xl font-black tracking-tight bg-gradient-to-br from-white via-zinc-200 to-zinc-500 bg-clip-text text-transparent select-none">
            TrendMaster
          </h1>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2 flex-1 justify-end sm:flex-none">
          {/* Add Symbol Form */}
          <form onSubmit={handleAddStock} className="flex items-center gap-1.5">
            <input
              type="text"
              placeholder="Symbol..."
              value={newTicker}
              onChange={e => setNewTicker(e.target.value)}
              className="input-glass rounded-xl px-3 py-2 text-xs sm:text-sm w-20 sm:w-36 focus:outline-none uppercase placeholder:text-zinc-600 font-medium"
            />
            <button
              type="submit"
              className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-emerald-400"
              title="添加标的"
            >
              <Plus size={16} />
            </button>
          </form>

          <button
            onClick={() => setShowNewGroupInput(true)}
            className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-emerald-400"
            title="新建分组"
          >
            <FolderPlus size={16} />
          </button>

          <div className="w-px h-5 bg-zinc-800/50 mx-0.5 hidden sm:block" />

          {/* Search (Desktop) */}
          <div className="relative hidden md:block">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={14} />
            <input
              type="text"
              placeholder="搜索..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="input-glass rounded-full pl-9 pr-4 py-2 text-sm focus:outline-none w-28 lg:w-44 placeholder:text-zinc-600"
            />
          </div>

          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={clsx(
              "p-2 rounded-xl transition-all duration-200 border",
              activeFilters.length > 0
                ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-[0_0_12px_-4px_rgba(16,185,129,0.3)]"
                : "btn-glass text-zinc-500 hover:text-zinc-300"
            )}
            title="筛选"
          >
            <SlidersHorizontal size={15} className={clsx(showFilters && "rotate-90", "transition-transform duration-200")} />
          </button>

          {/* EMA Toggle */}
          <button
            onClick={() => setEmaMode(prev => prev === 'long' ? 'short' : 'long')}
            className="btn-glass px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl text-zinc-400 hover:text-white font-mono font-semibold tracking-tight"
            title="切换 EMA 均线"
          >
            {emaMode === 'long' ? 'EMA 20/50' : 'EMA 5/10'}
          </button>

          {/* Chart Toggle */}
          <button
            onClick={() => setShowCharts(!showCharts)}
            className={clsx(
              "px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl border font-semibold transition-all duration-200 flex items-center gap-1.5",
              showCharts
                ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400 shadow-[0_0_12px_-4px_rgba(16,185,129,0.3)]"
                : "btn-glass text-zinc-400 hover:text-white"
            )}
            title="显示/隐藏趋势图"
          >
            <LineChart size={13} />
            <span className="hidden sm:inline">30日</span>
          </button>

          {/* Refresh */}
          <button
            onClick={handleRefresh}
            className={clsx(
              "p-2 text-zinc-500 hover:text-emerald-400 hover:bg-zinc-800/50 rounded-xl transition-all duration-200",
              loading && "animate-spin"
            )}
            title="刷新数据"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>
    </header>
  );
};
