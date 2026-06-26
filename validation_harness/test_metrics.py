import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l8_monitoring.validation.metrics import evaluate_strategy

def test_metrics():
    print("Testing Cost-Adjusted Metric Reporting...")
    
    # Create dummy returns for 1000 H4 bars
    np.random.seed(123)
    dates = pd.date_range(start="2023-01-01", periods=1000, freq='4h')
    returns = pd.Series(np.random.normal(0.0001, 0.002, 1000), index=dates)
    
    # Create a dummy strategy signal that has a slight edge
    # Let's make it correct 55% of the time
    signals = []
    for ret in returns:
        if np.random.rand() < 0.55:
            signals.append(1 if ret > 0 else -1)
        else:
            signals.append(-1 if ret > 0 else 1)
            
    signals = pd.Series(signals, index=dates)
    
    # Evaluate
    spread_bps = 1.0 # 1 pip spread
    comm_bps = 0.5   # 0.5 pip commission eq
    
    print(f"Evaluating strategy with {spread_bps} bps spread and {comm_bps} bps commission...")
    metrics = evaluate_strategy(signals, returns, spread_bps=spread_bps, comm_bps=comm_bps)
    
    print("\n--- Evaluation Report ---")
    df_metrics = pd.DataFrame(metrics).T
    print(df_metrics.to_string(float_format=lambda x: f"{x:.4f}"))
    
    print("\nValidation passed if Strat_Net exists and is compared against BnH and Random_Net.")

if __name__ == "__main__":
    test_metrics()
