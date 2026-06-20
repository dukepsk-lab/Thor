# Handoff Report — Explorer Testing Investigation

**Context**: Investigation of the Thor trading codebase to identify test/validation files, design an MT5 mocking strategy, specify data schemas, and draft a 71-case test plan across 4 tiers for the validation framework.
**Action**: Implementer to set up pytest, mock MT5 using the recommended design, apply the specified schemas, and implement the 71 test cases.

---

## 1. Observation
1. **Directory Investigation**:
   A full scan of the `c:\Users\swing\Desktop\TRADING\Thor` codebase was performed. No existing test files, test runner configurations (`pytest.ini`, `conftest.py`), or mock implementations for external dependencies were found in the project.
   - Core source files are located in `src/`.
   - Data ingestion layers (`src/layers/l0_ingestion/db_sync.py` and `mt5_client.py`) interact directly with TimescaleDB and the `MetaTrader5` python package.
   - No testing framework is currently configured in `requirements.txt` (only runtime dependencies like `MetaTrader5`, `fastapi`, `pandas`, `sqlalchemy` are present).

2. **Integration Touchpoints**:
   - `MT5Client` (in `src/layers/l0_ingestion/mt5_client.py`) references `import MetaTrader5 as mt5` and utilizes `initialize()`, `shutdown()`, `last_error()`, `copy_rates_range()`, and `copy_ticks_range()`.
   - `db_sync.py` uses SQLAlchemy's `engine` to append data to `ohlcv_data` and `tick_data` tables.
   - Feature engineering and labeling modules (like `triple_barrier.py` and `sample_weights.py` in `src/layers/l4_labeling/`) utilize pandas operations on price and ATR data.

---

## 2. Logic Chain
1. **Need for MT5 Mocking**:
   - The `MetaTrader5` python library requires a live Windows environment and a running MetaTrader 5 desktop application. It cannot run in typical CI/CD pipelines or headless development environments.
   - Therefore, a mock package must be injected into Python’s `sys.modules` to intercept all MT5 calls at import-time.
   - Using a pytest fixture in a root `conftest.py` ensures that all tests running across the layers can mock, control, and assert against MT5 interactions without modifying the production client code.

2. **Data Schemas**:
   - For historical validation, data integrity must be checked at every level of the pipeline: from raw MT5 structured arrays to pandas DataFrames and TimescaleDB tables.
   - Clear schemas are specified for both **OHLCV** and **Tick** data to prevent data-type mismatches, timestamp alignment issues, and timezone/integer-precision bugs.

3. **4-Tier Test Plan**:
   - Risk management and out-of-sample validity are the top priorities (as stated in `ML_Trading_System_Architecture.md`).
   - The 71 test cases are distributed across 4 tiers to ensure both basic features and complex system behaviors (purging, cost deductions, walk-forward baselines, high-frequency stress loads) are exhaustively covered.
   - Keeping tests co-located with their target modules (e.g. `src/layers/l0_ingestion/test_mt5_client.py` next to `mt5_client.py`) enforces modular design and aligns with standard repository layout compliance.

---

## 3. Caveats
- **Database Dependency**: The current DB syncing functions in `db_sync.py` rely on a live TimescaleDB connection. In the test runner setup, SQL database calls must be mocked, or an in-memory SQLite database / temporary PostgreSQL docker container must be used.
- **Tick Volume & Flags**: MetaTrader 5 tick flags are bitwise integers (`uint32`). The mock strategy assumes these flags can be simulated using standard integer values, but specific execution-layer logic (if added) will need to parse those bitwise flags accurately.
- **News/Slippage Events**: Realistic cost-adjusted metric testing requires simulated news schedules and slippage distributions. The test plan describes how these should be structured, but their implementation requires generating synthetic price-gap events.

---

## 4. Conclusion
A rigorous test-driven foundation is essential before executing live trades on H4 EURUSD/GBPUSD. Implementing the recommended MT5 mock strategy, schemas, and 71 test cases will establish a complete validation harness, protecting the system's thin edge and preventing data leakage during CPCV splits.

---

## 5. Verification Method
1. **Setup Verification**:
   Verify that `pytest` is added to `requirements.txt` (or a `requirements-dev.txt`) and can be run:
   ```bash
   pip install pytest pytest-mock pytest-cov
   pytest --version
   ```
2. **Mock Activation Verification**:
   Run a simple test that imports `MetaTrader5` in a environment without the MT5 terminal installed. If the import succeeds and yields the mock instance, the interceptor in `conftest.py` is verified.
