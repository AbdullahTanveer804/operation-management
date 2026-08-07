"""
STEP 5 / HELPER ALGORITHM B: GROUP_AND_BALANCE

For every operation, in sequence order:
  1. If its Basic_Time already falls within [LCL, UCL] -> its own workstation, M/P = 1.
  2. Otherwise, look for candidate operations to combine with (same Machine_Type,
     predecessor constraint satisfied).
  3. If candidates exist, combine and either keep M/P = 1 (if the combined time
     fits the band) or split across enough operators (M/P) to bring the
     per-operator share within the band.
  4. If no candidates exist, split the standalone operation across operators
     the same way.
"""

from typing import List

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation


def is_within_range(time: float, ucl: float, lcl: float) -> bool:
    return lcl <= time <= ucl


def _predecessor_constraint_satisfied(op: Operation, other_op: Operation, grouped_ids: set) -> bool:
    """
    Two operations may share a workstation only if doing so doesn't violate
    sequence: every predecessor of EITHER operation (other than each other)
    must already be grouped/placed - i.e. both operations are simultaneously
    "ready" at this point in the sequence.
    """
    all_preds = set(op.predecessors) | set(other_op.predecessors)
    unresolved = [
        p for p in all_preds
        if p not in grouped_ids and p not in (op.op_id, other_op.op_id)
    ]
    return len(unresolved) == 0


def _find_candidates(op: Operation, ungrouped: List[Operation], grouped_ids: set) -> List[Operation]:
    matches = []
    for other in ungrouped:
        if other.op_id == op.op_id or other.op_id in grouped_ids:
            continue
        if other.machine_type == op.machine_type:
            if _predecessor_constraint_satisfied(op, other, grouped_ids):
                matches.append(other)
    return matches


def _closest_split(time: float, ucl: float, lcl: float, max_divisor: int = 10):
    """
    Find the manpower split that brings time/manpower CLOSEST to Pitch Time.

    The literal 'increase divisor until it lands inside [LCL, UCL]' rule can
    skip straight over a narrow band (e.g. 32.1 -> 32.1 above UCL, 16.05 below
    LCL, nothing in between) and never terminate cleanly. Instead we search a
    bounded range of divisors and keep whichever minimizes the distance to
    Pitch Time - exact landings inside the band still win outright, and
    anything that can't land inside the band gets the nearest miss instead of
    a runaway divisor.
    """
    pitch_time = (ucl + lcl) / 2  # UCL + LCL always sum to 2 * Pitch Time
    best_divisor, best_time = 1, time
    best_diff = abs(time - pitch_time)

    for divisor in range(2, max_divisor + 1):
        test_time = time / divisor
        diff = abs(test_time - pitch_time)
        if diff < best_diff:
            best_divisor, best_time, best_diff = divisor, test_time, diff
        elif test_time < pitch_time:
            # time/divisor only decreases as divisor grows, so once we're
            # past the minimum and moving away again, further divisors won't help
            break

    return best_divisor, best_time


def group_and_balance(sorted_operations: List[Operation], ucl: float, lcl: float) -> List[Workstation]:
    workstations: List[Workstation] = []
    grouped_ids: set = set()

    for op in sorted_operations:
        if op.op_id in grouped_ids:
            continue

        # ---- Step 1: Trigger check ----
        if is_within_range(op.basic_time, ucl, lcl):
            workstations.append(Workstation(operations=[op], manpower=1, balancing_sam=op.basic_time))
            grouped_ids.add(op.op_id)
            continue

        # ---- Step 2: Dependency check (machine type + predecessor) ----
        candidates = _find_candidates(op, sorted_operations, grouped_ids)

        if candidates:
            # ---- Step 3: Combine path ----
            combined_group = [op] + candidates
            combined_time = sum(o.basic_time for o in combined_group)

            if is_within_range(combined_time, ucl, lcl):
                manpower, balancing_sam = 1, combined_time
            else:
                manpower, balancing_sam = _closest_split(combined_time, ucl, lcl)

            workstations.append(Workstation(operations=combined_group, manpower=manpower, balancing_sam=balancing_sam))
            grouped_ids.update(o.op_id for o in combined_group)

        else:
            # ---- Step 4: No-match / standalone path ----
            manpower, balancing_sam = _closest_split(op.basic_time, ucl, lcl)
            workstations.append(Workstation(operations=[op], manpower=manpower, balancing_sam=balancing_sam))
            grouped_ids.add(op.op_id)

    return workstations
