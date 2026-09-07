"""
Unit and integration tests for Line Balancing by Composite Machines
"""

import pytest
from src.line_balancer.models import Operation
from src.line_balancer.balancing_by_composite_machines import (
    can_combine_composite_machines,
    check_predecessor_constraint,
    is_press_machine,
    balance_composite_method_a_takt,
    balance_composite_method_b_pitch,
    calculate_composite_takt_vs_pitch_comparison,
)
from src.line_balancer.io_utils import read_operations


def test_is_press_machine():
    assert is_press_machine("Press") is True
    assert is_press_machine("press") is True
    assert is_press_machine("Iron Press") is True
    assert is_press_machine("Steam Press Machine") is True
    assert is_press_machine("SNLS") is False
    assert is_press_machine("3TOL") is False
    assert is_press_machine("By Hand") is False
    assert is_press_machine("") is False


def test_can_combine_composite_machines():
    # Press can combine with Press and helper-machines
    assert can_combine_composite_machines("Press", "Press") is True
    assert can_combine_composite_machines("Iron Press", "Press") is True
    assert can_combine_composite_machines("Press", "By Hand") is True
    assert can_combine_composite_machines("By Hand", "Press") is True
    assert can_combine_composite_machines("Press", "Pointer") is True
    assert can_combine_composite_machines("Press", "Pencil") is True
    assert can_combine_composite_machines("Press", "Clipper") is True

    # Press CANNOT combine with regular machines
    assert can_combine_composite_machines("Press", "SNLS") is False
    assert can_combine_composite_machines("SNLS", "Press") is False
    assert can_combine_composite_machines("Press", "3TOL") is False
    assert can_combine_composite_machines("Press", "Overlock") is False
    assert can_combine_composite_machines("Press", "Flatlock") is False

    # Any non-press machine can combine with any other non-press machine
    assert can_combine_composite_machines("SNLS", "SNLS") is True
    assert can_combine_composite_machines("SNLS", "3TOL") is True
    assert can_combine_composite_machines("3TOL", "5TOL") is True
    assert can_combine_composite_machines("SNLS", "By Hand") is True
    assert can_combine_composite_machines("SNLS(Charcoal)", "SNLS") is True
    assert can_combine_composite_machines("Pointer", "5TOL") is True


def test_check_predecessor_constraint():
    op1 = Operation(op_id=1, name="Op 1", predecessors=[], machine_type="SNLS", basic_time=20.0)
    op2 = Operation(op_id=2, name="Op 2", predecessors=[1], machine_type="3TOL", basic_time=25.0)
    op3 = Operation(op_id=3, name="Op 3", predecessors=[2], machine_type="5TOL", basic_time=30.0)

    # Op 1 and Op 2 can combine because Op 2's predecessor is Op 1 itself
    assert check_predecessor_constraint(op1, op2, set()) is True

    # Op 1 and Op 3 cannot combine yet because Op 2 has not been grouped
    assert check_predecessor_constraint(op1, op3, set()) is False

    # If Op 2 is already grouped, Op 1 and Op 3 can combine
    assert check_predecessor_constraint(op1, op3, {2}) is True


def test_composite_balancing_method_a():
    ops = [
        # Op 1 (SNLS) and Op 2 (3TOL) can merge across machine types: 20 + 30 = 50 <= 60
        Operation(op_id=1, name="Op 1", predecessors=[], machine_type="SNLS", basic_time=20.0),
        Operation(op_id=2, name="Op 2", predecessors=[1], machine_type="3TOL", basic_time=30.0),
        # Op 3 (Press, 25s) - cannot merge with Op 4 (SNLS, 20s)
        Operation(op_id=3, name="Op 3", predecessors=[2], machine_type="Press", basic_time=25.0),
        Operation(op_id=4, name="Op 4", predecessors=[3], machine_type="SNLS", basic_time=20.0),
    ]
    takt_time = 60.0

    workstations = balance_composite_method_a_takt(ops, takt_time)

    assert len(workstations) == 3
    # WS 1: Op 1 (SNLS) + Op 2 (3TOL)
    assert len(workstations[0].operations) == 2
    assert workstations[0].operations[0].op_id == 1
    assert workstations[0].operations[1].op_id == 2
    assert workstations[0].balancing_sam == 50.0

    # WS 2: Op 3 (Press) standalone
    assert len(workstations[1].operations) == 1
    assert workstations[1].operations[0].op_id == 3
    assert workstations[1].balancing_sam == 25.0

    # WS 3: Op 4 (SNLS) standalone
    assert len(workstations[2].operations) == 1
    assert workstations[2].operations[0].op_id == 4
    assert workstations[2].balancing_sam == 20.0


def test_composite_balancing_with_input2():
    ops = read_operations("data/Input2.xlsx")
    assert len(ops) == 27

    res = calculate_composite_takt_vs_pitch_comparison(
        operations=ops,
        shift_time_minutes=420.0,
        production_target=350,
    )

    assert res["takt_time"] == 72.0
    assert len(res["comparison"]) == 8

    # Verify Method A has fewer stations due to composite pairing than original
    ws_a = res["method_a"]["workstations"]
    assert len(ws_a) == 15

    # Verify Op 7 (Press) is strictly standalone
    press_ws = [ws for ws in ws_a if any(is_press_machine(op.machine_type) for op in ws.operations)]
    assert len(press_ws) == 1
    assert len(press_ws[0].operations) == 1
    assert press_ws[0].operations[0].op_id == 7

    # Verify Method B runs and produces valid workstations and statuses
    ws_b = res["method_b"]["workstations"]
    assert len(ws_b) == 24
    assert len(res["method_b"]["statuses"]) == 24


def test_composite_balancing_press_with_helper():
    ops = [
        # Op 1 (Press, 25s) and Op 2 (By Hand, 20s) can merge: 25 + 20 = 45 <= 60
        Operation(op_id=1, name="Press Op", predecessors=[], machine_type="Press", basic_time=25.0),
        Operation(op_id=2, name="Hand Op", predecessors=[1], machine_type="By Hand", basic_time=20.0),
    ]
    takt_time = 60.0
    workstations = balance_composite_method_a_takt(ops, takt_time)

    assert len(workstations) == 1
    assert len(workstations[0].operations) == 2
    assert workstations[0].operations[0].op_id == 1
    assert workstations[0].operations[1].op_id == 2
    assert workstations[0].balancing_sam == 45.0


