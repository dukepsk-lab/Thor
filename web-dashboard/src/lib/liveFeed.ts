import { useEffect, useRef, useState } from 'react';
import {
  type AccountHealth,
  type EquityForecast,
  type Pair,
  type Position,
  type PriceTile,
  type RiskState,
  type SignalState,
  type SystemHealth,
} from './types';
import type { MockFeedState } from './mockFeed';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

function nextH4BarClose(): number {
  const now = new Date();
  const next = new Date(now);
  const hourBlock = Math.floor(now.getUTCHours() / 4) * 4 + 4;
  next.setUTCHours(hourBlock, 0, 0, 0);
  return next.getTime();
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function emptyAccount(): AccountHealth {
  return {
    equity: 0,
    equityCurve: [{ t: Date.now(), v: 0 }],
    realizedPnl: 0,
    unrealizedPnl: 0,
    commission: 0,
    winRatePct: 0,
    dailyPnl: 0,
    weeklyPnl: 0,
    mtdPnl: 0,
    drawdownPct: 0,
    maxDrawdownPct: 15,
    marginLevelPct: 0,
    freeMargin: 0,
    leverageUsed: 0,
  };
}

function emptyRisk(): RiskState {
  return {
    portfolioHeatPct: 0,
    portfolioHeatCeilingPct: 10,
    correlation: {} as RiskState['correlation'],
    correlationCeiling: 0.65,
    atrRisk: [],
    circuitBreaker: { status: 'ARMED', dailyLossPct: 0, dailyLossLimitPct: 5 },
  };
}

function emptySystem(): SystemHealth {
  return { mt5Connected: false, latencyMs: 0, vpsCpuPct: 0, vpsMemPct: 0, executionLog: [] };
}

function emptyEquityForecast(): EquityForecast {
  return { history: [{ t: Date.now(), v: 0 }], forecast: { best: [], normal: [], worst: [] }, totalCommission: 0 };
}

interface LivePriceResponse {
  pair: Pair;
  bid: number;
  ask: number;
  spreadPips: number;
  changePct: number;
  spreadStatus: 'healthy' | 'caution';
}

interface LiveAccountResponse {
  balance: number;
  equity: number;
  margin_free: number;
  margin_level: number;
  profit: number;
  realized_pnl_30d: number;
  commission_30d: number;
  win_rate_30d: number;
  daily_pnl: number;
  weekly_pnl: number;
  mtd_pnl: number;
  drawdown_pct: number;
  max_drawdown_pct: number;
  leverage_used: number;
  error?: string;
}

interface LivePositionResponse {
  ticket: number;
  symbol: Pair;
  type: 'BUY' | 'SELL';
  volume: number;
  open_price: number;
  current_price: number;
  sl: number;
  tp: number;
  profit: number;
  time_ms: number;
  near_boundary: boolean;
}

export function useLiveFeed(): MockFeedState {
  const [state, setState] = useState<MockFeedState>(() => ({
    prices: {} as Record<Pair, PriceTile>,
    account: emptyAccount(),
    positions: [],
    risk: emptyRisk(),
    signals: {} as Record<Pair, SignalState>,
    system: emptySystem(),
    equityForecast: emptyEquityForecast(),
    barCloseAt: nextH4BarClose(),
    now: Date.now(),
  }));

  const equityHistory = useRef<{ t: number; v: number }[]>([]);

  useEffect(() => {
    let cancelled = false;

    const pollFast = async () => {
      const [pricesRes, accountRes, positionsRes] = await Promise.all([
        getJson<Record<Pair, LivePriceResponse>>('/api/live/prices'),
        getJson<LiveAccountResponse>('/api/live/account'),
        getJson<LivePositionResponse[]>('/api/live/positions'),
      ]);
      if (cancelled) return;

      setState((prev) => {
        const next = { ...prev, now: Date.now() };

        if (pricesRes) {
          next.prices = pricesRes;
        }

        if (accountRes && !accountRes.error) {
          if (equityHistory.current.length === 0 || equityHistory.current.length > 200) {
            equityHistory.current = [{ t: Date.now(), v: accountRes.equity }];
          } else {
            equityHistory.current = [...equityHistory.current.slice(-119), { t: Date.now(), v: accountRes.equity }];
          }
          next.account = {
            equity: accountRes.equity,
            equityCurve: equityHistory.current,
            realizedPnl: accountRes.realized_pnl_30d,
            unrealizedPnl: accountRes.profit,
            commission: accountRes.commission_30d,
            winRatePct: accountRes.win_rate_30d,
            dailyPnl: accountRes.daily_pnl,
            weeklyPnl: accountRes.weekly_pnl,
            mtdPnl: accountRes.mtd_pnl,
            drawdownPct: accountRes.drawdown_pct,
            maxDrawdownPct: accountRes.max_drawdown_pct,
            marginLevelPct: accountRes.margin_level,
            freeMargin: accountRes.margin_free,
            leverageUsed: accountRes.leverage_used,
          };
        }

        if (positionsRes) {
          next.positions = positionsRes.map<Position>((p) => ({
            ticket: p.ticket,
            pair: p.symbol,
            direction: p.type === 'BUY' ? 'LONG' : 'SHORT',
            entry: p.open_price,
            current: p.current_price,
            lots: p.volume,
            unrealizedPnl: p.profit,
            sl: p.sl,
            tp: p.tp,
            openedAt: p.time_ms,
            nearBoundary: p.near_boundary,
          }));
        }

        return next;
      });
    };

    const pollSlow = async () => {
      const [riskRes, signalsRes, systemRes, equityForecastRes] = await Promise.all([
        getJson<RiskState>('/api/risk/state'),
        getJson<Record<Pair, SignalState>>('/api/signals/state'),
        getJson<SystemHealth>('/api/system/health'),
        getJson<EquityForecast>('/api/account/equity-history'),
      ]);
      if (cancelled) return;

      setState((prev) => ({
        ...prev,
        risk: riskRes ?? prev.risk,
        signals: signalsRes ?? prev.signals,
        system: systemRes ?? prev.system,
        equityForecast: equityForecastRes ?? prev.equityForecast,
        barCloseAt: nextH4BarClose(),
      }));
    };

    pollFast();
    pollSlow();

    const fastTimer = setInterval(pollFast, 2000);
    const slowTimer = setInterval(pollSlow, 15000);
    const clockTimer = setInterval(() => {
      setState((prev) => ({ ...prev, now: Date.now() }));
    }, 1000);

    return () => {
      cancelled = true;
      clearInterval(fastTimer);
      clearInterval(slowTimer);
      clearInterval(clockTimer);
    };
  }, []);

  return state;
}
