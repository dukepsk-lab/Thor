# Context: Ingestion Environment & Dependencies

## Working Directory
- Sub-Orchestrator metadata: `c:\Users\swing\Desktop\TRADING\Thor\.agents\sub_orch_m1_ingestion\`
- Code under development: `c:\Users\swing\Desktop\TRADING\Thor\validation_harness\ingestion.py`

## External Systems
1. **MetaTrader 5 Terminal**
   - API: `MetaTrader5` python package.
   - Credentials / Path: Defined in `src/core/config.py` via environment variables.
   - Behavior: Needs initialization via `mt5.initialize()`. Since we are in a headless/automated test environment, connection may fail if the actual terminal is not running or credentials are wrong. The code must have a robust reconnection logic and/or mock capability for testing.
2. **TimescaleDB**
   - API: SQLAlchemy engine and session, pandas `to_sql`.
   - Behavior: Writes to tables `ohlcv_data` and `tick_data`.

## Code Dependencies
- `src/core/config.py`: Provides MT5 and DB connection parameters.
- `src/core/db.py`: Provides database engine and sessionmaker.
- `src/layers/l0_ingestion/mt5_client.py`: Provides base `MT5Client` class.
- `src/layers/l0_ingestion/db_sync.py`: Provides base synchronization functions.
