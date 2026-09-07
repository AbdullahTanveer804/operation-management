"""
Unit and integration tests for Pitch Time (Auto) with Composite Machines
(src/line_balancer/balancing_auto_composite_machines.py)
"""

import pytest
from src.line_balancer.models import Operation, Workstation
from src.line_balancer.balancing_auto_composite_machines import (
    can_combine_composite_machines,
    find_compatible_composite_operations,
    group_and_balance_auto_composite,
    build_auto_composite_report_dataframe,
    calculate_auto_composite_balancing,
)
from src.line_balancer.metrics import calculate_pitch_time, calculate_tolerance_bands


# ==============================================================================
# 1. Centralized Press Restriction & Machine Compatibility Tests
# ==============================================================================

def test_press_restriction_centralized():
    """
    Deliverable requirement:
    Confirm the Press restriction is centralized in one compatibility check function,
    with a test case showing Press correctly rejecting a merge with a sewing machine
    and accepting one with By Hand.
    """
    # Press must REJECT all regular sewing/stitching machines
    assert can_combine_composite_machines("Press", "SNLS") is False
    assert can_combine_composite_machines("SNLS", "Press") is False
    assert can_combine_composite_machines("Press", "3TOL") is False
    assert can_combine_composite_machines("3TOL", "Press") is False
    assert can_combine_composite_machines("Press", "5TOL") is False
    assert can_combine_composite_machines("Press", "Overlock") is False
    assert can_combine_composite_machines("Press", "Flatlock") is False
    assert can_combine_composite_machines("Iron Press", "SNLS") is False

    # Press must ACCEPT other helper machines and itself
    assert can_combine_composite_machines("Press", "By Hand") is True
    assert can_combine_composite_machines("By Hand", "Press") is True
    assert can_combine_composite_machines("Press", "Pointer") is True
    assert can_combine_composite_machines("Pointer", "Press") is True
    assert can_combine_composite_machines("Press", "Pencil") is True
    assert can_combine_composite_machines("Press", "Clipper") is True
    assert can_combine_composite_machines("Press", "Press") is True
    assert can_combine_composite_machines("Iron Press", "Press") is True
    assert can_combine_composite_machines("Iron Press", "By Hand") is True

    # Other helper machines retain unrestricted compatibility with any machine
    assert can_combine_composite_machines("By Hand", "SNLS") is True
    assert can_combine_composite_machines("Pointer", "3TOL") is True
    assert can_combine_composite_machines("Pencil", "Overlock") is True
    assert can_combine_composite_machines("Clipper", "Flatlock") is True

    # Non-press regular machines can combine with each other (composite capability)
    assert can_combine_composite_machines("SNLS", "3TOL") is True
    assert can_combine_composite_machines("3TOL", "5TOL") is True
    assert can_combine_composite_machines("Overlock", "Flatlock") is True


# ==============================================================================
# 2. Composite Auto Balancing Core Algorithm Tests
# ==============================================================================

def test_composite_auto_merges_different_machines():
    """
    Verify cross-machine merging in auto pitch time mode:
    Op 1 (SNLS, 20s) and Op 2 (3TOL, 30s) should merge into one workstation
    when their combined time (50s) is within [LCL, UCL].
    """
    ops = [
        Operation(op_id=1, name="Op 1", predecessors=[], machine_type="SNLS", basic_time=20.0),
        Operation(op_id=2, name="Op 2", predecessors=[1], machine_type="3TOL", basic_time=30.0),
    ]
    # Pitch time = 25.0, but let's test with UCL=55, LCL=45
    ucl = 55.0
    lcl = 45.0
    workstations = group_and_balance_auto_composite(ops, ucl=ucl, lcl=lcl)

    assert len(workstations) == 1
    assert len(workstations[0].operations) == 2
    assert workstations[0].operations[0].op_id == 1
    assert workstations[0].operations[1].op_id == 2
    assert workstations[0].balancing_sam == 50.0
    assert workstations[0].manpower == 1


def test_composite_auto_rejects_press_sewing_merge_in_balancing():
    """
    Even when combined time fits perfectly within [LCL, UCL],
    Press must NOT merge with a sewing machine.
    """
    ops = [
        Operation(op_id=1, name="Press Op", predecessors=[], machine_type="Press", basic_time=25.0),
        Operation(op_id=2, name="Sewing Op", predecessors=[], machine_type="SNLS", basic_time=25.0),
    ]
    ucl = 55.0
    lcl = 45.0  # Combined = 50.0 which would fit in range [45, 55]

    workstations = group_and_balance_auto_composite(ops, ucl=ucl, lcl=lcl)

    # Must NOT combine because Press cannot merge with SNLS
    assert len(workstations) == 2
    assert len(workstations[0].operations) == 1
    assert workstations[0].operations[0].op_id == 1
    assert len(workstations[1].operations) == 1
    assert workstations[1].operations[0].op_id == 2


