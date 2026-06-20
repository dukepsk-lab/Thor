import type { Position } from '../lib/types';
import './PositionsTable.css';

function fmtPrice(pair: string, v: number) {
  return pair === 'USDJPY' ? v.toFixed(3) : pair === 'XAUUSD' ? v.toFixed(2) : v.toFixed(5);
}

function timeHeld(openedAt: number) {
  const ms = Date.now() - openedAt;
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m}m`;
}

export default function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <div className="panel pos-panel">
      <div className="panel-head">
        <span className="panel-title">Open Positions</span>
        <span className="label">{positions.length} active</span>
      </div>
      <div className="pos-table-wrap">
        <table className="pos-table">
          <thead>
            <tr>
              <th>Pair</th>
              <th>Dir</th>
              <th>Entry</th>
              <th>Current</th>
              <th>Lots</th>
              <th>Unrealized</th>
              <th>SL / TP</th>
              <th>Held</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={8} className="pos-empty">No open positions</td>
              </tr>
            ) : (
              positions.map((p) => (
                <tr key={p.ticket} className={p.nearBoundary ? 'row-boundary' : ''}>
                  <td className="mono pos-pair">{p.pair}</td>
                  <td className={`mono ${p.direction === 'LONG' ? 'pos' : 'neg'}`}>{p.direction}</td>
                  <td className="mono">{fmtPrice(p.pair, p.entry)}</td>
                  <td className="mono">{fmtPrice(p.pair, p.current)}</td>
                  <td className="mono">{p.lots.toFixed(2)}</td>
                  <td className={`mono ${p.unrealizedPnl >= 0 ? 'pos' : 'neg'}`}>
                    {p.unrealizedPnl >= 0 ? '+' : ''}${p.unrealizedPnl.toFixed(2)}
                  </td>
                  <td className="mono pos-sltp">
                    {fmtPrice(p.pair, p.sl)} / {fmtPrice(p.pair, p.tp)}
                  </td>
                  <td className="mono ink-dim">{timeHeld(p.openedAt)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
