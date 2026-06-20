# Context: E2E Testing Track

## Environment Information
- **OS**: Windows
- **Python Packages**: MetaTrader5, pandas, numpy, lightgbm, catboost, scikit-learn, psycopg2-binary, sqlalchemy, python-dotenv, pyzmq.
- **Test Framework**: `pytest` (inferred/required for tests).
- **Target Folder**: `validation_harness/tests/`
- **Output Files**: `TEST_READY.md` to be placed in `validation_harness/` and `.agents/orchestrator/`.

## Dependencies & Mocking
- **MetaTrader5**: Since MT5 requires a Windows Terminal application running, tests run in CI/CD or headless environments must mock `MetaTrader5`.
- **Interface Mappings**:
  - `validation_harness.ingestion` exports `fetch_historical_ohlcv` and `fetch_historical_ticks`.
  - `validation_harness.cpcv` exports `get_cpcv_splits`.
  - `validation_harness.metrics` exports `compute_cost_adjusted_metrics`.
