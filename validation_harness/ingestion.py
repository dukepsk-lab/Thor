import logging
import pandas as pd
import numpy as np
from datetime import datetime
from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l0_ingestion.db_sync import sync_ohlcv_to_timescale, sync_ticks_to_timescale

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- PRE-EXISTING HARNESS FUNCTIONS ---

def validate_ohlcv_data(df: pd.DataFrame) -> dict:
    """
    Validates OHLCV DataFrame against the strict schema.
    Checks for:
    - Non-empty DataFrame
    - Presence of required columns
    - No missing values
    - Index is a DatetimeIndex
    - No duplicate timestamps
    - Index is monotonically increasing
    - Valid open, high, low, close values (open > 0, close > 0, high >= max(open, close), low <= min(open, close))
    - Non-negative volumes and spread
    """
    if df is None or df.empty:
        return {
            "valid": False,
            "error": "Empty or None DataFrame",
            "missing_values": 0,
            "duplicate_timestamps": 0,
            "is_sorted": False
        }
    
    required_cols = ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return {
            "valid": False,
            "error": f"Missing columns: {missing_cols}",
            "missing_values": 0,
            "duplicate_timestamps": 0,
            "is_sorted": False
        }
        
    missing_vals = int(df[required_cols].isna().sum().sum())
    
    if not isinstance(df.index, pd.DatetimeIndex):
        return {
            "valid": False,
            "error": "Index is not DatetimeIndex",
            "missing_values": missing_vals,
            "duplicate_timestamps": 0,
            "is_sorted": False
        }
        
    dup_times = int(df.index.duplicated().sum())
    is_sorted = bool(df.index.is_monotonic_increasing)
    
    # Value range checks
    valid_prices = bool((df["open"] > 0).all() and (df["close"] > 0).all())
    valid_boundaries = bool((df["high"] >= df[["open", "close", "low"]].max(axis=1)).all() and 
                            (df["low"] <= df[["open", "close", "high"]].min(axis=1)).all())
    valid_volumes = bool((df["tick_volume"] >= 0).all() and 
                          (df["spread"] >= 0).all() and 
                          (df["real_volume"] >= 0).all())
    
    valid = (missing_vals == 0) and (dup_times == 0) and is_sorted and valid_prices and valid_boundaries and valid_volumes
    
    return {
        "valid": bool(valid),
        "missing_values": missing_vals,
        "duplicate_timestamps": dup_times,
        "is_sorted": is_sorted
    }

