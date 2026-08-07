"""
STEP 2 / HELPER ALGORITHM A: SORT_BY_PREDECESSOR

Orders operations so that every operation appears after all of its
predecessors (a topological sort over the precedence chain). Any
operation whose predecessor never resolves (broken/circular chain,
or a predecessor ID that doesn't exist) is flagged rather than dropped.
"""

from typing import List

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation


def sort_by_predecessor(operations: List[Operation]) -> List[Operation]:
    visited: set = set()
    sorted_list: List[Operation] = []

    # Start with operations that have no predecessor
    for op in operations:
        if not op.predecessors:
            sorted_list.append(op)
            visited.add(op.op_id)

    # Repeatedly add operations whose predecessors are all already placed
    added_this_round = True
    while added_this_round:
        added_this_round = False
        for op in operations:
            if op.op_id in visited:
                continue
            if all(pred in visited for pred in op.predecessors):
                sorted_list.append(op)
                visited.add(op.op_id)
                added_this_round = True

    # Catch broken / circular / missing predecessor chains
    for op in operations:
        if op.op_id not in visited:
            op.flagged = "Unresolved Predecessor"
            sorted_list.append(op)

    return sorted_list
