"""
Read-only inference + risk-state helpers backing the dashboard's live endpoints.

Mirrors the feature/regime/signal computation in live_bot.py's run_cycle(),
but never sends orders. Per-symbol models are loaded once and cached in
process memory; regime-bars-held and last-inference-time are tracked the
same way (in-memory only — they reset if the API process restarts).
"""
import os
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import torch
import MetaTrader5 as mt5

from src.inference import decision

TIMEFRAME = mt5.TIMEFRAME_H4
PIP = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.1}

# Map the canonical router regime label to the dashboard's display vocabulary.
_REGIME_DISPLAY = {
    "state_0": "TREND", "state_1": "MEAN_REV", "state_2": "HIGH_VOL",
    "trend": "TREND", "range": "MEAN_REV", "neutral": "MEAN_REV",
}

CIRCUIT_BREAKER_STATE_FILE = "data/circuit_breaker_state.json"


class _SymbolEngine:
    def __init__(self, symbol: str):
        # Shared loader: same models, same contract validation as live_bot/backtest.
        m = decision.load_models(symbol, load_cnn=True)
        self.symbol = symbol
        self.hmm = m.hmm
        self.tree = m.tree
        self.cnn = m.cnn
        self.meta = m.meta
        self.confidence_threshold = m.confidence_threshold

        self.last_regime: Optional[str] = None
        self.regime_bars_held = 0
        self.last_inference_ms: Optional[int] = None


_engines: Dict[str, _SymbolEngine] = {}
_engines_lock = threading.Lock()


def _get_engine(symbol: str) -> Optional[_SymbolEngine]:
    if symbol in _engines:
        return _engines[symbol]
    with _engines_lock:
        if symbol in _engines:
            return _engines[symbol]
        if not os.path.exists(f"models/{symbol}/hmm_model.pkl"):
            return None
        try:
            engine = _SymbolEngine(symbol)
        except (FileNotFoundError, TypeError) as e:
            # Missing or outdated-format models: surface in logs, degrade gracefully.
            print(f"[live_engine] Cannot load models for {symbol}: {e}")
            return None
        _engines[symbol] = engine
        return engine


def compute_signal_state(symbol: str) -> Optional[dict]:
    engine = _get_engine(symbol)
    if engine is None:
        return None

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, 50)
    if rates is None or len(rates) < 30:
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)

    df_feats = decision.compute_features(df)

    # second-to-last bar: the most recent fully-closed candle
    latest = df_feats.iloc[-2:-1]

    # Canonical decision -- identical to live_bot.run_cycle() and the backtest.
    dec = decision.generate_decisions(engine, latest, engine.confidence_threshold)
    primary_signal = int(dec["primary_signal"].iloc[0])
    p_correct = float(dec["p_correct"].iloc[0])
    current_regime = _REGIME_DISPLAY.get(dec["regime"].iloc[0], "MEAN_REV")

    # ---- Display-only model votes (cosmetic; not part of the trade decision) ----
    tree_probas = decision._tree_probas(engine.tree, latest[decision.FEATURES_FLAT])[0]
    tree_class = int(np.argmax(tree_probas))
    tree_vote = "SHORT" if tree_class == 0 else ("LONG" if tree_class == 2 else "FLAT")
    tree_weight = float(tree_probas[tree_class])

    # CNN is untrained scaffolding; shown for display parity only, never traded on.
    seq_window = df_feats.iloc[-11:-1][decision.FEATURES_FLAT].values
    cnn_vote, cnn_weight = "FLAT", 0.34
    if len(seq_window) == 10:
        x = torch.tensor(seq_window, dtype=torch.float32).T.unsqueeze(0)
        with torch.no_grad():
            cnn_probas = engine.cnn(x).numpy()[0]
        cnn_class = int(np.argmax(cnn_probas))
        cnn_vote = "SHORT" if cnn_class == 0 else ("LONG" if cnn_class == 2 else "FLAT")
        cnn_weight = float(cnn_probas[cnn_class])

    if engine.last_regime == current_regime:
        engine.regime_bars_held += 1
    else:
        engine.last_regime = current_regime
        engine.regime_bars_held = 1
    engine.last_inference_ms = int(time.time() * 1000)

    return {
        "pair": symbol,
        "regime": current_regime,
        "regimeBarsHeld": engine.regime_bars_held,
        "conviction": p_correct,
        "convictionGate": engine.confidence_threshold,
        "ensemble": [
            {"model": "TREE", "vote": tree_vote, "weight": round(tree_weight, 3)},
            {"model": "CNN", "vote": cnn_vote, "weight": round(cnn_weight, 3)},
        ],
        "metaLabelProb": round(p_correct, 3),
        "lastInferenceMs": engine.last_inference_ms,
        "featureDrift": False,
    }


def get_live_prices(symbols: List[str]) -> dict:
    result = {}
    for sym in symbols:
        mt5.symbol_select(sym, True)
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if tick is None or info is None:
            continue

        pip_size = PIP.get(sym, info.point * 10)
        spread_pips = (tick.ask - tick.bid) / pip_size if pip_size else 0.0

        change_pct = 0.0
        d1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, 1)
        if d1 is not None and len(d1) > 0:
            day_open = float(d1[0]["open"])
            if day_open:
                change_pct = (tick.bid - day_open) / day_open * 100

        result[sym] = {
            "pair": sym,
            "bid": tick.bid,
            "ask": tick.ask,
            "spreadPips": round(spread_pips, 2),
            "changePct": round(change_pct, 3),
            "spreadStatus": "caution" if spread_pips > (6 if sym == "XAUUSD" else 2.2) else "healthy",
        }
    return result


