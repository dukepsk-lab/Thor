import sys
import os
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
from datetime import datetime

# Mimic conftest.py
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

from src.layers.l0_ingestion.mt5_client import MT5Client

rates_data = np.array([
    (1672531200, 1.0850, 1.0900, 1.0820, 1.0880, 500, 15, 0)
], dtype=[
    ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'), 
    ('close', 'f8'), ('tick_volume', 'i8'), ('spread', 'i4'), ('real_volume', 'u8')
])
mock_mt5_instance.rates_return = rates_data

client = MT5Client()
client.connect()
print("hasattr(mock_mt5_instance, 'terminal_info'):", hasattr(mock_mt5_instance, 'terminal_info'))
try:
    df = client.fetch_ohlcv("EURUSD", mock_mt5_instance.TIMEFRAME_H4, datetime(2023, 1, 1), datetime(2023, 1, 2))
    print("df is:", df)
except Exception as e:
    import traceback
    traceback.print_exc()
