import numpy as np
import pandas as pd
import pytest
from validation_harness.cpcv import CombinatorialPurgedKFold, get_cpcv_splits, calculate_sample_uniqueness_exact

def test_interface_compatibility():
    """Verify that the class interface doesn't match CPCVSplitter expected by test suite."""
    print("\n--- Running Interface Compatibility Check ---")
    mismatches = []
    
    # Check parameters
    import inspect
    sig = inspect.signature(CombinatorialPurgedKFold.__init__)
    params = list(sig.parameters.keys())
    
    expected_params = ['n_splits', 'n_test_splits', 'embargo_pct']
    for ep in expected_params:
        if ep not in params:
            mismatches.append(f"Missing parameter in __init__: {ep}")
            
    # Check split signature and yield type
    # test_cpcv.py expects a list/iterable of dicts, e.g. splits[i]['train'] and splits[i]['test']
    # CombinatorialPurgedKFold.split is a generator yielding tuples (train_idx, test_idx)
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    cv = CombinatorialPurgedKFold(n_partitions=5, n_test_partitions=1)
    
    # Try calling split like test suite does: split(df, event_times=...)
    # The actual split takes: pred_times
    # If the test suite passes event_times as a positional argument (e.g. split(df, event_times))
    # It maps to y! Because split is: split(self, X, y=None, pred_times=None)
    # If called as splitter.split(df, event_times), event_times maps to y, and pred_times is None,
    # raising ValueError: pred_times (event hit times) is required for CPCV purging and embargoing.
    
    event_times = pd.Series(dates, index=dates)
    try:
        # Call it positionally like in some test_cpcv.py tests
        # e.g., splitter.split(df, event_times)
        generator = cv.split(df, event_times)
        next(generator)
        mismatches.append("Calling split(df, event_times) positionally did not raise error, but it should fail because event_times maps to y")
    except ValueError as e:
        mismatches.append(f"Calling split(df, event_times) positionally failed with: {e} (because event_times is treated as y, leaving pred_times=None)")
    except Exception as e:
        mismatches.append(f"Calling split(df, event_times) positionally failed with unexpected: {e}")
        
    print("Mismatches found:")
    for m in mismatches:
        print(f" - {m}")
        
    return mismatches

def test_purging_correctness():
    """Adversarially test the purging logic under different offsets."""
    print("\n--- Running Purging Correctness Test ---")
    # 5 events, daily frequency
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    X = pd.DataFrame(index=dates)
    
    # Event 0: starts Jan 1, ends Jan 2.
    # Event 1: starts Jan 2, ends Jan 3.
    # Event 2: starts Jan 3, ends Jan 4.
    # Event 3: starts Jan 4, ends Jan 5.
    # Event 4: starts Jan 5, ends Jan 6.
    pred_times = pd.Series(dates + pd.Timedelta(days=1), index=dates)
    
    # N=5, k=1. Each partition has exactly 1 event.
    # Test partition is index 2 (Event 2: starts Jan 3, ends Jan 4).
    # Purging offset = 0.
    cv = CombinatorialPurgedKFold(n_partitions=5, n_test_partitions=1, purging_offset=pd.Timedelta(days=0), embargo_offset=0.0)
    splits = list(cv.split(X, pred_times=pred_times))
    
    # Let's inspect the split where the test set is Event 2 (index 2).
    # Since n_partitions=5, k=1, there are 5 splits. The 2nd split should have test=[2].
    target_split = None
    for train_idx, test_idx in splits:
        if 2 in test_idx and len(test_idx) == 1:
            target_split = (train_idx, test_idx)
            break
            
    assert target_split is not None
    train_idx, test_idx = target_split
    
    print(f"Test index: {test_idx}")
    print(f"Train index: {train_idx}")
    
    # Event 1 starts Jan 2, ends Jan 3. The test event (Event 2) starts Jan 3.
    # Since Event 1 ends at Jan 3, and purging offset is 0,
    # ti_hit + offset = Jan 3 + 0 = Jan 3 >= t_start_min (Jan 3).
    # So Event 1 must be purged.
    # Event 0 starts Jan 1, ends Jan 2. ti_hit + offset = Jan 2 + 0 = Jan 2 < Jan 3.
    # So Event 0 must NOT be purged.
    # Let's check:
    assert 1 not in train_idx, "Event 1 should be purged because its hit time matches test start time"
    assert 0 in train_idx, "Event 0 should not be purged"
    
    # Now let's try with purging_offset = 12 hours.
    # Event 0 ends Jan 2. ti_hit + offset = Jan 2 + 12h = Jan 2 12:00 < Jan 3.
    # So Event 0 should still not be purged.
    # What if purging_offset = 24 hours?
    # Event 0 ends Jan 2. ti_hit + offset = Jan 2 + 24h = Jan 3 >= Jan 3.
    # So Event 0 must be purged!
    cv_offset = CombinatorialPurgedKFold(n_partitions=5, n_test_partitions=1, purging_offset=pd.Timedelta(days=1), embargo_offset=0.0)
    splits_offset = list(cv_offset.split(X, pred_times=pred_times))
    for train_idx_o, test_idx_o in splits_offset:
        if 2 in test_idx_o and len(test_idx_o) == 1:
            print(f"With 1 day purging offset - Train: {train_idx_o}")
            assert 0 not in train_idx_o, "Event 0 should be purged when purging offset is 1 day"
            
    print("Purging correctness tests passed.")

