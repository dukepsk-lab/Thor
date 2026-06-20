# Handoff Report — CPCV Splitter, Purging, and Embargo Logic Investigation

## 1. Observation
We inspected the splitting, purging, and embargo logic in `validation_harness/cpcv.py` and examined the tests in `validation_harness/tests/test_cpcv.py` and `validation_harness/tests/test_adversarial.py`.

### A. Index Alignment Scrambling
In `validation_harness/cpcv.py` (lines 102–103), the event start and hit times Series are instantiated as:
```python
102:         t_start = pd.Series(X_index_dt, index=original_idx)
103:         t_hit = pd.Series(pd.to_datetime(pred_times.values), index=original_idx)
```
- By using `pred_times.values`, the raw numpy array values are extracted without index matching to `X.index`.
- In `validation_harness/tests/test_adversarial.py` (lines 40–62), the test `test_non_chronological_index_alignment` verifies this issue. When `X` has index `['2023-01-02', '2023-01-01']` (unsorted) and `pred_times` has index `['2023-01-01', '2023-01-02']` (sorted), mapping values by position results in the event starting on `2023-01-02` incorrectly getting `t_hit` of `2023-01-01 12:00:00` (creating a negative duration), while the event starting on `2023-01-01` gets `t_hit` of `2023-01-02 12:00:00` (meaning it incorrectly overlaps with the test fold and is purged, resulting in `train_idx` being empty).

### B. IndexError on Empty/Small Test Splits
In `validation_harness/cpcv.py` (lines 133 and 140):
```python
133:             test_idx = np.array(sorted(test_idx_list))
...
140:             train_idx_arr = np.array([i for i in range(M) if i not in test_idx])
```
- When `test_idx_list` is empty, `test_idx` is created as `np.array([])`. Since no type is specified, NumPy defaults to `float64` dtype.
- Similarly, if `train_idx_arr` is empty, it is created as `np.array([], dtype=float64)`.
- When slicing the start and hit arrays (lines 157–158):
```python
157:                 train_starts = t_start_arr[train_idx_arr]
158:                 train_hits = t_hit_arr[train_idx_arr]
```
NumPy raises an `IndexError`: `arrays used as indices must be of integer (or boolean) type`. This is verified by `test_empty_inputs`, `test_extreme_parameters`, and `test_fewer_samples_than_partitions` in `test_adversarial.py`.

### C. Slicing Bottleneck
In `validation_harness/cpcv.py` (lines 143–155):
```python
143:             for part_idx in test_part_idxs:
144:                 part_indices = partitions[part_idx]
145:                 if len(part_indices) == 0:
146:                     continue
147:                 
148:                 t_start_min = t_start_sorted.iloc[part_indices].min()
149:                 t_hit_max = t_hit_sorted.iloc[part_indices].max()
150:                 
151:                 # Embargo boundary
152:                 t_embargo = self._get_embargo_boundary(t_hit_max, reference_index)
```
- In the outer combination loop, `.iloc[part_indices]` is called on `t_start_sorted` and `t_hit_sorted` Series for each test partition, which incurs high pandas overhead due to Series slicing and instantiation.
- Furthermore, `_get_embargo_boundary` is called inside the loop, executing index search operations (`searchsorted`) repeatedly.
- Since the partitions (determined by `partition_bounds`) are fixed for a given `split()` call, the minimum start time, maximum hit time, and resulting embargo boundary for each partition are constant and can be precomputed outside the combination loop.

---

## 2. Logic Chain
1. **Index Alignment Scrambling**:
   - `pred_times` and `X` can have different sorting orders or index structures.
   - Taking `.values` directly from `pred_times` and wrapping it with a Series indexed by `original_idx` implicitly assumes position-based alignment rather than label-based alignment.
   - We must align `pred_times` to `X.index` before extracting values.
   - When duplicate timestamps are present in the index, standard `reindex` raises `ValueError`. To solve this, we can construct a MultiIndex combining the datetime and its occurrence count (`cumcount()`) to uniquely align matching occurrences in both indexes.
2. **IndexError on Empty/Small Test Splits**:
   - NumPy arrays created from empty lists default to `float64`.
   - Indexing numpy arrays using float-type arrays is prohibited and throws an `IndexError`.
   - Coercing `test_idx` to `dtype=np.int64` and using `np.setdiff1d` to generate `train_idx_arr` ensures that both arrays always maintain integer dtype, even if empty.
3. **Slicing Bottleneck**:
   - Pandas Series slicing (`iloc`) and method calls (`min()`, `max()`) inside a nested loop running `math.comb(N, K) * K` times is extremely slow.
   - Because partitions are fixed, we can precompute the minimum start time and embargo boundary for each of the `N` partitions once, using fast NumPy slicing.
   - Inside the combination loop, we can retrieve these precomputed scalar values by index lookup, avoiding all pandas operations and reducing complexity.

---

## 3. Caveats
- We assumed that `pred_times` is a `pd.Series` with an index that is a subset/match of `X.index`. If `pred_times` has no matching index labels, `reindex` will populate NaTs, which is handled via fillna.
- We assumed that if duplicate datetime index labels are present, they are aligned by their relative occurrence order. This is standard in chronological event data.

---

## 4. Conclusion
We recommend updating `CombinatorialPurgedKFold.split` in `validation_harness/cpcv.py` as follows:

