import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.line_balancer.balancing import find_best_manpower_split, group_and_balance
from src.line_balancer.models import Operation
from src.line_balancer.main import run_workflow


def test_find_best_manpower_split_auto_vs_strict():
    # Case: Time is 15.3s, Target is 15.0s
    # In Auto mode (strict=False), 0.5s relaxation is allowed (15.3 <= 15.0 + 0.5 = 15.5) -> 1 operator
    mp_auto, time_auto = find_best_manpower_split(15.3, 15.0, 15.0, strict=False)
    assert mp_auto == 1
    assert time_auto == 15.3

    # In Manual/Target mode (strict=True), NO 0.5s relaxation is allowed (15.3 > 15.0) -> splits into 2 operators
    mp_strict, time_strict = find_best_manpower_split(15.3, 15.0, 15.0, strict=True)
    assert mp_strict == 2
    assert round(time_strict, 2) == 7.65


def test_find_best_manpower_split_exact():
    # When time is exact 15.0s and target is 15.0s, 1 operator is sufficient in strict mode
    mp_exact, time_exact = find_best_manpower_split(15.0, 15.0, 15.0, strict=True)
    assert mp_exact == 1
    assert time_exact == 15.0


def test_workflow_manual_exact_takt_time():
    # In Manual method with takt time 20.0s, every workstation balancing_sam must be <= 20.0s
    res_manual = run_workflow('data/sample_operations.csv', pitch_time_method='manual', manual_pitch_time=20.0)
    assert res_manual['pitch_time'] == 20.0
    assert res_manual['ucl'] is None
    assert res_manual['lcl'] is None
    for ws in res_manual['workstations']:
        assert ws.balancing_sam <= 20.0 + 1e-6, f"Workstation {ws.operations} exceeded exact takt time: {ws.balancing_sam} > 20.0"


def test_workflow_target_workflow():
    import pytest
    # In By Target method with production_target=1000 and shift_time=480 min (Takt = 28.8s)
    res_target = run_workflow('data/sample_operations.csv', pitch_time_method='target', production_target=1000, shift_time_minutes=480)
    takt_time = res_target['pitch_time']
    assert takt_time == pytest.approx(28.8)
    assert res_target['pitch_time_source'] == "By Target"
    # After Fix 1: ucl and lcl should now be populated with auto-computed values
    assert res_target['ucl'] is not None
    assert res_target['lcl'] is not None
    # Verify these are the auto-computed values (around 32.1 and 23.8 based on the sample data)
    assert res_target['ucl'] == pytest.approx(32.1, rel=0.01)  # auto_pitch_time * 1.15
    assert res_target['lcl'] == pytest.approx(23.8, rel=0.01)  # auto_pitch_time * 0.85
    assert 'demand_met' in res_target
    assert 'target_validation_message' in res_target
    assert 'target_recheck_messages' in res_target


if __name__ == "__main__":
    test_find_best_manpower_split_auto_vs_strict()
    print("[OK] test_find_best_manpower_split_auto_vs_strict passed")
    test_find_best_manpower_split_exact()
    print("[OK] test_find_best_manpower_split_exact passed")
    test_workflow_manual_exact_takt_time()
    print("[OK] test_workflow_manual_exact_takt_time passed")
    test_workflow_target_workflow()
    print("[OK] test_workflow_target_workflow passed")
    print("\nALL STRICT BALANCING TESTS PASSED!")
