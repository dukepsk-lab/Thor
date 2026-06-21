import { useEffect, useState } from 'react';
import {
  PAIRS,
  type AccountHealth,
  type EnsembleVote,
  type EquityForecast,
  type Pair,
  type Position,
  type PriceTile,
  type Regime,
  type RiskState,
  type SignalState,
  type SystemHealth,
} from './types';

/*
  Demo-only data engine. Mirrors the two real refresh tiers the live system
  will use: price/account/position ticks stream continuously (WebSocket),
  while model/regime state only changes once per H4 bar close. Here the H4
  countdown is computed from the real clock (bars close at :00 every 4h
  UTC) but the model-state mutation is sped up to a short interval so the
  zone is visibly demonstrable without a 4-hour wait — call sites only
  ever read `barCloseAt`, so swapping in a real bar-close websocket event
  is a one-line change.
*/

const BASE_PRICES: Record<Pair, number> = {
  EURUSD: 1.0842,
  GBPUSD: 1.2613,
  USDJPY: 156.42,
  XAUUSD: 2398.5,
};

const PIP: Record<Pair, number> = {
  EURUSD: 0.0001,
  GBPUSD: 0.0001,
  USDJPY: 0.01,
  XAUUSD: 0.1,
};

function rand(min: number, max: number) {
  return Math.random() * (max - min) + min;
}

function nextH4BarClose(): number {
  const now = new Date();
  const next = new Date(now);
  const hourBlock = Math.floor(now.getUTCHours() / 4) * 4 + 4;
  next.setUTCHours(hourBlock, 0, 0, 0);
  return next.getTime();
}

function makeSignalState(pair: Pair): SignalState {
  const regimes: Regime[] = ['TREND', 'MEAN_REV', 'HIGH_VOL'];
  const regime = regimes[Math.floor(Math.random() * regimes.length)];
  const conviction = rand(0.4, 0.92);
  const votes: Array<Direction2> = ['LONG', 'SHORT', 'FLAT'];
  const agree = Math.random() > 0.35;
  const primary = votes[Math.floor(Math.random() * votes.length)];
  const ensemble: EnsembleVote[] = (['TREE', 'CNN'] as const).map((m, i) => ({
    model: m,
    vote: agree ? primary : votes[(i + Math.floor(Math.random() * votes.length)) % votes.length],
    weight: rand(0.3, 0.7),
  }));
  return {
    pair,
    regime,
    regimeBarsHeld: Math.floor(rand(1, 18)),
    conviction,
    convictionGate: 0.62,
    ensemble,
    metaLabelProb: rand(0.45, 0.88),
    lastInferenceMs: Date.now(),
    featureDrift: Math.random() > 0.92,
  };
}

type Direction2 = 'LONG' | 'SHORT' | 'FLAT';

function makePosition(ticket: number, pair: Pair): Position {
  const base = BASE_PRICES[pair];
  const pip = PIP[pair];
  const direction = Math.random() > 0.5 ? 'LONG' : 'SHORT';
  const entry = base * rand(0.998, 1.002);
  const drift = direction === 'LONG' ? rand(-30, 60) : rand(-60, 30);
  const current = entry + drift * pip;
  const lots = Number(rand(0.1, 1.2).toFixed(2));
  const pnlPips = direction === 'LONG' ? (current - entry) / pip : (entry - current) / pip;
  const sl = direction === 'LONG' ? entry - 80 * pip : entry + 80 * pip;
  const tp = direction === 'LONG' ? entry + 160 * pip : entry - 160 * pip;
  const distToBoundary = Math.min(Math.abs(current - sl), Math.abs(tp - current)) / pip;
  return {
    ticket,
    pair,
    direction,
    entry,
    current,
    lots,
    unrealizedPnl: pnlPips * lots * 10,
    sl,
    tp,
    openedAt: Date.now() - rand(1, 14) * 3600 * 1000,
    nearBoundary: distToBoundary < 20,
  };
}

function correlationSeed(): RiskState['correlation'] {
  const m: RiskState['correlation'] = {} as RiskState['correlation'];
  for (const a of PAIRS) {
    m[a] = {} as Record<Pair, number>;
    for (const b of PAIRS) {
      if (a === b) m[a][b] = 1;
      else if (m[b]?.[a] !== undefined) m[a][b] = m[b][a];
      else m[a][b] = Number(rand(-0.85, 0.9).toFixed(2));
    }
  }
  return m;
}

export interface MockFeedState {
  prices: Record<Pair, PriceTile>;
  account: AccountHealth;
  positions: Position[];
  risk: RiskState;
  signals: Record<Pair, SignalState>;
  system: SystemHealth;
  equityForecast: EquityForecast;
  barCloseAt: number;
  now: number;
}

function makeEquityForecast(equityCurve: { t: number; v: number }[]): EquityForecast {
  const days = 90;
  const dayMs = 86_400_000;
  const startV = equityCurve[0].v - rand(2000, 6000);
  const history = Array.from({ length: days }, (_, i) => ({
    t: Date.now() - (days - i) * dayMs,
    v: startV + (equityCurve[equityCurve.length - 1].v - startV) * (i / days) + Math.sin(i / 5) * 250 + rand(-150, 150),
  }));
  const last = { t: Date.now(), v: equityCurve[equityCurve.length - 1].v };
  history[history.length - 1] = last;

  const forecast: EquityForecast['forecast'] = { best: [last], normal: [last], worst: [last] };
  for (let i = 1; i <= 30; i++) {
    const t = Date.now() + i * dayMs;
    forecast.best.push({ t, v: last.v + i * rand(40, 90) });
    forecast.normal.push({ t, v: last.v + i * rand(-5, 15) });
    forecast.worst.push({ t, v: last.v - i * rand(30, 70) });
  }

  return { history, forecast, totalCommission: rand(180, 640) };
}

