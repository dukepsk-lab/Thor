import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.layers.l8_monitoring.validation.cpcv import PurgedKFold

def test_cpcv():
    print("Testing CPCV Implementation...")
    
    # 1. Create a dummy timeline of 1000 bars
    dates = pd.date_range(start="2023-01-01", periods=1000, freq='4h')
    df = pd.DataFrame(index=dates)
    df['close'] = np.random.randn(1000).cumsum()
    
    # 2. Create simulated events (e.g., from Triple-Barrier)
    # Let's say each trade lasts exactly 5 bars
    events = pd.DataFrame(index=dates)
    events['t1'] = dates.to_series().shift(-5).values
    
    # 3. Initialize CPCV
    n_splits = 5
    embargo_pct = 0.01 # 1% of 1000 = 10 bars
    cv = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct)
    
    # 4. Generate splits and validate no overlap
    fold = 1
    for train_idx, test_idx in cv.split(df, events):
        print(f"\nFold {fold}:")
        print(f"  Train size: {len(train_idx)}, Test size: {len(test_idx)}")
        
        # Test boundaries
        test_start_time = df.index[test_idx[0]]
        test_end_time = events['t1'].iloc[test_idx[-1]] if pd.notna(events['t1'].iloc[test_idx[-1]]) else df.index[test_idx[-1]]
        
        # Validate Purging: no train label ends after test starts (for pre-test train indices)
        pre_test_train = [i for i in train_idx if i < test_idx[0]]
        if pre_test_train:
            max_pre_test_end = events['t1'].iloc[pre_test_train].max()
            print(f"  Max pre-test train end time: {max_pre_test_end}")
            print(f"  Test start time:             {test_start_time}")
            assert max_pre_test_end <= test_start_time, "Purging Failed! Leakage detected."
            
        # Validate Embargo: no train starts before test ends (for post-test train indices)
        post_test_train = [i for i in train_idx if i > test_idx[-1]]
        if post_test_train:
            min_post_test_start = df.index[post_test_train[0]]
            print(f"  Test end time:               {test_end_time}")
            print(f"  Min post-test train start:   {min_post_test_start}")
            assert min_post_test_start > test_end_time, "Embargo Failed! Leakage detected."
            
        fold += 1
        
    print("\nCPCV Validation Passed: Splits correctly exclude embargoed and purged periods without overlap.")

if __name__ == "__main__":
    test_cpcv()
