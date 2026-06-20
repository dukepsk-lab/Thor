# Handoff Report — Explorer 2.2 (Iteration 2)

## 1. Observation
1. **Uniqueness Calculation Bug with Duplicate Timestamps**:
   - Location: `validation_harness/cpcv.py` lines 258-260:
     ```python
     result = pd.Series(np.nan, index=events.index)
     result.loc[valid_events.index] = avg_uniq
     return result
     ```
   - When events have duplicate timestamps in their index, assigning values using label-based `.loc` with an array of length equal to `valid_events` raises a `ValueError` because label alignment expands the indexer list-like representation.
   - Verbatim error reproduced via PowerShell:
     ```
     ValueError: cannot set using a list-like indexer with a different length than the value
     ```

2. **SQLAlchemy 2.0 Raw Query Execution**:
   - Location: `validation_harness/tests/conftest.py` lines 388-417:
     ```python
     engine = create_engine("sqlite:///:memory:")
     with engine.begin() as conn:
         conn.execute(text("""
             CREATE TABLE ohlcv_data (
                 ...
     ```
   - SQLAlchemy 2.0 raises `sqlalchemy.exc.ObjectNotExecutableError: Not an executable object` if plain string queries are passed to `conn.execute()` instead of wrapping them in `sqlalchemy.text()`.

3. **OHLCV Data Boundary Violations**:
   - Location: `validation_harness/tests/conftest.py` lines 322-338 (`sample_ohlcv_data` fixture):
     ```python
     "open": [1.0800, 1.0810, 1.0805, 1.0820, 1.0830, 1.0825, 1.0840, 1.0850, 1.0845, 1.0860],
     "high": [1.0815, 1.0820, 1.0825, 1.0835, 1.0845, 1.0845, 1.0855, 1.0860, 1.0865, 1.0870],
     "low":  [1.0795, 1.0800, 1.0798, 1.0810, 1.0820, 1.0820, 1.0835, 1.0840, 1.0838, 1.0850],
     "close": [1.0810, 1.0805, 1.0820, 1.0830, 1.0840, 1.0840, 1.0850, 1.0845, 1.0860, 1.0865]
     ```
   - In `validation_harness/ingestion.py`, `validate_ohlcv_data` checks that `high >= max(open, close)` and `low <= min(open, close)`. Static values are prone to human errors during manual changes, violating boundaries.

---

## 2. Logic Chain
1. **Duplicate Timestamp ValueError**:
   - When we have duplicate indices (e.g. two events start at `2023-01-01`), the Series `result` has duplicate keys.
   - Performing `result.loc[valid_events.index] = avg_uniq` uses label indexing. Since `valid_events.index` has duplicate values, locating the keys returns an expanded length, causing a mismatch with the size of `avg_uniq`.
   - By initializing `result` first and performing positional indexing (`.iloc`) using the integer indices of non-null events (`np.where(events['hit_time'].notna())[0]`), we safely assign the values based on their positional alignment rather than label lookup.

2. **SQLAlchemy 2.0 Text Clause wrapping**:
   - The connection execution engine in SQLAlchemy 2.0 does not accept raw strings as executables.
   - The current fixture `db_engine` in `conftest.py` is already compliant as it wraps the raw SQL tables definition strings in `text(...)`. We must preserve this and recommend ensuring any other raw queries added subsequently follow this rule.

3. **OHLCV Validator boundary safety**:
   - Programmatically resetting `high` and `low` prices using element-wise max/min:
     ```python
     df["high"] = df[["open", "close", "low", "high"]].max(axis=1)
     df["low"] = df[["open", "close", "high", "low"]].min(axis=1)
     ```
     guarantees that regardless of any manually defined values in the fixture, the price boundaries will always be mathematically valid and pass the validator boundaries checks.

---

## 3. Caveats
- Investigated only the three specific requested issues.
- Other critical bugs in `CombinatorialPurgedKFold` identified by the Forensic Auditor (Index Alignment Scrambling, IndexError on Empty Test Splits, Slicing performance bottleneck) are not addressed in the proposed changes but have been outlined in the conclusion for future iterations.

---

## 4. Conclusion
We recommend implementing the following code changes:

