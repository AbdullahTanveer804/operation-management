"""
Takt vs Pitch Comparison Balancing Mode

Standalone comparison flow that runs two balancing passes in parallel:
- Method A: Takt Time balancing (strict ceiling = Takt Time, no bands, strict divide-and-increment)
- Method B: IE Pitch balancing (merge ceiling = UCL, single op split ceiling = Takt Time)

Computes 6 new KPIs for Before, Method A, and Method B:
1. Achievable Output = Available Time / Cycle Time
2. Efficiency = Balancing Rate = Total SAM / (N_operators * Cycle Time) * 100
3. Balancing Delay = 100 - Efficiency
4. Smoothing Index = sqrt(sum((Cmax - Ti)^2)) in seconds per operator position
5. Labour Productivity = Achievable Output / N_operators
6. Cycle Time: Method A = fixed at Takt Time; Method B = MAX(balanced station times); Before = MAX(op basic times)
"""

import math
from typing import Dict, List, Optional, Tuple
import pandas as pd

from .models import Operation, Workstation
from .sequencing import sort_by_id
from .balancing import (
    find_compatible_operations,
    find_best_manpower_split,
)
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
    calculate_before_num_operations,
    calculate_before_total_manpower,
    calculate_before_total_basic_time,
    calculate_before_balancing_rate,
    calculate_before_balance_delay,
    calculate_before_smoothing_index,
    calculate_before_line_efficiency,
    calculate_before_tolerance_bands,
)
from .comparison_recommendations import generate_takt_vs_pitch_recommendations


def balance_method_a_takt(sorted_operations: List[Operation],
                          takt_time: float) -> List[Workstation]:
    """
    Method A — Takt Time Balancing.
    
    - Ceiling = Takt Time (Shift Time * 60 / Production Target)
    - No UCL/LCL bands. Strict mode — zero relaxation.
    - Merge compatible ops up to Takt ceiling using best-fit matching.
    - Any single op exceeding Takt gets manpower-split using
      divide-and-increment (2, 3, 4...) logic in strict mode.
    
    Args:
        sorted_operations: Operations sorted by ID
        takt_time: Takt time in seconds
        
    Returns:
        List of balanced Workstations for Method A
    """
    workstations: List[Workstation] = []
    already_grouped_ids = set()

    for current_op in sorted_operations:
        if current_op.op_id in already_grouped_ids:
            continue

        # Look for compatible partner to combine with
        compatible_ops = find_compatible_operations(current_op,
                                                    sorted_operations,
                                                    already_grouped_ids)

        valid_candidates = []
        for partner_op in compatible_ops:
            combined_time = current_op.basic_time + partner_op.basic_time
            if combined_time <= takt_time:
                diff = abs(combined_time - takt_time)
                valid_candidates.append(
                    (diff, partner_op.op_id, partner_op, combined_time))

        if valid_candidates:
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
            # Standalone op
            if current_op.basic_time <= takt_time:
                ws = Workstation(
                    operations=[current_op],
                    manpower=1,
                    balancing_sam=current_op.basic_time,
                )
                workstations.append(ws)
                already_grouped_ids.add(current_op.op_id)
            else:
                # Single op exceeds Takt: manpower-split with strict mode
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


