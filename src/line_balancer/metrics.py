"""
STEP 3: CALCULATE PITCH TIME
STEP 4: CALCULATE TOLERANCE BANDS (UCL / LCL)
STEP 6: CALCULATE LINE BALANCING RATE
"""

from typing import List, Optional, Tuple

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation

DEFAULT_TOLERANCE = 0.15  # 15%, matches factory standard


def calculate_pitch_time(operations: List[Operation], total_operation_count: Optional[int] = None) -> float:
    """
    Pitch_Time = Total_Basic_Time / Total_Operation_Count

    total_operation_count lets you match the factory's real convention of
    dividing by ALL operations (including any not present in this file,
    e.g. non-stitching ones) rather than just len(operations).
    """
    total_basic_time = sum(op.basic_time for op in operations)
    count = total_operation_count or len(operations)
    if count == 0:
        raise ValueError("Total operation count cannot be zero.")
    return total_basic_time / count


def calculate_tolerance_bands(pitch_time: float, tolerance: float = DEFAULT_TOLERANCE) -> Tuple[float, float]:
    ucl = pitch_time + (pitch_time * tolerance)
    lcl = pitch_time - (pitch_time * tolerance)
    return ucl, lcl


def calculate_line_balancing_rate(
    workstations: List[Workstation],
) -> float:
    """
    Calculate Line Balancing Rate based on Bal SAM values.
    
    Formula:
    - maxBalSam = maximum Bal SAM across all workstations
    - SUM = sum of (maxBalSam - balSamEachCell) for all workstations
    - negativeRate = SUM / 60
    - lineBalancingRate = 100 - negativeRate
    
    Args:
        workstations: List of Workstation objects with balancing_sam values
    
    Returns:
        Line Balancing Rate as a percentage
    """
    if not workstations:
        return 0.0
    
    # Get all Bal SAM values
    bal_sams = [ws.balancing_sam for ws in workstations]
    
    # Find maximum Bal SAM
    max_bal_sam = max(bal_sams)
    
    # Calculate sum of differences
    sum_of_differences = sum(max_bal_sam - bal_sam for bal_sam in bal_sams)
    
    # Compute negative rate
    negative_rate = sum_of_differences / 60
    
    # Compute final balance rate
    line_balancing_rate = 100 - negative_rate
    
    return max(0.0, line_balancing_rate)  # Ensure non-negative