3. **Execution Command**:
   To run all co-located tests and print coverage:
   ```bash
   pytest src/ --cov=src --cov-report=term-missing
   ```

---

# APPENDIX A: MetaTrader 5 (MT5) Mocking Strategy

Since `MetaTrader5` is a Windows-only C-extension package, running tests on other environments (like Linux CI) will result in `ImportError`. We recommend using a global interceptor in `conftest.py` that mocks the module and registers it in `sys.modules` before any application code is imported.

### 1. `conftest.py` Mock Interceptor Setup

Create `conftest.py` at the project root (`c:\Users\swing\Desktop\TRADING\Thor\conftest.py` or `src/conftest.py`):

```python
import sys
from unittest.mock import MagicMock
import numpy as np

# Define standard MetaTrader 5 constants required by the codebase
class MockMetaTrader5:
    # Timeframes
    TIMEFRAME_M15 = 15
    TIMEFRAME_H4 = 16388
    TIMEFRAME_D1 = 16408
    
    # Tick copy flags
    COPY_TICKS_ALL = 1
    COPY_TICKS_INFO = 2
    
    # Error codes
    RES_S_OK = 1
    RES_E_FAIL = -1
    
    def __init__(self):
        self.initialize_return = True
        self.last_error_return = (1, "Success")
        self.rates_return = None
        self.ticks_return = None
        self.initialized = False

    def initialize(self, path=None, login=0, password="", server=""):
        if self.initialize_return:
            self.initialized = True
            return True
        return False

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return self.last_error_return

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not self.initialized:
            return None
        return self.rates_return

    def copy_ticks_range(self, symbol, date_from, date_to, flags):
        if not self.initialized:
            return None
        return self.ticks_return

# Instantiate the mock
mock_mt5_instance = MockMetaTrader5()

# Register the mock in sys.modules to intercept all 'import MetaTrader5' calls
sys.modules['MetaTrader5'] = mock_mt5_instance

import pytest

@pytest.fixture
def mock_mt5():
    """
    Fixture to get access to the MT5 mock instance, allowing individual tests
    to override returned values and inspect connection state.
    """
    yield mock_mt5_instance
    # Reset mock state after each test case
    mock_mt5_instance.initialize_return = True
    mock_mt5_instance.last_error_return = (1, "Success")
    mock_mt5_instance.rates_return = None
    mock_mt5_instance.ticks_return = None
    mock_mt5_instance.initialized = False
```

### 2. Test Example using the Mock Fixture

```python
from datetime import datetime
import numpy as np
from src.layers.l0_ingestion.mt5_client import MT5Client

def test_fetch_ohlcv_success(mock_mt5):
    # 1. Define dummy structured array matching MT5 return type
    rates_data = np.array([
        (1672531200, 1.0850, 1.0900, 1.0820, 1.0880, 500, 15, 0)
    ], dtype=[
        ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'), 
        ('close', 'f8'), ('tick_volume', 'i8'), ('spread', 'i4'), ('real_volume', 'u8')
    ])
    
    # 2. Inject rates into the mock
    mock_mt5.rates_return = rates_data
    
    # 3. Call client
    client = MT5Client()
    assert client.connect() is True
    
    df = client.fetch_ohlcv("EURUSD", mock_mt5.TIMEFRAME_H4, datetime(2023,1,1), datetime(2023,1,2))
    
    # 4. Assertions
    assert df is not None
    assert len(df) == 1
    assert df.index[0] == datetime(2023, 1, 1)
    assert df.loc[datetime(2023, 1, 1), 'close'] == 1.0880
```

---

# APPENDIX B: Historical OHLCV and Tick Schemas

Data schemas must enforce strict validation. Data flows from **MT5 Numpy Structured Array** -> **Pandas DataFrame** -> **TimescaleDB Hypertable**.

### 1. Historical OHLCV Data Schema

#### A. MT5 Structured Array (Input)
- **Data Structure**: NumPy array of structured records.
- **Fields**:
  - `time` (`int64`): UTC seconds since Jan 1, 1970 (Unix Epoch).
  - `open` (`float64`): Bar open price (e.g. 1.08540).
  - `high` (`float64`): Bar high price.
  - `low` (`float64`): Bar low price.
  - `close` (`float64`): Bar close price.
  - `tick_volume` (`int64`): Count of ticks recorded during the bar.
  - `spread` (`int32`): Average or last spread in points (1 point = 0.00001 for EURUSD).
  - `real_volume` (`uint64`): Real trade volume (0 for standard spot FX brokers).

