import { useState, useEffect } from 'react';
import { fetchWatchlist, addTicker, removeTicker, createGroup, updateWatchlist } from './utils';
import type { StockData, WatchlistGroup } from './types';
import { ChartModal } from './components/ChartModal';
import { StatusBadge } from './components/StatusBadge';
import { RefreshCw, TrendingUp, Search, Plus, Trash2, FolderPlus, GripVertical, ChevronDown, ChevronRight } from 'lucide-react';
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
  onRemoveStock 
}: { 
  stock: StockData; 
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
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
      className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-zinc-800/50 transition-colors cursor-pointer group relative bg-zinc-900/30"
      onClick={() => onStockClick(stock)}
    >
      {/* Drag Handle */}
      <div 
        className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 cursor-grab"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="text-zinc-600" size={14} />
      </div>

      <div className="col-span-4 sm:col-span-2 pl-4">
        <div className="font-bold text-white group-hover:text-emerald-400 transition-colors">{stock.symbol}</div>
        <div className="text-xs text-zinc-500 truncate">{stock.name}</div>
      </div>
      
      <div className="col-span-3 sm:col-span-2 text-right">
        <div className="font-mono text-zinc-200">${stock.price.toFixed(2)}</div>
        <div className={clsx("text-xs font-mono", stock.changePercent >= 0 ? "text-emerald-400" : "text-rose-400")}>
          {stock.changePercent >= 0 ? '+' : ''}{stock.changePercent.toFixed(2)}%
        </div>
      </div>

      <div className="col-span-3 sm:col-span-2 text-right flex justify-end">
        <StatusBadge trend={stock.trend} adx={stock.adx} />
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
          {stock.rsiStatus && stock.rsiStatus !== '中性' && (
            <span className="ml-1 text-xs opacity-75">{stock.rsiStatus}</span>
          )}
        </span>
      </div>

      <div className="col-span-2 hidden sm:block text-right">
        <span className={clsx("font-mono text-sm", stock.adx > 25 ? "text-zinc-200" : "text-zinc-600")}>
          {stock.adx.toFixed(2)}
        </span>
      </div>

      {/* Delete Action */}
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
}: {
  group: WatchlistGroup;
  onToggleCollapse: (groupId: string) => void;
  onStockClick: (stock: StockData) => void;
  onRemoveStock: (e: React.MouseEvent, symbol: string) => void;
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
          <span className="text-xs text-zinc-500 ml-2">({group.stocks.length})</span>
        </div>
      </div>
      
      {/* Stocks List */}
      {!group.collapsed && (
        <div className="border border-t-0 border-zinc-700/50 rounded-b-lg overflow-hidden">
          {group.stocks.length === 0 ? (
            <div className="p-4 text-center text-zinc-600 text-sm">
              拖拽股票到此分组
            </div>
          ) : (
            <SortableContext items={group.stocks.map(s => s.symbol)} strategy={verticalListSortingStrategy}>
              <div className="divide-y divide-zinc-800/50">
                {group.stocks.map(stock => (
                  <SortableStockRow 
                    key={stock.symbol} 
                    stock={stock} 
                    onStockClick={onStockClick}
                    onRemoveStock={onRemoveStock}
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
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    const data = await fetchWatchlist();
    setGroups(data);
    setLoading(false);
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
          symbols: g.stocks.map(s => s.symbol),
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
        symbols: g.stocks.map(s => s.symbol),
        collapsed: g.collapsed
      })));
    }
  };

  const filteredGroups = groups.map(g => ({
    ...g,
    stocks: searchTerm 
      ? g.stocks.filter(s => 
          s.symbol.toLowerCase().includes(searchTerm.toLowerCase()) || 
          s.name.toLowerCase().includes(searchTerm.toLowerCase())
        )
      : g.stocks
  }));

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-emerald-500/30">
      {/* Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-emerald-500/10 p-2 rounded-lg border border-emerald-500/20">
              <TrendingUp className="text-emerald-400" size={24} />
            </div>
            <h1 className="text-xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent hidden sm:block">
              TrendMaster
            </h1>
          </div>
          
          <div className="flex items-center gap-4">
            <form onSubmit={handleAddStock} className="flex items-center gap-2">
              <input 
                type="text" 
                placeholder="Add Symbol" 
                value={newTicker}
                onChange={e => setNewTicker(e.target.value)}
                className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm w-28 sm:w-36 focus:outline-none focus:border-emerald-500/50 uppercase"
              />
              <button type="submit" className="p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors">
                <Plus size={16} />
              </button>
            </form>

            <button 
              onClick={() => setShowNewGroupInput(true)}
              className="p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors hidden sm:block"
              title="New Group"
            >
              <FolderPlus size={16} />
            </button>

            <div className="w-px h-6 bg-zinc-800 mx-2 hidden sm:block"></div>

            <div className="relative hidden sm:block">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
              <input 
                type="text" 
                placeholder="Search..." 
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="bg-zinc-900 border border-zinc-700 rounded-full pl-10 pr-4 py-1.5 text-sm focus:outline-none focus:border-emerald-500/50 w-40"
              />
            </div>
            <button 
              onClick={handleRefresh}
              className={clsx(
                "p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors",
                loading && "animate-spin"
              )}
              title="Refresh Data"
            >
              <RefreshCw size={20} />
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

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-8">
        {/* Column Headers */}
        <div className="grid grid-cols-12 gap-4 px-4 pb-2 text-xs font-semibold text-zinc-500 uppercase tracking-wider">
          <div className="col-span-4 sm:col-span-2 pl-4">Symbol</div>
          <div className="col-span-3 sm:col-span-2 text-right">Price</div>
          <div className="col-span-3 sm:col-span-2 text-right">Trend</div>
          <div className="col-span-2 hidden sm:block text-right">Signal</div>
          <div className="col-span-2 hidden sm:block text-right">RSI</div>
          <div className="col-span-2 hidden sm:block text-right">ADX</div>
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
