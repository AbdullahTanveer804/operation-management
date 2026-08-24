"""
STEP 7: Generate Output Report

Creates a formatted report showing all workstations with:
- Which operations are grouped together
- The times, manpower, and balancing rate metrics
- Status flags for workstations outside acceptable ranges
"""

from typing import List

import pandas as pd

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation


def determine_status(balancing_sam: float, ucl: float, lcl: float) -> str:
    """
    Determine the status of a workstation based on its balancing SAM.
    
    Args:
        balancing_sam: The balanced time per operator
        ucl: Upper Control Limit (or target time for manual/target methods)
        lcl: Lower Control Limit (or target time for manual/target methods)
    
    Returns:
        Status string: "OK", "> UCL (review)", or "< LCL (review)"
        For manual/target methods, returns "OK" if within 10% of target
    """
    if ucl is None or lcl is None:
        # For manual/target methods, use target (ucl) and allow 10% flexibility
        target = ucl if ucl is not None else lcl
        if target is None:
            return "OK"  # No constraints
        if balancing_sam > target * 1.1:
            return "> Target (review)"
        else:
            return "OK"
    
    if balancing_sam > ucl:
        return "> UCL (review)"
    elif balancing_sam < lcl:
        return "< LCL (review)"
    else:
        return "OK"


def build_report_dataframe(workstations: List[Workstation], ucl: float = None, lcl: float = None, pitch_time: float = None, pitch_time_source: str = "calculated") -> pd.DataFrame:
    """
    Build a DataFrame report with all workstations and their details.
    
    The output format has these columns (in order):
    1. Workstation - Workstation number
    2. Serial/Id - Operation IDs joined with " + " for combined (e.g., "5 + 9")
    3. Operations - Operation names joined with " + " for combined
    4. Machine - Machine types joined with " + " for combined (e.g., "M1 + M2")
    5. Predecessor - Predecessor IDs joined with " + " for combined (e.g., "1 + 18")
    6. Basic Time - Individual basic times joined with " + " for combined
    7. Pitch Time / Takt Time - Constant pitch/takt time value (repeated for each row)
    8. UCL - Constant Upper Control Limit value (repeated for each row) - ONLY for auto method
    9. LCL - Constant Lower Control Limit value (repeated for each row) - ONLY for auto method
    10. Combined Basic Time - Total time for the workstation
    11. M/P - Manpower needed
    12. Balancing SAM - Time per operator after balancing
    13. Status - OK / > UCL / < LCL / > Target
    
    Args:
        workstations: List of Workstation objects
        ucl: Upper Control Limit (optional, for status determination and column - only for auto method)
        lcl: Lower Control Limit (optional, for status determination and column - only for auto method)
        pitch_time: Pitch time (optional, for column)
        pitch_time_source: Source of pitch time calculation ("manual", "By Target", or "calculated")
    
    Returns:
        DataFrame with formatted report data
    """
    rows = []
    
    # Determine column name based on pitch time source
    if pitch_time_source == "manual" or pitch_time_source == "By Target":
        pitch_time_column_name = "Takt Time"
    else:
        pitch_time_column_name = "Pitch Time"
    
    # Check if UCL/LCL should be included (only for auto method)
    include_ucl_lcl = (pitch_time_source == "calculated")
    
    for ws_num, ws in enumerate(workstations, start=1):
        # Build combined representations using " + " as separator
        op_ids = " + ".join(str(op.op_id) for op in ws.operations)
        op_names = " + ".join(op.name for op in ws.operations)
        basic_times = " + ".join(f"{op.basic_time:.1f}" for op in ws.operations)
        
        # Build combined machine types
        machine_types = " + ".join(op.machine_type for op in ws.operations)
        
        # Build combined predecessors (collect all predecessors from all operations)
        # Format: "1 + 18" for single op, or "19, 17 + 20" for multiple ops
        op_predecessor_groups = []
        for op in ws.operations:
            if op.predecessors:
                # Sort and join this operation's predecessors with " + "
                op_preds = ", ".join(str(p) for p in sorted(op.predecessors))
                op_predecessor_groups.append(op_preds)
        # Join different operation predecessor groups with ", "
        predecessors = "+".join(op_predecessor_groups) if op_predecessor_groups else "-"
        
        # Combined basic time (sum of all operations in this workstation)
        combined_basic_time = ws.combined_basic_time
        
        # Determine status
        status = "OK"
        if include_ucl_lcl and ucl is not None and lcl is not None:
            status = determine_status(ws.balancing_sam, ucl, lcl)
        elif not include_ucl_lcl:
            # For manual/target methods, use pitch_time as target
            status = determine_status(ws.balancing_sam, pitch_time, pitch_time)
        
        # Build row dictionary
        row = {
            "Composite Operations": int(ws_num),  # Ensure workstation number is stored as integer
            "Serial/Id": op_ids,
            "Operations": op_names,
            "Machine": machine_types,
            "Predecessor": predecessors,
            "Basic Time": basic_times,
            "Combined Basic Time": round(combined_basic_time, 1),
            "Balancing SAM": round(ws.balancing_sam, 1),
            "M/P": ws.manpower,
            pitch_time_column_name: round(pitch_time, 1) if pitch_time is not None else "",
            "Status": status,
        }
        
        # Only add UCL/LCL columns for auto method
        if include_ucl_lcl:
            row["UCL"] = round(ucl, 1) if ucl is not None else ""
            row["LCL"] = round(lcl, 1) if lcl is not None else ""
        
        rows.append(row)
    
    df = pd.DataFrame(rows)
    # Ensure Workstation column is integer type
    df['Composite Operations'] = df['Composite Operations'].astype(int)
    return df


