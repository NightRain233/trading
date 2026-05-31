import React from 'react';
import { TrendingUp, Plus, FolderPlus, Search, RefreshCw, LineChart, SlidersHorizontal, BarChart2 } from 'lucide-react';
import { clsx } from 'clsx';
import type { Timeframe } from '../types';

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
  emaMode: 'long' | 'short' | 'boll';
  setEmaMode: (val: 'long' | 'short' | 'boll' | ((prev: 'long' | 'short' | 'boll') => 'long' | 'short' | 'boll')) => void;
  showCharts: boolean;
  setShowCharts: (val: boolean) => void;
  chartTimeframe: Timeframe;
  setChartTimeframe: (val: Timeframe) => void;
  loading: boolean;
  handleRefresh: () => void;
  onShowBacktest: () => void;
  activeTab: 'watchlist' | 'rs' | 'wbb' | 'st' | 'history';
  onTabChange: (tab: 'watchlist' | 'rs' | 'wbb' | 'st' | 'history') => void;
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
  chartTimeframe,
  setChartTimeframe,
  loading,
  handleRefresh,
  onShowBacktest,
  activeTab,
  onTabChange,
}) => {
  const isWatchlist = activeTab === 'watchlist';
  const tabClass = (tab: HeaderProps['activeTab']) => clsx(
    "shrink-0 px-2.5 py-1.5 text-[10px] sm:text-xs rounded-lg border font-semibold transition-all duration-200 active:scale-[0.98]",
    activeTab === tab
      ? tab === 'st'
        ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-300"
        : tab === 'rs'
          ? "bg-amber-500/10 border-amber-500/40 text-amber-300"
          : tab === 'wbb'
            ? "bg-indigo-500/10 border-indigo-500/40 text-indigo-300"
            : tab === 'history'
              ? "bg-sky-500/10 border-sky-500/40 text-sky-300"
              : "bg-zinc-700/60 border-zinc-600 text-zinc-100"
      : "btn-glass text-zinc-400 hover:text-zinc-200"
  );

  return (
    <header className="header-gradient border-b border-zinc-800/50 sticky top-0 z-20">
      {/* Subtle top accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />

      <div className="max-w-6xl mx-auto px-3 sm:px-4 py-2.5 sm:min-h-16 flex flex-wrap items-center justify-between gap-2 sm:gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2.5 sm:gap-3">
          <div className="relative">
            <div className="bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 p-1.5 sm:p-2 rounded-xl border border-emerald-500/20 shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)]">
              <TrendingUp className="text-emerald-400" size={18} />
            </div>
            <div className="absolute -inset-1 bg-emerald-500/5 rounded-xl blur-md -z-10" />
          </div>
          <h1 className="text-lg sm:text-2xl font-black tracking-tight bg-gradient-to-br from-white via-zinc-200 to-zinc-500 bg-clip-text text-transparent select-none">
            TrendMaster
          </h1>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2 flex-1 justify-end sm:flex-none min-w-0">
          <nav className="order-2 sm:order-none basis-full sm:basis-auto flex items-center gap-1.5 overflow-x-auto no-scrollbar pt-1 sm:pt-0">
            <button onClick={() => onTabChange('watchlist')} className={tabClass('watchlist')} title="自选">
              自选
            </button>
            <button onClick={() => onTabChange('st')} className={tabClass('st')} title="SuperTrend">
              ST
            </button>
            <button onClick={() => onTabChange('rs')} className={tabClass('rs')} title="RS 轮动">
              RS轮动
            </button>
            <button onClick={() => onTabChange('wbb')} className={tabClass('wbb')} title="周线BB突破">
              周线BB
            </button>
            <button onClick={() => onTabChange('history')} className={tabClass('history')} title="历史买卖点复盘">
              复盘
            </button>
          </nav>

          {/* Add Symbol Form */}
          {isWatchlist && (
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
          )}

          {isWatchlist && (
          <button
            onClick={() => setShowNewGroupInput(true)}
            className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-emerald-400"
            title="新建分组"
          >
            <FolderPlus size={16} />
          </button>
          )}

          {isWatchlist && <div className="w-px h-5 bg-zinc-800/50 mx-0.5 hidden sm:block" />}

          {/* Search (Desktop) */}
          {isWatchlist && (
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
          )}

          {/* Filter toggle */}
          {isWatchlist && (
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
          )}

          {/* EMA Toggle */}
          {isWatchlist && (
          <button
            onClick={() => setEmaMode(prev => prev === 'long' ? 'short' : prev === 'short' ? 'boll' : 'long')}
            className="btn-glass px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl text-zinc-400 hover:text-white font-mono font-semibold tracking-tight"
            title="切换均线模式"
          >
            {emaMode === 'long' ? 'EMA 20/50' : emaMode === 'short' ? 'EMA 5/10' : 'BOLL'}
          </button>
          )}

          {/* Timeframe Toggle */}
          {isWatchlist && (
          <button
            onClick={() => setChartTimeframe(chartTimeframe === '1D' ? '1W' : '1D')}
            className="btn-glass px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl text-zinc-400 hover:text-white font-mono font-semibold tracking-tight"
            title="切换日线/周线"
          >
            {chartTimeframe === '1D' ? '日线' : '周线'}
          </button>
          )}

          {/* Chart Toggle */}
          {isWatchlist && (
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
            <span className="hidden sm:inline">{chartTimeframe === '1D' ? '30日' : '30周'}</span>
          </button>
          )}

          {/* Backtest */}
          {isWatchlist && (
          <button
            onClick={onShowBacktest}
            className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-amber-400"
            title="回测"
          >
            <BarChart2 size={16} />
          </button>
          )}

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
