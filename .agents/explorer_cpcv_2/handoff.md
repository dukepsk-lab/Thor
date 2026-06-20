# Handoff: Triple-Barrier Labeling & Overlap Purging Investigation

## 1. Observation

In the current codebase, the labeling and weighting systems are defined in two primary files:
1. `src/layers/l4_labeling/triple_barrier.py`
2. `src/layers/l4_labeling/sample_weights.py`

### Observations from `triple_barrier.py`:
- Line 4: The function `apply_triple_barrier` accepts a DataFrame and parameters:
  ```python
  def apply_triple_barrier(df: pd.DataFrame, atr_multiplier_tp: float = 2.0, atr_multiplier_sl: float = 2.0, vertical_bars: int = 20) -> pd.DataFrame:
  ```
- Lines 17-18: The vertical barrier `t1` is defined by shifting the index by `vertical_bars` bars:
  ```python
  events = pd.DataFrame(index=df.index)
  events['t1'] = df.index.to_series().shift(-vertical_bars) # Vertical barrier
  ```
- Lines 28-30: The start time of each trade event $i$ is its index `df.index[i]`, and the timeout end time is `events['t1'].iloc[i]`:
  ```python
  start_time = df.index[i]
  end_time = events['t1'].iloc[i]
  ```
- Lines 43-44: Upper and lower barrier hit times are computed based on high and low prices crossing the ATR-scaled barriers:
  ```python
  hit_upper = path[path['high'] >= upper].index.min()
  hit_lower = path[path['low'] <= lower].index.min()
  ```
- Lines 68-69: The final output contains `label` (TP = 1, SL = -1, Timeout = 0) and `hit_time` (representing the exact time the event ended):
  ```python
  events['label'] = labels
  events['hit_time'] = hit_times
  ```

### Observations from `sample_weights.py`:
- Lines 4-31: The function `calculate_sample_uniqueness` is implemented as:
  ```python
  def calculate_sample_uniqueness(events: pd.DataFrame, close_index: pd.Index) -> pd.Series:
      """
      Calculate sample uniqueness based on overlapping labels.
      ...
      """
      out = pd.Series(0.0, index=events.index)
      
      for i, start_time in enumerate(events.index):
          end_time = events['hit_time'].iloc[i]
          if pd.isna(end_time):
              continue
              
          # Number of concurrent active labels during this label's lifetime
          concurrent_labels = ((events.index <= start_time) & (events['hit_time'] > start_time)).sum()
          
          # Simple uniqueness approximation
          out.loc[start_time] = 1.0 / max(1, concurrent_labels)
          
      return out
  ```
- Critically, the `close_index` parameter is documented in the docstring but **never used** in the function body.
- The concurrency calculation only counts active labels at `start_time`, representing a single-point approximation rather than the true average uniqueness over the sample's full duration $[t_{i,0}, t_{i,1}]$.
- The complexity of the current loop is $O(N^2)$ due to the nested pandas boolean indexing inside a loop over $N$ events.

---

## 2. Logic Chain

### A. Start Times and Hit Times mapping to Event Intervals
From our observations of `triple_barrier.py`, each trade sample $i$ is characterized by:
- $t_{i,0}$: Start time (index of the event).
- $t_{i,1}$: Hit time (stored in `hit_time` column), which is the timestamp when the first barrier was hit.
This means the information window for training sample $i$ is the closed interval $[t_{i,0}, t_{i,1}]$.

### B. Mathematical Overlap Formulation
Two samples $i$ (training) and $j$ (testing) overlap if and only if their intervals intersect:
$$[t_{i,0}, t_{i,1}] \cap [t_{j,0}, t_{j,1}] \neq \emptyset$$
This intersection is non-empty if and only if:
$$\max(t_{i,0}, t_{j,0}) \le \min(t_{i,1}, t_{j,1})$$
Any training sample $i$ that overlaps with any test sample $j \in S_{test}$ must be **purged** to prevent information leakage.

### C. Embargoing Logic
To prevent leakage from features with memory (e.g. rolling features of lookback window $W$), we define an embargo period of length $h \ge W$ after the test fold. The test fold's activity ends at the maximum hit time of the test events:
$$T_{test, max} = \max_{j \in S_{test}} (t_{j,1})$$
Any training sample $i$ starting after the test fold must start after $T_{test, max} + h$.
Thus, the embargo condition requires purging training samples starting in $(T_{test, max}, T_{test, max} + h]$.

