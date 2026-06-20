# Handoff — CPCV Embargo & API Interface Design

## 1. Observation
We observed the following files and codebase structures:
1. **`validation_harness/PROJECT.md`** specifies the target interface for `get_cpcv_splits` (lines 64-79):
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
2. **`src/layers/l4_labeling/triple_barrier.py`** (lines 68-71) returns a DataFrame with:
   - Index: event start times.
   - Column `'hit_time'`: the event's barrier hit or timeout end time.
3. **`src/layers/l4_labeling/sample_weights.py`** computes sample uniqueness based on overlapping labels using the events index and `'hit_time'`.
4. Run commands confirmed that Python 3.11.0, pandas, numpy, and scikit-learn are installed.
5. We wrote a prototype class implementation `CombinatorialPurgedKFold` in `cpcv_prototype.py` and executed it. The test output showed correct indices and behaviour for all embargo modes:
   - **No embargo (0)**: `Split 0: Train=[4 5 6 7 8 9], Test=[0 1 2]`
   - **12 hours timedelta**: `Split 0: Train=[5 6 7 8 9], Test=[0 1 2]`
   - **5 bars absolute count**: `Split 0: Train=[5 6 7 8 9], Test=[0 1 2]`
   - **10% (10 bars) percentage**: `Split 0: Train=[5 6 7 8 9], Test=[0 1 2]`

---

## 2. Logic Chain
- **Requirement for Purging & Embargoing**:
  - In financial time-series, labels are computed over a forward-looking window $[t, t_1]$ (e.g. triple-barrier).
  - If a training sample's label interval $[t_{train, 0}, t_{train, 1}]$ overlaps with a test sample's interval $[t_{test, 0}, t_{test, 1}]$, information leaks between the sets.
  - Furthermore, serial correlation in features/returns means that training samples starting immediately *after* a test fold ends will carry leaked information.
  - Thus, we must **purge** overlapping training samples, and **embargo** training samples starting within a buffer period after the test fold.
- **Formulating Embargo Application**:
  - Let $P_c$ be a test partition in the selected combination.
  - Let $T_{test, max\_hit}(P_c) = \max_{j \in P_c} t_{j, 1}$ be the maximum hit time of the test samples in that partition.
  - The embargo buffer starts at $T_{test, max\_hit}(P_c)$ and ends at $T_{embargo}(P_c) = T_{test, max\_hit}(P_c) + \text{embargo\_window}$.
  - Any training sample $i$ that starts *after* the test partition begins ($t_{i, 0} \ge \min_{j \in P_c} t_{j,0}$) must not start within the embargo buffer.
  - If $t_{i, 0} \le T_{embargo}(P_c)$, it is discarded.
  - This single check ($t_{i, 0} \le T_{embargo}(P_c)$) elegantly handles both purging of future overlapping samples and the embargo period.
  - For training samples starting *before* the test partition ($t_{i, 0} < \min_{j \in P_c} t_{j,0}$), we only purge if they overlap ($t_{i, 1} \ge \min_{j \in P_c} t_{j,0}$).
- **Embargo Window Calculations**:
  - **Timedelta-based**: Direct addition: $T_{embargo}(P_c) = T_{test, max\_hit}(P_c) + \Delta$.
  - **Absolute bar-count**: Given bar count $M$ and reference timeline $T_{ref}$, find the smallest $idx$ such that $T_{ref}[idx] \ge T_{test, max\_hit}(P_c)$. Then $T_{embargo}(P_c) = T_{ref}[\min(idx + M, \text{len}(T_{ref}) - 1)]$.
  - **Percentage-based**: Convert percentage $p$ to bar count $M = \text{int}(p \times \text{len}(T_{ref}))$, then apply absolute bar-count logic.
  - **Reference Timeline Fallback**: If the underlying price series bar timestamps (`bar_times`) are not provided, we fall back to using the event start times index (`event_times`).
