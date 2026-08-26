"""
STEP 3: CALCULATE PITCH TIME / TAKT TIME
STEP 4: CALCULATE TOLERANCE BANDS (UCL / LCL)
STEP 6: CALCULATE LINE BALANCING RATE

Note: When time method is manual or calculated by target, it's called "Takt Time".
When auto-calculated from operations, it's called "Pitch Time".
"""

from typing import List, Optional, Tuple

if __package__ in {None, ""}:
    from models import Operation, Workstation
else:
    from .models import Operation, Workstation

DEFAULT_TOLERANCE = 0.15  # 15%, matches factory standard


def calculate_pitch_time(operations: List[Operation]) -> float:
    """
    Pitch_Time = Total_Basic_Time / Total_Operation_Count
    
    Calculates pitch time based on operations from the input file.
    Note: This is for auto-calculation only, so it's called "Pitch Time".
    """
    total_basic_time = sum(op.basic_time for op in operations)
    count = len(operations)
    if count == 0:
        raise ValueError("Total operation count cannot be zero.")
    return total_basic_time / count


def calculate_pitch_time_from_target(production_target: int, shift_time_minutes: float) -> float:
    """
    Calculate Takt Time from production target and shift time.
    
    Note: When calculated from target, this is called "Takt Time" in the UI,
    though the function name remains for backward compatibility.
    
    Formula:
    - Takt Time = (Shift time / Production Target) - result is in minutes
    - Convert to seconds for internal use (multiply by 60)
    
    Args:
        production_target: Production target (number of units)
        shift_time_minutes: Shift time in minutes
    
    Returns:
        Calculated takt time in seconds
    """
    if production_target <= 0:
        raise ValueError("Production target must be positive.")
    if shift_time_minutes <= 0:
        raise ValueError("Shift time must be positive.")
    
    # Calculate takt time in minutes
    takt_time_minutes = shift_time_minutes / production_target
    
    # Convert to seconds for internal use
    takt_time_seconds = takt_time_minutes * 60
    
    return takt_time_seconds


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


def calculate_throughput_rate(workstations: List[Workstation]) -> float:
    """
    Calculate throughput rate after balancing (maximum balancing SAM across all composite operations/workstations).
    Applies ONLY to By Target method.
    
    Args:
        workstations: List of Workstation objects with balancing_sam values
        
    Returns:
        Throughput rate in seconds
    """
    if not workstations:
        return 0.0
    return max(ws.balancing_sam for ws in workstations)


def calculate_required_minutes(
    production_target: int,
    workstations: List[Workstation],
    line_efficiency: float,
) -> Optional[float]:
    """
    Calculate required minutes after balancing.
    Applies ONLY to By Target method.
    
    Formula:
    Required Minutes = (Target × SAM_total_minutes) / (Manpower × Required_Line_Efficiency_fraction)
    
    Where:
    - Target: production_target (customer demand)
    - SAM_total_minutes: SUM(balancing_SAM_j in seconds, all workstations) / 60
    - Manpower: sum of manpower across all workstations
    - Required_Line_Efficiency_fraction: line_efficiency / 100
    
    Args:
        production_target: Production target (customer demand)
        workstations: List of Workstation objects with balancing_sam and manpower
        line_efficiency: After-balancing Line Efficiency percentage
        
    Returns:
        Required minutes
    """
    if not workstations or production_target <= 0 or line_efficiency is None or line_efficiency <= 0:
        return None
        
    total_manpower = sum(ws.manpower for ws in workstations)
    if total_manpower <= 0:
        return None
        
    sam_total_minutes = sum(ws.balancing_sam for ws in workstations) / 60
    required_line_efficiency_fraction = line_efficiency / 100
    denominator = total_manpower * required_line_efficiency_fraction
    
    if denominator <= 0:
        return None
        
    return (production_target * sam_total_minutes) / denominator
