import os
import time
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any, List

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
import sqlalchemy
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError, InterfaceError

# Configure Logger
logger = logging.getLogger("ThorIngestionHA")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

class MT5ConnectionException(Exception):
    """Custom exception raised for MT5 connection failures."""
    pass

class DatabaseConnectionException(Exception):
    """Custom exception raised for Database connection failures."""
    pass

class SchemaValidationException(Exception):
    """Custom exception raised when data schema validation fails critically."""
    pass


class MT5ConnectionManager:
    """
    Manages connection to the MetaTrader 5 terminal.
    Handles terminal launching, broker server connection tracking, 
    exponential backoff retries, and clean terminal shutdown/restarts.
    """
    def __init__(self, 
                 path: str, 
                 login: int, 
                 password: str, 
                 server: str, 
                 max_retries: int = 5,
                 initial_backoff: float = 2.0,
                 backoff_factor: float = 2.0,
                 max_backoff: float = 60.0):
        self.path = path
        self.login = login
        self.password = password
        self.server = server
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        
        self.connected_to_terminal = False
        self.last_terminal_restart_time = 0.0

    def connect(self) -> bool:
        """
        Attempts to connect to MT5 with exponential backoff.
        Differentiates between terminal-start failures, broker connection losses,
        and fatal authentication failures.
        """
        backoff = self.initial_backoff
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Connecting to MT5 Terminal (Attempt {attempt}/{self.max_retries})...")
            
            # Step 1: Initialize terminal process
            init_success = mt5.initialize(
                path=self.path,
                login=self.login,
                password=self.password,
                server=self.server
            )
            
            if init_success:
                self.connected_to_terminal = True
                
                # Step 2: Check broker connection
                term_info = mt5.terminal_info()
                if term_info is not None:
                    if term_info.connected:
                        logger.info("Successfully connected to MT5 terminal and Broker server.")
                        return True
                    else:
                        logger.warning("MT5 terminal started but not connected to Broker server. Checking last error...")
                
                # Check for other errors
                err_code, err_desc = mt5.last_error()
                logger.warning(f"MT5 terminal status warning: Code={err_code}, Desc={err_desc}")
            else:
                # Step 3: Handle failed initialization
                err_code, err_desc = mt5.last_error()
                logger.error(f"MT5 initialization failed: Code={err_code}, Desc={err_desc}")
                
                # Check for fatal credential/params errors
                # mt5.RES_ERROR_PARAMS (-2) or authorization issues
                if err_code in [-2, -5, mt5.RES_ERROR_PARAMS]:
                    logger.critical("Fatal: MT5 authentication or parameter failure. Retries aborted.")
                    raise MT5ConnectionException(f"Fatal MT5 authentication failure: Code={err_code}, Desc={err_desc}")
            
            # Clean up before retrying
            self.disconnect()
            
            if attempt == self.max_retries:
                break
                
            logger.info(f"Retrying MT5 connection in {backoff:.1f} seconds...")
            time.sleep(backoff)
            backoff = min(backoff * self.backoff_factor, self.max_backoff)
            
        raise MT5ConnectionException("Failed to establish stable MT5 connection after maximum retries.")

    def disconnect(self):
        """Cleanly shuts down MT5 terminal connection."""
        if self.connected_to_terminal:
            logger.info("Shutting down MT5 connection...")
            mt5.shutdown()
            self.connected_to_terminal = False

    def ensure_connected(self) -> bool:
        """
        Verifies active connection to both terminal and broker.
        If connection is lost, triggers reconnect flow.
        """
        if not self.connected_to_terminal:
            return self.connect()
            
        term_info = mt5.terminal_info()
        if term_info is None or not term_info.connected:
            logger.warning("MT5 terminal or Broker connection lost. Re-establishing connection...")
            return self.connect()
            
        return True

    def execute_with_retry(self, api_func, *args, **kwargs) -> Any:
        """
        Executes an MT5 API call, handling connection loss and retries.
        """
        backoff = self.initial_backoff
        for attempt in range(1, self.max_retries + 1):
            try:
                self.ensure_connected()
                result = api_func(*args, **kwargs)
                
                if result is not None:
                    return result
                
                # API call returned None; check error
                err_code, err_desc = mt5.last_error()
                logger.warning(f"MT5 API call returned None. Code={err_code}, Desc={err_desc} (Attempt {attempt}/{self.max_retries})")
                
                # If connection issue, force disconnect and reconnect
                if err_code in [mt5.RES_ERROR_CONNECTION, -1, -10014]:
                    logger.error("Connection error detected during API call. Forcing reconnect...")
                    self.disconnect()
                
            except Exception as e:
                logger.exception(f"Unexpected exception during MT5 API execution: {str(e)}")
                self.disconnect()
                
            if attempt == self.max_retries:
                break
                
            time.sleep(backoff)
            backoff = min(backoff * self.backoff_factor, self.max_backoff)
            
        raise MT5ConnectionException("MT5 API call failed repeatedly due to connection errors.")


