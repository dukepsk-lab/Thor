import { PAIRS, type RiskState, type Status } from '../lib/types';
import StatusBadge from './StatusBadge';
import './RiskLayer.css';

function heatStatus(pct: number, ceiling: number): Status {
  const ratio = pct / ceiling;
  if (ratio >= 0.9) return 'critical';
  if (ratio >= 0.7) return 'caution';
  return 'healthy';
}

function corrCellClass(v: number, ceiling: number) {
  if (Math.abs(v) >= ceiling) return 'corr-breach';
  if (Math.abs(v) >= ceiling - 0.15) return 'corr-near';
  return '';
}

export default function RiskLayer({ risk }: { risk: RiskState }) {
  const heat = heatStatus(risk.portfolioHeatPct, risk.portfolioHeatCeilingPct);
  const breaker = risk.circuitBreaker;
  const breakerStatus: Status = breaker.status === 'TRIGGERED' ? 'critical' : 'healthy';

  return (
    <div className="panel risk-panel">
      <div className="panel-head">
        <span className="panel-title">Risk Layer</span>
      </div>

      <div className="risk-row">
        <div className="label">Portfolio heat</div>
        <StatusBadge status={heat} text={`${risk.portfolioHeatPct.toFixed(1)}% / ${risk.portfolioHeatCeilingPct}%`} />
      </div>
      <div className="heat-gauge">
        <div
          className="heat-gauge-fill"
          style={{
            width: `${Math.min(100, (risk.portfolioHeatPct / risk.portfolioHeatCeilingPct) * 100)}%`,
            background: heat === 'critical' ? 'var(--alarm)' : heat === 'caution' ? 'var(--warn)' : 'var(--pos)',
          }}
        />
      </div>

      <div className="risk-section-label">Correlation (ceiling ρ &lt; {risk.correlationCeiling})</div>
      <table className="corr-matrix">
        <thead>
          <tr>
            <th></th>
            {PAIRS.map((p) => <th key={p}>{p.slice(0, 3)}</th>)}
          </tr>
        </thead>
        <tbody>
          {PAIRS.map((a) => (
            <tr key={a}>
              <th>{a.slice(0, 3)}</th>
              {PAIRS.map((b) => {
                const v = risk.correlation[a]?.[b];
                return (
                  <td key={b} className={`mono ${a === b || v === undefined ? '' : corrCellClass(v, risk.correlationCeiling)}`}>
                    {a === b ? '—' : v === undefined ? '·' : v.toFixed(2)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="risk-section-label">ATR-sized risk vs current</div>
      <div className="atr-list">
        {risk.atrRisk.map((r) => (
          <div className="atr-row" key={r.pair}>
            <span className="atr-pair">{r.pair.slice(0, 3)}</span>
            <div className="atr-bars">
              <div className="atr-bar atr-bar-target" style={{ width: `${Math.min(100, r.atrSizedRiskPct * 40)}%` }} />
              <div className="atr-bar atr-bar-current" style={{ width: `${Math.min(100, r.currentRiskPct * 40)}%` }} />
            </div>
            <span className="mono atr-val">{r.currentRiskPct.toFixed(2)}%</span>
          </div>
        ))}
      </div>

      <div className={`breaker-card ${breaker.status === 'TRIGGERED' ? 'breaker-tripped' : ''}`}>
        <div className="breaker-head">
          <span className="label">Circuit breaker</span>
          <StatusBadge status={breakerStatus} text={breaker.status} />
        </div>
        <div className="breaker-loss">
          <span className="mono">{breaker.dailyLossPct.toFixed(1)}%</span>
          <span className="ink-dim mono"> / {breaker.dailyLossLimitPct}% daily limit</span>
        </div>
      </div>
    </div>
  );
}
