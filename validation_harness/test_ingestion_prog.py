import sys
from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import pytest
from sqlalchemy import create_engine, text

# 1. Setup Mock MT5 before importing modules that use it
mock_mt5 = MagicMock()
mock_mt5.COPY_TICKS_ALL = 1
mock_mt5.TIMEFRAME_M15 = 15
mock_mt5.TIMEFRAME_H4 = 16388

class MockTerminalInfo:
    def __init__(self, connected=True):
        self.connected = connected

mock_mt5.terminal_info.return_value = MockTerminalInfo()
mock_mt5.initialize.return_value = True
mock_mt5.last_error.return_value = 1  # RES_S_OK

# Apply mock to the system modules so any import gets the mock
sys.modules['MetaTrader5'] = mock_mt5

# Overwrite in mt5_client module
import src.layers.l0_ingestion.mt5_client as mt5_client_mod
mt5_client_mod.mt5 = mock_mt5

# Get the actual mt5_client class instance
from src.layers.l0_ingestion.mt5_client import mt5_client

# 2. Setup SQLite database engine override for DB sync tests
import src.layers.l0_ingestion.db_sync as db_sync
sqlite_engine = create_engine("sqlite:///:memory:")
db_sync.engine = sqlite_engine

# Import ingestion functions now that modules are mocked/overridden
from validation_harness.ingestion import (
    validate_ohlcv_schema,
    validate_tick_schema,
    fetch_historical_ohlcv,
    fetch_historical_ticks,
    get_timeframe_str
)
from src.core.config import settings
from src.layers.l0_ingestion.db_sync import init_hypertables, sync_ohlcv_to_timescale, sync_ticks_to_timescale

# Sample numpy data that MT5 copy functions would return
sample_rates = np.array([
    (1700000000, 1.1000, 1.1050, 1.0950, 1.1010, 100, 10, 0),
    (1700000060, 1.1010, 1.1060, 1.1000, 1.1020, 150, 12, 0),
], dtype=[
    ('time', 'i8'),
    ('open', 'f8'),
    ('high', 'f8'),
    ('low', 'f8'),
    ('close', 'f8'),
    ('tick_volume', 'i8'),
    ('spread', 'i4'),
    ('real_volume', 'i8')
])

sample_ticks = np.array([
    (1700000000, 1.1000, 1.1005, 1.1002, 1, 1700000000000, 0, 0.0),
    (1700000060, 1.1002, 1.1008, 1.1005, 2, 1700000060000, 0, 0.0),
], dtype=[
    ('time', 'i8'),
    ('bid', 'f8'),
    ('ask', 'f8'),
    ('last', 'f8'),
    ('volume', 'i8'),
    ('time_msc', 'i8'),
    ('flags', 'i4'),
    ('volume_real', 'f8')
])

