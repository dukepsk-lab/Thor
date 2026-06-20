import { useEffect, useState } from 'react';
import type { PriceTile } from '../lib/types';
import StatusBadge from './StatusBadge';
import './MarketStrip.css';

const SESSION_DEFS = [
  { name: 'Tokyo', startUTC: 0, endUTC: 9 },
  { name: 'London', startUTC: 7, endUTC: 16 },
  { name: 'New York', startUTC: 12, endUTC: 21 },
] as const;

function activeSessions(hourUTC: number) {
  return SESSION_DEFS.map((s) => ({ ...s, active: hourUTC >= s.startUTC && hourUTC < s.endUTC }));
}

function formatPrice(pair: string, v: number) {
  return pair === 'USDJPY' ? v.toFixed(3) : pair === 'XAUUSD' ? v.toFixed(2) : v.toFixed(5);
}

function BarCountdown({ barCloseAt, now }: { barCloseAt: number; now: number }) {
  const remaining = Math.max(0, barCloseAt - now);
  const h = Math.floor(remaining / 3_600_000);
  const m = Math.floor((remaining % 3_600_000) / 60_000);
  const s = Math.floor((remaining % 60_000) / 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    <div className="bar-countdown">
      <span className="label">H4 close</span>
      <span className="mono countdown-value">{pad(h)}:{pad(m)}:{pad(s)}</span>
    </div>
  );
}

export default function MarketStrip({
  prices,
  barCloseAt,
  now,
}: {
  prices: Record<string, PriceTile>;
  barCloseAt: number;
  now: number;
}) {
  const [hourUTC, setHourUTC] = useState(new Date().getUTCHours());
  useEffect(() => {
    const t = setInterval(() => setHourUTC(new Date().getUTCHours()), 30_000);
    return () => clearInterval(t);
  }, []);
  const sessions = activeSessions(hourUTC);

  return (
    <div className="market-strip">
      <div className="tiles">
        {Object.values(prices).map((t) => (
          <div className="tile" key={t.pair}>
            <div className="tile-head">
              <span className="tile-pair">{t.pair}</span>
              <span className={`mono tile-change ${t.changePct >= 0 ? 'pos' : 'neg'}`}>
                {t.changePct >= 0 ? '+' : ''}{t.changePct.toFixed(2)}%
              </span>
            </div>
            <div className="tile-prices">
              <div className="mono tile-bid">{formatPrice(t.pair, t.bid)}</div>
              <span className="tile-sep">/</span>
              <div className="mono tile-ask">{formatPrice(t.pair, t.ask)}</div>
            </div>
            <div className="tile-foot">
              <span className="mono spread-val">{t.spreadPips.toFixed(1)}p</span>
              <StatusBadge status={t.spreadStatus} text={t.spreadStatus === 'healthy' ? 'SPREAD OK' : 'SPREAD WIDE'} />
            </div>
          </div>
        ))}
      </div>

      <div className="session-bar">
        <span className="label">Sessions</span>
        <div className="session-pills">
          {sessions.map((s) => (
            <span key={s.name} className={`session-pill ${s.active ? 'active' : ''}`}>
              {s.name}
            </span>
          ))}
        </div>
      </div>

      <BarCountdown barCloseAt={barCloseAt} now={now} />
    </div>
  );
}
