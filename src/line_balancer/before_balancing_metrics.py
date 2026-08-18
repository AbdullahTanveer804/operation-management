"""
Before Balancing Metrics Calculation

Calculates metrics based on the original input operations before any balancing occurs.
These metrics provide a baseline comparison to the after-balancing metrics.
"""

from typing import List, Tuple

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation

DEFAULT_TOLERANCE = 0.15  # 15%, hard coded as per requirements


def calculate_before_pitch_time(operations: List[Operation]) -> float:
    """
    Calculate pitch time from input operations before balancing.
    
    Formula: Pitch_Time = Total_Basic_Time / Total_Operation_Count
    
    Args:
        operations: List of Operation objects from input file
    
    Returns:
        Pitch time in seconds
    """
    total_basic_time = sum(op.basic_time for op in operations)
    count = len(operations)
    if count == 0:
        raise ValueError("Total operation count cannot be zero.")
    return total_basic_time / count


def calculate_before_tolerance_bands(pitch_time: float, tolerance: float = DEFAULT_TOLERANCE) -> Tuple[float, float]:
    """
    Calculate UCL and LCL based on pitch time before balancing.
    
    Formula:
    - UCL = pitch_time + (pitch_time * tolerance)
    - LCL = pitch_time - (pitch_time * tolerance)
    
    Args:
        pitch_time: Calculated pitch time
        tolerance: Tolerance percentage (hardcoded to 0.15 for 15%)
    
    Returns:
        Tuple of (UCL, LCL) in seconds
    """
    ucl = pitch_time + (pitch_time * tolerance)
    lcl = pitch_time - (pitch_time * tolerance)
    return ucl, lcl


def calculate_before_num_operations(operations: List[Operation]) -> int:
    """
    Get the number of operations from input file.
    
    Args:
        operations: List of Operation objects from input file
    
    Returns:
        Number of operations
    """
    return len(operations)


def calculate_before_total_manpower(operations: List[Operation]) -> int:
    """
    Calculate total manpower before balancing.
    Each operation has 1 man as per input.
    
    Args:
        operations: List of Operation objects from input file
    
    Returns:
        Total manpower (equals number of operations)
    """
    return len(operations)


def calculate_before_total_basic_time(operations: List[Operation]) -> float:
    """
    Calculate total basic time (SAM) from input file.
    
    Args:
        operations: List of Operation objects from input file
    
    Returns:
        Total basic time in seconds
    """
    return sum(op.basic_time for op in operations)


def calculate_before_balancing_rate(operations: List[Operation]) -> float:
    """
    Calculate balancing rate before balancing using basic time (SAM) from input.
    
    Formula:
    - maxSam = maximum basic time across all operations
    - SUM = sum of (maxSam - basicTimeEachOp) for all operations
    - negativeRate = SUM / 60
    - lineBalancingRate = 100 - negativeRate
    
    Args:
        operations: List of Operation objects with basic_time values
    
    Returns:
        Line Balancing Rate as a percentage
    """
    if not operations:
        return 0.0
    
    # Get all basic time values
    basic_times = [op.basic_time for op in operations]
    
    # Find maximum basic time
    max_basic_time = max(basic_times)
    
    # Calculate sum of differences
    sum_of_differences = sum(max_basic_time - basic_time for basic_time in basic_times)
    
    # Compute negative rate
    negative_rate = sum_of_differences / 60
    
    # Compute final balance rate
    line_balancing_rate = 100 - negative_rate
    
    return max(0.0, line_balancing_rate)  # Ensure non-negative


def calculate_before_line_efficiency(
    operations: List[Operation],
    production_target: int,
    shift_time_minutes: float,
) -> float:
    """
    Calculate line efficiency before balancing.
    
    Formula:
    [(Production target × Total Basic Time) / (Total Manpower × Shift Time)] × 100
    
    Uses manpower before balancing (which equals number of operations).
    
    Args:
        operations: List of Operation objects with basic_time values
        production_target: Production target (number of units)
        shift_time_minutes: Shift time in minutes (will be converted to seconds)
    
    Returns:
        Line Efficiency as a percentage
    """
    if not operations or production_target <= 0 or shift_time_minutes <= 0:
        return 0.0
    
    # Calculate total manpower (equals number of operations before balancing)
    total_manpower = len(operations)
    
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


