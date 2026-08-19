import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  RefreshCw,
} from 'lucide-react';
import { clsx } from 'clsx';
import type { PortfolioNavSeries, PortfolioSnapshot, PortfolioStrategyItem } from '../types';
import {
  fetchPortfolioNav,
  fetchPortfolioSnapshot,
  fetchPortfolioStrategies,
  refreshPortfolioStrategy,
} from '../utils';
import { buildAssetRows, fmtDate, fmtNum, fmtPct, stateTone } from '../portfolioStrategies.js';

const PRIMARY_ORDER = [
  'risk_parity_core_next_open',
  'core90_ma200_bull10',
  'theme_alpha',
  'btc_supertrend_satellite',
];

const EMPTY_OPERATIONS: PortfolioSnapshot['operations'] = {
  orders: [],
  bullCandidates: [],
  dueOrderCount: 0,
  waitingOpenCount: 0,
  pendingOrderCount: 0,
  ma200AllowedCount: 0,
  ma200BlockedCount: 0,
  dataQualityEventCount: 0,
  benchmark: { strategyId: 'risk_parity_core_next_open' },
};

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={clsx('rounded-2xl border border-zinc-800 bg-zinc-950/60', className)}>{children}</section>;
}

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{children}</div>;
}

function StateBadge({ state }: { state: string }) {
  const status = stateTone(state);
  return (
    <span className={clsx(
      'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold',
      status.tone === 'positive' && 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
      status.tone === 'warning' && 'border-amber-500/30 bg-amber-500/10 text-amber-300',
      status.tone === 'danger' && 'border-red-500/30 bg-red-500/10 text-red-400',
      status.tone === 'info' && 'border-sky-500/30 bg-sky-500/10 text-sky-400',
      status.tone === 'neutral' && 'border-zinc-700 bg-zinc-800/60 text-zinc-400',
    )}>{status.label}</span>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' | 'warn' }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zinc-600">{label}</div>
      <div className={clsx(
        'mt-1 font-mono text-xl font-semibold tabular-nums text-zinc-100',
        tone === 'good' && 'text-emerald-400',
        tone === 'bad' && 'text-red-400',
        tone === 'warn' && 'text-amber-300',
      )}>{value}</div>
    </div>
  );
}