def test_composite_auto_accepts_press_by_hand_merge_in_balancing():
    """
    Press CAN merge with By Hand when combined time fits within [LCL, UCL].
    """
    ops = [
        Operation(op_id=1, name="Press Op", predecessors=[], machine_type="Press", basic_time=25.0),
        Operation(op_id=2, name="Hand Op", predecessors=[], machine_type="By Hand", basic_time=25.0),
    ]
    ucl = 55.0
    lcl = 45.0  # Combined = 50.0 fits in range [45, 55]

    workstations = group_and_balance_auto_composite(ops, ucl=ucl, lcl=lcl)

    assert len(workstations) == 1
    assert len(workstations[0].operations) == 2
    assert workstations[0].operations[0].op_id == 1
    assert workstations[0].operations[1].op_id == 2
    assert workstations[0].balancing_sam == 50.0


def test_composite_auto_respects_predecessor_constraints():
    """
    Operations cannot merge if predecessor dependency is violated.
    """
    ops = [
        Operation(op_id=1, name="Op 1", predecessors=[], machine_type="SNLS", basic_time=20.0),
        Operation(op_id=2, name="Op 2", predecessors=[1], machine_type="3TOL", basic_time=20.0),
        Operation(op_id=3, name="Op 3", predecessors=[2], machine_type="5TOL", basic_time=30.0),
    ]
    ucl = 55.0
    lcl = 45.0

    # Op 1 (20) + Op 3 (30) = 50 would fit, but Op 3 depends on Op 2 which is not grouped yet.
    workstations = group_and_balance_auto_composite(ops, ucl=ucl, lcl=lcl)

    # Op 1 cannot combine with Op 3 ahead of Op 2
    # Check that Op 1 and Op 3 are not together in the first workstation
    first_ws_ids = {op.op_id for op in workstations[0].operations}
    assert 3 not in first_ws_ids


# ==============================================================================
# 3. Output Contract Tests
# ==============================================================================

def test_output_contract_field_names_and_shapes():
    """
    Deliverable requirement:
    Confirm output field names match the standard contract exactly:
    rows with Combined Basic Time, Combined SAM, Balancing SAM, M/P, UCL/LCL, Status, etc.
    """
    ops = [
        Operation(op_id=1, name="Collar Join", predecessors=[], machine_type="SNLS", basic_time=22.0),
        Operation(op_id=2, name="Overlock Edge", predecessors=[1], machine_type="3TOL", basic_time=28.0),
        Operation(op_id=3, name="Iron Pressing", predecessors=[2], machine_type="Press", basic_time=25.0),
        Operation(op_id=4, name="Thread Trim", predecessors=[3], machine_type="By Hand", basic_time=24.0),
    ]

    result = calculate_auto_composite_balancing(ops, tolerance=0.15)

    # Verify top-level result contract
    assert "operations" in result
    assert "sorted_operations" in result
    assert "pitch_time" in result
    assert "pitch_time_source" in result
    assert result["pitch_time_source"] == "calculated"
    assert "tolerance" in result
    assert result["tolerance"] == 0.15
    assert "ucl" in result
    assert "lcl" in result
    assert "workstations" in result
    assert "num_workstations" in result
    assert "total_manpower" in result
    assert "total_basic_time" in result
    assert "total_basic_time_minutes" in result
    assert "line_balancing_rate" in result
    assert "balance_delay" in result
    assert "smoothing_index" in result
    assert "report_df" in result
    assert "rows" in result
    assert "formatted_rows" in result
    assert "statuses" in result

    # Check rows contract
    rows = result["rows"]
    assert len(rows) > 0

    required_contract_fields = [
        "Composite Operations",
        "Serial/Id",
        "Operations",
        "Machine",
        "Predecessor",
        "Basic Time",
        "Combined Basic Time",
        "Combined SAM",
        "Balancing SAM",
        "M/P",
        "Pitch Time",
        "UCL",
        "LCL",
        "Status",
    ]

    for row in rows:
        for field in required_contract_fields:
            assert field in row, f"Missing required contract field: '{field}' in row: {row}"

        # Check types
        assert isinstance(row["Composite Operations"], int)
        assert isinstance(row["M/P"], int)
        assert isinstance(row["Combined Basic Time"], (int, float))
        assert isinstance(row["Combined SAM"], (int, float))
        assert isinstance(row["Balancing SAM"], (int, float))
        assert isinstance(row["Status"], str)
        # Combined Basic Time and Combined SAM must match
        assert row["Combined Basic Time"] == row["Combined SAM"]

    # Check formatted rows contract
    for frow in result["formatted_rows"]:
        for field in required_contract_fields:
            assert field in frow
        assert isinstance(frow["Combined Basic Time"], str)
        assert isinstance(frow["Combined SAM"], str)
        assert isinstance(frow["Balancing SAM"], str)

