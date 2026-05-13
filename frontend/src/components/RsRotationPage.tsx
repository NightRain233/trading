import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { RefreshCw } from 'lucide-react';

const API_BASE = '/api';

interface PresetHoldings {
  label: string;
  holdings: string[];
  date: string | null;
}

interface EqPoint { date: string; equity: number; drawdownPct: number; }

interface BacktestResult {
  rsRotationPortfolio?: { totalReturnPct: number; maxDrawdownPct: number; equityCurve: EqPoint[] };
}

interface Strategy { id: string; label: string; }

export function RsRotationPage() {
  const [holdings, setHoldings] = useState<Record<string, PresetHoldings> | null>(null);
  const [loadingHoldings, setLoadingHoldings] = useState(true);

  const chartRef = useRef<HTMLDivElement>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyId, setStrategyId] = useState('rs_rotation_a_share');
  const [start, setStart] = useState('2023-01-01');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/rs-rotation/holdings`)
      .then(r => r.json())
      .then(setHoldings)
      .finally(() => setLoadingHoldings(false));

    fetch(`${API_BASE}/backtest/strategies`)
      .then(r => r.json())
      .then(list => setStrategies(list.filter((s: Strategy) => s.id.startsWith('rs_rotation_'))))
      .catch(() => {});
  }, []);

  async function runBacktest() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        rs_preset: strategyId,
        rs_min_history_bars: 250,
        rs_min_avg_volume: 100000000,
        start,
      };
      const r = await fetch(`${API_BASE}/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!chartRef.current || !result) return;
    const rs = result.rsRotationPortfolio?.equityCurve ?? [];
    if (!rs.length) return;

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: chartRef.current.clientWidth,
      height: 360,
      timeScale: { borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });

    const toTime = (d: string) => d as Time;
    const s = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: 'RS轮动' });
    s.setData(rs.map(p => ({ time: toTime(p.date), value: p.equity })));

    const baseline = chart.addSeries(LineSeries, { color: '#475569', lineWidth: 1, title: '基准1.0' });
    baseline.setData([
      { time: toTime(rs[0].date), value: 1 },
      { time: toTime(rs[rs.length - 1].date), value: 1 },
    ]);

    chart.timeScale().fitContent();

    const obs = new ResizeObserver(() => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    });
    obs.observe(chartRef.current);

    return () => { chart.remove(); obs.disconnect(); };
  }, [result]);

  const rs = result?.rsRotationPortfolio;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 sm:py-8">
      <h1 className="text-2xl font-bold text-white mb-6">RS 轮动策略</h1>

      {/* 当前持仓 */}
      <div className="glass-card rounded-2xl p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">当前持仓</h2>
        {loadingHoldings && <div className="text-slate-400 text-sm">加载中…</div>}
        {holdings && (
          <div className="flex flex-col gap-4">
            {Object.entries(holdings).map(([id, preset]) => (
              <div key={id} className="flex flex-col gap-2">
                <div className="text-xs text-slate-400">{preset.label}{preset.date ? ` (${preset.date})` : ''}</div>
                {preset.holdings.length === 0 ? (
                  <div className="text-slate-500 text-sm">空仓</div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {preset.holdings.map(s => (
                      <span key={s} className="bg-slate-800 text-amber-400 text-sm font-mono px-3 py-1 rounded-lg border border-slate-700">
                        {s}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 回测 */}
      <div className="glass-card rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-white mb-4">历史回测</h2>

        <div className="flex flex-wrap gap-3 items-end mb-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400">策略版本</label>
            <select
              value={strategyId}
              onChange={e => setStrategyId(e.target.value)}
              className="bg-slate-800 text-white text-sm rounded px-2 py-1 border border-slate-700"
            >
              {strategies.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400">开始日期</label>
            <input type="date" value={start} onChange={e => setStart(e.target.value)}
              className="bg-slate-800 text-white text-sm rounded px-2 py-1 border border-slate-700" />
          </div>
          <button
            onClick={runBacktest}
            disabled={loading}
            className="flex items-center gap-1 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm rounded px-3 py-1.5"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {loading ? '运行中…' : '运行回测'}
          </button>
        </div>

        {error && <div className="text-red-400 text-sm mb-4">{error}</div>}

        {result && (
          <div className="flex gap-6 text-sm mb-4">
            <Stat label="总收益" value={rs ? `${rs.totalReturnPct.toFixed(1)}%` : '-'} color="text-amber-400" />
            <Stat label="最大回撤" value={rs ? `${rs.maxDrawdownPct.toFixed(1)}%` : '-'} color="text-red-400" />
          </div>
        )}

        <div ref={chartRef} className="w-full rounded-lg overflow-hidden bg-slate-950" style={{ minHeight: 360 }} />
      </div>
    </div>
  );
}

function Stat({ label, value, color = 'text-white' }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`font-semibold ${color}`}>{value}</span>
    </div>
  );
}
