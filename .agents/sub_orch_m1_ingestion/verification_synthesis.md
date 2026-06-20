# Verification Synthesis & Remediation Plan — Ingestion Milestone

This document synthesizes findings from 2 Reviewers, 2 Challengers, and the Forensic Auditor (Iteration 1 Verification), and outlines the remediation plan.

## 1. Synthesized Findings

### A. Critical Issues (Must Address)
1. **Tick Data Loss (Same-Millisecond Collisions)**
   - *Problem*: The tick table schema has `PRIMARY KEY (time, symbol, time_msc)`. If multiple ticks arrive in the same millisecond, they collide and subsequent ticks are silently dropped via `ON CONFLICT DO NOTHING` or `INSERT OR IGNORE`.
   - *Impact*: In liquid sessions, key tick-level price updates are lost, corrupting spread and transaction cost modeling.
   - *Fix*: Remove the primary key constraint on `tick_data`. Instead of `ON CONFLICT`, query the database for the maximum `time_msc` already synced for the symbol: `SELECT MAX(time_msc) FROM tick_data WHERE symbol = :symbol`. Filter the dataframe to only include rows where `time_msc > max_time_msc`, then perform a simple bulk insert of the new ticks.
2. **False Positive MT5 Connection Check**
   - *Problem*: `MT5Client` checks `if info is not None` instead of `if info is not None and info.connected`.
   - *Impact*: If broker connectivity drops while the local terminal remains open, the client fails to detect the drop and gets stuck in a loop of failing requests without attempting to reconnect.
   - *Fix*: Check both `info is not None and info.connected` in connection checks.

### B. Major Issues (Must Address)
3. **DDL Lock Contention in Ingestion Path**
   - *Problem*: `init_hypertables()` runs at the start of every sync execution, invoking `CREATE TABLE IF NOT EXISTS` and `create_hypertable` DDL queries.
   - *Impact*: Under concurrent writes, this causes AccessExclusiveLock contention on catalog tables, leading to deadlocks or locked-out writes.
   - *Fix*: Remove `init_hypertables()` from the data syncing paths. Expose database initialization as a startup method to run once.
4. **Lack of Thread Safety in MT5Client**
   - *Problem*: The global `mt5_client` is a singleton instance mutated and read across threads without synchronization, while the underlying `MetaTrader5` C-extension uses a single-threaded IPC link.
   - *Impact*: Concurrency leads to race conditions, out-of-order data, or terminal process crashes.
   - *Fix*: Wrap all `MetaTrader5` package function calls inside `MT5Client` with a `threading.Lock()` mutex.
5. **Ignored Schema Validation Results**
   - *Problem*: `fetch_historical_ohlcv` and `fetch_historical_ticks` execute schema validation checks but discard the return values, syncing invalid data straight to the DB.
   - *Impact*: Defeats defensive validation gates.
   - *Fix*: Check the return value of validators (or raise `ValueError` / `SchemaValidationException` directly) and halt/raise on validation failure.
6. **Missing Index Sorting and Deduplication in Validators**
   - *Problem*: The new schema validators do not sort timestamps or deduplicate timestamps, whereas legacy validators checked both.
   - *Impact*: Out-of-order or duplicate timestamps bypass the validator.
   - *Fix*: Implement `.sort_index(inplace=True)` and drop duplicates (e.g. keeping the last timestamp) inside the validators.
7. **CPCV Performance Bottleneck**
   - *Problem*: `CombinatorialPurgedKFold.split` uses a non-vectorized list comprehension check `[i for i in range(M) if i not in test_idx]` which scales quadratically with dataset and split combinations.
   - *Impact*: Takes >1.1 seconds for $M=3000, N=12, K=3$, failing the execution threshold.
   - *Fix*: Vectorize the index exclusion check using numpy masking:
     ```python
     mask = np.ones(M, dtype=bool)
     mask[test_idx] = False
     train_idx_arr = np.where(mask)[0]
     ```

### C. Minor Issues (Improve)
8. **Timezone Naivety in TimescaleDB tables**
   - *Problem*: Table schemas use `TIMESTAMP WITHOUT TIME ZONE`.
   - *Impact*: Timezone offset stripping risks locale shifts.
   - *Fix*: Use `TIMESTAMP WITH TIME ZONE` (or `TIMESTAMPTZ`) in table schemas.
9. **OOM and Lock Risks on Bulk Database Syncs**
   - *Problem*: Database syncing converts entire dataframes into record list parameters, leading to linear memory growth and long transaction write locks.
   - *Impact*: High memory usage and lock contention on millions of rows.
   - *Fix*: Implement batching/chunking (e.g. chunk size 5000) during database inserts.
10. **Nested Retry Loops in MT5Client**
    - *Problem*: Fetch retries run nested connection retry loops.
    - *Fix*: Simplify client retry logic and separate connection checking from fetch attempts.

## 2. Remediation Execution Plan
We will spawn a fresh **Worker** to apply these structural modifications to `db_sync.py`, `mt5_client.py`, `ingestion.py`, and `cpcv.py`, and verify them against the test suites.