def get_correlation_matrix(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    returns = {}
    for sym in symbols:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, TIMEFRAME, 0, 60)
        if rates is None or len(rates) < 10:
            continue
        closes = pd.Series([r["close"] for r in rates])
        returns[sym] = closes.pct_change().dropna().reset_index(drop=True)

    if len(returns) < 2:
        return {}

    corr = pd.DataFrame(returns).corr()
    return {
        a: {b: (1.0 if a == b else round(float(corr.loc[a, b]), 2)) for b in corr.columns}
        for a in corr.columns
    }


def _load_breaker_state() -> dict:
    if os.path.exists(CIRCUIT_BREAKER_STATE_FILE):
        try:
            with open(CIRCUIT_BREAKER_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"peak_equity": 0.0, "day": None, "day_start_equity": None}


def _save_breaker_state(state: dict) -> None:
    os.makedirs(os.path.dirname(CIRCUIT_BREAKER_STATE_FILE), exist_ok=True)
    with open(CIRCUIT_BREAKER_STATE_FILE, "w") as f:
        json.dump(state, f)


def _read_risk_per_trade_pct(symbol: str) -> float:
    file_path = f"models/{symbol}/best_params_{symbol}.json"
    if os.path.exists(file_path):
        try:
            with open(file_path) as f:
                return float(json.load(f).get("risk_per_trade", 0.01)) * 100
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    return 1.0


def get_drawdown_pct(equity: float) -> float:
    state = _load_breaker_state()
    peak = max(state.get("peak_equity") or 0.0, equity)
    return round(((peak - equity) / peak * 100) if peak > 0 else 0.0, 2)


def get_risk_state(symbols: List[str], daily_loss_limit_pct: float = 5.0, max_drawdown_limit_pct: float = 15.0) -> dict:
    info = mt5.account_info()
    equity = info.equity if info else 0.0

    state = _load_breaker_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["day_start_equity"] = equity
    if equity > state.get("peak_equity", 0.0):
        state["peak_equity"] = equity
    _save_breaker_state(state)

    peak = state.get("peak_equity") or equity
    drawdown_pct = ((peak - equity) / peak * 100) if peak > 0 else 0.0
    day_start = state.get("day_start_equity") or equity
    daily_loss_pct = max(0.0, (day_start - equity) / day_start * 100) if day_start > 0 else 0.0
    is_halted = drawdown_pct >= max_drawdown_limit_pct or daily_loss_pct >= daily_loss_limit_pct

    open_positions = mt5.positions_get() or []
    pos_by_symbol = {p.symbol: p for p in open_positions}

    atr_risk = []
    portfolio_heat_pct = 0.0
    for sym in symbols:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, TIMEFRAME, 0, 30)
        current_risk_pct = 0.0
        if rates is not None and len(rates) >= 15:
            df = pd.DataFrame(rates)
            atr_value = float(calculate_atr(df, period=14).bfill().iloc[-1])

            pos = pos_by_symbol.get(sym)
            symbol_info = mt5.symbol_info(sym)
            if pos is not None and symbol_info is not None and equity > 0:
                tick_size = symbol_info.trade_tick_size or symbol_info.point
                tick_value = symbol_info.trade_tick_value or 1.0
                stop_distance = abs(pos.price_open - pos.sl) if pos.sl else atr_value * 2
                if tick_size > 0:
                    risk_dollar = (stop_distance / tick_size) * tick_value * pos.volume
                    current_risk_pct = (risk_dollar / equity) * 100

        atr_sized_risk_pct = _read_risk_per_trade_pct(sym)
        portfolio_heat_pct += current_risk_pct
        atr_risk.append({
            "pair": sym,
            "currentRiskPct": round(current_risk_pct, 2),
            "atrSizedRiskPct": round(atr_sized_risk_pct, 2),
        })

    return {
        "portfolioHeatPct": round(portfolio_heat_pct, 2),
        "portfolioHeatCeilingPct": 10.0,
        "correlation": get_correlation_matrix(symbols),
        "correlationCeiling": 0.65,
        "atrRisk": atr_risk,
        "circuitBreaker": {
            "status": "TRIGGERED" if is_halted else "ARMED",
            "dailyLossPct": round(daily_loss_pct, 2),
            "dailyLossLimitPct": daily_loss_limit_pct,
        },
    }


def get_system_health() -> dict:
    from src.core.config import settings
    connected = mt5.initialize(
        path=settings.MT5_PATH,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
    )
    latency_ms = 0.0
    if connected:
        start = time.perf_counter()
        mt5.symbol_info_tick("EURUSD")
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

    cpu_pct = 0.0
    mem_pct = 0.0
    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=0.05)
        mem_pct = psutil.virtual_memory().percent
    except ImportError:
        pass

    return {
        "mt5Connected": connected,
        "latencyMs": latency_ms,
        "vpsCpuPct": cpu_pct,
        "vpsMemPct": mem_pct,
        # No execution log persistence exists yet (live_bot.py only prints to
        # stdout) — surfaced empty rather than fabricated.
        "executionLog": [],
    }
