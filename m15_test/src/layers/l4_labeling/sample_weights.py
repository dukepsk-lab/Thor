import pandas as pd
import numpy as np

def calculate_sample_uniqueness(events: pd.DataFrame, close_index: pd.Index) -> pd.Series:
    """
    Calculate sample uniqueness based on overlapping labels.
    
    Args:
        events: DataFrame with 'hit_time' (when the barrier was hit). Index is trade start time.
        close_index: The index of the full price series.
        
    Returns:
        Series of uniqueness values [0, 1] for each label.
    """
    # Create a binary matrix where rows are time bars and cols are events
    # 1 if event i spans over bar t
    
    out = pd.Series(0.0, index=events.index)
    
    for i, start_time in enumerate(events.index):
        end_time = events['hit_time'].iloc[i]
        if pd.isna(end_time):
            continue
            
        # Number of concurrent active labels during this label's lifetime
        concurrent_labels = ((events.index <= start_time) & (events['hit_time'] > start_time)).sum()
        
        # Simple uniqueness approximation
        out.loc[start_time] = 1.0 / max(1, concurrent_labels)
        
    return out

def get_sample_weights(events: pd.DataFrame, close_index: pd.Index) -> pd.Series:
    """
    Calculate sample weights by combining uniqueness and absolute returns.
    """
    uniqueness = calculate_sample_uniqueness(events, close_index)
    # Further weight by return magnitude if desired
    return uniqueness
