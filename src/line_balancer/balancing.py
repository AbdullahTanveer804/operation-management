"""
STEP 5: Group and Balance Operations into Workstations

ALGORITHM (Simple English):

For each operation in ID order:
1. Check if its basic time is already acceptable (within LCL to UCL)
   - If YES: Create its own workstation with M/P = 1, move to next operation
   - If NO: Continue to step 2

2. Look for another operation to combine with:
   - Must use compatible machine types (helper-machine rules apply)
     * Helper-machines (By Hand, Pointer, Pencil, Clipper, Press) can combine with any machine type
     * Press can ONLY combine with helper-machines, never with regular machine types
     * Regular machine types can only combine with identical types (unless one is a helper-machine)
   - Both operations' predecessor requirements must be satisfied
   - If found: Combine their times and check the sum
     - If sum is acceptable: Use M/P = 1, Balancing SAM = sum
     - If sum is still too high or too low: Try splitting across 2, 3, 4... operators
       until the time per operator becomes acceptable
   - If NOT found: Try splitting this operation across 2, 3, 4... operators
     until the time per operator becomes acceptable

3. Create a workstation with the combined operation(s) and the calculated M/P
"""

from typing import List
from .models import Operation, Workstation

# Helper-machines: special categories that can combine with any machine type
HELPER_MACHINES = {"By Hand", "Pointer", "Pencil", "Clipper", "Press"}


def is_within_range(time: float,
                    ucl: float,
                    lcl: float,
                    strict: bool = False) -> bool:
    """Check if a time value falls within the acceptable band [LCL, UCL].
    
    If ucl and lcl are None (or identical for manual/target methods), check if time is close to target.
    When strict=True, time must not exceed target (time <= target).
    """
    if ucl is None or lcl is None:
        # For manual/target methods, use the ucl as target
        target = ucl if ucl is not None else lcl
        if target is None:
            return True  # No constraints if both are None
        if strict:
            return time <= target
        return time <= target * 1.1  # Allow 10% above target
    return lcl <= time <= ucl


def can_combine_machine_types(machine_type1: str, machine_type2: str) -> bool:
    """
    Check if two machine types can be combined based on helper-machine rules.
    
    Rules:
    - Helper-machines (By Hand, Pointer, Pencil, Clipper, Press) can combine with any machine type
    - Helper-machines can combine with other helper-machines
    - Press can ONLY combine with helper-machines, never with regular machine types
    - Regular machine types can only combine with identical types (unless one is a helper-machine)
    
    Args:
        machine_type1: First machine type
        machine_type2: Second machine type
    
    Returns:
        True if the machine types can be combined, False otherwise
    """
    # If both are the same machine type, they can always combine
    if machine_type1 == machine_type2:
        return True

    # Check if either is a helper-machine
    is_helper1 = machine_type1 in HELPER_MACHINES
    is_helper2 = machine_type2 in HELPER_MACHINES

    # If both are helper-machines, they can combine
    if is_helper1 and is_helper2:
        return True

    # If one is a helper-machine and the other is not
    if is_helper1 or is_helper2:
        # Press has special restriction: can ONLY combine with helper-machines
        if machine_type1 == "Press" or machine_type2 == "Press":
            # Press can only combine if the OTHER is also a helper-machine
            return is_helper1 and is_helper2  # Both must be helpers
        return True

    # Both are regular machine types but different - cannot combine
    return False


def check_predecessor_constraint(op1: Operation, op2: Operation,
                                 already_grouped_ids: set) -> bool:
    """
    Check if two operations can be combined together.
    
    RULE: An operation cannot be placed ahead of the operation it depends on.
    This means: if op1 depends on ID 5, then ID 5 must already be grouped
    (or be op2 itself).
    
    Args:
        op1: First operation
        op2: Second operation
        already_grouped_ids: Set of operation IDs already assigned to workstations
    
    Returns:
        True if they can be combined, False otherwise
    """
    # Get all predecessor IDs from both operations
    all_predecessors = set(op1.predecessors) | set(op2.predecessors)

    # For each predecessor, check if it's already grouped OR is one of these two ops
    for pred_id in all_predecessors:
        if pred_id not in already_grouped_ids and pred_id != op1.op_id and pred_id != op2.op_id:
            # This predecessor is not yet grouped and it's not one of the current ops
            # So we cannot combine these two operations yet
            return False

    return True


def find_compatible_operations(current_op: Operation,
                               all_operations: List[Operation],
                               already_grouped_ids: set) -> List[Operation]:
    """
    Find all operations that could be combined with current_op.
    
    Compatibility rules:
    - Machine types must be compatible (helper-machine rules apply)
    - Not already grouped
    - Predecessor constraints satisfied
    
    Args:
        current_op: The operation we're looking to combine with others
        all_operations: All operations in the dataset
        already_grouped_ids: Operations already assigned to workstations
    
    Returns:
        List of compatible operations
    """
    compatible = []

    for other_op in all_operations:
        # Skip the current operation itself
        if other_op.op_id == current_op.op_id:
            continue

        # Skip if already grouped
        if other_op.op_id in already_grouped_ids:
            continue

        # Must have compatible machine types (helper-machine rules)
        if not can_combine_machine_types(current_op.machine_type,
                                         other_op.machine_type):
            continue

        # Must satisfy predecessor constraints
        if check_predecessor_constraint(current_op, other_op,
                                        already_grouped_ids):
            compatible.append(other_op)

    return compatible


