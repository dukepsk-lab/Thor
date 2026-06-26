# Handoff Report: Ingestion Milestone (gen 3) Review

## 1. Observation

### Concurrency and Thread Safety
In `src/layers/l0_ingestion/mt5_client.py`:
- A global instance `mt5_client = MT5Client()` is initialized (line 149).
- Inside `MT5Client`, a `threading.Lock()` instance is created as `self._lock` (line 12).
- Thread-safety is achieved by wrapping individual MT5 API calls (e.g. `mt5.copy_rates_range`, `mt5.copy_ticks_range`, `mt5.initialize`, `mt5.shutdown`, and `mt5.last_error`) within `with self._lock:` contexts.
- Specifically:
  - Line 94: `with self._lock: rates = mt5.copy_rates_range(...)`
  - Line 126: `with self._lock: ticks = mt5.copy_ticks_range(...)`
  - Line 41: `with self._lock: initialized = mt5.initialize(...)`
- However, connection checking and connection initialization in `connect()` are executed under separate lock acquisitions, creating a minor race condition window where multiple threads could invoke `mt5.initialize()` sequentially (lines 35-48).

### Database Batching
In `src/layers/l0_ingestion/db_sync.py`:
- In both `sync_ohlcv_to_timescale` (line 118) and `sync_ticks_to_timescale` (line 207), a chunk size of 5,000 is defined:
  ```python
  chunk_size = 5000
  ```
- Batch writes are executed in chunks of 5,000 records using SQLAlchemy Core's parameter binding:
  ```python
  with engine.begin() as conn:
      for i in range(0, len(records), chunk_size):
          conn.execute(query, records[i:i + chunk_size])
  ```
- The fallback code using Pandas also respects this chunk size (line 154 and line 218):
  ```python
  df.to_sql(..., chunksize=chunk_size)
  ```

### Timezone Awareness
In `src/layers/l0_ingestion/db_sync.py`:
- Database schemas for PostgreSQL use `TIMESTAMP WITH TIME ZONE NOT NULL` (lines 24 and 43):
  ```sql
  CREATE TABLE IF NOT EXISTS ohlcv_data (
      time TIMESTAMP WITH TIME ZONE NOT NULL,
      ...
  )
  ```
- In python, `pd.to_datetime(df['time'])` is used, and elements are converted to native Python datetimes using `to_pydatetime()`.
- However, there is no explicit timezone localization or conversion (e.g. `.dt.tz_localize('UTC')`) performed in `db_sync.py`. The datetimes passed to the database are timezone-naive.

### Tick Deduplication
In `src/layers/l0_ingestion/db_sync.py`, tick deduplication is implemented via maximum `time_msc` filtering (lines 183-195):
- The maximum `time_msc` is retrieved from the database:
  ```python
  res = conn.execute(
      text("SELECT MAX(time_msc) FROM tick_data WHERE symbol = :symbol"),
      {"symbol": symbol}
  ).scalar()
  ```
- Incoming ticks are filtered using:
  ```python
  df = df[df['time_msc'] > max_time_msc]
  ```
- If the database query fails, `max_time_msc` defaults to `0`, resulting in no filtering and potential duplicate insertions.
- Ticks having the exact same millisecond timestamp as `max_time_msc` but not yet written will be dropped.

---

## 2. Logic Chain

1. **Locking Adequacy**: Because MT5 is a C-based library that is notoriously non-thread-safe, serialization of API calls is required. Guarding each call with a mutex lock (`self._lock`) satisfies this. However, since the state check `self.connected` and re-connection are non-atomic, parallel threads might perform redundant initializations.
2. **Database Batching**: The database syncing routines slice the list of dictionaries or parameters using `records[i:i + chunk_size]`, where `chunk_size = 5000`. This matches the requirement of batching writes in chunks of 5,000.
3. **Timezone Conversion**: When a timezone-naive `datetime` is written to a `TIMESTAMP WITH TIME ZONE` column in PostgreSQL, PostgreSQL converts it using the database session's default timezone offset. If the PostgreSQL server or active session timezone is set to anything other than UTC (e.g. server local time), the timestamps will be incorrectly converted and shifted, causing timezone-drift bugs.
4. **Tick Deduplication**: High-frequency ticks can share the same millisecond timestamp (`time_msc`). If a fetch boundaries at `time_msc = X`, the query `SELECT MAX(time_msc)` will return `X`. Any remaining ticks with `time_msc = X` fetched in the next batch will be filtered out by `df['time_msc'] > max_time_msc`, causing permanent loss of legitimate tick data. Additionally, if two ingestion tasks run concurrently, they can read the same max `time_msc` and write duplicate ticks since the `tick_data` table lacks a unique constraint or primary key.

---

## 3. Caveats

- We assumed the MT5 library's C-bindings do not internally manage thread pools that bypass our lock. If the underlying MetaTrader5 client has internal async workers, further process-level isolation might be needed.
- Testing of timezone behavior was performed on SQLite which uses naive `TIMESTAMP` representation, so the timezone shift vulnerability was not detected by the test suite.

---

## 4. Conclusion