#### B. Pandas DataFrame (Intermediate)
- **Index**: `time` (`datetime64[ns]`, timezone-naive representing UTC).
- **Columns**:
  - `open` (`float64`): Open price. Must be $> 0$.
  - `high` (`float64`): High price. Must be $\ge \max(\text{open}, \text{close}, \text{low})$.
  - `low` (`float64`): Low price. Must be $\le \min(\text{open}, \text{close}, \text{high})$.
  - `close` (`float64`): Close price. Must be $> 0$.
  - `tick_volume` (`int64`): Tick count. Must be $\ge 0$.
  - `spread` (`int32`): Spread in points. Must be $\ge 0$.
  - `real_volume` (`int64` or `float64`): Volume. Must be $\ge 0$.

#### C. TimescaleDB `ohlcv_data` Table (Database Schema)
```sql
CREATE TABLE ohlcv_data (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    tick_volume BIGINT NOT NULL,
    spread INT NOT NULL,
    real_volume BIGINT NOT NULL,
    PRIMARY KEY (time, symbol, timeframe)
);

-- Convert to hypertable partitioned by time
SELECT create_hypertable('ohlcv_data', 'time', if_not_exists => TRUE);
```

---

### 2. Historical Tick Data Schema

#### A. MT5 Structured Array (Input)
- **Data Structure**: NumPy array of structured records.
- **Fields**:
  - `time` (`int64`): UTC seconds since epoch.
  - `bid` (`float64`): Bid price.
  - `ask` (`float64`): Ask price.
  - `last` (`float64`): Price of the last trade (mostly 0.0 for spot FX).
  - `volume` (`float64`): Volume of the last trade.
  - `time_msc` (`int64`): Precise timestamp in milliseconds since epoch.
  - `flags` (`uint32`): Tick flags (bitwise):
    - `1`: Bid changed.
    - `2`: Ask changed.
    - `4`: Last price changed.
    - `8`: Volume changed.
    - `16`: Buy order executed.
    - `32`: Sell order executed.
  - `volume_real` (`float64`): Real execution volume.

#### B. Pandas DataFrame (Intermediate)
- **Index**: `time` (`datetime64[ns]`, timezone-naive representing UTC).
- **Columns**:
  - `bid` (`float64`): Bid price. Must be $> 0$.
  - `ask` (`float64`): Ask price. Must be $\ge \text{bid}$ (spread $\ge 0$).
  - `last` (`float64`): Last price. Must be $\ge 0$.
  - `volume` (`float64`): Last trade volume. Must be $\ge 0$.
  - `time_msc` (`int64`): Microsecond/millisecond epoch integer.
  - `flags` (`uint32`): Action bitmask.
  - `volume_real` (`float64`): Exact volume. Must be $\ge 0$.

#### C. TimescaleDB `tick_data` Table (Database Schema)
```sql
CREATE TABLE tick_data (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    bid DOUBLE PRECISION NOT NULL,
    ask DOUBLE PRECISION NOT NULL,
    last DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    time_msc BIGINT NOT NULL,
    flags BIGINT NOT NULL,
    volume_real DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (time, symbol)
);

-- Convert to hypertable partitioned by time
SELECT create_hypertable('tick_data', 'time', if_not_exists => TRUE);
```

---

# APPENDIX C: Test Plan (71 Test Cases across 4 Tiers)

The test cases cover 6 features:
- **F1**: OHLCV Ingestion
- **F2**: Tick Ingestion
- **F3**: CPCV Split Generation
- **F4**: CPCV Purging & Embargo
- **F5**: Cost-adjusted Metrics
- **F6**: Baseline Comparisons

---

## TIER 1: Feature Coverage (Test Cases 1 - 20)
*Validates that the core path of each individual feature performs exactly as expected under standard nominal conditions.*

