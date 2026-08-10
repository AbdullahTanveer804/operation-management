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
        ucl: Upper Control Limit
        lcl: Lower Control Limit
    
    Returns:
        Status string: "OK", "> UCL (review)", or "< LCL (review)"
    """
    if balancing_sam > ucl:
        return "> UCL (review)"
    elif balancing_sam < lcl:
        return "< LCL (review)"
    else:
        return "OK"


def build_report_dataframe(workstations: List[Workstation], ucl: float = None, lcl: float = None) -> pd.DataFrame:
    """
    Build a DataFrame report with all workstations and their details.
    
    The output format has these columns (in order):
    1. Workstation - Workstation number
    2. Serial/Id - Operation IDs joined with " + " for combined (e.g., "5 + 9")
    3. Operations - Operation names joined with " + " for combined
    4. Basic Time - Individual basic times joined with " + " for combined
    5. Combined Basic Time - Total time for the workstation
    6. M/P - Manpower needed
    7. Balancing SAM - Time per operator after balancing
    8. Status - OK / > UCL / < LCL
    
    Args:
        workstations: List of Workstation objects
        ucl: Upper Control Limit (optional, for status determination)
        lcl: Lower Control Limit (optional, for status determination)
    
    Returns:
        DataFrame with formatted report data
    """
    rows = []
    
    for ws_num, ws in enumerate(workstations, start=1):
        # Build combined representations using " + " as separator
        op_ids = " + ".join(str(op.op_id) for op in ws.operations)
        op_names = " + ".join(op.name for op in ws.operations)
        basic_times = " + ".join(f"{op.basic_time:.1f}" for op in ws.operations)
        
        # Combined basic time (sum of all operations in this workstation)
        combined_basic_time = ws.combined_basic_time
        
        # Determine status
        status = "OK"
        if ucl is not None and lcl is not None:
            status = determine_status(ws.balancing_sam, ucl, lcl)
        
        # Add row to report
        rows.append({
            "Workstation": ws_num,
            "Serial/Id": op_ids,
            "Operations": op_names,
            "Basic Time": basic_times,
            "Combined Basic Time": round(combined_basic_time, 1),
            "M/P": ws.manpower,
            "Balancing SAM": round(ws.balancing_sam, 1),
            "Status": status,
        })
    
    return pd.DataFrame(rows)


def print_summary(
    pitch_time: float,
    ucl: float,
    lcl: float,
    workstations: List[Workstation],
    line_balancing_rate: float,
    flagged_ops: List[Operation],
) -> None:
    """
    Print a summary of the balancing results to the console.
    
    Shows:
    - The calculated metrics (Pitch Time, UCL, LCL)
    - Summary counts (workstations, total manpower)
    - Line balancing rate
    - Any flagged operations that had errors
    
    Args:
        pitch_time: The calculated pitch time
        ucl: Upper Control Limit
        lcl: Lower Control Limit
        workstations: List of balanced workstations
        line_balancing_rate: Calculated balancing rate percentage
        flagged_ops: List of operations with errors
    """
    df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl)
    
    print("\n" + "=" * 120)
    print("LINE BALANCING RESULTS")
    print("=" * 120)
    print(df.to_string(index=False))
    print("-" * 120)
    print(f"Pitch Time:        {pitch_time:.1f}s")
    print(f"Upper Limit (UCL): {ucl:.1f}s")
    print(f"Lower Limit (LCL): {lcl:.1f}s")
    print(f"Total Workstations: {len(workstations)}")
    print(f"Total Manpower:     {sum(ws.manpower for ws in workstations)} operators")
    print(f"Line Balancing Rate: {line_balancing_rate:.1f}%")
    print("=" * 120)
    
    # Show any flagged operations
    if flagged_ops:
        print("\n⚠️  FLAGGED OPERATIONS (please review):")
        for op in flagged_ops:
            print(f"  - Operation {op.op_id}: {op.name}")
            print(f"    Error: {op.flagged}")


def export_report(workstations: List[Workstation], filepath: str) -> None:
    """
    Export the report to a CSV or Excel file.
    
    Args:
        workstations: List of Workstation objects
        filepath: Where to save the file (must end in .csv or .xlsx)
    """
    df = build_report_dataframe(workstations)
    
    if filepath.lower().endswith(".xlsx"):
        df.to_excel(filepath, index=False)
    else:
        df.to_csv(filepath, index=False)
