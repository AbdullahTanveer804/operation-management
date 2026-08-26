"""
Before Balancing Metrics Calculation

Calculates metrics based on the original input operations before any balancing occurs.
These metrics provide a baseline comparison to the after-balancing metrics.

Note: Before balancing supports the same time methods as after balancing:
- Manual: Uses provided Takt Time
- Target: Calculates Takt Time from production target and shift time  
- Auto: Calculates Pitch Time from operations data

Tolerance Input Format: The tolerance parameter expects values as decimal (e.g., 0.15 for 15%).
Frontend input is expected as percentage (e.g., 15) and should be converted to decimal (e.g., 0.15) before calling these functions.
"""

from typing import List, Tuple, Optional

if __package__ in {None, ""}:
    from models import Operation
else:
    from .models import Operation

DEFAULT_TOLERANCE = 0.15  # 15%, hard coded as per requirements


def calculate_pitch_time_from_target(production_target: int, shift_time_minutes: float) -> float:
    """
    Calculate Takt Time from production target and shift time.
    
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
        raise ValueError("Production target must be a positive number.")
    if shift_time_minutes <= 0:
        raise ValueError("Shift time must be a positive number.")
    
    # Calculate takt time in minutes
    takt_time_minutes = shift_time_minutes / production_target
    
    # Convert to seconds for internal use
    takt_time_seconds = takt_time_minutes * 60
    
    return takt_time_seconds


def calculate_before_pitch_time(operations: List[Operation]) -> float:
    """
    Calculate pitch time from input operations before balancing (auto method).
    
    Note: This is for auto-calculation only (method = "auto"), so it's called "Pitch Time".
    For manual or target methods, the calculate_all_before_metrics function handles those cases.
    
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
        tolerance: Tolerance percentage as decimal (default 0.15 for 15%). Note: Input from frontend is expected as percentage (e.g., 15) and converted to decimal (e.g., 0.15) before calling this function.
    
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


def calculate_before_throughput_rate(operations: List[Operation]) -> float:
    """
    Calculate throughput rate before balancing (maximum basic time across all operations).
    Applies ONLY to By Target method.
    
    Args:
        operations: List of Operation objects from input file
        
    Returns:
        Throughput rate in seconds
    """
    if not operations:
        return 0.0
    return max(op.basic_time for op in operations)


def calculate_before_required_minutes(
    operations: List[Operation],
    production_target: int,
    line_efficiency: float,
) -> Optional[float]:
    """
    Calculate required minutes before balancing.
    Applies ONLY to By Target method.
    
    Formula:
    Required Minutes = (Target × SAM_total_minutes) / (Manpower × Required_Line_Efficiency_fraction)
    
    Args:
        operations: List of Operation objects from input file
        production_target: Production target (customer demand)
        line_efficiency: Before-balancing Line Efficiency percentage
        
    Returns:
        Required minutes
    """
    if not operations or production_target <= 0 or line_efficiency is None or line_efficiency <= 0:
        return None
    
    total_manpower = len(operations)
    if total_manpower <= 0:
        return None
        
    sam_total_minutes = sum(op.basic_time for op in operations) / 60
    required_line_efficiency_fraction = line_efficiency / 100
    denominator = total_manpower * required_line_efficiency_fraction
    
    if denominator <= 0:
        return None
        
    return (production_target * sam_total_minutes) / denominator


