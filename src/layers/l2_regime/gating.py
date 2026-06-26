import pandas as pd
import numpy as np

def calculate_gating_signals(df: pd.DataFrame, hurst_col: str = 'hurst', ker_col: str = 'ker') -> pd.Series:
    """
    Applies hard-coded rulesets using Hurst and KER to identify absolute market regimes.
    
    States:
    - 'trend': High Hurst (> 0.55) AND high KER.
    - 'range': Low Hurst (< 0.45).
    - 'neutral': Everything else.
    """
    states = pd.Series('neutral', index=df.index)
    
    if hurst_col in df.columns and ker_col in df.columns:
        # Assuming KER is normalized or we use a threshold like 0.4
        trend_mask = (df[hurst_col] > 0.55) & (df[ker_col] > 0.4)
        range_mask = (df[hurst_col] < 0.45)
        
        states[trend_mask] = 'trend'
        states[range_mask] = 'range'
        
    return states
