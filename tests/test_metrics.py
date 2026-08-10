from line_balancer.models import Operation, Workstation
from line_balancer.metrics import calculate_pitch_time, calculate_tolerance_bands, calculate_line_balancing_rate


def test_pitch_time_basic():
    ops = [Operation(1, "A", [], "M1", 10), Operation(2, "B", [], "M1", 20)]
    assert calculate_pitch_time(ops) == 15.0


def test_pitch_time_with_override_count():
    ops = [Operation(1, "A", [], "M1", 10), Operation(2, "B", [], "M1", 20)]
    # matches factory convention of dividing by total ops incl. untracked ones
    assert calculate_pitch_time(ops, total_operation_count=3) == 10.0


def test_tolerance_bands():
    ucl, lcl = calculate_tolerance_bands(20.0, tolerance=0.15)
    assert round(ucl, 1) == 23.0
    assert round(lcl, 1) == 17.0


def test_line_balancing_rate():
    # Test with balanced workstations (all same SAM)
    ws1 = Workstation([Operation(1, "A", [], "M1", 10)], 1, 10.0)
    ws2 = Workstation([Operation(2, "B", [], "M1", 10)], 1, 10.0)
    assert calculate_line_balancing_rate([ws1, ws2]) == 100.0
    
    # Test with unbalanced workstations
    ws3 = Workstation([Operation(1, "A", [], "M1", 20)], 1, 20.0)
    ws4 = Workstation([Operation(2, "B", [], "M1", 10)], 1, 10.0)
    # maxBalSam = 20, SUM = (20-20) + (20-10) = 10, negativeRate = 10/60 = 0.1667, rate = 100 - 0.1667 = 99.8333
    result = calculate_line_balancing_rate([ws3, ws4])
    assert abs(result - 99.83) < 0.01
