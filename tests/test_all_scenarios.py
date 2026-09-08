"""
Unit and integration tests for All-Scenarios Aggregator
(src/line_balancer/all_scenarios.py)
"""

import pytest
from src.line_balancer.models import Operation
from src.line_balancer.io_utils import read_operations
from src.line_balancer.all_scenarios import (
    run_all_scenarios,
    adapt_composite_result,
    normalize_scenario_rows,
    compute_kpis_from_workstations,
)


@pytest.fixture
def sample_ops():
    return [
        Operation(op_id=1, name="Waist Pocket Hem", predecessors=[], machine_type="SNLS", basic_time=15.0),
        Operation(op_id=2, name="Waist Pocket Hem With Loop", predecessors=[], machine_type="SNLS", basic_time=25.0),
        Operation(op_id=3, name="Moon & Fashion O/L", predecessors=[1], machine_type="3TOL", basic_time=30.0),
        Operation(op_id=4, name="Waist Pockets Press", predecessors=[2], machine_type="Press", basic_time=20.0),
        Operation(op_id=5, name="Thread Trim", predecessors=[3, 4], machine_type="By Hand", basic_time=10.0),
    ]


def test_run_all_scenarios_presence_of_7_keys(sample_ops):
    """
    Deliverable requirement (2):
    Sample run showing all 7 scenario keys present with populated KPI values.
    """
    res = run_all_scenarios(sample_ops, shift_time_minutes=420.0, production_target=350, tolerance=0.15)

    expected_scenarios = [
        "before",
        "takt_same",
        "pitch_same",
        "takt_composite",
        "pitch_composite",
        "auto_same",
        "auto_composite",
    ]

    # Verify scenario order
    assert res["scenario_order"] == expected_scenarios

    # Verify top-level scenario keys
    for sid in expected_scenarios:
        assert sid in res, f"Scenario key '{sid}' missing from top-level result"
        assert sid in res["scenarios"], f"Scenario key '{sid}' missing from res['scenarios']"

        sc = res[sid]
        assert "rows" in sc
        assert "kpis" in sc
        assert "formatted_kpis" in sc
        assert "reference_lines" in sc
        assert "workstations" in sc

        # Check all 8 KPIs are present and positive
        kpis = sc["kpis"]
        for kpi in [
            "num_workstations",
            "total_manpower",
            "cycle_time",
            "achievable_output",
            "efficiency",
            "balancing_delay",
            "smoothing_index",
            "labour_productivity",
        ]:
            assert kpi in kpis, f"KPI '{kpi}' missing from scenario '{sid}'"
            assert isinstance(kpis[kpi], (int, float)), f"KPI '{kpi}' in '{sid}' is not numeric"
            assert kpis[kpi] >= 0, f"KPI '{kpi}' in '{sid}' is negative"


def test_shared_parameters_computed_once(sample_ops):
    """
    Deliverable requirement (3):
    Confirm the shared baseline block is computed once, not per scenario.
    """
    res = run_all_scenarios(sample_ops, shift_time_minutes=420.0, production_target=350, tolerance=0.15)

    assert "shared_parameters" in res
    sp = res["shared_parameters"]

    expected_total_sam = sum(op.basic_time for op in sample_ops)  # 15+25+30+20+10 = 100.0
    expected_takt = (420.0 * 60.0) / 350  # 72.0s
    expected_pitch = expected_total_sam / 5  # 20.0s

    assert sp["customer_demand"] == 350
    assert sp["available_time_minutes"] == 420.0
    assert sp["available_time_seconds"] == 25200.0
    assert sp["total_sam"] == pytest.approx(expected_total_sam)
    assert sp["num_operations"] == 5
    assert sp["takt_time"] == pytest.approx(expected_takt)
    assert sp["pitch_time"] == pytest.approx(expected_pitch)
    assert sp["ucl"] == pytest.approx(expected_pitch * 1.15)
    assert sp["lcl"] == pytest.approx(expected_pitch * 0.85)


def test_all_scenarios_standard_row_contract(sample_ops):
    """
    Ensure every scenario's workstation rows expose the exact standard field set.
    """
    res = run_all_scenarios(sample_ops, shift_time_minutes=420.0, production_target=350, tolerance=0.15)

    required_fields = [
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
        "Takt Time",
        "UCL",
        "LCL",
        "Status",
    ]

    for sid, sc in res["scenarios"].items():
        assert len(sc["rows"]) > 0, f"Scenario '{sid}' has no rows"
        for row in sc["rows"]:
            for field in required_fields:
                assert field in row, f"Field '{field}' missing from row in scenario '{sid}': {row}"
            # Combined Basic Time and Combined SAM must match
            assert row["Combined Basic Time"] == row["Combined SAM"]


def test_comparison_table_structure(sample_ops):
    """
    Verify side-by-side comparison table has 8 headline KPIs.
    """
    res = run_all_scenarios(sample_ops, shift_time_minutes=420.0, production_target=350, tolerance=0.15)

    assert "comparison_table" in res
    ct = res["comparison_table"]
    assert len(ct) == 8

    kpi_keys = [
        "num_workstations",
        "total_manpower",
        "cycle_time",
        "achievable_output",
        "efficiency",
        "balancing_delay",
        "smoothing_index",
        "labour_productivity",
    ]

    for item, expected_key in zip(ct, kpi_keys):
        assert item["key"] == expected_key
        assert "best_scenario" in item
        for sid in res["scenario_order"]:
            assert sid in item
            assert f"formatted_{sid}" in item


def test_real_dataset_run():
    """
    Integration test using data/Input2.xlsx.
    """
    ops = read_operations("data/Input2.xlsx")
    res = run_all_scenarios(ops, shift_time_minutes=420.0, production_target=350, tolerance=0.15)

    assert res["shared_parameters"]["num_operations"] == 27
    assert len(res["scenarios"]) == 7

    # Check each scenario produces valid results
    for sid in res["scenario_order"]:
        sc = res[sid]
        assert sc["kpis"]["total_manpower"] > 0
        assert sc["kpis"]["cycle_time"] > 0
        assert sc["kpis"]["achievable_output"] > 0
        assert sc["kpis"]["efficiency"] > 0
        assert len(sc["rows"]) > 0

