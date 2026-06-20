import time
import pandas as pd
import numpy as np
from validation_harness.cpcv import CPCVSplitter

def run_test(size, n_splits, k):
    dates = pd.date_range("2020-01-01", periods=size, freq="h")
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=n_splits, n_test_splits=k)
    
    start = time.time()
    splits = splitter.split(df)
    elapsed = time.time() - start
    return elapsed, len(splits)

def stress_test_cpcv():
    print("CPCV Performance Stress Test")
    print("-" * 50)
    
    configs = [
        (10, 2),
        (12, 3),
        (15, 3)
    ]
    
    sizes = [1000, 3000, 5000, 10000]
    
    for n, k in configs:
        print(f"\nConfiguration: N={n}, K={k}")
        print("M      | Time (s) | Splits")
        print("-" * 35)
        for size in sizes:
            try:
                t, num_splits = run_test(size, n, k)
                print(f"{size:5d} | {t:7.4f}s | {num_splits:5d}")
            except Exception as e:
                print(f"{size:5d} | Error: {e}")

if __name__ == "__main__":
    stress_test_cpcv()
