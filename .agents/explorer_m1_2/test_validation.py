import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add the directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from proposed_ingestion import DataSchemaValidator, SchemaValidationException

def test_validate_ohlcv():
    print("Running test_validate_ohlcv...")
    
    # Use dates that are clearly in the past relative to UTC (e.g., yesterday)
    base_time = datetime.utcnow() - timedelta(days=1)
    dates = pd.date_range(start=base_time, periods=3, freq="h")
    
    data = {
        'open': [1.1000, 1.1010, 1.1020],
        'high': [1.1050, 1.1060, 1.1070],
        'low': [1.0950, 1.0960, 1.0970],
        'close': [1.1010, 1.1020, 1.1030],
        'tick_volume': [100, 200, 300],
        'spread': [1, 2, 1]
    }
    df = pd.DataFrame(data, index=dates)
    
    df_cleaned = DataSchemaValidator.validate_ohlcv(df, "EURUSD")
    assert len(df_cleaned) == 3
    print("Pass: Valid data accepted.")

    # 2. Null price
    df_with_null = df.copy()
    df_with_null.iloc[1, 0] = np.nan # Null open price
    df_cleaned = DataSchemaValidator.validate_ohlcv(df_with_null, "EURUSD")
    assert len(df_cleaned) == 2 # 1 row dropped
    print("Pass: Null row dropped.")

    # 3. Duplicate timestamp
    df_with_dup = df.copy()
    # Add a duplicate index row
    df_with_dup = pd.concat([df_with_dup, df_with_dup.iloc[[1]]])
    df_cleaned = DataSchemaValidator.validate_ohlcv(df_with_dup, "EURUSD")
    assert len(df_cleaned) == 3 # Deduplicated to 3 rows
    print("Pass: Duplicate timestamp deduplicated.")

    # 4. Logical price violation (High < Low)
    df_with_violation = df.copy()
    df_with_violation.iloc[0, 1] = 1.0900 # High set below open/close/low
    df_cleaned = DataSchemaValidator.validate_ohlcv(df_with_violation, "EURUSD")
    assert len(df_cleaned) == 2 # 1 row dropped
    print("Pass: Logical violation row dropped.")

    # 5. Invalid price (price <= 0)
    df_with_zero = df.copy()
    df_with_zero.iloc[0, 0] = -0.5 # Negative price
    df_cleaned = DataSchemaValidator.validate_ohlcv(df_with_zero, "EURUSD")
    assert len(df_cleaned) == 2 # 1 row dropped
    print("Pass: Negative price row dropped.")

    # 6. Future timestamp
    df_with_future = df.copy()
    future_date = datetime.utcnow() + timedelta(days=1)
    df_with_future.index = [dates[0], dates[1], future_date]
    df_cleaned = DataSchemaValidator.validate_ohlcv(df_with_future, "EURUSD")
    assert len(df_cleaned) == 2 # 1 future row dropped
    print("Pass: Future timestamp row dropped.")

def test_validate_ticks():
    print("Running test_validate_ticks...")
    
    base_time = datetime.utcnow() - timedelta(days=1)
    dates = pd.date_range(start=base_time, periods=3, freq="s")
    
    # 1. Valid ticks
    data = {
        'bid': [1.1000, 1.1005, 1.1010],
        'ask': [1.1002, 1.1007, 1.1012]
    }
    df = pd.DataFrame(data, index=dates)
    
    df_cleaned = DataSchemaValidator.validate_ticks(df, "EURUSD")
    assert len(df_cleaned) == 3
    print("Pass: Valid ticks accepted.")

    # 2. Ask < Bid violation
    df_viol = df.copy()
    df_viol.iloc[1, 1] = 1.0990 # Ask < Bid
    df_cleaned = DataSchemaValidator.validate_ticks(df_viol, "EURUSD")
    assert len(df_cleaned) == 2
    print("Pass: Ask < Bid tick dropped.")

if __name__ == "__main__":
    test_validate_ohlcv()
    test_validate_ticks()
    print("All tests passed successfully!")
