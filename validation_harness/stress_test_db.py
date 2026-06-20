import time
import tracemalloc
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
import src.layers.l0_ingestion.db_sync as db_sync
from validation_harness.ingestion import sync_ohlcv_to_db, sync_ticks_to_db

def generate_ohlcv_data(size):
    dates = pd.date_range("2026-01-01", periods=size, freq="min")
    df = pd.DataFrame({
        'open': np.random.uniform(1.0, 1.2, size),
        'high': np.random.uniform(1.2, 1.3, size),
        'low': np.random.uniform(0.9, 1.0, size),
        'close': np.random.uniform(1.0, 1.2, size),
        'tick_volume': np.random.randint(100, 1000, size),
        'spread': np.random.randint(5, 20, size),
        'real_volume': np.random.randint(100, 1000, size)
    }, index=dates)
    return df

def generate_tick_data(size):
    dates = pd.date_range("2026-01-01", periods=size, freq="s")
    df = pd.DataFrame({
        'bid': np.random.uniform(1.0800, 1.0900, size),
        'ask': np.random.uniform(1.0901, 1.1000, size),
        'last': np.random.uniform(1.0850, 1.0950, size),
        'volume': np.random.randint(1, 10, size),
        'time_msc': [1700000000000 + i * 1000 for i in range(size)],
        'flags': np.random.randint(0, 10, size),
        'volume_real': np.random.uniform(0.1, 5.0, size)
    }, index=dates)
    return df

def run_db_stress():
    print("Database Ingestion & Sync Stress Test")
    print("-" * 50)
    
    sizes = [1000, 10000, 50000, 100000]
    
    for size in sizes:
        print(f"\n--- Testing Bulk Size: {size} records ---")
        
        # Reset engine to a clean in-memory SQLite database
        test_engine = create_engine("sqlite:///:memory:")
        db_sync.engine = test_engine
        
        # 1. OHLCV Sync
        df_ohlcv = generate_ohlcv_data(size)
        
        tracemalloc.start()
        start = time.time()
        # Using db_sync implementation directly
        db_sync.sync_ohlcv_to_timescale(df_ohlcv, "EURUSD", "M1")
        elapsed = time.time() - start
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        print(f"OHLCV Ingest Time: {elapsed:.4f}s | Peak Memory: {peak / 10**6:.2f} MB")
        
        # Test upsert performance (insert same data again to trigger ON CONFLICT)
        tracemalloc.start()
        start = time.time()
        db_sync.sync_ohlcv_to_timescale(df_ohlcv, "EURUSD", "M1")
        elapsed_conflict = time.time() - start
        current_c, peak_c = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"OHLCV Upsert (Conflict) Time: {elapsed_conflict:.4f}s | Peak Memory: {peak_c / 10**6:.2f} MB")

        # 2. Tick Sync
        df_ticks = generate_tick_data(size)
        
        tracemalloc.start()
        start = time.time()
        db_sync.sync_ticks_to_timescale(df_ticks, "EURUSD")
        elapsed = time.time() - start
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        print(f"Tick Ingest Time: {elapsed:.4f}s | Peak Memory: {peak / 10**6:.2f} MB")
        
        # Test insert ignore performance
        tracemalloc.start()
        start = time.time()
        db_sync.sync_ticks_to_timescale(df_ticks, "EURUSD")
        elapsed_conflict = time.time() - start
        current_c, peak_c = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"Tick Conflict Ignore Time: {elapsed_conflict:.4f}s | Peak Memory: {peak_c / 10**6:.2f} MB")

if __name__ == "__main__":
    run_db_stress()
