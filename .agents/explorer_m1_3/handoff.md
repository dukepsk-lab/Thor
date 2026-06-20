# Ingestion Milestone Testing Strategy Report

## 1. Observation
We observed the following files and code patterns in the workspace:
1. **MT5 Client (`src/layers/l0_ingestion/mt5_client.py`)**:
   - Imports `MetaTrader5 as mt5` (line 1).
   - In `connect(self)` (lines 11-25), calls `mt5.initialize` passing credentials from `settings`.
   - In `fetch_ohlcv` (lines 35-51) and `fetch_ticks` (lines 53-68), retrieves rates/ticks using `mt5.copy_rates_range` and `mt5.copy_ticks_range`, converting results to `pd.DataFrame` and changing the `'time'` column to datetime index.
2. **Database Synchronizer (`src/layers/l0_ingestion/db_sync.py`)**:
   - Imports SQLAlchemy `engine` from `src.core.db` (line 3).
   - In `sync_ohlcv_to_timescale` (lines 5-21) and `sync_ticks_to_timescale` (lines 22-34), writes dataframes to database using `df.to_sql('ohlcv_data', engine, ...)` and `df.to_sql('tick_data', engine, ...)`.
   - In `init_hypertables` (lines 35-44), contains commented-out Postgres-specific commands (`SELECT create_hypertable(...)`).
3. **Data Ingestion Interface (`.agents/orchestrator/PROJECT.md`)**:
   - Specifies the following interface contracts for `validation_harness/ingestion.py` (lines 47-62):
     ```python
     def fetch_historical_ohlcv(symbol: str, timeframe: int, start: datetime, end: datetime) -> pd.DataFrame:
         """
         Returns DataFrame with Index: DatetimeIndex (named 'time')
         Columns: open (float), high (float), low (float), close (float), tick_volume (int), spread (int), real_volume (int)
         Raises ConnectionError if MT5 is unavailable.
         """

     def fetch_historical_ticks(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
         """
         Returns DataFrame with Index: DatetimeIndex (named 'time')
         Columns: bid (float), ask (float), last (float), volume (float), flags (int)
         Raises ConnectionError if MT5 is unavailable.
         """
     ```
4. **Environment Limitations (`requirements.txt`)**:
   - The system depends on `MetaTrader5` (line 3), which compiles exclusively on Windows and requires a running MT5 Windows terminal to execute, meaning tests run on non-Windows (e.g. Linux CI/CD) or headless environments will fail to import or initialize.

---

## 2. Logic Chain
To implement a robust testing strategy for `validation_harness/ingestion.py` without requiring a live terminal or DB connection, we reason as follows:
1. **Dynamic Module Patching**: Because the official `MetaTrader5` package cannot be imported on non-Windows systems, we must mock the `MetaTrader5` module inside `sys.modules` before importing any client files. This bypasses `ImportError` on Linux/macOS and isolates the test runner.
2. **Realistic MT5 Data Mocking**: Since `mt5_client.py` constructs a `pd.DataFrame` directly from the object returned by `copy_rates_range` and `copy_ticks_range` (which are numpy structured arrays in MT5), our mock must return numpy structured arrays with identical field definitions (`time`, `open`, `high`, `low`, `close`, `tick_volume`, `spread`, `real_volume` for rates; and `time`, `bid`, `ask`, `last`, `volume`, `time_msc`, `flags`, `volume_real` for ticks).
3. **In-Memory SQLite Database Gating**: To test the database synchronization without a live TimescaleDB database, we can patch SQLAlchemy's `engine` with a `sqlite:///:memory:` engine.
4. **Dialect-Safe Hypertable Initialization**: Because SQLite does not support Postgres-specific functions (like `create_hypertable`), we must ensure the hypertable creation logic checks the database dialect and executes Postgres commands only when connected to a PostgreSQL/TimescaleDB engine.
5. **Execution Sleep Mitigation**: The ingestion module is expected to implement exponential backoff retry on connection loss. To avoid delaying tests by seconds or minutes, we must patch `time.sleep` with a mock stub to make the test suite execute instantly while still asserting that correct backoff values were applied.

---

## 3. Caveats
- **SQLite Dialect Differences**: SQLite does not strictly enforce some constraints (like varchar lengths or decimal scales) and does not support full Postgres upsert operations (`ON CONFLICT`). If the implementation moves to raw SQL upserts instead of pandas `to_sql`, tests using SQLite in-memory might need to be adjusted or run against a real Postgres container (e.g., using `testcontainers-postgres`).
- **Timezone Handling**: MetaTrader 5 terminal times are usually in the broker's local timezone (e.g., UTC+2 or UTC+3). Our mock generates UTC timestamps. The live system must handle timezone normalization, which should be verified in integration tests.

