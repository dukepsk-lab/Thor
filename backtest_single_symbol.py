import os
import json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l8_monitoring.backtest.predictor import SymbolPredictor
from src.layers.l8_monitoring.validation.metrics import evaluate_strategy
from src.inference import decision

SPREAD_BPS = 1.0   # per-trade spread assumption used for reported metrics
COMM_BPS = 0.5     # per-trade commission assumption


def compute_and_save_stats(per_symbol: dict, out_path: str = "data/backtest_stats.json"):
    """
    Aggregate per-symbol (target_position, return) series into honest, real
    portfolio metrics and persist them for /api/stats. Replaces the old
    hardcoded placeholder numbers.
    """
    targets = pd.concat([t for t, _ in per_symbol.values()])
    returns = pd.concat([r for _, r in per_symbol.values()])

    m = evaluate_strategy(targets, returns, spread_bps=SPREAD_BPS, comm_bps=COMM_BPS).get('strat_net', {})

    # Per-bar net strategy returns for win rate / profit factor / trade count.
    gross = targets.shift(1) * returns
    trades = targets.diff().abs().fillna(0)
    net = (gross - trades * ((SPREAD_BPS + COMM_BPS) / 10000.0)).dropna()
    active = net[net != 0]
    wins, losses = active[active > 0], active[active < 0]
    win_rate = len(wins) / len(active) if len(active) else 0.0
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else 0.0

    stats = {
        "generated_at": datetime.now().isoformat(timespec='seconds'),
        "annual_return": f"{m.get('Ann Return', 0) * 100:.1f}%",
        "max_drawdown": f"{m.get('Max Drawdown', 0) * 100:.1f}%",
        "sharpe_ratio": round(m.get('Sharpe', 0), 2),
        "win_rate": f"{win_rate * 100:.1f}%",
        "profit_factor": round(float(profit_factor), 2),
        "total_trades": int(trades.sum()),
        "sample": f"out-of-sample (last {decision.HOLDOUT_DAYS} days, excluded from training)",
        "costs_modeled": f"spread {SPREAD_BPS}bps + commission {COMM_BPS}bps per trade; swap/overnight NOT modeled",
        "symbols": list(per_symbol.keys()),
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"\n[stats] Saved real backtest metrics to {out_path}:\n{json.dumps(stats, indent=2)}")
    return stats

def load_threshold(symbol):
    return decision._load_threshold(symbol)

def simulate_single_asset(df, symbol, initial_balance=1000.0):
    # Spread approximations
    if symbol == 'EURUSD': spread_pct = 0.00001
    elif symbol == 'USDJPY': spread_pct = 0.00002
    elif symbol == 'XAUUSD': spread_pct = 0.00010
    elif symbol == 'GBPUSD': spread_pct = 0.000015
    else: spread_pct = 0.00002
    
    threshold = load_threshold(symbol)
    print(f"[{symbol}] Using Confidence Threshold: {threshold:.4f}")
    
    balance = initial_balance
    equity_curve = [balance]
    dates = [df.index[0]]
    current_position = 0.0 # 1.0 (Long), -1.0 (Short), 0.0 (Cash)
    
    for i in range(1, len(df)):
        signal = df['signal'].iloc[i-1]
        confidence = df['confidence'].iloc[i-1]
        
        # Determine target position
        if confidence >= threshold:
            target_position = float(signal)
        else:
            target_position = 0.0
            
        # Deduct transaction cost if position changes
        if target_position != current_position:
            # We pay spread on the absolute change in position size
            cost = abs(target_position - current_position) * spread_pct * balance
            balance -= cost
            
        # PnL from market movement
        step_return = df['return'].iloc[i]
        pnl = target_position * step_return * balance
        balance += pnl
        
        current_position = target_position
        equity_curve.append(balance)
        dates.append(df.index[i])
        
    return dates, equity_curve

