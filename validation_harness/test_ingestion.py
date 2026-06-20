import sys
import os
import datetime
import MetaTrader5 as mt5

# Add the project root to the path so we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.layers.l0_ingestion.mt5_client import mt5_client

def test_ingestion():
    print("Testing MT5 Data Ingestion...")
    
    if not mt5_client.connect():
        print("Failed to connect to MT5. Ensure the terminal is running and credentials in .env are correct.")
        return
        
    symbol = "EURUSD"
    timeframe = mt5.TIMEFRAME_H4
    
    # Let's fetch data for the last 30 days
    end_time = datetime.datetime.now()
    start_time = end_time - datetime.timedelta(days=30)
    
    print(f"Fetching OHLCV for {symbol} from {start_time} to {end_time}...")
    df_ohlcv = mt5_client.fetch_ohlcv(symbol, timeframe, start_time, end_time)
    
    if df_ohlcv is not None and not df_ohlcv.empty:
        print("OHLCV Data fetched successfully.")
        print(df_ohlcv.head())
        print(f"Shape: {df_ohlcv.shape}")
        
        # Validate schema
        expected_cols = {'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume'}
        if expected_cols.issubset(set(df_ohlcv.columns)):
            print("OHLCV Schema validated.")
        else:
            print(f"Schema validation failed. Missing columns. Found: {df_ohlcv.columns}")
    else:
        print("Failed to fetch OHLCV data.")
        
    # Fetch ticks for the last 1 hour
    start_tick_time = end_time - datetime.timedelta(hours=1)
    print(f"\nFetching Ticks for {symbol} from {start_tick_time} to {end_time}...")
    df_ticks = mt5_client.fetch_ticks(symbol, start_tick_time, end_time)
    
    if df_ticks is not None and not df_ticks.empty:
        print("Tick Data fetched successfully.")
        print(df_ticks.head())
        print(f"Shape: {df_ticks.shape}")
        
        expected_tick_cols = {'bid', 'ask', 'last', 'volume', 'time_msc', 'flags', 'volume_real'}
        if expected_tick_cols.issubset(set(df_ticks.columns)):
            print("Tick Schema validated.")
        else:
            print(f"Tick Schema validation failed. Found: {df_ticks.columns}")
    else:
        print("Failed to fetch Tick data.")
        
    mt5_client.disconnect()
    print("Testing complete.")

if __name__ == "__main__":
    test_ingestion()