class DBConnectionManager:
    """
    Manages TimescaleDB connection recovery and transaction wrappers.
    Implements pessimistic connection checking (pre-ping) and pool disposal on failure.
    """
    def __init__(self, db_url: str, pool_size: int = 10, max_overflow: int = 20):
        self.db_url = db_url
        # Create SQLAlchemy engine with resilient settings
        self.engine = create_engine(
            self.db_url,
            pool_pre_ping=True,      # Test connections before checkout
            pool_recycle=1800,        # Recycle connections every 30 minutes
            pool_size=pool_size,
            max_overflow=max_overflow
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def dispose_pool(self):
        """Forces disposal of connection pool. Useful after DB crash or failover."""
        logger.info("Disposing database connection pool to drop dead connections...")
        self.engine.dispose()

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except (OperationalError, InterfaceError) as e:
            session.rollback()
            logger.error(f"Database connection error: {str(e)}")
            self.dispose_pool()
            raise DatabaseConnectionException("Database connection lost during transaction.") from e
        except Exception as e:
            session.rollback()
            logger.error(f"Transaction failed, rolling back: {str(e)}")
            raise
        finally:
            session.close()

    def execute_write_with_retry(self, write_func, df: pd.DataFrame, *args, **kwargs) -> bool:
        """
        Executes a database write function with retry logic.
        """
        max_retries = 3
        backoff = 2.0
        for attempt in range(1, max_retries + 1):
            try:
                with self.session_scope() as session:
                    write_func(session, df, *args, **kwargs)
                return True
            except DatabaseConnectionException:
                if attempt == max_retries:
                    raise
                logger.warning(f"Retrying database write in {backoff} seconds (Attempt {attempt}/{max_retries})...")
                time.sleep(backoff)
                backoff *= 2.0
            except Exception as e:
                logger.error(f"Non-recoverable database write error: {str(e)}")
                raise
        return False


class DataSchemaValidator:
    """
    Validates incoming market data (OHLCV & Ticks) before database insertion.
    Checks for nulls, out-of-range prices, logical consistency, and duplicates.
    """
    
    @staticmethod
    def validate_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Validates OHLCV DataFrame.
        Expected columns in index or dataframe: 'open', 'high', 'low', 'close', 'tick_volume', 'spread'
        Returns cleaned DataFrame, or raises SchemaValidationException for critical failures.
        """
        if df is None or df.empty:
            raise SchemaValidationException(f"OHLCV data is empty or None for {symbol}")

        # Ensure index is datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception as e:
                raise SchemaValidationException(f"Index is not convertible to DatetimeIndex: {str(e)}")

        df = df.copy()
        
        # 1. Null Checks
        critical_cols = ['open', 'high', 'low', 'close']
        for col in critical_cols:
            if col not in df.columns:
                raise SchemaValidationException(f"Missing critical column '{col}' in OHLCV data.")
            
            null_mask = df[col].isnull()
            if null_mask.any():
                null_count = null_mask.sum()
                logger.warning(f"Found {null_count} nulls in {col} for {symbol}. Attempting to drop rows...")
                df = df.dropna(subset=[col])
                
        if df.empty:
            raise SchemaValidationException(f"All rows contained nulls in critical columns for {symbol}.")

        # 2. Duplicate Checks
        # Deduplicate based on timestamp (index)
        duplicate_count = df.index.duplicated().sum()
        if duplicate_count > 0:
            logger.warning(f"Found {duplicate_count} duplicate timestamps for {symbol}. Deduplicating (keeping last)...")
            df = df[~df.index.duplicated(keep='last')]

        # 3. Value Range Checks
        # Prices must be strictly positive
        for col in critical_cols:
            invalid_price_mask = df[col] <= 0
            if invalid_price_mask.any():
                invalid_count = invalid_price_mask.sum()
                logger.error(f"Found {invalid_count} non-positive prices in {col} for {symbol}.")
                # For safety, drop rows with negative or zero prices
                df = df[df[col] > 0]
                
        if df.empty:
            raise SchemaValidationException(f"All rows contained invalid non-positive prices for {symbol}.")

        # 4. Logical Price Consistency Checks
        # High must be >= open, high >= close, high >= low
        # Low must be <= open, low <= close, low <= high
        logical_violation = (
            (df['high'] < df['open']) | 
            (df['high'] < df['close']) | 
            (df['high'] < df['low']) |
            (df['low'] > df['open']) | 
            (df['low'] > df['close'])
        )
        if logical_violation.any():
            violation_count = logical_violation.sum()
            logger.error(f"Found {violation_count} logical price violations (e.g. High < Low) for {symbol}. Dropping violated rows...")
            df = df[~logical_violation]
            
        if df.empty:
            raise SchemaValidationException(f"All rows failed price consistency checks for {symbol}.")

        # 5. Volume and Spread checks
        if 'tick_volume' in df.columns:
            # Volume should be >= 0
            df.loc[df['tick_volume'] < 0, 'tick_volume'] = 0
        if 'spread' in df.columns:
            # Spread should be >= 0
            df.loc[df['spread'] < 0, 'spread'] = 0

        # Time range safety check: no data in the future
        future_mask = df.index > datetime.utcnow()
        if future_mask.any():
            future_count = future_mask.sum()
            logger.error(f"Found {future_count} rows with timestamps in the future for {symbol}. Dropping future rows...")
            df = df[~future_mask]

        if df.empty:
            raise SchemaValidationException(f"No valid rows left after all schema validations for {symbol}.")

        return df

    @staticmethod
    def validate_ticks(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Validates Tick DataFrame.
        Expected columns: 'bid', 'ask'
        """
        if df is None or df.empty:
            raise SchemaValidationException(f"Tick data is empty or None for {symbol}")

        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception as e:
                raise SchemaValidationException(f"Index is not convertible to DatetimeIndex: {str(e)}")

        df = df.copy()

        # 1. Null Checks
        for col in ['bid', 'ask']:
            if col not in df.columns:
                raise SchemaValidationException(f"Missing critical column '{col}' in Tick data.")
            null_mask = df[col].isnull()
            if null_mask.any():
                df = df.dropna(subset=[col])

        if df.empty:
            raise SchemaValidationException(f"All ticks contained nulls in bid/ask for {symbol}.")

        # 2. Value Range and Spread Logic Check
        # bid > 0, ask > 0, ask >= bid
        invalid_ticks = (df['bid'] <= 0) | (df['ask'] <= 0) | (df['ask'] < df['bid'])
        if invalid_ticks.any():
            logger.error(f"Found {invalid_ticks.sum()} invalid ticks (bid<=0 or ask<=0 or ask < bid) for {symbol}. Dropping...")
            df = df[~invalid_ticks]

        if df.empty:
            raise SchemaValidationException(f"All ticks failed validity checks for {symbol}.")

        # Time range safety check: no data in the future
        future_mask = df.index > datetime.utcnow()
        if future_mask.any():
            df = df[~future_mask]

        if df.empty:
            raise SchemaValidationException(f"No valid ticks left after schema validation for {symbol}.")

        return df


class HAIngestionPipeline:
    """
    High-Availability Ingestion Pipeline.
    Coordinates MT5 connection, data retrieval, data validation, and database syncing.
    """
    def __init__(self, 
                 mt5_manager: MT5ConnectionManager, 
                 db_manager: DBConnectionManager,
                 local_cache_path: str = "./ingestion_buffer"):
        self.mt5 = mt5_manager
        self.db = db_manager
        self.local_cache_path = local_cache_path
        os.makedirs(self.local_cache_path, exist_ok=True)

    def fetch_and_sync_ohlcv(self, symbol: str, timeframe: int, start: datetime, end: datetime, tf_name: str) -> bool:
        """
        Fetches OHLCV data from MT5, validates schema, and syncs to TimescaleDB.
        Buffers to local CSV if TimescaleDB is unreachable to prevent data loss.
        """
        logger.info(f"Ingestion started for {symbol} ({tf_name}) from {start} to {end}")
        
        # 1. Fetch data from MT5 using MT5 Connection Manager (retries inside)
        try:
            rates = self.mt5.execute_with_retry(
                mt5.copy_rates_range, symbol, timeframe, start, end
            )
        except MT5ConnectionException as e:
            logger.error(f"MT5 retrieval failed for {symbol} ({tf_name}): {str(e)}")
            return False
            
        if rates is None or len(rates) == 0:
            logger.warning(f"No rates returned from MT5 for {symbol} ({tf_name})")
            return False

        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)

        # 2. Validate Data
        try:
            df_cleaned = DataSchemaValidator.validate_ohlcv(df, symbol)
        except SchemaValidationException as e:
            logger.critical(f"Schema validation failed for {symbol} ({tf_name}): {str(e)}")
            return False

        # Prepare for database write
        df_cleaned['symbol'] = symbol
        df_cleaned['timeframe'] = tf_name

        # Define the DB write action
        def db_write_action(session: Session, data: pd.DataFrame):
            # Using SQLAlchemy engine to insert
            data.to_sql('ohlcv_data', session.bind, if_exists='append', index=True, index_label='time')

        # 3. Sync to TimescaleDB with connection recovery
        try:
            self.db.execute_write_with_retry(db_write_action, df_cleaned)
            logger.info(f"Successfully ingested and synced {len(df_cleaned)} rows for {symbol} ({tf_name})")
            
            # Check if there are local buffered files and attempt to flush them
            self.flush_local_buffer()
            return True
        except DatabaseConnectionException:
            logger.critical("Database is down. Buffering data to local disk to prevent loss.")
            self.buffer_to_disk(df_cleaned, f"ohlcv_{symbol}_{tf_name}_{int(time.time())}.csv")
            return False

    def buffer_to_disk(self, df: pd.DataFrame, filename: str):
        """Saves a dataframe to local storage when database is unreachable."""
        filepath = os.path.join(self.local_cache_path, filename)
        try:
            df.to_csv(filepath, index=True)
            logger.info(f"Buffered {len(df)} rows to local cache: {filepath}")
        except Exception as e:
            logger.error(f"Failed to write buffer file to disk: {str(e)}")

    def flush_local_buffer(self):
        """Attempts to flush buffered CSV files to the database."""
        buffer_files = [f for f in os.listdir(self.local_cache_path) if f.endswith('.csv')]
        if not buffer_files:
            return
            
        logger.info(f"Found {len(buffer_files)} files in local buffer. Attempting to flush...")
        
        for file in buffer_files:
            filepath = os.path.join(self.local_cache_path, file)
            try:
                df = pd.read_csv(filepath, index_col='time')
                df.index = pd.to_datetime(df.index)
                
                # Determine which table to write to based on filename
                table_name = 'ohlcv_data' if 'ohlcv' in file else 'tick_data'
                
                def db_write_action(session: Session, data: pd.DataFrame):
                    data.to_sql(table_name, session.bind, if_exists='append', index=True, index_label='time')
                    
                self.db.execute_write_with_retry(db_write_action, df)
                logger.info(f"Successfully flushed buffer file {file} to DB.")
                os.remove(filepath)
            except DatabaseConnectionException:
                logger.warning(f"Database still unreachable. Keeping file {file} in buffer.")
                break
            except Exception as e:
                logger.error(f"Failed to process buffer file {file} (possibly corrupted): {str(e)}. Deleting file.")
                os.remove(filepath)
