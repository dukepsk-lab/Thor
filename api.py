import os
import json
import numpy as np
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict

app = FastAPI(title="Thor ML Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SymbolConfig(BaseModel):
    risk_per_trade: float
    confidence_threshold: float
    tp_multiplier: float
    sl_multiplier: float

class MultiConfigModel(BaseModel):
    configs: Dict[str, SymbolConfig]

def get_active_symbols():
    if not os.path.exists("models"):
        return []
    return [d for d in os.listdir("models") if os.path.isdir(os.path.join("models", d))]

@app.get("/api/config")
def get_config():
    master_config = {}
    default_cfg = {
        "risk_per_trade": 0.01,
        "confidence_threshold": 0.62,
        "tp_multiplier": 2.0,
        "sl_multiplier": 1.2
    }
    
    for sym in get_active_symbols():
        cfg = default_cfg.copy()
        file_path = f"models/{sym}/best_params_{sym}.json"
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                saved = json.load(f)
                cfg["tp_multiplier"] = saved.get("tp_multiplier", cfg["tp_multiplier"])
                cfg["sl_multiplier"] = saved.get("sl_multiplier", cfg["sl_multiplier"])
                cfg["confidence_threshold"] = saved.get("confidence_threshold", cfg["confidence_threshold"])
                cfg["risk_per_trade"] = saved.get("risk_per_trade", cfg["risk_per_trade"])
        master_config[sym] = cfg
        
    return {"configs": master_config}

@app.post("/api/config")
def save_config(data: MultiConfigModel):
    for sym, cfg in data.configs.items():
        # Ensure directory exists
        os.makedirs(f"models/{sym}", exist_ok=True)
        file_path = f"models/{sym}/best_params_{sym}.json"
        
        existing = {}
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                existing = json.load(f)
                
        existing["tp_multiplier"] = cfg.tp_multiplier
        existing["sl_multiplier"] = cfg.sl_multiplier
        existing["confidence_threshold"] = cfg.confidence_threshold
        existing["risk_per_trade"] = cfg.risk_per_trade
        
        with open(file_path, "w") as f:
            json.dump(existing, f, indent=4)
            
    return {"status": "success"}

@app.post("/api/forecast")
def generate_forecast(data: MultiConfigModel):
    days = 365
    dates = [datetime.now() - timedelta(days=x) for x in range(days, 0, -1)]
    
    symbols = get_active_symbols()
    
    combined_equity_curve = []
    individual_curves = {sym: [] for sym in symbols}
    
    current_equity = 10000.0
    symbol_equities = {sym: 10000.0 for sym in symbols}
    
    for d in dates:
        daily_total_pnl = 0
        date_str = d.strftime("%Y-%m-%d")
        
        for sym in symbols:
            cfg = data.configs.get(sym)
            if not cfg: continue
            
            win_rate = 0.40 + (cfg.confidence_threshold * 0.3)
            trades_per_day = max(0.2, 2.0 - (cfg.confidence_threshold * 1.5))
            
            daily_trades = np.random.poisson(trades_per_day)
            sym_pnl = 0
            
            for _ in range(daily_trades):
                risk_amount = (current_equity / len(symbols)) * cfg.risk_per_trade
                if np.random.random() < win_rate:
                    reward_ratio = cfg.tp_multiplier / cfg.sl_multiplier
                    sym_pnl += risk_amount * reward_ratio
                else:
                    sym_pnl -= risk_amount
                    
            symbol_equities[sym] += sym_pnl
            daily_total_pnl += sym_pnl
            
            individual_curves[sym].append({
                "date": date_str,
                "equity": round(symbol_equities[sym], 2)
            })
            
        current_equity += daily_total_pnl
        combined_equity_curve.append({
            "date": date_str,
            "equity": round(current_equity, 2)
        })
        
    return {
        "combined": combined_equity_curve,
        "individuals": individual_curves
    }

# ==========================================
# LIVE MONITORING ENDPOINTS
# ==========================================

import MetaTrader5 as mt5
from src.core.config import settings

_mt5_connected = False

def ensure_mt5():
    global _mt5_connected
    if _mt5_connected:
        info = mt5.terminal_info()
        if info is not None and info.connected:
            return True
        _mt5_connected = False

    initialized = mt5.initialize(
        path=settings.MT5_PATH,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
    )
    if not initialized:
        print(f"MT5 initialization failed in API, error code: {mt5.last_error()}")
        return False
    _mt5_connected = True
    return True

@app.get("/api/live/account")
def get_live_account():
    if not ensure_mt5():
        return {"error": "MT5 not connected", "balance": 0, "equity": 0, "margin_level": 0, "profit": 0}

    info = mt5.account_info()
    if info is None:
        return {"error": "Failed to get account info", "balance": 0, "equity": 0, "margin_level": 0, "profit": 0}

    now = datetime.now()
    deals = mt5.history_deals_get(now - timedelta(days=31), now) or []
    daily_pnl = sum(d.profit for d in deals if datetime.fromtimestamp(d.time).date() == now.date())
    weekly_pnl = sum(d.profit for d in deals if datetime.fromtimestamp(d.time) >= now - timedelta(days=7))
    mtd_pnl = sum(d.profit for d in deals if datetime.fromtimestamp(d.time).month == now.month and datetime.fromtimestamp(d.time).year == now.year)
    realized_pnl_30d = sum(d.profit for d in deals if datetime.fromtimestamp(d.time) >= now - timedelta(days=30))
    commission_30d = sum(d.commission for d in deals if datetime.fromtimestamp(d.time) >= now - timedelta(days=30))

    closes_30d = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and datetime.fromtimestamp(d.time) >= now - timedelta(days=30)]
    wins_30d = sum(1 for d in closes_30d if d.profit > 0)
    win_rate_30d = round(100 * wins_30d / len(closes_30d), 1) if closes_30d else 0.0

    return {
        "balance": info.balance,
        "equity": info.equity,
        "margin_free": info.margin_free,
        "margin_level": getattr(info, 'margin_level', 0.0),
        "profit": info.profit,
        "realized_pnl_30d": round(realized_pnl_30d, 2),
        "commission_30d": round(commission_30d, 2),
        "win_rate_30d": win_rate_30d,
        "daily_pnl": round(daily_pnl, 2),
        "weekly_pnl": round(weekly_pnl, 2),
        "mtd_pnl": round(mtd_pnl, 2),
        "drawdown_pct": live_engine.get_drawdown_pct(info.equity),
        "max_drawdown_pct": 15.0,
        "leverage_used": round((info.equity - info.margin_free) / info.equity, 2) if info.equity else 0.0,
    }

