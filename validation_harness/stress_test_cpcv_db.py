import time
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

# Setup python path to import packages correctly
sys.path.append(os.getcwd())

from validation_harness.cpcv import CPCVSplitter, CombinatorialPurgedKFold
import src.layers.l0_ingestion.db_sync as db_sync

def test_cpcv_stress():
    print("\n" + "="*80)
    print(" CPCV PERFORMANCE & CORRECTNESS STRESS TEST")
    print("="*80)
    
    # Configurations to test
    configs = [
        # (N, K)
        (6, 2),
        (10, 2),
        (12, 3),
        (12, 4),
        (15, 3),
        (15, 4),
        (20, 2)
    ]
    
    # Dataset sizes (M)
    sizes = [1000, 3000, 5000, 10000, 30000]
    
    # Overlap scenarios:
    # 1. Instantaneous (no overlap)
    # 2. Medium overlap (10 bars event duration, 4 bars purging, 10 bars embargo)
    # 3. High overlap (100 bars event duration, 10 bars purging, 50 bars embargo)
    overlap_scenarios = [
        {"name": "Instantaneous", "duration": 0, "purging": 0, "embargo": 0},
        {"name": "Medium Overlap", "duration": 10, "purging": 4, "embargo": 10},
        {"name": "High Overlap", "duration": 100, "purging": 10, "embargo": 50}
    ]
    
    results = []
    
    for n, k in configs:
        for size in sizes:
            # We don't want to run extremely large configurations if they explode,
            # but let's test if they exceed 1.0s.
            # Combinations: 15 choose 4 is 1365 splits.
            # If M=30000, 1365 splits might take a few seconds, let's measure.
            if n == 15 and k == 4 and size > 10000:
                continue
            
            # Generate dataset
            dates = pd.date_range("2020-01-01", periods=size, freq="15min")
            df = pd.DataFrame(index=dates)
            
            for scenario in overlap_scenarios:
                dur = scenario["duration"]
                purging = pd.Timedelta(minutes=15 * scenario["purging"])
                # embargo as absolute bar counts
                embargo = scenario["embargo"]
                
                # event hit times
                if dur == 0:
                    event_times = pd.Series(dates, index=dates)
                else:
                    event_times = pd.Series(dates + pd.Timedelta(minutes=15 * dur), index=dates)
                
                cv = CombinatorialPurgedKFold(
                    n_partitions=n,
                    n_test_partitions=k,
                    purging_offset=purging,
                    embargo_offset=embargo
                )
                
                start_time = time.time()
                splits = list(cv.split(df, pred_times=event_times))
                elapsed = time.time() - start_time
                
                num_splits = len(splits)
                results.append({
                    "N": n,
                    "K": k,
                    "M": size,
                    "Scenario": scenario["name"],
                    "Splits": num_splits,
                    "Time (s)": elapsed,
                    "Pass (<1s)": elapsed < 1.0
                })
                
                # Run some basic correctness check on the first split
                if num_splits > 0:
                    train_idx, test_idx = splits[0]
                    # Check disjointness
                    assert len(np.intersect1d(train_idx, test_idx)) == 0, f"Overlap in train/test for N={n}, K={k}"
                    
    # Display results
    print(f"{'N':<3} | {'K':<3} | {'M':<6} | {'Scenario':<15} | {'Splits':<6} | {'Time (s)':<10} | {'Pass (<1.0s)':<12}")
    print("-" * 70)
    for r in results:
        pass_str = "YES" if r["Pass (<1s)"] else "NO"
        print(f"{r['N']:<3} | {r['K']:<3} | {r['M']:<6} | {r['Scenario']:<15} | {r['Splits']:<6} | {r['Time (s)']:<10.4f} | {pass_str:<12}")
        
    return results

