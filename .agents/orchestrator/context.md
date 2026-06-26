# Project Context

## Codebase Context
- Project: ML Trading System (Thor)
- Language: Python
- Core Packages: fastapi, uvicorn, MetaTrader5, pandas, numpy, lightgbm, catboost, scikit-learn, psycopg2-binary, sqlalchemy, python-dotenv, pyzmq.
- Configuration: `src/core/config.py` relies on `pydantic_settings`.

## Database Details
- TimescaleDB host/port/credentials configured in `.env`.
- Two tables/hypertables mentioned in `db_sync.py`: `ohlcv_data` and `tick_data`.

## Existing Ingestion/Labeling Utilities
- `src/layers/l0_ingestion/mt5_client.py`: Initial connection methods to MT5, plus stubs for `fetch_ohlcv` and `fetch_ticks`.
- `src/layers/l4_labeling/triple_barrier.py`: Initial TBM implementation (has a potential start-index path inclusion bug to fix during development).
- `src/layers/l4_labeling/sample_weights.py`: Initial sample uniqueness calculations.

## Validation Harness Scope
All code for the validation harness will be built in `c:\Users\swing\Desktop\TRADING\Thor\validation_harness\`.
Tests will live in `c:\Users\swing\Desktop\TRADING\Thor\validation_harness\tests\`.