def run_single_backtests():
    print("=== Single Asset & Equal-Weight Portfolio Backtester (No PPO) ===")
    symbols = ['EURUSD', 'USDJPY', 'XAUUSD']
    
    if not mt5_client.connect():
        raise ConnectionError("Failed to connect to MT5.")
        
    # Out-of-sample window: the same HOLDOUT_DAYS that train_and_save excluded,
    # plus padding so rolling features have warm-up history.
    start_date = datetime.now() - timedelta(days=decision.HOLDOUT_DAYS + 30)
    oos_start = datetime.now() - timedelta(days=decision.HOLDOUT_DAYS)
    end_date = datetime.now()

    plt.figure(figsize=(12, 6))

    equities = {}
    per_symbol_stats = {}
    
    # We will simulate allocating $333.33 (1/3 of $1000) to each asset independently
    initial_alloc = 1000.0 / len(symbols)
    
    for sym in symbols:
        print(f"\n--- Backtesting {sym} ---")
        df_raw = mt5_client.fetch_ohlcv(sym, mt5.TIMEFRAME_H4, start_date, end_date)
        if df_raw is None or df_raw.empty:
            print(f"Skipping {sym}, no data.")
            continue
            
        predictor = SymbolPredictor(sym)
        df_pred = predictor.generate_predictions(df_raw)

        # Restrict to the out-of-sample window (bars excluded from training).
        df_test = df_pred[df_pred.index >= pd.Timestamp(oos_start)]
        if df_test.empty:
            print(f"Skipping {sym}, no out-of-sample bars.")
            continue

        dates, equity = simulate_single_asset(df_test, sym, initial_balance=initial_alloc)

        # Collect target positions + returns for honest aggregate metrics.
        threshold = load_threshold(sym)
        target = df_test['signal'].where(df_test['confidence'] >= threshold, 0).astype(float)
        per_symbol_stats[sym] = (target, df_test['return'])

        equities[sym] = pd.Series(equity, index=pd.DatetimeIndex(dates))
        
        final_balance = equity[-1]
        profit_pct = (final_balance - initial_alloc) / initial_alloc * 100
        print(f"{sym} Final Balance: ${final_balance:.2f} ({profit_pct:.2f}%)")
        
        plt.plot(dates, equity, linestyle='--', alpha=0.5, label=f'{sym} (Net: {profit_pct:.2f}%)')
        
    # Calculate Combined Portfolio Equity. Symbols can have different out-of-sample
    # window lengths (different data availability), so align on the union of dates
    # instead of assuming equal-length arrays. Before a symbol's first bar it hasn't
    # started trading yet, so it holds its flat initial allocation.
    if equities:
        common_idx = sorted(set().union(*[s.index for s in equities.values()]))
        combined_equity = pd.Series(0.0, index=common_idx)
        for sym, s in equities.items():
            aligned = s.reindex(common_idx).ffill().fillna(initial_alloc)
            combined_equity += aligned

        final_port_balance = combined_equity.iloc[-1]
        port_profit_pct = (final_port_balance - 1000.0) / 1000.0 * 100
        print(f"\n--- Equal-Weight Portfolio Results ---")
        print(f"Initial Portfolio Balance: $1000.00")
        print(f"Final Portfolio Balance:   ${final_port_balance:.2f} ({port_profit_pct:.2f}%)")

        plt.plot(common_idx, combined_equity.values, color='black', linewidth=3, label=f'Combined Portfolio (Net: {port_profit_pct:.2f}%)')
        
    plt.title('Equal-Weight Portfolio vs Individual Assets (Last 3 Months, No PPO)', fontsize=14)
    plt.xlabel('Date')
    plt.ylabel('Balance ($)')
    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('combined_portfolio_equity.png', dpi=300)
    print("\nSaved graph to 'combined_portfolio_equity.png'")

    # Persist real metrics for /api/stats (replaces the old hardcoded numbers).
    if per_symbol_stats:
        compute_and_save_stats(per_symbol_stats)

if __name__ == "__main__":
    run_single_backtests()
