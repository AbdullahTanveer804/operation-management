"""
STEP 3: CALCULATE PITCH TIME
STEP 4: CALCULATE TOLERANCE BANDS (UCL / LCL)
STEP 6: CALCULATE LINE BALANCING RATE
"""

from typing import List, Tuple

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation

DEFAULT_TOLERANCE = 0.15  # 15%, matches factory standard


def calculate_pitch_time(operations: List[Operation]) -> float:
    """
    Pitch_Time = Total_Basic_Time / Total_Operation_Count
    
    Calculates pitch time based on operations from the input file.
    """
    total_basic_time = sum(op.basic_time for op in operations)
    count = len(operations)
    if count == 0:
        raise ValueError("Total operation count cannot be zero.")
    return total_basic_time / count


def calculate_pitch_time_from_target(production_target: int, shift_time_minutes: float, tolerance: float = DEFAULT_TOLERANCE) -> float:
    """
    Calculate pitch time from production target and shift time.
    
    Formula:
    - UCL = (Production Target / Shift time) * 60
    - Pitch time = UCL - (UCL * tolerance)
    
    Args:
        production_target: Production target (number of units)
        shift_time_minutes: Shift time in minutes
        tolerance: Tolerance percentage (default 0.15 for 15%)
    
    Returns:
        Calculated pitch time
    """
    if production_target <= 0:
        raise ValueError("Production target must be a positive number.")
    if shift_time_minutes <= 0:
        raise ValueError("Shift time must be a positive number.")
    
    # Calculate UCL
    ucl = (production_target / shift_time_minutes) * 60
    
    # Calculate pitch time = UCL - (UCL * tolerance)
    pitch_time = ucl - (ucl * tolerance)
    
    return pitch_time


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


def calculate_balance_delay(
    workstations: List[Workstation],
    operations: List,
) -> float:
    """
    Calculate Balance Delay percentage.
    
    Formula:
    [(Total Manpower × Max balanced SAM - total basic time) / (Total Manpower × Max balanced SAM)] × 100
    
    Args:
        workstations: List of Workstation objects with balancing_sam values
        operations: List of Operation objects with basic_time values
    
    Returns:
        Balance Delay as a percentage
    """
    if not workstations:
        return 0.0
    
    # Calculate total manpower (actual physical machines after balancing)
    total_manpower = sum(ws.manpower for ws in workstations)
    
    # Get maximum balanced SAM (bottleneck)
    max_balanced_sam = max(ws.balancing_sam for ws in workstations)
    
    # Calculate total basic time (SAM)
    total_basic_time = sum(op.basic_time for op in operations)
    
    # Calculate balance delay
    numerator = (total_manpower * max_balanced_sam) - total_basic_time
    denominator = total_manpower * max_balanced_sam
    
    if denominator == 0:
        return 0.0
    
    balance_delay = (numerator / denominator) * 100
    
    return max(0.0, balance_delay)  # Ensure non-negative


def calculate_line_efficiency(
    workstations: List[Workstation],
    operations: List,
    production_target: int,
    shift_time_minutes: float,
) -> float:
    """
    Calculate Line Efficiency percentage.
    
    Formula:
    [(Production target × Total Basic Time) / (Total Manpower × Shift Time)] × 100
    
    Args:
        workstations: List of Workstation objects with manpower values
        operations: List of Operation objects with basic_time values
        production_target: Production target (number of units)
        shift_time_minutes: Shift time in minutes (will be converted to seconds)
    
    Returns:
        Line Efficiency as a percentage
    """
    if not workstations or production_target <= 0 or shift_time_minutes <= 0:
        return 0.0
    
    # Calculate total manpower (actual physical machines after balancing)
    total_manpower = sum(ws.manpower for ws in workstations)
    
    # Calculate total basic time (SAM)
    total_basic_time = sum(op.basic_time for op in operations)
    
    # Convert shift time from minutes to seconds
    shift_time_seconds = shift_time_minutes * 60
    
    # Calculate line efficiency
    numerator = production_target * total_basic_time
    denominator = total_manpower * shift_time_seconds
    
    if denominator == 0:
        return 0.0
    
    line_efficiency = (numerator / denominator) * 100
    
    return max(0.0, line_efficiency)  # Ensure non-negative


def calculate_smoothing_index(workstations: List[Workstation]) -> float:
    """
    Calculate Smoothing Index based on Balancing SAM values.
    
    Formula:
    Smoothness Index = √[Σ((Bottleneck cycle time in minutes - cycle time of workstation i in minutes)²)]
    
    Steps:
    1. Get all Balancing SAM values (in seconds)
    2. Convert to minutes (divide by 60)
    3. Find bottleneck (maximum Balancing SAM in minutes)
    4. Calculate squared differences from bottleneck for each workstation
    5. Sum all squared differences
    6. Take square root of the sum
    
    Args:
        workstations: List of Workstation objects with balancing_sam values
    
    Returns:
        Smoothing Index in minutes
    """
    if not workstations:
        return 0.0
    
    # Get all Balancing SAM values and convert to minutes
    balancing_sam_minutes = [ws.balancing_sam / 60 for ws in workstations]
    
    # Find bottleneck (maximum Balancing SAM in minutes)
    bottleneck = max(balancing_sam_minutes)
    
    # Calculate squared differences from bottleneck
    squared_differences = [(bottleneck - sam) ** 2 for sam in balancing_sam_minutes]
    
    # Sum all squared differences
    sum_squared_differences = sum(squared_differences)
    
    # Take square root
    smoothing_index = sum_squared_differences ** 0.5
    
    return smoothing_index
