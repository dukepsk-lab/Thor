# Scope: E2E Testing Track

## Architecture
The E2E Testing Track is responsible for designing, implementing, and verifying a comprehensive test suite for the ML Trading System Validation Harness. The tests will exercise the modules under `validation_harness/` without having direct dependency on implementation details. Opaque-box methodology is used, checking input-output behavior, schema conformance, and analytical correctness.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| T1 | Decompose & Plan | Design feature inventory, test tiers, test architecture, and write TEST_INFRA.md. | None | IN_PROGRESS |
| T2 | Tier 1 & 2 Test Suite | Implement Feature Coverage (Tier 1) and Boundary/Corner (Tier 2) test scripts under `validation_harness/tests/`. | T1 | PLANNED |
| T3 | Tier 3 & 4 Test Suite | Implement Cross-Feature Combinations (Tier 3) and Real-World Workloads (Tier 4) test scripts under `validation_harness/tests/`. | T2 | PLANNED |
| T4 | Validation & Run | Verify all test cases run and pass under a simulated mock MT5/data environment. Publish `TEST_READY.md`. | T3 | PLANNED |

## Interface Contracts
The test scripts will verify compliance with the function signatures defined in the project's global contract (see `PROJECT.md`).
- `fetch_historical_ohlcv(symbol, timeframe, start, end)`
- `fetch_historical_ticks(symbol, start, end)`
- `get_cpcv_splits(event_times, event_hit_times, ...)`
- `compute_cost_adjusted_metrics(signals, ohlcv, ...)`
