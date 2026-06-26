import pandas as pd
import numpy as np
from typing import Generator, Tuple

class PurgedKFold:
    """
    Implements a Purged K-Fold Cross Validation tailored for overlapping time-series labels.
    
    Args:
        n_splits: Number of folds.
        embargo_pct: Percentage of total bars to embargo after the test set to prevent leakage.
    """
    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01):
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(self, X: pd.DataFrame, events: pd.DataFrame) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Generates train/test indices while applying purging and embargoing.
        
        Args:
            X: The feature dataframe. Index must be time.
            events: DataFrame containing 't1' (the end time of the label) for each index in X.
                    Index must match X's index.
        """
        t1 = events['t1']
        indices = np.arange(X.shape[0])
        test_starts = [(i[0], i[-1] + 1) for i in np.array_split(np.arange(X.shape[0]), self.n_splits)]
        
        embargo_size = int(X.shape[0] * self.embargo_pct)
        
        for i, j in test_starts:
            # test index
            test_indices = indices[i:j]
            test_start_time = X.index[i]
            test_end_time = t1.iloc[j-1] if j-1 < len(t1) and pd.notna(t1.iloc[j-1]) else X.index[j-1]
            
            train_indices = []
            
            # Pre-test training split (with purging)
            for k in range(i):
                train_end_time = t1.iloc[k] if pd.notna(t1.iloc[k]) else X.index[k]
                # Purging: train label must complete before test starts
                if train_end_time <= test_start_time:
                    train_indices.append(k)
                    
            # Post-test training split (with embargo)
            embargo_end_idx = j + embargo_size
            for k in range(embargo_end_idx, len(indices)):
                train_start_time = X.index[k]
                # Embargo: train start time must be after test end time + embargo
                if train_start_time > test_end_time:
                    train_indices.append(k)
                    
            yield np.array(train_indices), test_indices
