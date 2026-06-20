# Plan for Milestone 2 CPCV Implementation

## Overview
We will implement and validate the Combinatorial Purged Cross-Validation (CPCV) splitting, purging, and embargo logic in `validation_harness/cpcv.py`.

## Phase 1: Investigation & Design
- Spawn 3 Explorers to inspect the codebase, understand the data structures used for H4 bar data, label formats, and details of CPCV math and implementation.
- Retrieve Explorer recommendation for the exact CPCV class interface and purging/embargo algorithms.

## Phase 2: Implementation
- Spawn 1 Worker to:
  - Create the `validation_harness` package directory if missing.
  - Create `validation_harness/__init__.py`.
  - Implement `CombinatorialPurgedKFold` in `validation_harness/cpcv.py`.
  - Write unit/integration tests to verify splitting, purging, and embargoing logic under various scenarios (different $N$, $K$, embargo periods, labels with/without overlap).

## Phase 3: Review & Challenge
- Spawn 2 Reviewers to inspect the implementation for correctness, readability, robustness, and compliance with the specification.
- Spawn 2 Challengers to write adversarial tests (edge cases, extreme parameters, zero overlap, full overlap, negative test cases) and verify performance.

## Phase 4: Forensic Audit
- Spawn 1 Forensic Auditor to check for integrity violations (such as hardcoded test results, facade implementations, logic circumventions, or data leakage).

## Phase 5: Synthesis & Reporting
- Synthesize all subagent reports and submit a final handoff to the parent orchestrator.
