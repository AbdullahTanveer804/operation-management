"""
STEP 3: CALCULATE PITCH TIME
STEP 4: CALCULATE TOLERANCE BANDS (UCL / LCL)
STEP 6: CALCULATE LINE EFFICIENCY
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


def calculate_line_efficiency(
    operations: List[Operation],
    workstations: List[Workstation],
    pitch_time: float,
) -> float:
    """Line_Efficiency = (Total_Basic_Time / (Total_M/P * Pitch_Time)) * 100"""
    total_basic_time = sum(op.basic_time for op in operations)
    total_manpower = sum(ws.manpower for ws in workstations)
    if total_manpower == 0 or pitch_time == 0:
        return 0.0
    return (total_basic_time / (total_manpower * pitch_time)) * 100
