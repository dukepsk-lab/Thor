# Handoff Report — Reviewer 2 (CPCV Review)

## 1. Observation

- **Implementation File**: `validation_harness/cpcv.py`
  - Defines `CombinatorialPurgedKFold` (lines 7-173) with constructor parameters: `n_partitions`, `n_test_partitions`, `purging_offset`, `embargo_offset`, `bar_times`.
  - Defines `split` method as a generator yielding `(train_idx, test_idx)` as numpy arrays (lines 72-173).
- **Test Files**: `validation_harness/tests/test_cpcv.py` (lines 4, 12, 20, etc.) and `validation_harness/tests/test_e2e.py` (lines 8, 49, 61, 77, 91, 128)
  - Attempt to import `CPCVSplitter` from `validation_harness.cpcv`.
  - Instantiate `CPCVSplitter` with parameters: `n_splits`, `n_test_splits`, `embargo_pct`.
  - Expect `split` method to return a list of dictionaries with keys `'train'` and `'test'`.
- **Test Configuration File**: `validation_harness/tests/conftest.py`
  - Employs a dynamic import injection hook (lines 273-283) that intercepts imports of `validation_harness.cpcv` and monkeypatches it, injecting a dummy class named `CPCVSplitter` (defined as a stub in lines 125-181).
- **Test Failures**:
  - Running pytest on `test_e2e.py` results in `test_large_scale_cpcv_split` failing due to execution time:
    ```
    FAILED validation_harness/tests/test_e2e.py::test_large_scale_cpcv_split - assert 2.8804187774658203 < 1.0
    ```
  - Running pytest on `test_ingestion.py` in environments with strict/new SQLAlchemy versions raises:
    ```
    sqlalchemy.exc.ObjectNotExecutableError: Not an executable object
    ```
    during the execution of raw string SQL statements in the `db_engine` fixture in `conftest.py` (line 381).
- **Adversarial Test File**: `validation_harness/tests/test_adversarial.py`
  - Specifically imports `CombinatorialPurgedKFold` and tests it directly against empty inputs and extreme parameters (lines 6-39), confirming it raises raw `IndexError` exceptions.
- **Deflated Sharpe Ratio (DSR) Capping**: `validation_harness/metrics.py` (lines 95-96)
  - Clamps `m_term` and `m_e_term` at `0.9999`, which artificially caps the expected maximum Sharpe ratio (`e_max`) and deflates the multi-testing penalty for high trial numbers.

---

## 2. Logic Chain

1. **Facade Implementation & Bypass (INTEGRITY VIOLATION)**:
   - The production code defines `CombinatorialPurgedKFold`.
   - The tests look for `CPCVSplitter` (with completely different parameter names and return structures).
   - Rather than fixing the code or the tests to align, `conftest.py` dynamically injects a dummy/stub implementation `CPCVSplitter` directly into the module dictionary.
   - Consequently, the main test suite runs against this mock stub instead of the actual `CombinatorialPurgedKFold` production code.
   - This constitutes a **facade implementation** that bypasses actual verification of the production code.
2. **Performance Bottleneck**:
   - The stub `CPCVSplitter._purge_and_embargo` loops over elements in Python list structures.
   - For 3,000 samples and 45 split combinations, it executes over 216k loops in pure Python.
   - This takes ~2.8 seconds, consistently failing the `< 1.0s` assertion in `test_large_scale_cpcv_split`.
3. **DSR Deflation Flaw**:
   - The math for DSR calls for computing the expected maximum of `M` (trials) independent standard normal variables.
   - As $M \to \infty$, $e\_max \to \infty$.
   - The code clamps the inputs to `stats.norm.ppf` at `0.9999`, preventing `e_max` from scaling correctly for $M \ge 10,000$. This results in deflated Sharpe ratios that are under-penalized (overoptimistic DSR values).
4. **SQLAlchemy 2.0 Incompatibility**:
   - In SQLAlchemy 2.x, raw string statements are not executable directly via `conn.execute("CREATE TABLE ...")`. They must be wrapped in `text("...")`.
   - This causes database fixture setup to crash in strict SQLAlchemy 2.x environments.

---

## 3. Caveats

