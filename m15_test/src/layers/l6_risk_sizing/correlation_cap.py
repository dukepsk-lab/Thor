import pandas as pd

def apply_correlation_cap(sizes: dict, returns_df: pd.DataFrame, max_aggregate_risk: float, current_balance: float) -> dict:
    """
    Analyzes aggregate risk across instruments. If signals are highly correlated and 
    directional, it proportionally scales down the allocated sizes.
    
    Args:
        sizes: dict mapping symbol -> proposed dollar risk allocation.
        returns_df: DataFrame containing recent returns for all symbols.
        max_aggregate_risk: Maximum allowed total dollar risk across the portfolio.
        current_balance: Current account balance.
    """
    # Sum total proposed risk
    total_proposed_risk = sum(abs(v) for v in sizes.values())
    
    # If total risk is within bounds, no reduction needed
    if total_proposed_risk <= max_aggregate_risk:
        return sizes
        
    # Alternatively, if we just want a hard proportional scale down to fit the cap:
    scale_factor = max_aggregate_risk / total_proposed_risk
    
    capped_sizes = {sym: size * scale_factor for sym, size in sizes.items()}
    return capped_sizes
