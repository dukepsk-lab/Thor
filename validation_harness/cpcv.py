import numpy as np
import pandas as pd
import itertools
import math
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
            train_idx: Numpy array of training indices (original positions in X).
            test_idx: Numpy array of test indices (original positions in X).
        """
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
        purging_offset_np = self.purging_offset.to_timedelta64()
        
        for test_part_idxs in partition_combinations:
            # Gather all test indices in sorted-order positions
            test_idx_list = []
            for part_idx in test_part_idxs:
                test_idx_list.extend(partitions[part_idx])
            test_idx = np.array(sorted(test_idx_list), dtype=np.int64)
            
            mask = np.ones(M, dtype=bool)
            mask[test_idx] = False
            train_idx_arr = np.where(mask)[0]
            
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
    if pd.api.types.is_datetime64_any_dtype(event_times):
        start_index = pd.DatetimeIndex(event_times.values)
    else:
        start_index = pd.DatetimeIndex(event_times.index)
        
    X = pd.DataFrame(index=start_index)
    
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
    if valid_events.empty or len(close_index) == 0:
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
    
    result = pd.Series(np.nan, index=events.index, dtype=float)
    result.iloc[np.where(events['hit_time'].notna())[0]] = avg_uniq
    return result


class CPCVSplitter:
    def __init__(self, n_splits: int = 6, n_test_splits: int = 2, embargo_pct: float = 0.0):
        if n_splits <= 0:
            raise ValueError("n_splits must be positive")
        if n_test_splits >= n_splits:
            raise ValueError("n_test_splits must be less than n_splits")
        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.embargo_pct = embargo_pct

    def split(self, X: pd.DataFrame, event_times: Optional[pd.Series] = None) -> List[Dict[str, np.ndarray]]:
        if len(X) < self.n_splits:
            raise ValueError(f"Dataset size {len(X)} is less than N ({self.n_splits})")
            
        cv = CombinatorialPurgedKFold(
            n_partitions=self.n_splits,
            n_test_partitions=self.n_test_splits,
            embargo_offset=self.embargo_pct,
            purging_offset=pd.Timedelta(hours=0)
        )
        
        if event_times is None:
            pred_times = pd.Series(X.index, index=X.index)
        else:
            pred_times = event_times
            
        splits = []
        for train_idx, test_idx in cv.split(X, pred_times=pred_times):
            splits.append({
                'train': train_idx,
                'test': test_idx
            })
        return splits

