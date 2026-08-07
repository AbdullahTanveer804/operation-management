from line_balancer.models import Operation
from line_balancer.sequencing import sort_by_predecessor


def test_sorts_by_predecessor_chain():
    ops = [
        Operation(1, "A", [], "M1", 10),
        Operation(2, "B", [1], "M1", 10),
        Operation(3, "C", [2], "M1", 10),
    ]
    result = sort_by_predecessor(ops)
    assert [op.op_id for op in result] == [1, 2, 3]


def test_handles_multiple_predecessors():
    ops = [
        Operation(1, "A", [], "M1", 10),
        Operation(2, "B", [], "M1", 10),
        Operation(3, "C", [1, 2], "M1", 10),
    ]
    result = sort_by_predecessor(ops)
    assert result[-1].op_id == 3


def test_flags_unresolved_predecessor():
    ops = [
        Operation(1, "A", [99], "M1", 10),  # predecessor 99 doesn't exist
    ]
    result = sort_by_predecessor(ops)
    assert result[0].flagged == "Unresolved Predecessor"
