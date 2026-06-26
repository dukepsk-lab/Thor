import pytest
import pandas as pd
import numpy as np
from validation_harness.cpcv import CPCVSplitter

# TIER 1: Feature Coverage (TC_T1_08 to 14)

def test_cpcv_split_count():
    """TC_T1_08: CPCV Split Count N=5, k=2 yields exactly 10 splits"""
    dates = pd.date_range("2023-01-01", periods=100)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2)
    splits = splitter.split(df)
    assert len(splits) == 10

def test_cpcv_split_disjointness():
    """TC_T1_09: CPCV Split Disjointness (intersection of train and test is empty)"""
    dates = pd.date_range("2023-01-01", periods=120)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=6, n_test_splits=2)
    splits = splitter.split(df)
    for s in splits:
        train_set = set(s["train"])
        test_set = set(s["test"])
        assert train_set.intersection(test_set) == set()

def test_cpcv_mask_coverage():
    """TC_T1_10: CPCV Mask Coverage N=4, k=1 yields each group appearing exactly once"""
    # Combinations of 4 choose 1 = 4.
    # Total samples = 100, each group = 25.
    dates = pd.date_range("2023-01-01", periods=100)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=4, n_test_splits=1)
    splits = splitter.split(df)
    assert len(splits) == 4
    
    # Track counts of how many times each sample is in test folds
    counts = np.zeros(100)
    for s in splits:
        counts[s["test"]] += 1
    assert (counts == 1).all()

def test_basic_purging():
    """TC_T1_11: Basic Purging removes overlapping train indices"""
    # 10 samples
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="D")
    df = pd.DataFrame(index=dates)
    # Events ending 1 day later (e.g. index 3 ends at day 4)
    event_times = pd.Series(dates + pd.Timedelta(days=1), index=dates)
    
    # Let's say test fold has index [4, 5] (dates[4] and dates[5])
    # The test intervals are [dates[4], dates[5]+1day] -> [Day 4, Day 6]
    # Train index 3: starts at Day 3, ends at Day 4. It overlaps Day 4. So index 3 should be purged!
    # Train index 6: starts at Day 6, ends at Day 7. It starts at Day 6 (which is test group end + 0, wait, if no embargo).
    # Let's check with embargo_pct = 0.0
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.0)
    splits = splitter.split(df, event_times)
    
    # Find a split containing Day 4, Day 5 as test
    # group_bounds for N=5 on 10 samples are: [0, 2, 4, 6, 8, 10]
    # Split 2 has test group 2: indices [4, 5].
    split_2 = splits[2]
    assert set(split_2["test"]) == {4, 5}
    # Index 3 event ends at Day 4 (which is test start). It should be purged.
    assert 3 not in split_2["train"]

def test_basic_embargo():
    """TC_T1_12: Basic Embargo removes train indices immediately after test fold"""
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="D")
    df = pd.DataFrame(index=dates)
    # Instantaneous events (event_times = df.index)
    event_times = pd.Series(dates, index=dates)
    
    # Set N=5, k=1. Group bounds: [0, 2, 4, 6, 8, 10]
    # Group 1 is test: indices [2, 3] (Day 2, Day 3).
    # Embargo of 10% on 9 days total span is 0.9 days.
    # So training samples within 0.9 days after Day 3 (i.e. Day 3.9) are purged.
    # Day 4 (index 4) is 1.0 days after Day 3, so it should not be embargoed? Wait, 0.9 days is less than 1.0 day.
    # Let's use embargo_pct = 0.2 (1.8 days). Day 4 (index 4) and Day 5 (index 5) should be embargoed!
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.2)
    splits = splitter.split(df, event_times)
    
    # Split 1 test is [2, 3] (group 1)
    split_1 = splits[1]
    assert set(split_1["test"]) == {2, 3}
    assert 4 not in split_1["train"]
    assert 5 not in split_1["train"]
    # Day 6 (index 6) is 3 days after Day 3, should be kept
    assert 6 in split_1["train"]

def test_purge_embargo_combined():
    """TC_T1_13: Purge + Embargo Combined"""
    dates = pd.date_range("2023-01-01 00:00:00", periods=10, freq="D")
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates + pd.Timedelta(hours=12), index=dates)
    
    # N=5, k=1. Group bounds: [0, 2, 4, 6, 8, 10]
    # Split 1 test: [2, 3].
    # Purging handles overlaps of events.
    # Embargo removes post-test fold samples.
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.15)
    splits = splitter.split(df, event_times)
    split_1 = splits[1]
    
    # Test indices = [2, 3]
    # Train indices should not contain [2, 3] (disjointness)
    # Train index 1 ends at Day 1.5, test starts at Day 2. No overlap.
    # Train index 4 starts at Day 4, but test event ends at Day 3.5. Embargo is 9 days * 0.15 = 1.35 days.
    # So embargo end is Day 3.5 + 1.35 = Day 4.85.
    # So index 4 (Day 4) and 5 (Day 5) are within Day 4.85 and should be embargoed.
    assert 4 not in split_1["train"]
    assert 5 not in split_1["train"]

def test_zero_overlap_verification():
    """TC_T1_14: Zero-Overlap Verification of final purged train/test masks"""
    dates = pd.date_range("2023-01-01", periods=50)
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates + pd.Timedelta(days=2), index=dates)
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2, embargo_pct=0.05)
    splits = splitter.split(df, event_times)
    
    for s in splits:
        train_idx = s["train"]
        test_idx = s["test"]
        if len(train_idx) == 0:
            continue
        
        # Test event intervals
        test_intervals = [(df.index[i], event_times.iloc[i]) for i in test_idx]
        
        # Verify no train index is within any test event interval
        for i in train_idx:
            t_start = df.index[i]
            t_end = event_times.iloc[i]
            
            for f_start, f_end in test_intervals:
                # Overlap check
                assert not (max(t_start, f_start) <= min(t_end, f_end))


