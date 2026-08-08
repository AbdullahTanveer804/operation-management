"""Line Balancing Optimizer - public API."""

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .balancing import group_and_balance, is_within_range
from .io_utils import read_operations
from .metrics import calculate_line_efficiency, calculate_pitch_time as _calculate_pitch_time, calculate_tolerance_bands
from .models import Operation, Workstation
from .sequencing import sort_by_id

# Re-export the current package API.
Operation = Operation
Workstation = Workstation


@dataclass
class CompatWorkstation:
    """Compatibility container for the older module-based API."""

    ops: List[Operation] = field(default_factory=list)
    total_time: float = 0.0
    machine: Optional[str] = None
    manpower: int = 1

    @property
    def balancing_sam(self) -> float:
        return self.total_time / self.manpower if self.manpower else self.total_time

    @property
    def op_names(self) -> str:
        return ", ".join(op.name for op in self.ops)


def compute_pitch_time(total_basic_time: float, total_op_count: int, tolerance: float = 0.15):
    """Compatibility wrapper for the older module-style API."""
    pitch_time = total_basic_time / total_op_count
    ucl = pitch_time * (1 + tolerance)
    lcl = pitch_time * (1 - tolerance)
    return pitch_time, ucl, lcl


def topological_order(operations: List[Operation]) -> List[Operation]:
    """Compatibility wrapper that returns the predecessor-sorted operations."""
    ordered = sort_by_predecessor(operations)
    if any(op.flagged == "Unresolved Predecessor" for op in ordered):
        return ordered
    return ordered


def balance_line(operations: List[Operation], pitch_time: float, ucl: float, lcl: float) -> List[CompatWorkstation]:
    """Compatibility wrapper that mirrors the older module-based balancing flow."""
    ordered = sort_by_predecessor(operations)
    workstations: List[CompatWorkstation] = []
    current = CompatWorkstation()

    def close_current() -> None:
        nonlocal current
        if current.ops:
            workstations.append(current)
        current = CompatWorkstation()

    for op in ordered:
        if op.basic_time > ucl:
            close_current()
            ws = CompatWorkstation(ops=[op], total_time=op.basic_time, machine=op.machine_type)
            ws.manpower = math.ceil(op.basic_time / pitch_time)
            workstations.append(ws)
            continue

        fits_machine = (current.machine is None or current.machine == op.machine_type)
        fits_time_single = (current.total_time + op.basic_time) <= ucl

        if current.ops and fits_machine and fits_time_single:
            current.ops.append(op)
            current.total_time += op.basic_time
            continue

        close_current()
        current = CompatWorkstation(ops=[op], total_time=op.basic_time, machine=op.machine_type)

    close_current()
    return workstations


def print_report(workstations: List[CompatWorkstation], pitch_time: float, ucl: float, lcl: float) -> None:
    """Compatibility wrapper for the older module-style report output."""
    total_mp = sum(ws.manpower for ws in workstations)
    print(f"{'Workstation':<4}{'Operations':<55}{'Total Time':>11}{'M/P':>5}{'Bal. SAM':>10}{'Status':>12}")
    print("-" * 100)
    for i, ws in enumerate(workstations, 1):
        if ws.balancing_sam > ucl:
            status = "> UCL"
        elif ws.balancing_sam < lcl:
            status = "< LCL"
        else:
            status = "OK"
        print(f"{i:<4}{ws.op_names[:53]:<55}{ws.total_time:>11.1f}{ws.manpower:>5}{ws.balancing_sam:>10.1f}{status:>12}")
    print("-" * 100)
    print(f"Pitch Time = {pitch_time:.1f}s | UCL = {ucl:.1f}s | LCL = {lcl:.1f}s")
    print(f"Total Workstations = {len(workstations)} | Total Manpower Required = {total_mp}")


__all__ = [
    "read_operations",
    "sort_by_predecessor",
    "calculate_pitch_time",
    "calculate_tolerance_bands",
    "calculate_line_efficiency",
    "group_and_balance",
    "is_within_range",
    "Operation",
    "Workstation",
    "compute_pitch_time",
    "balance_line",
    "print_report",
    "topological_order",
]

__version__ = "0.1.0"
