import sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import MetaTrader5 as mt5

sys.path.append('.')
from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l8_monitoring.backtest.predictor import SymbolPredictor
from backtest_single_symbol import simulate_single_asset

if not mt5_client.connect():
    sys.exit(1)

sym = "USDJPY"
start_date = datetime.now() - timedelta(days=95)
end_date = datetime.now()
df_raw = mt5_client.fetch_ohlcv(sym, mt5.TIMEFRAME_H4, start_date, end_date)
predictor = SymbolPredictor(sym)
df_pred = predictor.generate_predictions(df_raw)
df_test = df_pred.iloc[-390:]
dates, equity = simulate_single_asset(df_test, sym, initial_balance=333.33)

equity = np.array(equity)
returns = np.diff(equity) / equity[:-1]

# Max Drawdown
peak = np.maximum.accumulate(equity)
drawdown = (equity - peak) / peak
max_dd = drawdown.min() * 100

# Annualized Sharpe Ratio (assuming H4 timeframe, ~6 bars a day, 252 trading days -> 1512 bars/year)
if len(returns) > 0 and np.std(returns) != 0:
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(1512)
else:
    sharpe = 0.0

print(f"Max Drawdown: {max_dd:.2f}%")
print(f"OOS Return: {(equity[-1]-333.33)/333.33 * 100:.2f}%")
print(f"Sharpe Ratio: {sharpe:.2f}")
