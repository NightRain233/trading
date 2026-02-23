import { useState, useEffect, useMemo, useCallback, lazy, Suspense } from 'react';
import { fetchWatchlist, fetchBatchQuotes, fetchBatchCharts, addTicker, removeTicker, createGroup, updateWatchlist, updateAlias } from './utils';
import type { StockData, Candle, WatchlistGroup } from './types';
const ChartModal = lazy(() => import('./components/ChartModal').then(m => ({ default: m.ChartModal })));
import { SortableGroup } from './components/SortableGroup';
import { Header } from './components/Header';
import { FilterBar } from './components/FilterBar';
import { NewGroupModal, AliasEditModal } from './components/Modals';
import { ColumnHeaders } from './components/ColumnHeaders';

import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';

const SortableContextAny = SortableContext as any;

const getUniqueSymbols = (groupsData: WatchlistGroup[]) => {
  const symbols = new Set<string>();
  const aliasMap = new Map<string, string>();
  groupsData.forEach(g => {
    g.symbols.forEach(s => {
      symbols.add(s.symbol);
      if (s.alias) aliasMap.set(s.symbol, s.alias);
    });
  });
  return { symbols: Array.from(symbols), aliasMap };
};

const scheduleIdle = (cb: () => void) => {
  if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
    (window as any).requestIdleCallback(cb, { timeout: 1500 });
    return;
  }
  setTimeout(cb, 0);
};

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
  const [sortConfig, setSortConfig] = useState<{
    key: keyof StockData | 'weeklyStatus'; 
    direction: 'asc' | 'desc' | null 
  }>({ key: 'price', direction: null });
  const [activeFilters, setActiveFilters] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  const weeklyFilterOptions = ['周线牛市', '周线反弹', '周线回调', '周线熊市'];
  const trendFilterOptions = ['强势多头', '潜在转空', '强势空头', '潜在转多'];

  // 迷你图状态
  const [chartData, setChartData] = useState<Record<string, Candle[]>>({});
  const [emaMode, setEmaMode] = useState<'long' | 'short'>('long');
  const [showCharts, setShowCharts] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // 1. Fetch group structure (lightweight) → 立即渲染骨架
      const groupsData = await fetchWatchlist();

      const { symbols: uniqueSymbols, aliasMap } = getUniqueSymbols(groupsData);

      // 先用 watchlist 信息渲染股票名称占位行
      setGroups(groupsData.map(g => ({
        ...g,
        stocks: g.symbols.map(s => ({
          symbol: s.symbol,
          name: s.symbol,
          alias: s.alias,
          price: 0,
          changePercent: 0,
          candles: [],
          ema20: 0,
          ema50: 0,
          adx: 0,
          rsi: 0,
          rsiPeriod: 14,
          rsiStatus: '中性' as const,
          rsiOverbought: 70,
          rsiOversold: 30,
          trend: '震荡' as const,
          signal: '观望' as const,
          _loading: true,
        }))
      })));
      // 2. 异步拉取批量数据，回来后填充
      const stockMap = await fetchBatchQuotes(uniqueSymbols);

      for (const [symbol, alias] of aliasMap) {
        if (stockMap[symbol]) {
          stockMap[symbol].alias = alias;
        }
      }

      const populatedGroups = groupsData.map(g => ({
        ...g,
        stocks: g.symbols
          .map(symObj => stockMap[symObj.symbol])
          .filter((s): s is StockData => s !== undefined)
      }));

      setGroups(populatedGroups);
    } catch (error) {
      console.error("Failed to load watchlist:", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const allSymbols = useMemo(() => {
    const symbolSet = new Set<string>();
    groups.forEach(g => {
      (g.stocks || []).forEach(s => symbolSet.add(s.symbol));
    });
    return Array.from(symbolSet);
  }, [groups]);

  const loadCharts = useCallback(async (symbols: string[]) => {
    if (symbols.length === 0) return;
    const charts = await fetchBatchCharts(symbols);
    if (charts && Object.keys(charts).length > 0) {
      setChartData(prev => ({ ...prev, ...charts }));
    }
  }, []);

  useEffect(() => {
    if (!showCharts) return;
    const missingSymbols = allSymbols.filter(s => !chartData[s]);
    if (missingSymbols.length === 0) return;
    scheduleIdle(() => {
      loadCharts(missingSymbols);
    });
  }, [showCharts, allSymbols, chartData, loadCharts]);

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

  const openAliasModal = useCallback((stock: StockData) => {
    setEditingAliasStock(stock);
    setAliasInput(stock.alias || '');
    setAliasModalOpen(true);
  }, []);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

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

  const handleRemoveStock = useCallback(async (e: React.MouseEvent, symbol: string) => {
    e.stopPropagation();
    if (confirm(`Remove ${symbol}?`)) {
       await removeTicker(symbol);
       loadData();
    }
  }, [loadData]);

  const handleToggleCollapse = useCallback(async (groupId: string) => {
    let updatedGroups: WatchlistGroup[] = [];
    setGroups(prev => {
      updatedGroups = prev.map(g =>
        g.id === groupId ? { ...g, collapsed: !g.collapsed } : g
      );
      return updatedGroups;
    });

    // 需要等 setState 完成后再发请求，用 updatedGroups 闭包
    await updateWatchlist(updatedGroups.map(g => ({
      id: g.id,
      name: g.name,
      symbols: (g.stocks || []).map(s => ({ symbol: s.symbol, alias: s.alias })),
      collapsed: g.collapsed
    })));
  }, []);

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    await createGroup(newGroupName);
    setNewGroupName('');
    setShowNewGroupInput(false);
    loadData();
  };

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over || active.id === over.id) return;

    // Check if dragging a group
    const isGroup = groups.some(g => g.id === active.id);
    
    if (isGroup) {
      // Reorder groups
      const oldIndex = groups.findIndex(g => g.id === active.id);
      const newIndex = groups.findIndex(g => g.id === over.id);
      
      if (oldIndex !== -1 && newIndex !== -1) {
        const newGroups = [...groups];
        const movedGroups = Array.from(newGroups);
        const [removed] = movedGroups.splice(oldIndex, 1);
        movedGroups.splice(newIndex, 0, removed);
        setGroups(movedGroups);
        
        await updateWatchlist(movedGroups.map(g => ({
          id: g.id,
          name: g.name,
          symbols: (g.stocks || []).map(s => ({ symbol: s.symbol, alias: s.alias })),
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
        const si = (g.stocks || []).findIndex(s => s.symbol === active.id);
        if (si !== -1) {
          sourceGroupIdx = gi;
          sourceStockIdx = si;
        }
      });

      // Find target
      groups.forEach((g, gi) => {
        const si = (g.stocks || []).findIndex(s => s.symbol === over.id);
        if (si !== -1) {
          targetGroupIdx = gi;
          targetStockIdx = si;
        }
      });

      if (sourceGroupIdx === -1) return;

      const newGroups = [...groups];
      const sourceStocks = [...(newGroups[sourceGroupIdx].stocks || [])];
      const [movedStock] = sourceStocks.splice(sourceStockIdx, 1);
      newGroups[sourceGroupIdx].stocks = sourceStocks;

      if (targetGroupIdx !== -1) {
        // Move to specific position
        const targetStocks = [...(newGroups[targetGroupIdx].stocks || [])];
        targetStocks.splice(targetStockIdx, 0, movedStock);
        newGroups[targetGroupIdx].stocks = targetStocks;
      } else {
        // Check if dropping on a group
        const targetGroup = newGroups.find(g => g.id === over.id);
        if (targetGroup) {
          const targetStocks = [...(targetGroup.stocks || [])];
          targetStocks.push(movedStock);
          targetGroup.stocks = targetStocks;
        }
      }

      setGroups(newGroups);
      
      await updateWatchlist(newGroups.map(g => ({
        id: g.id,
        name: g.name,
        symbols: (g.stocks || []).map(s => ({ symbol: s.symbol, alias: s.alias })),
        collapsed: g.collapsed
      })));
    }
  }, [groups]);

  const filteredGroups = useMemo(() => {
    const needsFilter = searchTerm.length > 0 || activeFilters.length > 0 || !!sortConfig.direction;
    if (!needsFilter) return groups;
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
        const activeWeekly = activeFilters.filter(f => weeklyFilterOptions.includes(f));
        const activeTrend = activeFilters.filter(f => trendFilterOptions.includes(f));

        if (activeWeekly.length > 0) {
          stocks = stocks.filter(s => 
            s.weeklyMacdStatus && activeWeekly.includes(s.weeklyMacdStatus)
          );
        }

        if (activeTrend.length > 0) {
          stocks = stocks.filter(s => 
            s.trend && activeTrend.includes(s.trend)
          );
        }
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
          } else if (sortConfig.key === 'trend') {
            const trendOrder = [
              '强势多头',
              '回调多头',
              '震荡',
              '潜在转空',
              '反弹空头',
              '强势空头',
              '潜在转多',
            ];
            const idxA = trendOrder.indexOf(a.trend);
            const idxB = trendOrder.indexOf(b.trend);
            valA = idxA === -1 ? Number.POSITIVE_INFINITY : idxA;
            valB = idxB === -1 ? Number.POSITIVE_INFINITY : idxB;
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

  const toggleSort = useCallback((key: any) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key
        ? (prev.direction === 'asc' ? 'desc' : prev.direction === 'desc' ? null : 'asc')
        : 'asc'
    }));
  }, []);

  const toggleFilter = useCallback((filter: string) => {
    setActiveFilters(prev =>
      prev.includes(filter) ? prev.filter(f => f !== filter) : [...prev, filter]
    );
  }, []);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-emerald-500/30">
      <Header 
        newTicker={newTicker}
        setNewTicker={setNewTicker}
        handleAddStock={handleAddStock}
        setShowNewGroupInput={setShowNewGroupInput}
        searchTerm={searchTerm}
        setSearchTerm={setSearchTerm}
        showFilters={showFilters}
        setShowFilters={setShowFilters}
        activeFilters={activeFilters}
        emaMode={emaMode}
        setEmaMode={setEmaMode}
        showCharts={showCharts}
        setShowCharts={setShowCharts}
        loading={loading}
        handleRefresh={loadData}
      />

      {showNewGroupInput && (
        <NewGroupModal 
          newGroupName={newGroupName}
          setNewGroupName={setNewGroupName}
          handleCreateGroup={handleCreateGroup}
          setShowNewGroupInput={setShowNewGroupInput}
        />
      )}
      
      {aliasModalOpen && editingAliasStock && (
        <AliasEditModal 
          symbol={editingAliasStock.symbol}
          aliasInput={aliasInput}
          setAliasInput={setAliasInput}
          handleEditAlias={handleEditAlias}
          setAliasModalOpen={setAliasModalOpen}
        />
      )}

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-8">
        
        <FilterBar 
          showFilters={showFilters}
          activeFilters={activeFilters}
          toggleFilter={toggleFilter}
          setActiveFilters={setActiveFilters}
          sortConfig={sortConfig}
          toggleSort={toggleSort}
        />

        <ColumnHeaders sortConfig={sortConfig} toggleSort={toggleSort} />

        {/* Groups with Drag and Drop */}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContextAny items={filteredGroups.map(g => g.id)} strategy={verticalListSortingStrategy}>
            {filteredGroups.map(group => (
              <SortableGroup
                key={group.id}
                group={group}
                onToggleCollapse={handleToggleCollapse}
                onStockClick={setSelectedStock}
                onRemoveStock={handleRemoveStock}
                onEditAlias={openAliasModal}
                chartData={chartData}
                emaMode={emaMode}
                showCharts={showCharts}
              />
            ))}
          </SortableContextAny>
        </DndContext>

        {filteredGroups.length === 0 && (
          <div className="p-8 text-center text-zinc-500">
            No groups found
          </div>
        )}
      </main>

      {/* Detail Modal */}
      {selectedStock && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md">
            <div className="text-zinc-400 text-sm">Loading chart...</div>
          </div>
        }>
          <ChartModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
        </Suspense>
      )}
    </div>
  );
}

export default App;
