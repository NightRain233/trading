import React from 'react';
import { TrendingUp, Plus, FolderPlus, Search, RefreshCw, LineChart } from 'lucide-react';
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
    <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-4 py-2 sm:h-16 flex flex-wrap items-center justify-between gap-2 sm:gap-4">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="bg-emerald-500/10 p-1.5 sm:p-2 rounded-lg border border-emerald-500/20">
            <TrendingUp className="text-emerald-400" size={20} />
          </div>
          <h1 className="text-lg sm:text-xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">
            TrendMaster
          </h1>
        </div>
        
        <div className="flex items-center gap-2 flex-1 justify-end sm:flex-none">
          <form onSubmit={handleAddStock} className="flex items-center gap-1 sm:gap-2">
            <input 
              type="text" 
              placeholder="Add Symbol" 
              value={newTicker}
              onChange={e => setNewTicker(e.target.value)}
              className="bg-zinc-900 border border-zinc-700 rounded-lg px-2 sm:px-3 py-1.5 text-xs sm:text-sm w-20 sm:w-36 focus:outline-none focus:border-emerald-500/50 uppercase"
            />
            <button type="submit" className="p-1.5 sm:p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors">
              <Plus size={16} />
            </button>
          </form>

          <button 
            onClick={() => setShowNewGroupInput(true)}
            className="p-1.5 sm:p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors"
            title="New Group"
          >
            <FolderPlus size={16} />
          </button>

          <div className="w-px h-6 bg-zinc-800 mx-1 hidden sm:block"></div>

          <div className="relative hidden md:block">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
            <input 
              type="text" 
              placeholder="Search..." 
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="bg-zinc-900 border border-zinc-700 rounded-full pl-10 pr-4 py-1.5 text-sm focus:outline-none focus:border-emerald-500/50 w-32 lg:w-40"
            />
          </div>

          <button
            onClick={() => setShowFilters(!showFilters)}
            className={clsx(
              "p-1.5 sm:p-2 rounded-lg transition-colors border",
              activeFilters.length > 0 ? "bg-emerald-500/10 border-emerald-500/50 text-emerald-400" : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white"
            )}
            title="Filter by Weekly Status"
          >
            <Search size={16} className={clsx(showFilters && "rotate-90")} style={{ transition: 'transform 0.2s' }} />
          </button>

          <button
             onClick={() => setEmaMode(prev => prev === 'long' ? 'short' : 'long')}
             className="px-2 py-1 sm:py-1.5 text-[10px] sm:text-xs font-mono rounded-lg border bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors"
             title="切换 EMA 均线"
           >
             {emaMode === 'long' ? 'EMA 20/50' : 'EMA 5/10'}
           </button>

           <button
             onClick={() => setShowCharts(!showCharts)}
             className={clsx(
               "px-2 py-1 sm:py-1.5 text-[10px] sm:text-xs font-mono rounded-lg border transition-colors flex items-center gap-1.5",
               showCharts ? "bg-emerald-500/10 border-emerald-500/50 text-emerald-400" : "bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-white"
             )}
             title="显示/隐藏 10日趋势图"
           >
             <LineChart size={14} />
             30日图
           </button>

          <button 
            onClick={handleRefresh}
            className={clsx(
              "p-1.5 sm:p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors",
              loading && "animate-spin"
            )}
            title="Refresh Data"
          >
            <RefreshCw size={18} className="sm:w-5 sm:h-5" />
          </button>
        </div>
      </div>
    </header>
  );
};
