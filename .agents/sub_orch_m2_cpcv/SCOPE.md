# Scope: CPCV splitting, purging, and embargo logic

## Architecture
- Part of the ML Trading System's validation layer.
- Implements Combinatorial Purged Cross-Validation (CPCV) to split time-series datasets into train and test folds.
- Correctly purges train samples that overlap with test samples in terms of label evaluation windows.
- Correctly embargoes train samples that start within a specified period/bars after test samples end.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Assess & Design | Gather requirements, define API, check existing structures. | None | PLANNED |
| 2 | Implementation | Implement CPCV split, purge, and embargo logic in cpcv.py. | M1 | PLANNED |
| 3 | Verification | Write and execute unit/integration tests for CPCV logic. | M2 | PLANNED |
| 4 | Audit & Signoff | Perform forensic auditing and code review to verify zero leakage. | M3 | PLANNED |

## Interface Contracts
### `cpcv.py` ↔ Training Pipeline
- The CPCV class (e.g. `CombinatorialPurgedKFold`) must be compatible with standard sklearn cross-validation splitter interface or provide a similar `.split(X, y, groups)` generator.
- Inputs for split:
  - `df`: pandas DataFrame containing index and labels' `hit_time` (or separate series of `t1` / `hit_time` if preferred).
  - `n_splits`: number of partition groups ($N$).
  - `n_test_splits`: number of test groups ($K$).
  - `embargo_pct`: embargo period as a percentage of the total dataset or absolute timeframe/bars. Let's support both pct and pd.Timedelta/int.
  - `purging`: boolean flag, default True.
- Output:
  - Generator yielding `(train_indices, test_indices)` for each combination.