def print_summary(
    pitch_time: float,
    ucl: float,
    lcl: float,
    workstations: List[Workstation],
    line_balancing_rate: float,
    flagged_ops: List[Operation],
    operations: List[Operation],
    balance_delay: float = None,
    line_efficiency: float = None,
    pitch_time_source: str = "calculated",
    smoothing_index: float = None,
    tolerance: float = 0.15,
    production_target: int = None,
    shift_time_minutes: float = None,
) -> None:
    """
    Print a summary of the balancing results to the console.
    
    Shows metrics in the specified order:
    1. Production Target (If available)
    2. Shift Time (If available)
    3. No. of Composite operations
    4. Total Basic Time (SAM)
    5. Line Efficiency%
    6. Total ManPower
    7. Pitch Time / Takt Time (based on method)
    8. Tolerance
    9. UCL
    10. LCL
    11. Balancing Rate
    12. Balance Delay
    13. Smoothing Index
    - Any flagged operations that had errors
    
    Args:
        pitch_time: The calculated pitch time
        ucl: Upper Control Limit
        lcl: Lower Control Limit
        workstations: List of balanced workstations
        line_balancing_rate: Calculated balancing rate percentage
        flagged_ops: List of operations with errors
        operations: List of all operations (for total basic time calculation)
        balance_delay: Optional balance delay percentage
        line_efficiency: Optional line efficiency percentage
        pitch_time_source: Source of pitch time calculation ("manual", "By Target", or "calculated")
        smoothing_index: Optional smoothing index in minutes
        tolerance: Tolerance percentage (default 0.15 for 15%)
        production_target: Optional production target
        shift_time_minutes: Optional shift time in minutes
    """
    df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl, pitch_time=pitch_time, pitch_time_source=pitch_time_source)
    
    print("\n" + "=" * 120)
    print("LINE BALANCING RESULTS")
    print("=" * 120)
    print(df.to_string(index=False))
    print("-" * 120)
    
    # Print metrics in the specified order
    if production_target is not None:
        print(f"Production Target: {production_target} units")
    if shift_time_minutes is not None:
        print(f"Shift Time: {shift_time_minutes:.1f} minutes")
    print(f"No. of Composite operations: {len(workstations)}")
    print(f"Total Basic Time (SAM): {sum(op.basic_time for op in operations) / 60:.1f} min")
    if line_efficiency is not None:
        print(f"Line Efficiency%: {line_efficiency:.1f}%")
    print(f"Total ManPower: {sum(ws.manpower for ws in workstations)}")
    # Determine display name based on pitch time source
    if pitch_time_source == "manual" or pitch_time_source == "By Target":
        time_display_name = "Takt Time"
    else:
        time_display_name = "Pitch Time"
    print(f"{time_display_name}: {pitch_time:.1f}s ({pitch_time_source})")
    # Only show tolerance and UCL/LCL for auto method
    if pitch_time_source == "calculated":
        if tolerance != 0.15:
            print(f"Tolerance (Manual): {tolerance * 100:.1f}%")
        else:
            print(f"Tolerance: {tolerance * 100:.1f}%")
        print(f"UCL: {ucl:.1f}s")
        print(f"LCL: {lcl:.1f}s")
    print(f"Balancing Rate: {line_balancing_rate:.1f}%")
    if balance_delay is not None:
        print(f"Balance Delay: {balance_delay:.1f}%")
    if smoothing_index is not None:
        print(f"Smoothing Index: {smoothing_index:.2f} min")
    print("=" * 120)
    
    # Show any flagged operations
    if flagged_ops:
        print("\n⚠️  FLAGGED OPERATIONS (please review):")
        for op in flagged_ops:
            print(f"  - Operation {op.op_id}: {op.name}")
            print(f"    Error: {op.flagged}")


def export_report(workstations: List[Workstation], filepath: str, pitch_time: float = None, ucl: float = None, lcl: float = None, pitch_time_source: str = "calculated") -> None:
    """
    Export the report to an Excel file.
    
    Note: The column name will be "Takt Time" for manual/target methods, "Pitch Time" for auto.
    
    Args:
        workstations: List of Workstation objects
        filepath: Where to save the file (must end in .xlsx)
        pitch_time: Pitch time value (optional, for column)
        ucl: Upper Control Limit (optional, for column)
        lcl: Lower Control Limit (optional, for column)
        pitch_time_source: Source of pitch time calculation ("manual", "By Target", or "calculated")
    """
    df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl, pitch_time=pitch_time, pitch_time_source=pitch_time_source)
    
    if filepath.lower().endswith(".xlsx"):
        df.to_excel(filepath, index=False)
    else:
        raise ValueError("Export format must be .xlsx")
