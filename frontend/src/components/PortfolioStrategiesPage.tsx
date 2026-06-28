import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, AlertTriangle, CheckCircle2, Clock, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { clsx } from 'clsx';
import type {
  PortfolioSnapshot,
  PortfolioStrategyItem,
  PortfolioNavSeries,
} from '../types';
import {
  fetchPortfolioStrategies,
  fetchPortfolioSnapshot,
  refreshPortfolioStrategy,
  fetchPortfolioNav,
} from '../utils';
import { stateTone, buildAssetRows, fmtDate, fmtPct, fmtNum } from '../portfolioStrategies.js';

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={clsx('glass-card rounded-xl p-4 border border-zinc-800/50', className)}>
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function StatusBadge({ state }: { state: string }) {
  const { tone, label } = stateTone(state);
  const colors: Record<string, string> = {
    positive: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    neutral: 'bg-zinc-700/60 border-zinc-600 text-zinc-300',
    warning: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    danger: 'bg-red-500/10 border-red-500/30 text-red-400',
    info: 'bg-sky-500/10 border-sky-500/30 text-sky-400',
  };
  return (
    <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-semibold border', colors[tone] || colors.neutral)}>
      {tone === 'positive' && <CheckCircle2 size={10} />}
      {tone === 'warning' && <Clock size={10} />}
      {tone === 'danger' && <XCircle size={10} />}
      {tone === 'info' && <AlertTriangle size={10} />}
      {label}
    </span>
  );
}