export default function PortfolioStrategiesPage() {
  const [strategies, setStrategies] = useState<PortfolioStrategyItem[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, PortfolioSnapshot>>({});
  const [selectedId, setSelectedId] = useState(PRIMARY_ORDER[0]);
  const [navSeries, setNavSeries] = useState<PortfolioNavSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAssets, setShowAssets] = useState(false);
  const [showNav, setShowNav] = useState(false);

  const loadPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchPortfolioStrategies();
      const orderedPrimary = list
        .filter(item => item.isPrimary || PRIMARY_ORDER.includes(item.strategyId))
        .sort((a, b) => PRIMARY_ORDER.indexOf(a.strategyId) - PRIMARY_ORDER.indexOf(b.strategyId));
      setStrategies(list);
      setSelectedId(current => orderedPrimary.some(item => item.strategyId === current)
        ? current
        : (orderedPrimary[0]?.strategyId || PRIMARY_ORDER[0]));
      const entries = await Promise.all(orderedPrimary.filter(item => item.paperEnabled).map(async item => {
        try {
          return [item.strategyId, await fetchPortfolioSnapshot(item.strategyId)] as const;
        } catch {
          return null;
        }
      }));
      setSnapshots(Object.fromEntries(entries.filter((entry): entry is readonly [string, PortfolioSnapshot] => entry !== null)));
    } catch {
      setError('组合数据加载失败，请检查后端服务。');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadPage(); }, [loadPage]);

  useEffect(() => {
    let active = true;
    fetchPortfolioNav(selectedId)
      .then(value => { if (active) setNavSeries(value); })
      .catch(() => { if (active) setNavSeries(null); });
    return () => { active = false; };
  }, [selectedId]);

  const primary = useMemo(() => strategies
    .filter(item => item.isPrimary || PRIMARY_ORDER.includes(item.strategyId))
    .sort((a, b) => PRIMARY_ORDER.indexOf(a.strategyId) - PRIMARY_ORDER.indexOf(b.strategyId)), [strategies]);
  const comparisons = strategies.filter(item => !item.isPrimary && !PRIMARY_ORDER.includes(item.strategyId));
  const snapshot = snapshots[selectedId] || null;
  const strategy = strategies.find(item => item.strategyId === selectedId);
  const operations = snapshot?.operations || EMPTY_OPERATIONS;
  const allOrders = primary.flatMap(item => (snapshots[item.strategyId]?.operations || EMPTY_OPERATIONS).orders
    .map(order => ({ ...order, strategyName: item.displayName })));
  const urgentOrders = allOrders.filter(
    order => order.due || ['PENDING', 'WAITING_OPEN', 'DELAYED'].includes(order.status),
  );
  const totalDue = primary.reduce((sum, item) => sum + (snapshots[item.strategyId]?.operations?.dueOrderCount || 0), 0);
  const totalWaiting = primary.reduce((sum, item) => sum + (snapshots[item.strategyId]?.operations?.waitingOpenCount || 0), 0);
  const totalAnomalies = primary.reduce((sum, item) => {
    const snap = snapshots[item.strategyId];
    return sum + (snap?.diagnostics.length || 0) + (snap?.operations?.dataQualityEventCount || 0);
  }, 0);
  const navPoints = navSeries?.points || [];
  const latestNav = navPoints.at(-1);
  const assetRows = snapshot ? buildAssetRows(snapshot) : [];

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const next = await refreshPortfolioStrategy(selectedId);
      if (!next) throw new Error('refresh failed');
      setSnapshots(current => ({ ...current, [selectedId]: next }));
      setNavSeries(await fetchPortfolioNav(selectedId));
    } catch {
      setError('刷新失败；未写入重复信号或订单。');
    } finally {
      setRefreshing(false);
    }
  }, [selectedId]);

  const aliasMap = Object.fromEntries((snapshot?.assets || []).map(asset => [asset.symbol, asset.alias]));
  const symbolLabel = (symbol: string) => aliasMap[symbol] ? `${symbol} · ${aliasMap[symbol]}` : symbol;

  if (loading) {
    return <main className="mx-auto max-w-7xl px-4 py-6"><div className="h-48 animate-pulse rounded-2xl border border-zinc-800 bg-zinc-900/40" /></main>;
  }

  return (
    <main className="mx-auto max-w-7xl px-3 py-5 sm:px-5 sm:py-7">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <Eyebrow>Daily paper execution</Eyebrow>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-100">组合策略执行台</h1>
          <p className="mt-1 text-xs text-zinc-500">冻结规则 · 样本外跟踪 · 无真实下单</p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing || !snapshot}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-3 text-xs font-semibold text-zinc-300 transition-colors hover:border-zinc-600 hover:text-white disabled:opacity-40"
        >
          <RefreshCw size={14} strokeWidth={1.5} className={clsx(refreshing && 'animate-spin')} />
          刷新当前策略
        </button>
      </header>

      {error && <div className="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-300">{error}</div>}

      <Card className="mb-4 overflow-hidden">
        <div className="border-b border-zinc-800 px-4 py-3 sm:px-5">
          <div className="flex items-center justify-between">
            <div>
              <Eyebrow>Execution first</Eyebrow>
              <h2 className="mt-1 text-sm font-semibold text-zinc-200">今日执行与等待队列</h2>
            </div>
            <div className="flex items-center gap-4 text-xs">
              <span className={clsx('font-mono', totalDue ? 'text-amber-300' : 'text-zinc-500')}>今日 {totalDue}</span>
              <span className={clsx('font-mono', totalWaiting ? 'text-sky-300' : 'text-zinc-500')}>等待 Open {totalWaiting}</span>
              <span className={clsx('hidden font-mono sm:inline', totalAnomalies ? 'text-red-400' : 'text-emerald-400')}>异常 {totalAnomalies}</span>
            </div>
          </div>
        </div>
        {urgentOrders.length ? (
          <div className="divide-y divide-zinc-800">
            {urgentOrders.map(order => (
              <div key={`${order.strategyName}-${order.orderId}`} className="grid gap-2 px-4 py-3 text-xs sm:grid-cols-[1.4fr_.8fr_.8fr_1fr] sm:items-center sm:px-5">
                <div><div className="font-medium text-zinc-200">{order.symbol} · {order.side}</div><div className="mt-0.5 text-[10px] text-zinc-600">{order.strategyName}</div></div>
                <div className="font-mono text-zinc-400">预期 {fmtDate(order.expectedExecutionDate)}</div>
                <div className="font-mono text-zinc-400">下次 {fmtDate(order.nextAttemptDate)}</div>
                <div className={clsx('sm:text-right', order.due ? 'text-amber-300' : 'text-sky-300')}>{order.delayReason || order.status}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 px-5 py-5 text-xs text-emerald-400"><CheckCircle2 size={14} strokeWidth={1.5} />当前没有需要执行或等待 Open 的订单</div>
        )}
      </Card>

      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {primary.map(item => {
          const snap = snapshots[item.strategyId];
          const ops = snap?.operations || EMPTY_OPERATIONS;
          const selected = item.strategyId === selectedId;
          return (
            <button
              key={item.strategyId}
              onClick={() => { setSelectedId(item.strategyId); setShowAssets(false); setShowNav(false); }}
              className={clsx(
                'min-h-28 rounded-2xl border p-4 text-left transition-colors',
                selected ? 'border-emerald-500/50 bg-emerald-500/[0.06]' : 'border-zinc-800 bg-zinc-950/60 hover:border-zinc-700',
              )}
            >
              <div className="flex items-start justify-between gap-2"><span className="text-xs font-semibold leading-5 text-zinc-200">{item.displayName}</span><StateBadge state={snap?.state || (item.bootstrapped ? 'READY' : 'EMPTY')} /></div>
              <div className="mt-4 flex gap-4 font-mono text-[10px] text-zinc-500"><span>订单 {ops.pendingOrderCount}</span><span>敞口 {fmtPct(ops.grossExposure, 0)}</span></div>
            </button>
          );
        })}
      </div>

      {snapshot ? (
        <div className="grid gap-4 lg:grid-cols-[1.55fr_.85fr]">
          <div className="space-y-4">
            <Card className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><Eyebrow>Selected portfolio</Eyebrow><h2 className="mt-1 text-xl font-semibold text-zinc-100">{strategy?.displayName}</h2><p className="mt-1 max-w-xl text-xs leading-5 text-zinc-500">{strategy?.description}</p></div>
                <div className="text-right"><div className="font-mono text-[10px] text-zinc-600">{snapshot.strategyVersion}</div><div className="mt-1"><StateBadge state={snapshot.state} /></div></div>
              </div>
              <div className="mt-6 grid grid-cols-2 gap-5 border-t border-zinc-800 pt-5 sm:grid-cols-4">
                <Metric label="NAV" value={fmtNum(snapshot.nav.netNav ?? latestNav?.netNav, 2)} />
                <Metric label="累计收益" value={fmtPct(snapshot.nav.cumulativeReturn ?? latestNav?.cumulativeReturn)} tone={(snapshot.nav.cumulativeReturn ?? 0) >= 0 ? 'good' : 'bad'} />
                <Metric label="回撤" value={fmtPct(snapshot.nav.drawdown ?? latestNav?.drawdown)} tone="bad" />
                <Metric label="相对 RiskParity" value={fmtPct(operations.benchmark.relativeReturn)} tone={(operations.benchmark.relativeReturn ?? 0) >= 0 ? 'good' : 'bad'} />
              </div>
            </Card>

            <Card>
              <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-3"><div><Eyebrow>Holdings</Eyebrow><h3 className="mt-1 text-sm font-semibold text-zinc-200">当前持仓与现金</h3></div><span className="font-mono text-xs text-zinc-400">总敞口 {fmtPct(operations.grossExposure)}</span></div>
              {snapshot.currentWeights.length ? (
                <div className="divide-y divide-zinc-800/70">
                  {snapshot.currentWeights.filter(position => position.weight > .0001 || position.symbol === 'CASH').sort((a, b) => b.weight - a.weight).map((position, index) => (
                    <div key={`${position.sleeve}-${position.symbol}-${index}`} className="grid grid-cols-[1fr_auto] items-center gap-4 px-5 py-3 text-xs">
                      <div><div className="font-mono text-zinc-200">{symbolLabel(position.symbol)}</div><div className="mt-0.5 text-[10px] uppercase tracking-wider text-zinc-600">{position.sleeve || 'portfolio'}</div></div>
                      <div className="text-right"><div className="font-mono font-semibold text-zinc-200">{fmtPct(position.weight)}</div><div className="mt-0.5 font-mono text-[10px] text-zinc-600">{fmtNum(position.value, 0)}</div></div>
                    </div>
                  ))}
                </div>
              ) : <div className="px-5 py-8 text-xs text-zinc-600">尚无纸面持仓</div>}
            </Card>

            <Card className="overflow-hidden">
              <button onClick={() => setShowAssets(value => !value)} className="flex w-full items-center justify-between px-5 py-4 text-left"><div><Eyebrow>Allocation audit</Eyebrow><div className="mt-1 text-sm font-semibold text-zinc-200">当前与目标权重 · {assetRows.length} 项</div></div>{showAssets ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</button>
              {showAssets && <div className="overflow-x-auto border-t border-zinc-800"><table className="w-full min-w-[620px] text-xs"><thead className="bg-zinc-900/70 text-[10px] uppercase tracking-wider text-zinc-600"><tr><th className="px-5 py-2 text-left">资产</th><th className="px-3 py-2 text-left">模块</th><th className="px-3 py-2 text-right">当前</th><th className="px-3 py-2 text-right">目标</th><th className="px-5 py-2 text-right">差异</th></tr></thead><tbody>{assetRows.map(row => <tr key={`${row.sleeve}-${row.symbol}`} className="border-t border-zinc-800/70"><td className="px-5 py-3 font-mono text-zinc-300">{symbolLabel(row.symbol)}</td><td className="px-3 py-3 text-zinc-500">{row.sleeve}</td><td className="px-3 py-3 text-right font-mono text-zinc-400">{fmtPct(row.currentWeight)}</td><td className="px-3 py-3 text-right font-mono text-zinc-300">{fmtPct(row.desiredWeight)}</td><td className={clsx('px-5 py-3 text-right font-mono', row.delta > 0 ? 'text-emerald-400' : row.delta < 0 ? 'text-red-400' : 'text-zinc-600')}>{row.delta > 0 ? '+' : ''}{fmtPct(row.delta)}</td></tr>)}</tbody></table></div>}
            </Card>

            {navPoints.length > 1 && <Card className="overflow-hidden"><button onClick={() => setShowNav(value => !value)} className="flex w-full items-center justify-between px-5 py-4 text-left"><div><Eyebrow>Ledger series</Eyebrow><div className="mt-1 text-sm font-semibold text-zinc-200">净值历史 · {navPoints.length} 条</div></div>{showNav ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</button>{showNav && <div className="max-h-72 overflow-auto border-t border-zinc-800"><table className="w-full text-xs"><thead className="sticky top-0 bg-zinc-950 text-zinc-600"><tr><th className="px-5 py-2 text-left">日期</th><th className="px-3 py-2 text-right">NAV</th><th className="px-3 py-2 text-right">日收益</th><th className="px-5 py-2 text-right">回撤</th></tr></thead><tbody>{navPoints.map(point => <tr key={point.valuationDate} className="border-t border-zinc-800/70"><td className="px-5 py-2 font-mono text-zinc-400">{point.valuationDate}</td><td className="px-3 py-2 text-right font-mono text-zinc-300">{fmtNum(point.netNav)}</td><td className={clsx('px-3 py-2 text-right font-mono', point.dailyReturn >= 0 ? 'text-emerald-400' : 'text-red-400')}>{fmtPct(point.dailyReturn)}</td><td className="px-5 py-2 text-right font-mono text-red-400">{fmtPct(point.drawdown)}</td></tr>)}</tbody></table></div>}</Card>}
          </div>

          <aside className="space-y-4">
            <Card className="p-5">
              <Eyebrow>Bull flip gate</Eyebrow>
              <h3 className="mt-1 text-sm font-semibold text-zinc-200">今日候选与 MA200</h3>
              <div className="mt-4 grid grid-cols-3 gap-3"><Metric label="候选" value={String(operations.bullCandidates.length)} /><Metric label="允许" value={String(operations.ma200AllowedCount)} tone="good" /><Metric label="拦截" value={String(operations.ma200BlockedCount)} tone={operations.ma200BlockedCount ? 'warn' : undefined} /></div>
              <div className="mt-4 space-y-2">
                {operations.bullCandidates.slice(0, 8).map(candidate => (
                  <div key={`${candidate.symbol}-${candidate.signalDate}`} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3 text-xs">
                    <div className="flex items-center justify-between"><span className="font-mono font-semibold text-zinc-200">{candidate.symbol}</span><span className={candidate.eligible ? 'text-emerald-400' : 'text-amber-300'}>{candidate.eligible ? 'MA200 允许' : 'MA200 拦截'}</span></div>
                    <div className="mt-1 text-[10px] leading-4 text-zinc-600">{candidate.gateReason || candidate.reason}</div>
                  </div>
                ))}
                {!operations.bullCandidates.length && <div className="py-3 text-xs text-zinc-600">今日没有 bull flip 候选</div>}
              </div>
            </Card>

            <Card className="p-5">
              <Eyebrow>Audit status</Eyebrow>
              <h3 className="mt-1 text-sm font-semibold text-zinc-200">日期与异常</h3>
              <dl className="mt-4 space-y-2 text-xs">
                {[['行情日期', snapshot.dates.marketDataDate], ['信号日期', snapshot.dates.signalDate], ['下次检查', snapshot.dates.nextCheck]].map(([label, value]) => <div key={label} className="flex justify-between gap-4"><dt className="text-zinc-600">{label}</dt><dd className="font-mono text-zinc-300">{fmtDate(value)}</dd></div>)}
                <div className="flex justify-between gap-4"><dt className="text-zinc-600">数据质量事件</dt><dd className={clsx('font-mono', operations.dataQualityEventCount ? 'text-red-400' : 'text-emerald-400')}>{operations.dataQualityEventCount}</dd></div>
              </dl>
              {snapshot.diagnostics.length ? <div className="mt-4 space-y-2">{snapshot.diagnostics.map((diagnostic, index) => <div key={`${diagnostic.code}-${index}`} className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-3 text-xs"><div className="font-mono text-red-400">{diagnostic.code}</div><div className="mt-1 leading-4 text-zinc-500">{diagnostic.message}</div></div>)}</div> : <div className="mt-4 flex items-center gap-2 text-xs text-emerald-400"><CheckCircle2 size={14} strokeWidth={1.5} />未发现策略诊断异常</div>}
            </Card>

            <Card className="p-5">
              <Eyebrow>Deterministic output</Eyebrow>
              <div className="mt-3 space-y-2 text-xs leading-5 text-zinc-500">
                <div className="flex gap-2"><Clock3 size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-sky-400" /><span>订单只按各标的下一有效 Open 执行；缺失 Open 会继续等待。</span></div>
                <div className="flex gap-2"><AlertTriangle size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-amber-300" /><span>页面解释冻结规则输出，不修改信号、参数或仓位。</span></div>
              </div>
            </Card>
          </aside>
        </div>
      ) : <Card className="p-10 text-center text-sm text-zinc-500">该策略尚无账户快照；不会自动 bootstrap。</Card>}

      {comparisons.length > 0 && (
        <section className="mt-7 border-t border-zinc-800 pt-5">
          <Eyebrow>Comparison only</Eyebrow>
          <h2 className="mt-1 text-sm font-semibold text-zinc-300">影子对照</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">{comparisons.map(item => <div key={item.strategyId} className="rounded-xl border border-zinc-800/70 bg-zinc-950/40 px-4 py-3"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium text-zinc-400">{item.displayName}</span><span className="text-[10px] uppercase tracking-wider text-zinc-600">comparison</span></div><p className="mt-1 text-[10px] leading-4 text-zinc-600">{item.description}</p></div>)}</div>
        </section>
      )}

      {selectedId.startsWith('btc') && <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/[0.05] px-4 py-3 text-[10px] leading-4 text-amber-300/80"><AlertTriangle size={13} strokeWidth={1.5} className="mt-0.5 shrink-0" />BTC-USD 是收益代理，不建模 CNY/USD 兑换；纸面仓位不代表可直接投资产品。</div>}
    </main>
  );
}
