"""
STEP 5: Group and Balance Operations into Workstations

ALGORITHM (Simple English):

For each operation in ID order:
1. Check if its basic time is already acceptable (within LCL to UCL)
   - If YES: Create its own workstation with M/P = 1, move to next operation
   - If NO: Continue to step 2

2. Look for another operation to combine with:
   - Must use the same machine type
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

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation


def is_within_range(time: float, ucl: float, lcl: float) -> bool:
    """Check if a time value falls within the acceptable band [LCL, UCL]."""
    return lcl <= time <= ucl


def check_predecessor_constraint(op1: Operation, op2: Operation, already_grouped_ids: set) -> bool:
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


def find_compatible_operations(
    current_op: Operation,
    all_operations: List[Operation],
    already_grouped_ids: set
) -> List[Operation]:
    """
    Find all operations that could be combined with current_op.
    
    Compatibility rules:
    - Same machine type
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
        
        # Must have same machine type
        if other_op.machine_type != current_op.machine_type:
            continue
        
        # Must satisfy predecessor constraints
        if check_predecessor_constraint(current_op, other_op, already_grouped_ids):
            compatible.append(other_op)
    
    return compatible


def find_best_manpower_split(time_value: float, ucl: float, lcl: float, max_operators: int = 10):
    """
    Find how many operators are needed to make this time acceptable.
    
    LOGIC:
    - Start with M/P = 1 (time unchanged)
    - If time is still outside [LCL, UCL], try M/P = 2 (time / 2), then 3, etc.
    - Stop when time/M/P falls within [LCL, UCL]
    - If nothing works perfectly, use the M/P that gets closest to the middle
      of the acceptable band (Pitch Time)
    
    Args:
        time_value: The time to split (basic time or combined time)
        ucl: Upper control limit
        lcl: Lower control limit
        max_operators: Maximum M/P to try
    
    Returns:
        (manpower, resulting_time_per_operator)
    """
    # Calculate the middle of the acceptable band (Pitch Time)
    pitch_time = (ucl + lcl) / 2
    
    # Track the best option found
    best_manpower = 1
    best_time = time_value
    best_distance_to_pitch = abs(time_value - pitch_time)
    
    # Try increasing manpower from 2 onwards
    for manpower in range(2, max_operators + 1):
        time_per_op = time_value / manpower
        distance_to_pitch = abs(time_per_op - pitch_time)
        
        # If this is better (closer to Pitch Time), use it
        if distance_to_pitch < best_distance_to_pitch:
            best_manpower = manpower
            best_time = time_per_op
            best_distance_to_pitch = distance_to_pitch
        
        # If we've already gone below Pitch Time and are moving further away,
        # stop searching (it will only get worse)
        elif time_per_op < pitch_time:
            break
    
    return best_manpower, best_time


def group_and_balance(sorted_operations: List[Operation], ucl: float, lcl: float) -> List[Workstation]:
    """
    Process operations in Serial No. order and assign them to workstations,
    combining operations and adjusting manpower as needed to stay within
    the UCL/LCL band.
    
    Args:
        sorted_operations: Operations sorted by ID (ascending)
        ucl: Upper Control Limit
        lcl: Lower Control Limit
    
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
        if is_within_range(current_op.basic_time, ucl, lcl):
            # It's fine as-is: create a workstation with just this operation
            ws = Workstation(
                operations=[current_op],
                manpower=1,
                balancing_sam=current_op.basic_time
            )
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)
            continue
        
        # ===== STEP 2: Operation is outside range, look for compatible operations =====
        compatible_ops = find_compatible_operations(current_op, sorted_operations, already_grouped_ids)
        
        if compatible_ops:
            # ===== STEP 3a: Combine path (found compatible operation) =====
            # Take the first compatible operation and combine with it
            partner_op = compatible_ops[0]
            combined_time = current_op.basic_time + partner_op.basic_time
            
            # Check if combined time is now acceptable
            if is_within_range(combined_time, ucl, lcl):
                # Perfect! Combined time fits in the band
                ws = Workstation(
                    operations=[current_op, partner_op],
                    manpower=1,
                    balancing_sam=combined_time
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(partner_op.op_id)
            else:
                # Combined time is still outside the band
                # Split across multiple operators
                manpower, balancing_sam = find_best_manpower_split(combined_time, ucl, lcl)
                ws = Workstation(
                    operations=[current_op, partner_op],
                    manpower=manpower,
                    balancing_sam=balancing_sam
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
                already_grouped_ids.add(partner_op.op_id)
        else:
            # ===== STEP 3b: Standalone path (no compatible operation found) =====
            # Operation couldn't find a partner, try splitting it alone
            manpower, balancing_sam = find_best_manpower_split(current_op.basic_time, ucl, lcl)
            ws = Workstation(
                operations=[current_op],
                manpower=manpower,
                balancing_sam=balancing_sam
            )
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)
    
    return workstations
