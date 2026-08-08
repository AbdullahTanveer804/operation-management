"""
STEP 1: Read and Validate Input Data

Reads operations from a CSV or Excel file with the following expected columns:
- Serial/Id (unique identifier for each operation)
- Operation (name or label of the operation)
- Predecessor (operation ID this operation depends on; can be blank for starting operations)
- Machine Type (type of machine used)
- Basic Time (time to complete in seconds, allowance already included)

Validates each operation and flags any errors for display to the user.
"""

from pathlib import Path
from typing import List

import pandas as pd

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation

# Column name mappings (we accept several variations of the expected headers)
COLUMN_MAPPINGS = {
    "op_id": ["Serial No.", "Serial/Id", "Serial No", "Id", "Operation ID", "Seq"],
    "name": ["Operation", "Operations", "Operation name", "Name", "Label"],
    "predecessor": ["Predecessor", "Pred", "Depends On", "Previous"],
    "machine_type": ["Machine Type", "Machine", "Equipment Type"],
    "basic_time": ["Basic Time", "Basic_Time", "Time (s)", "SAM", "Time"],
}


def find_column_name(df_columns: list, mapping_options: list) -> str:
    """
    Find which column name in the dataframe matches one of our expected names.
    
    Args:
        df_columns: List of actual column names in the dataframe
        mapping_options: List of names we accept for this column
    
    Returns:
        The actual column name, or None if no match found
    """
    for option in mapping_options:
        for col in df_columns:
            if col.strip().lower() == option.lower():
                return col
    return None


def parse_predecessor_value(raw_value) -> List[int]:
    """
    Convert predecessor cell value to a list of operation IDs.
    
    Handles several formats:
    - Empty or "-" = no predecessor (starting operation)
    - Single number like "3" = depends on operation 3
    - Multiple numbers like "9,11" = depends on operations 9 and 11
    
    Args:
        raw_value: The cell value from the CSV/Excel
    
    Returns:
        List of predecessor operation IDs
    """
    # Check if it's empty, null, or just a dash
    if pd.isna(raw_value) or str(raw_value).strip() in ("-", ""):
        return []
    
    # Try to parse as comma-separated numbers
    try:
        pred_str = str(raw_value).strip()
        # Split by comma and convert each to int
        ids = [int(p.strip()) for p in pred_str.split(",") if p.strip()]
        return ids
    except (ValueError, AttributeError):
        # If parsing fails, return empty (this will flag as an error)
        return []


def read_operations(filepath: str) -> List[Operation]:
    """
    Read operations from a CSV or Excel file.
    
    Each row becomes one Operation object. If the file has a Serial/Id column,
    we use that; otherwise, we use row position (1-indexed) as the ID.
    
    Args:
        filepath: Path to CSV or XLSX file
    
    Returns:
        List of Operation objects
    
    Raises:
        ValueError: If required columns are missing
    """
    path = Path(filepath)
    
    # Read the file
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    
    # Find which columns we have
    op_id_col = find_column_name(df.columns, COLUMN_MAPPINGS["op_id"])
    name_col = find_column_name(df.columns, COLUMN_MAPPINGS["name"])
    pred_col = find_column_name(df.columns, COLUMN_MAPPINGS["predecessor"])
    machine_col = find_column_name(df.columns, COLUMN_MAPPINGS["machine_type"])
    time_col = find_column_name(df.columns, COLUMN_MAPPINGS["basic_time"])
    
    # Check that we found all required columns
    missing = []
    if not name_col:
        missing.append("Operation/Name")
    if not machine_col:
        missing.append("Machine Type")
    if not time_col:
        missing.append("Basic Time")
    
    if missing:
        raise ValueError(f"Missing required columns in {filepath}: {', '.join(missing)}")
    
    # Read each row as an operation
    operations: List[Operation] = []
    
    for row_idx, row in df.iterrows():
        # Determine operation ID
        if op_id_col:
            try:
                op_id = int(row[op_id_col])
            except (ValueError, TypeError):
                op_id = row_idx + 1
        else:
            # Use row position as ID (1-indexed)
            op_id = row_idx + 1
        
        # Extract operation name
        name = str(row[name_col]).strip() if not pd.isna(row[name_col]) else ""
        
        # Extract machine type
        machine_type = str(row[machine_col]).strip() if not pd.isna(row[machine_col]) else ""
        
        # Extract basic time
        try:
            basic_time = float(row[time_col])
        except (ValueError, TypeError):
            basic_time = 0.0
        
        # Extract predecessor(s)
        predecessors = []
        if pred_col:
            predecessors = parse_predecessor_value(row[pred_col])
        
        # Validation: flag if any required field is missing/invalid
        flagged = None
        if not name:
            flagged = "Missing operation name"
        elif not machine_type:
            flagged = "Missing machine type"
        elif basic_time <= 0:
            flagged = "Invalid basic time (must be positive)"
        
        # Create operation object
        op = Operation(
            op_id=op_id,
            name=name,
            predecessors=predecessors,
            machine_type=machine_type,
            basic_time=basic_time,
            flagged=flagged
        )
        operations.append(op)
    
    return operations