def test_db_sync_stress():
    print("\n" + "="*80)
    print(" DATABASE SYNCHRONIZATION STRESS TEST")
    print("="*80)
    
    # Setup SQLite in-memory DB and inject into db_sync
    test_engine = create_engine("sqlite:///:memory:")
    db_sync.engine = test_engine
    
    # Initialize hypertables
    db_sync.init_hypertables(force=True)
    
    # 1. OHLCV Stress Test
    print("\nTesting OHLCV Sync performance:")
    ohlcv_sizes = [5000, 10000, 50000]
    
    for size in ohlcv_sizes:
        dates = pd.date_range("2020-01-01", periods=size, freq="15min")
        df = pd.DataFrame({
            'open': np.random.uniform(1.0, 1.2, size),
            'high': np.random.uniform(1.2, 1.3, size),
            'low': np.random.uniform(0.9, 1.0, size),
            'close': np.random.uniform(1.0, 1.2, size),
            'tick_volume': np.random.randint(10, 1000, size),
            'spread': np.random.randint(1, 20, size),
            'real_volume': np.random.randint(0, 100, size)
        }, index=dates)
        
        # Initial sync
        start_time = time.time()
        db_sync.sync_ohlcv_to_timescale(df, "EURUSD", "M15")
        elapsed_init = time.time() - start_time
        
        # Verify row count in database
        with test_engine.connect() as conn:
            cnt = conn.execute(text("SELECT COUNT(*) FROM ohlcv_data")).scalar()
            
        # Overwrite sync (with ON CONFLICT upsert)
        df_new = df.copy()
        df_new['close'] = df_new['close'] + 0.0001 # Modify close prices to force updates
        
        start_time = time.time()
        db_sync.sync_ohlcv_to_timescale(df_new, "EURUSD", "M15")
        elapsed_upsert = time.time() - start_time
        
        print(f"  M = {size:5d} | Init Sync: {elapsed_init:6.4f}s | Upsert Sync: {elapsed_upsert:6.4f}s | DB Count: {cnt}")
        
        # Clean table for next size
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM ohlcv_data;"))
            
    # 2. Tick Stress Test
    print("\nTesting Ticks Sync performance:")
    tick_sizes = [5000, 10000, 50000, 100000]
    
    for size in tick_sizes:
        # Ticks often have sub-second timestamps
        dates = pd.date_range("2020-01-01", periods=size, freq="100ms")
        time_mscs = [int(t.timestamp() * 1000) for t in dates]
        df = pd.DataFrame({
            'bid': np.random.uniform(1.0850, 1.0900, size),
            'ask': np.random.uniform(1.0900, 1.0950, size),
            'last': np.random.uniform(1.0850, 1.0950, size),
            'volume': np.random.randint(1, 10, size),
            'time_msc': time_mscs,
            'flags': np.random.randint(0, 10, size),
            'volume_real': np.random.uniform(0.1, 5.0, size)
        }, index=dates)
        
        # Initial sync (nothing in DB)
        start_time = time.time()
        db_sync.sync_ticks_to_timescale(df, "EURUSD")
        elapsed_init = time.time() - start_time
        
        # Verify row count in database
        with test_engine.connect() as conn:
            cnt = conn.execute(text("SELECT COUNT(*) FROM tick_data")).scalar()
            
        # Overlap sync with some old and some new ticks
        # Generate 1000 new ticks at the end of the existing ticks
        new_dates = pd.date_range(dates[-1] + pd.Timedelta(milliseconds=100), periods=1000, freq="100ms")
        new_time_mscs = [int(t.timestamp() * 1000) for t in new_dates]
        df_new_ticks = pd.DataFrame({
            'bid': np.random.uniform(1.0850, 1.0900, 1000),
            'ask': np.random.uniform(1.0900, 1.0950, 1000),
            'last': np.random.uniform(1.0850, 1.0950, 1000),
            'volume': np.random.randint(1, 10, 1000),
            'time_msc': new_time_mscs,
            'flags': np.random.randint(0, 10, 1000),
            'volume_real': np.random.uniform(0.1, 5.0, 1000)
        }, index=new_dates)
        
        # Combine last half of old ticks + new ticks to simulate overlap ingestion
        df_combined = pd.concat([df.iloc[size//2:], df_new_ticks])
        
        start_time = time.time()
        db_sync.sync_ticks_to_timescale(df_combined, "EURUSD")
        elapsed_overlap = time.time() - start_time
        
        with test_engine.connect() as conn:
            final_cnt = conn.execute(text("SELECT COUNT(*) FROM tick_data")).scalar()
            
        print(f"  M = {size:6d} | Init Sync: {elapsed_init:6.4f}s | Overlap Sync (filtered {size//2} dup, added 1000 new): {elapsed_overlap:6.4f}s | Final DB Count: {final_cnt}")
        
        # Clean table for next size
        with test_engine.begin() as conn:
            conn.execute(text("DELETE FROM tick_data;"))

if __name__ == "__main__":
    cpcv_results = test_cpcv_stress()
    test_db_sync_stress()
