# Review and Handoff Report — Ingestion Milestone Review

## 1. Observation

### Reviewed File Paths
- `validation_harness/ingestion.py`
- `src/layers/l0_ingestion/mt5_client.py`
- `src/layers/l0_ingestion/db_sync.py`

### Test Executions and Outputs
The test suites were executed successfully to verify syntax, correctness, and integration:
1. Running main test suite via `pytest`:
   ```
   83 passed, 1 warning in 20.06s
   ```
2. Running progress-specific test suite via `pytest validation_harness/test_ingestion_prog.py`:
   ```
   10 passed, 1 warning in 1.61s
   ```

### Specific Code Observations

#### Observation 1 (Tick Data Loss)
In `src/layers/l0_ingestion/db_sync.py` lines 46 & 79, the tick tables are initialized with `PRIMARY KEY (time, symbol, time_msc)`.
In lines 189 & 195, insertions utilize `ON CONFLICT (time, symbol, time_msc) DO NOTHING` (PostgreSQL) and `INSERT OR IGNORE` (SQLite):
```python
186:         query = text("""
187:             INSERT INTO tick_data (time, symbol, bid, ask, last, volume, time_msc, flags, volume_real)
188:             VALUES (:time, :symbol, :bid, :ask, :last, :volume, :time_msc, :flags, :volume_real)
189:             ON CONFLICT (time, symbol, time_msc) DO NOTHING;
190:         """)
```
And:
```python
194:         query = text("""
195:             INSERT OR IGNORE INTO tick_data (time, symbol, bid, ask, last, volume, time_msc, flags, volume_real)
196:             VALUES (:time, :symbol, :bid, :ask, :last, :volume, :time_msc, :flags, :volume_real);
197:         """)
```

#### Observation 2 (MT5 Connection/Status Defect)
In `src/layers/l0_ingestion/mt5_client.py` lines 20-22 and 47-51:
```python
19:             if self.connected:
20:                 info = mt5.terminal_info()
21:                 if info is not None:
22:                     return True
```
And:
```python
47:         info = mt5.terminal_info()
48:         if info is None:
49:             self.connected = False
50:             return False
51:         return True
```
Neither of these checks check the `connected` attribute of the `TerminalInfo` named tuple returned by `mt5.terminal_info()` (i.e. `info.connected`), which represents broker trade server connectivity.

#### Observation 3 (Schema Validation Code Ignored)
In `validation_harness/ingestion.py` lines 395-408:
```python
395:     df = mt5_client.fetch_ohlcv(symbol, timeframe, start, end)
396:     if df is None:
397:         raise RuntimeError(f"Failed to fetch OHLCV data for {symbol} after retries/reconnections.")
398: 
399:     # Validate and clean schema (modifies df in-place)
400:     validate_ohlcv_schema(df)
```
The return value of `validate_ohlcv_schema(df)` (which is `False` if validation fails/empty) is ignored, and syncing proceeds immediately in line 406: `sync_ohlcv_to_timescale(df, symbol, tf_str)`.

#### Observation 4 (Missing Sorting and Duplicates Checks in New Validators)
In `validation_harness/ingestion.py` lines 211-307 (`validate_ohlcv_schema`) and lines 309-388 (`validate_tick_schema`), there are no calls to check for duplicates (`df.index.duplicated().any()`) or monotonic index ordering (`df.index.is_monotonic_increasing`).

#### Observation 5 (Redundant DDL Operations)
In `src/layers/l0_ingestion/db_sync.py` lines 104 & 175:
`init_hypertables()` is called at the beginning of every call to `sync_ohlcv_to_timescale` and `sync_ticks_to_timescale`.

---

## 2. Logic Chain

1. **Loss of Tick Data**:
   - Market volatility and liquid sessions (such as the London/New York session overlap) frequently produce multiple ticks per millisecond for a given symbol (Observation 1).
   - Because the primary key is restricted to `(time, symbol, time_msc)`, these ticks share the exact same key.
   - The SQL engine executes `ON CONFLICT DO NOTHING` or `INSERT OR IGNORE` (Observation 1), silently dropping all ticks but the first one in the batch.
   - This leads to systematic loss of tick-level price changes, impairing realized volatility and spread analysis.

2. **Connection Status Defect**:
   - `mt5.terminal_info()` returns a named tuple `TerminalInfo` as long as the MetaTrader 5 application itself is running locally (Observation 2).
   - If the connection between the MT5 terminal and the broker's trade server drops (e.g., due to authentication failures or network loss), `terminal_info()` still returns a non-None tuple, but its `connected` attribute is `False`.
   - Because the code only checks `info is not None`, it incorrectly assumes the client is connected to the broker (Observation 2).
   - Consequently, `self.connected` remains `True` and bypasses the reconnection trigger (`if not self.connected or mt5.terminal_info() is None:`) inside `fetch_ohlcv` and `fetch_ticks`, trapping the client in a loop of failing data calls without trying to reconnect.

3. **Ignored Schema Validation Results**:
   - If `validate_ohlcv_schema` or `validate_tick_schema` logs warnings and returns `False` (Observation 3), the fetch functions ignore the validation status and immediately attempt to write the data to the database.
   - This defeats the defensive validation gate: invalid or malformed data is synced to the database instead of being rejected or quarantined.

