export type Pair = 'EURUSD' | 'GBPUSD' | 'USDJPY' | 'XAUUSD';

export const PAIRS: Pair[] = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'];

export type Status = 'healthy' | 'caution' | 'critical';

export interface PriceTile {
  pair: Pair;
  bid: number;
  ask: number;
  spreadPips: number;
  changePct: number;
  spreadStatus: Status;
}

export interface SessionWindow {
  name: 'Tokyo' | 'London' | 'New York';
  active: boolean;
  overlap: boolean;
}

export interface AccountHealth {
  equity: number;
  equityCurve: { t: number; v: number }[];
  realizedPnl: number;
  unrealizedPnl: number;
  dailyPnl: number;
  weeklyPnl: number;
  mtdPnl: number;
  drawdownPct: number;
  maxDrawdownPct: number;
  marginLevelPct: number;
  freeMargin: number;
  leverageUsed: number;
}

export type Direction = 'LONG' | 'SHORT';

export interface Position {
  ticket: number;
  pair: Pair;
  direction: Direction;
  entry: number;
  current: number;
  lots: number;
  unrealizedPnl: number;
  sl: number;
  tp: number;
  openedAt: number;
  nearBoundary: boolean;
}

export interface RiskState {
  portfolioHeatPct: number;
  portfolioHeatCeilingPct: number;
  correlation: Record<Pair, Record<Pair, number>>;
  correlationCeiling: number;
  atrRisk: { pair: Pair; currentRiskPct: number; atrSizedRiskPct: number }[];
  circuitBreaker: {
    status: 'ARMED' | 'TRIGGERED';
    dailyLossPct: number;
    dailyLossLimitPct: number;
  };
}

export type Regime = 'TREND' | 'MEAN_REV' | 'HIGH_VOL';

export interface EnsembleVote {
  model: 'TREE' | 'CNN';
  vote: Direction | 'FLAT';
  weight: number;
}

export interface SignalState {
  pair: Pair;
  regime: Regime;
  regimeBarsHeld: number;
  conviction: number;
  convictionGate: number;
  ensemble: EnsembleVote[];
  metaLabelProb: number;
  lastInferenceMs: number;
  featureDrift: boolean;
}

export interface SystemHealth {
  mt5Connected: boolean;
  latencyMs: number;
  vpsCpuPct: number;
  vpsMemPct: number;
  executionLog: { t: number; msg: string; level: 'info' | 'warn' | 'error' }[];
}

export interface EquityPoint {
  t: number;
  v: number;
}

export interface EquityForecast {
  history: EquityPoint[];
  forecast: {
    best: EquityPoint[];
    normal: EquityPoint[];
    worst: EquityPoint[];
  };
  totalCommission: number;
}