- **Scikit-learn Compatibility**:
  - Scikit-learn's CV splitter interface requires `split(X, y=None, groups=None)` returning a generator of `(train_idx, test_idx)`, and `get_n_splits(X=None, y=None, groups=None)`.
  - Since purging and embargoing require event hit times, we pass `pred_times: pd.Series` (matching `X.index`) as a keyword parameter in `split()` or constructor `__init__()`.

---

## 3. Caveats
- **Duplicate Timestamps**: If multiple events start at the exact same timestamp, `t_start.iloc[part_indices].min()` and `max()` will group them together. This is correct but assumes partitions do not split events starting at the exact same time.
- **Reference Timeline Alignment**: When searching for $T_{test, max\_hit}(P_c)$ in the reference index, if the hit time is far outside the index range (e.g. beyond the last bar), the index is capped at the last bar.
- **No Lookahead**: Embargo is only applied to training samples starting *after* the test fold. No backward embargo is applied (as time flows forward).

---

## 4. Conclusion
We recommend implementing the `CombinatorialPurgedKFold` splitter class and `get_cpcv_splits` function wrapper as designed below.

### Proposed Python Class API Interface
```python
import numpy as np
import pandas as pd
import itertools
from typing import Generator, Tuple, List, Union, Optional, Dict

class CombinatorialPurgedKFold:
    """
    Combinatorial Purged Cross-Validation (CPCV) Splitter.
    Compatible with scikit-learn's cross-validation splitter interface.
    """
    def __init__(
        self,
        n_partitions: int = 6,
        n_test_partitions: int = 2,
        purging_offset: pd.Timedelta = pd.Timedelta(hours=0),
        embargo_offset: Union[float, int, pd.Timedelta] = 0.0,
        bar_times: Optional[pd.Index] = None
    ):
        """
        Args:
            n_partitions: Number of partitions N.
            n_test_partitions: Number of test partitions K.
            purging_offset: Padding time to extend the purging window.
            embargo_offset: Embargo window. Can be a float (percentage of bars),
                            an int (absolute bar count), or pd.Timedelta.
            bar_times: DatetimeIndex of the underlying price bars. Used to calculate
                       bar-count and percentage-based embargo. If None, falls back to
                       the event start times index.
        """
        if n_test_partitions >= n_partitions:
            raise ValueError("n_test_partitions must be less than n_partitions")
        self.n_partitions = n_partitions
        self.n_test_partitions = n_test_partitions
        self.purging_offset = purging_offset
        self.embargo_offset = embargo_offset
        self.bar_times = bar_times

    def get_n_splits(self, X: Optional[pd.DataFrame] = None, y: Optional[pd.Series] = None, groups: Optional[pd.Series] = None) -> int:
        """Returns the number of splits (combinations of N choose K)."""
        import math
        return math.comb(self.n_partitions, self.n_test_partitions)

    def _get_embargo_boundary(
        self, 
        t_hit_max: pd.Timestamp, 
        reference_index: pd.Index
    ) -> pd.Timestamp:
        """Calculate the embargo boundary timestamp based on the offset type."""
        if isinstance(self.embargo_offset, pd.Timedelta):
            return t_hit_max + self.embargo_offset
        
        elif isinstance(self.embargo_offset, (int, np.integer)):
            if self.embargo_offset == 0:
                return t_hit_max
            idx = reference_index.searchsorted(t_hit_max)
            embargo_idx = min(idx + self.embargo_offset, len(reference_index) - 1)
            return reference_index[embargo_idx]
            
        elif isinstance(self.embargo_offset, (float, np.float64)):
            if self.embargo_offset == 0.0:
                return t_hit_max
            if not (0.0 <= self.embargo_offset < 1.0):
                raise ValueError("Percentage-based embargo_offset must be in [0.0, 1.0)")
            n_bars = int(self.embargo_offset * len(reference_index))
            idx = reference_index.searchsorted(t_hit_max)
            embargo_idx = min(idx + n_bars, len(reference_index) - 1)
            return reference_index[embargo_idx]
            
        else:
            raise TypeError("embargo_offset must be a pd.Timedelta, int, or float")

    def split(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        pred_times: Optional[pd.Series] = None
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Generate indices to split data into training and test set.

        Args:
            X: Features DataFrame. Index must contain the event start times.
            y: Target Series (optional).
            pred_times: Event end/hit times Series. Index must match X.index.

        Yields:
            train_idx: Numpy array of training indices.
            test_idx: Numpy array of test indices.
        """
        if pred_times is None:
            raise ValueError("pred_times (event hit times) is required for CPCV purging and embargoing.")
            
        t_start = pd.Series(X.index)
        t_hit = pd.Series(pred_times.values, index=t_start.index)
        M = len(X)
        
        # Reference index for bar-count or percentage-based embargo
        reference_index = self.bar_times if self.bar_times is not None else X.index
        if not isinstance(reference_index, pd.DatetimeIndex):
            reference_index = pd.to_datetime(reference_index)
            
        # Divide indices into N partitions
        partition_bounds = np.linspace(0, M, self.n_partitions + 1, dtype=int)
        partitions = [list(range(partition_bounds[i], partition_bounds[i+1])) for i in range(self.n_partitions)]
        
        # Generate N choose K combinations
        partition_combinations = list(itertools.combinations(range(self.n_partitions), self.n_test_partitions))
        
        for test_part_idxs in partition_combinations:
            # Gather all test indices
            test_idx_list = []
            for part_idx in test_part_idxs:
                test_idx_list.extend(partitions[part_idx])
            test_idx = np.array(sorted(test_idx_list))
            
            # Initial train indices
            train_idx_list = [i for i in range(M) if i not in test_idx]
            
            # Apply purging/embargoing for each test partition
            for part_idx in test_part_idxs:
                part_indices = partitions[part_idx]
                if len(part_indices) == 0:
                    continue
                
                t_start_min = t_start.iloc[part_indices].min()
                t_hit_max = t_hit.iloc[part_indices].max()
                
                # Embargo boundary
                t_embargo = self._get_embargo_boundary(t_hit_max, reference_index)
                
                purged_train_idx = []
                for idx in train_idx_list:
                    ti_start = t_start.iloc[idx]
                    ti_hit = t_hit.iloc[idx]
                    
                    # Case 1: Train sample starts before test partition starts
                    if ti_start < t_start_min:
                        # Purge if it overlaps with the test partition start
                        if ti_hit + self.purging_offset >= t_start_min:
                            continue
                    
                    # Case 2: Train sample starts at or after test partition starts
                    else:
                        # Purge and embargo if it starts before embargo boundary
                        if ti_start <= t_embargo:
                            continue
                            
                    purged_train_idx.append(idx)
                
                train_idx_list = purged_train_idx
                
            yield np.array(train_idx_list), test_idx
```

