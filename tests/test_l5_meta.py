import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l5_meta_model.meta_learner import MetaLearner

def test_l5_meta():
    print("Testing L5 Meta-Learner (Calibration)...")
    
    dates = pd.date_range(start='2023-01-01', periods=200, freq='4h')
    
    # Dummy Features
    primary_signals = pd.Series(np.random.choice([-1, 1], size=200), index=dates)
    volatility = pd.Series(np.random.uniform(0.001, 0.01, size=200), index=dates)
    regimes = pd.Series(np.random.choice(['trend', 'range'], size=200), index=dates)
    
    # Target: 1 if signal was right, 0 if wrong
    actual_outcomes = pd.Series(np.random.choice([0, 1], size=200, p=[0.4, 0.6]), index=dates)
    
    learner = MetaLearner()
    learner.fit(primary_signals, regimes, volatility, actual_outcomes)
    
    probas = learner.predict_trust_probability(primary_signals, regimes, volatility)
    
    print("\nCalibrated Probabilities Head:")
    print(probas.head())
    
    # Assertions
    assert len(probas) == 200
    assert probas.min() >= 0.0, "Probabilities cannot be negative."
    assert probas.max() <= 1.0, "Probabilities cannot exceed 1.0."
    
    print("\nL5 Meta-Learner Test Passed.")

if __name__ == "__main__":
    test_l5_meta()
