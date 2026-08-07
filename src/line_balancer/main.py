"""
Line Balancing Optimizer - main entry point.
Runs STEP 1 through STEP 7 of the workflow end to end.

Usage:
    python -m line_balancer.main data/sample_operations.csv --total-ops 27 --export report.csv
"""

import argparse
from pathlib import Path
from typing import List, Optional

if __package__ in {None, ""}:
    from balancing import group_and_balance
    from io_utils import read_operations
    from metrics import calculate_line_efficiency, calculate_pitch_time, calculate_tolerance_bands
    from models import Workstation
    from report import build_report_dataframe, export_report, print_summary
    from sequencing import sort_by_predecessor
else:
    from .balancing import group_and_balance
    from .io_utils import read_operations
    from .metrics import calculate_line_efficiency, calculate_pitch_time, calculate_tolerance_bands
    from .models import Workstation
    from .report import build_report_dataframe, export_report, print_summary
    from .sequencing import sort_by_predecessor


def resolve_input_path(input_path: Optional[str] = None) -> str:
    if input_path:
        return input_path

    default_path = Path(__file__).resolve().parents[2] / "data" / "sample_operations.csv"
    return str(default_path)


def run_workflow(
    input_path: Optional[str] = None,
    total_operation_count: Optional[int] = None,
    tolerance: float = 0.15,
    export_path: Optional[str] = None,
) -> dict:
    resolved_input = resolve_input_path(input_path)

    # STEP 1
    raw_operations = read_operations(resolved_input)

    # STEP 2
    sorted_operations = sort_by_predecessor(raw_operations)

    # STEP 3 & 4
    pitch_time = calculate_pitch_time(sorted_operations, total_operation_count)
    ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)

    # STEP 5
    workstations = group_and_balance(sorted_operations, ucl, lcl)

    # STEP 6
    line_efficiency = calculate_line_efficiency(sorted_operations, workstations, pitch_time)

    # STEP 7
    flagged_ops = [op for op in sorted_operations if op.flagged]
    report_df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl)

    print_summary(pitch_time, ucl, lcl, workstations, line_efficiency, flagged_ops)

    if export_path:
        export_report(workstations, export_path)
        print(f"\nReport exported to {export_path}")

    return {
        "input_path": resolved_input,
        "operations": raw_operations,
        "sorted_operations": sorted_operations,
        "pitch_time": pitch_time,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "line_efficiency": line_efficiency,
        "flagged_ops": flagged_ops,
        "report_df": report_df,
    }


def run(
    input_path: Optional[str] = None,
    total_operation_count: Optional[int] = None,
    tolerance: float = 0.15,
    export_path: Optional[str] = None,
) -> List[Workstation]:
    result = run_workflow(
        input_path=input_path,
        total_operation_count=total_operation_count,
        tolerance=tolerance,
        export_path=export_path,
    )
    return result["workstations"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Line Balancing Optimizer")
    parser.add_argument("input", nargs="?", default=None, help="Path to CSV/XLSX with operation data")
    parser.add_argument(
        "--total-ops",
        type=int,
        default=None,
        help="Total operation count including any not listed in the file (e.g. non-stitching ops)",
    )
    parser.add_argument("--tolerance", type=float, default=0.15, help="UCL/LCL tolerance, default 0.15 (15%%)")
    parser.add_argument("--export", type=str, default=None, help="Export report to a CSV or XLSX path")
    args = parser.parse_args()

    run_workflow(
        input_path=args.input,
        total_operation_count=args.total_ops,
        tolerance=args.tolerance,
        export_path=args.export,
    )


if __name__ == "__main__":
    main()