The verdict is **REQUEST_CHANGES** due to major risks identified in timezone handling and tick deduplication logic. While the basic mechanics of locking and batching conform to specifications and the test suite passes, the implementation has significant vulnerabilities:
1. **Timezone Shift Vulnerability**: Lack of explicit UTC localization for naive datetimes.
2. **Tick Data Loss Vulnerability**: Loss of sub-millisecond duplicate-time ticks due to strict `>` filtering.
3. **Race Conditions in Deduplication**: Concurrent writes or database failures can cause duplicates due to read-then-write logic and missing unique constraints.

---

## 5. Verification Method

To run the validation suite:
```powershell
pytest
```
Expected output: `89 passed`

To verify the timezone shift, run a script inserting timezone-naive datetimes into a Postgres database with a non-UTC session timezone, and check if the retrieved timestamps are modified.

---

# Quality Review Report

## Review Summary

**Verdict**: REQUEST_CHANGES

## Findings

### [Major] Finding 1: Timezone Shift Vulnerability
- **What**: Timezone-naive datetimes are sent to PostgreSQL `TIMESTAMP WITH TIME ZONE` columns.
- **Where**: `src/layers/l0_ingestion/db_sync.py`, lines 103-104 and 169-170.
- **Why**: PostgreSQL session settings will interpret naive datetimes in the session's local timezone. If this timezone is not UTC, the database will shift the timestamps, corrupting historical time-series data.
- **Suggestion**: Explicitly localize DatetimeIndexes/datetimes to UTC in Python before syncing:
  ```python
  df['time'] = pd.to_datetime(df['time']).dt.tz_localize('UTC')
  ```

### [Major] Finding 2: Tick Data Loss at Boundary Milliseconds
- **What**: Strict `>` filtering of ticks based on `max_time_msc`.
- **Where**: `src/layers/l0_ingestion/db_sync.py`, line 195.
- **Why**: High-frequency ticks can occur within the same millisecond. Strict `>` filtering will drop any new ticks that share the millisecond of the last imported tick.
- **Suggestion**: Implement deduplication using a hash of the entire tick row or a combination of `time_msc` and other columns (e.g. sequence ID or bid/ask values).

### [Minor] Finding 3: Non-Atomic Connection and State Checking
- **What**: Lock is released and re-acquired between connection check and initialization in `connect()`.
- **Where**: `src/layers/l0_ingestion/mt5_client.py`, lines 35-48.
- **Why**: Allows minor race conditions where concurrent threads attempt redundant initializations.
- **Suggestion**: Enclose the entire connection check and initialization logic inside a single `with self._lock:` block.

---

## Verified Claims

- **Batching chunk size is 5,000** → verified via inspecting `db_sync.py` → **PASS**
- **Pg tables use TIMESTAMPTZ** → verified via inspecting `db_sync.py` SQL schemas → **PASS**
- **MT5 calls are locked** → verified via inspecting `mt5_client.py` → **PASS**
- **Test suite runs successfully** → verified by running `pytest` → **PASS (89 tests passed)**

---

## Coverage Gaps

- **Database integration tests** — risk level: MEDIUM — The test suite uses SQLite in-memory databases, which hides the timezone interpretation behavior of PostgreSQL. Recommendation: Implement integration tests using a local PostgreSQL container or service to catch dialect-specific bugs.

---

# Adversarial Review Report

## Challenge Summary

**Overall risk assessment**: MEDIUM

## Challenges

### [High] Challenge 1: Data Loss under High-Frequency Tick Ingestion
- **Assumption challenged**: Ticks have strictly unique `time_msc` values.
- **Attack scenario**: The system fetches tick history in chunks. Batch 1 contains a tick at millisecond `1672531200100`. Batch 2 starts fetching from millisecond `1672531200100` and contains two other ticks at the same millisecond. Since `max_time_msc` is `1672531200100`, the filter `df['time_msc'] > max_time_msc` discards both ticks.
- **Blast radius**: Loss of tick data at boundary timestamps, leading to inaccurate spread and cost calculations in the backtest engine.
- **Mitigation**: Fetch and query last N ticks at the boundary to perform row-wise deduplication instead of strict timestamp filtering.

### [Medium] Challenge 2: Duplicate Insertion on Database Queries Failures
- **Assumption challenged**: The `SELECT MAX(time_msc)` query will never fail.
- **Attack scenario**: A temporary connection dropout or deadlock causes the query to fail. The exception handler catches it, sets `max_time_msc = 0`, and proceeds to insert the entire batch.
- **Blast radius**: Massive duplication of ticks in the database, because `tick_data` has no unique constraint or primary key.
- **Mitigation**: Instead of defaulting to 0, raise the exception and abort the sync to maintain database integrity.

---

## Stress Test Results

- **Multiple ticks in same millisecond** → Ticks with `time_msc == max_time_msc` are filtered out → **FAIL (Data Loss)**
- **Database read failure during sync** → `max_time_msc` defaults to 0 and inserts all ticks → **FAIL (Duplicate Insertion)**

---

## Unchallenged Areas

- **ZeroMQ connections in MQL5 script** — out of scope for Reviewer 2.