### D. The Unified Keep Condition
Combining purging (pre-test and post-test overlap) and embargoing for a test fold whose events start in $[T_0, T_1]$, we find that a training sample $i$ is kept if and only if it does not overlap with the forbidden zone $[T_0, T_{test, max} + h]$.
This yields the **Unified Keep Condition**:
$$\text{Keep}(i) \iff \left(t_{i,1} < T_0\right) \lor \left(t_{i,0} > T_{test, max} + h\right)$$
For multiple disjoint test folds (as in CPCV), this must hold across all folds:
$$\text{Keep}(i) \iff \forall m \in \{1, \dots, M\}, \quad \left(t_{i,1} < T_{0,m}\right) \lor \left(t_{i,0} > T_{test, max, m} + h\right)$$

---

## 3. Caveats

1. **Resolution Dependency**: The accuracy of the start and hit times is bounded by the bar timeframe (H4 in this system). Intra-bar overlaps are not captured; we assume the discrete H4 bars represent the pricing grid.
2. **Embargo Size Selection**: The embargo parameter $h$ must be selected to be at least as large as the maximum feature lookback window. If the lookback is 50 bars (approx 8.3 days on H4), $h$ must be configured to match this.
3. **Timezone Alignment**: The indices of the price series and events series must be strictly aligned and use consistent timezone representation (aware vs. naive).

---

## 4. Conclusion

1. **Purging & Embargoing**: Overlapping training samples can be successfully purged by applying the derived keep condition. This eliminates the need for expensive multi-interval union operations and integrates embargoing natively.
2. **Sample Uniqueness Correction**: The current `calculate_sample_uniqueness` is a crude approximation that ignores the full duration of events and has an $O(N^2)$ time complexity. We propose a vectorized $O(N \log T + T)$ cumulative sum algorithm that is mathematically exact and highly efficient.

### Clean Design Pattern

```python
import pandas as pd
import numpy as np
from typing import List, Tuple, Union

class PurgingEmbargoManager:
    """
    Manages the purging and embargoing of training samples to prevent
    information leakage during cross-validation (specifically CPCV).
    """
    def __init__(self, embargo_pct: float = 0.01):
        """
        Args:
            embargo_pct: Percentage of total data points to use for the embargo window.
        """
        self.embargo_pct = embargo_pct

    def purge_train_set(
        self,
        event_times: pd.Series,
        test_folds: List[Tuple[pd.Timestamp, pd.Timestamp]]
    ) -> pd.Index:
        """
        Purges training samples overlapping with the test folds and applies embargo.
        
        Args:
            event_times: pd.Series where index is start time (t0) and value is hit time (t1).
            test_folds: A list of (test_start, test_end) representing disjoint test folds.
                        test_start (T0) and test_end (T1) define the boundaries of the test event start times.
            
        Returns:
            pd.Index: The indices of the training samples that survived purging and embargoing.
        """
        train_idx = event_times.index.copy()
        
        # Calculate embargo size in terms of bars
        embargo_offset = int(len(event_times) * self.embargo_pct)
        
        for t0, t1 in test_folds:
            # Find the test events in this fold
            fold_events = event_times.loc[t0:t1]
            if fold_events.empty:
                continue
                
            # T_test,max is the maximum hit time of any event starting in the test fold
            t_test_max = fold_events.max()
            
            # Find the embargo limit time (t_test_max + h)
            hit_idx = event_times.index.searchsorted(t_test_max)
            embargo_idx = min(hit_idx + embargo_offset, len(event_times) - 1)
            t_embargo = event_times.index[embargo_idx]
            
            # Unified Keep Condition:
            # Keep sample i iff it ends before t0 OR starts after t_embargo
            keep_mask = (event_times < t0) | (event_times.index > t_embargo)
            train_idx = train_idx.intersection(event_times[keep_mask].index)
            
        return train_idx


def calculate_sample_uniqueness_exact(events: pd.DataFrame, close_index: pd.Index) -> pd.Series:
    """
    Vectorized O(N log T + T) average uniqueness calculation using cumulative sums.
    Eliminates the O(N * T) memory scaling and the O(N^2) time complexity.
    
    Args:
        events: DataFrame with 'hit_time' (when the barrier was hit). Index is trade start time.
        close_index: The index of the full price series.
        
    Returns:
        pd.Series: Average uniqueness values [0, 1] for each label, indexed by start time.
    """
    # Filter out events with invalid/NaN hit times
    valid_events = events[events['hit_time'].notna()].copy()
    if valid_events.empty:
        return pd.Series(dtype=float, index=events.index)
        
    # 1. Compute concurrency c_t for each price bar in close_index
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
    
    # 2. Compute average uniqueness for each event using cumulative sum of inv_c
    cum_inv_c = np.zeros(len(close_index) + 1, dtype=np.float64)
    cum_inv_c[1:] = np.cumsum(inv_c)
    
    # Sum of 1 / c_t for event i from start_idx[i] to end_idx[i] - 1
    sums = cum_inv_c[end_idx] - cum_inv_c[start_idx]
    
    # Number of bars in event i's lifetime
    lengths = end_idx - start_idx
    lengths_safe = np.maximum(1, lengths)
    
    # Average uniqueness
    avg_uniq = sums / lengths_safe
    
    # Reindex back to original events DataFrame to handle any missing/NaN hit times
    result = pd.Series(np.nan, index=events.index)
    result.loc[valid_events.index] = avg_uniq
    
    return result
```

