## 2026-06-19T05:51:50Z
<USER_REQUEST>
You are Worker 2 for the Ingestion Milestone.
Your working directory is c:\Users\swing\Desktop\TRADING\Thor\.agents\worker_m1_2\.

YOUR MISSION:
We have received feedback from Reviewers and Challengers regarding bugs, concurrency limits, and scalability issues. You must fix them in:
1. `src/layers/l0_ingestion/db_sync.py`:
   - Remove `init_hypertables()` from the `sync_ohlcv_to_timescale` and `sync_ticks_to_timescale` hot execution paths. Expose database initialization separately (or only run it once on first load / initialization).
   - In `init_hypertables()`, change the table column definitions for all timestamp fields from `TIMESTAMP WITHOUT TIME ZONE` to `TIMESTAMP WITH TIME ZONE`.
   - Remove the primary key constraint on `tick_data` (or drop the `PRIMARY KEY (time, symbol, time_msc)` declaration to prevent silently dropping colliding same-millisecond ticks).
   - Instead, handle overlaps/duplicates in `sync_ticks_to_timescale`:
     * Before syncing ticks, query the database to retrieve the maximum `time_msc` already synced for the symbol.
     * Filter the tick DataFrame: `df = df[df['time_msc'] > max_time_msc]`.
     * Sync the filtered DataFrame using a simple bulk insert (no `ON CONFLICT` or `INSERT OR IGNORE`).
   - Implement batching/chunking for database insertions: instead of executing the entire insert block at once, divide insertions into chunks of size 5,000 using standard dataframe splits or row boundaries.

2. `src/layers/l0_ingestion/mt5_client.py`:
   - Thread Safety: Guard all `MetaTrader5` library calls inside `MT5Client` connect, status, and fetch methods with a `threading.Lock()` instance.
   - Connection Check: Check both `info is not None` and `info.connected` during connectivity checks in `check_status` and `connect` (do not just check `info is not None`).
   - Retry Simplification: Simplify the connection retries in fetch functions (e.g. check connection, try a single reconnect if disconnected, then attempt fetch, without nested loops).

3. `validation_harness/ingestion.py`:
   - Schema Validators: In `validate_ohlcv_schema` and `validate_tick_schema`, add sorting of the index (`df.sort_index(inplace=True)`) and drop duplicate timestamps. Correctly check and clamp negative volumes and spreads to 0. Add validation to reject or drop future timestamps.
   - Return Value Check: Ensure that `fetch_historical_ohlcv` and `fetch_historical_ticks` assert or check if validation succeeded, raising an error if it failed critically (rather than silently inserting anyway).

4. `validation_harness/cpcv.py`:
   - Vectorize the index exclusion check in `CombinatorialPurgedKFold.split`: replace `np.array([i for i in range(M) if i not in test_idx])` with:
     ```python
     mask = np.ones(M, dtype=bool)
     mask[test_idx] = False
     train_idx_arr = np.where(mask)[0]
     ```

5. Ensure all existing project tests and the custom programmatic test suites pass successfully. Run tests to confirm.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Please report your progress and output the test command and results. Write your handoff to `c:\Users\swing\Desktop\TRADING\Thor\.agents\worker_m1_2\handoff.md` and send me a message when done.
</USER_REQUEST>
