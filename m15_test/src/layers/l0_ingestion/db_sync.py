import pandas as pd
from sqlalchemy.orm import Session
from src.core.db import engine

from sqlalchemy import text

_hypertables_initialized = False

def init_hypertables(force=False):
    """
    Utility function to create tables and convert standard Postgres tables into TimescaleDB hypertables.
    This safely checks the dialect to avoid failure on SQLite.
    """
    global _hypertables_initialized
    if _hypertables_initialized and not force:
        return
        
    dialect_name = engine.dialect.name
    with engine.begin() as conn:
        if dialect_name == 'postgresql':
            # Create ohlcv_data table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ohlcv_data (
                    time TIMESTAMP WITH TIME ZONE NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    timeframe VARCHAR(20) NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    tick_volume BIGINT NOT NULL,
                    spread INTEGER NOT NULL,
                    real_volume BIGINT NOT NULL,
                    PRIMARY KEY (time, symbol, timeframe)
                );
            """))
            # Convert to hypertable
            conn.execute(text("SELECT create_hypertable('ohlcv_data', 'time', if_not_exists => TRUE);"))
            
            # Create tick_data table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tick_data (
                    time TIMESTAMP WITH TIME ZONE NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    bid DOUBLE PRECISION,
                    ask DOUBLE PRECISION,
                    last DOUBLE PRECISION,
                    volume BIGINT,
                    time_msc BIGINT NOT NULL,
                    flags INTEGER,
                    volume_real DOUBLE PRECISION
                );
            """))
            # Convert to hypertable
            conn.execute(text("SELECT create_hypertable('tick_data', 'time', if_not_exists => TRUE);"))
        else:
            # SQLite or other dialect for testing
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ohlcv_data (
                    time TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    tick_volume INTEGER NOT NULL,
                    spread INTEGER NOT NULL,
                    real_volume INTEGER NOT NULL,
                    PRIMARY KEY (time, symbol, timeframe)
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tick_data (
                    time TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    bid REAL,
                    ask REAL,
                    last REAL,
                    volume INTEGER,
                    time_msc INTEGER NOT NULL,
                    flags INTEGER,
                    volume_real REAL
                );
            """))
    _hypertables_initialized = True

def sync_ohlcv_to_timescale(df: pd.DataFrame, symbol: str, timeframe: str):
    """
    Syncs OHLCV dataframe to a TimescaleDB hypertable.
    Assumes a hypertable `ohlcv_data` exists with columns:
    time, symbol, timeframe, open, high, low, close, tick_volume, spread, real_volume
    Handles overlaps using upserts / ON CONFLICT.
    """
    if df is None or df.empty:
        return
        
    df = df.copy()
    if 'time' not in df.columns:
        df.index.name = 'time'
        df = df.reset_index()
        
    df['time'] = pd.to_datetime(df['time'])
    df['time'] = df['time'].apply(lambda x: x.to_pydatetime() if hasattr(x, 'to_pydatetime') else x)
    df['symbol'] = symbol
    df['timeframe'] = timeframe
    
    dialect_name = engine.dialect.name
    
    records = df.to_dict(orient='records')
    if not records:
        return
        
    for r in records:
        if 'time' in r and hasattr(r['time'], 'to_pydatetime'):
            r['time'] = r['time'].to_pydatetime()
        
    chunk_size = 5000
    if dialect_name == 'postgresql':
        query = text("""
            INSERT INTO ohlcv_data (time, symbol, timeframe, open, high, low, close, tick_volume, spread, real_volume)
            VALUES (:time, :symbol, :timeframe, :open, :high, :low, :close, :tick_volume, :spread, :real_volume)
            ON CONFLICT (time, symbol, timeframe) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                tick_volume = EXCLUDED.tick_volume,
                spread = EXCLUDED.spread,
                real_volume = EXCLUDED.real_volume;
        """)
        with engine.begin() as conn:
            for i in range(0, len(records), chunk_size):
                conn.execute(query, records[i:i + chunk_size])
            
    elif dialect_name == 'sqlite':
        query = text("""
            INSERT INTO ohlcv_data (time, symbol, timeframe, open, high, low, close, tick_volume, spread, real_volume)
            VALUES (:time, :symbol, :timeframe, :open, :high, :low, :close, :tick_volume, :spread, :real_volume)
            ON CONFLICT (time, symbol, timeframe) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                tick_volume = excluded.tick_volume,
                spread = excluded.spread,
                real_volume = excluded.real_volume;
        """)
        with engine.begin() as conn:
            for i in range(0, len(records), chunk_size):
                conn.execute(query, records[i:i + chunk_size])
    else:
        df.set_index('time', inplace=True)
        df.to_sql('ohlcv_data', engine, if_exists='append', index=True, index_label='time', chunksize=chunk_size)

def sync_ticks_to_timescale(df: pd.DataFrame, symbol: str):
    """
    Syncs tick dataframe to a TimescaleDB hypertable.
    Assumes a hypertable `tick_data` exists.
    """
    if df is None or df.empty:
        return
        
    df = df.copy()
    if 'time' not in df.columns:
        df.index.name = 'time'
        df = df.reset_index()
        
    df['time'] = pd.to_datetime(df['time'])
    df['symbol'] = symbol
    
    # Map and pad fields
    for col in ['bid', 'ask', 'last', 'volume', 'time_msc', 'flags', 'volume_real']:
        if col not in df.columns:
            df[col] = None
            
    # Ensure time_msc is not None or 0
    if 'time_msc' in df.columns:
        df['time_msc'] = df['time_msc'].fillna(0).astype(int)
    
    dialect_name = engine.dialect.name
    
    max_time_msc = 0
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT MAX(time_msc) FROM tick_data WHERE symbol = :symbol"),
                {"symbol": symbol}
            ).scalar()
            if res is not None:
                max_time_msc = int(res)
    except Exception as e:
        max_time_msc = 0

    df = df[df['time_msc'] > max_time_msc]
    if df.empty:
        return
    
    records = df[['time', 'symbol', 'bid', 'ask', 'last', 'volume', 'time_msc', 'flags', 'volume_real']].to_dict(orient='records')
    if not records:
        return
        
    for r in records:
        if 'time' in r and hasattr(r['time'], 'to_pydatetime'):
            r['time'] = r['time'].to_pydatetime()
        
    chunk_size = 5000
    if dialect_name in ['postgresql', 'sqlite']:
        query = text("""
            INSERT INTO tick_data (time, symbol, bid, ask, last, volume, time_msc, flags, volume_real)
            VALUES (:time, :symbol, :bid, :ask, :last, :volume, :time_msc, :flags, :volume_real);
        """)
        with engine.begin() as conn:
            for i in range(0, len(records), chunk_size):
                conn.execute(query, records[i:i + chunk_size])
    else:
        df.set_index('time', inplace=True)
        df.to_sql('tick_data', engine, if_exists='append', index=True, index_label='time', chunksize=chunk_size)

# Initialize hypertables once on load
try:
    init_hypertables()
except Exception:
    pass

