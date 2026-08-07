"""STEP 7: OUTPUT RESULTS - display and export the final workstation report."""

from typing import List

import pandas as pd

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation


def build_report_dataframe(workstations: List[Workstation], ucl: float = None, lcl: float = None) -> pd.DataFrame:
    rows = []
    for i, ws in enumerate(workstations, start=1):
        status = "OK"
        if ucl is not None and lcl is not None:
            if ws.balancing_sam > ucl:
                status = "> UCL (review)"
            elif ws.balancing_sam < lcl:
                status = "< LCL (review)"
        rows.append(
            {
                "Workstation": i,
                "Operations": ws.operation_names,
                "Combined_Basic_Time": round(ws.combined_basic_time, 2),
                "M/P": ws.manpower,
                "Balancing_SAM": round(ws.balancing_sam, 2),
                "Status": status,
            }
        )
    return pd.DataFrame(rows)


def print_summary(
    pitch_time: float,
    ucl: float,
    lcl: float,
    workstations: List[Workstation],
    line_efficiency: float,
    flagged_ops: List[Operation],
) -> None:
    df = build_report_dataframe(workstations, ucl=ucl, lcl=lcl)
    print(df.to_string(index=False))
    print("-" * 90)
    print(f"Pitch Time = {pitch_time:.2f}s | UCL = {ucl:.2f}s | LCL = {lcl:.2f}s")
    print(f"Total Workstations = {len(workstations)} | Total Manpower = {sum(w.manpower for w in workstations)}")
    print(f"Line Efficiency = {line_efficiency:.1f}%")

    if flagged_ops:
        print("\nFlagged operations:")
        for op in flagged_ops:
            print(f"  - {op.name} (ID {op.op_id}): {op.flagged}")


def export_report(workstations: List[Workstation], filepath: str) -> None:
    df = build_report_dataframe(workstations)
    if filepath.lower().endswith(".xlsx"):
        df.to_excel(filepath, index=False)
    else:
        df.to_csv(filepath, index=False)
