import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { X, RefreshCw } from 'lucide-react';

const API_BASE = '/api';

interface EqPoint { date: string; equity: number; drawdownPct: number; }

interface BacktestResult {
  summary?: { tradeCount: number; winRate: number; averageReturnPct: number };
  markToMarketPortfolio?: { totalReturnPct: number; maxDrawdownPct: number; equityCurve: EqPoint[] };
  rsRotationPortfolio?: { totalReturnPct: number; maxDrawdownPct: number; equityCurve: EqPoint[] };
  benchmark?: { equalWeightReturnPct: number };
}

interface Strategy { id: string; label: string; }

interface Props { onClose: () => void; }

export function BacktestChart({ onClose }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyId, setStrategyId] = useState('resonance_v2_atr_2_0_csi300_entry_buffer_1_0_etf_established');
  const [start, setStart] = useState('2023-01-01');
  const [end, setEnd] = useState('');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/backtest/strategies`)
      .then(r => r.json())
      .then(setStrategies)
      .catch(() => {});
  }, []);

  async function runBacktest() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { strategy_version: strategyId };
      if (start) body.start = start;
      if (end) body.end = end;
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
    const mtm = result.markToMarketPortfolio?.equityCurve ?? [];
    const rs = result.rsRotationPortfolio?.equityCurve ?? [];
    if (!mtm.length && !rs.length) return;

    const chart = createChart(chartRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: chartRef.current.clientWidth,
      height: 360,
      timeScale: { borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });

    const toTime = (d: string) => d as Time;

    if (mtm.length) {
      const s = chart.addSeries(LineSeries, { color: '#38bdf8', lineWidth: 2, title: 'MTM策略' });
      s.setData(mtm.map(p => ({ time: toTime(p.date), value: p.equity })));
    }
    if (rs.length) {
      const s = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: 'RS轮动' });
      s.setData(rs.map(p => ({ time: toTime(p.date), value: p.equity })));
    }

    // baseline
    const allDates = [...mtm, ...rs].map(p => p.date).sort();
    if (allDates.length >= 2) {
      const s = chart.addSeries(LineSeries, { color: '#475569', lineWidth: 1, title: '基准1.0' });
      s.setData([
        { time: toTime(allDates[0]), value: 1 },
        { time: toTime(allDates[allDates.length - 1]), value: 1 },
      ]);
    }

    chart.timeScale().fitContent();

    const obs = new ResizeObserver(() => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    });
    obs.observe(chartRef.current);

    return () => { chart.remove(); obs.disconnect(); };
  }, [result]);

  const mtm = result?.markToMarketPortfolio;
  const rs = result?.rsRotationPortfolio;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-slate-900 rounded-xl w-full max-w-4xl flex flex-col gap-4 p-5 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <span className="text-white font-semibold text-lg">回测 · 资金曲线对比</span>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>

        <div className="flex flex-wrap gap-3 items-end">
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
          <div className="flex flex-col gap-1">
            <label className="text-xs text-slate-400">结束日期</label>
            <input type="date" value={end} onChange={e => setEnd(e.target.value)}
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

        {error && <div className="text-red-400 text-sm">{error}</div>}

        {result && (
          <div className="flex gap-6 text-sm">
            <Stat label="MTM策略收益" value={mtm ? `${mtm.totalReturnPct.toFixed(1)}%` : '-'} color="text-sky-400" />
            <Stat label="MTM最大回撤" value={mtm ? `${mtm.maxDrawdownPct.toFixed(1)}%` : '-'} color="text-red-400" />
            <Stat label="RS轮动收益" value={rs ? `${rs.totalReturnPct.toFixed(1)}%` : '-'} color="text-amber-400" />
            <Stat label="RS最大回撤" value={rs ? `${rs.maxDrawdownPct.toFixed(1)}%` : '-'} color="text-red-400" />
            <Stat label="交易次数" value={result.summary?.tradeCount ?? '-'} />
            <Stat label="胜率" value={result.summary ? `${(result.summary.winRate * 100).toFixed(0)}%` : '-'} />
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
