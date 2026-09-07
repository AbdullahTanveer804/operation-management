"""
Line Balancing — Pitch Time (Auto) for Composite Machines

This module implements the "Pitch Time (Auto)" balancing method for cross-machine-type
(composite) operations.

Core Algorithm & Rules:
1. Reuses same-machine Auto algorithm:
   - Pitch Time calculation = Total Basic Time / Operation Count
   - UCL / LCL tolerance bands = Pitch Time +/- (Pitch Time * tolerance) [default +/-15%]
   - Divide-and-increment manpower split logic (find_best_manpower_split)
2. Merging eligibility across DIFFERENT machine types (composite):
   - Any regular machine type can combine with any other machine type
   - Regular helper-machines (By Hand, Pointer, Pencil, Clipper) can combine with any machine
   - SPECIAL RULE — "Press" machine restriction:
     * "Press" can ONLY combine with: Press (itself), By Hand, Pointer, Pencil, Clipper
       (other helper-type machines)
     * "Press" must NEVER combine with any regular sewing/stitching machine (SNLS, 3TOL, 5TOL,
       Overlock, Flatlock, etc.)
   - Predecessor dependency constraint is strictly respected (an operation cannot precede
     its unassigned predecessor)
3. Output contract:
   - Matches standard balancing output contract exactly:
     Workstation / Composite Operations, Serial/Id, Operations, Machine, Predecessor,
     Basic Time, Combined Basic Time, Combined SAM, Balancing SAM, M/P, Pitch Time,
     UCL, LCL, Status.
"""

import argparse
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    file_path = Path(__file__).resolve()
    project_root = file_path.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

try:
    from .models import Operation, Workstation
    from .sequencing import sort_by_id
    from .balancing import is_within_range, find_best_manpower_split
    from .balancing_by_composite_machines import (
        can_combine_composite_machines,
        check_predecessor_constraint,
        is_press_machine,
        is_helper_machine,
        PRESS_COMPATIBLE_HELPERS,
    )
    from .metrics import (
        calculate_pitch_time,
        calculate_tolerance_bands,
        calculate_line_balancing_rate,
        calculate_balance_delay,
        calculate_line_efficiency,
        calculate_smoothing_index,
    )
    from .report import determine_status
    from .io_utils import read_operations
except ImportError:
    from src.line_balancer.models import Operation, Workstation
    from src.line_balancer.sequencing import sort_by_id
    from src.line_balancer.balancing import is_within_range, find_best_manpower_split
    from src.line_balancer.balancing_by_composite_machines import (
        can_combine_composite_machines,
        check_predecessor_constraint,
        is_press_machine,
        is_helper_machine,
        PRESS_COMPATIBLE_HELPERS,
    )
    from src.line_balancer.metrics import (
        calculate_pitch_time,
        calculate_tolerance_bands,
        calculate_line_balancing_rate,
        calculate_balance_delay,
        calculate_line_efficiency,
        calculate_smoothing_index,
    )
    from src.line_balancer.report import determine_status
    from src.line_balancer.io_utils import read_operations


def find_compatible_composite_operations(
    current_op: Operation,
    all_operations: List[Operation],
    already_grouped_ids: Set[int],
) -> List[Operation]:
    """
    Find all operations eligible to merge with current_op under composite rules.
    
    Eligibility criteria:
    1. Not the current operation itself
    2. Not already assigned to a workstation
    3. Machine types compatible under centralized composite rules (including Press restriction)
    4. Predecessor constraints fully satisfied
    """
    compatible = []
    for other_op in all_operations:
        if other_op.op_id == current_op.op_id:
            continue
        if other_op.op_id in already_grouped_ids:
            continue
        if not can_combine_composite_machines(current_op.machine_type, other_op.machine_type):
            continue
        if check_predecessor_constraint(current_op, other_op, already_grouped_ids):
            compatible.append(other_op)
    return compatible


