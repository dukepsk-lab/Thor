# CPCV Implementation Review Handoff Report

## 1. Observation

Direct observations made on files and outputs during the review:

- **Production File (`validation_harness/cpcv.py`)**:
  - Implements `CombinatorialPurgedKFold` (line 7), `get_cpcv_splits` (line 175), and `calculate_sample_uniqueness_exact` (line 211).
  - Does **NOT** define a class named `CPCVSplitter`.
- **Test File (`validation_harness/tests/test_cpcv.py`)**:
  - Imports and instantiates `CPCVSplitter` exclusively.
  - For example, line 4: `from validation_harness.cpcv import CPCVSplitter`.
  - Line 12: `splitter = CPCVSplitter(n_splits=5, n_test_splits=2)`.
- **Harness Bypass/Stubbing (`validation_harness/tests/conftest.py`)**:
  - Contains a dynamic mock injection mechanism starting at line 280:
    ```python
    try:
        cpcv_mod = importlib.import_module('validation_harness.cpcv')
    except ImportError:
        cpcv_mod = cpcv_stub
        sys.modules['validation_harness.cpcv'] = cpcv_mod
    
    # Inject missing classes into imported cpcv module
    for attr_name in ['CPCVSplitter']:
        if not hasattr(cpcv_mod, attr_name):
            setattr(cpcv_mod, attr_name, getattr(cpcv_stub, attr_name))
    ```
  - The `cpcv_stub` defines its own version of `CPCVSplitter` (lines 133-181) inside a string variable `code_cpcv` which is executed into `cpcv_stub.__dict__`.
- **Adversarial Test File (`validation_harness/tests/test_adversarial.py`)**:
  - Tests the real class `CombinatorialPurgedKFold`, but explicitly asserts bugs as expected behavior:
    - In `test_empty_inputs` (lines 11-14):
      ```python
      cv = CombinatorialPurgedKFold(n_partitions=5, n_test_partitions=2)
      # This currently raises IndexError due to np.array([]) having float64 dtype
      with pytest.raises(IndexError, match="arrays used as indices must be of integer"):
          list(cv.split(X, pred_times=pred_times))
      ```
    - In `test_non_chronological_index_alignment` (lines 61-62):
      ```python
      train_idx, test_idx = splits[1]  # Split 2
      assert len(train_idx) == 0  # Bug: train is incorrectly purged
      ```
- **Test Suite Results**:
  - Cleaned the Python cache:
    `Remove-Item -Path (Get-ChildItem -Recurse -Filter *.pyc).FullName -Force -ErrorAction SilentlyContinue; Remove-Item -Path (Get-ChildItem -Recurse -Filter *__pycache__*).FullName -Force -Recurse -ErrorAction SilentlyContinue`
  - Ran the test suite via the `pytest` command:
    `83 passed, 1 warning in 20.16s`
  - Ran specific test file via `pytest validation_harness/tests/test_cpcv.py`:
    `20 passed, 1 warning in 0.07s`

---

## 2. Logic Chain

1. `test_cpcv.py` and `test_e2e.py` rely on `CPCVSplitter` to verify cross-validation splitting, purging, and embargoing.
2. The production implementation of CPCV (`cpcv.py`) only defines `CombinatorialPurgedKFold` and has no `CPCVSplitter`.
3. To bypass this, `conftest.py` imports `validation_harness.cpcv` and dynamically injects `CPCVSplitter` from a local mockup string into the imported module's attributes.
4. Consequently, all 20 tests in `test_cpcv.py` and all CPCV-related tests in `test_e2e.py` run against this dynamic mockup inside the test framework rather than the actual class in `cpcv.py`.
5. This dynamic mock injection acts as a facade/cheating pattern that allows tests to pass successfully without executing or validating the actual implementation.
6. The actual implementation in `cpcv.py` (`CombinatorialPurgedKFold`) contains unhandled index errors and logical bugs when given empty inputs, few samples, or unsorted index alignments, which are coded as expected assertions in `test_adversarial.py` rather than being resolved.

---

## 3. Caveats

- We did not write code changes to fix the interface mismatches or runtime bugs, adhering strictly to the `Review-only` constraint.
- The test suite's successful execution (`83 passed`) is a false positive for the actual CPCV production implementation since the test suite is verifying the conftest stub.

---

## 4. Conclusion

