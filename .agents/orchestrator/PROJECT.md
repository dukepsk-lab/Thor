# Project: ML Trading System Validation Harness

## Architecture
The Validation Harness is an independent evaluation suite that sits outside the live execution pathway but interfaces with MT5 (L0 Ingestion) to pull clean historical data.

```
+------------------+      +--------------------------+
|   MetaTrader 5   | <---> | validation_harness       |
|    Terminal      |       |  - ingestion.py          |
+------------------+       +--------------------------+
                                       |
                                       v
                           +--------------------------+
                           | validation_harness       |
                           |  - cpcv.py               |
                           +--------------------------+
                                       |
                                       v
                           +--------------------------+
                           | validation_harness       |
                           |  - metrics.py            |
                           +--------------------------+
                                       |
                                       v
                           +--------------------------+
                           | validation_harness       |
                           |  - runner.py             |
                           +--------------------------+
```

- **ingestion.py**: Connects to MT5 terminal dynamically, pulls OHLCV and ticks, validates their schemas, handles reconnects.
- **cpcv.py**: Given event timestamps (labels start/end times), computes Combinatorial Purged Cross-Validation train/test indices with purging (overlapping interval removal) and embargo (post-test leakage buffer).
- **metrics.py**: Processes strategy signals, computes trade executions, calculates cost-adjusted metrics (Sharpe, Sortino, Drawdowns) using raw ticks/spread and commission, and outputs comparisons with Buy-and-Hold and Random baselines.
- **runner.py**: Runs the validation loop over the splits and aggregates metrics into a report.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| T0 | E2E Testing Track | Define E2E and Unit test infrastructure, implement tests, and generate `TEST_READY.md`. | None | DONE |
| M1 | Data Ingestion | Implement `ingestion.py` for MT5 fetching and validation. | None | PLANNED |
| M2 | CPCV | Implement `cpcv.py` for CPCV splitting, purging, and embargo. | None | PLANNED |
| M3 | Cost-Adjusted Metrics | Implement `metrics.py` for cost adjustments and baselines. | M1, M2 | PLANNED |
| M4 | E2E Integration & Verification | E2E integration test pass and Tier 5 adversarial hardening. | T0, M1, M2, M3 | PLANNED |

## Interface Contracts

### Data Ingestion Interface
```python
def fetch_historical_ohlcv(symbol: str, timeframe: int, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Returns DataFrame with Index: DatetimeIndex (named 'time')
    Columns: open (float), high (float), low (float), close (float), tick_volume (int), spread (int), real_volume (int)
    Raises ConnectionError if MT5 is unavailable.
    """

def fetch_historical_ticks(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    Returns DataFrame with Index: DatetimeIndex (named 'time')
    Columns: bid (float), ask (float), last (float), volume (float), flags (int)
    Raises ConnectionError if MT5 is unavailable.
    """
```

### CPCV Splitting Interface
```python
def get_cpcv_splits(
    event_times: pd.Series, 
    event_hit_times: pd.Series, 
    n_partitions: int = 6, 
    n_test_partitions: int = 2,
    purging_offset: pd.Timedelta = pd.Timedelta(hours=4),
    embargo_offset: pd.Timedelta = pd.Timedelta(hours=24)
) -> List[Dict[str, np.ndarray]]:
    """
    Given event start times and hit (barrier) times, generates Combinatorial Purged Cross-Validation train/test splits.
    Handles overlapping event labels by purging training events that overlap with test events,
    and embargoing training events that immediately follow test events.
    """
```

### Cost-Adjusted Metrics Interface
```python
def compute_cost_adjusted_metrics(
    signals: pd.Series, 
    ohlcv: pd.DataFrame, 
    ticks: Optional[pd.DataFrame] = None,
    spread_pips: float = 1.5,
    commission_per_lot: float = 5.0,
    point_value: float = 10.0
) -> Dict[str, Any]:
    """
    Computes Sharpe, Sortino, Max Drawdown, and Cumulative Returns adjusted for spread and commission.
    Compares strategy metrics against a Buy-and-Hold baseline and a Random baseline (1000 trials).
    """
```

## Code Layout
The code must be structured as follows:
```
c:\Users\swing\Desktop\TRADING\Thor\
├── validation_harness/
│   ├── __init__.py
│   ├── ingestion.py
│   ├── cpcv.py
│   ├── metrics.py
│   ├── runner.py
│   └── tests/
│       ├── __init__.py
│       ├── test_ingestion.py
│       ├── test_cpcv.py
│       ├── test_metrics.py
│       └── test_e2e.py
```
