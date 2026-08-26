import unittest
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.line_balancer.models import Operation, Workstation
from src.line_balancer.sequencing import sort_by_id
from src.line_balancer.metrics import (
    calculate_pitch_time_from_target,
    calculate_line_balancing_rate,
    calculate_balance_delay,
    calculate_line_efficiency,
    calculate_smoothing_index,
    calculate_throughput_rate,
    calculate_required_minutes,
)
from src.line_balancer.balancing import group_and_balance
from src.line_balancer.before_balancing_metrics import calculate_all_before_metrics
from src.line_balancer.report import determine_status, build_report_dataframe
from app import calculate_balance, generate_chart_image, generate_before_chart_image

class TestTargetDirectMethod(unittest.TestCase):
    def setUp(self):
        # Sample operations
        self.operations = [
            Operation(op_id=1, name="Sew Collar", basic_time=25.0, machine_type="SNLS", predecessors=[]),
            Operation(op_id=2, name="Attach Collar", basic_time=40.0, machine_type="SNLS", predecessors=[1]),
            Operation(op_id=3, name="Sew Cuff", basic_time=20.0, machine_type="DNLS", predecessors=[]),
            Operation(op_id=4, name="Attach Cuff", basic_time=35.0, machine_type="DNLS", predecessors=[3]),
            Operation(op_id=5, name="Side Seam", basic_time=50.0, machine_type="4T-OL", predecessors=[2, 4]),
            Operation(op_id=6, name="Bottom Hem", basic_time=30.0, machine_type="FOA", predecessors=[5]),
        ]
        self.production_target = 300
        self.shift_time_minutes = 420.0

    def test_takt_time_calculation(self):
        """Test Takt Time derivation: (420 / 300) * 60 = 84.0s."""
        takt_time = calculate_pitch_time_from_target(self.production_target, self.shift_time_minutes)
        self.assertEqual(takt_time, 84.0)

    def test_strict_balancing_no_operation_crosses_takt_time(self):
        """Test that balanced workstations never exceed Takt Time under strict mode."""
        takt_time = calculate_pitch_time_from_target(self.production_target, self.shift_time_minutes)
        sorted_ops = sort_by_id(self.operations)
        workstations = group_and_balance(sorted_ops, takt_time, takt_time, strict=True)
        
        for idx, ws in enumerate(workstations, 1):
            self.assertLessEqual(ws.balancing_sam, takt_time, f"Workstation {idx} SAM {ws.balancing_sam} exceeded Takt Time {takt_time}")

    def test_calculate_balance_engine_target_direct(self):
        """Test calculate_balance engine with target_direct method."""
        result = calculate_balance(
            operations=self.operations,
            production_target=self.production_target,
            shift_time_minutes=self.shift_time_minutes,
            pitch_time_method="target_direct"
        )
        
        # 1. Constant metrics
        self.assertEqual(result["production_target"], 300)
        self.assertEqual(result["shift_time_minutes"], 420.0)
        self.assertAlmostEqual(result["total_basic_time"], 200.0 / 60.0, places=4)
        self.assertEqual(result["pitch_time"], 84.0)
        self.assertEqual(result["pitch_time_source"], "By Target Direct")
        self.assertIsNone(result["ucl"])
        self.assertIsNone(result["lcl"])
        self.assertNotIn("tolerance", result)
        
        # 2. Comparison metrics
        before_metrics = result["before_metrics"]
        self.assertEqual(before_metrics["pitch_time_source"], "By Target Direct")
        self.assertEqual(before_metrics["num_operations"], 6)
        self.assertEqual(before_metrics["total_manpower"], 6)
        self.assertIsNotNone(before_metrics["labour_productivity"])
        self.assertIsNotNone(before_metrics["line_efficiency"])
        self.assertIsNotNone(before_metrics["throughput_rate"])
        self.assertIsNotNone(before_metrics["required_minutes"])
        self.assertIsNotNone(before_metrics["balancing_rate"])
        self.assertIsNotNone(before_metrics["balance_delay"])
        self.assertIsNotNone(before_metrics["smoothing_index"])
        
        # After metrics
        self.assertIsNotNone(result["line_balancing_rate"])
        self.assertIsNotNone(result["balance_delay"])
        self.assertIsNotNone(result["line_efficiency"])
        self.assertIsNotNone(result["smoothing_index"])
        self.assertIsNotNone(result["throughput_rate"])
        self.assertIsNotNone(result["required_minutes"])
        self.assertIsNotNone(result["labour_productivity_after"])
        
        # 3. Report dataframe
        df = result["report_df"]
        self.assertIn("Takt Time", df.columns)
        self.assertNotIn("Pitch Time", df.columns)
        self.assertNotIn("UCL", df.columns)
        self.assertNotIn("LCL", df.columns)
        
        # Check Status values
        for status in df["Status"]:
            self.assertIn(status, ["< Takt Time", "> Takt Time"])

    def test_status_determination(self):
        """Test status strings for By Target Direct."""
        status_ok = determine_status(80.0, 84.0, 84.0, pitch_time_source="By Target Direct")
        self.assertEqual(status_ok, "< Takt Time")
        status_exceed = determine_status(90.0, 84.0, 84.0, pitch_time_source="By Target Direct")
        self.assertEqual(status_exceed, "> Takt Time")

    def test_chart_generation_target_direct(self):
        """Test that charts generate without error for By Target Direct."""
        result = calculate_balance(
            operations=self.operations,
            production_target=self.production_target,
            shift_time_minutes=self.shift_time_minutes,
            pitch_time_method="target_direct"
        )
        before_buf = generate_before_chart_image(
            operations=result["sorted_operations"],
            pitch_time=result["pitch_time"],
            ucl=result["ucl"],
            lcl=result["lcl"],
            pitch_time_source=result["pitch_time_source"]
        )
        self.assertIsNotNone(before_buf)
        self.assertGreater(len(before_buf.getvalue()), 0)
        
        after_buf = generate_chart_image(
            workstations=result["workstations"],
            pitch_time=result["pitch_time"],
            ucl=result["ucl"],
            lcl=result["lcl"],
            pitch_time_source=result["pitch_time_source"]
        )
        self.assertIsNotNone(after_buf)
        self.assertGreater(len(after_buf.getvalue()), 0)

if __name__ == "__main__":
    unittest.main()
