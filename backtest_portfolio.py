import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l8_monitoring.backtest.predictor import SymbolPredictor
from src.layers.l6_risk_sizing.portfolio_env import PortfolioEnv
from src.layers.l6_risk_sizing.ppo_allocator import PPOAllocator

def fetch_and_predict(symbols, start_date):
    """
    Fetches data and generates predictions from start_date to now.
    """
    if not mt5_client.connect():
        raise ConnectionError("Failed to connect to MT5.")
        
    end_date = datetime.now()
    dict_preds = {}
    
    for sym in symbols:
        df_raw = mt5_client.fetch_ohlcv(sym, mt5.TIMEFRAME_H4, start_date, end_date)
        if df_raw is None or df_raw.empty:
            raise ValueError(f"Failed to fetch data for {sym}")
            
        predictor = SymbolPredictor(sym)
        df_pred = predictor.generate_predictions(df_raw)
        
        # Approximate spreads
        if sym == 'EURUSD': spread = 0.00001
        elif sym == 'USDJPY': spread = 0.00002
        elif sym == 'XAUUSD': spread = 0.00010
        elif sym == 'GBPUSD': spread = 0.000015
        else: spread = 0.00002
        
        df_pred['spread_pct'] = spread
        dict_preds[sym] = df_pred
        
    return dict_preds

def align_matrices(dict_preds, symbols):
    """
    Aligns the individual prediction DataFrames.
    """
    common_idx = None
    for sym in symbols:
        idx = dict_preds[sym].index
        if common_idx is None:
            common_idx = idx
        else:
            common_idx = common_idx.intersection(idx)
            
    time_steps = len(common_idx)
    num_assets = len(symbols)
    
    features_per_asset = 3
    df_features = np.zeros((time_steps, num_assets * features_per_asset))
    df_returns = np.zeros((time_steps, num_assets))
    df_spreads_pct = np.zeros((time_steps, num_assets))
    
    for i, sym in enumerate(symbols):
        df = dict_preds[sym].loc[common_idx]
        feat_start = i * features_per_asset
        df_features[:, feat_start] = df['signal'].values
        df_features[:, feat_start + 1] = df['confidence'].values
        df_features[:, feat_start + 2] = df['volatility'].values
        df_returns[:, i] = df['return'].values
        df_spreads_pct[:, i] = df['spread_pct'].values
        
    return common_idx, df_features, df_returns, df_spreads_pct

def run_backtest():
    print("=== PPO Full Portfolio Backtester ===")
    symbols = ['EURUSD', 'USDJPY', 'XAUUSD']
    
    # 1. Fetch from 2023-01-01 (same as primary models)
    print("1. Fetching full historical data (2023-present)...")
    start_date = datetime(2023, 1, 1)
    dict_preds = fetch_and_predict(symbols, start_date)
    
    print("2. Aligning time series matrices...")
    common_idx, features, returns, spreads_pct = align_matrices(dict_preds, symbols)
    
    print(f"Data aligned. Total H4 bars: {len(common_idx)}")
    
    # 3. Setup Train Environment
    print("3. Initializing Train RL Environment...")
    env_train = PortfolioEnv(df_features=features, df_returns=returns, df_spreads_pct=spreads_pct, symbols=symbols)
    
    # 4. Train PPO (Learn correlations over 3 years)
    print("4. Training PPO Allocator on 3-year dataset (In-sample for PPO)...")
    allocator = PPOAllocator(env_train)
    allocator.train(total_timesteps=30000)
    
    # 5. Setup Test Environment (Last 3 months = ~390 bars, Initial Balance = $1000)
    print("5. Initializing Test Environment (Last 3 months, Balance $1000)...")
    test_bars = 390
    test_idx = common_idx[-test_bars:]
    test_features = features[-test_bars:]
    test_returns = returns[-test_bars:]
    test_spreads_pct = spreads_pct[-test_bars:]
    
    env_test = PortfolioEnv(
        df_features=test_features, 
        df_returns=test_returns, 
        df_spreads_pct=test_spreads_pct, 
        symbols=symbols,
        initial_balance=1000.0
    )
    
    # 6. Deterministic Evaluation (Backtest)
    print("6. Running Deterministic Backtest over the 3-month period...")
    obs, _ = env_test.reset()
    done = False
    
    equity_curve = [1000.0]
    dates = [test_idx[0]]
    
    while not done:
        weights = allocator.predict_allocation(obs)
        obs, reward, done, truncated, info = env_test.step(weights)
        equity_curve.append(env_test.balance)
        dates.append(test_idx[env_test.current_step - 1] if env_test.current_step <= len(test_idx) else test_idx[-1])
        
    final_balance = equity_curve[-1]
    profit_pct = (final_balance - 1000) / 1000 * 100
    print(f"\n--- Backtest Results ---")
    print(f"Initial Balance: $1000.00")
    print(f"Final Balance:   ${final_balance:.2f}")
    print(f"Net Profit:      {profit_pct:.2f}% (in ~3 months)")
    
    # 7. Plotting
    print("7. Generating Equity Graph...")
    plt.figure(figsize=(12, 6))
    plt.plot(dates, equity_curve, color='blue', linewidth=2, label='PPO Portfolio (Trained on 3 years)')
    plt.title('Hedge Fund Portfolio Equity Curve (Last 3 Months)', fontsize=14)
    plt.xlabel('Date')
    plt.ylabel('Balance ($)')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('portfolio_equity_curve.png', dpi=300)
    print("Saved graph to 'portfolio_equity_curve.png'")
    
if __name__ == "__main__":
    run_backtest()
