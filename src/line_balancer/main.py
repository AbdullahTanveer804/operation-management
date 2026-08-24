"""
Line Balancing Optimizer - main entry point.
Runs STEP 1 through STEP 7 of the workflow end to end.

Usage:
    python -m line_balancer.main data/sample_operations.csv --export report.xlsx
"""

import argparse
from pathlib import Path
from typing import List, Optional

if __package__ in {None, ""}:
    from balancing import group_and_balance
    from io_utils import read_operations
    from metrics import calculate_line_balancing_rate, calculate_pitch_time, calculate_pitch_time_from_target, calculate_tolerance_bands, calculate_balance_delay, calculate_line_efficiency, calculate_smoothing_index
    from models import Workstation
    from report import build_report_dataframe, export_report, print_summary
    from sequencing import sort_by_id
else:
    from .balancing import group_and_balance
    from .io_utils import read_operations
    from .metrics import calculate_line_balancing_rate, calculate_pitch_time, calculate_pitch_time_from_target, calculate_tolerance_bands, calculate_balance_delay, calculate_line_efficiency, calculate_smoothing_index
    from .models import Workstation
    from .report import build_report_dataframe, export_report, print_summary
    from .sequencing import sort_by_id


def resolve_input_path(input_path: Optional[str] = None) -> str:
    if input_path:
        return input_path

    default_path = Path(__file__).resolve().parents[2] / "data" / "sample_operations.csv"
    return str(default_path)


def run_workflow(
    input_path: Optional[str] = None,
    tolerance: float = 0.15,
    export_path: Optional[str] = None,
    production_target: Optional[int] = None,
    shift_time_minutes: Optional[float] = None,
    pitch_time_method: str = "auto",
    manual_pitch_time: Optional[float] = None,
) -> dict:
    resolved_input = resolve_input_path(input_path)

    # STEP 1: Read operations from file
    raw_operations = read_operations(resolved_input)

    # STEP 2: Sort operations by Serial No. / ID (ascending)
    sorted_operations = sort_by_id(raw_operations)

    # STEP 3 & 4: Calculate Pitch Time / Takt Time and balance based on method
    demand_met = None
    target_validation_message = None
    target_recheck_messages = []
    target_recheck_summary = None

    if pitch_time_method == "manual":
        if manual_pitch_time is None or manual_pitch_time <= 0:
            raise ValueError("Manual pitch time must be provided and positive when method is 'manual'.")
        pitch_time = manual_pitch_time
        pitch_time_source = "manual"
        # Clear target-related parameters for manual method
        production_target = None
        shift_time_minutes = None
        # No tolerance bands for manual method
        ucl = None
        lcl = None
        # STEP 5: Balance operations into workstations
        workstations = group_and_balance(sorted_operations, pitch_time, pitch_time, strict=True)
    elif pitch_time_method == "target":
        if production_target is None or production_target <= 0:
            raise ValueError("Production target must be provided and positive when method is 'target'.")
        if shift_time_minutes is None or shift_time_minutes <= 0:
            raise ValueError("Shift time must be provided and positive when method is 'target'.")
        
        # Step 1 — Derive Takt Time from By-Target input
        takt_time = calculate_pitch_time_from_target(production_target, shift_time_minutes)
        pitch_time = takt_time
        pitch_time_source = "By Target"
        ucl = None
        lcl = None

        # Step 2 — Validate BEFORE balancing
        max_sam = max(op.basic_time for op in sorted_operations) if sorted_operations else 0.0
        if max_sam > takt_time:
            demand_met = False
            target_validation_message = "Max basic time (SAM) exceeds Takt Time — customer demand target is NOT currently met."
        else:
            demand_met = True
            target_validation_message = "Max basic time (SAM) is within Takt Time — customer demand target is met."

        # Step 3 — Balance the line using Pitch Time Auto logic
        auto_pitch_time = calculate_pitch_time(sorted_operations)
        auto_ucl, auto_lcl = calculate_tolerance_bands(auto_pitch_time, tolerance if tolerance is not None else 0.15)
        workstations = group_and_balance(sorted_operations, auto_ucl, auto_lcl)

        # Step 4 — Recheck balanced result against Takt Time, loop until it passes or safety cap is hit
        attempt = 1
        MAX_ATTEMPTS = 5
        target_recheck_messages = []

        while attempt <= MAX_ATTEMPTS:
            recheck_max_sam = max(ws.balancing_sam for ws in workstations) if workstations else 0.0
            if recheck_max_sam <= takt_time:
                target_recheck_messages.append("Balancing OK — result satisfies Takt Time.")
                target_recheck_summary = f"Balancing OK — result satisfies Takt Time (Attempt {attempt})."
                break
            else:
                target_recheck_messages.append(f"Balancing not OK (attempt {attempt}) — re-balancing required.")
                workstations = group_and_balance(sorted_operations, auto_ucl, auto_lcl)
                attempt += 1

        if attempt > MAX_ATTEMPTS:
            target_recheck_messages.append(f"Unable to fully satisfy Takt Time after {MAX_ATTEMPTS} balancing attempts — showing best achieved result.")
            target_recheck_summary = f"Unable to fully satisfy Takt Time after {MAX_ATTEMPTS} balancing attempts — showing best achieved result."
    else:  # auto (default)
        pitch_time = calculate_pitch_time(sorted_operations)
        pitch_time_source = "calculated"
        # Clear target-related parameters for auto method
        production_target = None
        shift_time_minutes = None
        # Calculate tolerance bands for auto method
        ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)
        # STEP 5: Balance operations into workstations
        workstations = group_and_balance(sorted_operations, ucl, lcl)

    # STEP 6: Calculate line balancing rate
    line_balancing_rate = calculate_line_balancing_rate(workstations)

    # STEP 6.5: Calculate balance delay
    balance_delay = calculate_balance_delay(workstations, sorted_operations)

    # STEP 6.6: Calculate line efficiency (if production target and shift time provided and method is target)
    line_efficiency = None
    if pitch_time_method == "target" and production_target is not None and shift_time_minutes is not None:
        line_efficiency = calculate_line_efficiency(workstations, sorted_operations, production_target, shift_time_minutes)

    # STEP 6.7: Calculate smoothing index
    smoothing_index = calculate_smoothing_index(workstations)

    # STEP 7: Build report
    flagged_ops = [op for op in sorted_operations if op.flagged]
    report_df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl, pitch_time=pitch_time, pitch_time_source=pitch_time_source)

    print_summary(pitch_time, ucl, lcl, workstations, line_balancing_rate, flagged_ops, sorted_operations, balance_delay, line_efficiency, pitch_time_source, smoothing_index, tolerance, production_target, shift_time_minutes)

    if export_path:
        export_report(workstations, export_path, pitch_time=pitch_time, ucl=ucl, lcl=lcl, pitch_time_source=pitch_time_source)
        print(f"\nReport exported to {export_path}")

    return {
        "input_path": resolved_input,
        "operations": raw_operations,
        "sorted_operations": sorted_operations,
        "pitch_time": pitch_time,
        "pitch_time_source": pitch_time_source,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "line_balancing_rate": line_balancing_rate,
        "balance_delay": balance_delay,
        "line_efficiency": line_efficiency,
        "smoothing_index": smoothing_index,
        "flagged_ops": flagged_ops,
        "report_df": report_df,
        "demand_met": demand_met,
        "target_validation_message": target_validation_message,
        "target_recheck_messages": target_recheck_messages,
        "target_recheck_summary": target_recheck_summary,
    }