| Test ID | Feature | Test Case Name | Inputs / Setup | Mock Behavior | Expected Behavior & Assertions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC_T1_01** | F1 | MT5 Client Init | Default config path & logins | `initialize` returns `True` | Connection flag set to `True`, error code is `1` (OK). |
| **TC_T1_02** | F1 | MT5 Client Shutdown | Connected client | `shutdown` called successfully | Connection flag set to `False`. |
| **TC_T1_03** | F1 | Standard H4 Ingestion | `EURUSD`, `TIMEFRAME_H4`, dates | `copy_rates_range` returns 10 bars | Returns a DataFrame with 10 rows, index = `DatetimeIndex`, columns match OHLCV schema. |
| **TC_T1_04** | F1 | OHLCV DB Sync | DataFrame (5 rows) | Mock SQLAlchemy `to_sql` method | `to_sql` called once, index mapped to `time`, target table is `ohlcv_data`. |
| **TC_T1_05** | F2 | Standard Tick Ingestion | `GBPUSD`, date range | `copy_ticks_range` returns 10 ticks | Returns a DataFrame with 10 rows, columns: `['bid', 'ask', 'last', 'volume', 'time_msc', 'flags', 'volume_real']`. |
| **TC_T1_06** | F2 | Tick Millisecond Parsing | Raw ticks array with `time_msc` | Standard ticks array returned | DataFrame index is parsed as datetime, fractional seconds preserved; `time_msc` retains integer mills. |
| **TC_T1_07** | F2 | Tick DB Sync | DataFrame (20 ticks) | Mock DB connection | `to_sql` called, target table is `tick_data`, data appended without index loss. |
| **TC_T1_08** | F3 | CPCV Split Count | $N=5, k=2$ split parameters | Toy dataset index of 100 samples | Generates exactly $\frac{5!}{2!(5-2)!} = 10$ training/testing splits. |
| **TC_T1_09** | F3 | CPCV Split Disjointness | $N=6, k=2$ split parameters | Toy dataset index | For every split, intersection of train index and test index is empty (`set(train) & set(test) == {}`). |
| **TC_T1_10** | F3 | CPCV Mask Coverage | $N=4, k=1$ split parameters | Toy dataset index | Every sample index appears in the test fold exactly once across all generated splits. |
| **TC_T1_11** | F4 | Basic Purging | Events DataFrame (5 overlaps) | Toy price index | Training indices that fall within the interval `[start_time, hit_time]` of any test sample are removed. |
| **TC_T1_12** | F4 | Basic Embargo | Test Fold boundaries | Embargo multiplier $1.0\times$ | Training indices occurring within the embargo duration immediately following a test fold are removed. |
| **TC_T1_13** | F4 | Purge + Embargo Combined | Overlapping events, test fold | Embargo multiplier $1.0\times$ | Returned training indices contain no overlaps with test fold intervals and no indices inside the post-test embargo window. |
| **TC_T1_14** | F4 | Zero-Overlap Verification | Final purged train/test masks | Standard dataset | Assert that `(train_event_intervals & test_event_intervals)` is empty across all active labels. |
| **TC_T1_15** | F5 | Transaction Cost Deduction | Return series, spread=1 pip, commission=2$ | Flat fees and dynamic spreads | Net returns are strictly lower than raw returns; verifies formula: $\text{net\_ret} = \text{raw\_ret} - \text{spread\_costs} - \text{commissions}$. |
| **TC_T1_16** | F5 | Sharpe Ratio Calculation | Constant positive returns | No costs added | Returns correct Sharpe ratio value matching hand-calculated standard deviation and mean return. |
| **TC_T1_17** | F5 | Sortino Ratio Calculation | Series with negative skew | Downside deviation only | Returns correct Sortino ratio value; upside volatility is ignored in the denominator. |
| **TC_T1_18** | F5 | Deflated Sharpe Ratio (DSR) | Sharpe=1.5, trials=5, var=0.1 | DSR formula execution | Outputs a calibrated probability $P(\text{SR} > 0)$ accounting for multi-testing inflation. |
| **TC_T1_19** | F6 | Majority Class Comparison | Model predictions, actual labels | Constant dummy baseline model | Model metrics are reported as relative diff: $\text{Accuracy}_{\text{model}} - \text{Accuracy}_{\text{baseline}}$. |
| **TC_T1_20** | F6 | Buy-and-Hold Benchmark | Price series | Buy-and-Hold long-only simulation | Cumulative returns of strategy are aligned and subtracted from Buy-and-Hold cumulative returns. |

---

## TIER 2: Boundary & Corner Cases (Test Cases 21 - 40)
*Verifies system robustness, validation gates, and error handling when encountering missing, malformed, or extreme inputs.*

