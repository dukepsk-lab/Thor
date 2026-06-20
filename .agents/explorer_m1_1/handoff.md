# Ingestion Milestone — Ingestion Validation and Schema Design Analysis

This report presents the analysis of the MT5 Client (`src/layers/l0_ingestion/mt5_client.py`), DB synchronization client (`src/layers/l0_ingestion/db_sync.py`), and system architecture. It outlines the schema designs for OHLCV and tick history, validation rules, reconnect/retry mechanics for the validation harness, and a programmatic testing strategy.

---

## 1. Observation

Direct observations from the repository files:

### A. MT5 Client (`src/layers/l0_ingestion/mt5_client.py`)
- **Connection initialization (Lines 11-25):**
  ```python
  def connect(self) -> bool:
      if not mt5.initialize(
          path=settings.MT5_PATH,
          login=settings.MT5_LOGIN,
          password=settings.MT5_PASSWORD,
          server=settings.MT5_SERVER
      ):
          print(f"MT5 initialization failed, error code: {mt5.last_error()}")
          return False
          
      self.connected = True
      return True
  ```
  The connection relies on four configuration settings: `MT5_PATH`, `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER`. If `initialize` fails, it logs via `mt5.last_error()` but does not retry or handle exceptions.

- **Data Fetching (Lines 35-68):**
  `fetch_ohlcv` and `fetch_ticks` fetch data using `mt5.copy_rates_range` and `mt5.copy_ticks_range` respectively:
  ```python
  rates = mt5.copy_rates_range(symbol, timeframe, start, end)
  if rates is None:
      print(f"Failed to fetch rates for {symbol}, error code: {mt5.last_error()}")
      return None
  ```
  And:
  ```python
  ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
  if ticks is None:
      print(f"Failed to fetch ticks for {symbol}, error code: {mt5.last_error()}")
      return None
  ```
  Both methods cast the resulting numpy structured array into a pandas DataFrame, format the `time` column as datetime (`pd.to_datetime(df['time'], unit='s')`), set it as index, and return the DataFrame. No schema validation or gap detection is performed.

### B. DB Synchronization Client (`src/layers/l0_ingestion/db_sync.py`)
- **Scaffolding and Comments (Lines 18-20, 33):**
  The file uses pandas `to_sql` method for database inserts:
  ```python
  # In a production setting, you'd use a more robust upsert method or copy_from.
  # For now, using pandas to_sql for scaffolding.
  df.to_sql('ohlcv_data', engine, if_exists='append', index=True, index_label='time')
  ```
  And:
  ```python
  df.to_sql('tick_data', engine, if_exists='append', index=True, index_label='time')
  ```
  There is currently no conflict handling (`ON CONFLICT`) for primary key collisions, meaning duplicate inserts will crash the pipeline.
- **Hypertables setup (Lines 35-44):**
  The `init_hypertables` function contains commented template code for creating TimescaleDB hypertables:
  ```python
  # conn.execute("SELECT create_hypertable('ohlcv_data', 'time', if_not_exists => TRUE);")
  # conn.execute("SELECT create_hypertable('tick_data', 'time', if_not_exists => TRUE);")
  ```

### C. System Architecture (`ML_Trading_System_Architecture.md`)
- **Layer 0 Details (Lines 47-50):**
  - "MT5 pull of OHLCV for EURUSD & GBPUSD at H4 (primary), plus D1 (regime context) and M15 (execution context)."
  - "Tick/spread history stored alongside bars — non-negotiable, because realistic cost modeling depends on it."
  - "TimescaleDB hypertables + continuous aggregates for fast feature windows."

---

## 2. Logic Chain

1. **Database Conflict Handling:**
   - *Observation:* `db_sync.py` uses `to_sql(..., if_exists='append')`.
   - *Reasoning:* If a connection drops and retries, or if the ingestion agent pulls overlapping data segments, executing `to_sql` will attempt to insert duplicate rows. If there is a primary key constraint, it will raise an `IntegrityError` and crash the program.
   - *Conclusion:* We must implement a robust bulk upsert (`ON CONFLICT DO UPDATE` or `ON CONFLICT DO NOTHING`) for `ohlcv_data` using SQLAlchemy's PostgreSQL dialect. For `tick_data`, since we have no primary key (due to sub-second duplicate possibilities), duplicates should be prevented by tracking last-inserted ticks or filtering by `time_msc` beforehand.

