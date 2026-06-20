import { AlertCircle } from 'lucide-react';
import type { SignalState } from '../lib/types';
import './SignalConsole.css';

const REGIME_DEF = [
  { key: 'TREND', label: 'Trend', hue: 'var(--regime-trend)' },
  { key: 'MEAN_REV', label: 'Mean-rev', hue: 'var(--regime-meanrev)' },
  { key: 'HIGH_VOL', label: 'High-vol', hue: 'var(--regime-highvol)' },
] as const;

const VOTE_X: Record<string, number> = { SHORT: 12, FLAT: 50, LONG: 88 };

function gaugeArcPoint(t: number, cx: number, cy: number, r: number) {
  const angle = (180 - 180 * t) * (Math.PI / 180);
  return { x: cx + r * Math.cos(angle), y: cy - r * Math.sin(angle) };
}

function timeAgo(ms: number) {
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

export default function SignalConsole({ signal }: { signal: SignalState }) {
  const cx = 60;
  const cy = 58;
  const r = 46;
  const circumference = Math.PI * r;
  const fillLen = Math.max(0, Math.min(1, signal.conviction)) * circumference;
  const gate = gaugeArcPoint(signal.convictionGate, cx, cy, r);
  const pass = signal.conviction >= signal.convictionGate;

  const consensusX = signal.ensemble.reduce((acc, v) => acc + VOTE_X[v.vote], 0) / signal.ensemble.length;
  const spread = Math.max(...signal.ensemble.map((v) => Math.abs(VOTE_X[v.vote] - consensusX)));
  const agreement = spread < 5 ? 'agree' : spread < 30 ? 'split' : 'disagree';

  return (
    <div className="signal-console">
      <div className="sc-head">
        <span className="sc-pair">{signal.pair}</span>
        <div className="sc-health">
          {signal.featureDrift && <AlertCircle size={12} className="warn" />}
          <span className="ink-dim mono sc-infer">{timeAgo(signal.lastInferenceMs)}</span>
        </div>
      </div>

      <div className="sc-regime-rail">
        {REGIME_DEF.map((r2) => (
          <div
            key={r2.key}
            className={`sc-regime-seg ${signal.regime === r2.key ? 'active' : ''}`}
            style={signal.regime === r2.key ? { background: r2.hue, color: 'var(--surf-void)' } : undefined}
          >
            {r2.label}
          </div>
        ))}
      </div>
      <div className="sc-persistence">
        <span className="label">held</span>
        <span className="mono">{signal.regimeBarsHeld} bars</span>
      </div>

      <div className="sc-gauge-row">
        <svg viewBox="0 0 120 64" className="sc-gauge">
          <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} className="sc-gauge-track" />
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            className="sc-gauge-fill"
            stroke={pass ? 'var(--pos)' : 'var(--warn)'}
            strokeDasharray={`${fillLen} ${circumference}`}
          />
          <circle cx={gate.x} cy={gate.y} r={3} className="sc-gate-tick" />
        </svg>
        <div className="sc-gauge-readout">
          <span className={`mono sc-conviction ${pass ? 'pos' : 'warn'}`}>{(signal.conviction * 100).toFixed(0)}</span>
          <span className="label">conviction · gate {(signal.convictionGate * 100).toFixed(0)}</span>
        </div>
      </div>

      <div className={`sc-ensemble sc-ensemble-${agreement}`}>
        <div className="sc-track">
          <span className="sc-track-label" style={{ left: '4%' }}>S</span>
          <span className="sc-track-label" style={{ left: '46%' }}>F</span>
          <span className="sc-track-label" style={{ left: '88%' }}>L</span>
          {signal.ensemble.map((v, i) => (
            <span
              key={v.model}
              className="sc-vote"
              style={{ left: `${VOTE_X[v.vote]}%`, top: `${4 + i * 9}px` }}
              title={`${v.model}: ${v.vote}`}
            >
              {v.model.slice(1)}
            </span>
          ))}
        </div>
        <span className="label sc-agree-label">{agreement === 'agree' ? 'models agree' : agreement === 'split' ? 'split vote' : 'models disagree'}</span>
      </div>

      <div className="sc-meta">
        <span className="label">Meta-label P</span>
        <span className="mono">{(signal.metaLabelProb * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}
