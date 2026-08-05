"""
Line Balancing Tool - Core Algorithm
Greedy grouping heuristic based on Pitch Time / UCL / LCL band,
respecting predecessor sequence and machine type compatibility.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Operation:
    id: int
    name: str
    predecessors: List[int]  # list of operation IDs
    machine: str
    basic_time: float  # in seconds


@dataclass
class Workstation:
    ops: List[Operation] = field(default_factory=list)
    total_time: float = 0.0
    machine: Optional[str] = None
    manpower: int = 1

    @property
    def balancing_sam(self):
        return self.total_time / self.manpower if self.manpower else self.total_time

    @property
    def op_names(self):
        return ", ".join(op.name for op in self.ops)


def compute_pitch_time(total_basic_time: float, total_op_count: int, tolerance: float = 0.15):
    """Pitch Time = Total Basic Time / Total Operation Count (all operations, including untracked ones)."""
    pitch_time = total_basic_time / total_op_count
    ucl = pitch_time * (1 + tolerance)
    lcl = pitch_time * (1 - tolerance)
    return pitch_time, ucl, lcl


def topological_order(operations: List[Operation]) -> List[Operation]:
    """Kahn's algorithm - orders operations so predecessors always come first."""
    op_by_id = {op.id: op for op in operations}
    in_degree = {op.id: len(op.predecessors) for op in operations}
    queue = [op.id for op in operations if in_degree[op.id] == 0]
    ordered = []

    # successors map
    successors = {op.id: [] for op in operations}
    for op in operations:
        for pred in op.predecessors:
            successors[pred].append(op.id)

    while queue:
        # keep original entry order among ready ops for stability
        queue.sort()
        current_id = queue.pop(0)
        ordered.append(op_by_id[current_id])
        for succ_id in successors[current_id]:
            in_degree[succ_id] -= 1
            if in_degree[succ_id] == 0:
                queue.append(succ_id)

    if len(ordered) != len(operations):
        raise ValueError("Cycle detected in predecessor relationships - check your data.")
    return ordered


def balance_line(operations: List[Operation], pitch_time: float, ucl: float, lcl: float) -> List[Workstation]:
    order = topological_order(operations)
    workstations: List[Workstation] = []
    current = Workstation()

    def close_current():
        nonlocal current
        if current.ops:
            workstations.append(current)
        current = Workstation()

    for op in order:
        # Case 1: operation alone exceeds UCL -> must split across multiple operators
        if op.basic_time > ucl:
            close_current()  # flush whatever bucket was open
            ws = Workstation(ops=[op], total_time=op.basic_time, machine=op.machine)
            ws.manpower = math.ceil(op.basic_time / pitch_time)
            workstations.append(ws)
            continue

        # Case 2: try adding to the open bucket (single-operator fit)
        fits_machine = (current.machine is None or current.machine == op.machine)
        fits_time_single = (current.total_time + op.basic_time) <= ucl

        if current.ops and fits_machine and fits_time_single:
            current.ops.append(op)
            current.total_time += op.basic_time
            continue

        # NOTE: pairwise combining heuristics (tried and removed) could not
        # reliably replicate manual IE groupings - manual balancing folds in
        # line layout and holistic judgment that isn't in this data alone.
        # V1 goal: propose a reasonable initial balance; let IE staff
        # override groupings in the UI rather than chase full automation.
        close_current()
        current = Workstation(ops=[op], total_time=op.basic_time, machine=op.machine)

    close_current()
    return workstations


def print_report(workstations: List[Workstation], pitch_time: float, ucl: float, lcl: float):
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