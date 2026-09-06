"""
Line Balancing by Composite Machines - Takt vs Pitch Comparison

In this balancing mode:
- Any machine type can combine with any different machine type (e.g. SNLS + 3TOL, 5TOL + SNLS)
  EXCEPT:
  - Press can ONLY combine with another Press machine (never with regular machines or helper categories)
- Predecessor dependency is strictly respected:
  An operation cannot be placed ahead of the operation it depends on.
- Runs both Method A (Takt Time Balancing) and Method B (IE Pitch Balancing)
- Computes all comparison KPIs and recommendations
- Standalone CLI execution support
"""

import argparse
import math
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set, Tuple
import pandas as pd

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    file_path = Path(__file__).resolve()
    project_root = file_path.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

try:
    from .models import Operation, Workstation
    from .sequencing import sort_by_id
    from .balancing import find_best_manpower_split
    from .metrics import (
        calculate_pitch_time,
        calculate_pitch_time_from_target,
        calculate_tolerance_bands,
        calculate_line_balancing_rate,
        calculate_balance_delay,
        calculate_line_efficiency,
        calculate_smoothing_index,
    )
    from .before_balancing_metrics import (
        calculate_before_balancing_rate,
        calculate_before_balance_delay,
        calculate_before_smoothing_index,
        calculate_before_line_efficiency,
    )
    from .comparison_recommendations import generate_takt_vs_pitch_recommendations
    from .io_utils import read_operations
except ImportError:
    from src.line_balancer.models import Operation, Workstation
    from src.line_balancer.sequencing import sort_by_id
    from src.line_balancer.balancing import find_best_manpower_split
    from src.line_balancer.metrics import (
        calculate_pitch_time,
        calculate_pitch_time_from_target,
        calculate_tolerance_bands,
        calculate_line_balancing_rate,
        calculate_balance_delay,
        calculate_line_efficiency,
        calculate_smoothing_index,
    )
    from src.line_balancer.before_balancing_metrics import (
        calculate_before_balancing_rate,
        calculate_before_balance_delay,
        calculate_before_smoothing_index,
        calculate_before_line_efficiency,
    )
    from src.line_balancer.comparison_recommendations import generate_takt_vs_pitch_recommendations
    from src.line_balancer.io_utils import read_operations


def is_press_machine(machine_type: str) -> bool:
    """
    Check if a machine type is a Press category machine.
    Matches 'Press', 'Iron Press', etc. (case-insensitive).
    """
    if not machine_type:
        return False
    m = machine_type.strip().lower()
    return "press" in m


def can_combine_composite_machines(machine_type1: str, machine_type2: str) -> bool:
    """
    Machine combination rule for Composite Machine balancing:
    - Any machine can combine with any different machine
    - EXCEPT Press: Press can ONLY combine with Press.
      If one is Press and the other is not, they cannot combine.
    
    Args:
        machine_type1: First operation machine type
        machine_type2: Second operation machine type
        
    Returns:
        True if machines can be combined, False otherwise
    """
    is_press1 = is_press_machine(machine_type1)
    is_press2 = is_press_machine(machine_type2)

    # If one is Press and the other is not -> cannot combine
    if is_press1 != is_press2:
        return False

    # If both are Press -> can combine
    # If neither is Press -> any machine can combine with any other machine
    return True


def check_predecessor_constraint(op1: Operation,
                                 op2: Operation,
                                 already_grouped_ids: Set[int]) -> bool:
    """
    Check if two operations can be combined without violating predecessor ordering.
    
    RULE: An operation cannot be placed ahead of the operation it depends on.
    This means every predecessor ID of op1 and op2 must either:
    1. Be already grouped in an earlier workstation, OR
    2. Be op1 or op2 itself.
    """
    all_predecessors = set(op1.predecessors) | set(op2.predecessors)
    for pred_id in all_predecessors:
        if pred_id not in already_grouped_ids and pred_id != op1.op_id and pred_id != op2.op_id:
            return False
    return True