- We did not modify the production code or tests because we operate under the "review-only" constraint.
- The behavior of `CombinatorialPurgedKFold` was only partially evaluated in `test_adversarial.py` (showing it fails on empty inputs). The full cross-validation correctness of the production class remains unverified by the standard test suite due to the stub override.

---

## 4. Conclusion & Verdict

**Verdict**: **REQUEST_CHANGES**
**Critical Finding**: **INTEGRITY VIOLATION**

The test harness uses a facade/bypass mechanism in `conftest.py` to substitute a mock stub for the actual CPCV class under test. The production `CombinatorialPurgedKFold` is left completely untested by the main test suite. In addition, there are class name mismatches, parameter mismatches, performance bottlenecks in the stub, unhandled boundary conditions in the production code, and a statistical deflation bug in the DSR calculation.

---

## 5. Verification Method

To verify these findings:
1. Run pytest directly on the workspace:
   `python -m pytest`
2. Inspect the dynamic injection block in `validation_harness/tests/conftest.py` starting at line 273.
3. Compare the class name, constructor arguments, and output types of `CombinatorialPurgedKFold` in `validation_harness/cpcv.py` against those of `CPCVSplitter` in `conftest.py` (line 125).

---

# QUALITY & ADVERSARIAL REVIEW REPORTS

## Review Summary

**Verdict**: REQUEST_CHANGES

### Critical Finding 1: Facade Bypass (INTEGRITY VIOLATION)
- **What**: The test suite runs against a dummy stub injected in `conftest.py` instead of the production CPCV code.
- **Where**: `validation_harness/tests/conftest.py` lines 125-181 and 273-283.
- **Why**: Bypasses verification of the actual production implementation.
- **Suggestion**: Standardize the class names and interface between `cpcv.py` and the tests. Test the production `CombinatorialPurgedKFold` directly and remove the dynamic injection hook.

### Major Finding 2: Class and Interface Mismatch
- **What**: Discrepancy between production class name (`CombinatorialPurgedKFold`) and test expected class name (`CPCVSplitter`), as well as constructor parameters and return structures.
- **Where**: `validation_harness/cpcv.py` vs `validation_harness/tests/test_cpcv.py` and `test_e2e.py`.
- **Why**: Code cannot be used interchangeably; integration will fail.
- **Suggestion**: Align the signatures and structure of the split outputs.

### Major Finding 3: Performance Failure in Stub
- **What**: `test_large_scale_cpcv_split` fails because the split calculation is slow.
- **Where**: `validation_harness/tests/test_e2e.py:135`.
- **Why**: Takes ~2.8s, exceeding the 1.0s limit.
- **Suggestion**: Optimize the splitting logic using vectorized pandas/numpy operations.

### Minor Finding 4: SQLAlchemy 2.0 Execute Failure
- **What**: SQLite db fixture throws ObjectNotExecutableError in SQLAlchemy 2.x environments.
- **Where**: `validation_harness/tests/conftest.py:381`.
- **Why**: Raw strings are no longer accepted.
- **Suggestion**: Wrap the SQL creation strings in `sqlalchemy.text()`.

---

## Verified Claims

- CPCV implementation correctly verified by main tests? → **FAIL** (verified stub instead).
- DSR with high trials deflates probability? → **FAIL** (capping prevents correct penalty, returning 0.13 instead of < 0.1).
- Tick DB sync and OHLCV DB sync work correctly? → **PASS** (once SQLAlchemy version differences are bypassed).

---

## Challenge Summary

**Overall risk assessment**: CRITICAL

### Critical Challenge 1: Dummy Implementation Verification
- **Assumption challenged**: Tests are verifying production logic.
- **Attack scenario**: Production class could be completely broken or unimplemented, yet the test suite passes because it executes the stub.
- **Blast radius**: Undetected runtime bugs in validation/backtesting logic.
- **Mitigation**: Disallow stub injection in tests.

### Medium Challenge 2: DSR Overoptimism under Multi-Testing
- **Assumption challenged**: DSR correctly penalizes arbitrary trial sizes.
- **Attack scenario**: Selecting the best strategy from 100,000 runs returns a low penalty because PPF capping prevents the maximum expected Sharpe from scaling.
- **Blast radius**: Deployment of non-viable models due to inflated statistical significance.
- **Mitigation**: Remove or adjust the `0.9999` clamp to scale with `num_trials`.
