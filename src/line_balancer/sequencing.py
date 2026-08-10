"""
STEP 2: Sequence Operations by Serial No. / ID (Ascending)

This is simple: just sort operations by their ID from lowest to highest.
The Predecessor field is NOT used for ordering here—it's only used later
in the balancing step to enforce constraints (an operation cannot be
combined in a way that violates its predecessor dependency).
"""

from typing import List
from collections import defaultdict, deque

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation


def sort_by_id(operations: List[Operation]) -> List[Operation]:
    """
    Sort all operations by Serial No. / ID in ascending order.
    
    Args:
        operations: List of Operation objects
    
    Returns:
        List of operations sorted by op_id (ascending)
    """
    return sorted(operations, key=lambda op: op.op_id)