2. **Tick Hypertable Constraints:**
   - *Observation:* Ticks contain millisecond timestamps (`time_msc`), bid, ask, and flags. Multiple ticks can arrive during the same millisecond or have identical data from the broker.
   - *Reasoning:* A primary key constraint on `(time, symbol, time_msc)` will cause insertions to fail if the broker sends two ticks with identical milliseconds.
   - *Conclusion:* The `tick_data` table should not have a primary key constraint. Instead, it should rely on a composite index on `(symbol, time_msc DESC)` to enable rapid historical queries.

3. **Auto-Reconnect and Retries:**
   - *Observation:* MT5 terminal interactions return `None` on connection failure or history gaps.
   - *Reasoning:* A transient network error or terminal crash shouldn't fail the entire ingestion daemon. We need to check connection health using `mt5.terminal_info()` and execute retries with exponential backoff and jitter.
   - *Conclusion:* Implement an execution wrapper that automatically recreates the MT5 terminal connection and retries the data pull.

4. **FX Weekend Gap Filtering:**
   - *Observation:* The foreign exchange (FX) market closes on weekends (Friday ~22:00 UTC to Sunday ~22:00 UTC).
   - *Reasoning:* Standard gap detection would flag the weekend gap as a data loss event since H4 bars will be missing for ~48 hours.
   - *Conclusion:* The validation harness must inspect gap timestamps and skip alerts if the gap occurs over a weekend.

---

## 3. Caveats

- **Mocking Limitations:** Programmatic testing using mocked MT5 libraries validates logic flow and recovery states but cannot simulate exact MT5 internal error behaviors (e.g., how the terminal handles slow historical backfilling).
- **Database Scaling:** SQLAlchemy bulk inserts are sufficient for development, but for high-frequency tick data with hundreds of thousands of rows, using PostgreSQL `COPY` commands (via `psycopg2` or `asyncpg`) is significantly faster.
- **Timezone Standardization:** MT5 servers usually operate on Eastern European Time (EET/EEST) or broker-specific timezones. It is critical that all timestamps are converted to UTC before DB storage to prevent alignment issues.

---

## 4. Conclusion

### A. TimescaleDB Schema Design

#### 1. OHLCV Table (`ohlcv_data`)
- **Purpose:** Store historical bar data for EURUSD & GBPUSD across H4, D1, and M15 timeframes.
- **Partitioning:** Partitioned as a TimescaleDB hypertable by `time` with a 1-month interval.
- **Primary Key:** Composite primary key `(time, symbol, timeframe)`.

| Column | PostgreSQL Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `time` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL` | Bar start time (UTC) |
| `symbol` | `VARCHAR(10)` | `NOT NULL` | e.g. "EURUSD", "GBPUSD" |
| `timeframe` | `VARCHAR(5)` | `NOT NULL` | "H4", "D1", "M15" |
| `open` | `DOUBLE PRECISION` | `NOT NULL` | Opening price |
| `high` | `DOUBLE PRECISION` | `NOT NULL` | Highest price |
| `low` | `DOUBLE PRECISION` | `NOT NULL` | Lowest price |
| `close` | `DOUBLE PRECISION` | `NOT NULL` | Closing price |
| `tick_volume` | `BIGINT` | `NOT NULL` | Number of ticks in the bar |
| `spread` | `INTEGER` | `NOT NULL` | Spread in points |
| `real_volume` | `BIGINT` | `NOT NULL` | Volume of actual transactions (often 0 in Forex) |

**DDL SQL:**
```sql
CREATE TABLE IF NOT EXISTS ohlcv_data (
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    tick_volume BIGINT NOT NULL,
    spread INTEGER NOT NULL,
    real_volume BIGINT NOT NULL,
    PRIMARY KEY (time, symbol, timeframe)
);