---

## 4. Conclusion
We propose the following testing architecture and mock setups to be implemented in `validation_harness/tests/`:

### A. MetaTrader 5 Mock Setup
Create a fixture in `conftest.py` that intercepts the `MetaTrader5` import and provides configurable behaviors (success, fail, connection lost):

```python
# validation_harness/tests/conftest.py
import sys
import pytest
from unittest.mock import MagicMock
import numpy as np

class MockMetaTrader5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408
    COPY_TICKS_ALL = 3

    def __init__(self):
        self._connected = False
        self._error_code = 1
        self._error_desc = "Success"
        self.mock_rates = None
        self.mock_ticks = None

    def initialize(self, path=None, login=0, password="", server=""):
        self._connected = True
        return True

    def shutdown(self):
        self._connected = False
        return True

    def last_error(self):
        return (self._error_code, self._error_desc)

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not self._connected:
            self._error_code = -1
            self._error_desc = "Not connected"
            return None
        
        if self.mock_rates is not None:
            return self.mock_rates

        # Default synthetic rates
        ts_start = int(date_from.timestamp())
        ts_end = int(date_to.timestamp())
        times = [ts_start, (ts_start + ts_end) // 2, ts_end]
        
        rates_dtype = [
            ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'),
            ('close', 'f8'), ('tick_volume', 'i8'), ('spread', 'i8'), ('real_volume', 'i8')
        ]
        
        data = [
            (times[0], 1.0800, 1.0850, 1.0750, 1.0810, 1500, 15, 0),
            (times[1], 1.0810, 1.0870, 1.0790, 1.0840, 2000, 12, 0),
            (times[2], 1.0840, 1.0890, 1.0820, 1.0850, 1800, 18, 0)
        ]
        return np.array(data, dtype=rates_dtype)

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        if not self._connected:
            self._error_code = -1
            self._error_desc = "Not connected"
            return None

        if self.mock_ticks is not None:
            return self.mock_ticks

        # Default synthetic ticks
        ts_start = int(date_from.timestamp())
        ts_end = int(date_to.timestamp())
        times = [ts_start, (ts_start + ts_end) // 2, ts_end]
        
        ticks_dtype = [
            ('time', 'i8'), ('bid', 'f8'), ('ask', 'f8'), ('last', 'f8'),
            ('volume', 'f8'), ('time_msc', 'i8'), ('flags', 'i8'), ('volume_real', 'f8')
        ]
        
        data = [
            (times[0], 1.0800, 1.0802, 0.0, 1.0, times[0]*1000, flags, 0.0),
            (times[1], 1.0810, 1.0812, 0.0, 2.0, times[1]*1000, flags, 0.0),
            (times[2], 1.0820, 1.0822, 0.0, 1.5, times[2]*1000, flags, 0.0)
        ]
        return np.array(data, dtype=ticks_dtype)

# Inject mock into sys.modules before importing ingestion
mock_mt5_lib = MockMetaTrader5()
sys.modules['MetaTrader5'] = mock_mt5_lib

@pytest.fixture
def mt5_mock():
    return mock_mt5_lib
```

### B. TimescaleDB/SQLite Mock Setup
Provide an in-memory SQLite setup that pre-creates the hypertables using standard SQL syntax:

```python
# validation_harness/tests/conftest.py (continued)
from sqlalchemy import create_engine, text
from src.core import db as core_db
from src.layers.l0_ingestion import db_sync as l0_db_sync

@pytest.fixture
def mock_sqlite_engine(monkeypatch):
    # 1. Create in-memory SQLite database
    sqlite_engine = create_engine("sqlite:///:memory:")
    
    # 2. Pre-create schemas
    with sqlite_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE ohlcv_data (
                time TIMESTAMP NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                timeframe VARCHAR(10) NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                tick_volume INTEGER,
                spread INTEGER,
                real_volume INTEGER,
                PRIMARY KEY (time, symbol, timeframe)
            )
        """))
        conn.execute(text("""
            CREATE TABLE tick_data (
                time TIMESTAMP NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                bid REAL NOT NULL,
                ask REAL NOT NULL,
                last REAL,
                volume REAL,
                flags INTEGER,
                PRIMARY KEY (time, symbol)
            )
        """))
        conn.commit()

    # 3. Patch engine & SessionLocal in DB and Sync modules
    monkeypatch.setattr(core_db, "engine", sqlite_engine)
    monkeypatch.setattr(l0_db_sync, "engine", sqlite_engine)
    
    from sqlalchemy.orm import sessionmaker
    MockSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)
    monkeypatch.setattr(core_db, "SessionLocal", MockSessionLocal)
    
    # Patch init_hypertables to avoid Postgres-specific syntax error
    monkeypatch.setattr(l0_db_sync, "init_hypertables", lambda: None)
    
    yield sqlite_engine
    sqlite_engine.dispose()
```

