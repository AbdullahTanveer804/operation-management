"""
STEP 1: READ INPUT DATA

Reads Raw_Operations from a CSV/XLSX file with standard header:
    Operation_Name, Predecessor, Machine_Type, Basic_Time

Validates each row and flags anything missing (except Predecessor,
which is allowed to be empty for the first operation(s)).
"""

from pathlib import Path
from typing import List

import pandas as pd

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation

REQUIRED_COLUMNS = ["Operation_Name", "Predecessor", "Machine_Type", "Basic_Time"]
COLUMN_ALIASES = {
    "Operation_Name": ["Operation_Name", "Operations"],
    "Predecessor": ["Predecessor"],
    "Machine_Type": ["Machine_Type", "Machine Type"],
    "Basic_Time": ["Basic_Time", "Basic Time", "Basic Time ", "Basic_Time "],
}


def _parse_predecessors(raw) -> List[int]:
    """
    Turn a Predecessor cell into a list of operation IDs.
    Supports single values ('3'), multiple ('9,11'), and empty/'-' (no predecessor).
    NOTE: the original pseudocode treats Predecessor as a single value; real
    factory data uses comma-separated multiple predecessors (e.g. '9,11'),
    so this parses to a list to stay compatible with both.
    """
    if pd.isna(raw) or str(raw).strip() in ("-", ""):
        return []
    return [int(p.strip()) for p in str(raw).split(",") if p.strip()]


def read_operations(filepath: str) -> List[Operation]:
    """Read and validate the raw operations file. Operation IDs are assigned
    by row position (1-indexed), matching the factory's own convention where
    Predecessor values reference row numbers."""
    path = Path(filepath)

    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    resolved_columns = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in df.columns:
                resolved_columns[canonical] = alias
                break

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in resolved_columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in {filepath}: {missing_cols}")

    operations: List[Operation] = []
    for idx, row in df.iterrows():
        op_id = idx + 1
        name_col = resolved_columns["Operation_Name"]
        machine_col = resolved_columns["Machine_Type"]
        basic_time_col = resolved_columns["Basic_Time"]
        predecessor_col = resolved_columns["Predecessor"]

        name = str(row[name_col]).strip() if not pd.isna(row[name_col]) else ""
        machine = str(row[machine_col]).strip() if not pd.isna(row[machine_col]) else ""
        basic_time_raw = row[basic_time_col]

        flagged = None
        if not name or not machine or pd.isna(basic_time_raw):
            flagged = "Invalid Input — check file"

        operations.append(
            Operation(
                op_id=op_id,
                name=name,
                predecessors=_parse_predecessors(row[predecessor_col]),
                machine_type=machine,
                basic_time=float(basic_time_raw) if not pd.isna(basic_time_raw) else 0.0,
                flagged=flagged,
            )
        )

    return operations