@app.get("/api/account/equity-history")
def get_equity_history():
    empty = {"history": [], "forecast": {"best": [], "normal": [], "worst": []}, "totalCommission": 0.0}
    if not ensure_mt5():
        return empty

    info = mt5.account_info()
    if info is None:
        return empty

    to_date = datetime.now()
    deals = sorted(mt5.history_deals_get(datetime(2000, 1, 1), to_date) or [], key=lambda d: d.time)
    total_commission = round(sum(d.commission for d in deals), 2)

    if not deals:
        now_ms = int(to_date.timestamp() * 1000)
        return {
            "history": [{"t": now_ms, "v": round(info.equity, 2)}],
            "forecast": {"best": [], "normal": [], "worst": []},
            "totalCommission": total_commission,
        }

    net_total = sum(d.profit + d.commission + d.swap for d in deals)
    running = info.balance - net_total
    history = []
    for d in deals:
        running += d.profit + d.commission + d.swap
        history.append({"t": int(d.time) * 1000, "v": round(running, 2)})
    history.append({"t": int(to_date.timestamp() * 1000), "v": round(info.equity, 2)})

    daily_pnl: Dict[str, float] = {}
    for d in deals:
        day = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d")
        daily_pnl[day] = daily_pnl.get(day, 0.0) + d.profit + d.commission + d.swap
    samples = list(daily_pnl.values())

    last_point = {"t": int(to_date.timestamp() * 1000), "v": round(info.equity, 2)}
    forecast = {"best": [last_point], "normal": [last_point], "worst": [last_point]}

    if len(samples) >= 5:
        n_sims, n_days = 500, 30
        draws = np.random.choice(samples, size=(n_sims, n_days), replace=True)
        paths = info.equity + np.cumsum(draws, axis=1)
        best = np.percentile(paths, 90, axis=0)
        normal = np.percentile(paths, 50, axis=0)
        worst = np.percentile(paths, 10, axis=0)
        for i in range(n_days):
            t_ms = int((to_date + timedelta(days=i + 1)).timestamp() * 1000)
            forecast["best"].append({"t": t_ms, "v": round(float(best[i]), 2)})
            forecast["normal"].append({"t": t_ms, "v": round(float(normal[i]), 2)})
            forecast["worst"].append({"t": t_ms, "v": round(float(worst[i]), 2)})

    return {"history": history, "forecast": forecast, "totalCommission": total_commission}

