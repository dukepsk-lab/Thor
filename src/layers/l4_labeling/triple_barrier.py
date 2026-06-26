import pandas as pd
import numpy as np

def apply_triple_barrier(df: pd.DataFrame, atr_multiplier_tp: float = 2.0, atr_multiplier_sl: float = 2.0, vertical_bars: int = 20) -> pd.DataFrame:
    """
    Apply Triple-Barrier Labeling with ATR-scaled barriers.
    
    Args:
        df: DataFrame with 'close', 'high', 'low', 'time', and pre-calculated 'atr'.
        atr_multiplier_tp: Multiplier for Take Profit (Upper barrier).
        atr_multiplier_sl: Multiplier for Stop Loss (Lower barrier).
        vertical_bars: Timeout barrier (N bars).
        
    Returns:
        DataFrame with barrier hit times and labels (1: TP, -1: SL, 0: Timeout).
    """
    events = pd.DataFrame(index=df.index)
    events['t1'] = df.index.to_series().shift(-vertical_bars) # Vertical barrier
    
    # Calculate upper and lower barriers dynamically
    events['trgt_upper'] = df['close'] + df['atr'] * atr_multiplier_tp
    events['trgt_lower'] = df['close'] - df['atr'] * atr_multiplier_sl
    
    labels = []
    hit_times = []
    
    # Iterate through each bar to find the first barrier hit
    for i in range(len(df)):
        start_time = df.index[i]
        end_time = events['t1'].iloc[i]
        
        if pd.isna(end_time):
            labels.append(np.nan)
            hit_times.append(pd.NaT)
            continue
            
        # Path of prices from t to t1
        path = df.iloc[i:i+vertical_bars+1]
        
        upper = events['trgt_upper'].iloc[i]
        lower = events['trgt_lower'].iloc[i]
        
        hit_upper = path[path['high'] >= upper].index.min()
        hit_lower = path[path['low'] <= lower].index.min()
        
        if pd.isna(hit_upper) and pd.isna(hit_lower):
            labels.append(0) # Timeout
            hit_times.append(end_time)
        elif pd.isna(hit_lower):
            labels.append(1) # Hit TP
            hit_times.append(hit_upper)
        elif pd.isna(hit_upper):
            labels.append(-1) # Hit SL
            hit_times.append(hit_lower)
        else:
            # Hit both, which hit first?
            if hit_upper < hit_lower:
                labels.append(1)
                hit_times.append(hit_upper)
            elif hit_lower < hit_upper:
                labels.append(-1)
                hit_times.append(hit_lower)
            else:
                # Same bar hit, ambiguity - usually assume stop loss hit first for safety
                labels.append(-1)
                hit_times.append(hit_lower)
                
    events['label'] = labels
    events['hit_time'] = hit_times
    
    return events
