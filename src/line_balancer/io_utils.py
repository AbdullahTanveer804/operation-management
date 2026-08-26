"""
STEP 1: Read and Validate Input Data

Reads operations from a CSV or Excel file with the following expected columns:
- Serial/Id (unique identifier for each operation)
- Operation (name or label of the operation)
- Predecessor (operation ID this operation depends on; can be blank for starting operations)
- Machine Type (type of machine used)
- Basic Time (time to complete in seconds, allowance already included)

Validates each operation and flags any errors for display to the user.

ID Validation:
- IDs must start from 1
- IDs must be unique (no duplicates)
- IDs must not be null/missing

Predecessor Validation:
- No duplicate IDs within a single predecessor list
- No self-references (operation can't depend on itself)
- Each operation ID can be a predecessor for only ONE other operation
- Highest ID operation is not referenced as a predecessor
- All referenced IDs must exist in the operation list
"""

from pathlib import Path
from typing import List
import pandas as pd
from .models import Operation

# Column name mappings (we accept several variations of the expected headers)
COLUMN_MAPPINGS = {
    "op_id": [
        "Serial No.", "Serial/Id", "Serial No", "Id", "Operation ID", "Seq",
        "Sr", "Sr."
    ],
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
    - "-" = no predecessor (starting operation)
    - Single number like "3" = depends on operation 3
    - Multiple numbers like "9,11" = depends on operations 9 and 11
    
    Args:
        raw_value: The cell value from the CSV/Excel
    
    Returns:
        List of predecessor operation IDs
    
    Raises:
        ValueError: If the value cannot be parsed as valid predecessor IDs
    """
    # Check if it's just a dash (explicit no predecessor)
    if str(raw_value).strip() == "-":
        return []

    # Try to parse as comma-separated numbers
    try:
        pred_str = str(raw_value).strip()
        if not pred_str:
            return []  # Empty string is valid (no predecessor)

        # Split by comma and convert each to int
        ids = [int(p.strip()) for p in pred_str.split(",") if p.strip()]

        # Validate that all IDs are positive
        for pid in ids:
            if pid <= 0:
                raise ValueError(f"Predecessor ID must be positive, got {pid}")

        return ids
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid predecessor value '{raw_value}': {str(e)}")


def validate_operation_ids(operations: List[Operation]) -> List[str]:
    """
    Validate operation IDs for completeness and uniqueness.
    
    Returns:
        List of error messages (empty if validation passes)
    """
    errors = []

    if not operations:
        errors.append("No operations found in file")
        return errors

    # Extract all IDs
    ids = [op.op_id for op in operations]

    # Check for null/missing IDs
    null_ids = [
        i for i, op in enumerate(operations)
        if op.op_id is None or op.op_id == ""
    ]
    if null_ids:
        errors.append(f"Missing/null operation IDs at row(s): {null_ids}")

    # Check if IDs start from 1
    min_id = min(ids) if ids else 0
    if min_id != 1:
        errors.append(
            f"Operation IDs must start from 1, found minimum ID: {min_id}")

    # Check for duplicate IDs with more detail
    seen_ids = {}
    duplicate_ids = []
    for op in operations:
        if op.op_id in seen_ids:
            duplicate_ids.append(op.op_id)
            seen_ids[op.op_id].append(op.op_id)
        else:
            seen_ids[op.op_id] = [op.op_id]

    if duplicate_ids:
        # Get unique duplicate IDs
        unique_duplicates = list(set(duplicate_ids))
        errors.append(f"Duplicate operation IDs found: {unique_duplicates}")

    return errors


def validate_predecessors(operations: List[Operation]) -> List[str]:
    """
    Validate predecessor references across all operations.
    
    Checks:
    - No duplicate IDs within a single predecessor list
    - No self-references (operation can't depend on itself)
    - Each operation ID can be a predecessor for only ONE other operation
    - Highest ID operation is not referenced as a predecessor
    - All referenced IDs must exist in the operation list
    - Each operation ID (except first and last) must appear exactly once in predecessor column
    
    Returns:
        List of error messages (empty if validation passes)
    """
    errors = []

    if not operations:
        return errors

    # Get all valid operation IDs
    valid_ids = set(op.op_id for op in operations)
    min_id = min(valid_ids) if valid_ids else 0
    max_id = max(valid_ids) if valid_ids else 0

    # Track which operation IDs are already used as predecessors
    used_predecessor_ids = set()

    # Validate each operation's predecessors
    for op in operations:
        # Check for duplicate IDs within single predecessor list
        if len(op.predecessors) != len(set(op.predecessors)):
            duplicates = [
                pid for pid in op.predecessors
                if op.predecessors.count(pid) > 1
            ]
            errors.append(
                f"Operation {op.op_id} has duplicate predecessors: {duplicates}"
            )

        # Check for self-references
        if op.op_id in op.predecessors:
            errors.append(
                f"Operation {op.op_id} cannot depend on itself (self-reference)"
            )

        # Check each predecessor
        for pred_id in op.predecessors:
            # Check if referenced ID exists
            if pred_id not in valid_ids:
                errors.append(
                    f"Operation {op.op_id} references non-existent predecessor ID: {pred_id}"
                )

            # Check if this predecessor ID is already used by another operation
            if pred_id in used_predecessor_ids:
                # Find which operation already used this predecessor
                for other_op in operations:
                    if pred_id in other_op.predecessors and other_op.op_id != op.op_id:
                        errors.append(
                            f"Operation ID {pred_id} is already used as predecessor for operation {other_op.op_id}, cannot be used again for operation {op.op_id}"
                        )
                        break
            else:
                # Mark this predecessor ID as used
                used_predecessor_ids.add(pred_id)

    # Check if highest ID is referenced as predecessor
    if max_id in used_predecessor_ids:
        referencing_ops = [
            op.op_id for op in operations if max_id in op.predecessors
        ]
        errors.append(
            f"Highest operation ID ({max_id}) should not be referenced as a predecessor (referenced by: {referencing_ops})"
        )

    # Check that each operation ID (except first and last) appears exactly once in predecessor column
    # Collect all predecessor references across all operations
    all_predecessor_refs = []
    for op in operations:
        all_predecessor_refs.extend(op.predecessors)

    # Count occurrences of each ID in predecessor column
    predecessor_counts = {}
    for pred_id in all_predecessor_refs:
        predecessor_counts[pred_id] = predecessor_counts.get(pred_id, 0) + 1

    # Check that each operation ID (except min and max) appears exactly once
    expected_ids = set(range(min_id + 1,
                             max_id))  # All IDs except first and last
    for expected_id in expected_ids:
        count = predecessor_counts.get(expected_id, 0)
        if count == 0:
            errors.append(
                f"Operation ID {expected_id} is missing from predecessor column (should appear exactly once)"
            )
        elif count > 1:
            errors.append(
                f"Operation ID {expected_id} appears {count} times in predecessor column (should appear exactly once)"
            )

    return errors


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
        ValueError: If required columns are missing or ID/predecessor validation fails
    """
    path = Path(filepath)

    # Read the file
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(
            path, dtype=str
        )  # Read all columns as strings to prevent auto-conversion

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
        raise ValueError(
            f"Missing required columns in {filepath}: {', '.join(missing)}")

    # Require predecessor column to be present
    if not pred_col:
        raise ValueError(
            f"Missing required column: Predecessor (or Predecessor/Pred/Depends On/Previous)"
        )

    # Read each row as an operation
    operations: List[Operation] = []

    for row_idx, row in df.iterrows():
        # Determine operation ID
        if op_id_col:
            # Require explicit ID column to be present and valid
            if not row[op_id_col] or str(
                    row[op_id_col]).strip().lower() in ['nan', 'none', '']:
                raise ValueError(
                    f"Row {row_idx + 1}: Operation ID is missing/null")

            # Check if the ID value contains commas (multiple IDs in one cell)
            id_str = str(row[op_id_col]).strip()
            if ',' in id_str:
                raise ValueError(
                    f"Row {row_idx + 1}: Operation ID cannot contain multiple values (found '{id_str}')"
                )

            try:
                # First try to convert to float (handles both int and float strings), then to int
                op_id = int(float(row[op_id_col]))
                if op_id <= 0:
                    raise ValueError(
                        f"Row {row_idx + 1}: Operation ID must be positive, got {op_id}"
                    )
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"Row {row_idx + 1}: Invalid operation ID '{row[op_id_col]}' - {str(e)}"
                )
        else:
            # Use row position as ID (1-indexed)
            op_id = row_idx + 1

        # Extract operation name
        name = str(row[name_col]).strip() if row[name_col] and str(
            row[name_col]).strip().lower() not in ['nan', 'none', ''] else ""

        # Extract machine type
        machine_type = str(
            row[machine_col]).strip() if row[machine_col] and str(
                row[machine_col]).strip().lower() not in ['nan', 'none', ''
                                                          ] else ""

        # Extract basic time
        try:
            basic_time = float(row[time_col])
        except (ValueError, TypeError):
            try:
                basic_time = float(str(row[time_col]).strip())
            except (ValueError, TypeError):
                basic_time = 0.0

        # Extract predecessor(s)
        predecessors = []
        if pred_col:
            pred_value = row[pred_col]
            # Check if predecessor value is missing/null
            if not pred_value or str(pred_value).strip().lower() in [
                    'nan', 'none', ''
            ]:
                raise ValueError(
                    f"Row {row_idx + 1}: Predecessor cell is empty/null")
            try:
                predecessors = parse_predecessor_value(pred_value)
            except ValueError as e:
                raise ValueError(f"Row {row_idx + 1}: {str(e)}")

        # Validation: flag if any required field is missing/invalid
        flagged = None
        if not name:
            flagged = "Missing operation name"
        elif not machine_type:
            flagged = "Missing machine type"
        elif basic_time <= 0:
            flagged = "Invalid basic time (must be positive)"

        # Create operation object
        op = Operation(op_id=op_id,
                       name=name,
                       predecessors=predecessors,
                       machine_type=machine_type,
                       basic_time=basic_time,
                       flagged=flagged)
        operations.append(op)

    # Run ID validation
    id_errors = validate_operation_ids(operations)
    if id_errors:
        raise ValueError(f"Operation ID validation failed:\n" +
                         "\n".join(id_errors))

    # Run predecessor validation
    pred_errors = validate_predecessors(operations)
    if pred_errors:
        raise ValueError(f"Predecessor validation failed:\n" +
                         "\n".join(pred_errors))

    return operations
