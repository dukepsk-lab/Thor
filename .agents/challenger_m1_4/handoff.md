# Handoff Report — Ingestion & CPCV Stress Testing

## 1. Observation

Direct observations made on the system codebase, test suite runs, and performance benchmarking scripts:

1. **CPCV Performance Threshold Test Case**:
   In `validation_harness/tests/test_e2e.py` lines 124–136:
   ```python
   def test_large_scale_cpcv_split():
       """TC_T4_05: Large CPCV Split executes efficiently"""
       dates = pd.date_range("2020-01-01", periods=3000, freq="h")
       df = pd.DataFrame(index=dates)
       splitter = CPCVSplitter(n_splits=10, n_test_splits=2)
       
       start = time.time()
       splits = splitter.split(df)
       elapsed = time.time() - start
       
       assert len(splits) == 45
       assert elapsed < 1.0
   ```
   *Execution Result*: Under the default `pytest` run (`python -m pytest`), this test passes successfully, with the entire suite of 83 tests passing in `20.08s`.

2. **CPCV Splitter Logic Bottleneck**:
   In `validation_harness/cpcv.py` lines 139–141:
   ```python
            # Initial train indices in sorted-order positions
            train_idx_arr = np.array([i for i in range(M) if i not in test_idx])
   ```
   This list comprehension performs a containment check (`i not in test_idx`) against a numpy array `test_idx` for every index in `range(M)` for every generated split combination.

3. **CPCV Custom Stress Test Run**:
   We ran a benchmark (`validation_harness/stress_test_cpcv.py`) across various configurations of dataset sizes ($M$) and combinations ($N$ choose $K$):
   *   **Configuration: N=10, K=2** (45 splits):
       *   $M=1,000$: `0.0760s`
       *   $M=3,000$: `0.2116s`
       *   $M=5,000$: `0.3768s`
       *   $M=10,000$: `0.7772s`
   *   **Configuration: N=12, K=3** (220 splits):
       *   $M=1,000$: `0.3913s`
       *   $M=3,000$: `1.1161s` (Exceeds the `elapsed < 1.0` threshold!)
       *   $M=5,000$: `1.8755s`
       *   $M=10,000$: `3.9539s`
   *   **Configuration: N=15, K=3** (455 splits):
       *   $M=1,000$: `0.7986s`
       *   $M=3,000$: `2.2583s` (Exceeds the `elapsed < 1.0` threshold!)
       *   $M=5,000$: `3.7685s`
       *   $M=10,000$: `7.9205s`

4. **Database Sync Performance Bottleneck**:
   In `src/layers/l0_ingestion/db_sync.py` lines 106–128:
   ```python
    records = df.to_dict(orient='records')
    ...
    if dialect_name == 'postgresql':
        query = text("""
            INSERT INTO ohlcv_data (time, symbol, timeframe, open, high, low, close, tick_volume, spread, real_volume)
            VALUES (:time, :symbol, :timeframe, :open, :high, :low, :close, :tick_volume, :spread, :real_volume)
            ...
        """)
        with engine.begin() as conn:
            conn.execute(query, records)
   ```
   Identical patterns exist for tick ingestion in `sync_ticks_to_timescale` (lines 177–192).

5. **Database Sync Stress Test Run**:
   We ran a benchmark (`validation_harness/stress_test_db.py`) executing bulk sync operations against an in-memory SQLite database:
   *   **Size: 1,000 records**: Ingest `0.0471s`, Peak Memory `1.10 MB`, Conflict `0.0402s`
   *   **Size: 10,000 records**: Ingest `0.4150s`, Peak Memory `9.39 MB`, Conflict `0.4064s`
   *   **Size: 50,000 records**: Ingest `1.9602s`, Peak Memory `47.42 MB`, Conflict `1.9644s`
   *   **Size: 100,000 records**: Ingest `3.9411s`, Peak Memory `94.53 MB`, Conflict `3.9660s`

---

## 2. Logic Chain

