import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from src.layers.l0_ingestion.mt5_client import MT5Client
from validation_harness.ingestion import (
    validate_ohlcv_data,
    validate_tick_data,
    sync_ohlcv_to_db,
    sync_ticks_to_db,
    check_db_integrity
)

# TIER 1: Feature Coverage (TC_T1_01 to 07)

def test_mt5_client_init(mock_mt5):
    """TC_T1_01: MT5 Client Init success path"""
    mock_mt5.initialize_return = True
    client = MT5Client()
    assert client.connect() is True
    assert client.connected is True

def test_mt5_client_shutdown(mock_mt5):
    """TC_T1_02: MT5 Client Shutdown success path"""
    client = MT5Client()
    client.connected = True
    client.disconnect()
    assert client.connected is False

def test_standard_h4_ingestion(mock_mt5):
    """TC_T1_03: Standard H4 OHLCV Ingestion"""
    # 1. Define dummy structured array matching MT5 return type
    rates_data = np.array([
        (1672531200, 1.0850, 1.0900, 1.0820, 1.0880, 500, 15, 0)
    ], dtype=[
        ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'), 
        ('close', 'f8'), ('tick_volume', 'i8'), ('spread', 'i4'), ('real_volume', 'u8')
    ])
    mock_mt5.rates_return = rates_data
    
    client = MT5Client()
    client.connect()
    
    df = client.fetch_ohlcv("EURUSD", mock_mt5.TIMEFRAME_H4, datetime(2023, 1, 1), datetime(2023, 1, 2))
    assert df is not None
    assert len(df) == 1
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.iloc[0]['close'] == 1.0880

def test_ohlcv_db_sync(db_engine, sample_ohlcv_data):
    """TC_T1_04: OHLCV DB Sync to hypertable"""
    rows_synced = sync_ohlcv_to_db(sample_ohlcv_data, "EURUSD", "H4", db_engine)
    assert rows_synced == len(sample_ohlcv_data)
    
    integrity = check_db_integrity(db_engine)
    assert integrity["ohlcv_table_exists"] is True

def test_standard_tick_ingestion(mock_mt5):
    """TC_T1_05: Standard Tick Ingestion"""
    ticks_data = np.array([
        (1672531200, 1.0850, 1.0851, 0.0, 0.0, 1672531200000, 6, 0.0)
    ], dtype=[
        ('time', 'i8'), ('bid', 'f8'), ('ask', 'f8'), ('last', 'f8'), 
        ('volume', 'f8'), ('time_msc', 'i8'), ('flags', 'u4'), ('volume_real', 'f8')
    ])
    mock_mt5.ticks_return = ticks_data
    
    client = MT5Client()
    client.connect()
    
    df = client.fetch_ticks("GBPUSD", datetime(2023, 1, 1), datetime(2023, 1, 2))
    assert df is not None
    assert len(df) == 1
    assert list(df.columns) == ['bid', 'ask', 'last', 'volume', 'time_msc', 'flags', 'volume_real']

def test_tick_millisecond_parsing(mock_mt5):
    """TC_T1_06: Tick Millisecond Parsing accuracy"""
    ticks_data = np.array([
        (1672531200, 1.0850, 1.0851, 0.0, 0.0, 1672531200123, 6, 0.0)
    ], dtype=[
        ('time', 'i8'), ('bid', 'f8'), ('ask', 'f8'), ('last', 'f8'), 
        ('volume', 'f8'), ('time_msc', 'i8'), ('flags', 'u4'), ('volume_real', 'f8')
    ])
    mock_mt5.ticks_return = ticks_data
    
    client = MT5Client()
    client.connect()
    
    df = client.fetch_ticks("GBPUSD", datetime(2023, 1, 1), datetime(2023, 1, 2))
    assert df is not None
    assert df.iloc[0]['time_msc'] == 1672531200123

def test_tick_db_sync(db_engine, sample_tick_data):
    """TC_T1_07: Tick DB Sync to tick_data hypertable"""
    rows_synced = sync_ticks_to_db(sample_tick_data, "GBPUSD", db_engine)
    assert rows_synced == len(sample_tick_data)
    
    integrity = check_db_integrity(db_engine)
    assert integrity["tick_table_exists"] is True


# TIER 2: Boundary & Corner Cases (TC_T2_01 to 06)

def test_mt5_init_failure(mock_mt5):
    """TC_T2_01: MT5 initialization failure handling"""
    mock_mt5.initialize_return = False
    client = MT5Client()
    assert client.connect() is False
    assert client.connected is False

