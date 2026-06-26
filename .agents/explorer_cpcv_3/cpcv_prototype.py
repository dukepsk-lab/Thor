import pandas as pd
import numpy as np
import itertools
from typing import Generator, Tuple, List, Union, Optional, Dict

class CombinatorialPurgedKFold:
    """
    Combinatorial Purged Cross-Validation (CPCV) Splitter.
    Supports purging of overlapping train/test samples and embargoing of
    training samples that start immediately after a test fold.
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
        if n_test_partitions >= n_partitions:
            raise ValueError("n_test_partitions must be less than n_partitions")
        self.n_partitions = n_partitions
        self.n_test_partitions = n_test_partitions
        self.purging_offset = purging_offset
        self.embargo_offset = embargo_offset
        self.bar_times = bar_times

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        """Return the number of splitting iterations."""
        import math
        return math.comb(self.n_partitions, self.n_test_partitions)

    def _get_embargo_boundary(
        self, 
        t_hit_max: pd.Timestamp, 
        reference_index: pd.Index
    ) -> pd.Timestamp:
        """
        Calculate the embargo boundary timestamp.
        Supports percentage-based, absolute bar-count, or timedelta-based embargo window.
        """
        if isinstance(self.embargo_offset, pd.Timedelta):
            return t_hit_max + self.embargo_offset
        
        elif isinstance(self.embargo_offset, (int, np.integer)):
            if self.embargo_offset == 0:
                return t_hit_max
            # Find the position of t_hit_max in the reference index
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
            X: Features DataFrame. Index must be datetime-like (event start times).
            y: Target Series (optional).
            pred_times: Event end/hit times Series (required for purging/embargoing).
                        Index must match X.index.
                        
        Yields:
            train_idx: Training set indices.
            test_idx: Test set indices.
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
            
        # Divide sample indices into N partitions
        partition_bounds = np.linspace(0, M, self.n_partitions + 1, dtype=int)
        partitions = [list(range(partition_bounds[i], partition_bounds[i+1])) for i in range(self.n_partitions)]
        
        # Generate all combinations of K test partitions
        partition_combinations = list(itertools.combinations(range(self.n_partitions), self.n_test_partitions))
        
        for test_part_idxs in partition_combinations:
            # Test indices are the union of the chosen partitions
            test_idx_list = []
            for part_idx in test_part_idxs:
                test_idx_list.extend(partitions[part_idx])
            test_idx = np.array(sorted(test_idx_list))
            
            # Initial train indices
            train_idx_list = [i for i in range(M) if i not in test_idx]
            
            # Apply purging and embargoing relative to each test partition
            for part_idx in test_part_idxs:
                part_indices = partitions[part_idx]
                if len(part_indices) == 0:
                    continue
                
                # Get time boundaries for the current test partition
                t_start_min = t_start.iloc[part_indices].min()
                t_start_max = t_start.iloc[part_indices].max()
                t_hit_max = t_hit.iloc[part_indices].max()
                
                # Calculate embargo boundary for this partition
                t_embargo = self._get_embargo_boundary(t_hit_max, reference_index)
                
                # Filter train indices
                purged_train_idx = []
                for idx in train_idx_list:
                    ti_start = t_start.iloc[idx]
                    ti_hit = t_hit.iloc[idx]
                    
                    # Case 1: Train sample starts before test partition
                    if ti_start < t_start_min:
                        # Purge if it overlaps with the test partition start
                        if ti_hit >= t_start_min:
                            continue
                    
                    # Case 2: Train sample starts at or after test partition start
                    else:
                        # Purge and embargo if it starts before embargo boundary
                        if ti_start <= t_embargo:
                            continue
                            
                    purged_train_idx.append(idx)
                
                train_idx_list = purged_train_idx
                
            yield np.array(train_idx_list), test_idx

if __name__ == "__main__":
    print("Testing CombinatorialPurgedKFold prototype...")
    # Create mock time series: 100 hourly bars
    bar_times = pd.date_range(start="2026-06-19 00:00:00", periods=100, freq="h")
    
    # Create 10 events
    # Each event starts at bar_times[i*10] and runs for 15 hours (overlapping)
    event_start_times = bar_times[::10][:10]
    event_hit_times = event_start_times + pd.Timedelta(hours=15)
    
    X = pd.DataFrame(np.random.randn(10, 4), index=event_start_times)
    pred_times = pd.Series(event_hit_times, index=event_start_times)
    
    print("\nEvent times:")
    for i in range(10):
        print(f"Sample {i}: Start {event_start_times[i]}, Hit {event_hit_times[i]}")
        
    print("\n--- Split with 3 partitions, 1 test partition, 0 embargo ---")
    cv = CombinatorialPurgedKFold(n_partitions=3, n_test_partitions=1, embargo_offset=0, bar_times=bar_times)
    for i, (train, test) in enumerate(cv.split(X, pred_times=pred_times)):
        print(f"Split {i}: Train={train}, Test={test}")
        
    print("\n--- Split with 3 partitions, 1 test partition, 12 hours embargo ---")
    cv_emb = CombinatorialPurgedKFold(n_partitions=3, n_test_partitions=1, embargo_offset=pd.Timedelta(hours=12), bar_times=bar_times)
    for i, (train, test) in enumerate(cv_emb.split(X, pred_times=pred_times)):
        print(f"Split {i}: Train={train}, Test={test}")
        
    print("\n--- Split with 3 partitions, 1 test partition, 5 bars embargo ---")
    cv_bars = CombinatorialPurgedKFold(n_partitions=3, n_test_partitions=1, embargo_offset=5, bar_times=bar_times)
    for i, (train, test) in enumerate(cv_bars.split(X, pred_times=pred_times)):
        print(f"Split {i}: Train={train}, Test={test}")

    print("\n--- Split with 3 partitions, 1 test partition, 10% (10 bars) embargo ---")
    cv_pct = CombinatorialPurgedKFold(n_partitions=3, n_test_partitions=1, embargo_offset=0.10, bar_times=bar_times)
    for i, (train, test) in enumerate(cv_pct.split(X, pred_times=pred_times)):
        print(f"Split {i}: Train={train}, Test={test}")