### C. Programmatic Unit & Integration Tests
Define tests inside `validation_harness/tests/test_ingestion.py` covering all execution paths:

```python
# validation_harness/tests/test_ingestion.py
import pytest
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch, MagicMock
from validation_harness.ingestion import (
    fetch_historical_ohlcv,
    fetch_historical_ticks,
    validate_ohlcv_schema,
    validate_ticks_schema
)
from src.layers.l0_ingestion.db_sync import sync_ohlcv_to_timescale, sync_ticks_to_timescale

# 1. Connection Retry Logic Test
def test_connection_reconnect_backoff(mt5_mock):
    # Simulate connection failures followed by a success
    failures = [False, False, True]
    
    def mock_init(*args, **kwargs):
        val = failures.pop(0)
        mt5_mock._connected = val
        if not val:
            mt5_mock._error_code = -1001
            mt5_mock._error_desc = "Terminal not running"
        return val
        
    with patch.object(mt5_mock, "initialize", side_effect=mock_init) as mock_init_func, \
         patch("time.sleep") as mock_sleep:
         
        # Trigger client connection
        from src.layers.l0_ingestion.mt5_client import mt5_client
        connected = mt5_client.connect()
        
        assert connected is True
        assert mock_init_func.call_count == 3
        # Assert sleep was called with progressive backoff (e.g. 1s, 2s)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

# 2. OHLCV Ingestion & Schema Verification Test
def test_fetch_ohlcv_contract_compliance(mt5_mock):
    mt5_mock._connected = True
    start = datetime(2026, 6, 1)
    end = datetime(2026, 6, 2)
    
    df = fetch_historical_ohlcv("EURUSD", mt5_mock.TIMEFRAME_H4, start, end)
    
    # Verify index
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.name == 'time'
    
    # Verify columns and types
    expected_cols = {'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume'}
    assert set(df.columns) == expected_cols
    for col in ['open', 'high', 'low', 'close']:
        assert pd.api.types.is_float_dtype(df[col])
    for col in ['tick_volume', 'spread', 'real_volume']:
        assert pd.api.types.is_integer_dtype(df[col])

# 3. Connection Error propagation Test
def test_fetch_ohlcv_when_disconnected(mt5_mock):
    mt5_mock.shutdown()  # force disconnected
    
    with pytest.raises(ConnectionError):
        fetch_historical_ohlcv("EURUSD", mt5_mock.TIMEFRAME_H4, datetime.now(), datetime.now())

# 4. Database Sync Integration Test
def test_db_sync_integration(mock_sqlite_engine, mt5_mock):
    mt5_mock._connected = True
    start = datetime(2026, 6, 1)
    end = datetime(2026, 6, 2)
    
    # 1. Fetch
    df = fetch_historical_ohlcv("EURUSD", mt5_mock.TIMEFRAME_H4, start, end)
    
    # 2. Sync to DB
    sync_ohlcv_to_timescale(df, "EURUSD", "H4")
    
    # 3. Query back from SQLite to verify insertion
    db_df = pd.read_sql_table("ohlcv_data", mock_sqlite_engine)
    assert len(db_df) == 3
    assert (db_df["symbol"] == "EURUSD").all()
    assert (db_df["timeframe"] == "H4").all()
    assert "open" in db_df.columns
```

---

## 5. Verification Method
1. **Directory Integrity Check**:
   - Create mock files (e.g. `validation_harness/tests/conftest.py` and `validation_harness/tests/test_ingestion.py`) containing the suggested code structures.
2. **Execute Tests**:
   - Run `pytest validation_harness/tests/` to verify tests pass inside the environment.
3. **Behavior Verification**:
   - Verify that running tests does not require a running MetaTrader 5 terminal.
   - Verify that running tests does not require a running PostgreSQL/TimescaleDB container.
   - Verify that tests run successfully on Linux/macOS runtimes.