def find_compatible_composite_operations(
    current_op: Operation,
    all_operations: List[Operation],
    already_grouped_ids: Set[int],
) -> List[Operation]:
    """
    Find all operations that can be combined with current_op under composite machine rules.
    """
    compatible = []
    for other_op in all_operations:
        if other_op.op_id == current_op.op_id:
            continue
        if other_op.op_id in already_grouped_ids:
            continue
        if not can_combine_composite_machines(current_op.machine_type, other_op.machine_type):
            continue
        if check_predecessor_constraint(current_op, other_op, already_grouped_ids):
            compatible.append(other_op)
    return compatible


def balance_composite_method_a_takt(sorted_operations: List[Operation],
                                    takt_time: float) -> List[Workstation]:
    """
    Method A — Takt Time Balancing with Composite Machine capability.
    
    - Ceiling = Takt Time (Shift Time * 60 / Production Target)
    - Strict mode — zero relaxation.
    - Merge compatible cross-machine ops up to Takt ceiling using best-fit matching.
    - Press can only combine with Press.
    - Any single op exceeding Takt gets manpower-split using divide-and-increment.
    """
    workstations: List[Workstation] = []
    already_grouped_ids: Set[int] = set()

    for current_op in sorted_operations:
        if current_op.op_id in already_grouped_ids:
            continue

        compatible_ops = find_compatible_composite_operations(
            current_op, sorted_operations, already_grouped_ids)

        valid_candidates = []
        for partner_op in compatible_ops:
            combined_time = current_op.basic_time + partner_op.basic_time
            if combined_time <= takt_time:
                diff = abs(combined_time - takt_time)
                valid_candidates.append(
                    (diff, partner_op.op_id, partner_op, combined_time))

        if valid_candidates:
            # Pick best match: closest to Takt Time, tie-breaker op_id
            valid_candidates.sort(key=lambda x: (x[0], x[1]))
            _, _, best_partner, best_combined_time = valid_candidates[0]
            ws = Workstation(
                operations=[current_op, best_partner],
                manpower=1,
                balancing_sam=best_combined_time,
            )
            workstations.append(ws)
            already_grouped_ids.add(current_op.op_id)
            already_grouped_ids.add(best_partner.op_id)
        else:
            if current_op.basic_time <= takt_time:
                ws = Workstation(
                    operations=[current_op],
                    manpower=1,
                    balancing_sam=current_op.basic_time,
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
            else:
                manpower, balancing_sam = find_best_manpower_split(
                    current_op.basic_time,
                    ucl=takt_time,
                    lcl=None,
                    strict=True)
                ws = Workstation(
                    operations=[current_op],
                    manpower=manpower,
                    balancing_sam=balancing_sam,
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)

    return workstations


def balance_composite_method_b_pitch(
    sorted_operations: List[Operation],
    pitch_time: float,
    ucl: float,
    lcl: float,
    takt_time: float,
) -> Tuple[List[Workstation], List[str]]:
    """
    Method B — IE Pitch Balancing with Composite Machine capability.
    
    - Ceiling for MERGING = UCL (min(UCL, Takt Time) for safety).
      Evaluates compatible candidates across machines (except Press only with Press)
      and selects the Best Match (closest to Pitch Time <= UCL).
    - Ceiling for SPLITTING single operations = Takt Time.
      Single op > Takt Time gets manpower-split (2..n) until time/manpower <= Takt Time.
    """
    workstations: List[Workstation] = []
    statuses: List[str] = []
    already_grouped_ids: Set[int] = set()

    merge_ceiling = min(ucl, takt_time) if ucl is not None else takt_time

    for current_op in sorted_operations:
        if current_op.op_id in already_grouped_ids:
            continue

        compatible_ops = find_compatible_composite_operations(
            current_op, sorted_operations, already_grouped_ids)

        valid_candidates = []
        for partner_op in compatible_ops:
            combined_time = current_op.basic_time + partner_op.basic_time
            if combined_time <= merge_ceiling:
                diff_from_pitch = abs(combined_time - pitch_time) if pitch_time is not None else 0.0
                valid_candidates.append(
                    (diff_from_pitch, partner_op.op_id, partner_op, combined_time))

        if valid_candidates:
            valid_candidates.sort(key=lambda x: (x[0], x[1]))
            _, _, best_partner, best_combined_time = valid_candidates[0]

            ws = Workstation(
                operations=[current_op, best_partner],
                manpower=1,
                balancing_sam=best_combined_time,
            )
            workstations.append(ws)
            statuses.append("OK")
            already_grouped_ids.add(current_op.op_id)
            already_grouped_ids.add(best_partner.op_id)
        else:
            total = current_op.basic_time
            if total <= takt_time:
                status = "OK" if (ucl is None or total <= ucl) else "> UCL"
                ws = Workstation(
                    operations=[current_op],
                    manpower=1,
                    balancing_sam=total,
                )
                workstations.append(ws)
                statuses.append(status)
                already_grouped_ids.add(current_op.op_id)
            else:
                manpower, balancing_sam = find_best_manpower_split(
                    total, ucl=takt_time, lcl=None, strict=True)
                if ucl is not None and balancing_sam <= ucl:
                    status = "OK"
                elif balancing_sam <= takt_time:
                    status = "> UCL"
                else:
                    status = "> Takt Time"

                ws = Workstation(
                    operations=[current_op],
                    manpower=manpower,
                    balancing_sam=balancing_sam,
                )
                workstations.append(ws)
                statuses.append(status)
                already_grouped_ids.add(current_op.op_id)

    return workstations, statuses


def calculate_smoothing_index_seconds(
    station_times_and_manpower: List[Tuple[float, int]],
    c_max: float,
) -> float:
    """Calculate Smoothing Index in SECONDS per individual operator position."""
    sum_squared_diff = 0.0
    for time_per_op, manpower in station_times_and_manpower:
        diff = c_max - time_per_op
        sum_squared_diff += (diff**2) * manpower
    return math.sqrt(sum_squared_diff)


def build_composite_method_report_df(
    workstations: List[Workstation],
    time_column_name: str,
    time_column_value: float,
    ucl: Optional[float] = None,
    lcl: Optional[float] = None,
    statuses: Optional[List[str]] = None,
    method_type: str = "method_a",
) -> pd.DataFrame:
    """Build report DataFrame for composite balancing workstations."""
    rows = []
    for ws_num, ws in enumerate(workstations, start=1):
        op_ids = " + ".join(str(op.op_id) for op in ws.operations)
        op_names = " + ".join(op.name for op in ws.operations)
        basic_times = " + ".join(f"{op.basic_time:.1f}" for op in ws.operations)
        machine_types = " + ".join(op.machine_type for op in ws.operations)

        op_predecessor_groups = []
        for op in ws.operations:
            if op.predecessors:
                op_preds = ", ".join(str(p) for p in sorted(op.predecessors))
                op_predecessor_groups.append(op_preds)
        predecessors = "+".join(op_predecessor_groups) if op_predecessor_groups else "-"

        combined_basic_time = ws.combined_basic_time

        if statuses and ws_num - 1 < len(statuses):
            status = statuses[ws_num - 1]
        else:
            status = "OK"

        row = {
            "Composite Operations": int(ws_num),
            "Serial/Id": op_ids,
            "Operations": op_names,
            "Machine": machine_types,
            "Predecessor": predecessors,
            "Basic Time": basic_times,
            "Combined SAM": round(combined_basic_time, 1),
            "Balancing SAM": round(ws.balancing_sam, 1),
            "M/P": ws.manpower,
        }

        if method_type == "method_a":
            row["Takt Time"] = round(time_column_value, 1) if time_column_value is not None else ""
        else:
            row["Pitch Time"] = round(time_column_value, 1) if time_column_value is not None else ""
            row["LCL"] = round(lcl, 1) if lcl is not None else ""
            row["UCL"] = round(ucl, 1) if ucl is not None else ""

        row["Status"] = status
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["Composite Operations"] = df["Composite Operations"].astype(int)
        if method_type == "method_a":
            cols = [
                "Composite Operations", "Serial/Id", "Operations", "Machine",
                "Predecessor", "Basic Time", "Combined SAM",
                "Balancing SAM", "M/P", "Takt Time", "Status"
            ]
        else:
            cols = [
                "Composite Operations", "Serial/Id", "Operations", "Machine",
                "Predecessor", "Basic Time", "Combined SAM",
                "Balancing SAM", "M/P", "Pitch Time", "LCL", "UCL", "Status"
            ]
        existing_cols = [c for c in cols if c in df.columns]
        df = df[existing_cols]
    return df


def calculate_composite_takt_vs_pitch_comparison(
    operations: List[Operation],
    shift_time_minutes: float,
    production_target: int,
) -> Dict:
    """
    Run complete Takt vs Pitch comparison using Composite Machine balancing rules.
    """
    if not operations:
        raise ValueError("Operations list cannot be empty.")
    if shift_time_minutes <= 0:
        raise ValueError("Shift time must be a positive number.")
    if production_target <= 0:
        raise ValueError("Production target must be a positive number.")

    sorted_ops = sort_by_id(operations)

    available_time_seconds = shift_time_minutes * 60.0
    takt_time = calculate_pitch_time_from_target(production_target, shift_time_minutes)
    total_sam = sum(op.basic_time for op in sorted_ops)

    pitch_time_b = calculate_pitch_time(sorted_ops)
    ucl_b, lcl_b = calculate_tolerance_bands(pitch_time_b, 0.15)

    # 1. RUN METHOD A (Composite Takt Time Balancing)
    workstations_a = balance_composite_method_a_takt(sorted_ops, takt_time)
    df_a = build_composite_method_report_df(
        workstations_a,
        time_column_name="Takt Time",
        time_column_value=takt_time,
        ucl=None,
        lcl=None,
        statuses=["OK"] * len(workstations_a),
        method_type="method_a",
    )
    rows_a = df_a.to_dict("records")

    # 2. RUN METHOD B (Composite IE Pitch Balancing)
    workstations_b, statuses_b = balance_composite_method_b_pitch(
        sorted_ops, pitch_time_b, ucl_b, lcl_b, takt_time)
    df_b = build_composite_method_report_df(
        workstations_b,
        time_column_name="Pitch Time",
        time_column_value=pitch_time_b,
        ucl=ucl_b,
        lcl=lcl_b,
        statuses=statuses_b,
        method_type="method_b",
    )
    rows_b = df_b.to_dict("records")

    # 3. BEFORE BALANCING KPIS
    n_ops_before = len(sorted_ops)
    cycle_time_before = max(op.basic_time for op in sorted_ops)
    achievable_output_before = available_time_seconds / cycle_time_before if cycle_time_before > 0 else 0.0
    efficiency_before = ((total_sam / (n_ops_before * cycle_time_before)) * 100.0 if
                         (n_ops_before > 0 and cycle_time_before > 0) else 0.0)
    balance_delay_before = 100.0 - efficiency_before
    smoothing_index_seconds_before = calculate_smoothing_index_seconds(
        [(op.basic_time, 1) for op in sorted_ops], cycle_time_before)
    labour_productivity_before = (achievable_output_before / n_ops_before if n_ops_before > 0 else 0.0)

    existing_balancing_rate_before = calculate_before_balancing_rate(sorted_ops)
    existing_balance_delay_before = calculate_before_balance_delay(sorted_ops)
    existing_line_eff_before = calculate_before_line_efficiency(
        sorted_ops, production_target, shift_time_minutes)
    existing_smoothing_index_min_before = calculate_before_smoothing_index(sorted_ops)

    before_metrics = {
        "num_operations": n_ops_before,
        "total_manpower": n_ops_before,
        "total_basic_time": total_sam,
        "total_basic_time_minutes": total_sam / 60.0,
        "pitch_time": pitch_time_b,
        "ucl": ucl_b,
        "lcl": lcl_b,
        "line_balancing_rate": existing_balancing_rate_before,
        "balance_delay": existing_balance_delay_before,
        "line_efficiency": existing_line_eff_before,
        "smoothing_index": existing_smoothing_index_min_before,
        "cycle_time": cycle_time_before,
        "achievable_output": achievable_output_before,
        "efficiency_balancing_rate": efficiency_before,
        "comparison_balance_delay": balance_delay_before,
        "smoothing_index_seconds": smoothing_index_seconds_before,
        "comparison_labour_productivity": labour_productivity_before,
    }

    # 4. METHOD A KPIS
    n_ops_a = sum(ws.manpower for ws in workstations_a)
    cycle_time_a = takt_time
    achievable_output_a = available_time_seconds / cycle_time_a if cycle_time_a > 0 else 0.0
    efficiency_a = ((total_sam / (n_ops_a * cycle_time_a)) * 100.0 if
                    (n_ops_a > 0 and cycle_time_a > 0) else 0.0)
    balance_delay_a = 100.0 - efficiency_a
    smoothing_index_seconds_a = calculate_smoothing_index_seconds(
        [(ws.balancing_sam, ws.manpower) for ws in workstations_a], cycle_time_a)
    labour_productivity_a = achievable_output_a / n_ops_a if n_ops_a > 0 else 0.0

    existing_balancing_rate_a = calculate_line_balancing_rate(workstations_a)
    existing_balance_delay_a = calculate_balance_delay(workstations_a, sorted_ops)
    existing_line_eff_a = calculate_line_efficiency(
        workstations_a, sorted_ops, production_target, shift_time_minutes)
    existing_smoothing_index_min_a = calculate_smoothing_index(workstations_a)

    method_a_metrics = {
        "num_workstations": len(workstations_a),
        "total_manpower": n_ops_a,
        "total_basic_time": total_sam,
        "total_basic_time_minutes": total_sam / 60.0,
        "takt_time": takt_time,
        "pitch_time": takt_time,
        "pitch_time_source": "Takt Time",
        "ucl": None,
        "lcl": None,
        "workstations": workstations_a,
        "report_df": df_a,
        "rows": rows_a,
        "line_balancing_rate": existing_balancing_rate_a,
        "balance_delay": existing_balance_delay_a,
        "line_efficiency": existing_line_eff_a,
        "smoothing_index": existing_smoothing_index_min_a,
        "cycle_time": cycle_time_a,
        "achievable_output": achievable_output_a,
        "efficiency_balancing_rate": efficiency_a,
        "comparison_balance_delay": balance_delay_a,
        "smoothing_index_seconds": smoothing_index_seconds_a,
        "comparison_labour_productivity": labour_productivity_a,
    }

    # 5. METHOD B KPIS
    n_ops_b = sum(ws.manpower for ws in workstations_b)
    cycle_time_b = max(ws.balancing_sam for ws in workstations_b) if workstations_b else 0.0
    achievable_output_b = available_time_seconds / cycle_time_b if cycle_time_b > 0 else 0.0
    efficiency_b = ((total_sam / (n_ops_b * cycle_time_b)) * 100.0 if
                    (n_ops_b > 0 and cycle_time_b > 0) else 0.0)
    balance_delay_b = 100.0 - efficiency_b
    smoothing_index_seconds_b = calculate_smoothing_index_seconds(
        [(ws.balancing_sam, ws.manpower) for ws in workstations_b], cycle_time_b)
    labour_productivity_b = achievable_output_b / n_ops_b if n_ops_b > 0 else 0.0

    existing_balancing_rate_b = calculate_line_balancing_rate(workstations_b)
    existing_balance_delay_b = calculate_balance_delay(workstations_b, sorted_ops)
    existing_line_eff_b = calculate_line_efficiency(
        workstations_b, sorted_ops, production_target, shift_time_minutes)
    existing_smoothing_index_min_b = calculate_smoothing_index(workstations_b)

    method_b_metrics = {
        "num_workstations": len(workstations_b),
        "total_manpower": n_ops_b,
        "total_basic_time": total_sam,
        "total_basic_time_minutes": total_sam / 60.0,
        "pitch_time": pitch_time_b,
        "pitch_time_source": "IE Pitch",
        "takt_time": takt_time,
        "ucl": ucl_b,
        "lcl": lcl_b,
        "workstations": workstations_b,
        "statuses": statuses_b,
        "report_df": df_b,
        "rows": rows_b,
        "line_balancing_rate": existing_balancing_rate_b,
        "balance_delay": existing_balance_delay_b,
        "line_efficiency": existing_line_eff_b,
        "smoothing_index": existing_smoothing_index_min_b,
        "cycle_time": cycle_time_b,
        "achievable_output": achievable_output_b,
        "efficiency_balancing_rate": efficiency_b,
        "comparison_balance_delay": balance_delay_b,
        "smoothing_index_seconds": smoothing_index_seconds_b,
        "comparison_labour_productivity": labour_productivity_b,
    }

    # 6. COMPARISON MATRIX
    def get_winner(val_a: float, val_b: float, higher_is_better: bool) -> str:
        if abs(val_a - val_b) < 1e-6:
            return "tie"
        if higher_is_better:
            return "method_a" if val_a > val_b else "method_b"
        else:
            return "method_a" if val_a < val_b else "method_b"

    comparison = [
        {
            "metric": "Composite Operations",
            "key": "num_workstations",
            "unit": "stations",
            "higher_is_better": False,
            "winner": get_winner(len(workstations_a), len(workstations_b), False),
            "before": n_ops_before,
            "method_a": len(workstations_a),
            "method_b": len(workstations_b),
            "formatted_before": f"{n_ops_before}",
            "formatted_method_a": f"{len(workstations_a)}",
            "formatted_method_b": f"{len(workstations_b)}",
        },
        {
            "metric": "Total Manpower",
            "key": "total_manpower",
            "unit": "operators",
            "higher_is_better": False,
            "winner": get_winner(n_ops_a, n_ops_b, False),
            "before": n_ops_before,
            "method_a": n_ops_a,
            "method_b": n_ops_b,
            "formatted_before": f"{n_ops_before}",
            "formatted_method_a": f"{n_ops_a}",
            "formatted_method_b": f"{n_ops_b}",
        },
        {
            "metric": "Cycle Time",
            "key": "cycle_time",
            "unit": "sec",
            "higher_is_better": False,
            "winner": get_winner(cycle_time_a, cycle_time_b, False),
            "before": cycle_time_before,
            "method_a": cycle_time_a,
            "method_b": cycle_time_b,
            "formatted_before": f"{cycle_time_before:.1f} sec",
            "formatted_method_a": f"{cycle_time_a:.1f} sec",
            "formatted_method_b": f"{cycle_time_b:.1f} sec",
        },
        {
            "metric": "Achievable Output",
            "key": "achievable_output",
            "unit": "pcs/shift",
            "higher_is_better": True,
            "winner": get_winner(achievable_output_a, achievable_output_b, True),
            "before": achievable_output_before,
            "method_a": achievable_output_a,
            "method_b": achievable_output_b,
            "formatted_before": f"{achievable_output_before:.0f} pcs/shift",
            "formatted_method_a": f"{achievable_output_a:.0f} pcs/shift",
            "formatted_method_b": f"{achievable_output_b:.0f} pcs/shift",
        },
        {
            "metric": "Labour Productivity",
            "key": "comparison_labour_productivity",
            "unit": "pcs/operator",
            "higher_is_better": True,
            "winner": get_winner(labour_productivity_a, labour_productivity_b, True),
            "before": labour_productivity_before,
            "method_a": labour_productivity_a,
            "method_b": labour_productivity_b,
            "formatted_before": f"{labour_productivity_before:.1f} pcs/optr",
            "formatted_method_a": f"{labour_productivity_a:.1f} pcs/optr",
            "formatted_method_b": f"{labour_productivity_b:.1f} pcs/optr",
        },
        {
            "metric": "Efficiency (Balancing Rate)",
            "key": "efficiency_balancing_rate",
            "unit": "%",
            "higher_is_better": True,
            "winner": get_winner(efficiency_a, efficiency_b, True),
            "before": efficiency_before,
            "method_a": efficiency_a,
            "method_b": efficiency_b,
            "formatted_before": f"{efficiency_before:.1f}%",
            "formatted_method_a": f"{efficiency_a:.1f}%",
            "formatted_method_b": f"{efficiency_b:.1f}%",
        },
        {
            "metric": "Balancing Delay",
            "key": "comparison_balance_delay",
            "unit": "%",
            "higher_is_better": False,
            "winner": get_winner(balance_delay_a, balance_delay_b, False),
            "before": balance_delay_before,
            "method_a": balance_delay_a,
            "method_b": balance_delay_b,
            "formatted_before": f"{balance_delay_before:.1f}%",
            "formatted_method_a": f"{balance_delay_a:.1f}%",
            "formatted_method_b": f"{balance_delay_b:.1f}%",
        },
        {
            "metric": "Smoothing Index",
            "key": "smoothing_index_seconds",
            "unit": "sec",
            "higher_is_better": False,
            "winner": get_winner(smoothing_index_seconds_a, smoothing_index_seconds_b, False),
            "before": smoothing_index_seconds_before,
            "method_a": smoothing_index_seconds_a,
            "method_b": smoothing_index_seconds_b,
            "formatted_before": f"{smoothing_index_seconds_before:.2f} sec",
            "formatted_method_a": f"{smoothing_index_seconds_a:.2f} sec",
            "formatted_method_b": f"{smoothing_index_seconds_b:.2f} sec",
        },
    ]

    res = {
        "sorted_operations": sorted_ops,
        "shift_time_minutes": shift_time_minutes,
        "production_target": production_target,
        "takt_time": takt_time,
        "pitch_time": pitch_time_b,
        "ucl": ucl_b,
        "lcl": lcl_b,
        "total_sam": total_sam,
        "before": before_metrics,
        "method_a": method_a_metrics,
        "method_b": method_b_metrics,
        "comparison": comparison,
    }
    res["recommendations"] = generate_takt_vs_pitch_recommendations(res)
    return res


def print_cli_results(result: Dict, filepath: str):
    """
    Pretty-print the comparison results to the terminal with clear tables.
    """
    try:
        from tabulate import tabulate
        use_tabulate = True
    except ImportError:
        use_tabulate = False

    takt_time = result["takt_time"]
    pitch_time = result["pitch_time"]
    ucl = result["ucl"]
    lcl = result["lcl"]
    total_sam = result["total_sam"]
    demand = result["production_target"]
    shift_mins = result["shift_time_minutes"]

    sep = "=" * 105
    subsep = "-" * 105

    print("\n" + sep)
    print("  LINE BALANCING BY COMPOSITE MACHINES (TAKT VS PITCH COMPARISON)  ".center(105))
    print(sep)
    print(f"  Input File        : {filepath}")
    print(f"  Customer Demand   : {demand} units")
    print(f"  Available Time    : {shift_mins} minutes ({shift_mins * 60:.0f} seconds)")
    print(f"  Total Basic SAM   : {total_sam:.1f} seconds ({total_sam / 60.0:.2f} minutes)")
    print(f"  Calculated Takt   : {takt_time:.1f} seconds")
    print(f"  Calculated Pitch  : {pitch_time:.1f} seconds  [LCL = {lcl:.1f}s, UCL = {ucl:.1f}s]")
    print(f"  Rule Applied      : Any machine can combine with any machine (EXCEPT Press can ONLY combine with Press)")
    print(sep)

    # 1. METHOD A WORKSTATIONS
    print("\n" + subsep)
    print("  METHOD A: TAKT TIME BALANCING (COMPOSITE MACHINES)  ")
    print(f"  Ceiling = Takt Time ({takt_time:.1f}s) | Strict Mode | Total Stations: {len(result['method_a']['workstations'])} | Manpower: {result['method_a']['total_manpower']}")
    print(subsep)

    df_a = result["method_a"]["report_df"]
    if use_tabulate:
        print(tabulate(df_a, headers="keys", tablefmt="grid", showindex=False))
    else:
        print(df_a.to_string(index=False))

    # 2. METHOD B WORKSTATIONS
    print("\n" + subsep)
    print("  METHOD B: IE PITCH BALANCING (COMPOSITE MACHINES)  ")
    print(f"  Merge Ceiling = UCL ({ucl:.1f}s) | Split Ceiling = Takt ({takt_time:.1f}s) | Total Stations: {len(result['method_b']['workstations'])} | Manpower: {result['method_b']['total_manpower']}")
    print(subsep)

    df_b = result["method_b"]["report_df"]
    if use_tabulate:
        print(tabulate(df_b, headers="keys", tablefmt="grid", showindex=False))
    else:
        print(df_b.to_string(index=False))

    # 3. SIDE-BY-SIDE COMPARISON TABLE
    print("\n" + sep)
    print("  SIDE-BY-SIDE COMPARISON (BEFORE vs METHOD A vs METHOD B)  ".center(105))
    print(sep)

    comp_rows = []
    for item in result["comparison"]:
        winner_str = "TIE"
        if item["winner"] == "method_a":
            winner_str = "Method A (Takt)"
        elif item["winner"] == "method_b":
            winner_str = "Method B (Pitch)"

        comp_rows.append({
            "Metric": item["metric"],
            "Before Balancing": item["formatted_before"],
            "Method A (Takt Time)": item["formatted_method_a"],
            "Method B (Pitch Time)": item["formatted_method_b"],
            "Unit": item["unit"],
            "Best Method": winner_str,
        })

    comp_df = pd.DataFrame(comp_rows)
    if use_tabulate:
        print(tabulate(comp_df, headers="keys", tablefmt="grid", showindex=False))
    else:
        print(comp_df.to_string(index=False))

    # 4. RECOMMENDATIONS
    print("\n" + subsep)
    print("  EXECUTIVE SUMMARY & RECOMMENDATIONS  ")
    print(subsep)
    for idx, rec in enumerate(result.get("recommendations", []), 1):
        print(f"  {idx}. {rec}")
    print(sep + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Line Balancing by Composite Machines (Takt vs Pitch Comparison)"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default="data/Input2.xlsx",
        help="Path to operations input file (CSV/Excel). Default: data/Input2.xlsx",
    )
    parser.add_argument(
        "--demand",
        "-d",
        type=int,
        default=350,
        help="Customer demand target units. Default: 350",
    )
    parser.add_argument(
        "--available-time",
        "-t",
        type=float,
        default=420.0,
        help="Available time in minutes. Default: 420",
    )

    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        repo_root = Path(__file__).resolve().parent.parent.parent
        alt_path = repo_root / args.file
        if alt_path.exists():
            filepath = alt_path
        else:
            print(f"Error: Input file '{args.file}' not found.")
            sys.exit(1)

    print(f"Reading operations from '{filepath}'...")
    operations = read_operations(str(filepath))
    flagged = [op for op in operations if op.flagged]
    if flagged:
        print(f"Warning: Found {len(flagged)} flagged operations:")
        for op in flagged:
            print(f"  - Op {op.op_id} ({op.name}): {op.flagged}")

    print(f"Running Composite Machine Balancing (Demand={args.demand}, Time={args.available_time}m)...")
    results = calculate_composite_takt_vs_pitch_comparison(
        operations=operations,
        shift_time_minutes=args.available_time,
        production_target=args.demand,
    )

    print_cli_results(results, str(filepath))


if __name__ == "__main__":
    main()
