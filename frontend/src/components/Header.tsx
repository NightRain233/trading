import React from 'react';
import { Plus, FolderPlus, Search, RefreshCw, LineChart, SlidersHorizontal, BarChart2 } from 'lucide-react';
import { clsx } from 'clsx';
import type { SymbolResolveCandidate, Timeframe } from '../types';

interface HeaderProps {
  newTicker: string;
  setNewTicker: (val: string) => void;
  handleAddStock: (e: React.FormEvent) => void;
  symbolCandidates: SymbolResolveCandidate[];
  symbolResolving: boolean;
  symbolDropdownOpen: boolean;
  setSymbolDropdownOpen: (val: boolean) => void;
  onSelectSymbolCandidate: (candidate: SymbolResolveCandidate) => void;
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
}

export const Header: React.FC<HeaderProps> = ({
  newTicker,
  setNewTicker,
  handleAddStock,
  symbolCandidates,
  symbolResolving,
  symbolDropdownOpen,
  setSymbolDropdownOpen,
  onSelectSymbolCandidate,
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
}) => {
  const showSymbolDropdown = symbolDropdownOpen && (symbolResolving || symbolCandidates.length > 0);

  return (
    <header className="header-gradient border-b border-zinc-800/50 sticky top-0 z-20">
      {/* Subtle top accent line */}
      <div className="h-[1px] bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent" />

      <div className="max-w-6xl mx-auto px-3 sm:px-4 py-2.5 sm:min-h-16 flex flex-wrap items-center justify-between gap-2 sm:gap-4">
        <h1 className="text-lg font-semibold text-zinc-100">看盘</h1>

        {/* Controls */}
        <div className="flex items-center gap-1.5 sm:gap-2 flex-1 justify-end sm:flex-none min-w-0">
          {/* Add Symbol Form */}
          {(
          <form onSubmit={handleAddStock} className="relative flex items-center gap-1.5">
            <div className="relative">
              <input
                type="text"
                placeholder="Symbol..."
                value={newTicker}
                onChange={e => setNewTicker(e.target.value)}
                onFocus={() => setSymbolDropdownOpen(symbolCandidates.length > 0)}
                onBlur={() => window.setTimeout(() => setSymbolDropdownOpen(false), 120)}
                className="input-glass rounded-xl px-3 py-2 text-xs sm:text-sm w-20 sm:w-36 focus:outline-none uppercase placeholder:text-zinc-600 font-medium"
              />
              {showSymbolDropdown && (
                <div className="absolute right-0 top-full mt-2 w-72 max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-lg border border-zinc-700/80 bg-zinc-950/95 shadow-2xl shadow-black/40 backdrop-blur z-50">
                  {symbolResolving && symbolCandidates.length === 0 ? (
                    <div className="px-3 py-2 text-xs text-zinc-500">解析中...</div>
                  ) : (
                    <div className="max-h-72 overflow-y-auto py-1">
                      {symbolCandidates.map(candidate => (
                        <button
                          key={candidate.symbol}
                          type="button"
                          onMouseDown={(event) => {
                            event.preventDefault();
                            onSelectSymbolCandidate(candidate);
                          }}
                          className="w-full px-3 py-2 text-left hover:bg-emerald-500/10 focus:bg-emerald-500/10 focus:outline-none"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="min-w-0 truncate text-xs font-semibold text-zinc-100">
                              {candidate.name || candidate.displayCode}
                            </span>
                            <span className="shrink-0 rounded-md border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[10px] text-zinc-400">
                              {candidate.market}
                            </span>
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-500">
                            <span className="font-mono">{candidate.displayCode}</span>
                            <span className="h-1 w-1 rounded-full bg-zinc-700" />
                            <span className="font-mono">Yahoo: {candidate.symbol}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            <button
              type="submit"
              className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-emerald-400"
              title="添加标的"
            >
              <Plus size={16} />
            </button>
          </form>
          )}

          {(
          <button
            onClick={() => setShowNewGroupInput(true)}
            className="btn-glass p-2 rounded-xl text-zinc-400 hover:text-emerald-400"
            title="新建分组"
          >
            <FolderPlus size={16} />
          </button>
          )}

          {<div className="w-px h-5 bg-zinc-800/50 mx-0.5 hidden sm:block" />}

          {/* Search (Desktop) */}
          {(
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
          {(
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
          {(
          <button
            onClick={() => setEmaMode(prev => prev === 'long' ? 'short' : prev === 'short' ? 'boll' : 'long')}
            className="btn-glass px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl text-zinc-400 hover:text-white font-mono font-semibold tracking-tight"
            title="切换均线模式"
          >
            {emaMode === 'long' ? 'EMA 20/50' : emaMode === 'short' ? 'EMA 5/10' : 'BOLL'}
          </button>
          )}

          {/* Timeframe Toggle */}
          {(
          <button
            onClick={() => setChartTimeframe(chartTimeframe === '1D' ? '1W' : '1D')}
            className="btn-glass px-2.5 py-1.5 text-[10px] sm:text-xs rounded-xl text-zinc-400 hover:text-white font-mono font-semibold tracking-tight"
            title="切换日线/周线"
          >
            {chartTimeframe === '1D' ? '日线' : '周线'}
          </button>
          )}

          {/* Chart Toggle */}
          {(
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
          {(
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
