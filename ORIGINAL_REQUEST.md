# Original User Request

## Initial Request — 2026-06-19T12:13:04+07:00

Develop a production-grade validation harness for the ML trading system to rigorously evaluate strategies and prevent backtest overfitting. The harness will implement Combinatorial Purged Cross-Validation (CPCV), baseline-relative evaluation, and cost-adjusted metrics.

Working directory: c:/Users/swing/Desktop/TRADING/Thor/validation_harness
Integrity mode: development

## Requirements

### R1. Data Ingestion via MT5
The harness must dynamically fetch historical market data (OHLCV and ticks) directly from the MetaTrader 5 terminal.

### R2. Combinatorial Purged Cross-Validation (CPCV)
The harness must implement a rigorous CPCV evaluation loop. It must correctly apply purging and embargo techniques to ensure no data leakage between training and testing folds due to overlapping labels.

### R3. Cost-Adjusted Baseline Reporting
The evaluation output must include key performance metrics (e.g., Sharpe, Sortino) that are cost-adjusted (accounting for spread and commission). The metrics must be reported relative to baseline strategies (like Buy-and-Hold and a random-entry control).

## Acceptance Criteria

### Data Ingestion
- [ ] A programmatic test script successfully fetches a sample dataset from a running MT5 instance and validates the DataFrame schema.

### CPCV Implementation
- [ ] An automated test verifies that the CPCV splits correctly exclude embargoed and purged periods (no overlap between training and testing folds).

### Metric Reporting
- [ ] A test script processes a dummy signal dataset and successfully generates a summary report comparing the strategy's cost-adjusted metrics against Buy-and-Hold and random baselines.
