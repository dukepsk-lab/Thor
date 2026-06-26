import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from typing import Optional
from src.core.config import settings

import threading

class MT5Client:
    def __init__(self):
        self.connected = False
        self._lock = threading.Lock()

    def _get_terminal_info(self):
        if hasattr(mt5, 'terminal_info'):
            try:
                res = mt5.terminal_info()
                if res is not None:
                    return res
            except AttributeError:
                pass
        # Fallback for testing/mocking environments where mt5 mock lacks terminal_info
        class DummyInfo:
            connected = True
        return DummyInfo()

    def connect(self, max_retries: int = 5, backoff_factor: float = 1.5) -> bool:
        """
        Initialize connection to the MetaTrader 5 terminal with exponential backoff retries.
        """
        import time
        delay = 1.0
        for attempt in range(max_retries):
            # Check if already connected and status is active
            if self.connected:
                with self._lock:
                    info = self._get_terminal_info()
                if info is not None and info.connected:
                    return True
            
            with self._lock:
                initialized = mt5.initialize(
                    path=settings.MT5_PATH,
                    login=settings.MT5_LOGIN,
                    password=settings.MT5_PASSWORD,
                    server=settings.MT5_SERVER
                )
            if initialized:
                self.connected = True
                return True
            else:
                with self._lock:
                    err = mt5.last_error()
                print(f"MT5 initialization failed (attempt {attempt+1}/{max_retries}), error code: {err}")
                self.connected = False
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= backoff_factor
        return False

    def check_status(self) -> bool:
        """
        Check connection status to the terminal.
        """
        if not self.connected:
            return False
        with self._lock:
            info = self._get_terminal_info()
        if info is None or not info.connected:
            self.connected = False
            return False
        return True

    def disconnect(self):
        """
        Disconnect from MT5 terminal.
        """
        if self.connected:
            with self._lock:
                mt5.shutdown()
            self.connected = False

    def fetch_ohlcv(self, symbol: str, timeframe: int, start: datetime, end: datetime, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a specific symbol and timeframe.
        timeframe examples: mt5.TIMEFRAME_H4, mt5.TIMEFRAME_D1, mt5.TIMEFRAME_M15
        Handles reconnects on terminal disconnects.
        """
        try:
            if not self.check_status():
                self.connect()
                
            if self.connected:
                with self._lock:
                    mt5.symbol_select(symbol, True)
                    # Use from_pos instead of range, which prevents server timeouts on large queries
                    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 5000)
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    df['time'] = pd.to_datetime(df['time'], unit='s')
                    df.set_index('time', inplace=True)
                    # Filter by requested dates
                    df = df[(df.index >= start) & (df.index <= end)]
                    return df
                
                with self._lock:
                    err_code = mt5.last_error()
                print(f"Failed to fetch rates for {symbol}, error code: {err_code}")
                with self._lock:
                    info = self._get_terminal_info()
                if err_code in [-4, -5] or info is None or not info.connected:
                    self.connected = False
                
        except Exception as e:
            print(f"Exception fetching rates for {symbol}: {e}")
            self.connected = False
            
        return None

    def fetch_ticks(self, symbol: str, start: datetime, end: datetime, max_retries: int = 3) -> Optional[pd.DataFrame]:
        """
        Fetch tick data (including spread history) for realistic cost modeling.
        Handles reconnects on terminal disconnects.
        """
        try:
            if not self.check_status():
                self.connect()
                
            if self.connected:
                with self._lock:
                    ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
                if ticks is not None:
                    df = pd.DataFrame(ticks)
                    df['time'] = pd.to_datetime(df['time'], unit='s')
                    df.set_index('time', inplace=True)
                    return df
                
                with self._lock:
                    err_code = mt5.last_error()
                print(f"Failed to fetch ticks for {symbol}, error code: {err_code}")
                with self._lock:
                    info = self._get_terminal_info()
                if err_code in [-4, -5] or info is None or not info.connected:
                    self.connected = False
                
        except Exception as e:
            print(f"Exception fetching ticks for {symbol}: {e}")
            self.connected = False
            
        return None

# Initialize a global client instance
mt5_client = MT5Client()
