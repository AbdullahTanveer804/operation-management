from line_balancer.models import Operation
from line_balancer.metrics import calculate_pitch_time, calculate_tolerance_bands


def test_pitch_time_basic():
    ops = [Operation(1, "A", [], "M1", 10), Operation(2, "B", [], "M1", 20)]
    assert calculate_pitch_time(ops) == 15.0


def test_pitch_time_with_override_count():
    ops = [Operation(1, "A", [], "M1", 10), Operation(2, "B", [], "M1", 20)]
    # matches factory convention of dividing by total ops incl. untracked ones
    assert calculate_pitch_time(ops, total_operation_count=3) == 10.0


def test_tolerance_bands():
    ucl, lcl = calculate_tolerance_bands(20.0, tolerance=0.15)
    assert round(ucl, 2) == 23.0
    assert round(lcl, 2) == 17.0