def test_empty_rates_return(mock_mt5):
    """TC_T2_02: Empty Rates return handling"""
    mock_mt5.rates_return = None
    client = MT5Client()
    client.connect()
    df = client.fetch_ohlcv("EURUSD", mock_mt5.TIMEFRAME_H4, datetime(2023, 1, 1), datetime(2023, 1, 2))
    assert df is None

def test_reversed_start_end_dates(mock_mt5):
    """TC_T2_03: Reversed Start/End Dates"""
    # MT5 client returns None when range is invalid or start > end
    mock_mt5.rates_return = None
    client = MT5Client()
    client.connect()
    df = client.fetch_ohlcv("EURUSD", mock_mt5.TIMEFRAME_H4, datetime(2023, 1, 2), datetime(2023, 1, 1))
    assert df is None

def test_empty_ticks_return(mock_mt5):
    """TC_T2_04: Empty Ticks return handling"""
    mock_mt5.ticks_return = None
    client = MT5Client()
    client.connect()
    df = client.fetch_ticks("GBPUSD", datetime(2023, 1, 1), datetime(2023, 1, 2))
    assert df is None

def test_weekend_holiday_query(mock_mt5):
    """TC_T2_05: Weekend/Holiday Query returns empty array"""
    # Simulates returning empty structured array instead of None
    mock_mt5.ticks_return = np.array([], dtype=[
        ('time', 'i8'), ('bid', 'f8'), ('ask', 'f8'), ('last', 'f8'), 
        ('volume', 'f8'), ('time_msc', 'i8'), ('flags', 'u4'), ('volume_real', 'f8')
    ])
    client = MT5Client()
    client.connect()
    df = client.fetch_ticks("GBPUSD", datetime(2023, 1, 7), datetime(2023, 1, 8))
    assert df is not None
    assert df.empty is True

def test_negative_spreads(sample_tick_data):
    """TC_T2_06: Negative Spreads filtration in validator"""
    # Introduce anomalous tick where bid > ask
    sample_tick_data.loc[sample_tick_data.index[0], "bid"] = 1.0900
    sample_tick_data.loc[sample_tick_data.index[0], "ask"] = 1.0800
    
    validation = validate_tick_data(sample_tick_data)
    assert validation["valid"] is False
    assert validation["invalid_spreads"] == 1


# ADDITIONAL BOUNDARY & SCHEMA VALIDATOR CASES (to reach 20 ingestion cases)

def test_ohlcv_validator_valid(sample_ohlcv_data):
    """TC_Ingest_Boundary_01: Validator succeeds on perfect OHLCV data"""
    res = validate_ohlcv_data(sample_ohlcv_data)
    assert res["valid"] is True
    assert res["missing_values"] == 0

def test_ohlcv_missing_column(sample_ohlcv_data):
    """TC_Ingest_Boundary_02: Validator fails on missing required column"""
    df_bad = sample_ohlcv_data.drop(columns=["close"])
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False
    assert "close" in res["error"]

def test_ohlcv_negative_prices(sample_ohlcv_data):
    """TC_Ingest_Boundary_03: Validator fails on negative prices"""
    df_bad = sample_ohlcv_data.copy()
    df_bad.loc[df_bad.index[0], "open"] = -1.0800
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False

def test_ohlcv_bounds_violation(sample_ohlcv_data):
    """TC_Ingest_Boundary_04: Validator fails on High < Low/Open/Close bounds"""
    df_bad = sample_ohlcv_data.copy()
    # Setting High to be lower than Open
    df_bad.loc[df_bad.index[0], "high"] = 1.0700
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False

def test_ohlcv_non_datetime_index(sample_ohlcv_data):
    """TC_Ingest_Boundary_05: Validator fails if index is not DatetimeIndex"""
    df_bad = sample_ohlcv_data.copy()
    df_bad.index = range(len(df_bad))
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False

def test_ohlcv_unsorted_index(sample_ohlcv_data):
    """TC_Ingest_Boundary_06: Validator fails if index is not sorted chronologically"""
    df_bad = sample_ohlcv_data.copy()
    # Swap first and last rows
    idx = list(df_bad.index)
    idx[0], idx[-1] = idx[-1], idx[0]
    df_bad = df_bad.reindex(idx)
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False
    assert res["is_sorted"] is False

def test_ohlcv_duplicate_timestamps(sample_ohlcv_data):
    """TC_Ingest_Boundary_07: Validator fails on duplicate timestamps"""
    df_bad = sample_ohlcv_data.copy()
    # Duplicate first timestamp
    new_idx = list(df_bad.index)
    new_idx[1] = new_idx[0]
    df_bad.index = new_idx
    res = validate_ohlcv_data(df_bad)
    assert res["valid"] is False
    assert res["duplicate_timestamps"] == 1