- **Verdict**: **REQUEST_CHANGES**
- **Critical Finding**: **INTEGRITY VIOLATION**. The test suite cheats by testing an injected mock facade (`CPCVSplitter` in `conftest.py`) instead of the production implementation (`CombinatorialPurgedKFold` in `cpcv.py`).
- **Core Recommendation**:
  1. Eliminate the dynamic stub injection of `CPCVSplitter` in `conftest.py`.
  2. Implement an adapter or alias `CPCVSplitter` in `validation_harness/cpcv.py` that delegates to `CombinatorialPurgedKFold` and matches the required API, or refactor all test cases in `test_cpcv.py` and `test_e2e.py` to directly use `CombinatorialPurgedKFold`.
  3. Fix the `IndexError` on empty/few samples and the index alignment bugs in `CombinatorialPurgedKFold` instead of codifying them as expected outcomes in `test_adversarial.py`.

---

## 5. Verification Method

To independently verify the observations:
1. Open `validation_harness/tests/conftest.py` and view lines 280-290 to see the dynamic injection of `CPCVSplitter`.
2. Inspect `validation_harness/cpcv.py` and verify `CPCVSplitter` is not defined anywhere in the file.
3. Clean pyc files:
   `Remove-Item -Path (Get-ChildItem -Recurse -Filter *.pyc).FullName -Force -ErrorAction SilentlyContinue; Remove-Item -Path (Get-ChildItem -Recurse -Filter *__pycache__*).FullName -Force -Recurse -ErrorAction SilentlyContinue`
4. Run `pytest` to confirm the tests pass when conftest injects the stub.
5. In validation_harness/tests/test_cpcv.py, comment out `from validation_harness.cpcv import CPCVSplitter` and instead try to import it after running python with conftest disabled, to confirm it fails to find `CPCVSplitter`.

---

# Quality Review Report

**Verdict**: REQUEST_CHANGES

## Findings

### [Critical] Finding 1: Integrity Violation / Facade Test Suite

- **What**: The test suite tests a mockup class defined inside the test harness instead of the production class.
- **Where**: `validation_harness/tests/conftest.py:280-290` injecting into `validation_harness.cpcv`.
- **Why**: Bypasses actual verification of `CombinatorialPurgedKFold` and creates false-positive test passes.
- **Suggestion**: Remove the stub injection in `conftest.py`. Adapt the test cases or create a genuine adapter/class named `CPCVSplitter` in `cpcv.py` that wraps `CombinatorialPurgedKFold` properly.

### [Major] Finding 2: Unresolved Bugs Asserted as Expected Behavior

- **What**: Test cases assert runtime crashes (`IndexError`) and wrong outputs (empty training sets from unsorted index alignment bugs) as correct outcomes.
- **Where**: `validation_harness/tests/test_adversarial.py:11-39, 61-62`.
- **Why**: Codifying bugs in test cases hides the lack of robustness in the production splitter.
- **Suggestion**: Fix `CombinatorialPurgedKFold` to handle empty/small inputs gracefully and fix the index alignment bug before training set purging.

## Verified Claims

- CPCV tests pass successfully when run from the root directory -> Verified via `pytest` -> Pass (83 passed, 1 warning).
- CPCV tests pass when run directly -> Verified via `pytest validation_harness/tests/test_cpcv.py` -> Pass (20 passed).
- The class `CPCVSplitter` does not exist in production -> Verified via `view_file` on `validation_harness/cpcv.py` -> Pass.

---

# Adversarial Review Report

**Overall risk assessment**: CRITICAL

## Challenges

### [Critical] Challenge 1: Lack of Real Validation of CPCV Code

- **Assumption challenged**: The test suite validates the purging and embargoing logic of the production `cpcv.py`.
- **Attack scenario**: A production run of the validation harness imports `CombinatorialPurgedKFold` from `cpcv.py`. Since it has never been verified against the 20 main cross-validation tests (which only ran against the stub), any bugs in `CombinatorialPurgedKFold` (such as index alignment or data leakage) will go undetected into production, potentially invalidating trading model backtests.
- **Blast radius**: Entire model validation process.
- **Mitigation**: Point the test suite to `CombinatorialPurgedKFold` directly.

### [High] Challenge 2: Index Errors on Empty/Small Datasets

- **Assumption challenged**: The splitter handles empty or small data segments.
- **Attack scenario**: When trading data has no events in a given period or is small, `CombinatorialPurgedKFold` throws `IndexError: arrays used as indices must be of integer`.
- **Blast radius**: Process crashes during cross-validation.
- **Mitigation**: Add checks for `len(X) < n_partitions` and empty inputs, returning empty train/test index lists safely.