def validate_tick_data(df: pd.DataFrame) -> dict:
    """
    Validates tick DataFrame against the strict schema.
    Checks for:
    - Non-empty DataFrame
    - Required columns presence
    - No missing values
    - Index is DatetimeIndex
    - No duplicate timestamps
    - Index is monotonically increasing
    - Valid bid/ask spread (ask >= bid)
    - Valid bid/ask values (> 0)
    """
    if df is None or df.empty:
        return {
            "valid": False,
            "error": "Empty or None DataFrame",
            "missing_values": 0,
            "duplicate_timestamps": 0,
            "is_sorted": False,
            "invalid_spreads": 0
        }
        
    required_cols = ["bid", "ask", "last", "volume", "time_msc", "flags", "volume_real"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        return {
            "valid": False,
            "error": f"Missing columns: {missing_cols}",
            "missing_values": 0,
            "duplicate_timestamps": 0,
            "is_sorted": False,
            "invalid_spreads": 0
        }
        
    missing_vals = int(df[required_cols].isna().sum().sum())
    
    if not isinstance(df.index, pd.DatetimeIndex):
        return {
            "valid": False,
            "error": "Index is not DatetimeIndex",
            "missing_values": missing_vals,
            "duplicate_timestamps": 0,
            "is_sorted": False,
            "invalid_spreads": 0
        }
        
    dup_times = int(df.index.duplicated().sum())
    is_sorted = bool(df.index.is_monotonic_increasing)
    
    # In FX, tick spreads can occasionally be anomalous in raw data.
    # We identify how many bid > ask ticks exist.
    invalid_spreads = int((df["ask"] < df["bid"]).sum())
    valid_prices = bool((df["bid"] > 0).all() and (df["ask"] > 0).all())
    
    valid = (missing_vals == 0) and (dup_times == 0) and is_sorted and (invalid_spreads == 0) and valid_prices
    
    return {
        "valid": bool(valid),
        "missing_values": missing_vals,
        "duplicate_timestamps": dup_times,
        "is_sorted": is_sorted,
        "invalid_spreads": invalid_spreads
    }

def sync_ohlcv_to_db(df: pd.DataFrame, symbol: str, timeframe: str, engine) -> int:
    """
    Syncs OHLCV data to ohlcv_data table in TimescaleDB (or SQLite for tests).
    """
    if df is None or df.empty:
        return 0
    df_copy = df.copy()
    df_copy["symbol"] = symbol
    df_copy["timeframe"] = timeframe
    df_copy.to_sql("ohlcv_data", engine, if_exists="append", index=True, index_label="time")
    return len(df)

def sync_ticks_to_db(df: pd.DataFrame, symbol: str, engine) -> int:
    """
    Syncs Tick data to tick_data table in TimescaleDB (or SQLite for tests).
    """
    if df is None or df.empty:
        return 0
    df_copy = df.copy()
    df_copy["symbol"] = symbol
    df_copy.to_sql("tick_data", engine, if_exists="append", index=True, index_label="time")
    return len(df)

def check_db_integrity(engine) -> dict:
    """
    Checks if database has required hypertables and structure.
    """
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    has_ohlcv = "ohlcv_data" in tables
    has_ticks = "tick_data" in tables
    
    return {
        "ohlcv_table_exists": has_ohlcv,
        "tick_table_exists": has_ticks,
        "valid": bool(has_ohlcv and has_ticks)
    }

# --- NEW INGESTION MODULE FUNCTIONS ---

def get_timeframe_str(timeframe) -> str:
    if isinstance(timeframe, str):
        return timeframe
    mapping = {
        1: "M1",
        2: "M2",
        3: "M3",
        4: "M4",
        5: "M5",
        6: "M6",
        10: "M10",
        12: "M12",
        15: "M15",
        20: "M20",
        30: "M30",
        16385: "H1",
        16386: "H2",
        16388: "H4",
        16390: "H6",
        16392: "H8",
        16396: "H12",
        16408: "D1",
        32769: "W1",
        49153: "MN1"
    }
    return mapping.get(timeframe, str(timeframe))

def validate_ohlcv_schema(df: pd.DataFrame) -> bool:
    """
    Returns True if the DataFrame conforms to the expected OHLCV schema,
    otherwise raises/logs errors and cleans/handles columns/values.
    """
    if df is None:
        raise ValueError("DataFrame is None")
    if df.empty:
        logger.warning("DataFrame is empty")
        return False

    # Standardize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    # If 'time' is a column, set it as index
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception as e:
            raise ValueError(f"Index is not DatetimeIndex and cannot be converted: {e}")

    # Sort index in-place
    df.sort_index(inplace=True)

    # Drop duplicate timestamps in-place
    if df.index.duplicated().any():
        df.index.name = 'time'
        df.reset_index(inplace=True)
        df.drop_duplicates(subset=['time'], keep='first', inplace=True)
        df.set_index('time', inplace=True)

    # Reject or drop future timestamps
    now = pd.Timestamp.now(tz=df.index.tz)
    future_mask = df.index > now
    if future_mask.any():
        logger.warning(f"Future timestamps found and dropped: {df.index[future_mask]}")
        df.drop(df.index[future_mask], inplace=True)

    if df.empty:
        logger.warning("DataFrame is empty after dropping future timestamps")
        return False

    # Check for required columns and map alternatives
    required_cols = {
        'open': float,
        'high': float,
        'low': float,
        'close': float,
        'tick_volume': int,
        'spread': int,
        'real_volume': int
    }

    # Check alternate column names
    rename_map = {}
    if 'volume' in df.columns and 'tick_volume' not in df.columns:
        rename_map['volume'] = 'tick_volume'
    if 'volume_real' in df.columns and 'real_volume' not in df.columns:
        rename_map['volume_real'] = 'real_volume'

    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Fill missing columns with defaults
    for col, dtype in required_cols.items():
        if col not in df.columns:
            logger.warning(f"Missing column '{col}'. Adding it with default value 0.")
            df[col] = 0

    # Cast types and handle NaNs
    for col, dtype in required_cols.items():
        # Fill NaN values
        if df[col].isnull().any():
            logger.warning(f"NaN values found in column '{col}'. Filling them.")
            if col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].ffill().bfill().fillna(0.0)
            else:
                df[col] = df[col].fillna(0)

        # Cast to proper dtype
        try:
            df[col] = df[col].astype(dtype)
        except Exception as e:
            raise ValueError(f"Failed to cast column '{col}' to {dtype}: {e}")

    # Validate values consistency
    # 1. Prices must be non-negative
    for col in ['open', 'high', 'low', 'close']:
        if (df[col] < 0).any():
            logger.error(f"Negative price values found in column '{col}'")
            df[col] = df[col].abs()

    # 2. High must be >= low
    invalid_hl = df['high'] < df['low']
    if invalid_hl.any():
        logger.error(f"Found {invalid_hl.sum()} rows where high < low. Swapping them.")
        temp = df.loc[invalid_hl, 'high'].copy()
        df.loc[invalid_hl, 'high'] = df.loc[invalid_hl, 'low']
        df.loc[invalid_hl, 'low'] = temp

    # 3. Open and close must be within [low, high]
    for col in ['open', 'close']:
        invalid_val_high = df[col] > df['high']
        if invalid_val_high.any():
            logger.warning(f"Clamping {col} to high because it exceeded high price.")
            df.loc[invalid_val_high, col] = df.loc[invalid_val_high, 'high']

        invalid_val_low = df[col] < df['low']
        if invalid_val_low.any():
            logger.warning(f"Clamping {col} to low because it was lower than low price.")
            df.loc[invalid_val_low, col] = df.loc[invalid_val_low, 'low']

    # Clamp negative volumes and spreads to 0
    for col in ['tick_volume', 'spread', 'real_volume']:
        if col in df.columns:
            if (df[col] < 0).any():
                logger.warning(f"Negative values found in column '{col}'. Clamping to 0.")
                df[col] = df[col].clip(lower=0)

    return True