def find_best_manpower_split(time_value: float,
                             ucl: float,
                             lcl: float,
                             max_operators: int = 10,
                             strict: bool = False):
    """
    Find how many operators are needed to make this time acceptable.
    
    LOGIC:
    - Start with M/P = 1 (time unchanged)
    - If time > UCL + 0.5 (or UCL when strict=True), try M/P = 2 (time / 2), then 3, etc.
    - Keep dividing until time/manpower <= UCL + 0.5 (or UCL when strict=True)
    - Don't stop even if it goes below LCL - priority is staying at or below UCL + 0.5
    - 0.5 second flexibility is allowed before increasing manpower (auto method only)
    - strict=True disables the 0.5s relaxation (used for manual/target methods)
    
    Args:
        time_value: The time to split (basic time or combined time)
        ucl: Upper control limit (or target time for manual/target methods)
        lcl: Lower control limit (not used in current logic but kept for interface)
        max_operators: Maximum M/P to try
        strict: If True, no 0.5s relaxation is added (for manual/target methods)
    
    Returns:
        (manpower, resulting_time_per_operator)
    """
    target = ucl if ucl is not None else lcl
    if target is None:
        # No target specified, return as-is
        return 1, time_value

    # 0.5s flexibility only for auto method; strict mode uses exact target
    target_with_flexibility = target if strict else target + 0.5

    # If already at or below target (with flexibility), no splitting needed
    if time_value <= target_with_flexibility:
        return 1, time_value

    # Keep increasing manpower until time/manpower <= target (with flexibility)
    for manpower in range(2, max_operators + 1):
        time_per_op = time_value / manpower

        if time_per_op <= target_with_flexibility:
            return manpower, time_per_op

    # If we hit max_operators and still above target, return the best we found
    return max_operators, time_value / max_operators


def group_and_balance(sorted_operations: List[Operation],
                      ucl: float,
                      lcl: float,
                      strict: bool = False) -> List[Workstation]:
    """
    Process operations in Serial No. order and assign them to workstations,
    combining operations and adjusting manpower as needed to stay within
    the UCL/LCL band (or target time for manual/target methods).
    
    Args:
        sorted_operations: Operations sorted by ID (ascending)
        ucl: Upper Control Limit (or target time for manual/target methods)
        lcl: Lower Control Limit (or target time for manual/target methods)
    
    Returns:
        List of Workstation objects (grouped and balanced)
    """
    workstations: List[Workstation] = []
    already_grouped_ids: set = set()

    # Process each operation in order
    for current_op in sorted_operations:
        # Skip if already assigned to a workstation
        if current_op.op_id in already_grouped_ids:
            continue

        # ===== STEP 1: Check if operation is already within acceptable range =====
        if is_within_range(current_op.basic_time, ucl, lcl, strict=strict):
            # It's fine as-is: create a workstation with just this operation
            ws = Workstation(operations=[current_op],
                             manpower=1,
                             balancing_sam=current_op.basic_time)
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)
            continue

        # ===== STEP 2: Operation is outside range, look for compatible operations =====
        compatible_ops = find_compatible_operations(current_op,
                                                    sorted_operations,
                                                    already_grouped_ids)

        if compatible_ops:
            # ===== STEP 3a: Combine path (search all candidates for Best-Fit in range) =====
            target_pitch = (ucl + lcl) / 2.0 if (ucl is not None and lcl is not None) else (ucl if ucl is not None else lcl)

            valid_candidates = []
            for partner_op in compatible_ops:
                combined_time = current_op.basic_time + partner_op.basic_time
                if is_within_range(combined_time, ucl, lcl, strict=strict):
                    diff = abs(combined_time - target_pitch) if target_pitch is not None else 0.0
                    valid_candidates.append((diff, partner_op.op_id, partner_op, combined_time))

            if valid_candidates:
                # Perfect! Combined time fits in the band (Best-Fit candidate)
                valid_candidates.sort(key=lambda x: (x[0], x[1]))
                _, _, best_partner, best_combined_time = valid_candidates[0]
                ws = Workstation(operations=[current_op, best_partner],
                                 manpower=1,
                                 balancing_sam=best_combined_time)
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(best_partner.op_id)
            else:
                # Combined time is still outside the band: take the first compatible operation and split
                partner_op = compatible_ops[0]
                combined_time = current_op.basic_time + partner_op.basic_time
                manpower, balancing_sam = find_best_manpower_split(
                    combined_time, ucl, lcl, strict=strict)
                ws = Workstation(operations=[current_op, partner_op],
                                 manpower=manpower,
                                 balancing_sam=balancing_sam)
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(partner_op.op_id)
        else:
            # ===== STEP 3b: Standalone path (no compatible operation found) =====
            # Operation couldn't find a partner, try splitting it alone
            manpower, balancing_sam = find_best_manpower_split(
                current_op.basic_time, ucl, lcl, strict=strict)
            ws = Workstation(operations=[current_op],
                             manpower=manpower,
                             balancing_sam=balancing_sam)
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)

    return workstations