| Test ID | Feature | Test Case Name | Inputs / Setup | Mock Behavior | Expected Behavior & Assertions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC_T2_01** | F1 | MT5 Init Failure | Incorrect credentials / invalid path | `initialize` returns `False` | `MT5Client.connect()` returns `False`, registers error, and does not crash. |
| **TC_T2_02** | F1 | Empty Rates Return | Valid connection, fetch rates | `copy_rates_range` returns `None` | `fetch_ohlcv` returns `None`, logs error code via `last_error()`. |
| **TC_T2_03** | F1 | Reversed Start/End Dates | Start Date > End Date | `copy_rates_range` returns `None` | Returns empty DataFrame or raises `ValueError`. |
| **TC_T2_04** | F2 | Empty Ticks Return | Valid connection, fetch ticks | `copy_ticks_range` returns `None` | `fetch_ticks` returns `None`, logs error. |
| **TC_T2_05** | F2 | Weekend/Holiday Query | Range over market close | `copy_ticks_range` returns empty array | Returns empty DataFrame, does not raise error. |
| **TC_T2_06** | F2 | Negative Spreads | Raw tick array with bid > ask | Incorrect quote simulation | Filters out anomalous ticks (warns/logs) and retains only valid bid < ask rows. |
| **TC_T2_07** | F3 | Insufficient Samples | dataset size < $N$ folds | 5 samples, $N=10$ | Split generator raises `ValueError` indicating dataset is too small. |
| **TC_T2_08** | F3 | Invalid CPCV Parameters | $k \ge N$ (e.g. $k=3, N=3$) | Toy dataset | Split generator raises `ValueError` (test folds must be strictly less than total groups). |
| **TC_T2_09** | F3 | Single Sample Folds | $N$ equals sample count | $N=100$, 100 samples | CPCV splits successfully into single-row groups without division-by-zero errors. |
| **TC_T2_10** | F4 | Instant TP/SL Hit | `hit_time == start_time` | Dynamic barrier hit | Purging logic handles zero-duration intervals without crash, treating it as active only on that single bar. |
| **TC_T2_11** | F4 | Indefinite Label Timeout | `hit_time == NaT` (never hit) | Unlabeled/timeout events | Purged training set extends to vertical barrier timeout limit; handles missing hit times. |
| **TC_T2_12** | F4 | Embargo Out of Bounds | Test fold at end of series | Test fold is last partition | Embargo window truncation is handled gracefully without index overflow. |
| **TC_T2_13** | F4 | Hyper-Purged Dataset | Test intervals cover all data | Extreme overlaps | Training set reduces to empty series; downstream models handle empty train split gracefully. |
| **TC_T2_14** | F5 | Zero Volatility Returns | Returns = 0 for all bars | Zero price changes | Sharpe and Sortino ratio calculations return `0.0` or `NaN` instead of raising division-by-zero. |
| **TC_T2_15** | F5 | Extreme Slippage | Slippage set to 500 pips | Slippage model execution | Net returns become highly negative; metrics (Sharpe/Sortino) degrade to minimum caps. |
| **TC_T2_16** | F5 | NaN/Inf Returns | Returns series containing NaN | Price gaps or data holes | Metric calculators drop NaN values automatically and calculate stats on valid subset. |
| **TC_T2_17** | F5 | DSR with Single Trial | Number of trials = 1 | Single model evaluated | DSR equals standard Sharpe ratio; no multi-testing penalty applied. |
| **TC_T2_18** | F6 | Skewed Label Distribution | 99% Long labels | High drift environment | Baseline model achieves 99% accuracy; model accuracy must be evaluated relative to this. |
| **TC_T2_19** | F6 | Negative Baseline Sharpe | Buy-and-Hold Sharpe is -1.5 | Bear market environment | Model with Sharpe of 0.1 shows positive relative gain despite low absolute Sharpe. |
| **TC_T2_20** | F6 | Zero Trade Execution | Strategy executes zero trades | Flat signals | Strategy Sharpe is `0.0`, relative Sharpe compared to baseline matches negative baseline Sharpe. |

---

## TIER 3: Cross-Feature Combinations (Test Cases 41 - 56)
*Validates the interfaces, conversions, and integrity checks when multiple features are linked together in the validation pipeline.*

