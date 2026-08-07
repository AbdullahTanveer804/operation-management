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
    assert 17 <= workstations[0].balancing_sam <= 23