### Fix 1: Exact Sample Uniqueness in `validation_harness/cpcv.py`
Replace `calculate_sample_uniqueness_exact` (lines 209-260) with:
```python
def calculate_sample_uniqueness_exact(events: pd.DataFrame, close_index: pd.Index) -> pd.Series:
    """
    Vectorized O(N log T + T) average uniqueness calculation using cumulative sums.
    Eliminates the O(N * T) memory scaling and the O(N^2) time complexity.
    """
    # 1. Initialize result Series matching the index and length of the inputs
    result = pd.Series(np.nan, index=events.index, dtype=float)
    
    # 2. Filter out events with invalid/NaN hit times
    valid_events = events[events['hit_time'].notna()]
    if valid_events.empty or len(close_index) == 0:
        return result
        
    # 3. Compute concurrency c_t for each price bar in close_index
    counts = np.zeros(len(close_index) + 1, dtype=np.int64)
    
    # Map start times and hit times to indices in close_index
    start_idx = close_index.searchsorted(valid_events.index)
    end_idx = close_index.searchsorted(valid_events['hit_time'], side='right')
    
    # Increment concurrency at start, decrement at first bar strictly after hit_time
    np.add.at(counts, start_idx, 1)
    np.add.at(counts, end_idx, -1)
    
    # Cumulative sum to get active count at each bar
    c = np.cumsum(counts)[:-1]
    c_safe = np.maximum(1, c)
    
    # Uniqueness at each bar t is 1 / c_t
    inv_c = 1.0 / c_safe
    
    # 4. Compute average uniqueness for each event using cumulative sum of inv_c
    cum_inv_c = np.zeros(len(close_index) + 1, dtype=np.float64)
    cum_inv_c[1:] = np.cumsum(inv_c)
    
    # Sum of 1 / c_t for event i from start_idx[i] to end_idx[i] - 1
    sums = cum_inv_c[end_idx] - cum_inv_c[start_idx]
    
    # Number of bars in event i's lifetime
    lengths = end_idx - start_idx
    lengths_safe = np.maximum(1, lengths)
    
    # Average uniqueness
    avg_uniq = sums / lengths_safe
    
    # 5. Populate and return using .iloc to avoid index alignment scrambling
    result.iloc[np.where(events['hit_time'].notna())[0]] = avg_uniq
    return result
```

### Fix 2: SQLAlchemy 2.0 Compliance in `validation_harness/tests/conftest.py`
Confirm that lines 388-417 wrap SQL execution statements with `text()`:
```python
        conn.execute(text("""
            CREATE TABLE ohlcv_data (
                ...
```
Ensure any subsequent test query executions (e.g. in test suites or database checks) import `text` from `sqlalchemy` and wrap queries appropriately.

### Fix 3: Programmatic Boundary Enforcement in `validation_harness/tests/conftest.py`
Update `sample_ohlcv_data` fixture (lines 322-338) to:
```python
@pytest.fixture
def sample_ohlcv_data():
    """
    Returns a standard 10-bar OHLCV DataFrame (H4 EURUSD style).
    """
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="4h")
    data = {
        "open": [1.0800, 1.0810, 1.0805, 1.0820, 1.0830, 1.0825, 1.0840, 1.0850, 1.0845, 1.0860],
        "high": [1.0815, 1.0820, 1.0825, 1.0835, 1.0845, 1.0845, 1.0855, 1.0860, 1.0865, 1.0870],
        "low":  [1.0795, 1.0800, 1.0798, 1.0810, 1.0820, 1.0820, 1.0835, 1.0840, 1.0838, 1.0850],
        "close": [1.0810, 1.0805, 1.0820, 1.0830, 1.0840, 1.0840, 1.0850, 1.0845, 1.0860, 1.0865],
        "tick_volume": [100, 120, 110, 130, 140, 125, 150, 160, 145, 170],
        "spread": [12, 10, 11, 12, 13, 11, 12, 10, 11, 12],
        "real_volume": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    }
    df = pd.DataFrame(data, index=dates)
    # Programmatic boundary enforcement to guarantee validation check compliance
    df["high"] = df[["open", "close", "low", "high"]].max(axis=1)
    df["low"] = df[["open", "close", "high", "low"]].min(axis=1)
    df.index.name = "time"
    return df
```

---

## 5. Verification Method
1. Run `pytest` to ensure all existing 83 tests pass successfully.
2. Run the duplicate index validation script:
   ```powershell
   python -c "import pandas as pd, numpy as np; from validation_harness.cpcv import calculate_sample_uniqueness_exact; events = pd.DataFrame({'hit_time': pd.to_datetime(['2023-01-02', '2023-01-02', '2023-01-03'])}, index=pd.to_datetime(['2023-01-01', '2023-01-01', '2023-01-02'])); close_index = pd.date_range('2023-01-01', '2023-01-04', freq='D'); print(calculate_sample_uniqueness_exact(events, close_index))"
   ```
   - Before fix: Raises `ValueError: cannot set using a list-like indexer with a different length than the value`.
   - After fix: Runs successfully and prints the uniqueness Series without raising errors.