---

## 5. Verification Method

To verify the logic and correctness of this implementation, the following unit test pattern is proposed (can be run with `pytest` once implemented in test suites):

```python
def test_purging_and_uniqueness():
    import pandas as pd
    import numpy as np
    
    # Create mock price index (H4 bars)
    price_idx = pd.date_range(start="2026-01-01", periods=10, freq="4h")
    
    # Create mock events
    # Event 0: starts at 0, hits at 2 (spans 0, 1, 2)
    # Event 1: starts at 1, hits at 3 (spans 1, 2, 3)
    # Event 2: starts at 4, hits at 6 (spans 4, 5, 6)
    events = pd.DataFrame({
        'hit_time': [price_idx[2], price_idx[3], price_idx[6]]
    }, index=[price_idx[0], price_idx[1], price_idx[4]])
    
    # --- 1. Test Uniqueness ---
    uniq = calculate_sample_uniqueness_exact(events, price_idx)
    
    # Expected Concurrency:
    # bar 0: E0 (1) -> uniq: 1.0
    # bar 1: E0, E1 (2) -> uniq: 0.5
    # bar 2: E0, E1 (2) -> uniq: 0.5
    # bar 3: E1 (1) -> uniq: 1.0
    # bar 4: E2 (1) -> uniq: 1.0
    # bar 5: E2 (1) -> uniq: 1.0
    # bar 6: E2 (1) -> uniq: 1.0
    
    # Expected Avg Uniqueness:
    # E0: (1.0 + 0.5 + 0.5) / 3 = 2.0 / 3 = ~0.667
    # E1: (0.5 + 0.5 + 1.0) / 3 = 2.0 / 3 = ~0.667
    # E2: (1.0 + 1.0 + 1.0) / 3 = 1.0
    
    assert np.allclose(uniq.iloc[0], 2.0/3)
    assert np.allclose(uniq.iloc[1], 2.0/3)
    assert np.allclose(uniq.iloc[2], 1.0)
    print("Uniqueness test passed!")
    
    # --- 2. Test Purging and Embargo ---
    # Define test fold spanning Event 1: starts at price_idx[1], ends at price_idx[3]
    # Embargo of 1 bar (approx 10% of dataset length here)
    manager = PurgingEmbargoManager(embargo_pct=0.1)  # 10% of 3 events = 0 bars? No, pct * length.
    # Let's say we set embargo_offset manually or check with 0% embargo first
    manager_no_embargo = PurgingEmbargoManager(embargo_pct=0.0)
    
    # Test fold start = price_idx[1], test fold end = price_idx[2]
    # This selects Event 1 (starts at price_idx[1])
    test_folds = [(price_idx[1], price_idx[1])]
    
    train_idx = manager_no_embargo.purge_train_set(events['hit_time'], test_folds)
    
    # Event 0 starts before test fold, but hits at price_idx[2] which is >= test fold start (price_idx[1]).
    # So Event 0 must be purged.
    # Event 1 is the test fold, so it is removed.
    # Event 2 starts at price_idx[4], which is > max hit time of test fold (price_idx[3]).
    # So Event 2 must be kept.
    assert len(train_idx) == 1
    assert train_idx[0] == price_idx[4]
    print("Purging test passed!")

if __name__ == '__main__':
    test_purging_and_uniqueness()
```

### Invalidation Conditions
- If the start times in `event_times` are not monotonically increasing, the searchsorted method for indexing can locate incorrect positions.
- If `hit_time` values contain NaNs that are not properly filtered out, they will result in `NaT` indexing errors.
