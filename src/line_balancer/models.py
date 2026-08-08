"""
Data Models for Line Balancing Optimizer

Simple data structures to hold operation and workstation information.
These models are used throughout the calculation pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Operation:
    """
    Represents a single operation from the input file.
    
    Attributes:
        op_id (int): Unique identifier (Serial No.)
        name (str): Operation name (e.g., "V Panel Hem (L+R)")
        predecessors (List[int]): List of operation IDs this operation depends on
        machine_type (str): Type of machine used (e.g., "S/N L/S")
        basic_time (float): Time to complete in seconds (includes allowance)
        flagged (str): Error message if input is invalid
    """
    op_id: int
    name: str
    predecessors: List[int]
    machine_type: str
    basic_time: float
    flagged: Optional[str] = None

    def __repr__(self) -> str:
        return f"Op{self.op_id}: {self.name}"


@dataclass
class Workstation:
    """
    Represents a workstation (one or more combined operations).
    
    Attributes:
        operations (List[Operation]): Operations assigned to this workstation
        manpower (int): Number of operators needed (M/P)
        balancing_sam (float): Final standardized time per operator
    """
    operations: List[Operation] = field(default_factory=list)
    manpower: int = 1
    balancing_sam: float = 0.0
    is_edited: bool = False  # Flag if manually edited by user

    @property
    def combined_basic_time(self) -> float:
        """Sum of all operation basic times in this workstation."""
        return sum(op.basic_time for op in self.operations)

    @property
    def operation_names(self) -> str:
        """Comma-separated list of operation names."""
        return ", ".join(op.name for op in self.operations)
    
    @property
    def operation_ids(self) -> str:
        """Comma-separated list of operation IDs."""
        return ", ".join(str(op.op_id) for op in self.operations)
