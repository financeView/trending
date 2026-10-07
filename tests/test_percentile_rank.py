from scripts.metrics.percentile import scores_0_100


def test_two_distinct_values_are_0_and_100():
    assert scores_0_100([1.0, 2.0]) == [0, 100]


def test_ties_share_average_rank():
    # values 1,2,2 → ranks 1, 2.5, 2.5 → p=0, 0.75, 0.75 → 0, 75, 75
    assert scores_0_100([1.0, 2.0, 2.0]) == [0, 75, 75]


def test_n_le_1_all_null():
    assert scores_0_100([3.0]) == [None]
    assert scores_0_100([]) == []


def test_nulls_excluded_from_peer():
    assert scores_0_100([None, 1.0, 2.0]) == [None, 0, 100]
