import numpy as np
import pandas as pd
from src.layers.l6_risk_sizing.portfolio_env import PortfolioEnv
from src.layers.l6_risk_sizing.ppo_allocator import PPOAllocator

def generate_mock_multi_asset_data(symbols, time_steps=5000):
    """
    Generate mock features, returns, and spreads.
    """
    print(f"Generating mock data for {symbols}...")
    num_assets = len(symbols)
    features_per_asset = 3 # e.g. [Signal_Direction, Meta_Confidence, Volatility]
    
    # Random normal features
    df_features = np.random.randn(time_steps, num_assets * features_per_asset)
    
    # Returns (slightly positive bias for testing)
    df_returns = np.random.normal(loc=0.0001, scale=0.005, size=(time_steps, num_assets))
    
    # Mock real raw spread (e.g. 0.00001 = 1 pip / point ratio equivalent)
    # Typically raw spread on IUX EURUSD is around 0.0-0.2 pips. We convert that to percentage of price.
    df_spreads_pct = np.random.uniform(low=0.00001, high=0.00005, size=(time_steps, num_assets))
    
    return df_features, df_returns, df_spreads_pct

def main():
    print("=== Training Multi-Asset PPO Allocator ===")
    symbols = ['EURUSD', 'USDJPY', 'XAUUSD']
    
    # 1. Fetch Multi-Asset Data
    features, returns, spreads_pct = generate_mock_multi_asset_data(symbols, time_steps=10000)
    
    # 2. Setup Environment
    print("Initializing RL Environment (Commission: $7/lot, Raw Spreads)...")
    env = PortfolioEnv(df_features=features, df_returns=returns, df_spreads_pct=spreads_pct, symbols=symbols)
    
    # 3. Initialize and Train PPO
    allocator = PPOAllocator(env)
    allocator.train(total_timesteps=20000)
    
    # 4. Save the Model
    allocator.save("models/ppo_allocator")
    
    # 5. Evaluate
    print("\n--- Evaluation on latest step ---")
    obs, _ = env.reset()
    weights = allocator.predict_allocation(obs)
    print("Predicted Portfolio Allocation:")
    print(f"  Cash:   {weights[0]:.1%}")
    for i, sym in enumerate(symbols):
        print(f"  {sym}: {weights[i+1]:.1%}")

if __name__ == "__main__":
    main()