```python
    def split(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None,
        pred_times: Optional[pd.Series] = None
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        if pred_times is None:
            raise ValueError("pred_times (event hit times) is required for CPCV purging and embargoing.")
            
        M = len(X)
        original_idx = np.arange(M)
        
        # Determine event start times from X.index
        if not isinstance(X.index, pd.DatetimeIndex):
            X_index_dt = pd.to_datetime(X.index)
        else:
            X_index_dt = X.index
            
        # Align pred_times to X.index to avoid index alignment scrambling
        if not X.index.equals(pred_times.index):
            if X.index.is_unique and pred_times.index.is_unique:
                pred_times_aligned = pred_times.reindex(X.index)
            else:
                # Robust alignment for duplicate indexes using MultiIndex with occurrence cumcount
                cumcount_x = pd.Series(range(len(X.index)), index=X.index).groupby(level=0).cumcount()
                x_unique = pd.MultiIndex.from_arrays([X.index, cumcount_x])
                
                cumcount_p = pd.Series(range(len(pred_times.index)), index=pred_times.index).groupby(level=0).cumcount()
                p_unique = pd.MultiIndex.from_arrays([pred_times.index, cumcount_p])
                
                pred_times_temp = pd.Series(pred_times.values, index=p_unique)
                pred_times_aligned = pred_times_temp.reindex(x_unique)
        else:
            pred_times_aligned = pred_times

        t_start = pd.Series(X_index_dt, index=original_idx)
        t_hit = pd.Series(pd.to_datetime(pred_times_aligned.values), index=original_idx)
        t_hit = t_hit.fillna(t_start)  # Fallback if NaT
        
        # Sort by start time for contiguous partitioning in time
        sort_order = t_start.sort_values().index
        t_start_sorted = t_start.loc[sort_order].reset_index(drop=True)
        t_hit_sorted = t_hit.loc[sort_order].reset_index(drop=True)
        original_idx_sorted = original_idx[sort_order]
        
        # Reference index for bar-count or percentage-based embargo
        if self.bar_times is not None:
            reference_index = self.bar_times
            if not isinstance(reference_index, pd.DatetimeIndex):
                reference_index = pd.to_datetime(reference_index)
            reference_index = reference_index.sort_values()
        else:
            reference_index = pd.Index(t_start_sorted)
            
        # Divide indices into N partitions
        partition_bounds = np.linspace(0, M, self.n_partitions + 1, dtype=int)
        partitions = [list(range(partition_bounds[i], partition_bounds[i+1])) for i in range(self.n_partitions)]
        
        # Convert start and hit Series to numpy arrays for fast vectorized operations
        t_start_arr = t_start_sorted.values
        t_hit_arr = t_hit_sorted.values
        
        # Precompute partition-level boundaries (t_start_min and t_embargo) to avoid slicing bottleneck in loop
        partition_starts = []
        partition_embargoes = []
        for i in range(self.n_partitions):
            start_idx = partition_bounds[i]
            end_idx = partition_bounds[i+1]
            if start_idx < end_idx:
                t_start_min = t_start_arr[start_idx]
                t_hit_max = t_hit_arr[start_idx:end_idx].max()
                t_embargo = self._get_embargo_boundary(t_hit_max, reference_index)
            else:
                t_start_min = pd.NaT
                t_embargo = pd.NaT
            partition_starts.append(t_start_min)
            partition_embargoes.append(t_embargo)
            
        # Generate N choose K combinations
        partition_combinations = list(itertools.combinations(range(self.n_partitions), self.n_test_partitions))
        purging_offset_np = np.timedelta64(self.purging_offset)
        
        for test_part_idxs in partition_combinations:
            # Gather all test indices in sorted-order positions
            test_idx_list = []
            for part_idx in test_part_idxs:
                test_idx_list.extend(partitions[part_idx])
            # Coerce dtype to int64 to avoid IndexError on empty splits
            test_idx = np.array(sorted(test_idx_list), dtype=np.int64)
            
            # Initial train indices in sorted-order positions using fast set difference
            train_idx_arr = np.setdiff1d(np.arange(M), test_idx, assume_unique=True)
            
            # Apply purging/embargoing for each test partition
            for part_idx in test_part_idxs:
                if partition_bounds[part_idx] == partition_bounds[part_idx+1]:
                    continue
                
                t_start_min = partition_starts[part_idx]
                t_embargo = partition_embargoes[part_idx]
                
                if len(train_idx_arr) == 0:
                    continue
                    
                train_starts = t_start_arr[train_idx_arr]
                train_hits = t_hit_arr[train_idx_arr]
                
                # Condition 1: Train sample starts before test partition starts
                cond1 = train_starts < t_start_min
                keep_cond1 = ~cond1 | (train_hits + purging_offset_np < t_start_min)
                
                # Condition 2: Train sample starts at or after test partition starts
                keep_cond2 = cond1 | (train_starts > t_embargo)
                
                train_idx_arr = train_idx_arr[keep_cond1 & keep_cond2]
            
            # Map back to original indices in X
            yield original_idx_sorted[train_idx_arr], original_idx_sorted[test_idx]
```

---

## 5. Verification Method
1. **Test Execution**:
   - Run the project test suite using `pytest`.
   - Update adversarial tests in `validation_harness/tests/test_adversarial.py` to expect the corrected behaviors:
     - `test_empty_inputs`: Expect the call to successfully return empty/valid train/test splits without throwing `IndexError`.
     - `test_extreme_parameters`: Expect the call to succeed without throwing `IndexError`.
     - `test_fewer_samples_than_partitions`: Expect the call to succeed without throwing `IndexError`.
     - `test_non_chronological_index_alignment`: Change the assertion to verify that `train_idx` is NOT empty (it should contain index 1, i.e., Day 1's event, since it doesn't overlap when aligned correctly).
2. **Performance Benchmark**:
   - Run the large-scale CPCV split test in `test_e2e.py` (`test_large_scale_cpcv_split`) and assert that it takes `< 1` second (typically `< 0.2s` with precomputed boundaries and numpy set operations).
