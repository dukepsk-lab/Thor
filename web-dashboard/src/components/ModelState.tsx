import { PAIRS, type SignalState } from '../lib/types';
import SignalConsole from './SignalConsole';
import './ModelState.css';

export default function ModelState({ signals }: { signals: Record<string, SignalState> }) {
  return (
    <div className="panel model-panel">
      <div className="panel-head">
        <span className="panel-title">Model &amp; Signal State</span>
        <span className="label">updates on H4 close</span>
      </div>
      <div className="sc-grid">
        {PAIRS.map((p) =>
          signals[p] ? (
            <SignalConsole key={p} signal={signals[p]} />
          ) : (
            <div key={p} className="signal-console sc-empty">
              <span className="sc-pair">{p}</span>
              <span className="ink-dim label">awaiting inference…</span>
            </div>
          ),
        )}
      </div>
    </div>
  );
}