| Test ID | Feature | Test Case Name | Inputs / Setup | Mock Behavior | Expected Behavior & Assertions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC_T3_01** | F1 + F2 | Tick-Bar Spread Aggregation | Tick database + H4 bar database | Query overlapping times | Weighted average tick spread matches the H4 bar spread within tolerance ($\pm 0.1$ pips). |
| **TC_T3_02** | F1 + F2 | Bar Close Price Verification | Raw ticks + H4 bar close | Query bar end time | Last tick price within the bar window equals the H4 bar `close` price exactly. |
| **TC_T3_03** | F1 + F2 | Dual Ingestion DB Sync | Multi-day sync run | DB mock connections | Both tables `ohlcv_data` and `tick_data` are synchronized; foreign key/time constraints match. |
| **TC_T3_04** | F1 + F2 | Tick Volatility vs H4 Vol | Raw ticks series, H4 bars | Volatility calculators | Bar-based Yang-Zhang volatility correlates with tick-based realized volatility ($r > 0.85$). |
| **TC_T3_05** | F1+F3+F4 | End-to-End CPCV Split | Ingested OHLCV | Standard CPCV split | Ingested data is split, purged, and embargoed; returns valid disjoint numpy arrays for training. |
| **TC_T3_06** | F1+F4 | ATR Purging Window | Ingested H4 + calculated ATR | Triple barrier labeling | Purging window width scales dynamically with ATR values computed from the ingested data. |
| **TC_T3_07** | F2+F4 | Tick Path Purging Bounds | Tick database, H4 events | Tick-level TP/SL hits | Purging is applied to the exact timestamp of the tick-level barrier hit rather than the H4 bar close. |
| **TC_T3_08** | F3+F4 | Uniqueness Weights on splits | CPCV train folds | Overlapping label events | Sample uniqueness weights are re-calculated inside each training fold after purging is applied. |
| **TC_T3_09** | F3+F5 | Fold-Level Sharpe | CPCV train/test splits | Metric calculator | Sharpe ratio is computed for each test fold; returns a vector of $C(N,k)$ Sharpe values. |
| **TC_T3_10** | F3+F5 | Multi-Split DSR | Model outcomes across splits | DSR calculation | DSR is calculated using the variance of Sharpe ratios across all combinatorial CPCV splits. |
| **TC_T3_11** | F3+F5 | Go/No-Go Gate Decision | Mean/Min Sharpe threshold | Validation pipeline run | If mean cost-adjusted Sharpe across folds is $< 0.5$, the pipeline halts and reports failure. |
| **TC_T3_12** | F3+F5 | Split-Tuned Hyperparameters | Search grid of models | CPCV fold performance | Parameter selection picks parameters that maximize cost-adjusted Sortino ratio on purged splits. |
| **TC_T3_13** | F5+F6 | Strategy vs Buy-and-Hold | Cost-adjusted returns | Strategy vs Asset | strategy Sharpe is compared with Buy-and-Hold Sharpe under identical commission settings. |
| **TC_T3_14** | F5+F6 | DSR vs Random Entry | 100 model iterations | Monte Carlo path gen | Strategy DSR exceeds the 95th percentile of the randomized entry DSR distribution. |
| **TC_T3_15** | F5+F6 | Regime-Conditional Baseline | Trending vs ranging folds | Hurst/KER regime routing | Model beats the regime-specific baseline (e.g. beats mean-reversion during ranging periods). |
| **TC_T3_16** | F5+F6 | Walk-Forward vs Benchmark | Purged CPCV + OOS block | Walk-forward evaluation | OOS Sharpe is higher than Buy-and-Hold Sharpe on the OOS period; triggers Go-gate. |

---

## TIER 4: Real-World Workloads & Stress (Test Cases 57 - 71)
*Tests performance, scalability, memory usage, and stability under realistic trading volume loads and simulated system faults.*