### Wrapper Function matching the `PROJECT.md` Contract
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
    """
    # Create an empty DataFrame using event_times as the index to match X
    X = pd.DataFrame(index=event_times)
    
    cv = CombinatorialPurgedKFold(
        n_partitions=n_partitions,
        n_test_partitions=n_test_partitions,
        purging_offset=purging_offset,
        embargo_offset=embargo_offset
    )
    
    splits = []
    for train_idx, test_idx in cv.split(X, pred_times=event_hit_times):
        splits.append({
            'train': train_idx,
            'test': test_idx
        })
    return splits
```

---

## 5. Verification Method
- **Ad-hoc Testing**:
  - Run the `cpcv_prototype.py` script located in the working directory using:
    `python cpcv_prototype.py`
  - Verify that the output lists correct indices for combinations and matches the expected behavior for no embargo, timedelta embargo, bar-count embargo, and percentage embargo.
- **Unit/Integration Testing**:
  - Implement a unit test suite under `validation_harness/tests/test_cpcv.py` which runs a variety of tests:
    1. Verify `get_n_splits` matches $\binom{N}{K}$.
    2. Check that no index exists in both `train` and `test` sets (disjoint sets).
    3. Verify that train samples overlapping with test samples are purged.
    4. Verify that train samples starting after test folds within the embargo period are correctly excluded.
    5. Test with and without `bar_times` provided.
