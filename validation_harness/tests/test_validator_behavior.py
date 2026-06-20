import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from validation_harness.ingestion import validate_ohlcv_schema, validate_tick_schema

def test_validator_null_dataframe():
    """Verify how validator handles None or empty DataFrame"""
    with pytest.raises(ValueError, match="DataFrame is None"):
        validate_ohlcv_schema(None)
    with pytest.raises(ValueError, match="DataFrame is None"):
        validate_tick_schema(None)

    # Empty DataFrame should return False
    assert validate_ohlcv_schema(pd.DataFrame()) is False
    assert validate_tick_schema(pd.DataFrame()) is False

def test_validator_nan_inputs():
    """Verify how validator handles NaN (null) values inside columns"""
    df = pd.DataFrame({
        'open': [1.1, np.nan, 1.3],
        'high': [1.2, 1.25, np.nan],
        'low': [1.0, np.nan, 1.2],
        'close': [np.nan, 1.22, 1.28],
        'tick_volume': [100, np.nan, 300],
        'spread': [10, 15, np.nan],
        'real_volume': [0, np.nan, 0]
    }, index=pd.date_range("2026-06-19 12:00:00", periods=3, freq="15min"))

    assert validate_ohlcv_schema(df) is True
    # Verify that NaNs in prices were filled via ffill/bfill
    assert not df['open'].isna().any()
    assert df.loc[df.index[1], 'open'] == 1.1  # ffilled from index 0
    assert df.loc[df.index[2], 'high'] == 1.25  # ffilled from index 1
    # close was backfilled from 1.22 to index 0, but clamped to high (1.2) because high was 1.2
    assert df.loc[df.index[0], 'close'] == 1.2

    # Verify that NaNs in volumes/spreads were filled with 0 (no ffill/bfill)
    assert df.loc[df.index[1], 'tick_volume'] == 0
    assert df.loc[df.index[2], 'spread'] == 0
    assert df.loc[df.index[1], 'real_volume'] == 0

def test_validator_negative_values():
    """Verify how validator handles negative values inside columns"""
    df = pd.DataFrame({
        'open': [-1.1, 1.2],
        'high': [1.2, -1.25],
        'low': [-1.0, 1.1],
        'close': [1.15, -1.22],
        'tick_volume': [-100, 200],  # Negative volumes
        'spread': [10, -15],         # Negative spread
        'real_volume': [-50, 0]      # Negative real volume
    }, index=pd.date_range("2026-06-19 12:00:00", periods=2, freq="15min"))

    assert validate_ohlcv_schema(df) is True
    
    # Prices should be converted to positive using abs()
    assert (df['open'] > 0).all()
    assert (df['high'] > 0).all()
    assert (df['low'] > 0).all()
    assert (df['close'] > 0).all()
    
    # Note: validation fixes negative volumes/spreads in validate_ohlcv_schema!
    assert df.loc[df.index[0], 'tick_volume'] == 0
    assert df.loc[df.index[1], 'spread'] == 0
    assert df.loc[df.index[0], 'real_volume'] == 0

def test_validator_future_timestamps():
    """Verify how validator handles future timestamps"""
    future_time = datetime.now() + timedelta(days=365)
    df = pd.DataFrame({
        'open': [1.1],
        'high': [1.2],
        'low': [1.0],
        'close': [1.15],
        'tick_volume': [100],
        'spread': [10],
        'real_volume': [0]
    }, index=[future_time])

    # Should drop the future timestamp, making df empty and returning False
    assert validate_ohlcv_schema(df) is False
    assert len(df) == 0

def test_tick_validator_nan_inputs():
    """Verify how tick validator handles NaN (null) values inside columns"""
    df = pd.DataFrame({
        'bid': [1.1, np.nan, 1.3],
        'ask': [1.11, 1.26, np.nan],
        'last': [np.nan, 1.25, 1.28],
        'volume': [1, np.nan, 3],
        'time_msc': [1000, 2000, np.nan],
        'flags': [0, np.nan, 0],
        'volume_real': [1.0, np.nan, 3.0]
    }, index=pd.date_range("2026-06-19 12:00:00", periods=3, freq="15min"))

    assert validate_tick_schema(df) is True
    # Verify that NaNs in prices were filled via ffill/bfill
    assert not df['bid'].isna().any()
    assert df.loc[df.index[1], 'bid'] == 1.1
    # For index 2: bid was 1.3, ask was np.nan -> ffilled to 1.26.
    # Since bid (1.3) > ask (1.26), they are swapped.
    # So bid becomes 1.26, ask becomes 1.3.
    assert df.loc[df.index[2], 'bid'] == 1.26
    assert df.loc[df.index[2], 'ask'] == 1.3
    assert df.loc[df.index[0], 'last'] == 1.25

    # Verify that NaNs in volumes/timestamps/flags were ffilled
    assert df.loc[df.index[1], 'volume'] == 1
    assert df.loc[df.index[2], 'time_msc'] == 2000  # ffilled from index 1
    assert df.loc[df.index[1], 'flags'] == 0
    assert df.loc[df.index[1], 'volume_real'] == 1.0

def test_tick_validator_negative_values():
    """Verify how tick validator handles negative values"""
    df = pd.DataFrame({
        'bid': [-1.1, 1.2],
        'ask': [1.11, -1.21],
        'last': [-1.105, 1.205],
        'volume': [-1, 2],
        'time_msc': [1000, -2000],
        'flags': [-5, 0],
        'volume_real': [-1.0, 2.0]
    }, index=pd.date_range("2026-06-19 12:00:00", periods=2, freq="15min"))

    assert validate_tick_schema(df) is True
    
    # Prices should be converted to positive using abs()
    assert (df['bid'] > 0).all()
    assert (df['ask'] > 0).all()
    assert (df['last'] > 0).all()
    
    # Volumes and volume_real are converted / clamped to 0
    assert df.loc[df.index[0], 'volume'] == 0
    assert df.loc[df.index[1], 'time_msc'] == -2000
    assert df.loc[df.index[0], 'flags'] == -5
    assert df.loc[df.index[0], 'volume_real'] == 0.0
