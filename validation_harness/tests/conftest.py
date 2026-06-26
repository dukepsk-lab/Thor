import sys
import os
import types
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

# --- MetaTrader 5 Mocking Strategy ---
class MockMetaTrader5:
    TIMEFRAME_M15 = 15
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408
    
    COPY_TICKS_ALL = 1
    COPY_TICKS_INFO = 2
    
    RES_S_OK = 1
    RES_E_FAIL = -1
    
    def __init__(self):
        self.initialize_return = True
        self.last_error_return = (1, "Success")
        self.rates_return = None
        self.ticks_return = None
        self.initialized = False
        
    def initialize(self, path=None, login=0, password="", server=""):
        if self.initialize_return:
            self.initialized = True
            return True
        return False
        
    def shutdown(self):
        self.initialized = False
        
    def last_error(self):
        return self.last_error_return
        
    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not self.initialized:
            return None
        return self.rates_return
        
    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        if not self.initialized:
            return None
        return self.ticks_return

mock_mt5_instance = MockMetaTrader5()
sys.modules['MetaTrader5'] = mock_mt5_instance





# --- Reusable Pytest Fixtures ---

@pytest.fixture
def mock_mt5():
    """
    Fixture to get access to the MT5 mock instance, allowing individual tests
    to override returned values and inspect connection state.
    """
    yield mock_mt5_instance
    # Reset mock state after each test case
    mock_mt5_instance.initialize_return = True
    mock_mt5_instance.last_error_return = (1, "Success")
    mock_mt5_instance.rates_return = None
    mock_mt5_instance.ticks_return = None
    mock_mt5_instance.initialized = False

@pytest.fixture
def sample_ohlcv_data():
    """
    Returns a standard 10-bar OHLCV DataFrame (H4 EURUSD style).
    """
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="4h")
    data = {
        "open": [1.0800, 1.0810, 1.0805, 1.0820, 1.0830, 1.0825, 1.0840, 1.0850, 1.0845, 1.0860],
        "high": [1.0815, 1.0820, 1.0825, 1.0835, 1.0845, 1.0845, 1.0855, 1.0860, 1.0865, 1.0870],
        "low":  [1.0795, 1.0800, 1.0798, 1.0810, 1.0820, 1.0820, 1.0835, 1.0840, 1.0838, 1.0850],
        "close": [1.0810, 1.0805, 1.0820, 1.0830, 1.0840, 1.0840, 1.0850, 1.0845, 1.0860, 1.0865],
        "tick_volume": [100, 120, 110, 130, 140, 125, 150, 160, 145, 170],
        "spread": [12, 10, 11, 12, 13, 11, 12, 10, 11, 12],
        "real_volume": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    }
    df = pd.DataFrame(data, index=dates)
    # Programmatic boundary enforcement to guarantee validation check compliance
    df["high"] = df[["open", "close", "low", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "high", "low"]].min(axis=1)
    df.index.name = "time"
    return df

@pytest.fixture
def sample_tick_data():
    """
    Returns a standard 10-tick DataFrame.
    """
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="s")
    data = {
        "bid": [1.0800, 1.0801, 1.0802, 1.0801, 1.0803, 1.0804, 1.0803, 1.0805, 1.0806, 1.0805],
        "ask": [1.0801, 1.0802, 1.0803, 1.0802, 1.0804, 1.0805, 1.0804, 1.0806, 1.0807, 1.0806],
        "last": [0.0]*10,
        "volume": [1.0]*10,
        "time_msc": [1672531200000 + i*1000 for i in range(10)],
        "flags": [6]*10,
        "volume_real": [1.0]*10
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "time"
    return df

@pytest.fixture
def sample_returns():
    """
    Returns a Series of mock strategy returns (normal/skewed).
    """
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=100)
    rets = np.random.normal(0.0005, 0.01, 100)
    return pd.Series(rets, index=dates)

@pytest.fixture
def sample_signals():
    """
    Returns a dict with sample y_true and y_pred Series.
    """
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=100)
    y_true = pd.Series(np.random.choice([-1, 0, 1], size=100, p=[0.4, 0.2, 0.4]), index=dates)
    y_pred = y_true.copy()
    mask = np.random.rand(100) > 0.6
    y_pred[mask] = np.random.choice([-1, 0, 1], size=mask.sum())
    return {"y_true": y_true, "y_pred": y_pred}

@pytest.fixture
def db_engine():
    """
    Returns an in-memory SQLite database engine for testing schema insertions.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE ohlcv_data (
                time TIMESTAMP NOT NULL,
                symbol VARCHAR(16) NOT NULL,
                timeframe VARCHAR(8) NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                tick_volume BIGINT NOT NULL,
                spread INT NOT NULL,
                real_volume BIGINT NOT NULL,
                PRIMARY KEY (time, symbol, timeframe)
            );
        """))
        conn.execute(text("""
            CREATE TABLE tick_data (
                time TIMESTAMP NOT NULL,
                symbol VARCHAR(16) NOT NULL,
                bid DOUBLE PRECISION NOT NULL,
                ask DOUBLE PRECISION NOT NULL,
                last DOUBLE PRECISION NOT NULL,
                volume DOUBLE PRECISION NOT NULL,
                time_msc BIGINT NOT NULL,
                flags BIGINT NOT NULL,
                volume_real DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (time, symbol)
            );
        """))
    return engine