def test_embargo_correctness_and_boundary_bug():
    """Verify embargo behavior and the boundary bug where the last partition is test."""
    print("\n--- Running Embargo and Boundary Bug Test ---")
    
    # 5 events
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    X = pd.DataFrame(index=dates)
    pred_times = pd.Series(dates + pd.Timedelta(days=1), index=dates)
    
    # We use an integer embargo of 1.
    # Test partition is index 4 (Event 4: starts Jan 5, ends Jan 6).
    # Since reference_index is t_start_sorted = [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5].
    # t_hit_max is Jan 6.
    # idx = reference_index.searchsorted(Jan 6) = 5 (since Jan 6 is greater than Jan 5).
    # embargo_idx = min(5 + 1, 5 - 1) = 4.
    # t_embargo = reference_index[4] = Jan 5.
    # Wait, Jan 6 + 1 bar should end at a time after Jan 6. But because the index is capped,
    # the embargo boundary actually becomes Jan 5!
    # Let's see what happens to training events that start after the test partition.
    # Wait, in this split:
    # Test partition is index 4 (Event 4: starts Jan 5).
    # There are no training events after Jan 5 because Event 4 is the last event.
    
    # Let's design a case where there is a training event after the test partition!
    # Let's say N=5, k=1. The test partition is P2 (index 2: Event 2).
    # Events:
    # 0: start Jan 1, hit Jan 1.5
    # 1: start Jan 2, hit Jan 2.5
    # 2 (TEST): start Jan 3, hit Jan 4.5  (spans 1.5 days!)
    # 3 (TRAIN): start Jan 4, hit Jan 4.5
    # 4 (TRAIN): start Jan 5, hit Jan 5.5
    # Since Event 2 hit time is Jan 4.5.
    # Reference index = [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5].
    # embargo_offset = 1 (1 bar).
    # Since t_hit_max = Jan 4.5.
    # searchsorted(Jan 4.5) on [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5] -> index is 4 (since Jan 4.5 is between Jan 4 and Jan 5).
    # Wait, searchsorted returns 4.
    # embargo_idx = min(4 + 1, 4) = 4.
    # So t_embargo = reference_index[4] = Jan 5.
    # Train Event 4 starts Jan 5. Since ti_start = Jan 5 <= t_embargo (Jan 5), Event 4 is purged/embargoed.
    # What if embargo_offset = 2?
    # embargo_idx = min(4 + 2, 4) = 4.
    # So t_embargo is still Jan 5!
    # Thus, Even if we ask for 2 bars embargo, the boundary is capped at Jan 5!
    # So if there was a Train Event 5 starting Jan 6:
    # Since Jan 6 > Jan 5, it would NOT be embargoed under offset=2, even though Jan 6 is only 1.5 days after Jan 4.5
    # and the bar step is 1 day, so 2 bars would be 2 days (Jan 6.5).
    # Let's check this empirically!
    
    dates = pd.date_range("2023-01-01", periods=6, freq="D")
    X = pd.DataFrame(index=dates)
    pred_times = pd.Series([
        pd.Timestamp("2023-01-01 12:00:00"),
        pd.Timestamp("2023-01-02 12:00:00"),
        pd.Timestamp("2023-01-04 12:00:00"), # TEST event, hits Jan 4 12:00
        pd.Timestamp("2023-01-04 12:00:00"),
        pd.Timestamp("2023-01-05 12:00:00"),
        pd.Timestamp("2023-01-06 12:00:00"),
    ], index=dates)
    
    # N=6, k=1. Test partition is P2 (index 2).
    # Reference index = [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5, Jan 6].
    # embargo_offset = 2.
    # t_hit_max of Event 2 is Jan 4 12:00.
    # searchsorted(Jan 4 12:00) on reference index returns 4.
    # embargo_idx = min(4 + 2, 5) = 5.
    # t_embargo = reference_index[5] = Jan 6.
    # Train Event 5 starts Jan 6. Since ti_start = Jan 6 <= Jan 6, Event 5 is purged/embargoed.
    
    # Now what if embargo_offset = 5?
    # embargo_idx = min(4 + 5, 5) = 5.
    # t_embargo is still Jan 6.
    # So Train Event 5 (starts Jan 6) is still the last one that can be purged.
    # If we had Train Event 6 starting Jan 7 (which is 2.5 days after Jan 4 12:00, and embargo_offset = 5 days should cover it).
    # Let's add Event 6 starting Jan 7.
    dates_7 = pd.date_range("2023-01-01", periods=7, freq="D")
    X_7 = pd.DataFrame(index=dates_7)
    pred_times_7 = pd.Series([
        pd.Timestamp("2023-01-01 12:00:00"),
        pd.Timestamp("2023-01-02 12:00:00"),
        pd.Timestamp("2023-01-04 12:00:00"), # TEST event
        pd.Timestamp("2023-01-04 12:00:00"),
        pd.Timestamp("2023-01-05 12:00:00"),
        pd.Timestamp("2023-01-06 12:00:00"),
        pd.Timestamp("2023-01-07 12:00:00"),
    ], index=dates_7)
    
    # Reference index: [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5, Jan 6, Jan 7].
    # Test partition: index 2.
    # t_hit_max: Jan 4 12:00.
    # searchsorted: index 4.
    # If embargo_offset = 4:
    # embargo_idx = min(4 + 4, 6) = 6.
    # t_embargo = reference_index[6] = Jan 7.
    # Since Event 6 starts Jan 7 <= Jan 7, it is purged.
    # If embargo_offset = 5:
    # embargo_idx = min(4 + 5, 6) = 6.
    # t_embargo = reference_index[6] = Jan 7.
    # Event 6 starts Jan 7 <= Jan 7, it is purged.
    # BUT Event 7 starting Jan 8 (not in reference index) would not be purged.
    # Wait, what if we increase the embargo offset even more? It is always capped at reference_index[-1] (Jan 7).
    # So any training event starting after Jan 7 will NEVER be purged, no matter how large the embargo offset is!
    # Let's verify this by testing if large embargo_offset fails to purge events starting after reference_index[-1].
    # Let's add Event 7 starting Jan 8.
    dates_8 = pd.date_range("2023-01-01", periods=8, freq="D")
    X_8 = pd.DataFrame(index=dates_8)
    pred_times_8 = pd.Series([
        pd.Timestamp("2023-01-01 12:00:00"),
        pd.Timestamp("2023-01-02 12:00:00"),
        pd.Timestamp("2023-01-04 12:00:00"), # TEST event
        pd.Timestamp("2023-01-04 12:00:00"),
        pd.Timestamp("2023-01-05 12:00:00"),
        pd.Timestamp("2023-01-06 12:00:00"),
        pd.Timestamp("2023-01-07 12:00:00"),
        pd.Timestamp("2023-01-08 12:00:00"),
    ], index=dates_8)
    
    # Set embargo_offset = 10 (which is larger than the remaining dataset).
    cv_emb = CombinatorialPurgedKFold(n_partitions=8, n_test_partitions=1, embargo_offset=10)
    splits_emb = list(cv_emb.split(X_8, pred_times=pred_times_8))
    
    # Test partition is index 2.
    target_train = None
    for train_idx, test_idx in splits_emb:
        if 2 in test_idx and len(test_idx) == 1:
            target_train = train_idx
            break
            
    print(f"Embargo offset 10 - Train indices: {target_train}")
    # Wait! If embargo_offset is 10 bars, it should purge ALL training samples after the test set (since there are only 5 more days).
    # But because of the cap at len(reference_index) - 1, the embargo boundary is reference_index[-1] (Jan 8).
    # Let's see: Event 7 starts Jan 8. ti_start = Jan 8 <= Jan 8. So it is purged.
    # Wait, what if we have Event 8 starting Jan 9? It would be after reference_index[-1] (Jan 8).
    # But wait, why is Jan 8 the last element of reference_index? Because reference_index defaults to t_start_sorted,
    # which is the start times of the events in the dataset.
    # What if we pass `bar_times` to the constructor?
    # If `bar_times` only goes up to Jan 8, but we have a training event starting Jan 9.
    # In that case, reference_index[-1] is Jan 8, and the training event starting Jan 9 is not purged, even though embargo offset is 10!
    
    # Wait, another major issue is percentage-based embargo.
    # Let's check float:
    # embargo_offset = 0.5.
    # n_bars = int(0.5 * 8) = 4.
    # t_hit_max = Jan 4 12:00.
    # searchsorted(Jan 4 12:00) = 4.
    # embargo_idx = min(4 + 4, 7) = 7.
    # t_embargo = reference_index[7] = Jan 8.
    # If embargo_offset = 0.9.
    # n_bars = int(0.9 * 8) = 7.
    # embargo_idx = min(4 + 7, 7) = 7.
    # t_embargo is still Jan 8.
    # So again, capped at reference_index[-1].
    
    # Wait! What if t_hit_max is greater than reference_index[-1]?
    # For example, suppose the test event ends on Jan 9, but the last start time in the dataset is Jan 8.
    # (This is very common if the last event spans multiple days).
    # Let's test this case!
    # Events:
    # 0: start Jan 1, hit Jan 2
    # 1: start Jan 2, hit Jan 3
    # 2 (TEST): start Jan 3, hit Jan 9  (ends Jan 9!)
    # 3 (TRAIN): start Jan 4, hit Jan 5
    # 4 (TRAIN): start Jan 5, hit Jan 6
    # 5 (TRAIN): start Jan 8, hit Jan 9
    # In this case:
    # t_start_sorted = [Jan 1, Jan 2, Jan 3, Jan 4, Jan 5, Jan 8]
    # reference_index = t_start_sorted (last is Jan 8).
    # TEST event hit time is Jan 9.
    # t_hit_max = Jan 9.
    # `reference_index.searchsorted(Jan 9)` returns 6.
    # `embargo_idx = min(6 + offset, len(reference_index) - 1) = min(6 + offset, 5) = 5`.
    # `t_embargo = reference_index[5] = Jan 8`.
    # Wait! The embargo boundary becomes Jan 8.
    # But the test event ended on Jan 9!
    # This means the embargo boundary (Jan 8) is BEFORE the test event ended (Jan 9).
    # Let's check Train Event 5 starting on Jan 8.
    # Since ti_start = Jan 8 <= t_embargo (Jan 8), it is purged.
    # But what if there is a Train Event 6 starting on Jan 8 12:00?
    # ti_start = Jan 8 12:00 > Jan 8.
    # It starts AFTER Jan 8, so it is NOT purged or embargoed!
    # Even though it starts before the test event ended (Jan 9), and should have been purged!
    # Let's test this!
    
    dates_leak = pd.to_datetime(["2023-01-01 00:00:00", "2023-01-02 00:00:00", "2023-01-03 00:00:00", "2023-01-04 00:00:00", "2023-01-05 00:00:00", "2023-01-08 12:00:00"])
    X_leak = pd.DataFrame(index=dates_leak)
    pred_times_leak = pd.Series([
        pd.Timestamp("2023-01-02"),
        pd.Timestamp("2023-01-03"),
        pd.Timestamp("2023-01-09"), # TEST event ends Jan 9
        pd.Timestamp("2023-01-05"),
        pd.Timestamp("2023-01-06"),
        pd.Timestamp("2023-01-09 12:00:00"), # TRAIN event starts Jan 8 12:00
    ], index=dates_leak)
    
    cv_leak = CombinatorialPurgedKFold(n_partitions=6, n_test_partitions=1, embargo_offset=0.0) # no embargo, just purging
    splits_leak = list(cv_leak.split(X_leak, pred_times=pred_times_leak))
    
    # Test partition is index 2.
    target_train_leak = None
    for train_idx, test_idx in splits_leak:
        if 2 in test_idx and len(test_idx) == 1:
            target_train_leak = train_idx
            break
            
    print(f"Leak Test (Purging only) - Train indices: {target_train_leak}")
    # Wait, the training event at index 5 starts on Jan 8 12:00.
    # The test event ends on Jan 9.
    # So the training event starts BEFORE the test event ends, which means they overlap, so it MUST be purged!
    # Let's see if 5 is in target_train_leak.
    # If 5 is in target_train_leak, it means a training sample overlapping with a test sample was NOT purged!
    # That is a critical bug.
    
    # Let's run this test and print the result.
    if 5 in target_train_leak:
        print("CRITICAL BUG: Train event 5 is NOT purged despite starting before test event ends (starts Jan 8 12:00, test ends Jan 9)!")
    else:
        print("Train event 5 was correctly purged.")

    # Now, test leakage with non-zero embargo offset = 1 bar
    # dates_leak has 6 elements, last starts at Jan 8 12:00.
    # We add another train event starting Jan 8 13:00.
    dates_leak2 = pd.to_datetime([
        "2023-01-01 00:00:00",
        "2023-01-02 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-04 00:00:00",
        "2023-01-05 00:00:00",
        "2023-01-08 12:00:00",
        "2023-01-08 13:00:00",  # Event 6
    ])
    X_leak2 = pd.DataFrame(index=dates_leak2)
    pred_times_leak2 = pd.Series([
        pd.Timestamp("2023-01-02 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-09 00:00:00"),  # TEST event ends Jan 9
        pd.Timestamp("2023-01-05 00:00:00"),
        pd.Timestamp("2023-01-06 00:00:00"),
        pd.Timestamp("2023-01-09 12:00:00"),
        pd.Timestamp("2023-01-09 12:00:00"),  # TRAIN event starts Jan 8 13:00, ends Jan 9 12:00 (overlaps TEST!)
    ], index=dates_leak2)

    cv_leak2 = CombinatorialPurgedKFold(n_partitions=7, n_test_partitions=1, embargo_offset=1)
    splits_leak2 = list(cv_leak2.split(X_leak2, pred_times=pred_times_leak2))

    # Test partition is index 2.
    target_train_leak2 = None
    for train_idx, test_idx in splits_leak2:
        if 2 in test_idx and len(test_idx) == 1:
            target_train_leak2 = train_idx
            break

    print(f"Leak Test 2 (Embargo = 1 bar) - Train indices: {target_train_leak2}")
    if 6 in target_train_leak2:
        print("CRITICAL BUG: Train event 6 (starts Jan 8 13:00) is NOT purged/embargoed despite starting before test event ends (Jan 9)!")
    else:
        print("Train event 6 was correctly purged.")

    # Test duplicate start times when bar_times is None
    # Events start: Jan 1, Jan 2, Jan 3, Jan 3, Jan 3, Jan 3, Jan 3, Jan 4
    dates_dup = pd.to_datetime([
        "2023-01-01 00:00:00",
        "2023-01-02 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-03 00:00:00",
        "2023-01-04 00:00:00", # Event 7
    ])
    X_dup = pd.DataFrame(index=dates_dup)
    pred_times_dup = pd.Series([
        pd.Timestamp("2023-01-02 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"), # TEST event starts Jan 2, ends Jan 3
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-03 00:00:00"),
        pd.Timestamp("2023-01-05 00:00:00"), # TRAIN event starts Jan 4, ends Jan 5
    ], index=dates_dup)

    # Test is index 1 (starts Jan 2, ends Jan 3).
    # Since n_partitions=8, k=1, test index 1 is in partition 1.
    # We set embargo_offset = 3 (3 bars).
    # t_hit_max of partition 1 is Jan 3.
    # searchsorted(Jan 3) on reference_index finds first Jan 3 at index 2.
    # idx = 2.
    # embargo_idx = min(2 + 3, 7) = 5.
    # reference_index[5] is Jan 3!
    # So t_embargo is Jan 3.
    # Train Event 7 starts Jan 4.
    # Since ti_start = Jan 4 > Jan 3 (t_embargo), Event 7 is NOT purged/embargoed!
    # But wait, we specified an embargo offset of 3 bars! If we actually had 3 distinct bars,
    # the embargo should have extended to Jan 4 or Jan 5.
    # Instead, because of duplicates, the embargo boundary is Jan 3, and Event 7 (starting Jan 4) leaks.
    cv_dup = CombinatorialPurgedKFold(n_partitions=8, n_test_partitions=1, embargo_offset=3)
    splits_dup = list(cv_dup.split(X_dup, pred_times=pred_times_dup))

    target_train_dup = None
    for train_idx, test_idx in splits_dup:
        if 1 in test_idx and len(test_idx) == 1:
            target_train_dup = train_idx
            break

    print(f"Duplicate Start Times Test (Embargo = 3 bars) - Train indices: {target_train_dup}")
    if 7 in target_train_dup:
        print("CRITICAL BUG: Train event 7 (starts Jan 4) is NOT embargoed despite embargo_offset=3, because duplicates prevented the embargo boundary from advancing in time!")
    else:
        print("Train event 7 was correctly embargoed.")

    # Test bar_times capping leak
    # bar_times: Jan 1, Jan 2, Jan 3, Jan 4, Jan 5
    # Events start: Jan 1, Jan 2, Jan 3, Jan 4, Jan 6 (Event 4)
    # TEST event starts Jan 3, ends Jan 4 (index 2).
    # embargo_offset = 3.
    # Expected embargo boundary to extend to Jan 7 (3 bars after Jan 4).
    # Since Event 4 starts Jan 6, it should be embargoed.
    # Let's see if it leaks.
    bar_times = pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04", "2023-01-05"])
    dates_bar = pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04", "2023-01-06"])
    X_bar = pd.DataFrame(index=dates_bar)
    pred_times_bar = pd.Series([
        pd.Timestamp("2023-01-02"),
        pd.Timestamp("2023-01-03"),
        pd.Timestamp("2023-01-04"), # TEST event
        pd.Timestamp("2023-01-05"),
        pd.Timestamp("2023-01-07"), # TRAIN event starts Jan 6
    ], index=dates_bar)

    cv_bar = CombinatorialPurgedKFold(n_partitions=5, n_test_partitions=1, embargo_offset=3, bar_times=bar_times)
    splits_bar = list(cv_bar.split(X_bar, pred_times=pred_times_bar))

    target_train_bar = None
    for train_idx, test_idx in splits_bar:
        if 2 in test_idx and len(test_idx) == 1:
            target_train_bar = train_idx
            break

    print(f"Bar Times Cap Leak Test (Embargo = 3 bars) - Train indices: {target_train_bar}")
    if 4 in target_train_bar:
        print("CRITICAL BUG: Train event 4 (starts Jan 6) is NOT embargoed despite embargo_offset=3, because the embargo boundary is capped at the last element of bar_times (Jan 5)!")
    else:
        print("Train event 4 was correctly embargoed.")


def test_performance_benchmark():
    """Measure execution time of the actual CombinatorialPurgedKFold implementation on 3,000 samples."""
    import time
    print("\n--- Running Performance Benchmark ---")
    dates = pd.date_range("2020-01-01", periods=3000, freq="h")
    df = pd.DataFrame(index=dates)
    pred_times = pd.Series(dates + pd.Timedelta(hours=2), index=dates)
    
    cv = CombinatorialPurgedKFold(n_partitions=10, n_test_partitions=2, purging_offset=pd.Timedelta(hours=4), embargo_offset=pd.Timedelta(hours=24))
    
    start = time.time()
    splits = list(cv.split(df, pred_times=pred_times))
    elapsed = time.time() - start
    
    print(f"Generated {len(splits)} splits in {elapsed:.4f} seconds.")
    if elapsed < 1.0:
        print("Performance PASS (less than 1.0s)")
    else:
        print(f"Performance FAIL: took {elapsed:.4f}s (exceeded 1.0s threshold)")


if __name__ == "__main__":
    test_interface_compatibility()
    test_purging_correctness()
    test_embargo_correctness_and_boundary_bug()
    test_performance_benchmark()
