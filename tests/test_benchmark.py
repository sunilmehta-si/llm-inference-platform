from scripts.benchmark import percentile


def test_percentile_interpolates_and_handles_empty_data():
    assert percentile([], 0.95) is None
    assert percentile([5], 0.95) == 5
    assert percentile([1, 3], 0.5) == 2
