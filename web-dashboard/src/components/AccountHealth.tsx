import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import type { AccountHealth as AccountHealthT, Status } from '../lib/types';
import StatusBadge from './StatusBadge';
import './AccountHealth.css';

function fmt(n: number) {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pnlClass(n: number) {
  return n >= 0 ? 'pos' : 'neg';
}

function ddStatus(ddPct: number, maxPct: number): Status {
  const ratio = ddPct / maxPct;
  if (ratio >= 0.85) return 'critical';
  if (ratio >= 0.6) return 'caution';
  return 'healthy';
}

function marginStatus(level: number): Status {
  if (level < 150) return 'critical';
  if (level < 300) return 'caution';
  return 'healthy';
}

export default function AccountHealth({ account }: { account: AccountHealthT }) {
  const dd = ddStatus(account.drawdownPct, account.maxDrawdownPct);
  const margin = marginStatus(account.marginLevelPct);

  return (
    <div className="panel acct-panel">
      <div className="panel-head">
        <span className="panel-title">Account &amp; P&amp;L</span>
      </div>

      <div className="acct-equity">
        <div className="label">Equity (live)</div>
        <div className="mono equity-value">${fmt(account.equity)}</div>
        <div className="equity-spark">
          <ResponsiveContainer width="100%" height={42}>
            <LineChart data={account.equityCurve}>
              <YAxis domain={['auto', 'auto']} hide />
              <Line type="monotone" dataKey="v" stroke="var(--pos)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="acct-pnl-grid">
        <div className="pnl-cell">
          <div className="label">Realized</div>
          <div className={`mono pnl-val ${pnlClass(account.realizedPnl)}`}>{account.realizedPnl >= 0 ? '+' : ''}{fmt(account.realizedPnl)}</div>
        </div>
        <div className="pnl-cell">
          <div className="label">Unrealized</div>
          <div className={`mono pnl-val ${pnlClass(account.unrealizedPnl)}`}>{account.unrealizedPnl >= 0 ? '+' : ''}{fmt(account.unrealizedPnl)}</div>
        </div>
        <div className="pnl-cell">
          <div className="label">Daily</div>
          <div className={`mono pnl-val ${pnlClass(account.dailyPnl)}`}>{account.dailyPnl >= 0 ? '+' : ''}{fmt(account.dailyPnl)}</div>
        </div>
        <div className="pnl-cell">
          <div className="label">Weekly</div>
          <div className={`mono pnl-val ${pnlClass(account.weeklyPnl)}`}>{account.weeklyPnl >= 0 ? '+' : ''}{fmt(account.weeklyPnl)}</div>
        </div>
        <div className="pnl-cell">
          <div className="label">MTD</div>
          <div className={`mono pnl-val ${pnlClass(account.mtdPnl)}`}>{account.mtdPnl >= 0 ? '+' : ''}{fmt(account.mtdPnl)}</div>
        </div>
      </div>

      <div className="acct-row">
        <div className="label">Drawdown</div>
        <StatusBadge status={dd} />
      </div>
      <div className="dd-gauge">
        <div
          className="dd-gauge-fill"
          style={{
            width: `${Math.min(100, (account.drawdownPct / account.maxDrawdownPct) * 100)}%`,
            background: dd === 'critical' ? 'var(--alarm)' : dd === 'caution' ? 'var(--warn)' : 'var(--pos)',
          }}
        />
        <div className="dd-gauge-ceiling" />
      </div>
      <div className="dd-gauge-labels">
        <span className="mono">{account.drawdownPct.toFixed(1)}%</span>
        <span className="mono ink-dim">max {account.maxDrawdownPct.toFixed(0)}%</span>
      </div>

      <div className="acct-row" style={{ marginTop: 10 }}>
        <div className="label">Margin level</div>
        <StatusBadge status={margin} text={`${account.marginLevelPct.toFixed(0)}%`} />
      </div>
      <div className="acct-mini-grid">
        <div>
          <div className="label">Free margin</div>
          <div className="mono">${fmt(account.freeMargin)}</div>
        </div>
        <div>
          <div className="label">Leverage used</div>
          <div className="mono">{account.leverageUsed.toFixed(1)}x</div>
        </div>
      </div>
    </div>
  );
}