| Test ID | Feature | Test Case Name | Inputs / Setup | Mock Behavior | Expected Behavior & Assertions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC_T4_01** | F1 | 10-Year H4 Ingestion | 15,000 H4 bars for 2 symbols | Large data stream | Ingestion handles conversion, index setting, and syncing of 30,000 bars in $< 10$ seconds. |
| **TC_T4_02** | F2 | 1-Million Tick Storm | High-frequency news window | News release tick spikes | Ingests, parses, and formats 1,000,000 ticks; memory usage remains stable (no memory leaks). |
| **TC_T4_03** | F1 + F2 | DB Disconnection Recovery | Syncing during DB drop | Database connection drops | Syncing halts, caches data, retries connection, and resumes syncing without losing data. |
| **TC_T4_04** | F1 + F2 | Concurrent Multi-Pair Ingestion | EURUSD, GBPUSD, USDJPY, XAUUSD | Multi-threaded requests | Ingests all 4 symbols concurrently; database writes execute without deadlock or transaction rollbacks. |
| **TC_T4_05** | F3 | Large-Scale CPCV Split | $N=10, k=2$ (45 splits) | 10,000 H4 samples | Split arrays are generated in $< 1$ second; memory footprint remains under 100MB. |
| **TC_T4_06** | F4 | High-Overlap Purge | 10,000 events, long barriers | Dynamic TP/SL events | Purging index lookup runs in $< 2$ seconds using optimized interval trees or pandas operations. |
| **TC_T4_07** | F3 + F4 | Imbalanced Folds Splitting | Highly persistent trend data | Skewed regime segments | CPCV splits balance sample numbers; purging does not result in empty training sets in any split. |
| **TC_T4_08** | F4 | Purge Memory Profiling | Continuous runs on large arrays | 50 sequential CPCV splits | Memory consumption does not grow between splits (verified with memory profiling mock). |
| **TC_T4_09** | F5 | News Slippage Shock | CHF peg removal / Brexit event | Extreme spreads & slippage | Cost model scales up transaction costs; Sharpe and Sortino ratios drop, triggering de-risk gates. |
| **TC_T4_10** | F5 | DSR with 1,000 candidates | 1,000 strategy iterations | High configuration variance | DSR correctly scales down confidence (Sharpe of 2.0 deflates to 0.4 due to multiple testing). |
| **TC_T4_11** | F6 | Volatility Regime Shift | 5-year H4 including 2020 crash | Volatility shock regime | Model routes to stand-down or beats Buy-and-Hold during regime transitions; zero blow-up. |
| **TC_T4_12** | F5 + F6 | Walk-Forward Cost Stress | High spread + slip on OOS | OOS performance testing | If OOS Sharpe drops below 0.3 after cost stress, the pipeline asserts No-Go. |
| **TC_T4_13** | F1-F6 | Full Training Integration | End-to-end pipeline run | Mock MT5 + DB connection | Raw data flows to trained meta-model and returns valid signals and weights; runs without warnings. |
| **TC_T4_14** | F5 + F6 | Go/No-Go Decision Gate | Final pipeline validation | Calibrated performance | Gateway asserts execution block when validation criteria fail; prevents live execution. |
| **TC_T4_15** | F5 + F6 | Automated retrain trigger | Simulated model decay | performance metrics drop | Retraining script is triggered when rolling Sharpe falls below Buy-and-Hold Sharpe over 100 bars. |

---

# APPENDIX D: Pytest Configuration & Runner Setup

To implement a clean test execution environment, configure `pytest.ini` and structure the test files co-located with the source code layers.

### 1. Pytest Configuration File (`pytest.ini`)
Create `pytest.ini` in the root directory:

```ini
[pytest]
minversion = 7.0
testpaths = src
addopts = 
    --tb=short
    --strict-markers
    --cov=src
    --cov-report=term-missing
    --cov-report=html
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    unit: Small, isolated unit tests.
    integration: Tests that verify interaction between multiple layers.
    stress: Long-running performance and volume stress tests.
```

### 2. Recommended Co-located Directory Layout
Following the `PROJECT.md` layout, test files are co-located within each layer module. This prevents path resolution errors and groups code with its verification.

```
c:\Users\swing\Desktop\TRADING\Thor\
├── pytest.ini
├── conftest.py
├── requirements.txt
└── src/
    ├── api/
    │   ├── main.py
    │   └── test_main.py                  <-- Co-located API tests
    ├── core/
    │   ├── config.py
    │   ├── db.py
    │   └── test_db.py                    <-- Co-located Core DB tests
    └── layers/
        ├── l0_ingestion/
        │   ├── db_sync.py
        │   ├── mt5_client.py
        │   ├── test_db_sync.py           <-- Co-located DB sync tests
        │   └── test_mt5_client.py        <-- Co-located MT5 Client tests
        ├── l1_features/
        │   ├── cross_pair.py
        │   ├── session.py
        │   ├── trend_memory.py
        │   ├── volatility.py
        │   └── test_features.py          <-- Co-located Feature engineering tests
        └── l4_labeling/
            ├── sample_weights.py
            ├── triple_barrier.py
            ├── test_sample_weights.py    <-- Co-located Weights tests
            └── test_triple_barrier.py    <-- Co-located Labeling tests
```
