import { useState, useEffect, useMemo } from 'react';
import { fetchWatchlist, fetchStockData, addTicker, removeTicker, createGroup, updateWatchlist, updateAlias } from './utils';
import type { StockData, WatchlistGroup } from './types';
import { ChartModal } from './components/ChartModal';
import { StatusBadge } from './components/StatusBadge';
import { RefreshCw, TrendingUp, Search, Plus, Trash2, FolderPlus, GripVertical, ChevronDown, ChevronRight, Pencil } from 'lucide-react';
import { clsx } from 'clsx';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent, DragStartEvent } from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

// Sortable Stock Row Component
function SortableStockRow({ 
  stock, 
  onStockClick, 
  onRemoveStock,
  onEditAlias
}: { 
  stock: StockData; 
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
  onEditAlias: (stock: StockData) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: stock.symbol });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div 
      ref={setNodeRef}
      style={style}
      className="flex flex-col sm:grid sm:grid-cols-12 gap-2 sm:gap-4 p-4 items-start sm:items-center hover:bg-zinc-800/50 transition-colors cursor-pointer group relative bg-zinc-900/30 border-b border-zinc-800/30 sm:border-none"
      onClick={() => onStockClick(stock)}
    >
      {/* Drag Handle - Hidden on very small screens or repositioned */}
      <div 
        className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 sm:block hidden cursor-grab"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="text-zinc-600" size={14} />
      </div>

      <div className="flex items-center justify-between w-full sm:col-span-2 sm:pl-4">
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-1 group/title">
            <div className="font-bold text-white group-hover:text-emerald-400 transition-colors truncate">
              {stock.alias || stock.symbol}
              {stock.alias && <span className="ml-1 text-[10px] text-zinc-500 font-normal">({stock.symbol})</span>}
            </div>
            <button 
              className="opacity-0 group-hover/title:opacity-100 p-0.5 text-zinc-600 hover:text-zinc-300 transition-opacity"
              onClick={(e) => {
                e.stopPropagation();
                onEditAlias(stock);
              }}
              title="Edit Alias"
            >
              <Pencil size={12} />
            </button>
          </div>
          <div className="text-[10px] sm:text-xs text-zinc-500 truncate max-w-[120px] sm:max-w-none">{stock.name}</div>
        </div>

        {/* Mobile Price Display */}
        <div className="sm:hidden text-right leading-tight">
          <div className="font-mono text-zinc-200">${(stock.price || 0).toFixed(2)}</div>
          <div className={clsx("text-[10px] font-mono", (stock.changePercent || 0) >= 0 ? "text-emerald-400" : "text-rose-400")}>
            {(stock.changePercent || 0) >= 0 ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
          </div>
        </div>
      </div>
      
      <div className="hidden sm:block sm:col-span-2 text-right">
        <div className="font-mono text-zinc-200">${(stock.price || 0).toFixed(2)}</div>
        <div className={clsx("text-xs font-mono", (stock.changePercent || 0) >= 0 ? "text-emerald-400" : "text-rose-400")}>
          {(stock.changePercent || 0) >= 0 ? '+' : ''}{(stock.changePercent || 0).toFixed(2)}%
        </div>
      </div>

      {/* Badges/Status Row */}
      <div className="flex items-center justify-between sm:justify-end w-full sm:col-span-2 gap-2">
        <div className="sm:hidden flex items-center gap-2">
          {stock.signal && stock.signal !== '观望' && (
            <span className={clsx(
              "px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap",
              stock.signal === '强烈信号' ? "bg-emerald-500 text-white" : "bg-yellow-500 text-zinc-900"
            )}>
              {stock.signal}
            </span>
          )}
          {stock.weeklyMacdStatus && (
            <span className={clsx(
              "text-[10px] font-bold whitespace-nowrap",
              stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" : 
              stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
              stock.weeklyMacdStatus === '周线回调' ? "text-yellow-500" :
              "text-rose-400"
            )}>
              {stock.weeklyMacdStatus}
            </span>
          )}
        </div>
        <StatusBadge status={stock.trend} type="trend" />
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        {stock.signal === '强烈信号' || stock.signal === '谨慎信号' ? (
          <span className={clsx(
            "px-2 py-1 rounded text-xs font-bold",
            stock.signal === '强烈信号' ? "bg-emerald-500 text-white" : "bg-yellow-500 text-zinc-900"
          )}>
            {stock.signal}
          </span>
        ) : (
          <span className="text-zinc-600 text-xs">观望</span>
        )}
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        <span 
          className={clsx(
            "font-mono text-sm px-2 py-0.5 rounded",
            stock.rsiStatus === '超买' ? "text-rose-400 bg-rose-500/10" : 
            stock.rsiStatus === '超卖' ? "text-emerald-400 bg-emerald-500/10" : 
            "text-zinc-400"
          )}
          title={`阈值: ${stock.rsiOversold || '?'}-${stock.rsiOverbought || '?'}`}
        >
          {stock.rsi?.toFixed(1) || 'N/A'}
          <span className="ml-1 text-[10px] text-zinc-600">({stock.rsiPeriod || 14})</span>
          {stock.rsiStatus && stock.rsiStatus !== '中性' && (
            <span className="ml-1 text-xs opacity-75">{stock.rsiStatus}</span>
          )}
        </span>
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        {stock.weeklyMacdStatus ? (
          <div className="flex flex-col items-end leading-tight">
            <span className={clsx(
              "text-xs font-bold",
              stock.weeklyMacdStatus === '周线牛市' ? "text-emerald-400" : 
              stock.weeklyMacdStatus === '周线反弹' ? "text-emerald-500/60" :
              stock.weeklyMacdStatus === '周线回调' ? "text-yellow-500" :
              "text-rose-400"
            )}>
              {stock.weeklyMacdStatus}
            </span>
            <span className={clsx(
              "text-[10px]",
              stock.weeklyPriceVsMA5 === '线上' ? "text-emerald-500/80" : "text-rose-500/80"
            )}>
              5W{stock.weeklyPriceVsMA5}
            </span>
          </div>
        ) : (
          <span className="text-zinc-600 text-xs">-</span>
        )}
      </div>

      {/* Delete Action - Floating button on mobile */}
      <div className="absolute right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center h-full top-0">
        <button 
          onClick={(e) => onRemoveStock(e, stock.symbol)}
          className="p-2 bg-zinc-800 hover:bg-rose-500/20 hover:text-rose-400 text-zinc-500 rounded-lg shadow-lg border border-zinc-700"
          title="Remove from Watchlist"
        >
          <Trash2 size={16} />
        </button>
      </div>
    </div>
  );
}