@app.get("/api/live/positions")
def get_live_positions():
    if not ensure_mt5():
        return []

    positions = mt5.positions_get()
    if positions is None:
        return []

    result = []
    for pos in positions:
        direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
        pip = live_engine.PIP.get(pos.symbol, 0.0001)
        dist_to_boundary = min(abs(pos.price_current - pos.sl), abs(pos.tp - pos.price_current)) / pip if pos.sl and pos.tp else None
        result.append({
            "ticket": pos.ticket,
            "symbol": pos.symbol,
            "type": direction,
            "volume": pos.volume,
            "open_price": pos.price_open,
            "current_price": pos.price_current,
            "sl": pos.sl,
            "tp": pos.tp,
            "profit": pos.profit,
            "time_ms": int(pos.time) * 1000,
            "near_boundary": dist_to_boundary is not None and dist_to_boundary < 20,
        })
    return result

@app.get("/api/live/history")
def get_live_history():
    if not ensure_mt5():
        return []
        
    # Get last 30 days of history
    to_date = datetime.now()
    from_date = to_date - timedelta(days=30)
    
    deals = mt5.history_deals_get(from_date, to_date)
    if deals is None or len(deals) == 0:
        return []
        
    # Group by day to build equity curve
    daily_pnl = {}
    
    # We only care about deals that actually realize profit (deal type DEAL_TYPE_BUY or SELL usually has profit if it closed a position)
    # Actually, simpler: just sum all deals' profit per day.
    for deal in deals:
        day_str = datetime.fromtimestamp(deal.time).strftime('%Y-%m-%d')
        if day_str not in daily_pnl:
            daily_pnl[day_str] = 0.0
        daily_pnl[day_str] += deal.profit
        
    sorted_days = sorted(daily_pnl.keys())
    
    # Try to calculate historical equity curve from current balance backwards
    info = mt5.account_info()
    current_balance = info.balance if info else 10000.0
    
    # We will just plot cumulative PnL from 30 days ago starting at 0
    curve = []
    cum_pnl = 0.0
    for day in sorted_days:
        cum_pnl += daily_pnl[day]
        curve.append({
            "date": day,
            "pnl": round(cum_pnl, 2)
        })
        
    return curve

@app.get("/api/stats")
def get_stats():
    # Real metrics are written by backtest_single_symbol.py. We never fabricate
    # numbers: if no backtest has been run, say so explicitly.
    stats_path = "data/backtest_stats.json"
    if not os.path.exists(stats_path):
        return {
            "available": False,
            "message": "No backtest results yet. Run backtest_single_symbol.py to generate real out-of-sample metrics.",
        }
    with open(stats_path) as f:
        data = json.load(f)
    data["available"] = True
    return data

# ==========================================
# TERMINAL DASHBOARD ENDPOINTS (real data)
# ==========================================

from src.api import live_engine
from src.layers.l7_execution.order_manager import OrderManager

_order_manager = OrderManager(magic_number=777, slippage_points=10)

@app.get("/api/live/prices")
def get_live_prices():
    if not ensure_mt5():
        return {}
    return live_engine.get_live_prices(get_active_symbols())

@app.get("/api/signals/state")
def get_signals_state():
    if not ensure_mt5():
        return {}
    out = {}
    for sym in get_active_symbols():
        state = live_engine.compute_signal_state(sym)
        if state is not None:
            out[sym] = state
    return out

@app.get("/api/risk/state")
def get_risk_state():
    if not ensure_mt5():
        return {}
    return live_engine.get_risk_state(get_active_symbols())

@app.get("/api/system/health")
def get_system_health():
    return live_engine.get_system_health()

@app.post("/api/execution/flatten-all")
def flatten_all():
    if not ensure_mt5():
        return {"error": "MT5 not connected", "results": []}
    results = _order_manager.flatten_all()
    return {"results": results}

from fastapi.staticfiles import StaticFiles
if os.path.exists("web-dashboard/dist"):
    app.mount("/", StaticFiles(directory="web-dashboard/dist", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
