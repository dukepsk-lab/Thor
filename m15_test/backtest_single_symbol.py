import os
import json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l8_monitoring.backtest.predictor import SymbolPredictor

def load_threshold(symbol):
    path = f'models/{symbol}/best_params_{symbol}.json'
    if os.path.exists(path):
        with open(path, 'r') as f:
            params = json.load(f)
            return params.get('confidence_threshold', 0.5)
    return 0.5

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
        
    # 3 months = approx 95 days
    start_date = datetime.now() - timedelta(days=95) # padding
    end_date = datetime.now()
    
    plt.figure(figsize=(12, 6))
    
    equities = {}
    common_idx = None
    
    # We will simulate allocating $333.33 (1/3 of $1000) to each asset independently
    initial_alloc = 1000.0 / len(symbols)
    
    for sym in symbols:
        print(f"\n--- Backtesting {sym} ---")
        df_raw = mt5_client.fetch_ohlcv(sym, mt5.TIMEFRAME_M15, start_date, end_date)
        if df_raw is None or df_raw.empty:
            print(f"Skipping {sym}, no data.")
            continue
            
        if not os.path.exists(f'models/{sym}'):
            print(f"Skipping {sym}, models not found.")
            continue
            
        predictor = SymbolPredictor(sym)
        df_pred = predictor.generate_predictions(df_raw)
        
        # Take the last 6000 bars (~3 months on M15)
        df_test = df_pred.iloc[-6000:]
        
        dates, equity = simulate_single_asset(df_test, sym, initial_balance=initial_alloc)
        
        if common_idx is None:
            common_idx = dates
            
        equities[sym] = equity
        
        final_balance = equity[-1]
        profit_pct = (final_balance - initial_alloc) / initial_alloc * 100
        print(f"{sym} Final Balance: ${final_balance:.2f} ({profit_pct:.2f}%)")
        
        plt.plot(dates, equity, linestyle='--', alpha=0.5, label=f'{sym} (Net: {profit_pct:.2f}%)')
        
    # Calculate Combined Portfolio Equity
    if equities:
        combined_equity = np.zeros(len(common_idx))
        for sym in symbols:
            if sym in equities:
                combined_equity += np.array(equities[sym])
                
        final_port_balance = combined_equity[-1]
        port_profit_pct = (final_port_balance - 1000.0) / 1000.0 * 100
        print(f"\n--- Equal-Weight Portfolio Results ---")
        print(f"Initial Portfolio Balance: $1000.00")
        print(f"Final Portfolio Balance:   ${final_port_balance:.2f} ({port_profit_pct:.2f}%)")
        
        plt.plot(common_idx, combined_equity, color='black', linewidth=3, label=f'Combined Portfolio (Net: {port_profit_pct:.2f}%)')
        
    plt.title('Equal-Weight Portfolio vs Individual Assets (Last 3 Months, No PPO)', fontsize=14)
    plt.xlabel('Date')
    plt.ylabel('Balance ($)')
    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('combined_portfolio_equity.png', dpi=300)
    print("\nSaved graph to 'combined_portfolio_equity.png'")

if __name__ == "__main__":
    run_single_backtests()