def balance_method_b_pitch(
    sorted_operations: List[Operation],
    pitch_time: float,
    ucl: float,
    lcl: float,
    takt_time: float,
) -> Tuple[List[Workstation], List[str]]:
    """
    Method B — IE Pitch Balancing.
    
    - Ceiling for MERGING = UCL (Upper Control Limit = Pitch Time + 15%).
      Evaluates all compatible candidates and selects the Best Match (closest to Pitch Time <= UCL).
      Combined SAM of merged operations must be <= UCL with zero relaxation.
      If no candidate satisfies combined SAM <= UCL, leave standalone.
    - Ceiling for SPLITTING single operations = Takt Time (Shift Time * 60 / Production Target).
      Every single operation remains standalone with 1 operator if <= Takt Time.
      If single operation > Takt Time, add incremental manpower (2..n) until time/manpower <= Takt Time.
    - Zero relaxation (strict mode) for both merging according to UCL and splitting according to Takt Time.
    
    Args:
        sorted_operations: Operations sorted by ID
        pitch_time: Auto Pitch Time in seconds
        ucl: Upper Control Limit in seconds
        lcl: Lower Control Limit in seconds
        takt_time: Takt Time in seconds (used as split trigger for single ops)
        
    Returns:
        Tuple of (workstations, statuses)
    """
    workstations: List[Workstation] = []
    statuses: List[str] = []
    already_grouped_ids = set()

    # Merge ceiling is strictly UCL (also capped at Takt Time for safety)
    merge_ceiling = min(ucl, takt_time) if ucl is not None else takt_time

    for current_op in sorted_operations:
        if current_op.op_id in already_grouped_ids:
            continue

        # Look for compatible partner to combine with
        compatible_ops = find_compatible_operations(current_op,
                                                    sorted_operations,
                                                    already_grouped_ids)

        valid_candidates = []
        for partner_op in compatible_ops:
            combined_time = current_op.basic_time + partner_op.basic_time
            if combined_time <= merge_ceiling:
                diff_from_pitch = abs(
                    combined_time -
                    pitch_time) if pitch_time is not None else 0.0
                valid_candidates.append((diff_from_pitch, partner_op.op_id,
                                         partner_op, combined_time))

        if valid_candidates:
            # Pick best match: closest to Pitch Time (tie-breaker: lowest op_id)
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
            # Standalone operation
            total = current_op.basic_time
            if total <= takt_time:
                # Single operation <= Takt Time: standalone with M/P = 1
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
                # Single operation > Takt Time: manpower-split via divide-and-increment strict mode (incremental 2..n)
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
    """
    Calculate Smoothing Index in SECONDS per individual operator position.
    
    Formula:
    Smoothing Index = sqrt( sum( (Cmax - Ti)^2 ) )
    
    Where:
    - Computed in SECONDS (not minutes).
    - Computed per individual operator position (a station with manpower M and time Ti
      counts as M operator positions each with time Ti).
    - Cmax is the Cycle Time for that method.
    
    Args:
        station_times_and_manpower: List of (time_per_operator, manpower)
        c_max: Cycle Time in seconds for that method
        
    Returns:
        Smoothing index in seconds
    """
    sum_squared_diff = 0.0
    for time_per_op, manpower in station_times_and_manpower:
        diff = c_max - time_per_op
        sum_squared_diff += (diff**2) * manpower
    return math.sqrt(sum_squared_diff)


def build_method_report_df(
    workstations: List[Workstation],
    time_column_name: str,
    time_column_value: float,
    ucl: Optional[float] = None,
    lcl: Optional[float] = None,
    statuses: Optional[List[str]] = None,
    method_type: str = "method_a",
) -> pd.DataFrame:
    """
    Build report DataFrame for Method A or Method B with requested column structure.
    """
    rows = []

    for ws_num, ws in enumerate(workstations, start=1):
        op_ids = " + ".join(str(op.op_id) for op in ws.operations)
        op_names = " + ".join(op.name for op in ws.operations)
        basic_times = " + ".join(f"{op.basic_time:.1f}"
                                 for op in ws.operations)
        machine_types = " + ".join(op.machine_type for op in ws.operations)

        op_predecessor_groups = []
        for op in ws.operations:
            if op.predecessors:
                op_preds = ", ".join(str(p) for p in sorted(op.predecessors))
                op_predecessor_groups.append(op_preds)
        predecessors = "+".join(
            op_predecessor_groups) if op_predecessor_groups else "-"

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
            "Combined Basic Time": round(combined_basic_time,
                                         1),  # Compatibility alias
            "Balancing SAM": round(ws.balancing_sam, 1),
            "M/P": ws.manpower,
        }

        if method_type == "method_a":
            row["Takt Time"] = round(
                time_column_value, 1) if time_column_value is not None else ""
        else:
            row["Pitch Time"] = round(
                time_column_value, 1) if time_column_value is not None else ""
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
                "Combined Basic Time", "Balancing SAM", "M/P", "Takt Time",
                "Status"
            ]
        else:
            cols = [
                "Composite Operations", "Serial/Id", "Operations", "Machine",
                "Predecessor", "Basic Time", "Combined SAM",
                "Combined Basic Time", "Balancing SAM", "M/P", "Pitch Time",
                "LCL", "UCL", "Status"
            ]
        existing_cols = [c for c in cols if c in df.columns]
        df = df[existing_cols]
    return df


