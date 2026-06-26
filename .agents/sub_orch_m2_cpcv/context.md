# Context for CPCV Validation Harness

## Overview
We are building the validation harness for the ML Trading System. Combinatorial Purged Cross-Validation (CPCV) is essential to validate our primary and meta-label models without data leakage.

## Relevant Code Paths
- Codebase root: `c:\Users\swing\Desktop\TRADING\Thor\`
- Labeling modules:
  - `src/layers/l4_labeling/triple_barrier.py` (defines trade start index and `hit_time` as label end index)
  - `src/layers/l4_labeling/sample_weights.py` (defines sample uniqueness)
- Validation module to implement:
  - `validation_harness/cpcv.py`

## Reference Material
- Marcos López de Prado, *Advances in Financial Machine Learning*, Chapter 7 (Purged K-Fold Cross-Validation, Combinatorial Purged K-Fold Cross-Validation).