def calculate_before_balance_delay(operations: List[Operation]) -> float:
    """
    Calculate balance delay before balancing.
    
    Formula:
    [(Total Manpower × Max basic time - Total basic time) / (Total Manpower × Max basic time)] × 100
    
    Args:
        operations: List of Operation objects with basic_time values
    
    Returns:
        Balance Delay as a percentage
    """
    if not operations:
        return 0.0
    
    # Calculate total manpower (equals number of operations before balancing)
    total_manpower = len(operations)
    
    # Get maximum basic time (bottleneck)
    max_basic_time = max(op.basic_time for op in operations)
    
    # Calculate total basic time (SAM)
    total_basic_time = sum(op.basic_time for op in operations)
    
    # Calculate balance delay
    numerator = (total_manpower * max_basic_time) - total_basic_time
    denominator = total_manpower * max_basic_time
    
    if denominator == 0:
        return 0.0
    
    balance_delay = (numerator / denominator) * 100
    
    return max(0.0, balance_delay)  # Ensure non-negative


def calculate_before_smoothing_index(operations: List[Operation]) -> float:
    """
    Calculate smoothing index before balancing based on basic time values.
    
    Formula:
    Smoothness Index = √[Σ((Bottleneck cycle time in minutes - cycle time of operation i in minutes)²)]
    
    Steps:
    1. Get all basic time values (in seconds)
    2. Convert to minutes (divide by 60)
    3. Find bottleneck (maximum basic time in minutes)
    4. Calculate squared differences from bottleneck for each operation
    5. Sum all squared differences
    6. Take square root of the sum
    
    Args:
        operations: List of Operation objects with basic_time values
    
    Returns:
        Smoothing Index in minutes
    """
    if not operations:
        return 0.0
    
    # Get all basic time values and convert to minutes
    basic_time_minutes = [op.basic_time / 60 for op in operations]
    
    # Find bottleneck (maximum basic time in minutes)
    bottleneck = max(basic_time_minutes)
    
    # Calculate squared differences from bottleneck
    squared_differences = [(bottleneck - sam) ** 2 for sam in basic_time_minutes]
    
    # Sum all squared differences
    sum_squared_differences = sum(squared_differences)
    
    # Take square root
    smoothing_index = sum_squared_differences ** 0.5
    
    return smoothing_index


def calculate_all_before_metrics(
    operations: List[Operation],
    production_target: int = None,
    shift_time_minutes: float = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict:
    """
    Calculate all before-balancing metrics.
    
    Args:
        operations: List of Operation objects from input file
        production_target: Optional production target for line efficiency calculation
        shift_time_minutes: Optional shift time in minutes for line efficiency calculation
        tolerance: Tolerance percentage (default 0.15 for 15%)
    
    Returns:
        Dictionary containing all before-balancing metrics
    """
    # Calculate pitch time
    pitch_time = calculate_before_pitch_time(operations)
    
    # Calculate tolerance bands
    ucl, lcl = calculate_before_tolerance_bands(pitch_time, tolerance)
    
    # Calculate basic metrics
    num_operations = calculate_before_num_operations(operations)
    total_manpower = calculate_before_total_manpower(operations)
    total_basic_time = calculate_before_total_basic_time(operations)
    
    # Calculate derived metrics
    balancing_rate = calculate_before_balancing_rate(operations)
    balance_delay = calculate_before_balance_delay(operations)
    smoothing_index = calculate_before_smoothing_index(operations)
    
    # Calculate line efficiency if production target and shift time are provided
    line_efficiency = None
    if production_target is not None and shift_time_minutes is not None:
        line_efficiency = calculate_before_line_efficiency(operations, production_target, shift_time_minutes)
    
    return {
        "pitch_time": pitch_time,
        "ucl": ucl,
        "lcl": lcl,
        "num_operations": num_operations,
        "total_manpower": total_manpower,
        "total_basic_time": total_basic_time,
        "total_basic_time_minutes": total_basic_time / 60,  # Convert to minutes for display
        "balancing_rate": balancing_rate,
        "line_efficiency": line_efficiency,
        "balance_delay": balance_delay,
        "smoothing_index": smoothing_index,
        "tolerance": tolerance,
    }
