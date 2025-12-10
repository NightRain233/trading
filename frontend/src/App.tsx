import { useState, useMemo, useEffect } from 'react';
import { fetchWatchlist, addTicker, removeTicker } from './utils';
import type { StockData } from './types';
import { ChartModal } from './components/ChartModal';
import { StatusBadge } from './components/StatusBadge';
import { RefreshCw, TrendingUp, Search, Plus, Trash2 } from 'lucide-react'; // Added icons
import { clsx } from 'clsx';

function App() {
  const [stocks, setStocks] = useState<StockData[]>([]);
  const [selectedStock, setSelectedStock] = useState<StockData | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [newTicker, setNewTicker] = useState(''); // State for input
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    const data = await fetchWatchlist();
    setStocks(data);
    setLoading(false);
  };

  const handleAddStock = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTicker.trim()) return;
    
    // Optimistic UI or wait? Let's wait for simplicity
    const success = await addTicker(newTicker);
    if (success) {
      setNewTicker('');
      loadData(); // Reload to get fresh data
    } else {
      alert('Failed to add ticker. Check symbol or connection.');
    }
  };

  const handleRemoveStock = async (e: React.MouseEvent, symbol: string) => {
    e.stopPropagation(); // Prevent modal opening
    if (confirm(`Remove ${symbol}?`)) {
       await removeTicker(symbol);
       loadData();
    }
  };

  const filteredStocks = useMemo(() => {
    return stocks.filter(s => 
      s.symbol.toLowerCase().includes(searchTerm.toLowerCase()) || 
      s.name.toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [stocks, searchTerm]);

  const handleRefresh = () => {
    loadData();
  };

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
             {/* Add Stock Form */}
            <form onSubmit={handleAddStock} className="flex items-center gap-2">
                <input 
                  type="text" 
                  placeholder="Add Symbol (e.g. BTC-USD)" 
                  value={newTicker}
                  onChange={e => setNewTicker(e.target.value)}
                  className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-sm w-32 sm:w-48 focus:outline-none focus:border-emerald-500/50 uppercase"
                />
                <button type="submit" className="p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors">
                    <Plus size={16} />
                </button>
            </form>

            <div className="w-px h-6 bg-zinc-800 mx-2 hidden sm:block"></div>

            <div className="relative hidden sm:block">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
              <input 
                type="text" 
                placeholder="Search symbol..." 
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)} // Fixed variable usage
                className="bg-zinc-900 border border-zinc-700 rounded-full pl-10 pr-4 py-1.5 text-sm focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/50 transition-all w-64"
              />
            </div>
            <button 
              onClick={handleRefresh}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-colors"
              title="Refresh Data"
            >
              <RefreshCw size={20} />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-4 py-8">
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden shadow-sm backdrop-blur-sm">
          <div className="grid grid-cols-12 gap-4 p-4 border-b border-zinc-800 text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            <div className="col-span-4 sm:col-span-3">Symbol / Name</div>
            <div className="col-span-3 sm:col-span-2 text-right">Price</div>
            <div className="col-span-3 sm:col-span-2 text-right">Trend</div>
            <div className="col-span-2 hidden sm:block text-right">Signal</div>
            <div className="col-span-2 hidden sm:block text-right">ADX</div>
          </div>

          <div className="divide-y divide-zinc-800/50">
            {filteredStocks.map((stock) => (
              <div 
                key={stock.symbol}
                onClick={() => setSelectedStock(stock)}
                className="grid grid-cols-12 gap-4 p-4 items-center hover:bg-zinc-800/50 transition-colors cursor-pointer group relative"
              >
                <div className="col-span-4 sm:col-span-3">
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
                    <span className={clsx("font-mono text-sm", stock.adx > 25 ? "text-zinc-200" : "text-zinc-600")}>
                        {stock.adx.toFixed(2)}
                    </span>
                 </div>

                 {/* Delete Action (visible on hover) */}
                 <div className="absolute right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center h-full top-0">
                    <button 
                        onClick={(e) => handleRemoveStock(e, stock.symbol)}
                        className="p-2 bg-zinc-800 hover:bg-rose-500/20 hover:text-rose-400 text-zinc-500 rounded-lg shadow-lg border border-zinc-700"
                        title="Remove from Watchlist"
                    >
                        <Trash2 size={16} />
                    </button>
                 </div>
              </div>
            ))}
            
            {filteredStocks.length === 0 && (
                <div className="p-8 text-center text-zinc-500">
                    No stocks found matching "{searchTerm}"
                </div>
            )}
          </div>
        </div>
      </main>

      {/* Modal */}
      {selectedStock && (
        <ChartModal stock={selectedStock} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  );
}

export default App;
