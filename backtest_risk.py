import os
import json
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l8_monitoring.backtest.predictor import SymbolPredictor

def load_params(symbol):
    path = f'models/{symbol}/best_params_{symbol}.json'
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {'confidence_threshold': 0.5, 'sl_multiplier': 2.0}

def apply_confidence_scaling(base_leverage: float, p_correct: float, threshold: float) -> float:
    if p_correct < threshold:
        return 0.0
    # Simple kelly approx
    win_loss_ratio = 1.5
    kelly_f = p_correct - ((1.0 - p_correct) / win_loss_ratio)
    if kelly_f <= 0:
        return 0.0
    scaled_f = kelly_f * 0.5 # Half kelly
    return base_leverage * min(scaled_f, 1.0)

def simulate_risk(df, symbol, initial_balance=1000.0, risk_pct=0.03):
    params = load_params(symbol)
    threshold = params.get('confidence_threshold', 0.5)
    sl_multiplier = params.get('sl_multiplier', 2.0)
    
    if symbol == 'EURUSD': spread_pct = 0.00001
    elif symbol == 'USDJPY': spread_pct = 0.00002
    elif symbol == 'XAUUSD': spread_pct = 0.00010
    elif symbol == 'GBPUSD': spread_pct = 0.000015
    else: spread_pct = 0.00002
    
    balance = initial_balance
    equity_curve = [balance]
    dates = [df.index[0]]
    current_position = 0.0 
    
    for i in range(1, len(df)):
        signal = df['signal'].iloc[i-1]
        confidence = df['confidence'].iloc[i-1]
        
        # Calculate leverage required to risk `risk_pct` (e.g. 0.03) given the SL distance
        atr = df['atr'].iloc[i-1]
        close_price = df['close'].iloc[i-1]
        
        if close_price > 0 and atr > 0:
            stop_loss_pct = (atr * sl_multiplier) / close_price
            base_leverage = risk_pct / stop_loss_pct
            
            # Cap leverage at 100x just for safety
            base_leverage = min(base_leverage, 100.0)
            
            target_leverage = apply_confidence_scaling(base_leverage, confidence, threshold)
            target_position = float(signal) * target_leverage
        else:
            target_position = 0.0
            
        if target_position != current_position:
            cost = abs(target_position - current_position) * spread_pct * balance
            balance -= cost
            
        step_return = df['return'].iloc[i]
        pnl = target_position * step_return * balance
        balance += pnl
        
        current_position = target_position
        equity_curve.append(balance)
        dates.append(df.index[i])
        
    return dates, equity_curve

def run_risk_backtests():
    symbols = ['EURUSD', 'USDJPY', 'XAUUSD']
    if not mt5_client.connect():
        raise ConnectionError("Failed to connect to MT5.")
        
    # We will fetch 6 months of data
    start_date = datetime.now() - timedelta(days=190)
    end_date = datetime.now()
    
    print("Fetching data...")
    dict_preds = {}
    for sym in symbols:
        df_raw = mt5_client.fetch_ohlcv(sym, mt5.TIMEFRAME_H4, start_date, end_date)
        if df_raw is not None and not df_raw.empty:
            predictor = SymbolPredictor(sym)
            dict_preds[sym] = predictor.generate_predictions(df_raw)

    # Scenarios: 1 month (130 bars), 3 months (390 bars), 6 months (780 bars)
    # H4: 6 bars/day * 22 days/month = 132 bars/month
    scenarios = {
        '1 Month': 132,
        '3 Months': 396,
        '6 Months': 792
    }
    
    results = {}
    
    for name, bars in scenarios.items():
        print(f"\n=== {name} at 3% Risk per trade ===")
        combined_equity = None
        common_idx = None
        
        initial_alloc = 1000.0 / len(symbols)
        
        for sym in symbols:
            if sym not in dict_preds: continue
            df_test = dict_preds[sym].iloc[-bars:]
            
            dates, equity = simulate_risk(df_test, sym, initial_balance=initial_alloc, risk_pct=0.03)
            
            if common_idx is None:
                common_idx = dates
            
            if combined_equity is None:
                combined_equity = np.array(equity)
            else:
                # Ensure sizes match
                min_len = min(len(combined_equity), len(equity))
                combined_equity = combined_equity[:min_len] + np.array(equity)[:min_len]
                
        final_bal = combined_equity[-1]
        profit_pct = (final_bal - 1000) / 1000 * 100
        print(f"Final Balance: ${final_bal:.2f} ({profit_pct:.2f}%)")
        results[name] = profit_pct
        
    print("\n=== Forecast 1 Year ===")
    # Forecast based on 6 months
    six_month_return = results['6 Months'] / 100.0
    # Compounded to 1 year
    one_year_multiplier = (1 + six_month_return) ** 2
    one_year_profit_pct = (one_year_multiplier - 1) * 100
    
    forecast_bal = 1000 * one_year_multiplier
    print(f"Expected 1-Year Balance (from $1000): ${forecast_bal:.2f} ({one_year_profit_pct:.2f}%)")

if __name__ == "__main__":
    run_risk_backtests()
