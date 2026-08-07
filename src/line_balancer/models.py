"""Data models used across the Line Balancing Optimizer."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Operation:
    """A single garment operation read from the input file."""

    op_id: int
    name: str
    predecessors: List[int]
    machine_type: str
    basic_time: float
    flagged: Optional[str] = None  # e.g. "Invalid Input", "Unresolved Predecessor"

    def __repr__(self) -> str:
        return f"Op{self.op_id}:{self.name}"


@dataclass
class Workstation:
    """One or more operations assigned together with a manpower count."""

    operations: List[Operation] = field(default_factory=list)
    manpower: int = 1
    balancing_sam: float = 0.0

    @property
    def combined_basic_time(self) -> float:
        return sum(op.basic_time for op in self.operations)

    @property
    def operation_names(self) -> str:
        return ", ".join(op.name for op in self.operations)
