import pandas as pd
from typing import List, Dict
import MetaTrader5 as mt5
from datetime import datetime
from .mt5_client import mt5_client

class MultiAssetClient:
    def __init__(self):
        pass
        
    def fetch_universe(self, symbols: List[str], timeframe: int, start: datetime, end: datetime) -> Dict[str, pd.DataFrame]:
        """
        Fetches data for multiple symbols and ensures they are perfectly aligned in time.
        """
        if not mt5_client.connect():
            raise ConnectionError("Cannot connect to MT5 for Multi-Asset fetch")
            
        data_dict = {}
        for sym in symbols:
            df = mt5_client.fetch_ohlcv(sym, timeframe, start, end)
            if df is not None and not df.empty:
                df.set_index('time', inplace=True)
                data_dict[sym] = df
                
        # Find common index (intersection)
        if not data_dict:
            return {}
            
        common_index = data_dict[symbols[0]].index
        for sym in symbols[1:]:
            if sym in data_dict:
                common_index = common_index.intersection(data_dict[sym].index)
                
        # Re-index all to the common timeframe to avoid leakage and NaNs
        aligned_dict = {}
        for sym in data_dict:
            aligned_dict[sym] = data_dict[sym].loc[common_index].copy()
            
        return aligned_dict

multi_asset_client = MultiAssetClient()
