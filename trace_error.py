import sys
import traceback
from datetime import datetime

# 1. Setup mock
from validation_harness.tests.conftest import mock_mt5_instance
sys.modules['MetaTrader5'] = mock_mt5_instance

# 2. Import mt5_client
import src.layers.l0_ingestion.mt5_client as mt5_client_mod
from src.layers.l0_ingestion.mt5_client import mt5_client

print("mt5_client.mt5 is:", mt5_client_mod.mt5)
print("hasattr(mt5_client.mt5, 'terminal_info'):", hasattr(mt5_client_mod.mt5, 'terminal_info'))

# Try to call fetch_ohlcv and catch traceback
try:
    mock_mt5_instance.rates_return = []
    mt5_client.fetch_ohlcv("EURUSD", 16388, datetime(2023, 1, 1), datetime(2023, 1, 2))
except Exception:
    traceback.print_exc()
