import { useState, useEffect, useMemo, useCallback, lazy, Suspense, useRef } from 'react';
import { fetchWatchlist, fetchBatchQuotesSnapshot, fetchBatchQuotesConditional, fetchBatchCharts, addTicker, removeTicker, createGroup, updateWatchlist, updateAlias } from './utils';
import type { StockData, Candle, Timeframe, WatchlistGroup } from './types';
const ChartModal = lazy(() => import('./components/ChartModal').then(m => ({ default: m.ChartModal })));
const BacktestChart = lazy(() => import('./components/BacktestChart').then(m => ({ default: m.BacktestChart })));
const RsRotationPage = lazy(() => import('./components/RsRotationPage').then(m => ({ default: m.RsRotationPage })));
const WeeklyBreakoutPage = lazy(() => import('./components/WeeklyBreakoutPage').then(m => ({ default: m.WeeklyBreakoutPage })));
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

const weeklyFilterOptions = ['周线牛市', '周线反弹', '周线回调', '周线熊市'];
const trendFilterOptions = ['强势多头', '潜在转空', '强势空头', '潜在转多'];
const resonanceFilterOptions = ['共振买点', '离场预警', '共振离场'];
const trendOrder = ['强势多头', '回调多头', '震荡', '潜在转空', '反弹空头', '强势空头', '潜在转多'];

const getUniqueSymbols = (groupsData: WatchlistGroup[]) => {
  const symbols = new Set<string>();
  groupsData.forEach(g => {
    g.symbols.forEach(s => {
      symbols.add(s.symbol);
    });
  });
  return { symbols: Array.from(symbols) };
};

const scheduleIdle = (cb: () => void) => {
  if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
    (window as any).requestIdleCallback(cb, { timeout: 1500 });
    return;
  }
  setTimeout(cb, 0);
};

const buildPlaceholderStock = (symbol: string, alias = ''): StockData => ({
  symbol,
  name: symbol,
  alias,
  price: 0,
  changePercent: 0,
  candles: [],
  ema20: 0,
  ema50: 0,
  adx: 0,
  rsi: 0,
  rsiPeriod: 14,
  rsiStatus: '中性',
  rsiOverbought: 70,
  rsiOversold: 30,
  trend: '震荡',
  signal: '观望',
  _loading: true,
});

const mergeGroupsWithStockMap = (
  groupsData: WatchlistGroup[],
  stockMap: Record<string, StockData>,
  fallbackStockMap?: Map<string, StockData>
) => {
  return groupsData.map(g => ({
    ...g,
    stocks: g.symbols.map(symObj => {
      const incoming = stockMap[symObj.symbol];
      if (incoming) {
        return {
          ...incoming,
          alias: symObj.alias || incoming.alias || '',
          _loading: false,
        };
      }

      const fallback = fallbackStockMap?.get(symObj.symbol);
      if (fallback) {
        return {
          ...fallback,
          alias: symObj.alias || fallback.alias || '',
          _loading: false,
        };
      }

      return buildPlaceholderStock(symObj.symbol, symObj.alias || '');
    }),
  }));
};