def calculate_takt_vs_pitch_comparison(
    operations: List[Operation],
    shift_time_minutes: float,
    production_target: int,
) -> Dict:
    """
    Run the complete Takt vs Pitch Comparison balancing and return:
    - before: baseline metrics + 6 new KPIs
    - method_a: Method A (Takt) results + workstation table + all KPIs
    - method_b: Method B (Pitch) results + workstation table + all KPIs
    - comparison: 8 headline KPIs side by side (Before / Method A / Method B)
    
    Args:
        operations: List of Operation objects
        shift_time_minutes: Shift duration in minutes
        production_target: Customer demand target in units
        
    Returns:
        Dictionary with before, method_a, method_b, and comparison keys
    """
    if not operations:
        raise ValueError("Operations list cannot be empty.")
    if shift_time_minutes <= 0:
        raise ValueError("Shift time must be a positive number.")
    if production_target <= 0:
        raise ValueError("Production target must be a positive number.")

    # Sort operations by ID
    sorted_ops = sort_by_id(operations)

    # Core parameters
    available_time_seconds = shift_time_minutes * 60.0
    takt_time = calculate_pitch_time_from_target(production_target,
                                                 shift_time_minutes)
    total_sam = sum(op.basic_time for op in sorted_ops)

    # Method B Pitch & UCL/LCL parameters
    pitch_time_b = calculate_pitch_time(sorted_ops)
    ucl_b, lcl_b = calculate_tolerance_bands(pitch_time_b, 0.15)

    # ==========================================
    # 1. RUN METHOD A (Takt Time Balancing)
    # ==========================================
    workstations_a = balance_method_a_takt(sorted_ops, takt_time)
    df_a = build_method_report_df(
        workstations_a,
        time_column_name="Takt Time",
        time_column_value=takt_time,
        ucl=None,
        lcl=None,
        statuses=["OK"] * len(workstations_a),
        method_type="method_a",
    )
    rows_a = df_a.to_dict("records")
    for r in rows_a:
        r["Combined SAM"] = f"{r['Combined SAM']:.1f}"
        r["Combined Basic Time"] = f"{r['Combined Basic Time']:.1f}"
        r["Balancing SAM"] = f"{r['Balancing SAM']:.1f}"
        if "Takt Time" in r and r["Takt Time"] != "":
            r["Takt Time"] = f"{r['Takt Time']:.1f}"

    # ==========================================
    # 2. RUN METHOD B (IE Pitch Balancing)
    # ==========================================
    workstations_b, statuses_b = balance_method_b_pitch(
        sorted_ops, pitch_time_b, ucl_b, lcl_b, takt_time)
    df_b = build_method_report_df(
        workstations_b,
        time_column_name="Pitch Time",
        time_column_value=pitch_time_b,
        ucl=ucl_b,
        lcl=lcl_b,
        statuses=statuses_b,
        method_type="method_b",
    )
    rows_b = df_b.to_dict("records")
    for r in rows_b:
        r["Combined SAM"] = f"{r['Combined SAM']:.1f}"
        r["Combined Basic Time"] = f"{r['Combined Basic Time']:.1f}"
        r["Balancing SAM"] = f"{r['Balancing SAM']:.1f}"
        if "Pitch Time" in r and r["Pitch Time"] != "":
            r["Pitch Time"] = f"{r['Pitch Time']:.1f}"
        if "UCL" in r and r["UCL"] != "":
            r["UCL"] = f"{r['UCL']:.1f}"
        if "LCL" in r and r["LCL"] != "":
            r["LCL"] = f"{r['LCL']:.1f}"

    # ==========================================
    # 3. COMPUTE 6 NEW KPIS FOR ALL THREE
    # ==========================================

    # --- BEFORE BALANCING ---
    n_ops_before = len(sorted_ops)
    cycle_time_before = max(op.basic_time for op in sorted_ops)
    achievable_output_before = available_time_seconds / cycle_time_before if cycle_time_before > 0 else 0.0
    efficiency_before = ((total_sam /
                          (n_ops_before * cycle_time_before)) * 100.0 if
                         (n_ops_before > 0 and cycle_time_before > 0) else 0.0)
    balance_delay_before = 100.0 - efficiency_before
    # Smoothing index per operator in seconds: Cmax = cycle_time_before
    smoothing_index_seconds_before = calculate_smoothing_index_seconds(
        [(op.basic_time, 1) for op in sorted_ops], cycle_time_before)
    labour_productivity_before = (achievable_output_before /
                                  n_ops_before if n_ops_before > 0 else 0.0)

    # Existing before metrics for completeness
    existing_balancing_rate_before = calculate_before_balancing_rate(
        sorted_ops)
    existing_balance_delay_before = calculate_before_balance_delay(sorted_ops)
    existing_line_eff_before = calculate_before_line_efficiency(
        sorted_ops, production_target, shift_time_minutes)
    existing_smoothing_index_min_before = calculate_before_smoothing_index(
        sorted_ops)

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
        # 6 New KPIs
        "cycle_time": cycle_time_before,
        "achievable_output": achievable_output_before,
        "efficiency_balancing_rate": efficiency_before,
        "comparison_balance_delay": balance_delay_before,
        "smoothing_index_seconds": smoothing_index_seconds_before,
        "comparison_labour_productivity": labour_productivity_before,
    }

    # --- METHOD A ---
    n_ops_a = sum(ws.manpower for ws in workstations_a)
    cycle_time_a = takt_time  # Fixed at Takt Time
    achievable_output_a = available_time_seconds / cycle_time_a if cycle_time_a > 0 else 0.0
    efficiency_a = ((total_sam / (n_ops_a * cycle_time_a)) * 100.0 if
                    (n_ops_a > 0 and cycle_time_a > 0) else 0.0)
    balance_delay_a = 100.0 - efficiency_a
    smoothing_index_seconds_a = calculate_smoothing_index_seconds(
        [(ws.balancing_sam, ws.manpower) for ws in workstations_a],
        cycle_time_a)
    labour_productivity_a = achievable_output_a / n_ops_a if n_ops_a > 0 else 0.0

    # Existing metrics for Method A
    existing_balancing_rate_a = calculate_line_balancing_rate(workstations_a)
    existing_balance_delay_a = calculate_balance_delay(workstations_a,
                                                       sorted_ops)
    existing_line_eff_a = calculate_line_efficiency(workstations_a, sorted_ops,
                                                    production_target,
                                                    shift_time_minutes)
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
        # 6 New KPIs
        "cycle_time": cycle_time_a,
        "achievable_output": achievable_output_a,
        "efficiency_balancing_rate": efficiency_a,
        "comparison_balance_delay": balance_delay_a,
        "smoothing_index_seconds": smoothing_index_seconds_a,
        "comparison_labour_productivity": labour_productivity_a,
    }

    # --- METHOD B ---
    n_ops_b = sum(ws.manpower for ws in workstations_b)
    cycle_time_b = max(ws.balancing_sam
                       for ws in workstations_b) if workstations_b else 0.0
    achievable_output_b = available_time_seconds / cycle_time_b if cycle_time_b > 0 else 0.0
    efficiency_b = ((total_sam / (n_ops_b * cycle_time_b)) * 100.0 if
                    (n_ops_b > 0 and cycle_time_b > 0) else 0.0)
    balance_delay_b = 100.0 - efficiency_b
    smoothing_index_seconds_b = calculate_smoothing_index_seconds(
        [(ws.balancing_sam, ws.manpower) for ws in workstations_b],
        cycle_time_b)
    labour_productivity_b = achievable_output_b / n_ops_b if n_ops_b > 0 else 0.0

    # Existing metrics for Method B
    existing_balancing_rate_b = calculate_line_balancing_rate(workstations_b)
    existing_balance_delay_b = calculate_balance_delay(workstations_b,
                                                       sorted_ops)
    existing_line_eff_b = calculate_line_efficiency(workstations_b, sorted_ops,
                                                    production_target,
                                                    shift_time_minutes)
    existing_smoothing_index_min_b = calculate_smoothing_index(workstations_b)

    # Review flagged count in Method B
    review_flag_count = sum(1 for s in statuses_b
                            if "review" in s.lower() or "Above UCL" in s)

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
        "review_flag_count": review_flag_count,
        "workstations": workstations_b,
        "statuses": statuses_b,
        "report_df": df_b,
        "rows": rows_b,
        "line_balancing_rate": existing_balancing_rate_b,
        "balance_delay": existing_balance_delay_b,
        "line_efficiency": existing_line_eff_b,
        "smoothing_index": existing_smoothing_index_min_b,
        # 6 New KPIs
        "cycle_time": cycle_time_b,
        "achievable_output": achievable_output_b,
        "efficiency_balancing_rate": efficiency_b,
        "comparison_balance_delay": balance_delay_b,
        "smoothing_index_seconds": smoothing_index_seconds_b,
        "comparison_labour_productivity": labour_productivity_b,
    }

    # ==========================================
    def get_winner(val_a: float, val_b: float, higher_is_better: bool) -> str:
        if abs(val_a - val_b) < 1e-6:
            return "tie"
        if higher_is_better:
            return "method_a" if val_a > val_b else "method_b"
        else:
            return "method_a" if val_a < val_b else "method_b"

    comparison = [
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
            "metric": "Composite Operations",
            "key": "num_workstations",
            "unit": "stations",
            "higher_is_better": False,
            "winner": get_winner(len(workstations_a), len(workstations_b),
                                 False),
            "before": n_ops_before,
            "method_a": len(workstations_a),
            "method_b": len(workstations_b),
            "formatted_before": f"{n_ops_before}",
            "formatted_method_a": f"{len(workstations_a)}",
            "formatted_method_b": f"{len(workstations_b)}",
        },
        {
            "metric": "Cycle Time",
            "key": "cycle_time",
            "unit": "s",
            "higher_is_better": False,
            "winner": get_winner(cycle_time_a, cycle_time_b, False),
            "before": cycle_time_before,
            "method_a": cycle_time_a,
            "method_b": cycle_time_b,
            "formatted_before": f"{cycle_time_before:.1f} s",
            "formatted_method_a": f"{cycle_time_a:.1f} s",
            "formatted_method_b": f"{cycle_time_b:.1f} s",
        },
        {
            "metric": "Achievable Output",
            "key": "achievable_output",
            "unit": "pcs/day",
            "higher_is_better": True,
            "winner": get_winner(achievable_output_a, achievable_output_b,
                                 True),
            "before": achievable_output_before,
            "method_a": achievable_output_a,
            "method_b": achievable_output_b,
            "formatted_before": f"{achievable_output_before:.0f} pcs/day",
            "formatted_method_a": f"{achievable_output_a:.0f} pcs/day",
            "formatted_method_b": f"{achievable_output_b:.0f} pcs/day",
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
            "metric":
            "Smoothing Index",
            "key":
            "smoothing_index_seconds",
            "unit":
            "s",
            "higher_is_better":
            False,
            "winner":
            get_winner(smoothing_index_seconds_a, smoothing_index_seconds_b,
                       False),
            "before":
            smoothing_index_seconds_before,
            "method_a":
            smoothing_index_seconds_a,
            "method_b":
            smoothing_index_seconds_b,
            "formatted_before":
            f"{smoothing_index_seconds_before:.2f} s",
            "formatted_method_a":
            f"{smoothing_index_seconds_a:.2f} s",
            "formatted_method_b":
            f"{smoothing_index_seconds_b:.2f} s",
        },
        {
            "metric":
            "Labour Productivity",
            "key":
            "comparison_labour_productivity",
            "unit":
            "pcs/operator",
            "higher_is_better":
            True,
            "winner":
            get_winner(labour_productivity_a, labour_productivity_b, True),
            "before":
            labour_productivity_before,
            "method_a":
            labour_productivity_a,
            "method_b":
            labour_productivity_b,
            "formatted_before":
            f"{labour_productivity_before:.1f} pcs/op",
            "formatted_method_a":
            f"{labour_productivity_a:.1f} pcs/op",
            "formatted_method_b":
            f"{labour_productivity_b:.1f} pcs/op",
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
