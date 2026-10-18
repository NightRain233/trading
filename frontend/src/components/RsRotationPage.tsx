import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import type { Time } from 'lightweight-charts';
import { RefreshCw } from 'lucide-react';
import { useChartTheme } from '../chartTheme';

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

function EquityChart({ curve }: { curve: EqPoint[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useChartTheme();

  useEffect(() => {
    if (!ref.current || !curve.length) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: theme.text },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
      width: ref.current.clientWidth,
      height: ref.current.clientHeight,
      timeScale: { borderColor: theme.border },
      rightPriceScale: { borderColor: theme.border },
    });
    const toTime = (d: string) => d as Time;
    const equity = chart.addSeries(LineSeries, { color: theme.ink, lineWidth: 2, title: '净值', priceLineVisible: false });
    equity.setData(curve.map(p => ({ time: toTime(p.date), value: p.equity })));
    const baseline = chart.addSeries(LineSeries, { color: theme.muted, lineWidth: 1, lineStyle: 2, title: '起点 1.0', priceLineVisible: false, lastValueVisible: false });
    baseline.setData([
      { time: toTime(curve[0].date), value: 1 },
      { time: toTime(curve[curve.length - 1].date), value: 1 },
    ]);
    chart.timeScale().fitContent();
    const node = ref.current;
    const observer = new ResizeObserver(() => chart.applyOptions({ width: node.clientWidth, height: node.clientHeight }));
    observer.observe(node);
    return () => { observer.disconnect(); chart.remove(); };
  }, [curve, theme]);

  return <div ref={ref} className="ui-lwc" style={{ height: 360 }} />;
}

export function RsRotationPage() {
  const [holdings, setHoldings] = useState<Record<string, PresetHoldings> | null>(null);
  const [loadingHoldings, setLoadingHoldings] = useState(true);
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
      .catch(() => setHoldings(null))
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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '回测失败');
    } finally {
      setLoading(false);
    }
  }

  const rs = result?.rsRotationPortfolio;

  return (
    <main className="ui-page">
      <section className="ui-hero">
        <span className="ui-eyebrow">RS 轮动 · 历史研究工具</span>
        <h1 className="ui-verdict" style={{ fontSize: 'clamp(26px, 4vw, 36px)' }}>买最近最强的几只，定期换</h1>
        <p className="ui-verdict-sub">按过去一段时间的涨幅排名，持有排名靠前的几只，到期再换。这是研究对照用的，不在主策略里，也不进每日推送。</p>
      </section>

      <section className="ui-panel ui-stack" aria-labelledby="h-hold">
        <div className="ui-sec-head"><h2 className="ui-h2" id="h-hold">按规则现在会持有</h2></div>
        {loadingHoldings && <p className="ui-note">计算中…每天第一次打开要把全部 ETF 重算一遍，大约一分钟，之后当天都是秒开。</p>}
        {!loadingHoldings && !holdings && <p className="ui-muted" style={{ margin: 0 }}>持仓数据加载失败。</p>}
        {holdings && Object.entries(holdings).map(([id, preset]) => (
          <div key={id} className="ui-stack" style={{ gap: 8 }}>
            <div className="ui-muted" style={{ fontSize: 13 }}>{preset.label}{preset.date ? ` · ${preset.date}` : ''}</div>
            {preset.holdings.length === 0
              ? <span className="ui-chip s1" style={{ alignSelf: 'flex-start' }}>空仓</span>
              : <div className="ui-row" style={{ gap: 6 }}>{preset.holdings.map(s => <span key={s} className="ui-chip ok ui-num">{s}</span>)}</div>}
          </div>
        ))}
      </section>

      <section className="ui-panel ui-stack" aria-labelledby="h-bt">
        <div className="ui-sec-head"><h2 className="ui-h2" id="h-bt">历史回测</h2><p>净值从 1.0 开始</p></div>
        <form className="ui-form" onSubmit={event => { event.preventDefault(); void runBacktest(); }}>
          <label className="ui-field" style={{ gridColumn: 'span 2' }}>
            策略版本
            <select value={strategyId} onChange={e => setStrategyId(e.target.value)} className="ui-input">
              {strategies.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
          </label>
          <label className="ui-field">
            开始日期
            <input type="date" value={start} onChange={e => setStart(e.target.value)} className="ui-input" />
          </label>
          <button type="submit" disabled={loading} className="ui-btn primary">
            <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />
            {loading ? '运行中…' : '运行回测'}
          </button>
        </form>

        {error && <p className="ui-error">{error}</p>}

        {rs && (
          <section className="ui-stats" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
            <div className="ui-stat"><span>总收益</span><b className={`ui-num ${rs.totalReturnPct >= 0 ? 'ui-rise' : 'ui-fall'}`}>{rs.totalReturnPct >= 0 ? '+' : ''}{rs.totalReturnPct.toFixed(1)}%</b></div>
            <div className="ui-stat"><span>最大回撤</span><b className="ui-num ui-fall">-{Math.abs(rs.maxDrawdownPct).toFixed(1)}%</b></div>
          </section>
        )}

        {rs?.equityCurve?.length
          ? <EquityChart curve={rs.equityCurve} />
          : <div className="ui-lwc ui-note" style={{ height: 200, display: 'grid', placeItems: 'center' }}>{loading ? '回测运行中，可能需要几十秒…' : '选好版本后点"运行回测"。'}</div>}
      </section>
    </main>
  );
}