4. **Inefficient DDL Operations**:
   - Data ingestion runs continuously in live trading, invoking syncing functions frequently (Observation 5).
   - Calling `init_hypertables()` on each sync executes multiple `CREATE TABLE IF NOT EXISTS` and `SELECT create_hypertable(...)` queries.
   - In PostgreSQL, check queries and table creation checks require table locks (AccessExclusiveLock for creation), leading to query blockages, transaction overhead, and resource exhaustion.

---

## 3. Caveats

- We did not test real, live broker connections (due to `CODE_ONLY` network and hardware constraints), but verified the connection logic via mocked MT5 test suite outcomes.
- We assumed that TimescaleDB continuous aggregates are set up correctly elsewhere; we did not examine the downstream aggregate queries.

---

## 4. Conclusion & Review Verdict

**Verdict**: **REQUEST_CHANGES**

The ingestion layer works correctly under ideal mock scenarios but presents major weaknesses under live-market stress, broker connection drops, and high-frequency tick throughput. Key fixes are required before proceeding to production.

### Findings

#### [Critical] Finding 1: Tick Data Loss under Same-Millisecond Collisions
- **What**: Legitimate tick records occurring in the same millisecond are dropped.
- **Where**: `src/layers/l0_ingestion/db_sync.py` lines 46, 79, 189, and 195.
- **Why**: Composite key is restricted to `time_msc`, causing database insertions to silently drop colliding records.
- **Suggestion**: Remove/relax the primary key constraint on ticks or expand the composite key to include price metrics.

#### [Critical] Finding 2: False Positive Connectivity Status Check
- **What**: MT5Client fails to detect connection drops between the terminal and broker server.
- **Where**: `src/layers/l0_ingestion/mt5_client.py` lines 20-22 and 47-51.
- **Why**: The code only checks `info is not None` instead of inspecting `info.connected`.
- **Suggestion**: Modify checks to: `if info is not None and info.connected:`

#### [Major] Finding 3: Validation Outcome Ignored in Historic Ingestion
- **What**: Ingestion proceeds to sync data to TimescaleDB even if schema validation fails.
- **Where**: `validation_harness/ingestion.py` lines 400 and 420.
- **Why**: Return value of schema validators is discarded.
- **Suggestion**: Raise a `ValueError` or quarantine data if `validate_ohlcv_schema(df)` or `validate_tick_schema(df)` returns `False`.

#### [Major] Finding 4: Missing Sort & Duplicate Checking in Schema Validators
- **What**: `validate_ohlcv_schema` and `validate_tick_schema` do not verify sorted order or duplicate timestamps.
- **Where**: `validation_harness/ingestion.py` lines 211 and 309.
- **Why**: Lacks chronological checking and deduplication logic present in the legacy validation harness.
- **Suggestion**: Add `.sort_index(inplace=True)` and check/drop duplicated timestamps.

#### [Minor] Finding 5: Redundant Hypertable Creation DDL Checks
- **What**: Table creation logic runs on every sync batch.
- **Where**: `src/layers/l0_ingestion/db_sync.py` lines 104 and 175.
- **Why**: `init_hypertables()` is called on every write.
- **Suggestion**: Initialize hypertables once at startup or via migrations.

---

## 5. Adversarial Challenge Report

**Overall Risk Assessment**: **MEDIUM-HIGH**

### Challenges

#### [High] Challenge 1: Tick Sequence/Millisecond Collision
- **Assumption Challenged**: Composite key `(time, symbol, time_msc)` uniquely identifies a single tick.
- **Attack Scenario**: Fast market overlap (e.g., NY open) yields multiple bid/ask ticks in a single millisecond.
- **Blast Radius**: The system silently drops crucial ticks, resulting in skewed spreads and corrupted tick volatility.
- **Mitigation**: Expand the primary key, or remove uniqueness constraints on the tick hypertable.

#### [High] Challenge 2: Broken Reconnection Loop on Broker Outage
- **Assumption Challenged**: MT5 terminal status indicates broker connectivity.
- **Attack Scenario**: Broker server goes down for maintenance; the terminal application remains open.
- **Blast Radius**: Ingestion loops fail continuously, but MT5Client never attempts to re-initialize the broker connection because it incorrectly believes it is connected.
- **Mitigation**: Check `info.connected` field.

#### [Medium] Challenge 3: Transaction Timeout on Ingestion DDL Locks
- **Assumption Challenged**: Running `CREATE TABLE IF NOT EXISTS` frequently is harmless.
- **Attack Scenario**: Continuous aggregates or concurrent reads block table locks.
- **Blast Radius**: `init_hypertables` locks block, causing ingestion pipeline delays and write timeouts.
- **Mitigation**: Relocate hypertable creation to startup.

### Stress Test Results
- **Millisecond duplicate tick insertion** → Ticks are dropped (Actual behavior matches prediction) → **FAIL**
- **MT5 connection drop with running terminal** → Reconnection logic bypassed (Actual behavior matches prediction) → **FAIL**
- **Malformed DataFrame validation** → Syncing continues to DB despite warning (Actual behavior matches prediction) → **FAIL**

---

## 6. Verification Method

To independently verify this review:
1. Run the test suite:
   ```powershell
   pytest
   ```
2. Run progress tests:
   ```powershell
   pytest validation_harness/test_ingestion_prog.py
   ```
3. Inspect files `src/layers/l0_ingestion/mt5_client.py` and `src/layers/l0_ingestion/db_sync.py` to confirm the code blocks quoted in the findings.
