# Validation Harness Orchestration Plan

## Overview
This plan outlines the design, implementation, and verification of a production-grade validation harness for the ML Trading System (Thor). The system comprises three main requirements:
1. Dynamic MT5 historical data ingestion (OHLCV + ticks).
2. Combinatorial Purged Cross-Validation (CPCV) with purging and embargo techniques to avoid data leakage.
3. Cost-Adjusted Baseline Reporting (Sharpe, Sortino, etc. adjusted for spread and commission, compared to Buy-and-Hold and random baselines).

## Architecture & File Layout
The validation harness code will reside in `c:\Users\swing\Desktop\TRADING\Thor\validation_harness\`.
- `validation_harness/`:
  - `__init__.py`: Package entry point.
  - `ingestion.py`: MT5 data ingestion client and schema validator.
  - `cpcv.py`: Purged and embargoed CPCV split generator.
  - `metrics.py`: Cost-adjusted metric calculations and baseline comparators.
  - `runner.py`: Orchestration pipeline execution.
- `validation_harness/tests/`:
  - `__init__.py`
  - `test_ingestion.py`: Test suite for MT5 ingestion.
  - `test_cpcv.py`: Test suite for CPCV purging and embargoing.
  - `test_metrics.py`: Test suite for cost-adjusted metrics.
  - `test_e2e.py`: E2E integration tests validating the whole pipeline.

## Tracks
Following the Project Pattern, we decompose the project into two tracks:
1. **E2E Testing Track**: Designs and implements E2E testing framework, publishing `TEST_READY.md`.
2. **Implementation Track**: Implements features and verifies them against the E2E tests, finishing with adversarial coverage hardening.

## Milestones & Status
| # | Milestone Name | Scope | Dependencies | Status |
|---|----------------|-------|--------------|--------|
| T0 | E2E Testing Suite | Create E2E test framework, test cases, and publish `TEST_READY.md`. | None | PLANNED |
| M1 | Data Ingestion | Implement `ingestion.py` for MT5 fetching and validation. | None | PLANNED |
| M2 | CPCV | Implement `cpcv.py` for CPCV splitting, purging, and embargo. | None | PLANNED |
| M3 | Cost-Adjusted Metrics | Implement `metrics.py` for cost adjustments and baselines. | M1, M2 | PLANNED |
| M4 | E2E Integration & Verification | E2E integration test pass and Tier 5 adversarial hardening. | T0, M1, M2, M3 | PLANNED |

## Detailed Subagent Spawning Plan
- **E2E Testing Orchestrator** (Conv ID: TBD): Inherits `self` archetype, runs the test track.
- **Milestone 1 Sub-Orchestrator** (Conv ID: TBD): Runs the data ingestion track.
- **Milestone 2 Sub-Orchestrator** (Conv ID: TBD): Runs the CPCV track.
- **Milestone 3 Sub-Orchestrator** (Conv ID: TBD): Runs the metrics track.
- **Milestone 4 Sub-Orchestrator** (Conv ID: TBD): Runs the final E2E verification and adversarial hardening.
