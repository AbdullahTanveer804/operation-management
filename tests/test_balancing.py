from line_balancer.models import Operation
from line_balancer.balancing import group_and_balance, is_within_range


def test_is_within_range():
    assert is_within_range(20, ucl=23, lcl=17) is True
    assert is_within_range(25, ucl=23, lcl=17) is False


def test_op_within_band_stays_standalone():
    ops = [Operation(1, "A", [], "M1", 20)]
    workstations = group_and_balance(ops, ucl=23, lcl=17)
    assert len(workstations) == 1
    assert workstations[0].manpower == 1


def test_oversized_op_gets_split():
    ops = [Operation(1, "A", [], "M1", 60)]
    workstations = group_and_balance(ops, ucl=23, lcl=17)
    assert workstations[0].manpower > 1
    # New logic: should be at or below UCL + 0.5, even if below LCL
    assert workstations[0].balancing_sam <= 23.5


def test_combined_time_above_ucl_gets_split():
    """Test the specific case: combined time 36.8 with UCL 32.1 should split to M/P=2"""
    from line_balancer.balancing import find_best_manpower_split
    
    # Test the exact scenario: combined time 36.8, UCL 32.1
    manpower, balancing_sam = find_best_manpower_split(36.8, ucl=32.1, lcl=20.0)
    
    # Should split to 2 operators since 36.8 > 32.1 + 0.5 = 32.6
    assert manpower == 2, f"Expected manpower == 2, got {manpower}"
    # Resulting time should be at or below UCL + 0.5
    assert balancing_sam <= 32.6, f"Expected balancing_sam <= 32.6, got {balancing_sam}"
    # Resulting time should be 36.8 / 2 = 18.4
    assert abs(balancing_sam - 18.4) < 0.01, f"Expected balancing_sam ≈ 18.4, got {balancing_sam}"


def test_combined_time_above_ucl_high_lcl():
    """Test when split goes below LCL - should still split to reduce from above UCL"""
    from line_balancer.balancing import find_best_manpower_split
    
    # Test with higher LCL where 36.8/2 = 18.4 might be below LCL
    manpower, balancing_sam = find_best_manpower_split(36.8, ucl=32.1, lcl=19.0)
    
    # Should still split since 36.8 > 32.1 + 0.5 = 32.6, even if 18.4 < 19.0 (below LCL)
    assert manpower == 2, f"Expected manpower == 2, got {manpower}"
    # Resulting time should be at or below UCL + 0.5 (priority over LCL)
    assert balancing_sam <= 32.6, f"Expected balancing_sam <= 32.6, got {balancing_sam}"
    # Resulting time should be 18.4 even though it's below LCL of 19.0
    assert abs(balancing_sam - 18.4) < 0.01, f"Expected balancing_sam ≈ 18.4, got {balancing_sam}"


def test_within_flexibility_range_no_split():
    """Test that times within UCL + 0.5 don't get split"""
    from line_balancer.balancing import find_best_manpower_split
    
    # Test time that's above UCL but within flexibility range
    # UCL = 32.1, so UCL + 0.5 = 32.6
    # Time = 32.4 should NOT split since 32.4 <= 32.6
    manpower, balancing_sam = find_best_manpower_split(32.4, ucl=32.1, lcl=20.0)
    
    # Should NOT split since it's within the 0.5 second flexibility
    assert manpower == 1, f"Expected manpower == 1 (no split), got {manpower}"
    # Should return original time unchanged
    assert abs(balancing_sam - 32.4) < 0.01, f"Expected balancing_sam ≈ 32.4, got {balancing_sam}"
