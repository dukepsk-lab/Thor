import sys
import os
import pandas as pd
import numpy as np
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from validation_harness.cpcv import CombinatorialPurgedKFold, CPCVSplitter

def test_empty_inputs(cv_class):
    X = pd.DataFrame(index=pd.DatetimeIndex([]))
    pred_times = pd.Series(dtype='datetime64[ns]')
    cv = cv_class(n_partitions=5, n_test_partitions=2)
    splits = list(cv.split(X, pred_times=pred_times))
    assert len(splits) == 10
    for train_idx, test_idx in splits:
        assert len(train_idx) == 0
        assert len(test_idx) == 0

def test_extreme_parameters(cv_class):
    cv = cv_class(n_partitions=1, n_test_partitions=0)
    X = pd.DataFrame(index=pd.date_range("2023-01-01", periods=10))
    pred_times = pd.Series(X.index, index=X.index)
    splits = list(cv.split(X, pred_times=pred_times))
    assert len(splits) == 1
    train_idx, test_idx = splits[0]
    assert len(test_idx) == 0
    assert len(train_idx) == 10

def test_fewer_samples_than_partitions(cv_class):
    X = pd.DataFrame(index=pd.date_range("2023-01-01", periods=3))
    pred_times = pd.Series(X.index, index=X.index)
    cv = cv_class(n_partitions=5, n_test_partitions=2)
    splits = list(cv.split(X, pred_times=pred_times))
    assert len(splits) == 10

# Implement patched split function
def patched_split(self, X: pd.DataFrame, y=None, pred_times=None):
    if pred_times is None:
        raise ValueError("pred_times (event hit times) is required for CPCV purging and embargoing.")
        
    M = len(X)
    original_idx = np.arange(M)
    
    if not isinstance(X.index, pd.DatetimeIndex):
        X_index_dt = pd.to_datetime(X.index)
    else:
        X_index_dt = X.index
        
    if not X.index.equals(pred_times.index):
        if X.index.is_unique and pred_times.index.is_unique:
            pred_times_aligned = pred_times.reindex(X.index)
        else:
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
    t_hit = t_hit.fillna(t_start)
    
    sort_order = t_start.sort_values().index
    t_start_sorted = t_start.loc[sort_order].reset_index(drop=True)
    t_hit_sorted = t_hit.loc[sort_order].reset_index(drop=True)
    original_idx_sorted = original_idx[sort_order]
    
    if self.bar_times is not None:
        reference_index = self.bar_times
        if not isinstance(reference_index, pd.DatetimeIndex):
            reference_index = pd.to_datetime(reference_index)
        reference_index = reference_index.sort_values()
    else:
        reference_index = pd.Index(t_start_sorted)
        
    partition_bounds = np.linspace(0, M, self.n_partitions + 1, dtype=int)
    partitions = [list(range(partition_bounds[i], partition_bounds[i+1])) for i in range(self.n_partitions)]
    
    t_start_arr = t_start_sorted.values
    t_hit_arr = t_hit_sorted.values
    
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
        
    partition_combinations = list(itertools_combinations(self.n_partitions, self.n_test_partitions))
    purging_offset_np = self.purging_offset.to_timedelta64()
    
    for test_part_idxs in partition_combinations:
        test_idx_list = []
        for part_idx in test_part_idxs:
            test_idx_list.extend(partitions[part_idx])
        # FIX IS HERE: Specify dtype=int to avoid empty array becoming float64
        test_idx = np.array(sorted(test_idx_list), dtype=int)
        
        mask = np.ones(M, dtype=bool)
        mask[test_idx] = False
        train_idx_arr = np.where(mask)[0]
        
        for part_idx in test_part_idxs:
            if partition_bounds[part_idx] == partition_bounds[part_idx+1]:
                continue
            
            t_start_min = partition_starts[part_idx]
            t_embargo = partition_embargoes[part_idx]
            
            if len(train_idx_arr) == 0:
                continue
                
            train_starts = t_start_arr[train_idx_arr]
            train_hits = t_hit_arr[train_idx_arr]
            
            cond1 = train_starts < t_start_min
            keep_cond1 = ~cond1 | (train_hits + purging_offset_np < t_start_min)
            
            keep_cond2 = cond1 | (train_starts > t_embargo)
            
            train_idx_arr = train_idx_arr[keep_cond1 & keep_cond2]
        
        yield original_idx_sorted[train_idx_arr], original_idx_sorted[test_idx]

def itertools_combinations(n, k):
    import itertools
    return list(itertools.combinations(range(n), k))

class PatchedCombinatorialPurgedKFold(CombinatorialPurgedKFold):
    def split(self, X, y=None, pred_times=None):
        return patched_split(self, X, y, pred_times)

if __name__ == "__main__":
    print("=== TESTING ORIGINAL IMPLEMENTATION ===")
    for test_fn in [test_empty_inputs, test_extreme_parameters, test_fewer_samples_than_partitions]:
        try:
            test_fn(CombinatorialPurgedKFold)
            print(f"{test_fn.__name__}: PASSED")
        except Exception as e:
            print(f"{test_fn.__name__}: FAILED with {type(e).__name__}: {e}")

    print("\n=== TESTING PATCHED IMPLEMENTATION ===")
    for test_fn in [test_empty_inputs, test_extreme_parameters, test_fewer_samples_than_partitions]:
        try:
            test_fn(PatchedCombinatorialPurgedKFold)
            print(f"{test_fn.__name__}: PASSED")
        except Exception as e:
            print(f"{test_fn.__name__}: FAILED with {type(e).__name__}: {e}")
