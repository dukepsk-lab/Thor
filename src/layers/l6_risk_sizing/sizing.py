import pandas as pd
import numpy as np

def calculate_base_size(account_balance: float, risk_per_trade_pct: float, atr: float, atr_multiplier: float = 2.0, point_value: float = 1.0) -> float:
    """
    Calculate the base position size maintaining constant dollar risk.
    """
    risk_dollar = account_balance * risk_per_trade_pct
    stop_distance = atr * atr_multiplier
    
    if stop_distance <= 0:
        return 0.0
        
    # Position size = Risk_Dollar / (Stop_Distance * Point_Value)
    size = risk_dollar / (stop_distance * point_value)
    return size

def apply_confidence_scaling(base_size: float, p_correct: float, win_loss_ratio: float = 1.5, kelly_fraction: float = 0.5, threshold: float = 0.5) -> float:
    """
    Scale the base size using a fractional Kelly criterion based on the meta-model's probability.
    Blocks the trade if probability is below the defined threshold.
    """
    if p_correct < threshold:
        return 0.0
        
    # Kelly Formula: f = P - ( (1-P) / WLR )
    kelly_f = p_correct - ((1.0 - p_correct) / win_loss_ratio)
    
    if kelly_f <= 0:
        return 0.0
        
    # Apply fractional kelly and cap it
    scaled_f = kelly_f * kelly_fraction
    capped_f = min(scaled_f, 1.0) # Never bet more than the base risk block
    
    return base_size * capped_f