function initState(): MockFeedState {
  const prices = {} as Record<Pair, PriceTile>;
  for (const p of PAIRS) {
    const mid = BASE_PRICES[p];
    const spread = p === 'XAUUSD' ? rand(2.5, 4) : rand(0.6, 1.4);
    prices[p] = {
      pair: p,
      bid: mid,
      ask: mid + spread * PIP[p],
      spreadPips: spread,
      changePct: rand(-0.8, 0.8),
      spreadStatus: spread > (p === 'XAUUSD' ? 6 : 2.2) ? 'caution' : 'healthy',
    };
  }

  const equityCurve = Array.from({ length: 60 }, (_, i) => ({
    t: Date.now() - (60 - i) * 60_000,
    v: 50_000 + Math.sin(i / 6) * 400 + rand(-80, 80) + i * 3,
  }));

  const signals = {} as Record<Pair, SignalState>;
  for (const p of PAIRS) signals[p] = makeSignalState(p);

  return {
    prices,
    account: {
      equity: equityCurve[equityCurve.length - 1].v,
      equityCurve,
      realizedPnl: 842.3,
      unrealizedPnl: -126.4,
      commission: 64.2,
      winRatePct: 58.4,
      dailyPnl: 715.9,
      weeklyPnl: 2310.5,
      mtdPnl: 6120.8,
      drawdownPct: 3.2,
      maxDrawdownPct: 12,
      marginLevelPct: 612,
      freeMargin: 47210,
      leverageUsed: 1.8,
    },
    positions: [makePosition(881023, 'EURUSD'), makePosition(881031, 'XAUUSD'), makePosition(881042, 'GBPUSD')],
    risk: {
      portfolioHeatPct: rand(3, 7),
      portfolioHeatCeilingPct: 10,
      correlation: correlationSeed(),
      correlationCeiling: 0.65,
      atrRisk: PAIRS.map((p) => ({ pair: p, currentRiskPct: rand(0.4, 1.4), atrSizedRiskPct: rand(0.6, 1.5) })),
      circuitBreaker: { status: 'ARMED', dailyLossPct: rand(0.5, 2.5), dailyLossLimitPct: 5 },
    },
    signals,
    system: {
      mt5Connected: true,
      latencyMs: rand(8, 40),
      vpsCpuPct: rand(15, 45),
      vpsMemPct: rand(30, 60),
      executionLog: [
        { t: Date.now() - 30_000, msg: 'EURUSD order filled at 1.08412 (4ms slippage)', level: 'info' },
        { t: Date.now() - 240_000, msg: 'XAUUSD spread 5.8 pips — above threshold', level: 'warn' },
      ],
    },
    equityForecast: makeEquityForecast(equityCurve),
    barCloseAt: nextH4BarClose(),
    now: Date.now(),
  };
}

export function useMockFeed(): MockFeedState {
  const [state, setState] = useState<MockFeedState>(initState);

  useEffect(() => {
    const priceTimer = setInterval(() => {
      setState((prev) => {
        const prices = { ...prev.prices };
        for (const p of PAIRS) {
          const t = prices[p];
          const pip = PIP[p];
          const moveBid = t.bid + rand(-1.5, 1.5) * pip;
          const spread = t.spreadPips + rand(-0.1, 0.1);
          const clampedSpread = Math.max(0.4, spread);
          prices[p] = {
            ...t,
            bid: moveBid,
            ask: moveBid + clampedSpread * pip,
            spreadPips: clampedSpread,
            changePct: t.changePct + rand(-0.03, 0.03),
            spreadStatus: clampedSpread > (p === 'XAUUSD' ? 6 : 2.2) ? 'caution' : 'healthy',
          };
        }
        const positions = prev.positions.map((pos) => {
          const pip = PIP[pos.pair];
          const current = pos.current + rand(-1.2, 1.2) * pip;
          const pnlPips = pos.direction === 'LONG' ? (current - pos.entry) / pip : (pos.entry - current) / pip;
          const distToBoundary = Math.min(Math.abs(current - pos.sl), Math.abs(pos.tp - current)) / pip;
          return { ...pos, current, unrealizedPnl: pnlPips * pos.lots * 10, nearBoundary: distToBoundary < 20 };
        });
        const lastV = prev.account.equityCurve[prev.account.equityCurve.length - 1].v;
        const equityCurve = [
          ...prev.account.equityCurve.slice(1),
          { t: Date.now(), v: lastV + rand(-15, 18) },
        ];
        return {
          ...prev,
          prices,
          positions,
          account: { ...prev.account, equityCurve, equity: equityCurve[equityCurve.length - 1].v },
          system: { ...prev.system, latencyMs: Math.max(4, prev.system.latencyMs + rand(-3, 3)) },
          now: Date.now(),
        };
      });
    }, 1500);

    // Demo acceleration: real system updates this block on H4 bar close only.
    const modelTimer = setInterval(() => {
      setState((prev) => {
        const signals = { ...prev.signals };
        const target = PAIRS[Math.floor(Math.random() * PAIRS.length)];
        signals[target] = makeSignalState(target);
        return { ...prev, signals, barCloseAt: nextH4BarClose() };
      });
    }, 20_000);

    const clockTimer = setInterval(() => {
      setState((prev) => ({ ...prev, now: Date.now() }));
    }, 1000);

    return () => {
      clearInterval(priceTimer);
      clearInterval(modelTimer);
      clearInterval(clockTimer);
    };
  }, []);

  return state;
}
