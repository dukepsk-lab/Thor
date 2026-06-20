## 2026-06-19T05:16:10Z

You are the Worker for the Ingestion Milestone.
Your working directory is c:\Users\swing\Desktop\TRADING\Thor\.agents\worker_m1_1\.

YOUR MISSION:
1. Implement the ingestion module in `validation_harness/ingestion.py`. It should fetch historical OHLCV and tick data from MT5, validate schemas, handle reconnects, and sync to TimescaleDB.
   Specifically, define:
   - `fetch_historical_ohlcv(symbol: str, timeframe: int, start: datetime, end: datetime) -> pd.DataFrame`
     Fetches rates, validates schema via `validate_ohlcv_schema`, and syncs to TimescaleDB. Handles reconnects on terminal disconnects.
   - `fetch_historical_ticks(symbol: str, start: datetime, end: datetime) -> pd.DataFrame`
     Fetches ticks, validates schema via `validate_tick_schema`, and syncs to TimescaleDB. Handles reconnects on terminal disconnects.
   - `validate_ohlcv_schema(df: pd.DataFrame) -> bool`
     Returns True if the DataFrame conforms to the expected OHLCV schema, otherwise raises/logs errors and cleans/handles columns/values.
   - `validate_tick_schema(df: pd.DataFrame) -> bool`
     Returns True if the DataFrame conforms to the expected tick schema, otherwise raises/logs errors and cleans/handles columns/values.

2. Modify `src/layers/l0_ingestion/mt5_client.py` and `src/layers/l0_ingestion/db_sync.py` to:
   - Add robust reconnects, exponential backoff retries, and check terminal status in `mt5_client.py`.
   - Implement Postgres DDL and hypertable creation safely checking the dialect (avoiding failure on SQLite), and support robust database inserts using upserts / `ON CONFLICT` for `ohlcv_data` to handle overlaps in `db_sync.py`.

3. Write a programmatic test script at `validation_harness/test_ingestion_prog.py` using pytest or standard unit tests.
   - Use a mock MT5 client (mocking MetaTrader5 package or mt5_client functions) to simulate connection drop, reconnect, and rates/ticks fetching.
   - Use a mock DB (sqlite in-memory or mocking session/engine) to test DB sync, schema validation, and upserts.
   - Run the programmatic test script using `pytest` or `python` command, and verify it passes.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Please report your progress and output the test command and results. Write your handoff to `c:\Users\swing\Desktop\TRADING\Thor\.agents\worker_m1_1\handoff.md` and send me a message when done.
