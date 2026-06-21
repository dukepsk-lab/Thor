import { ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { EquityForecast } from '../lib/types';
import './EquityForecastChart.css';

interface MergedPoint {
  t: number;
  history?: number;
  best?: number;
  normal?: number;
  worst?: number;
}

function mergeSeries(data: EquityForecast): MergedPoint[] {
  const map = new Map<number, MergedPoint>();
  const set = (t: number, key: keyof MergedPoint, v: number) => {
    map.set(t, { ...(map.get(t) ?? { t }), [key]: v });
  };
  for (const p of data.history) set(p.t, 'history', p.v);
  for (const p of data.forecast.best) set(p.t, 'best', p.v);
  for (const p of data.forecast.normal) set(p.t, 'normal', p.v);
  for (const p of data.forecast.worst) set(p.t, 'worst', p.v);
  return Array.from(map.values()).sort((a, b) => a.t - b.t);
}

function fmtDate(t: number) {
  return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function EquityForecastChart({ data }: { data: EquityForecast }) {
  const merged = mergeSeries(data);
  const nowT = data.history.length ? data.history[data.history.length - 1].t : 0;

  return (
    <div className="panel equity-forecast-panel">
      <div className="panel-head">
        <span className="panel-title">Equity History &amp; 30D Forecast</span>
        <span className="label">commission paid <span className="mono">${data.totalCommission.toFixed(2)}</span></span>
      </div>
      <div className="ef-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={merged} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} tickFormatter={fmtDate} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} />
            <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10, fill: 'var(--ink-faint)' }} width={58} />
            <Tooltip
              labelFormatter={(t) => new Date(t as number).toLocaleDateString()}
              formatter={(v) => `$${Number(v).toFixed(2)}`}
              contentStyle={{ background: 'var(--surf-raised)', border: '1px solid var(--line)', fontSize: 11 }}
            />
            <ReferenceLine x={nowT} stroke="var(--ink-dim)" strokeDasharray="2 2" />
            <Line type="monotone" dataKey="history" name="Equity" stroke="var(--ink)" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
            <Line type="monotone" dataKey="best" name="Best case" stroke="var(--pos)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />
            <Line type="monotone" dataKey="normal" name="Normal" stroke="var(--ink-dim)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />
            <Line type="monotone" dataKey="worst" name="Worst case" stroke="var(--neg)" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="ef-legend">
        <span><i className="ef-dot ef-dot-history" /> Equity</span>
        <span><i className="ef-dot ef-dot-best" /> Best case</span>
        <span><i className="ef-dot ef-dot-normal" /> Normal</span>
        <span><i className="ef-dot ef-dot-worst" /> Worst case</span>
      </div>
    </div>
  );
}