// Sortable Group Component
function SortableGroup({
  group,
  onToggleCollapse,
  onStockClick,
  onRemoveStock,
  onEditAlias
}: {
  group: WatchlistGroup;
  onToggleCollapse: (groupId: string) => void;
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
  onEditAlias: (stock: StockData) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: group.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="mb-4">
      {/* Group Header */}
      <div 
        className="flex items-center gap-2 p-3 bg-zinc-800/50 rounded-t-lg cursor-pointer hover:bg-zinc-800 transition-colors border border-zinc-700/50"
      >
        <div {...attributes} {...listeners} className="cursor-grab">
          <GripVertical className="text-zinc-600" size={16} />
        </div>
        <div onClick={() => onToggleCollapse(group.id)} className="flex items-center gap-2 flex-1">
          {group.collapsed ? (
            <ChevronRight className="text-zinc-400" size={18} />
          ) : (
            <ChevronDown className="text-zinc-400" size={18} />
          )}
          <span className="font-medium text-zinc-200">{group.name}</span>
          <span className="text-xs text-zinc-500 ml-2">({group.stocks?.length || 0})</span>
        </div>
      </div>
      
      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/50 rounded-b-lg overflow-hidden">
          {group.stocks?.length === 0 ? (
            <div className="p-4 text-center text-zinc-600 text-sm">
              拖拽股票到此分组
            </div>
          ) : (
            <SortableContext items={group.stocks?.map(s => s.symbol) || []} strategy={verticalListSortingStrategy}>
              <div className="divide-y divide-zinc-800/50">
                {group.stocks?.map(stock => (
                  <SortableStockRow 
                    key={stock.symbol} 
                    stock={stock} 
                    onStockClick={onStockClick}
                    onRemoveStock={onRemoveStock}
                    onEditAlias={onEditAlias}
                  />
                ))}
              </div>
            </SortableContext>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [selectedStock, setSelectedStock] = useState<StockData | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [newTicker, setNewTicker] = useState('');
  const [newGroupName, setNewGroupName] = useState('');
  const [loading, setLoading] = useState(false);
  const [showNewGroupInput, setShowNewGroupInput] = useState(false);
  // Alias Editing State
  const [aliasModalOpen, setAliasModalOpen] = useState(false);
  const [editingAliasStock, setEditingAliasStock] = useState<StockData | null>(null);
  const [aliasInput, setAliasInput] = useState('');
  
  // Sorting and Filtering State
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sortConfig, setSortConfig] = useState<{
    key: keyof StockData | 'weeklyStatus'; 
    direction: 'asc' | 'desc' | null 
  }>({ key: 'price', direction: null });
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  const handleEditAlias = async () => {
    if (!editingAliasStock) return;
    const success = await updateAlias(editingAliasStock.symbol, aliasInput);
    if (success) {
      setAliasModalOpen(false);
      loadData(); // Refresh to show new alias
    } else {
      alert('Failed to update alias');
    }
  };

  const openAliasModal = (stock: StockData) => {
    setEditingAliasStock(stock);
    setAliasInput(stock.alias || '');
    setAliasModalOpen(true);
  };

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      // 1. Fetch group structure (lightweight)
      const groupsData = await fetchWatchlist();
      
      // 2. Collect unique symbols
      const uniqueSymbols = new Set<string>();
      const aliasMap = new Map<string, string>(); // symbol -> alias
      
      groupsData.forEach(g => {
        g.symbols.forEach(s => {
          uniqueSymbols.add(s.symbol);
          if (s.alias) {
            aliasMap.set(s.symbol, s.alias);
          }
        });
      });

      // 3. Fetch stock details in parallel
      const stockMap = new Map<string, StockData>();
      const promises = Array.from(uniqueSymbols).map(async (symbol) => {
        const data = await fetchStockData(symbol);
        if (data) {
          // Merge alias if exists
          if (aliasMap.has(symbol)) {
            data.alias = aliasMap.get(symbol);
          }
          stockMap.set(symbol, data);
        }
      });

      await Promise.all(promises);

      // 4. Populate groups with stock data
      const populatedGroups = groupsData.map(g => ({
        ...g,
        stocks: g.symbols
          .map(symObj => stockMap.get(symObj.symbol))
          .filter((s): s is StockData => s !== undefined)
      }));

      setGroups(populatedGroups);
    } catch (error) {
      console.error("Failed to load watchlist:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddStock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTicker.trim()) return;
    
    const success = await addTicker(newTicker);
    if (success) {
      setNewTicker('');
      loadData();
    } else {
      alert('Failed to add ticker. Check symbol or connection.');
    }
  };

  const handleRemoveStock = async (e: React.MouseEvent, symbol: string) => {
    e.stopPropagation();
    if (confirm(`Remove ${symbol}?`)) {
       await removeTicker(symbol);
       loadData();
    }
  };

  const handleToggleCollapse = async (groupId: string) => {
    const updatedGroups = groups.map(g => 
      g.id === groupId ? { ...g, collapsed: !g.collapsed } : g
    );
    setGroups(updatedGroups);
    
    await updateWatchlist(updatedGroups.map(g => ({
      id: g.id,
      name: g.name,
      symbols: g.stocks.map(s => s.symbol),
      collapsed: g.collapsed
    })));
  };

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    await createGroup(newGroupName);
    setNewGroupName('');
    setShowNewGroupInput(false);
    loadData();
  };

  const handleRefresh = () => {
    loadData();
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);

    if (!over || active.id === over.id) return;

    // Check if dragging a group
    const isGroup = groups.some(g => g.id === active.id);
    
    if (isGroup) {
      // Reorder groups
      const oldIndex = groups.findIndex(g => g.id === active.id);
      const newIndex = groups.findIndex(g => g.id === over.id);
      
      if (oldIndex !== -1 && newIndex !== -1) {
        const newGroups = arrayMove(groups, oldIndex, newIndex);
        setGroups(newGroups);
        
        await updateWatchlist(newGroups.map(g => ({
          id: g.id,
          name: g.name,
          symbols: g.stocks.map(s => ({ symbol: s.symbol, alias: s.alias })),
          collapsed: g.collapsed
        })));
      }
    } else {
      // Reorder stocks within/between groups
      let sourceGroupIdx = -1;
      let sourceStockIdx = -1;
      let targetGroupIdx = -1;
      let targetStockIdx = -1;

      // Find source
      groups.forEach((g, gi) => {
        const si = g.stocks.findIndex(s => s.symbol === active.id);
        if (si !== -1) {
          sourceGroupIdx = gi;
          sourceStockIdx = si;
        }
      });

      // Find target
      groups.forEach((g, gi) => {
        const si = g.stocks.findIndex(s => s.symbol === over.id);
        if (si !== -1) {
          targetGroupIdx = gi;
          targetStockIdx = si;
        }
      });

      if (sourceGroupIdx === -1) return;

      const newGroups = [...groups];
      const [movedStock] = newGroups[sourceGroupIdx].stocks.splice(sourceStockIdx, 1);

      if (targetGroupIdx !== -1) {
        // Move to specific position
        newGroups[targetGroupIdx].stocks.splice(targetStockIdx, 0, movedStock);
      } else {
        // Check if dropping on a group
        const targetGroup = newGroups.find(g => g.id === over.id);
        if (targetGroup) {
          targetGroup.stocks.push(movedStock);
        }
      }

      setGroups(newGroups);
      
      await updateWatchlist(newGroups.map(g => ({
        id: g.id,
        name: g.name,
        symbols: g.stocks.map(s => ({ symbol: s.symbol, alias: s.alias })),
        collapsed: g.collapsed
      })));
    }
  };

  const filteredGroups = useMemo(() => {
    return groups.map(g => {
      let stocks = [...(g.stocks || [])];
      
      // 1. Text Search
      if (searchTerm) {
        const term = searchTerm.toLowerCase();
        stocks = stocks.filter(s => 
          s.symbol.toLowerCase().includes(term) || 
          s.name.toLowerCase().includes(term)
        );
      }
      
      // 2. Status Filters
      if (activeFilters.length > 0) {
        stocks = stocks.filter(s => 
          s.weeklyMacdStatus && activeFilters.includes(s.weeklyMacdStatus)
        );
      }
      
      // 3. Sorting
      if (sortConfig.direction && sortConfig.key) {
        stocks.sort((a, b) => {
          if (!a || !b) return 0;
          
          let valA: any = null;
          let valB: any = null;

          if (sortConfig.key === 'weeklyStatus') {
            valA = a.weeklyMacdStatus || '';
            valB = b.weeklyMacdStatus || '';
          } else {
            valA = (a as any)[sortConfig.key];
            valB = (b as any)[sortConfig.key];
          }

          if (valA === undefined || valA === null) return 1;
          if (valB === undefined || valB === null) return -1;

          if (typeof valA === 'string' && typeof valB === 'string') {
            const res = valA.localeCompare(valB);
            return sortConfig.direction === 'asc' ? res : -res;
          }

          if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
          if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
          return 0;
        });
      }

      return { ...g, stocks };
    });
  }, [groups, searchTerm, activeFilters, sortConfig]);

  const toggleSort = (key: any) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key 
        ? (prev.direction === 'asc' ? 'desc' : prev.direction === 'desc' ? null : 'asc')
        : 'asc'
    }));
  };

  const toggleFilter = (filter: string) => {
    setActiveFilters(prev => 
      prev.includes(filter) ? prev.filter(f => f !== filter) : [...prev, filter]
    );
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-emerald-500/30">
      {/* Header */}
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
              onClick={handleRefresh}
              className={clsx(
                "p-1.5 sm:p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors",
                loading && "animate-spin"
              )}
              title="Refresh Data"
            >
              <RefreshCw size={18} sm:size={20} />
            </button>
          </div>
        </div>
      </header>

      {/* New Group Modal */}
      {showNewGroupInput && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 w-80">
            <h3 className="text-lg font-bold mb-4">创建新分组</h3>
            <input 
              type="text" 
              placeholder="分组名称..." 
              value={newGroupName}
              onChange={e => setNewGroupName(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:border-emerald-500/50"
              autoFocus
            />
            <div className="flex gap-2 justify-end">
              <button 
                onClick={() => setShowNewGroupInput(false)}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white"
              >
                取消
              </button>
              <button 
                onClick={handleCreateGroup}
                className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg"
              >
                创建
              </button>
            </div>
          </div>
        </div>
      )}
      
      {/* Alias Edit Modal */}
      {aliasModalOpen && editingAliasStock && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-6 w-80">
            <h3 className="text-lg font-bold mb-4">Edit Alias ({editingAliasStock.symbol})</h3>
            <input 
              type="text" 
              placeholder="Enter alias..." 
              value={aliasInput}
              onChange={e => setAliasInput(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:border-emerald-500/50"
              autoFocus
              onKeyDown={e => e.key === 'Enter' && handleEditAlias()}
            />
            <div className="flex gap-2 justify-end">
              <button 
                onClick={() => setAliasModalOpen(false)}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white"
              >
                Cancel
              </button>
              <button 
                onClick={handleEditAlias}
                className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-8">
        
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

        {/* Column Headers */}
        <div className="hidden sm:grid grid-cols-12 gap-4 px-4 pb-2 text-xs font-semibold text-zinc-500 uppercase tracking-wider select-none">
          <div className="col-span-4 sm:col-span-2 pl-4 cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('symbol')}>
            Symbol {sortConfig.key === 'symbol' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
          </div>
          <div className="col-span-3 sm:col-span-2 text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('price')}>
            Price {sortConfig.key === 'price' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
          </div>
          <div className="col-span-3 sm:col-span-2 text-right cursor-pointer hover:text-zinc-300" onClick={() => toggleSort('trend')}>
            Trend {sortConfig.key === 'trend' && (sortConfig.direction === 'asc' ? '↑' : '↓')}
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

        {/* Groups with Drag and Drop */}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={filteredGroups.map(g => g.id)} strategy={verticalListSortingStrategy}>
            {filteredGroups.map(group => (
              <SortableGroup
                key={group.id}
                group={group}
                onToggleCollapse={handleToggleCollapse}
                onStockClick={setSelectedStock}
                onRemoveStock={handleRemoveStock}
                onEditAlias={openAliasModal}
              />
            ))}
          </SortableContext>
        </DndContext>

        {filteredGroups.length === 0 && (
          <div className="p-8 text-center text-zinc-500">
            No groups found
          </div>
        )}
      </main>

      {/* Modal */}
      {selectedStock && (
        <ChartModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  );
}

export default App;
