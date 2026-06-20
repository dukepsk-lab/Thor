# Plan: Milestone 1 Ingestion Execution Plan

## Work Breakdown Structure

### Phase 1: Analysis & Interface Design
- **Task 1.1**: Analyze MT5 connection initialization, parameter mapping, and potential error codes.
- **Task 1.2**: Define exact schema structures for:
  - OHLCV: `time` (timestamp index), `symbol` (str), `timeframe` (str), `open` (float), `high` (float), `low` (float), `close` (float), `tick_volume` (int/float), `spread` (int/float), `real_volume` (int/float).
  - Ticks: `time` (timestamp index), `symbol` (str), `bid` (float), `ask` (float), `last` (float), `volume` (float/int), `flags` (int), `spread` (float, derived as `ask - bid`).
- **Task 1.3**: Design the reconnection protocol (backoff retry, max retries, error handling).

### Phase 2: Implementation (via Worker)
- **Task 2.1**: Implement `validation_harness/ingestion.py` matching interface contracts.
- **Task 2.2**: Implement schema verification logic that checks data types, column presence, and alerts/logs on anomalies.
- **Task 2.3**: Update `src/layers/l0_ingestion/db_sync.py` and `mt5_client.py` if they require bug fixes or improvement (e.g. table initialization).
- **Task 2.4**: Implement programmatic test script `validation_harness/test_ingestion_prog.py` to verify the ingestion code in isolation.

### Phase 3: Review & Challenge (via Reviewers and Challenger)
- **Task 3.1**: Reviewers verify code quality, security/integrity, design compliance, and edge case handling.
- **Task 3.2**: Challenger runs programmatic tests, verifies both mock and real environments, and validates the schemas.

### Phase 4: Forensic Audit (via Auditor)
- **Task 4.1**: Forensic Auditor performs static and dynamic integrity validation to ensure no fake code, hardcoding, or bypasses are present.
- **Task 4.2**: Verify clean audit output.