def group_and_balance_auto_composite(
    sorted_operations: List[Operation],
    ucl: float,
    lcl: float,
    strict: bool = False,
) -> List[Workstation]:
    """
    Core auto balancing algorithm for Composite Machines.
    
    Reuses the exact same-machine Auto method logic, allowing cross-machine merges:
    1. For each operation in ID order:
       - Check if its basic time falls within [LCL, UCL].
         If YES: create standalone workstation with M/P = 1.
       - If NO: search all compatible composite candidates (subject to predecessor
         constraints and Press machine restriction).
         * If valid candidates exist whose combined SAM falls within [LCL, UCL], pick
           the Best-Fit candidate (closest to target pitch, tie-break op_id) with M/P = 1.
         * If no candidate combined SAM falls within [LCL, UCL] but compatible ops exist,
           take the first compatible op and split combined time across 2..n operators
           using find_best_manpower_split.
         * If no compatible op exists at all, split current op alone across 2..n operators
           using find_best_manpower_split.
    """
    workstations: List[Workstation] = []
    already_grouped_ids: Set[int] = set()

    target_pitch = (ucl + lcl) / 2.0 if (ucl is not None and lcl is not None) else (ucl if ucl is not None else lcl)

    for current_op in sorted_operations:
        if current_op.op_id in already_grouped_ids:
            continue

        # ===== STEP 1: Check if operation is already within acceptable range =====
        if is_within_range(current_op.basic_time, ucl, lcl, strict=strict):
            ws = Workstation(
                operations=[current_op],
                manpower=1,
                balancing_sam=current_op.basic_time,
            )
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)
            continue

        # ===== STEP 2: Find compatible composite operations =====
        compatible_ops = find_compatible_composite_operations(
            current_op, sorted_operations, already_grouped_ids
        )

        if compatible_ops:
            # ===== STEP 3a: Search for Best-Fit candidate within [LCL, UCL] =====
            valid_candidates = []
            for partner_op in compatible_ops:
                combined_time = current_op.basic_time + partner_op.basic_time
                if is_within_range(combined_time, ucl, lcl, strict=strict):
                    diff = abs(combined_time - target_pitch) if target_pitch is not None else 0.0
                    valid_candidates.append((diff, partner_op.op_id, partner_op, combined_time))

            if valid_candidates:
                # Best-Fit match closest to target pitch
                valid_candidates.sort(key=lambda x: (x[0], x[1]))
                _, _, best_partner, best_combined_time = valid_candidates[0]
                ws = Workstation(
                    operations=[current_op, best_partner],
                    manpower=1,
                    balancing_sam=best_combined_time,
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(best_partner.op_id)
            else:
                # Combined time still outside band: take first compatible op and split
                partner_op = compatible_ops[0]
                combined_time = current_op.basic_time + partner_op.basic_time
                manpower, balancing_sam = find_best_manpower_split(
                    combined_time, ucl, lcl, strict=strict
                )
                ws = Workstation(
                    operations=[current_op, partner_op],
                    manpower=manpower,
                    balancing_sam=balancing_sam,
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(partner_op.op_id)
        else:
            # ===== STEP 3b: Standalone split path =====
            manpower, balancing_sam = find_best_manpower_split(
                current_op.basic_time, ucl, lcl, strict=strict
            )
            ws = Workstation(
                operations=[current_op],
                manpower=manpower,
                balancing_sam=balancing_sam,
            )
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)

    return workstations


# Alias for backward/drop-in naming compatibility
group_and_balance = group_and_balance_auto_composite


def build_auto_composite_report_dataframe(
    workstations: List[Workstation],
    pitch_time: float,
    ucl: float,
    lcl: float,
) -> pd.DataFrame:
    """
    Build standard report DataFrame matching standard balancing output contract.
    
    Includes both 'Combined Basic Time' and 'Combined SAM' for complete drop-in
    compatibility with any consumers or downstream aggregators.
    """
    rows = []
    for ws_num, ws in enumerate(workstations, start=1):
        op_ids = " + ".join(str(op.op_id) for op in ws.operations)
        op_names = " + ".join(op.name for op in ws.operations)
        basic_times = " + ".join(f"{op.basic_time:.1f}" for op in ws.operations)
        machine_types = " + ".join(op.machine_type for op in ws.operations)

        op_predecessor_groups = []
        for op in ws.operations:
            if op.predecessors:
                op_preds = ", ".join(str(p) for p in sorted(op.predecessors))
                op_predecessor_groups.append(op_preds)
        predecessors = "+".join(op_predecessor_groups) if op_predecessor_groups else "-"

        combined_basic_time = ws.combined_basic_time
        status = determine_status(ws.balancing_sam, ucl, lcl, pitch_time_source="calculated")

        row = {
            "Composite Operations": int(ws_num),
            "Serial/Id": op_ids,
            "Operations": op_names,
            "Machine": machine_types,
            "Predecessor": predecessors,
            "Basic Time": basic_times,
            "Combined Basic Time": round(combined_basic_time, 1),
            "Combined SAM": round(combined_basic_time, 1),
            "Balancing SAM": round(ws.balancing_sam, 1),
            "M/P": ws.manpower,
            "Pitch Time": round(pitch_time, 1) if pitch_time is not None else "",
            "UCL": round(ucl, 1) if ucl is not None else "",
            "LCL": round(lcl, 1) if lcl is not None else "",
            "Status": status,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["Composite Operations"] = df["Composite Operations"].astype(int)
    return df


def calculate_auto_composite_balancing(
    operations: List[Operation],
    tolerance: float = 0.15,
    strict: bool = False,
    production_target: Optional[int] = None,
    shift_time_minutes: Optional[float] = None,
) -> Dict:
    """
    Main entry point for Pitch Time (Auto) balancing of Composite Machines.
    
    Calculates auto Pitch Time, UCL/LCL bands, groups and balances workstations,
    and computes all standard balancing metrics and report rows.
    Optionally computes target, takt time, and efficiency KPIs when production_target
    and shift_time_minutes are provided.
    """
    if not operations:
        raise ValueError("Operations list cannot be empty.")

    sorted_ops = sort_by_id(operations)
    pitch_time = calculate_pitch_time(sorted_ops)
    ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)

    workstations = group_and_balance_auto_composite(sorted_ops, ucl, lcl, strict=strict)

    line_balancing_rate = calculate_line_balancing_rate(workstations)
    balance_delay = calculate_balance_delay(workstations, sorted_ops)
    smoothing_index = calculate_smoothing_index(workstations)
    total_basic_time_sam = sum(op.basic_time for op in sorted_ops)
    total_mp = sum(ws.manpower for ws in workstations)
    cycle_time = max(ws.balancing_sam for ws in workstations) if workstations else 0.0

    takt_time = None
    line_efficiency = None
    achievable_output = None
    labour_productivity = None
    demand_met = None

    if production_target is not None and shift_time_minutes is not None:
        if production_target > 0 and shift_time_minutes > 0:
            available_time_seconds = shift_time_minutes * 60.0
            takt_time = available_time_seconds / production_target
            line_efficiency = calculate_line_efficiency(
                workstations, sorted_ops, production_target, shift_time_minutes
            )
            achievable_output = (
                available_time_seconds / cycle_time if cycle_time > 0 else 0.0
            )
            labour_productivity = (
                achievable_output / total_mp if total_mp > 0 else 0.0
            )
            demand_met = cycle_time <= takt_time

    report_df = build_auto_composite_report_dataframe(workstations, pitch_time, ucl, lcl)
    rows = report_df.to_dict(orient="records")

    formatted_rows = []
    for r in rows:
        formatted = dict(r)
        if isinstance(formatted.get("Combined Basic Time"), (int, float)):
            formatted["Combined Basic Time"] = f"{formatted['Combined Basic Time']:.1f}"
        if isinstance(formatted.get("Combined SAM"), (int, float)):
            formatted["Combined SAM"] = f"{formatted['Combined SAM']:.1f}"
        if isinstance(formatted.get("Balancing SAM"), (int, float)):
            formatted["Balancing SAM"] = f"{formatted['Balancing SAM']:.1f}"
        if isinstance(formatted.get("Pitch Time"), (int, float)):
            formatted["Pitch Time"] = f"{formatted['Pitch Time']:.1f}"
        if isinstance(formatted.get("UCL"), (int, float)):
            formatted["UCL"] = f"{formatted['UCL']:.1f}"
        if isinstance(formatted.get("LCL"), (int, float)):
            formatted["LCL"] = f"{formatted['LCL']:.1f}"
        formatted_rows.append(formatted)

    statuses = [r["Status"] for r in rows]
    review_flag_count = sum(1 for s in statuses if "review" in s.lower() or "> UCL" in s)

    return {
        "operations": operations,
        "sorted_operations": sorted_ops,
        "pitch_time": pitch_time,
        "pitch_time_source": "calculated",
        "tolerance": tolerance,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "num_workstations": len(workstations),
        "total_manpower": total_mp,
        "total_basic_time": total_basic_time_sam,
        "total_basic_time_minutes": total_basic_time_sam / 60.0,
        "cycle_time": cycle_time,
        "line_balancing_rate": line_balancing_rate,
        "balance_delay": balance_delay,
        "smoothing_index": smoothing_index,
        "production_target": production_target,
        "shift_time_minutes": shift_time_minutes,
        "takt_time": takt_time,
        "line_efficiency": line_efficiency,
        "achievable_output": achievable_output,
        "labour_productivity": labour_productivity,
        "demand_met": demand_met,
        "report_df": report_df,
        "rows": rows,
        "formatted_rows": formatted_rows,
        "statuses": statuses,
        "review_flag_count": review_flag_count,
    }


def print_cli_results(result: Dict, filepath: str) -> None:
    """Print formatted CLI results for Pitch Time (Auto) Composite Balancing."""
    sep = "=" * 110
    subsep = "-" * 110

    total_sam = result["total_basic_time"]
    pitch_time = result["pitch_time"]
    ucl = result["ucl"]
    lcl = result["lcl"]
    demand = result.get("production_target")
    shift_mins = result.get("shift_time_minutes")
    takt_time = result.get("takt_time")

    print("\n" + sep)
    print("  LINE BALANCING — PITCH TIME (AUTO) FOR COMPOSITE MACHINES  ".center(110))
    print(sep)
    print(f"  Input File        : {filepath}")
    if demand is not None:
        print(f"  Customer Demand   : {demand} units")
    if shift_mins is not None:
        print(f"  Available Time    : {shift_mins} minutes ({shift_mins * 60:.0f} seconds)")
    if takt_time is not None:
        print(f"  Customer Takt     : {takt_time:.1f} seconds")
    print(f"  Total Basic SAM   : {total_sam:.1f} seconds ({total_sam / 60.0:.2f} minutes)")
    print(f"  Calculated Pitch  : {pitch_time:.1f} seconds  [LCL = {lcl:.1f}s, UCL = {ucl:.1f}s (tolerance = {result['tolerance'] * 100:.0f}%)]")
    print("  Rules Applied     : Cross-machine composite merging allowed")
    print("                      * Press restricted: can ONLY combine with helper machines or itself")
    print(sep)

    print("\n" + subsep)
    print(f"  BALANCED WORKSTATIONS TABLE (Total Stations: {result['num_workstations']} | Total Manpower: {result['total_manpower']})  ")
    print(subsep)

    df = result["report_df"]
    # Reorder/select columns for clean display
    display_cols = [
        "Composite Operations",
        "Serial/Id",
        "Operations",
        "Machine",
        "Basic Time",
        "Combined SAM",
        "Balancing SAM",
        "M/P",
        "Pitch Time",
        "UCL",
        "LCL",
        "Status",
    ]
    cols_to_use = [c for c in display_cols if c in df.columns]
    display_df = df[cols_to_use]

    if HAS_TABULATE:
        print(tabulate(display_df, headers="keys", tablefmt="grid", showindex=False))
    else:
        print(display_df.to_string(index=False))

    print("\n" + subsep)
    print("  SUMMARY PERFORMANCE METRICS  ")
    print(subsep)
    print(f"  - Total Operations        : {len(result['sorted_operations'])}")
    print(f"  - Total Workstations      : {result['num_workstations']}")
    print(f"  - Total Manpower (M/P)    : {result['total_manpower']}")
    print(f"  - Cycle Time (Bottleneck) : {result['cycle_time']:.1f} seconds")
    print(f"  - Line Balancing Rate     : {result['line_balancing_rate']:.2f}%")
    print(f"  - Balance Delay           : {result['balance_delay']:.2f}%")
    print(f"  - Smoothing Index         : {result['smoothing_index']:.4f}")
    if result.get("line_efficiency") is not None:
        print(f"  - Line Efficiency         : {result['line_efficiency']:.2f}%")
    if result.get("achievable_output") is not None:
        print(f"  - Achievable Output       : {result['achievable_output']:.1f} units")
    if result.get("labour_productivity") is not None:
        print(f"  - Labour Productivity     : {result['labour_productivity']:.2f} units/operator")
    if result.get("demand_met") is not None:
        status_msg = "MET (Cycle Time <= Takt Time)" if result["demand_met"] else "NOT MET (Cycle Time > Takt Time)"
        print(f"  - Demand Satisfaction     : {status_msg}")
    print(sep + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Line Balancing — Pitch Time (Auto) for Composite Machines"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default="data/Input2.xlsx",
        help="Path to operations input file (CSV/Excel). Default: data/Input2.xlsx",
    )
    parser.add_argument(
        "--demand",
        "-d",
        type=int,
        default=350,
        help="Customer demand target units. Default: 350",
    )
    parser.add_argument(
        "--available-time",
        "-t",
        type=float,
        default=420.0,
        help="Available time in minutes. Default: 420",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.15,
        help="Tolerance band fraction (e.g. 0.15 for +/-15%%). Default: 0.15",
    )

    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        repo_root = Path(__file__).resolve().parent.parent.parent
        alt_path = repo_root / args.file
        if alt_path.exists():
            filepath = alt_path
        else:
            print(f"Error: Input file '{args.file}' not found.")
            sys.exit(1)

    print(f"Reading operations from '{filepath}'...")
    operations = read_operations(str(filepath))
    flagged = [op for op in operations if op.flagged]
    if flagged:
        print(f"Warning: Found {len(flagged)} flagged operations:")
        for op in flagged:
            print(f"  - Op {op.op_id} ({op.name}): {op.flagged}")

    results = calculate_auto_composite_balancing(
        operations=operations,
        tolerance=args.tolerance,
        production_target=args.demand,
        shift_time_minutes=args.available_time,
    )

    print_cli_results(results, str(filepath))


if __name__ == "__main__":
    main()