SELECT create_hypertable('ohlcv_data', 'time', chunk_time_interval => INTERVAL '1 month', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ohlcv_query 
ON ohlcv_data (symbol, timeframe, time DESC);
```

#### 2. Tick Table (`tick_data`)
- **Purpose:** Store tick-by-tick bid/ask prices and volumes for spread calculation and transaction cost modeling.
- **Partitioning:** Partitioned as a TimescaleDB hypertable by `time` with a 1-day interval (due to high volume).
- **Primary Key:** None (to prevent conflicts on duplicate milliseconds).

| Column | PostgreSQL Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `time` | `TIMESTAMP WITH TIME ZONE` | `NOT NULL` | Tick timestamp at second resolution (UTC) |
| `symbol` | `VARCHAR(10)` | `NOT NULL` | e.g. "EURUSD" |
| `bid` | `DOUBLE PRECISION` | `NOT NULL` | Bid price |
| `ask` | `DOUBLE PRECISION` | `NOT NULL` | Ask price |
| `last` | `DOUBLE PRECISION` | `NOT NULL` | Last trade price (0.0 for FX) |
| `volume` | `BIGINT` | `NOT NULL` | Last trade volume |
| `time_msc` | `BIGINT` | `NOT NULL` | Epoch millisecond timestamp |
| `flags` | `INTEGER` | `NOT NULL` | Tick flag bitmask from MT5 |
| `volume_real` | `DOUBLE PRECISION` | `NOT NULL` | High-precision trade volume |

**DDL SQL:**
```sql
CREATE TABLE IF NOT EXISTS tick_data (
    time TIMESTAMP WITH TIME ZONE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    bid DOUBLE PRECISION NOT NULL,
    ask DOUBLE PRECISION NOT NULL,
    last DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    time_msc BIGINT NOT NULL,
    flags INTEGER NOT NULL,
    volume_real DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('tick_data', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ticks_query 
ON tick_data (symbol, time_msc DESC);
```

---

### B. Schema Validation Rules

The ingestion pipeline must run these rules against every fetched DataFrame before syncing to the database:

1. **Null/NaN Validation:**
   - No row may contain `NaN` or `None` values in critical fields (`time`, `symbol`, `open`, `high`, `low`, `close`, `bid`, `ask`).

2. **Logical Boundaries:**
   - Prices (`open`, `high`, `low`, `close`, `bid`, `ask`) must be positive floats.
   - For OHLCV: `high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`.
   - Volumes (`tick_volume`, `real_volume`, `volume`) must be non-negative integers/floats.
   - Spread (`spread`) must be a non-negative integer.

3. **Data Completeness & Sequence Validation:**
   - Timestamps must be strictly monotonically increasing (for OHLCV) or non-decreasing (for ticks).
   - Timeframe gaps must be validated. If a gap exceeds the timeframe's expected duration, check if the gap spans a weekend (Friday 22:00 UTC to Sunday 22:00 UTC). If it is not a weekend, raise a `DataGapError`.

---

### C. Validation Harness Implementation Details

Below is the design and class layout for `validation_harness/ingestion.py`.

```python
import time
import random
import pandas as pd
from typing import Callable, Any, Optional
import MetaTrader5 as mt5
from src.core.db import engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import Table, MetaData

class IngestionValidationError(Exception):
    """Raised when data validation fails."""
    pass

class DataGapError(Exception):
    """Raised when unexpected data gaps are detected."""
    pass

class IngestionValidationHarness:
    def __init__(self, max_retries: int = 5, backoff_factor: float = 2.0, initial_delay: float = 1.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.initial_delay = initial_delay

    def validate_ohlcv_dataframe(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """Runs integrity and logical checks on OHLCV DataFrame."""
        if df is None or df.empty:
            raise IngestionValidationError(f"Empty OHLCV data for {symbol} ({timeframe})")

        # 1. Validate Columns
        required_cols = {'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume'}
        missing = required_cols - set(df.columns)
        if missing:
            raise IngestionValidationError(f"Missing columns: {missing}")

        # 2. Check for NaN/Null
        if df.isna().any().any():
            raise IngestionValidationError("DataFrame contains NaN/Null values")

        # 3. Check Price Bounds
        if not (df[['open', 'high', 'low', 'close']] > 0).all().all():
            raise IngestionValidationError("Prices must be positive values")

        # 4. Check Price Relationships
        if not (df['high'] >= df['low']).all():
            raise IngestionValidationError("High price is lower than Low price")
        if not (df['high'] >= df['open']).all() or not (df['high'] >= df['close']).all():
            raise IngestionValidationError("High price is lower than Open/Close")
        if not (df['low'] <= df['open']).all() or not (df['low'] <= df['close']).all():
            raise IngestionValidationError("Low price is higher than Open/Close")

        # 5. Volume checks
        if not (df['tick_volume'] >= 0).all() or not (df['real_volume'] >= 0).all():
            raise IngestionValidationError("Volume values cannot be negative")

        # 6. Monotonicity
        if not df.index.is_monotonic_increasing:
            raise IngestionValidationError("Timestamps are not monotonically increasing")

    def detect_ohlcv_gaps(self, df: pd.DataFrame, timeframe_delta: pd.Timedelta) -> None:
        """Validates timestamp continuity, ignoring FX weekends."""
        times = df.index
        for i in range(len(times) - 1):
            t1 = times[i]
            t2 = times[i+1]
            diff = t2 - t1
            
            if diff > timeframe_delta:
                # Check if it is a weekend gap: Friday 22:00 UTC to Sunday 22:00 UTC
                # t1 is Friday (weekday 4) and t2 is Sunday/Monday (weekday 6 or 0)
                is_weekend = (t1.weekday() == 4 and t2.weekday() in [6, 0])
                if not is_weekend:
                    raise DataGapError(f"Unexpected gap detected between {t1} and {t2} (Duration: {diff})")

    def execute_with_retry(self, client: Any, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Executes an MT5 client query with automatic reconnection and exponential backoff."""
        delay = self.initial_delay
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Ensure connection is established and server is active
                if not client.connected or not self._is_terminal_connected():
                    print(f"[Attempt {attempt}] Connection lost/inactive. Reconnecting...")
                    client.disconnect()
                    if not client.connect():
                        raise ConnectionError("Failed to initialize MT5 terminal.")
                
                result = func(*args, **kwargs)
                if result is not None:
                    return result
                
                err_code = mt5.last_error()
                print(f"[Attempt {attempt}] Query returned None. MT5 Error Code: {err_code}")
                
            except Exception as e:
                print(f"[Attempt {attempt}] Exception encountered: {e}")
                client.connected = False
            
            if attempt < self.max_retries:
                sleep_time = delay * random.uniform(0.8, 1.2)
                print(f"Retrying in {sleep_time:.2f} seconds...")
                time.sleep(sleep_time)
                delay *= self.backoff_factor

        raise ConnectionError(f"MT5 action failed after {self.max_retries} attempts.")

    def _is_terminal_connected(self) -> bool:
        info = mt5.terminal_info()
        return info is not None and info.connected

    def bulk_upsert_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> None:
        """Performs a bulk Postgres upsert on OHLCV data to prevent duplicate primary keys."""
        if df.empty:
            return
        
        df = df.copy()
        if 'time' not in df.columns:
            df = df.reset_index()
        df['symbol'] = symbol
        df['timeframe'] = timeframe

        records = df.to_dict(orient='records')
        metadata = MetaData()
        ohlcv_table = Table('ohlcv_data', metadata, autoload_with=engine)

        insert_stmt = insert(ohlcv_table).values(records)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=['time', 'symbol', 'timeframe'],
            set_={
                'open': insert_stmt.excluded.open,
                'high': insert_stmt.excluded.high,
                'low': insert_stmt.excluded.low,
                'close': insert_stmt.excluded.close,
                'tick_volume': insert_stmt.excluded.tick_volume,
                'spread': insert_stmt.excluded.spread,
                'real_volume': insert_stmt.excluded.real_volume
            }
        )

        with engine.begin() as conn:
            conn.execute(upsert_stmt)
```

---

### D. Testing & Mocking Strategy

To test the ingestion client and the validation harness programmatically without requiring a live MT5 instance (which runs only on Windows and requires GUI context), we must mock the `MetaTrader5` module.

Below is a proposed `pytest` unit test setup:

```python
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime

# Import components (assuming layout)
# from src.layers.l0_ingestion.mt5_client import MT5Client
# from validation_harness.ingestion import IngestionValidationHarness, IngestionValidationError

@pytest.fixture
def mock_mt5():
    with patch('src.layers.l0_ingestion.mt5_client.mt5') as mocked:
        yield mocked

@pytest.fixture
def sample_ohlcv_df():
    data = {
        'open': [1.1800, 1.1810],
        'high': [1.1850, 1.1860],
        'low': [1.1790, 1.1800],
        'close': [1.1810, 1.1820],
        'tick_volume': [1500, 1600],
        'spread': [12, 11],
        'real_volume': [0, 0]
    }
    times = pd.to_datetime(['2026-06-19 12:00:00', '2026-06-19 16:00:00'])
    df = pd.DataFrame(data, index=times)
    df.index.name = 'time'
    return df

def test_validation_success(sample_ohlcv_df):
    harness = IngestionValidationHarness()
    # Should not raise exception
    harness.validate_ohlcv_dataframe(sample_ohlcv_df, 'EURUSD', 'H4')

def test_validation_negative_price(sample_ohlcv_df):
    harness = IngestionValidationHarness()
    sample_ohlcv_df.loc[sample_ohlcv_df.index[0], 'close'] = -1.1800
    with pytest.raises(IngestionValidationError, match="Prices must be positive values"):
        harness.validate_ohlcv_dataframe(sample_ohlcv_df, 'EURUSD', 'H4')

def test_validation_invalid_high_low(sample_ohlcv_df):
    harness = IngestionValidationHarness()
    # Make low higher than high
    sample_ohlcv_df.loc[sample_ohlcv_df.index[0], 'low'] = 1.1900
    with pytest.raises(IngestionValidationError, match="High price is lower than Low price"):
        harness.validate_ohlcv_dataframe(sample_ohlcv_df, 'EURUSD', 'H4')

def test_validation_weekend_gap_ignored(sample_ohlcv_df):
    harness = IngestionValidationHarness()
    # Friday 20:00 UTC to Sunday 22:00 UTC
    times = pd.to_datetime(['2026-06-19 20:00:00', '2026-06-21 22:00:00'])  # Friday to Sunday
    df = pd.DataFrame({
        'open': [1.18, 1.18], 'high': [1.19, 1.19], 'low': [1.17, 1.17], 'close': [1.18, 1.18],
        'tick_volume': [100, 100], 'spread': [10, 10], 'real_volume': [0, 0]
    }, index=times)
    df.index.name = 'time'
    
    # Should not raise DataGapError because it's a weekend
    harness.detect_ohlcv_gaps(df, pd.Timedelta(hours=4))

def test_validation_weekday_gap_raises(sample_ohlcv_df):
    harness = IngestionValidationHarness()
    # Tuesday 12:00 UTC to Tuesday 20:00 UTC (8 hour gap for H4)
    times = pd.to_datetime(['2026-06-16 12:00:00', '2026-06-16 20:00:00'])
    df = pd.DataFrame({
        'open': [1.18, 1.18], 'high': [1.19, 1.19], 'low': [1.17, 1.17], 'close': [1.18, 1.18],
        'tick_volume': [100, 100], 'spread': [10, 10], 'real_volume': [0, 0]
    }, index=times)
    df.index.name = 'time'
    
    with pytest.raises(DataGapError):
        harness.detect_ohlcv_gaps(df, pd.Timedelta(hours=4))

@patch('src.layers.l0_ingestion.mt5_client.mt5')
def test_execute_with_retry_reconnect(mock_mt5_lib):
    from src.layers.l0_ingestion.mt5_client import MT5Client
    client = MT5Client()
    
    # Mocking terminal_info and initialize
    mock_terminal_info = MagicMock()
    mock_terminal_info.connected = True
    mock_mt5_lib.terminal_info.return_value = mock_terminal_info
    mock_mt5_lib.initialize.return_value = True
    
    harness = IngestionValidationHarness(max_retries=3, initial_delay=0.01)
    
    # Define a query function that fails once then succeeds
    call_count = 0
    def mock_query():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # First call fails
        return [1, 2, 3]  # Second call succeeds
        
    result = harness.execute_with_retry(client, mock_query)
    
    assert result == [1, 2, 3]
    assert call_count == 2
```

---

## 5. Verification Method

To verify the schema design and the reconnect logic:

1. **Verify Unit Tests:**
   Place the mock tests inside `tests/layers/l0_ingestion/test_validation.py` and run the command:
   ```powershell
   pytest tests/layers/l0_ingestion/test_validation.py
   ```
   Ensure all tests pass, validating that:
   - Data with negative prices or invalid relations is correctly rejected.
   - Weekend gaps do not raise errors, while weekday gaps do.
   - Connection failure triggers a reconnect attempt.

2. **Verify Database Hypertable DDL:**
   Connect to the local TimescaleDB instance and run the DDL schema commands. Execute:
   ```sql
   SELECT * FROM timescaledb_information.hypertables;
   ```
   Confirm that `ohlcv_data` has a 1-month chunk interval, and `tick_data` has a 1-day chunk interval.