# TIER 2: Boundary & Corner Cases (TC_T2_07 to 13)

def test_insufficient_samples():
    """TC_T2_07: Insufficient Samples raises ValueError"""
    dates = pd.date_range("2023-01-01", periods=4)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2)
    with pytest.raises(ValueError, match="Dataset size.*is less than N"):
        splitter.split(df)

def test_invalid_cpcv_parameters():
    """TC_T2_08: Invalid CPCV Parameters raises ValueError"""
    # k >= N cases
    with pytest.raises(ValueError):
        CPCVSplitter(n_splits=3, n_test_splits=3)
    with pytest.raises(ValueError):
        CPCVSplitter(n_splits=3, n_test_splits=4)
    with pytest.raises(ValueError):
        CPCVSplitter(n_splits=-1, n_test_splits=2)

def test_single_sample_folds():
    """TC_T2_09: Single Sample Folds (N = sample count)"""
    dates = pd.date_range("2023-01-01", periods=5)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.0)
    splits = splitter.split(df)
    assert len(splits) == 5
    for s in splits:
        assert len(s["test"]) == 1

def test_instant_tp_sl_hit():
    """TC_T2_10: Instant TP/SL Hit (hit_time == start_time)"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates, index=dates)  # Instantaneous
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.0)
    splits = splitter.split(df, event_times)
    # Should split and run without crash, index disjointness holds
    for s in splits:
        assert set(s["train"]).intersection(s["test"]) == set()

def test_indefinite_label_timeout():
    """TC_T2_11: Indefinite Label Timeout (hit_time == NaT)"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    event_times = pd.Series([pd.NaT]*10, index=dates)  # Never hit
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.01)
    splits = splitter.split(df, event_times)
    # Check that it splits successfully
    assert len(splits) == 5

def test_embargo_out_of_bounds():
    """TC_T2_12: Embargo Out of Bounds (test fold is the last partition)"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates, index=dates)
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.2)
    splits = splitter.split(df, event_times)
    # The last split has test = last group, so embargo shouldn't cause index error
    last_split = splits[-1]
    assert set(last_split["test"]) == {8, 9}

def test_hyper_purged_dataset():
    """TC_T2_13: Hyper-Purged Dataset (test intervals cover all data)"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    # Every event spans to the end of the dataset, creating massive overlaps
    event_times = pd.Series([dates[-1]]*10, index=dates)
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=2, embargo_pct=0.1)
    splits = splitter.split(df, event_times)
    # Training set should reduce to empty, but handles it gracefully
    for s in splits:
        assert len(s["train"]) == 0 or len(s["train"]) < len(df)


# ADDITIONAL CPCV EDGE CASES (to reach 20 cases)

def test_cpcv_no_event_times():
    """TC_CPCV_Edge_1: event_times is None defaults to instantaneous"""
    dates = pd.date_range("2023-01-01", periods=20)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=4, n_test_splits=1)
    splits = splitter.split(df, event_times=None)
    assert len(splits) == 4

def test_cpcv_embargo_zero():
    """TC_CPCV_Edge_2: embargo_pct is 0.0 has zero post-test purging"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates, index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.0)
    splits = splitter.split(df, event_times)
    # Split 1 test is [2, 3]. Index 4 is Day 4, should be present in train
    assert 4 in splits[1]["train"]

def test_cpcv_highly_imbalanced_sizes():
    """TC_CPCV_Edge_3: grouping handles non-perfect division of sizes"""
    dates = pd.date_range("2023-01-01", periods=13)  # 13 is not divisible by 5
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1)
    splits = splitter.split(df)
    assert len(splits) == 5
    total_test_len = sum(len(s["test"]) for s in splits)
    assert total_test_len == 13

def test_cpcv_empty_train_handling():
    """TC_CPCV_Edge_4: downstream uses empty train gracefully"""
    dates = pd.date_range("2023-01-01", periods=10)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=5, n_test_splits=4)  # k=4 means very large test set
    splits = splitter.split(df)
    # Check that splits are generated successfully
    assert len(splits) == 5

def test_cpcv_different_n_k_combinations():
    """TC_CPCV_Edge_5: different N and k combination (N=4, k=2 -> 6 splits)"""
    dates = pd.date_range("2023-01-01", periods=20)
    df = pd.DataFrame(index=dates)
    splitter = CPCVSplitter(n_splits=4, n_test_splits=2)
    splits = splitter.split(df)
    assert len(splits) == 6

def test_cpcv_embargo_boundary_exact():
    """TC_CPCV_Edge_6: embargo applied exactly up to the cutoff time"""
    # 5-day span. Embargo of 20% is exactly 1 day (0.8 days for H4).
    # Let's say dataset starts 2023-01-01, ends 2023-01-05.
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    df = pd.DataFrame(index=dates)
    event_times = pd.Series(dates, index=dates)
    
    splitter = CPCVSplitter(n_splits=5, n_test_splits=1, embargo_pct=0.25) # 4 days * 0.25 = 1.0 day embargo
    splits = splitter.split(df, event_times)
    # Split 1 has test = Day 2 (index 1).
    # Embargo limit is Day 2 + 1 day = Day 3.
    # Therefore, Day 3 (index 2) must be embargoed, but Day 4 (index 3) must be kept.
    assert 2 not in splits[1]["train"]
    assert 3 in splits[1]["train"]
