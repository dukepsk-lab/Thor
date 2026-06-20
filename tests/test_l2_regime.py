import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l2_regime.hmm_detector import RegimeHMM
from src.layers.l2_regime.router import RegimeRouter

def test_l2_regime():
    print("Testing L2 Regime Router...")
    
    # Create dummy data
    dates = pd.date_range(start='2023-01-01', periods=100, freq='4h')
    df = pd.DataFrame(index=dates)
    df['return'] = np.random.normal(0, 0.01, 100)
    df['volatility'] = np.random.normal(0.01, 0.005, 100).clip(min=0.001)
    df['hurst'] = np.random.uniform(0.3, 0.7, 100)
    df['ker'] = np.random.uniform(0.1, 0.8, 100)
    
    # Instantiate HMM
    hmm = RegimeHMM(n_components=3, random_state=42)
    hmm.fit(df[['return', 'volatility']])
    
    # Instantiate Router
    router = RegimeRouter(hmm_model=hmm)
    
    # Determine Regimes
    out = router.determine_regime(df)
    
    print("\nRegime Output Head:")
    print(out.head())
    
    print("\nValue Counts of Final Regimes:")
    print(out['final_regime'].value_counts())
    
    # Assertions
    assert 'final_regime' in out.columns, "Missing final_regime column"
    assert 'hmm_state' in out.columns, "Missing hmm_state column"
    assert 'gate_state' in out.columns, "Missing gate_state column"
    
    print("\nL2 Regime Detection Test Passed.")

if __name__ == "__main__":
    test_l2_regime()