def calculate_all_before_metrics(
    operations: List[Operation],
    production_target: int = None,
    shift_time_minutes: float = None,
    tolerance: float = DEFAULT_TOLERANCE,
    pitch_time_method: str = "auto",
    manual_pitch_time: Optional[float] = None,
    efficiency_percentage: Optional[float] = None,
    available_time_minutes: Optional[float] = None,
) -> dict:
    """
    Calculate all before-balancing metrics.
    
    Args:
        operations: List of Operation objects from input file
        production_target: Optional production target for line efficiency calculation and takt time calculation
        shift_time_minutes: Optional shift time in minutes for line efficiency calculation and takt time calculation
        tolerance: Tolerance percentage as decimal (default 0.15 for 15%). Note: Input from frontend is expected as percentage (e.g., 15) and converted to decimal (e.g., 0.15) before calling this function. Only used for auto method.
        pitch_time_method: Method for calculating time ("auto", "manual", "target")
        manual_pitch_time: Optional manual takt time (required when method is "manual")
        efficiency_percentage: Optional efficiency percentage for Target calculation (0-100)
        available_time_minutes: Optional available time in minutes for Target calculation
    
    Returns:
        Dictionary containing all before-balancing metrics
    """
    # Use default tolerance for auto method if not provided
    if pitch_time_method == "auto" and tolerance is None:
        tolerance = DEFAULT_TOLERANCE
    
    # Initialize auto_pitch_time for By Target method
    auto_pitch_time = None
    
    # Calculate time based on method
    if pitch_time_method == "manual":
        if manual_pitch_time is None or manual_pitch_time <= 0:
            raise ValueError("Manual takt time must be provided and positive when method is 'manual'.")
        pitch_time = manual_pitch_time
        pitch_time_source = "manual"
        # Clear target-related parameters for manual method
        production_target = None
        shift_time_minutes = None
        # No tolerance bands for manual method
        ucl = None
        lcl = None
    elif pitch_time_method == "target":
        if production_target is None or production_target <= 0:
            raise ValueError("Production target must be provided and positive when method is 'target'.")
        if shift_time_minutes is None or shift_time_minutes <= 0:
            raise ValueError("Shift time must be provided and positive when method is 'target'.")
        takt_time = calculate_pitch_time_from_target(production_target, shift_time_minutes)
        pitch_time = takt_time
        pitch_time_source = "By Target"
        # Calculate auto pitch time and tolerance bands for display purposes
        auto_pitch_time = calculate_before_pitch_time(operations)
        if tolerance is None:
            tolerance = DEFAULT_TOLERANCE
        auto_ucl, auto_lcl = calculate_before_tolerance_bands(auto_pitch_time, tolerance)
        # Use auto-computed values for display
        ucl = auto_ucl
        lcl = auto_lcl
    else:  # auto (default)
        pitch_time = calculate_before_pitch_time(operations)
        pitch_time_source = "calculated"
        # Clear target-related parameters for auto method
        production_target = None
        shift_time_minutes = None
        # Calculate tolerance bands for auto method
        ucl, lcl = calculate_before_tolerance_bands(pitch_time, tolerance)
    
    # Calculate basic metrics
    num_operations = calculate_before_num_operations(operations)
    total_manpower = calculate_before_total_manpower(operations)
    total_basic_time = calculate_before_total_basic_time(operations)
    
    # Calculate derived metrics
    balancing_rate = calculate_before_balancing_rate(operations)
    balance_delay = calculate_before_balance_delay(operations)
    smoothing_index = calculate_before_smoothing_index(operations)
    
    # Calculate line efficiency if production target and shift time are provided and method is target
    line_efficiency = None
    if pitch_time_method == "target" and production_target is not None and shift_time_minutes is not None:
        line_efficiency = calculate_before_line_efficiency(operations, production_target, shift_time_minutes)
    
    # Calculate Throughput Rate and Required Minutes for By Target method
    throughput_rate = None
    required_minutes = None
    if pitch_time_method == "target":
        throughput_rate = calculate_before_throughput_rate(operations)
        if line_efficiency is not None:
            required_minutes = calculate_before_required_minutes(operations, production_target, line_efficiency)

    # Calculate Target if both efficiency and available time are provided
    target = None
    if efficiency_percentage is not None and available_time_minutes is not None:
        # Target = (Efficiency% × Total Manpower × Available Time(minutes)) / Total Basic Time(SAM in Minutes)
        total_basic_time_minutes_for_target = total_basic_time / 60  # Convert to minutes
        if total_basic_time_minutes_for_target > 0:
            target = (efficiency_percentage / 100 * total_manpower * available_time_minutes) / total_basic_time_minutes_for_target
    
    # Calculate Labour Productivity
    # Labour Productivity = Production Target (Customer Demand) / Total Manpower
    # Use production_target if provided (target method), otherwise use calculated target
    labour_productivity = None
    target_for_productivity = production_target if production_target is not None else target
    if target_for_productivity is not None and total_manpower > 0:
        labour_productivity = target_for_productivity / total_manpower
    
    # Build return dictionary
    result = {
        "pitch_time": pitch_time,
        "pitch_time_source": pitch_time_source,
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
        "target": target,
        "labour_productivity": labour_productivity,
        "throughput_rate": throughput_rate,
        "required_minutes": required_minutes,
    }
    
    # Include tolerance for auto and By Target methods
    if pitch_time_source == "calculated" or pitch_time_source == "By Target":
        result["tolerance"] = tolerance
    
    # For By Target method, also include auto-computed values for display
    if pitch_time_source == "By Target":
        result["auto_pitch_time"] = auto_pitch_time
    
    return result
