# Scope: Milestone 1 Ingestion

## Architecture
The historical data ingestion module is located in `validation_harness/ingestion.py`. It coordinates fetching data from MT5 and saving it to TimescaleDB via SQLAlchemy/pandas.

```
+--------------------+
| MetaTrader 5       |
+---------+----------+
          | (pyMT5 API)
          v
+---------+----------+
| mt5_client.py      | (MT5 Client Wrapper)
+---------+----------+
          | (fetch_ohlcv, fetch_ticks)
          v
+---------+----------+
| ingestion.py       | (Main Entry Point & Schema Validator)
+---------+----------+
          | (save/sync data)
          v
+---------+----------+
| db_sync.py         | (TimescaleDB / PostgreSQL writer)
+--------------------+
```

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1.1 | Analysis | Explore MT5, DB, schema requirements, verify connectivity, design interfaces | None | DONE |
| M1.2 | Implementation | Implement `validation_harness/ingestion.py` with robust reconnects, schema checks | M1.1 | DONE (Conv: 74ab8c62, Remediation Conv: 6c711c11) |
| M1.3 | Test Harness | Write programmatic test script verifying ingestion behavior, schemas, DB writes | M1.2 | DONE (Conv: 74ab8c62, Remediation Conv: 6c711c11) |
| M1.4 | Verification | Run Review, Challenger, and Audit cycles to guarantee correctness | M1.3 | IN_PROGRESS (Conv: 78224572, d4701abf, b2de66cb, 5f0968b0, 5d9054eb) |

## Interface Contracts
### `validation_harness/ingestion.py`
- `fetch_and_sync_ohlcv(symbol: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame`
  - Fetches OHLCV from MT5, validates against schema, syncs to DB, returns DataFrame.
  - Handles reconnects if MT5 client is disconnected.
- `fetch_and_sync_ticks(symbol: str, start_date: str, end_date: str) -> pd.DataFrame`
  - Fetches tick/spread data from MT5, validates against schema, syncs to DB, returns DataFrame.
  - Handles reconnects if MT5 client is disconnected.
- `validate_ohlcv_schema(df: pd.DataFrame) -> bool`
  - Validates that columns match expected OHLCV types and names.
- `validate_tick_schema(df: pd.DataFrame) -> bool`
  - Validates that columns match expected tick/spread types and names.
