# BRIEFING — 2026-06-19T05:16:15Z

## Mission
Research the embargo logic requirements for CPCV on financial time-series. Recommend how the embargo period should be applied to training samples starting after a test fold (supporting both percentage-based, absolute bar-count, or timedelta-based embargo window). Propose the exact python API class interface for CombinatorialPurgedKFold (making it compatible with scikit-learn's cross-validation splitter interface where possible, e.g. having split() method).

## 🔒 My Identity
- Archetype: Explorer
- Roles: CPCV Explorer 3 (Embargo & API design)
- Working directory: c:\Users\swing\Desktop\TRADING\Thor\.agents\explorer_cpcv_3
- Original parent: 330d948a-1762-46ad-98d9-76d4c9adf839
- Milestone: CPCV Embargo & API Design

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Network mode: CODE_ONLY (no external web search or HTTP client)

## Current Parent
- Conversation ID: 330d948a-1762-46ad-98d9-76d4c9adf839
- Updated: 2026-06-19T05:16:15Z

## Investigation State
- **Explored paths**:
  - `validation_harness/PROJECT.md`
  - `src/layers/l4_labeling/triple_barrier.py`
  - `src/layers/l4_labeling/sample_weights.py`
- **Key findings**:
  - Formulated how the embargo window should be applied to training samples starting after a test fold (using the $T_{embargo}$ check after the maximum test hit time).
  - Designed absolute bar-count and percentage-based embargo methods that reference a sorted timeline (e.g. `bar_times`), falling back to `event_times` if not available.
  - Proposed a scikit-learn compatible `CombinatorialPurgedKFold` CV splitter.
- **Unexplored areas**: None, the investigation is complete.

## Key Decisions Made
- Supported all three requested embargo modes (percentage, count, timedelta) using a unified `_get_embargo_boundary` method.
- Subsumed future purging and embargoing into a single check ($t_{i,0} \le T_{embargo}$) for training samples starting after the test fold starts.

## Artifact Index
- c:\Users\swing\Desktop\TRADING\Thor\.agents\explorer_cpcv_3\handoff.md — Analysis and design report
- c:\Users\swing\Desktop\TRADING\Thor\.agents\explorer_cpcv_3\cpcv_prototype.py — Prototype implementation and verification script