def validate_tick_schema(df: pd.DataFrame) -> bool:
    """
    Returns True if the DataFrame conforms to the expected tick schema,
    otherwise raises/logs errors and cleans/handles columns/values.
    """
    if df is None:
        raise ValueError("DataFrame is None")
    if df.empty:
        logger.warning("DataFrame is empty")
        return False

    # Standardize column names to lowercase
    df.columns = [col.lower() for col in df.columns]

    # If 'time' is a column, set it as index
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

    # Ensure index is datetime
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception as e:
            raise ValueError(f"Index is not DatetimeIndex and cannot be converted: {e}")

    # Sort index in-place
    df.sort_index(inplace=True)

    # Drop duplicate timestamps in-place
    if df.index.duplicated().any():
        df.index.name = 'time'
        df.reset_index(inplace=True)
        df.drop_duplicates(subset=['time'], keep='first', inplace=True)
        df.set_index('time', inplace=True)

    # Reject or drop future timestamps
    now = pd.Timestamp.now(tz=df.index.tz)
    future_mask = df.index > now
    if future_mask.any():
        logger.warning(f"Future timestamps found and dropped: {df.index[future_mask]}")
        df.drop(df.index[future_mask], inplace=True)

    if df.empty:
        logger.warning("DataFrame is empty after dropping future timestamps")
        return False

    # Check for required columns and map alternatives
    required_cols = {
        'bid': float,
        'ask': float,
        'last': float,
        'volume': int,
        'time_msc': int,
        'flags': int,
        'volume_real': float
    }

    # Check alternate column names
    rename_map = {}
    if 'real_volume' in df.columns and 'volume_real' not in df.columns:
        rename_map['real_volume'] = 'volume_real'

    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Fill missing columns with defaults
    for col, dtype in required_cols.items():
        if col not in df.columns:
            logger.warning(f"Missing column '{col}'. Adding it with default value 0.")
            df[col] = 0.0 if dtype == float else 0

    # Cast types and handle NaNs
    for col, dtype in required_cols.items():
        # Fill NaN values
        if df[col].isnull().any():
            logger.warning(f"NaN values found in column '{col}'. Filling them.")
            df[col] = df[col].ffill().bfill().fillna(0.0 if dtype == float else 0)

        # Cast to proper dtype
        try:
            df[col] = df[col].astype(dtype)
        except Exception as e:
            raise ValueError(f"Failed to cast column '{col}' to {dtype}: {e}")

    # Validate values consistency
    # 1. Prices must be non-negative
    for col in ['bid', 'ask', 'last']:
        if (df[col] < 0).any():
            logger.error(f"Negative price values found in column '{col}'")
            df[col] = df[col].abs()

    # 2. Bid should generally be <= Ask
    invalid_spread = df['bid'] > df['ask']
    if invalid_spread.any():
        logger.warning(f"Found {invalid_spread.sum()} rows where bid > ask. Swapping them.")
        temp = df.loc[invalid_spread, 'bid'].copy()
        df.loc[invalid_spread, 'bid'] = df.loc[invalid_spread, 'ask']
        df.loc[invalid_spread, 'ask'] = temp

    # Clamp negative volumes to 0
    for col in ['volume', 'volume_real']:
        if col in df.columns:
            if (df[col] < 0).any():
                logger.warning(f"Negative values found in column '{col}'. Clamping to 0.")
                df[col] = df[col].clip(lower=0)

    return True

def fetch_historical_ohlcv(symbol: str, timeframe: int, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Fetches rates, validates schema via validate_ohlcv_schema, and syncs to TimescaleDB.
    Handles reconnects on terminal disconnects.
    """
    df = mt5_client.fetch_ohlcv(symbol, timeframe, start, end)
    if df is None:
        raise RuntimeError(f"Failed to fetch OHLCV data for {symbol} after retries/reconnections.")

    # Validate and clean schema (modifies df in-place)
    if not validate_ohlcv_schema(df):
        raise ValueError(f"OHLCV validation failed critically for {symbol}")

    # Convert timeframe to string
    tf_str = get_timeframe_str(timeframe)

    # Sync to DB
    sync_ohlcv_to_timescale(df, symbol, tf_str)

    return df

def fetch_historical_ticks(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Fetches ticks, validates schema via validate_tick_schema, and syncs to TimescaleDB.
    Handles reconnects on terminal disconnects.
    """
    df = mt5_client.fetch_ticks(symbol, start, end)
    if df is None:
        raise RuntimeError(f"Failed to fetch ticks data for {symbol} after retries/reconnections.")

    # Validate and clean schema (modifies df in-place)
    if not validate_tick_schema(df):
        raise ValueError(f"Tick validation failed critically for {symbol}")

    # Sync to DB
    sync_ticks_to_timescale(df, symbol)

    return df