function App() {
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [selectedStock, setSelectedStock] = useState<StockData | null>(null);
  const [showBacktest, setShowBacktest] = useState(false);
  const [activeTab, setActiveTab] = useState<'watchlist' | 'rs' | 'wbb'>('watchlist');
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

  // 迷你图状态
  const [chartDataByTimeframe, setChartDataByTimeframe] = useState<Record<Timeframe, Record<string, Candle[]>>>({
    '1D': {},
    '1W': {},
  });
  const [chartTimeframe, setChartTimeframe] = useState<Timeframe>('1D');
  const [emaMode, setEmaMode] = useState<'long' | 'short' | 'boll'>('long');
  const [showCharts, setShowCharts] = useState(false);
  const [lastDataUpdatedAt, setLastDataUpdatedAt] = useState<string | null>(null);
  const [dataStale, setDataStale] = useState(false);
  const etagRef = useRef<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setDataStale(false);
    try {
      // 1. Fetch group structure (lightweight) → 立即渲染骨架
      const groupsData = await fetchWatchlist();

      const { symbols: uniqueSymbols } = getUniqueSymbols(groupsData);

      // 先用 watchlist 信息渲染股票名称占位行
      setGroups(mergeGroupsWithStockMap(groupsData, {}));

      if (uniqueSymbols.length === 0) {
        setLastDataUpdatedAt(null);
        setDataStale(false);
        return;
      }

      // 2. 异步拉取批量数据，回来后填充
      const snapshot = await fetchBatchQuotesSnapshot(uniqueSymbols);
      setLastDataUpdatedAt(snapshot.updatedAt);
      setDataStale(snapshot.stale);
      setGroups(mergeGroupsWithStockMap(groupsData, snapshot.data));
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
      g.symbols.forEach(s => symbolSet.add(s.symbol));
    });
    return Array.from(symbolSet).sort();
  }, [groups]);
  const symbolsKey = useMemo(() => allSymbols.join(','), [allSymbols]);
  const formattedUpdatedAt = useMemo(
    () => (lastDataUpdatedAt ? new Date(lastDataUpdatedAt).toLocaleString('zh-CN', { hour12: false }) : ''),
    [lastDataUpdatedAt]
  );

  const currentChartData = chartDataByTimeframe[chartTimeframe] || {};
  const currentChartDataRef = useRef(currentChartData);
  currentChartDataRef.current = currentChartData;

  const loadCharts = useCallback(async (symbols: string[], timeframe: Timeframe) => {
    if (symbols.length === 0) return;
    const charts = await fetchBatchCharts(symbols, timeframe);
    if (charts && Object.keys(charts).length > 0) {
      setChartDataByTimeframe(prev => ({
        ...prev,
        [timeframe]: {
          ...(prev[timeframe] || {}),
          ...charts,
        },
      }));
    }
  }, []);

  useEffect(() => {
    if (!showCharts) return;
    const missingSymbols = allSymbols.filter(s => !currentChartDataRef.current[s]);
    if (missingSymbols.length === 0) return;
    scheduleIdle(() => {
      loadCharts(missingSymbols, chartTimeframe);
    });
  }, [showCharts, allSymbols, chartTimeframe, loadCharts]);

  useEffect(() => {
    etagRef.current = null;
  }, [symbolsKey]);

  useEffect(() => {
    if (!symbolsKey) return;

    const symbols = symbolsKey.split(',');
    let disposed = false;
    let timerId: number | null = null;
    const QUICK_REPOLL_DELAY_MS = 1_500;

    const runPoll = async () => {
      const result = await fetchBatchQuotesConditional(symbols, etagRef.current || undefined);
      if (disposed) return;

      if (result.etag) {
        etagRef.current = result.etag;
      }
      if (result.updatedAt) {
        setLastDataUpdatedAt(result.updatedAt);
      }
      setDataStale(result.stale);

      if (result.status === 'updated' && Object.keys(result.data).length > 0) {
        setGroups(prevGroups => {
          const fallbackStockMap = new Map<string, StockData>();
          prevGroups.forEach(group => {
            (group.stocks || []).forEach(stock => fallbackStockMap.set(stock.symbol, stock));
          });
          return mergeGroupsWithStockMap(prevGroups, result.data, fallbackStockMap);
        });
      }

      return result.refreshTriggered ? QUICK_REPOLL_DELAY_MS : null;
    };

    const scheduleNextPoll = (overrideDelay?: number | null) => {
      if (disposed) return;
      const delay = overrideDelay ?? (document.visibilityState === 'visible' ? 30_000 : 300_000);
      timerId = window.setTimeout(async () => {
        const nextDelay = await runPoll();
        scheduleNextPoll(nextDelay);
      }, delay);
    };

    const handleVisibilityChange = () => {
      if (timerId !== null) {
        window.clearTimeout(timerId);
        timerId = null;
      }
      void runPoll().then(nextDelay => scheduleNextPoll(nextDelay));
    };

    void runPoll().then(nextDelay => scheduleNextPoll(nextDelay));
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      disposed = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [symbolsKey]);

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

  const handleManualRefresh = useCallback(() => {
    etagRef.current = null;
    loadData();
  }, [loadData]);

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
        const activeResonance = activeFilters.filter(f => resonanceFilterOptions.includes(f));

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

        if (activeResonance.length > 0) {
          stocks = stocks.filter(s =>
            (activeResonance.includes('共振买点') && !!s.resonanceBuySignal) ||
            (activeResonance.includes('离场预警') && s.resonanceExitLevel === 'warn') ||
            (activeResonance.includes('共振离场') && s.resonanceExitLevel === 'hard')
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
    <div className="min-h-screen bg-zinc-950 text-zinc-100 selection:bg-emerald-500/30">
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
        chartTimeframe={chartTimeframe}
        setChartTimeframe={setChartTimeframe}
        loading={loading}
        handleRefresh={handleManualRefresh}
        onShowBacktest={() => setShowBacktest(true)}
        activeTab={activeTab}
        onTabChange={setActiveTab}
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
      {activeTab === 'rs' ? (
        <Suspense fallback={<div className="text-zinc-500 text-sm p-8">加载中…</div>}>
          <RsRotationPage />
        </Suspense>
      ) : activeTab === 'wbb' ? (
        <Suspense fallback={<div className="text-zinc-500 text-sm p-8">加载中…</div>}>
          <WeeklyBreakoutPage />
        </Suspense>
      ) : (
      <main className="max-w-6xl mx-auto px-4 py-6 sm:py-8">
        {/* Data timestamp */}
        <div className="mb-4 flex items-center gap-2">
          <div className="data-chip rounded-lg px-3 py-1.5 inline-flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 animate-pulse" />
            <span className="text-[11px] text-zinc-500 font-medium">
              {formattedUpdatedAt ? `行情更新至: ${formattedUpdatedAt}` : '数据加载中...'}
            </span>
          </div>
          {dataStale && (
            <span className="text-[11px] text-amber-400/80 bg-amber-500/5 border border-amber-500/15 px-2 py-1 rounded-lg font-medium">
              ⚠ 数据可能延迟
            </span>
          )}
        </div>

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
                chartData={currentChartData}
                chartTimeframe={chartTimeframe}
                emaMode={emaMode}
                showCharts={showCharts}
              />
            ))}
          </SortableContextAny>
        </DndContext>

        {filteredGroups.length === 0 && (
          <div className="glass-card rounded-2xl p-12 text-center animate-fade-in-up">
            <div className="text-3xl mb-3">📊</div>
            <div className="text-zinc-500 font-medium">暂无分组数据</div>
            <div className="text-zinc-700 text-sm mt-1">点击右上角 + 添加标的开始使用</div>
          </div>
        )}
      </main>
      )}

      {/* Detail Modal */}
      {selectedStock && (
        <Suspense fallback={
          <div className="modal-overlay fixed inset-0 z-50 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
              <div className="text-zinc-500 text-sm font-medium">加载图表中...</div>
            </div>
          </div>
        }>
          <ChartModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
        </Suspense>
      )}
      {showBacktest && (
        <Suspense fallback={null}>
          <BacktestChart onClose={() => setShowBacktest(false)} />
        </Suspense>
      )}
    </div>
  );
}

export default App;