def run(
    input_path: Optional[str] = None,
    tolerance: float = 0.15,
    export_path: Optional[str] = None,
    production_target: Optional[int] = None,
    shift_time_minutes: Optional[float] = None,
    pitch_time_method: str = "auto",
    manual_pitch_time: Optional[float] = None,
) -> List[Workstation]:
    result = run_workflow(
        input_path=input_path,
        tolerance=tolerance,
        export_path=export_path,
        production_target=production_target,
        shift_time_minutes=shift_time_minutes,
        pitch_time_method=pitch_time_method,
        manual_pitch_time=manual_pitch_time,
    )
    return result["workstations"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Line Balancing Optimizer")
    parser.add_argument("input", nargs="?", default=None, help="Path to CSV/XLSX with operation data")
    parser.add_argument("--tolerance", type=float, default=0.15, help="UCL/LCL tolerance, default 0.15 (15%%)")
    parser.add_argument("--export", type=str, default=None, help="Export report to a XLSX path")
    parser.add_argument("--production-target", type=int, default=None, help="Production target (number of units) for line efficiency calculation and pitch time calculation")
    parser.add_argument("--shift-time", type=float, default=None, help="Shift time in minutes for line efficiency calculation and pitch time calculation")
    parser.add_argument("--pitch-time-method", type=str, default="auto", choices=["auto", "manual", "target"], help="Method for calculating pitch time: auto (from file), manual (input), target (from production target)")
    parser.add_argument("--pitch-time", type=float, default=None, help="Manual pitch time (required when --pitch-time-method is manual)")
    args = parser.parse_args()

    run_workflow(
        input_path=args.input,
        tolerance=args.tolerance,
        export_path=args.export,
        production_target=args.production_target,
        shift_time_minutes=args.shift_time,
        pitch_time_method=args.pitch_time_method,
        manual_pitch_time=args.pitch_time,
    )


if __name__ == "__main__":
    main()
