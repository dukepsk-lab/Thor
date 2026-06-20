# E2E Test Suite Implementation Plan

## Overview
This plan governs the implementation of the opaque-box test suite for the ML Trading System Validation Harness.

## 4-Tier Test Case Framework

### Feature Inventory
We identify 6 key features derived from the requirements:
1. **F1: OHLCV Ingestion**: Fetching historical OHLCV data from MT5.
2. **F2: Tick Ingestion**: Fetching historical tick data from MT5.
3. **F3: CPCV Split Generation**: Combinatorial partition and indexing logic.
4. **F4: Purging & Embargo**: Removing overlapping samples and applying post-test embargo buffers.
5. **F5: Cost-Adjusted Metrics**: Calculating Sharpe, Sortino, Drawdowns, and Cumulative Returns adjusted for spread and commissions.
6. **F6: Baseline Comparisons**: Relative comparison against Buy-and-Hold and Random-entry control.

### Test Targets (Counts)
With N = 6 features:
- **Tier 1 (Feature Coverage)**: 5 * 6 = 30 test cases.
- **Tier 2 (Boundary & Corner Cases)**: 5 * 6 = 30 test cases.
- **Tier 3 (Cross-Feature Combinations)**: 6 test cases.
- **Tier 4 (Real-World Workloads)**: 5 test cases.
- **Total**: 71 test cases.

### Implementation Strategy
We will structure the tests in pytest files under `validation_harness/tests/`:
- `test_ingestion.py`: Ingestion feature coverage and edge cases (F1, F2).
- `test_cpcv.py`: CPCV splitting, purging, and embargo tests (F3, F4).
- `test_metrics.py`: Cost-adjusted metrics and baselines tests (F5, F6).
- `test_e2e.py`: Cross-feature combinations and real-world workload tests (Tiers 3 & 4).

### Mocking Strategy
Since MT5 is an external Windows application that requires a live terminal to run, we will design test fixtures that mock the MT5 connection (`MetaTrader5` library) to return representative dataframes for ingestion. This ensures the tests are fully executable in a CI/CD environment or locally without a running MT5 instance, while still validating the ingestion schemas and failure modes.

## Step-by-Step Schedule
1. **Step 1: Planning and Test Design** (Write TEST_INFRA.md, design mocks and fixtures)
2. **Step 2: Implementation of Ingestion Tests** (Tier 1 & Tier 2)
3. **Step 3: Implementation of CPCV Tests** (Tier 1 & Tier 2)
4. **Step 4: Implementation of Metrics Tests** (Tier 1 & Tier 2)
5. **Step 5: Implementation of E2E / Integration Tests** (Tier 3 & Tier 4)
6. **Step 6: Verification and Execution Gating** (Run tests, fix failures, publish TEST_READY.md)