def test_validate_ohlcv_schema():
    # Valid schema
    df = pd.DataFrame({
        'open': [1.1, 1.2],
        'high': [1.15, 1.25],
        'low': [1.05, 1.15],
        'close': [1.12, 1.22],
        'tick_volume': [100, 200],
        'spread': [10, 15],
        'real_volume': [0, 0]
    }, index=pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 12:15:00']))
    assert validate_ohlcv_schema(df) is True
    
    # Missing columns (should add them)
    df_missing = pd.DataFrame({
        'open': [1.1, 1.2],
        'high': [1.15, 1.25],
        'low': [1.05, 1.15],
        'close': [1.12, 1.22]
    }, index=pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 12:15:00']))
    assert validate_ohlcv_schema(df_missing) is True
    assert 'tick_volume' in df_missing.columns
    assert 'real_volume' in df_missing.columns
    assert (df_missing['tick_volume'] == 0).all()
    
    # Swapped high/low and negative prices
    df_invalid = pd.DataFrame({
        'open': [-1.1, 1.2],
        'high': [1.05, 1.25],  # high < low for first row
        'low': [1.15, 1.15],
        'close': [1.12, 1.22]
    }, index=pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 12:15:00']))
    assert validate_ohlcv_schema(df_invalid) is True
    assert (df_invalid['open'] > 0).all()
    assert (df_invalid['high'] >= df_invalid['low']).all()

def test_validate_tick_schema():
    # Valid
    df = pd.DataFrame({
        'bid': [1.1, 1.2],
        'ask': [1.11, 1.21],
        'last': [1.105, 1.205],
        'volume': [1, 2],
        'time_msc': [1000, 2000],
        'flags': [0, 0],
        'volume_real': [1.0, 2.0]
    }, index=pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 12:15:00']))
    assert validate_tick_schema(df) is True
    
    # Swapped bid/ask
    df_swapped = pd.DataFrame({
        'bid': [1.12, 1.2],
        'ask': [1.11, 1.21]
    }, index=pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 12:15:00']))
    assert validate_tick_schema(df_swapped) is True
    assert (df_swapped['bid'] <= df_swapped['ask']).all()

def test_mt5_client_reconnect():
    mock_mt5.initialize.reset_mock()
    mock_mt5.terminal_info.reset_mock()
    
    mt5_client.connected = False
    
    # Simulate success on second initialize attempt
    mock_mt5.initialize.side_effect = [False, True]
    
    success = mt5_client.connect(max_retries=3, backoff_factor=0.01)
    assert success is True
    assert mt5_client.connected is True
    assert mock_mt5.initialize.call_count == 2

def test_fetch_ohlcv_with_reconnect():
    mt5_client.connected = True
    
    # First check returns None (disconnected terminal), second returns MockTerminalInfo
    mock_mt5.terminal_info.side_effect = [None, MockTerminalInfo()]
    mock_mt5.initialize.return_value = True
    mock_mt5.copy_rates_range.return_value = sample_rates
    
    with patch('time.sleep', return_value=None):
        df = mt5_client.fetch_ohlcv("EURUSD", 15, datetime(2026, 6, 19), datetime(2026, 6, 20), max_retries=3)
        
    assert df is not None
    assert len(df) == 2
    mock_mt5.initialize.assert_called_with(
        path=settings.MT5_PATH,
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER
    )

def test_fetch_ticks_with_reconnect():
    mt5_client.connected = True
    
    mock_mt5.terminal_info.side_effect = [None, MockTerminalInfo()]
    mock_mt5.initialize.return_value = True
    mock_mt5.copy_ticks_range.return_value = sample_ticks
    
    with patch('time.sleep', return_value=None):
        df = mt5_client.fetch_ticks("EURUSD", datetime(2026, 6, 19), datetime(2026, 6, 20), max_retries=3)
        
    assert df is not None
    assert len(df) == 2

def test_db_init_and_sync():
    init_hypertables()
    
    with sqlite_engine.connect() as conn:
        res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
        table_names = [r[0] for r in res]
        assert 'ohlcv_data' in table_names
        assert 'tick_data' in table_names

def test_sync_ohlcv_upsert():
    # Insert initial data
    df1 = pd.DataFrame({
        'open': [1.1000],
        'high': [1.1050],
        'low': [1.0950],
        'close': [1.1010],
        'tick_volume': [100],
        'spread': [10],
        'real_volume': [0]
    }, index=pd.to_datetime(['2026-06-19 12:00:00']))
    
    sync_ohlcv_to_timescale(df1, "EURUSD", "M15")
    
    # Verify initial insert
    with sqlite_engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM ohlcv_data")).fetchone()
        assert row is not None
        assert row.open == 1.1000
        assert row.tick_volume == 100
        
    # Insert overlapping data with modified high, close, tick_volume to test upsert/ON CONFLICT
    df2 = pd.DataFrame({
        'open': [1.1000],
        'high': [1.1060],
        'low': [1.0950],
        'close': [1.1020],
        'tick_volume': [120],
        'spread': [10],
        'real_volume': [0]
    }, index=pd.to_datetime(['2026-06-19 12:00:00']))
    
    sync_ohlcv_to_timescale(df2, "EURUSD", "M15")
    
    # Verify upsert worked (values updated, count remains 1)
    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM ohlcv_data")).fetchall()
        assert len(rows) == 1
        assert rows[0].high == 1.1060
        assert rows[0].close == 1.1020
        assert rows[0].tick_volume == 120

def test_sync_ticks_ignore():
    df1 = pd.DataFrame({
        'bid': [1.1000],
        'ask': [1.1005],
        'last': [1.1002],
        'volume': [1],
        'time_msc': [1700000000000],
        'flags': [0],
        'volume_real': [0.0]
    }, index=pd.to_datetime(['2026-06-19 12:00:00']))
    
    sync_ticks_to_timescale(df1, "EURUSD")
    
    # Sync duplicate again (should not raise error due to INSERT OR IGNORE / ON CONFLICT DO NOTHING)
    sync_ticks_to_timescale(df1, "EURUSD")
    
    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM tick_data")).fetchall()
        assert len(rows) == 1

def test_fetch_historical_ohlcv_integration():
    mock_mt5.terminal_info.side_effect = None
    mock_mt5.terminal_info.return_value = MockTerminalInfo()
    mock_mt5.initialize.return_value = True
    mock_mt5.copy_rates_range.return_value = sample_rates
    
    with sqlite_engine.begin() as conn:
        conn.execute(text("DELETE FROM ohlcv_data;"))
        
    df = fetch_historical_ohlcv("EURUSD", 15, datetime(2026, 6, 19), datetime(2026, 6, 20))
    
    assert df is not None
    assert len(df) == 2
    
    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM ohlcv_data")).fetchall()
        assert len(rows) == 2

def test_fetch_historical_ticks_integration():
    mock_mt5.terminal_info.side_effect = None
    mock_mt5.terminal_info.return_value = MockTerminalInfo()
    mock_mt5.initialize.return_value = True
    mock_mt5.copy_ticks_range.return_value = sample_ticks
    
    with sqlite_engine.begin() as conn:
        conn.execute(text("DELETE FROM tick_data;"))
        
    df = fetch_historical_ticks("EURUSD", datetime(2026, 6, 19), datetime(2026, 6, 20))
    
    assert df is not None
    assert len(df) == 2
    
    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM tick_data")).fetchall()
        assert len(rows) == 2