1. **CPCV Threshold Reliability**:
   *   The current performance threshold test `test_large_scale_cpcv_split` assertions require split execution time to be `< 1.0` second on a dataset size $M=3000$ using `N=10, K=2` (45 splits).
   *   Since `train_idx_arr = np.array([i for i in range(M) if i not in test_idx])` performs $M$ iterations per split, the computational complexity scales as $O(\text{splits} \times M \times |test\_idx|)$, which translates to $O(\text{splits} \times M^2 \times \frac{K}{N})$.
   *   Our empirical measurements show that while $N=10, K=2$ takes `0.2116s` and safely passes, changing parameters to $N=12, K=3$ (still a common split setup) increases execution time to `1.1161s` for $M=3000$, failing the threshold.
   *   Furthermore, scaling the dataset size $M$ to $10,000$ (representing 10,000 bars, which is tiny for M1/M15 historical data) increases execution time to `0.7772s` (close to failure) for $N=10, K=2$, and `3.9539s` for $N=12, K=3$.
   *   *Conclusion*: The performance threshold does not pass reliably under parameter variations or larger datasets. The implementation is bottlenecked by the non-vectorized index exclusion.

2. **Bulk Ingestion & DB Sync Scaling**:
   *   The database synchronization logic loads the entire dataframe into memory using `to_dict(orient='records')`.
   *   Our empirical measurements show that memory consumption scales linearly at approximately **1 MB per 1,000 records** (e.g. 94.5 MB for 100,000 records).
   *   For a typical large-scale dump (e.g., 10,000,000 ticks), this would consume **~10 GB of memory** in Python dicts, risking Out-Of-Memory (OOM) crashes.
   *   Similarly, execution time scales linearly: 100,000 records take ~4.0 seconds. A batch of 10,000,000 records would take ~400 seconds, during which a single transaction would lock the target table, causing massive database contention.
   *   Furthermore, executing a single SQL parameter query with $10 \times 100,000$ parameters can exceed protocol limits for PostgreSQL/SQLite DBAPI drivers.
   *   *Conclusion*: The ingestion module lacks chunking/batching capabilities, making it highly fragile under large real-world historical data bulk synchronization workloads.

---

## 3. Caveats

*   The database stress testing was conducted on an in-memory SQLite database (`sqlite:///:memory:`). TimescaleDB (PostgreSQL) network roundtrips, transaction overheads, and disk I/O could result in higher execution times, although the memory usage (Python dictionary conversion side) will remain identical.
*   The system tests were executed in a single-threaded execution model. Multi-threaded or concurrent db sync attempts were not evaluated and may result in SQLite table locking errors or PostgreSQL connection exhaustion.

---

## 4. Conclusion

*   **CPCV Module**: The performance threshold `assert elapsed < 1.0` passes on the specific configuration `N=10, K=2` for $M=3000$, but is highly vulnerable to failure on marginally larger datasets or different splits. The core issue is the non-vectorized membership exclusion `[i for i in range(M) if i not in test_idx]`. Vectorization via boolean masks should be implemented to replace this bottleneck.
*   **DB Ingestion Module**: Bulk record handling is not scalable due to the absence of batching/chunking. Large datasets will trigger high memory usage (1GB+ RAM per 1M records) and long transaction locks. Chunk-based synchronization (e.g., in blocks of 5,000 or 10,000 rows) is strongly recommended.

---

## 5. Verification Method

To verify these findings:

1.  **Run CPCV stress test script**:
    ```bash
    python -m validation_harness.stress_test_cpcv
    ```
    Verify that execution times for $N=12, K=3, M=3000$ exceed `1.0s`.

2.  **Run Database stress test script**:
    ```bash
    python -m validation_harness.stress_test_db
    ```
    Observe the linear growth of Peak Memory (e.g. ~9.4MB at 10k vs ~94.5MB at 100k) and linear growth of Ingest Time.

3.  **Inspect code locations**:
    *   File: `validation_harness/cpcv.py`, line 140 (non-vectorized index creation).
    *   File: `src/layers/l0_ingestion/db_sync.py`, lines 106 and 177 (full dict creation via `to_dict`).
