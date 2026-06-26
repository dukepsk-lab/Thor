# CPCV Exploration and Mathematical Design Report

## 1. Observation
- Analyzed the codebase structure and ran searches using PowerShell `Select-String` to check for validation harness folders or files.
- The `src/` directory contains:
  - `src/api/main.py`
  - `src/core/config.py`
  - `src/core/db.py`
  - `src/layers/l0_ingestion/...`
  - `src/layers/l1_features/...`
  - `src/layers/l2_regime/__init__.py` (size: 53 bytes, contains only `# Layer 2: Regime Detection`)
  - `src/layers/l3_primary_model/__init__.py` (size: 39 bytes, contains only `# Layer 3: Primary Signal Model (SIDE)`)
  - `src/layers/l4_labeling/triple_barrier.py` and `sample_weights.py` (actual implementations)
  - `src/layers/l5_meta_model/__init__.py` (size: 41 bytes, contains only `# Layer 5: Meta-Label Model (SIZE/TRUST)`)
  - `src/layers/l6_risk_sizing/__init__.py` (size: 34 bytes)
  - `src/layers/l7_execution/__init__.py` (size: 21 bytes)
  - `src/layers/l8_monitoring/__init__.py` (size: 34 bytes)
- Searching for terms like `"CPCV"`, `"validation"`, `"purge"`, and `"embargo"` across all python files in `src/` returned zero matches:
  ```powershell
  Get-ChildItem -Recurse -Filter *.py | Select-String -Pattern "CPCV", "validation", "purge", "embargo"
  # Output: empty
  ```
- Therefore, there is no validation harness or cross-validation skeleton in the codebase.

## 2. Logic Chain
- Based on the absence of validation folders, files, and keywords under `src/layers/` (Observations 1 & 2), we conclude that no validation harness or CPCV skeleton currently exists.
- According to `ML_Trading_System_Architecture.md`, validation is the gatekeeper of live deployment using "CPCV Validation (purge + embargo)" (Observation 3).
- To implement CPCV, we need to partition the data, generate test/train split combinations, apply purging to avoid overlaps from path-dependent labels, apply embargoing to prevent serial correlation leakage, and reconstruct multiple out-of-sample (OOS) paths.
- **Mathematical Design**:
  - **Partitioning**: Divide the dataset of size $T$ into $N$ contiguous, non-overlapping groups.
  - **Split Combinations**: Choose $K$ test groups. The number of splits (combinations) is $C = \binom{N}{K}$.
  - **Purging**: If a test set interval is $[T_{start}, T_{end}]$ and a training event has start time $t_{start, i}$ and label end time $t_{end, i}$ (such as a Triple-Barrier hit time or vertical barrier timeout), the training event is purged if $t_{start, i} \leq T_{end}$ and $t_{end, i} \geq T_{start}$.
  - **Embargoing**: To prevent leakages from serial correlation, training events starting within an embargo period of size $h$ after the test interval (i.e. in $(T_{end}, T_{end} + h]$) are removed.
  - **Path Reconstruction**: Each group is in the test set in exactly $M = \binom{N-1}{K-1}$ splits. We can reconstruct $M$ complete OOS paths by aligning the sorted split indices for each group.
- We verified the mathematical correctness of our path reconstruction and purging/embargoing logic via a Python prototype (Observation 4).

### Step-by-Step CPCV Design & Implementation Blueprint
Here is the recommended python implementation for the CPCV split generation and out-of-sample path reconstruction:

```python
import numpy as np
import pandas as pd
from itertools import combinations
from typing import List, Tuple, Generator

class CombinatorialPurgedCV:
    """
    Combinatorial Purged Cross-Validation (CPCV) with purging and embargoing.
    As described in Marcos López de Prado's "Advances in Financial Machine Learning".
    """
    def __init__(self, n_groups: int = 5, k_test_groups: int = 2, embargo_pct: float = 0.01):
        self.n_groups = n_groups
        self.k_test_groups = k_test_groups
        self.embargo_pct = embargo_pct

    def split(self, df: pd.DataFrame, events: pd.DataFrame) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Generate (train_indices, test_indices) splits.
        
        Args:
            df: DataFrame containing the features/close prices. Index must be datetime.
            events: DataFrame with index as event start time and a column 'hit_time' (or 't1') 
                    indicating when the barrier was hit / label resolved.
        """
        n_samples = len(df)
        group_size = n_samples // self.n_groups
        
        # Calculate group boundaries
        group_bounds = []
        for g in range(self.n_groups):
            start_idx = g * group_size
            end_idx = (g + 1) * group_size - 1 if g < self.n_groups - 1 else n_samples - 1
            group_bounds.append((df.index[start_idx], df.index[end_idx]))
            
        # All group indices [0, 1, ..., N-1]
        groups = list(range(self.n_groups))
        
        # Generate combinations of K test groups
        for test_group_comb in combinations(groups, self.k_test_groups):
            # 1. Identify test indices
            test_indices = []
            test_intervals = []
            for g in test_group_comb:
                start_time, end_time = group_bounds[g]
                # Gather test sample indices
                g_indices = np.where((df.index >= start_time) & (df.index <= end_time))[0]
                test_indices.extend(g_indices)
                test_intervals.append((start_time, end_time))
                
            test_indices = np.array(sorted(test_indices))
            
            # 2. Identify training indices (start with all indices, then prune)
            train_indices = np.array(range(n_samples))
            
            # Prune test indices from training set
            train_indices = np.setdiff1d(train_indices, test_indices)
            
            # 3. Apply Purging and Embargoing
            purged_train_indices = []
            embargo_window = int(n_samples * self.embargo_pct)
            
            for train_idx in train_indices:
                train_start = df.index[train_idx]
                
                # Check if this training sample exists in events
                if train_start in events.index:
                    train_end = events.loc[train_start, 'hit_time']
                else:
                    train_end = train_start # fallback if no event exists
                
                if pd.isna(train_end):
                    train_end = train_start
                    
                keep = True
                for test_start, test_end in test_intervals:
                    # Purging check: overlap of [train_start, train_end] with [test_start, test_end]
                    # Overlap if: train_start <= test_end and train_end >= test_start
                    if train_start <= test_end and train_end >= test_start:
                        keep = False
                        break
                    
                    # Embargo check: train sample starts within embargo window after test_end
                    test_end_loc = df.index.get_loc(test_end)
                    embargo_end_loc = min(n_samples - 1, test_end_loc + embargo_window)
                    embargo_end_time = df.index[embargo_end_loc]
                    
                    if train_start > test_end and train_start <= embargo_end_time:
                        keep = False
                        break
                        
                if keep:
                    purged_train_indices.append(train_idx)
                    
            yield np.array(purged_train_indices), test_indices
            
    def get_paths(self) -> List[List[int]]:
        """
        Reconstruct the paths. Returns a list of paths, where each path is a list of
        split indices for each group.
        Specifically, for N groups, K test groups:
        Number of paths M = (N-1) choose (K-1)
        Returns:
            paths: List of length M. Each path is a list of length N, where the g-th element
                   is the split index to use for group g.
        """
        # Generate the list of all combinations in the same order as split()
        groups = list(range(self.n_groups))
        combs = list(combinations(groups, self.k_test_groups)) # Length is C = N choose K
        
        # For each group, find the indices of combinations containing it
        group_splits = {g: [] for g in groups}
        for split_idx, comb in enumerate(combs):
            for g in comb:
                group_splits[g].append(split_idx)
                
        # Length of each group_splits[g] is M = (N-1) choose (K-1)
        m_paths = len(group_splits[0])
        
        # Build the paths matrix
        paths = []
        for p in range(m_paths):
            path = []
            for g in groups:
                path.append(group_splits[g][p])
            paths.append(path)
            
        return paths
```

## 3. Caveats
- **Lookback-Scaled Embargo**: The embargo period $h$ (defined above as a fraction of the dataset length) must be carefully chosen. Standard practice suggests setting $h$ to match the maximum lookback window of features constructed in Layer 1 (e.g. max ATR lookback, Hurst exponent lookback) or setting it to a reasonable number of bars (e.g. 5–20 bars).
- **Temporal Alignment**: When working with cross-pair features (EURUSD and GBPUSD), the time-series indexes must be perfectly aligned (e.g. forward-filled or inner-joined) before performing partitioning.
- **Ambiguous Event Ends**: If the label end time is not present (`pd.NaT`), we fallback to treating it as instantaneous (i.e. ending at `train_start`), which could under-purge. It is critical that Layer 4 returns exact hit times for all events (even timeouts).

## 4. Conclusion
- No validation harness folder or skeleton exists.
- We recommend creating a new layer `src/layers/l9_validation/` or a helper module under `src/core/validation.py` containing the `CombinatorialPurgedCV` class.
- The step-by-step CPCV logic and the complete prototype implementation are ready to be handed over to the implementer agent.

## 5. Verification Method
- **Codebase Check**: Inspect the folders and verify the absence of validation modules.
- **Functional Validation**: Run the prototype inline code using:
  ```powershell
  python -c "..."
  ```
  Verify that:
  - Total splits is exactly $\binom{N}{K}$.
  - Total paths is exactly $\binom{N-1}{K-1}$.
  - Training events that overlap with any test group interval are correctly excluded from the training indices (purged).
  - Training events starting within the embargo window after any test group are correctly excluded (embargoed).