export default function PortfolioStrategiesPage() {
  const [strategies, setStrategies] = useState<PortfolioStrategyItem[]>([]);
  const [selectedId, setSelectedId] = useState<string>('btc_supertrend_satellite');
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [navSeries, setNavSeries] = useState<PortfolioNavSeries | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAllAssets, setShowAllAssets] = useState(false);

  const loadStrategies = useCallback(async () => {
    setLoading(true);
    const list = await fetchPortfolioStrategies();
    setStrategies(list);
    setLoading(false);
  }, []);

  const loadSnapshot = useCallback(async (id: string) => {
    const snap = await fetchPortfolioSnapshot(id);
    setSnapshot(snap);
  }, []);

  const loadNav = useCallback(async (id: string) => {
    const nav = await fetchPortfolioNav(id);
    setNavSeries(nav);
  }, []);

  useEffect(() => {
    loadStrategies();
  }, [loadStrategies]);

  useEffect(() => {
    if (selectedId) {
      loadSnapshot(selectedId);
      loadNav(selectedId);
      setError(null);
    }
  }, [selectedId, loadSnapshot, loadNav]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    const snap = await refreshPortfolioStrategy(selectedId);
    if (snap) {
      setSnapshot(snap);
      const nav = await fetchPortfolioNav(selectedId);
      setNavSeries(nav);
    } else {
      setError('刷新失败');
    }
    setRefreshing(false);
  }, [selectedId]);

  const handleStrategyChange = useCallback((id: string) => {
    setSelectedId(id);
    setShowAllAssets(false);
  }, []);

  const paperStrategies = strategies.filter(s => s.paperEnabled);
  const assetRows = snapshot ? buildAssetRows(snapshot) : [];
  const navPoints = navSeries?.points || [];
  const latestNav = navPoints.length > 0 ? navPoints[navPoints.length - 1] : null;
  const initialNav = strategies.find(s => s.strategyId === selectedId)?.initialNav || 100000;

  const aliasMap: Record<string, string> = {};
  if (snapshot?.assets) {
    for (const a of snapshot.assets) {
      aliasMap[a.symbol] = a.alias;
    }
  }
  const symbolLabel = (sym: string) => aliasMap[sym] ? `${sym} (${aliasMap[sym]})` : sym;

  return (
    <main className="max-w-7xl mx-auto px-3 sm:px-4 py-4 sm:py-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-zinc-100">组合策略</h2>
          {snapshot && <StatusBadge state={snapshot.state} />}
        </div>
        <div className="flex items-center gap-2">
          {/* Strategy selector */}
          <select
            value={selectedId}
            onChange={e => handleStrategyChange(e.target.value)}
            className="input-glass rounded-xl px-3 py-2 text-xs font-medium focus:outline-none border border-zinc-700/60 bg-zinc-900 text-zinc-200"
          >
            {paperStrategies.map(s => (
              <option key={s.strategyId} value={s.strategyId}>
                {s.displayName} {s.bootstrapped ? '' : '(未初始化)'}
              </option>
            ))}
          </select>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="btn-glass px-3 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:text-emerald-400 border border-zinc-700/60 disabled:opacity-50 flex items-center gap-1.5"
          >
            <RefreshCw size={14} className={clsx(refreshing && 'animate-spin')} />
            刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          {error}
        </div>
      )}

      {loading && !snapshot && (
        <div className="text-zinc-500 text-sm p-12 text-center">加载中...</div>
      )}

      {snapshot && (
        <>
          {/* Nine-panel grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
            {/* Panel 1: Dates */}
            <Panel title="日期">
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-zinc-500">行情日期</span>
                  <span className="text-zinc-200 font-mono">{fmtDate(snapshot.dates.marketDataDate)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">信号日期</span>
                  <span className="text-zinc-200 font-mono">{fmtDate(snapshot.dates.signalDate)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">执行日期</span>
                  <span className="text-zinc-200 font-mono">{fmtDate(snapshot.dates.executionDate)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">下次检查</span>
                  <span className="text-zinc-200 font-mono">{fmtDate(snapshot.dates.nextCheck)}</span>
                </div>
              </div>
            </Panel>

            {/* Panel 2: Diagnostics */}
            <Panel title="数据诊断">
              {snapshot.diagnostics.length === 0 ? (
                <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <CheckCircle2 size={12} />
                  数据正常
                </div>
              ) : (
                <div className="space-y-1.5 max-h-40 overflow-y-auto">
                  {snapshot.diagnostics.map((d, i) => (
                    <div key={i} className={clsx(
                      'text-xs px-2 py-1.5 rounded-lg border',
                      d.code.startsWith('BLOCKED')
                        ? 'bg-red-500/5 border-red-500/20 text-red-400'
                        : 'bg-amber-500/5 border-amber-500/20 text-amber-400'
                    )}>
                      <div className="font-semibold">{d.code}</div>
                      <div className="text-zinc-500 mt-0.5">{d.message}</div>
                      {d.symbol && <div className="text-zinc-600 font-mono mt-0.5">{d.symbol}</div>}
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            {/* Panel 3: Signal */}
            <Panel title="信号状态">
              {snapshot.observation.reason ? (
                <div className="space-y-1.5 text-xs">
                  <div className="text-zinc-200">{snapshot.observation.reason}</div>
                  {snapshot.observation.values && Object.keys(snapshot.observation.values).length > 0 && (
                    <div className="mt-2 pt-2 border-t border-zinc-800">
                      {Object.entries(snapshot.observation.values).map(([key, val]) => (
                        <div key={key} className="flex justify-between text-[11px]">
                          <span className="text-zinc-500 font-mono">{key}</span>
                          <span className="text-zinc-300 font-mono">
                            {typeof val === 'boolean' ? (val ? 'ON' : 'OFF') : typeof val === 'number' ? fmtNum(val, 4) : String(val)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-xs text-amber-400">
                  <AlertTriangle size={12} />
                  {snapshot.calcError || '无信号'}
                </div>
              )}
            </Panel>

            {/* Panel 4: Current Holdings */}
            <Panel title="当前持仓">
              {snapshot.currentWeights.length === 0 ? (
                <div className="text-xs text-zinc-600">无持仓</div>
              ) : (
                <div className="space-y-1">
                  {snapshot.currentWeights
                    .filter(p => p.weight > 0.001 || p.symbol === 'CASH')
                    .sort((a, b) => b.weight - a.weight)
                    .map(p => (
                      <div key={p.symbol} className="flex items-center justify-between text-xs">
                        <span className="text-zinc-300 font-mono text-[11px]">{symbolLabel(p.symbol)}</span>
                        <div className="flex items-center gap-2">
                          {p.price != null && (
                            <span className="text-zinc-600 font-mono text-[10px]">{fmtNum(p.price)}</span>
                          )}
                          <span className="text-zinc-200 font-mono font-semibold">{fmtPct(p.weight, 1)}</span>
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </Panel>

            {/* Panel 5: Target Weights */}
            <Panel title="目标权重">
              {snapshot.desiredWeights.length === 0 ? (
                <div className="text-xs text-zinc-600">无目标</div>
              ) : (
                <div className="space-y-1">
                  {snapshot.desiredWeights.map(w => (
                    <div key={w.symbol} className="flex items-center justify-between text-xs">
                      <div>
                        <span className="text-zinc-300 font-mono text-[11px]">{symbolLabel(w.symbol)}</span>
                        <span className="text-zinc-600 ml-1.5 text-[10px]">{w.sleeve}</span>
                      </div>
                      <span className="text-zinc-200 font-mono font-semibold">{fmtPct(w.weight, 1)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            {/* Panel 6: Rebalance Diff */}
            <Panel title="调仓差异">
              {assetRows.length === 0 ? (
                <div className="text-xs text-zinc-600">无差异</div>
              ) : (
                <div className="space-y-1">
                  {assetRows
                    .filter(r => Math.abs(r.delta) > 0.0001)
                    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
                    .slice(0, 6)
                    .map(r => (
                      <div key={r.symbol} className="flex items-center justify-between text-xs">
                        <span className="text-zinc-300 font-mono text-[11px]">{symbolLabel(r.symbol)}</span>
                        <span className={clsx(
                          'font-mono font-semibold',
                          r.delta > 0 ? 'text-emerald-400' : r.delta < 0 ? 'text-red-400' : 'text-zinc-600'
                        )}>
                          {r.delta > 0 ? '+' : ''}{fmtPct(r.delta, 2)}
                        </span>
                      </div>
                    ))}
                </div>
              )}
            </Panel>

            {/* Panel 7: NAV */}
            <Panel title="净值 & 回撤">
              {latestNav ? (
                <div className="space-y-1.5 text-xs">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">净值</span>
                    <span className="text-zinc-200 font-mono font-semibold">{fmtNum(latestNav.netNav, 2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">现金</span>
                    <span className="text-zinc-200 font-mono">{fmtNum(latestNav.cash, 2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">累计收益</span>
                    <span className={clsx(
                      'font-mono font-semibold',
                      latestNav.cumulativeReturn >= 0 ? 'text-emerald-400' : 'text-red-400'
                    )}>
                      {fmtPct(latestNav.cumulativeReturn, 2)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">最大回撤</span>
                    <span className="text-red-400 font-mono font-semibold">{fmtPct(latestNav.drawdown, 2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">初始资金</span>
                    <span className="text-zinc-400 font-mono">{fmtNum(initialNav, 0)}</span>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-zinc-600">无净值数据</div>
              )}
            </Panel>

            {/* Panel 8: Ledger Summary */}
            <Panel title="最近账本">
              <div className="text-xs space-y-1">
                <div className="flex justify-between">
                  <span className="text-zinc-500">状态</span>
                  <span className="text-zinc-200">{snapshot.ledger.status}</span>
                </div>
                {snapshot.ledger.signalDate && (
                  <div className="flex justify-between">
                    <span className="text-zinc-500">信号日</span>
                    <span className="text-zinc-200 font-mono">{fmtDate(snapshot.ledger.signalDate)}</span>
                  </div>
                )}
              </div>
            </Panel>

            {/* Panel 9: Next Check */}
            <Panel title="下次检查 & 状态">
              <div className="space-y-2 text-xs">
                {snapshot.dates.nextCheck ? (
                  <div className="flex items-center gap-1.5 text-emerald-400">
                    <Clock size={12} />
                    <span className="font-mono">{fmtDate(snapshot.dates.nextCheck)}</span>
                  </div>
                ) : (
                  <div className="text-zinc-600">待定</div>
                )}
                {snapshot.ledger.status === 'pending' && (
                  <div className="flex items-center gap-1.5 text-amber-400">
                    <AlertTriangle size={12} />
                    待执行调仓
                  </div>
                )}
                {snapshot.state === 'BLOCKED' && (
                  <div className="flex items-center gap-1.5 text-red-400">
                    <XCircle size={12} />
                    数据阻塞，无法调仓
                  </div>
                )}
              </div>
            </Panel>
          </div>

          {/* Expanded asset table */}
          {assetRows.length > 0 && (
            <div className="glass-card rounded-xl border border-zinc-800/50 overflow-hidden">
              <button
                onClick={() => setShowAllAssets(!showAllAssets)}
                className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-zinc-400 hover:text-zinc-200 transition-colors"
              >
                <span>全部资产 ({assetRows.length})</span>
                {showAllAssets ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              {showAllAssets && (
                <div className="overflow-x-auto border-t border-zinc-800/50">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-zinc-900/50 text-zinc-500">
                        <th className="text-left px-4 py-2 font-medium">标的</th>
                        <th className="text-left px-4 py-2 font-medium">模块</th>
                        <th className="text-right px-4 py-2 font-medium">当前权重</th>
                        <th className="text-right px-4 py-2 font-medium">目标权重</th>
                        <th className="text-right px-4 py-2 font-medium">差异</th>
                        <th className="text-left px-4 py-2 font-medium hidden sm:table-cell">原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assetRows.map(r => (
                        <tr key={r.symbol} className="border-t border-zinc-800/30 hover:bg-zinc-800/20">
                          <td className="px-4 py-2 font-mono text-zinc-300">{symbolLabel(r.symbol)}</td>
                          <td className="px-4 py-2 text-zinc-500">{r.sleeve}</td>
                          <td className="px-4 py-2 text-right font-mono text-zinc-300">{fmtPct(r.currentWeight, 1)}</td>
                          <td className="px-4 py-2 text-right font-mono text-zinc-300">{fmtPct(r.desiredWeight, 1)}</td>
                          <td className={clsx(
                            'px-4 py-2 text-right font-mono font-semibold',
                            r.delta > 0.001 ? 'text-emerald-400' : r.delta < -0.001 ? 'text-red-400' : 'text-zinc-600'
                          )}>
                            {r.delta > 0 ? '+' : ''}{fmtPct(r.delta, 2)}
                          </td>
                          <td className="px-4 py-2 text-zinc-500 hidden sm:table-cell max-w-48 truncate">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* BTC proxy warning */}
          {selectedId.startsWith('btc') && (
            <div className="mt-3 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/15 text-amber-400/80 text-[10px] flex items-center gap-1.5">
              <AlertTriangle size={11} />
              BTC-USD 为合成收益代理，本阶段不建模 CNY/USD 兑换。纸面仓位不代表可直接投资的 CNY 产品。
            </div>
          )}

          {/* NAV History mini table */}
          {navPoints.length > 1 && (
            <div className="glass-card rounded-xl border border-zinc-800/50 mt-4 p-4">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 mb-3">净值历史 ({navPoints.length} 条)</h3>
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="w-full text-[10px]">
                  <thead className="sticky top-0 bg-zinc-950 text-zinc-500">
                    <tr>
                      <th className="text-left px-2 py-1 font-medium">日期</th>
                      <th className="text-right px-2 py-1 font-medium">净值</th>
                      <th className="text-right px-2 py-1 font-medium">日收益</th>
                      <th className="text-right px-2 py-1 font-medium">累计收益</th>
                      <th className="text-right px-2 py-1 font-medium">回撤</th>
                    </tr>
                  </thead>
                  <tbody>
                    {navPoints.map((p, i) => (
                      <tr key={i} className="border-t border-zinc-800/20 hover:bg-zinc-800/20">
                        <td className="px-2 py-1 font-mono text-zinc-400">{p.valuationDate}</td>
                        <td className="px-2 py-1 text-right font-mono text-zinc-300">{fmtNum(p.netNav, 2)}</td>
                        <td className={clsx('px-2 py-1 text-right font-mono', p.dailyReturn >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                          {fmtPct(p.dailyReturn, 2)}
                        </td>
                        <td className={clsx('px-2 py-1 text-right font-mono', p.cumulativeReturn >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                          {fmtPct(p.cumulativeReturn, 2)}
                        </td>
                        <td className="px-2 py-1 text-right font-mono text-red-400/80">{fmtPct(p.drawdown, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {!loading && !snapshot && !error && (
        <div className="glass-card rounded-2xl p-12 text-center">
          <div className="text-zinc-500 text-sm font-medium mb-1">暂无数据</div>
          <div className="text-zinc-700 text-xs">点击"刷新"加载最新组合策略数据</div>
        </div>
      )}
    </main>
  );
}
