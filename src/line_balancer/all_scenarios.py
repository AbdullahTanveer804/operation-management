"""
All-Scenarios Orchestrator & Aggregator

Runs all 7 Line Balancing scenarios from a single shared input set:
  1. Before Balancing (baseline, unbalanced)
  2. Takt Time Balancing (Same-Machines) — existing takt_pitch_comparison module (Method A)
  3. IE Pitch Time Balancing (Same-Machines) — existing takt_pitch_comparison module (Method B)
  4. Takt Time Balancing (Composite-Machines) — existing balancing_by_composite_machines.py (Method A)
  5. IE Pitch Time Balancing (Composite-Machines) — existing balancing_by_composite_machines.py (Method B)
  6. Pitch Time (Auto), Same-Machines — existing /line-balancing Auto module
  7. Pitch Time (Auto), Composite-Machines — balancing_auto_composite_machines.py

Features:
- Single shared baseline block computed once (Customer Demand, Available Time, Total SAM, etc.).
- Normalizes rows so every scenario exposes the exact same field set for frontend rendering.
- Computes all 8 standard KPIs across all 7 scenarios.
- Provides a side-by-side 7-scenario comparison table.
- Standalone CLI execution support.
"""

import argparse
import copy
import math
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    file_path = Path(__file__).resolve()
    project_root = file_path.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

try:
    from .models import Operation, Workstation
    from .sequencing import sort_by_id
    from .io_utils import read_operations
    from .metrics import (
        calculate_pitch_time,
        calculate_pitch_time_from_target,
        calculate_tolerance_bands,
    )
    from .balancing import group_and_balance
    from .report import build_report_dataframe
    from .takt_pitch_comparison import calculate_takt_vs_pitch_comparison
    from .balancing_by_composite_machines import calculate_composite_takt_vs_pitch_comparison
    from .balancing_auto_composite_machines import calculate_auto_composite_balancing
except ImportError:
    from src.line_balancer.models import Operation, Workstation
    from src.line_balancer.sequencing import sort_by_id
    from src.line_balancer.io_utils import read_operations
    from src.line_balancer.metrics import (
        calculate_pitch_time,
        calculate_pitch_time_from_target,
        calculate_tolerance_bands,
    )
    from src.line_balancer.balancing import group_and_balance
    from src.line_balancer.report import build_report_dataframe
    from src.line_balancer.takt_pitch_comparison import calculate_takt_vs_pitch_comparison
    from src.line_balancer.balancing_by_composite_machines import calculate_composite_takt_vs_pitch_comparison
    from src.line_balancer.balancing_auto_composite_machines import calculate_auto_composite_balancing


# ==============================================================================
# Helper Math: Smoothing Index in Seconds
# ==============================================================================

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


# ==============================================================================
# Adapters & Row Normalization
# ==============================================================================

def adapt_composite_result(result: Dict) -> Dict:
    """
    Adapter normalizing output of calculate_composite_takt_vs_pitch_comparison()
    for scenarios 4 (takt_composite) and 5 (pitch_composite):
    - Formats numeric floats into strings
    - Adds 'Combined Basic Time' alias matching 'Combined SAM'
    - Injects 'review_flag_count'
    - Normalizes Achievable Output unit label
    """
    res = copy.deepcopy(result)

    # Method A rows
    for r in res.get("method_a", {}).get("rows", []):
        if "Combined SAM" in r and isinstance(r["Combined SAM"], (int, float)):
            r["Combined SAM"] = f"{r['Combined SAM']:.1f}"
        if "Balancing SAM" in r and isinstance(r["Balancing SAM"], (int, float)):
            r["Balancing SAM"] = f"{r['Balancing SAM']:.1f}"
        if "Takt Time" in r and r["Takt Time"] != "" and isinstance(r["Takt Time"], (int, float)):
            r["Takt Time"] = f"{r['Takt Time']:.1f}"
        r.setdefault("Combined Basic Time", r.get("Combined SAM", ""))

    # Method B rows
    for r in res.get("method_b", {}).get("rows", []):
        if "Combined SAM" in r and isinstance(r["Combined SAM"], (int, float)):
            r["Combined SAM"] = f"{r['Combined SAM']:.1f}"
        if "Balancing SAM" in r and isinstance(r["Balancing SAM"], (int, float)):
            r["Balancing SAM"] = f"{r['Balancing SAM']:.1f}"
        if "Pitch Time" in r and r["Pitch Time"] != "" and isinstance(r["Pitch Time"], (int, float)):
            r["Pitch Time"] = f"{r['Pitch Time']:.1f}"
        if "UCL" in r and r["UCL"] != "" and isinstance(r["UCL"], (int, float)):
            r["UCL"] = f"{r['UCL']:.1f}"
        if "LCL" in r and r["LCL"] != "" and isinstance(r["LCL"], (int, float)):
            r["LCL"] = f"{r['LCL']:.1f}"
        r.setdefault("Combined Basic Time", r.get("Combined SAM", ""))

    # Review flag count for method B
    statuses_b = res.get("method_b", {}).get("statuses", [])
    res["method_b"]["review_flag_count"] = sum(
        1 for s in statuses_b if "review" in s.lower() or "Above UCL" in s
    )

    # Normalise Achievable Output label in comparison rows
    for row in res.get("comparison", []):
        if row.get("metric") == "Achievable Output":
            row["unit"] = "pcs/available time"
            row["formatted_before"] = row["formatted_before"].replace("pcs/shift", "pcs/available time")
            row["formatted_method_a"] = row["formatted_method_a"].replace("pcs/shift", "pcs/available time")
            row["formatted_method_b"] = row["formatted_method_b"].replace("pcs/shift", "pcs/available time")

    return res


def normalize_scenario_rows(
    raw_rows: List[Dict],
    default_pitch: Optional[float] = None,
    default_takt: Optional[float] = None,
    default_ucl: Optional[float] = None,
    default_lcl: Optional[float] = None,
) -> List[Dict]:
    """
    Standardize row dictionaries across all scenarios so every row contains
    the exact same complete key set:
    - Composite Operations (int)
    - Serial/Id (str)
    - Operations (str)
    - Machine (str)
    - Predecessor (str)
    - Basic Time (str)
    - Combined Basic Time (str)
    - Combined SAM (str)
    - Balancing SAM (str)
    - M/P (int)
    - Pitch Time (str)
    - Takt Time (str)
    - UCL (str)
    - LCL (str)
    - Status (str)
    """
    normalized = []
    for idx, r in enumerate(raw_rows, start=1):
        row = dict(r)

        # Workstation number
        ws_num = row.get("Composite Operations", row.get("Workstation", idx))
        row["Composite Operations"] = int(ws_num)

        # Ensure Combined Basic Time & Combined SAM exist and match
        c_basic = row.get("Combined Basic Time")
        c_sam = row.get("Combined SAM")

        if c_basic is None and c_sam is not None:
            c_basic = c_sam
        elif c_sam is None and c_basic is not None:
            c_sam = c_basic
        elif c_basic is None and c_sam is None:
            c_basic = row.get("Basic Time", "0.0")
            c_sam = c_basic

        # Format numeric values to 1-decimal strings
        def fmt(val):
            if val is None or val == "":
                return ""
            if isinstance(val, (int, float)):
                return f"{val:.1f}"
            return str(val)

        row["Combined Basic Time"] = fmt(c_basic)
        row["Combined SAM"] = fmt(c_sam)
        row["Balancing SAM"] = fmt(row.get("Balancing SAM", ""))
        row["M/P"] = int(row.get("M/P", 1))

        # Handle reference line values
        if "Pitch Time" not in row or row["Pitch Time"] == "":
            row["Pitch Time"] = fmt(default_pitch)
        else:
            row["Pitch Time"] = fmt(row["Pitch Time"])

        if "Takt Time" not in row or row["Takt Time"] == "":
            row["Takt Time"] = fmt(default_takt)
        else:
            row["Takt Time"] = fmt(row["Takt Time"])

        if "UCL" not in row or row["UCL"] == "":
            row["UCL"] = fmt(default_ucl)
        else:
            row["UCL"] = fmt(row["UCL"])

        if "LCL" not in row or row["LCL"] == "":
            row["LCL"] = fmt(default_lcl)
        else:
            row["LCL"] = fmt(row["LCL"])

        row["Status"] = str(row.get("Status", "OK"))
        normalized.append(row)

    return normalized


# ==============================================================================
# Scenario Execution & KPI Calculations
# ==============================================================================

def compute_kpis_from_workstations(
    workstations: List[Workstation],
    total_sam: float,
    available_time_seconds: float,
    takt_time: float,
    fixed_cycle_time: Optional[float] = None,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Compute the 8 headline KPIs and their formatted string versions."""
    num_ws = len(workstations)
    total_mp = sum(ws.manpower for ws in workstations) if workstations else 0

    if fixed_cycle_time is not None:
        cycle_time = fixed_cycle_time
    else:
        cycle_time = max(ws.balancing_sam for ws in workstations) if workstations else 0.0

    achievable_output = (
        available_time_seconds / cycle_time if cycle_time > 0 else 0.0
    )
    efficiency = (
        (total_sam / (total_mp * cycle_time)) * 100.0
        if (total_mp > 0 and cycle_time > 0)
        else 0.0
    )
    balance_delay = 100.0 - efficiency
    smoothing_index = calculate_smoothing_index_seconds(
        [(ws.balancing_sam, ws.manpower) for ws in workstations], cycle_time
    )
    labour_productivity = (
        achievable_output / total_mp if total_mp > 0 else 0.0
    )

    kpis = {
        "num_workstations": num_ws,
        "total_manpower": total_mp,
        "cycle_time": cycle_time,
        "achievable_output": achievable_output,
        "efficiency": efficiency,
        "balancing_delay": balance_delay,
        "smoothing_index": smoothing_index,
        "labour_productivity": labour_productivity,
    }

    formatted_kpis = {
        "num_workstations": str(num_ws),
        "total_manpower": str(total_mp),
        "cycle_time": f"{cycle_time:.1f} sec",
        "achievable_output": f"{achievable_output:.0f} pcs/available time",
        "efficiency": f"{efficiency:.1f}%",
        "balancing_delay": f"{balance_delay:.1f}%",
        "smoothing_index": f"{smoothing_index:.2f} sec",
        "labour_productivity": f"{labour_productivity:.1f} pcs/optr",
    }

    return kpis, formatted_kpis


# ==============================================================================
# Main Aggregator Entry Point
# ==============================================================================

def run_all_scenarios(
    operations: List[Operation],
    shift_time_minutes: float,
    production_target: int,
    tolerance: float = 0.15,
) -> Dict[str, Any]:
    """
    Run all 7 line balancing scenarios from one shared input set.
    
    Shared Baseline Block:
    - Customer Demand, Available Time, Total SAM, Operation Count,
      Calculated Takt Time, Pitch Time, UCL/LCL are computed ONCE.
      
    Scenarios executed:
      1. before: Before Balancing (baseline, unbalanced)
      2. takt_same: Takt Time Balancing (Same-Machines)
      3. pitch_same: IE Pitch Time Balancing (Same-Machines)
      4. takt_composite: Takt Time Balancing (Composite-Machines, adapted)
      5. pitch_composite: IE Pitch Time Balancing (Composite-Machines, adapted)
      6. auto_same: Pitch Time (Auto, Same-Machines, adapted)
      7. auto_composite: Pitch Time (Auto, Composite-Machines)
    """
    if not operations:
        raise ValueError("Operations list cannot be empty.")
    if shift_time_minutes <= 0:
        raise ValueError("Available Time (shift_time_minutes) must be positive.")
    if production_target <= 0:
        raise ValueError("Customer Demand (production_target) must be positive.")

    # --------------------------------------------------------------------------
    # 0. SHARED BASELINE BLOCK (Computed ONCE)
    # --------------------------------------------------------------------------
    sorted_ops = sort_by_id(operations)
    num_ops = len(sorted_ops)
    total_sam = sum(op.basic_time for op in sorted_ops)
    available_time_seconds = shift_time_minutes * 60.0
    takt_time = calculate_pitch_time_from_target(production_target, shift_time_minutes)
    auto_pitch_time = calculate_pitch_time(sorted_ops)
    auto_ucl, auto_lcl = calculate_tolerance_bands(auto_pitch_time, tolerance)

    shared_parameters = {
        "customer_demand": production_target,
        "available_time_minutes": shift_time_minutes,
        "available_time_seconds": available_time_seconds,
        "total_sam": total_sam,
        "total_sam_minutes": total_sam / 60.0,
        "num_operations": num_ops,
        "takt_time": takt_time,
        "pitch_time": auto_pitch_time,
        "ucl": auto_ucl,
        "lcl": auto_lcl,
        "tolerance": tolerance,
    }

    scenarios = {}

    # --------------------------------------------------------------------------
    # SCENARIO 1: Before Balancing (baseline, unbalanced)
    # --------------------------------------------------------------------------
    ws_before = [
        Workstation(operations=[op], manpower=1, balancing_sam=op.basic_time)
        for op in sorted_ops
    ]
    kpis_before, fmt_kpis_before = compute_kpis_from_workstations(
        ws_before,
        total_sam,
        available_time_seconds,
        takt_time,
        fixed_cycle_time=max(op.basic_time for op in sorted_ops),
    )
    raw_rows_before = []
    for idx, op in enumerate(sorted_ops, start=1):
        preds = ", ".join(str(p) for p in sorted(op.predecessors)) if op.predecessors else "-"
        raw_rows_before.append({
            "Composite Operations": idx,
            "Serial/Id": str(op.op_id),
            "Operations": op.name,
            "Machine": op.machine_type,
            "Predecessor": preds,
            "Basic Time": f"{op.basic_time:.1f}",
            "Combined Basic Time": f"{op.basic_time:.1f}",
            "Combined SAM": f"{op.basic_time:.1f}",
            "Balancing SAM": f"{op.basic_time:.1f}",
            "M/P": 1,
            "Pitch Time": f"{auto_pitch_time:.1f}",
            "Takt Time": f"{takt_time:.1f}",
            "UCL": f"{auto_ucl:.1f}",
            "LCL": f"{auto_lcl:.1f}",
            "Status": "OK",
        })
    rows_before = normalize_scenario_rows(
        raw_rows_before,
        default_pitch=auto_pitch_time,
        default_takt=takt_time,
        default_ucl=auto_ucl,
        default_lcl=auto_lcl,
    )

    scenarios["before"] = {
        "id": "before",
        "name": "Before Balancing",
        "short_name": "Before",
        "description": "Baseline unbalanced operations (1 operator per operation)",
        "workstations": ws_before,
        "rows": rows_before,
        "kpis": kpis_before,
        "formatted_kpis": fmt_kpis_before,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": auto_pitch_time,
            "ucl": auto_ucl,
            "lcl": auto_lcl,
        },
        "review_flag_count": 0,
        "demand_met": kpis_before["cycle_time"] <= takt_time,
    }

    # --------------------------------------------------------------------------
    # SCENARIOS 2 & 3: Same-Machines Takt & Pitch Comparison
    # --------------------------------------------------------------------------
    res_same = calculate_takt_vs_pitch_comparison(
        operations, shift_time_minutes, production_target
    )

    # 2. takt_same
    meth_a_same = res_same["method_a"]
    kpis_takt_same = {
        "num_workstations": meth_a_same["num_workstations"],
        "total_manpower": meth_a_same["total_manpower"],
        "cycle_time": meth_a_same["cycle_time"],
        "achievable_output": meth_a_same["achievable_output"],
        "efficiency": meth_a_same["efficiency_balancing_rate"],
        "balancing_delay": meth_a_same["comparison_balance_delay"],
        "smoothing_index": meth_a_same["smoothing_index_seconds"],
        "labour_productivity": meth_a_same["comparison_labour_productivity"],
    }
    fmt_kpis_takt_same = {
        "num_workstations": str(meth_a_same["num_workstations"]),
        "total_manpower": str(meth_a_same["total_manpower"]),
        "cycle_time": f"{meth_a_same['cycle_time']:.1f} sec",
        "achievable_output": f"{meth_a_same['achievable_output']:.0f} pcs/available time",
        "efficiency": f"{meth_a_same['efficiency_balancing_rate']:.1f}%",
        "balancing_delay": f"{meth_a_same['comparison_balance_delay']:.1f}%",
        "smoothing_index": f"{meth_a_same['smoothing_index_seconds']:.2f} sec",
        "labour_productivity": f"{meth_a_same['comparison_labour_productivity']:.1f} pcs/optr",
    }
    rows_takt_same = normalize_scenario_rows(
        meth_a_same["rows"],
        default_takt=takt_time,
    )
    scenarios["takt_same"] = {
        "id": "takt_same",
        "name": "Takt Time Balancing (Same-Machines)",
        "short_name": "Takt (Same)",
        "description": "Takt Time pacing with single-machine-type merging",
        "workstations": meth_a_same["workstations"],
        "rows": rows_takt_same,
        "kpis": kpis_takt_same,
        "formatted_kpis": fmt_kpis_takt_same,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": None,
            "ucl": None,
            "lcl": None,
        },
        "review_flag_count": 0,
        "demand_met": kpis_takt_same["cycle_time"] <= takt_time,
    }

    # 3. pitch_same
    meth_b_same = res_same["method_b"]
    kpis_pitch_same = {
        "num_workstations": meth_b_same["num_workstations"],
        "total_manpower": meth_b_same["total_manpower"],
        "cycle_time": meth_b_same["cycle_time"],
        "achievable_output": meth_b_same["achievable_output"],
        "efficiency": meth_b_same["efficiency_balancing_rate"],
        "balancing_delay": meth_b_same["comparison_balance_delay"],
        "smoothing_index": meth_b_same["smoothing_index_seconds"],
        "labour_productivity": meth_b_same["comparison_labour_productivity"],
    }
    fmt_kpis_pitch_same = {
        "num_workstations": str(meth_b_same["num_workstations"]),
        "total_manpower": str(meth_b_same["total_manpower"]),
        "cycle_time": f"{meth_b_same['cycle_time']:.1f} sec",
        "achievable_output": f"{meth_b_same['achievable_output']:.0f} pcs/available time",
        "efficiency": f"{meth_b_same['efficiency_balancing_rate']:.1f}%",
        "balancing_delay": f"{meth_b_same['comparison_balance_delay']:.1f}%",
        "smoothing_index": f"{meth_b_same['smoothing_index_seconds']:.2f} sec",
        "labour_productivity": f"{meth_b_same['comparison_labour_productivity']:.1f} pcs/optr",
    }
    rows_pitch_same = normalize_scenario_rows(
        meth_b_same["rows"],
        default_pitch=meth_b_same["pitch_time"],
        default_takt=takt_time,
        default_ucl=meth_b_same["ucl"],
        default_lcl=meth_b_same["lcl"],
    )
    scenarios["pitch_same"] = {
        "id": "pitch_same",
        "name": "IE Pitch Time Balancing (Same-Machines)",
        "short_name": "Pitch (Same)",
        "description": "IE Pitch Time tolerance balancing with single-machine-type merging",
        "workstations": meth_b_same["workstations"],
        "rows": rows_pitch_same,
        "kpis": kpis_pitch_same,
        "formatted_kpis": fmt_kpis_pitch_same,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": meth_b_same["pitch_time"],
            "ucl": meth_b_same["ucl"],
            "lcl": meth_b_same["lcl"],
        },
        "review_flag_count": meth_b_same.get("review_flag_count", 0),
        "demand_met": kpis_pitch_same["cycle_time"] <= takt_time,
    }

    # --------------------------------------------------------------------------
    # SCENARIOS 4 & 5: Composite-Machines Takt & Pitch Comparison
    # --------------------------------------------------------------------------
    raw_comp = calculate_composite_takt_vs_pitch_comparison(
        operations, shift_time_minutes, production_target
    )
    res_comp = adapt_composite_result(raw_comp)

    # 4. takt_composite
    meth_a_comp = res_comp["method_a"]
    kpis_takt_comp = {
        "num_workstations": meth_a_comp["num_workstations"],
        "total_manpower": meth_a_comp["total_manpower"],
        "cycle_time": meth_a_comp["cycle_time"],
        "achievable_output": meth_a_comp["achievable_output"],
        "efficiency": meth_a_comp["efficiency_balancing_rate"],
        "balancing_delay": meth_a_comp["comparison_balance_delay"],
        "smoothing_index": meth_a_comp["smoothing_index_seconds"],
        "labour_productivity": meth_a_comp["comparison_labour_productivity"],
    }
    fmt_kpis_takt_comp = {
        "num_workstations": str(meth_a_comp["num_workstations"]),
        "total_manpower": str(meth_a_comp["total_manpower"]),
        "cycle_time": f"{meth_a_comp['cycle_time']:.1f} sec",
        "achievable_output": f"{meth_a_comp['achievable_output']:.0f} pcs/available time",
        "efficiency": f"{meth_a_comp['efficiency_balancing_rate']:.1f}%",
        "balancing_delay": f"{meth_a_comp['comparison_balance_delay']:.1f}%",
        "smoothing_index": f"{meth_a_comp['smoothing_index_seconds']:.2f} sec",
        "labour_productivity": f"{meth_a_comp['comparison_labour_productivity']:.1f} pcs/optr",
    }
    rows_takt_comp = normalize_scenario_rows(
        meth_a_comp["rows"],
        default_takt=takt_time,
    )
    scenarios["takt_composite"] = {
        "id": "takt_composite",
        "name": "Takt Time Balancing (Composite-Machines)",
        "short_name": "Takt (Composite)",
        "description": "Takt Time pacing with cross-machine merging capability",
        "workstations": meth_a_comp["workstations"],
        "rows": rows_takt_comp,
        "kpis": kpis_takt_comp,
        "formatted_kpis": fmt_kpis_takt_comp,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": None,
            "ucl": None,
            "lcl": None,
        },
        "review_flag_count": 0,
        "demand_met": kpis_takt_comp["cycle_time"] <= takt_time,
    }

    # 5. pitch_composite
    meth_b_comp = res_comp["method_b"]
    kpis_pitch_comp = {
        "num_workstations": meth_b_comp["num_workstations"],
        "total_manpower": meth_b_comp["total_manpower"],
        "cycle_time": meth_b_comp["cycle_time"],
        "achievable_output": meth_b_comp["achievable_output"],
        "efficiency": meth_b_comp["efficiency_balancing_rate"],
        "balancing_delay": meth_b_comp["comparison_balance_delay"],
        "smoothing_index": meth_b_comp["smoothing_index_seconds"],
        "labour_productivity": meth_b_comp["comparison_labour_productivity"],
    }
    fmt_kpis_pitch_comp = {
        "num_workstations": str(meth_b_comp["num_workstations"]),
        "total_manpower": str(meth_b_comp["total_manpower"]),
        "cycle_time": f"{meth_b_comp['cycle_time']:.1f} sec",
        "achievable_output": f"{meth_b_comp['achievable_output']:.0f} pcs/available time",
        "efficiency": f"{meth_b_comp['efficiency_balancing_rate']:.1f}%",
        "balancing_delay": f"{meth_b_comp['comparison_balance_delay']:.1f}%",
        "smoothing_index": f"{meth_b_comp['smoothing_index_seconds']:.2f} sec",
        "labour_productivity": f"{meth_b_comp['comparison_labour_productivity']:.1f} pcs/optr",
    }
    rows_pitch_comp = normalize_scenario_rows(
        meth_b_comp["rows"],
        default_pitch=meth_b_comp["pitch_time"],
        default_takt=takt_time,
        default_ucl=meth_b_comp["ucl"],
        default_lcl=meth_b_comp["lcl"],
    )
    scenarios["pitch_composite"] = {
        "id": "pitch_composite",
        "name": "IE Pitch Time Balancing (Composite-Machines)",
        "short_name": "Pitch (Composite)",
        "description": "IE Pitch Time tolerance balancing with cross-machine merging capability",
        "workstations": meth_b_comp["workstations"],
        "rows": rows_pitch_comp,
        "kpis": kpis_pitch_comp,
        "formatted_kpis": fmt_kpis_pitch_comp,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": meth_b_comp["pitch_time"],
            "ucl": meth_b_comp["ucl"],
            "lcl": meth_b_comp["lcl"],
        },
        "review_flag_count": meth_b_comp.get("review_flag_count", 0),
        "demand_met": kpis_pitch_comp["cycle_time"] <= takt_time,
    }

    # --------------------------------------------------------------------------
    # SCENARIO 6: Pitch Time (Auto, Same-Machines)
    # --------------------------------------------------------------------------
    ws_auto_same = group_and_balance(sorted_ops, auto_ucl, auto_lcl, strict=False)
    df_auto_same = build_report_dataframe(
        ws_auto_same, auto_ucl, auto_lcl, auto_pitch_time, "calculated"
    )
    raw_rows_auto_same = df_auto_same.to_dict("records")
    # Adapter for auto_same: ensure Combined SAM alias is set and values formatted
    for r in raw_rows_auto_same:
        if "Combined SAM" not in r:
            r["Combined SAM"] = r.get("Combined Basic Time", "")
    rows_auto_same = normalize_scenario_rows(
        raw_rows_auto_same,
        default_pitch=auto_pitch_time,
        default_takt=takt_time,
        default_ucl=auto_ucl,
        default_lcl=auto_lcl,
    )
    kpis_auto_same, fmt_kpis_auto_same = compute_kpis_from_workstations(
        ws_auto_same,
        total_sam,
        available_time_seconds,
        takt_time,
        fixed_cycle_time=max(ws.balancing_sam for ws in ws_auto_same) if ws_auto_same else 0.0,
    )
    statuses_auto_same = [r["Status"] for r in rows_auto_same]
    scenarios["auto_same"] = {
        "id": "auto_same",
        "name": "Pitch Time (Auto, Same-Machines)",
        "short_name": "Auto (Same)",
        "description": "Factory Auto Pitch Time (+/-15%) with single-machine merging",
        "workstations": ws_auto_same,
        "rows": rows_auto_same,
        "kpis": kpis_auto_same,
        "formatted_kpis": fmt_kpis_auto_same,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": auto_pitch_time,
            "ucl": auto_ucl,
            "lcl": auto_lcl,
        },
        "review_flag_count": sum(1 for s in statuses_auto_same if "review" in s.lower() or "> UCL" in s),
        "demand_met": kpis_auto_same["cycle_time"] <= takt_time,
    }

    # --------------------------------------------------------------------------
    # SCENARIO 7: Pitch Time (Auto, Composite-Machines)
    # --------------------------------------------------------------------------
    res_auto_comp = calculate_auto_composite_balancing(
        operations=operations,
        tolerance=tolerance,
        strict=False,
        production_target=production_target,
        shift_time_minutes=shift_time_minutes,
    )
    ws_auto_comp = res_auto_comp["workstations"]
    rows_auto_comp = normalize_scenario_rows(
        res_auto_comp["formatted_rows"],
        default_pitch=res_auto_comp["pitch_time"],
        default_takt=takt_time,
        default_ucl=res_auto_comp["ucl"],
        default_lcl=res_auto_comp["lcl"],
    )
    kpis_auto_comp, fmt_kpis_auto_comp = compute_kpis_from_workstations(
        ws_auto_comp,
        total_sam,
        available_time_seconds,
        takt_time,
        fixed_cycle_time=res_auto_comp["cycle_time"],
    )
    statuses_auto_comp = [r["Status"] for r in rows_auto_comp]
    scenarios["auto_composite"] = {
        "id": "auto_composite",
        "name": "Pitch Time (Auto, Composite-Machines)",
        "short_name": "Auto (Composite)",
        "description": "Factory Auto Pitch Time (+/-15%) with cross-machine composite merging",
        "workstations": ws_auto_comp,
        "rows": rows_auto_comp,
        "kpis": kpis_auto_comp,
        "formatted_kpis": fmt_kpis_auto_comp,
        "reference_lines": {
            "takt_time": takt_time,
            "pitch_time": res_auto_comp["pitch_time"],
            "ucl": res_auto_comp["ucl"],
            "lcl": res_auto_comp["lcl"],
        },
        "review_flag_count": sum(1 for s in statuses_auto_comp if "review" in s.lower() or "> UCL" in s),
        "demand_met": kpis_auto_comp["cycle_time"] <= takt_time,
    }

    # --------------------------------------------------------------------------
    # 8. UNIFIED COMPARISON TABLE ACROSS ALL 7 SCENARIOS
    # --------------------------------------------------------------------------
    scenario_order = [
        "before",
        "takt_same",
        "pitch_same",
        "takt_composite",
        "pitch_composite",
        "auto_same",
        "auto_composite",
    ]

    metric_defs = [
        ("Composite Operations", "num_workstations", "stations", False, "{:.0f}"),
        ("Total Manpower", "total_manpower", "operators", False, "{:.0f}"),
        ("Cycle Time", "cycle_time", "sec", False, "{:.1f}"),
        ("Achievable Output", "achievable_output", "pcs/available time", True, "{:.0f}"),
        ("Efficiency (Balancing Rate)", "efficiency", "%", True, "{:.1f}%"),
        ("Balancing Delay", "balancing_delay", "%", False, "{:.1f}%"),
        ("Smoothing Index", "smoothing_index", "sec", False, "{:.2f}"),
        ("Labour Productivity", "labour_productivity", "pcs/operator", True, "{:.1f}"),
    ]

    comparison_table = []
    for metric_name, kpi_key, unit, higher_is_better, fmt_str in metric_defs:
        row = {
            "metric": metric_name,
            "key": kpi_key,
            "unit": unit,
            "higher_is_better": higher_is_better,
        }

        vals = {}
        for sid in scenario_order:
            val = scenarios[sid]["kpis"][kpi_key]
            vals[sid] = val
            row[sid] = val
            row[f"formatted_{sid}"] = fmt_str.format(val)

        # Best among the 6 balanced scenarios (excluding baseline 'before')
        balanced_sids = [sid for sid in scenario_order if sid != "before"]
        if higher_is_better:
            best_val = max(vals[s] for s in balanced_sids)
            best_scenarios = [s for s in balanced_sids if abs(vals[s] - best_val) < 1e-5]
        else:
            best_val = min(vals[s] for s in balanced_sids)
            best_scenarios = [s for s in balanced_sids if abs(vals[s] - best_val) < 1e-5]

        row["best_scenario"] = best_scenarios[0] if len(best_scenarios) == 1 else "tie"
        row["best_scenarios"] = best_scenarios
        comparison_table.append(row)

    # --------------------------------------------------------------------------
    # Final Unified Structure
    # --------------------------------------------------------------------------
    result = {
        "shared_parameters": shared_parameters,
        "scenarios": scenarios,
        "scenario_order": scenario_order,
        "comparison_table": comparison_table,
        # Direct scenario keys for top-level access
        "before": scenarios["before"],
        "takt_same": scenarios["takt_same"],
        "pitch_same": scenarios["pitch_same"],
        "takt_composite": scenarios["takt_composite"],
        "pitch_composite": scenarios["pitch_composite"],
        "auto_same": scenarios["auto_same"],
        "auto_composite": scenarios["auto_composite"],
    }

    return result


# ==============================================================================
# CLI Formatter & Runner
# ==============================================================================

def print_all_scenarios_cli(result: Dict[str, Any], filepath: str) -> None:
    """Pretty-print all 7 scenarios comparison to console."""
    sep = "=" * 130
    subsep = "-" * 130

    sp = result["shared_parameters"]
    print("\n" + sep)
    print("  ALL 7 BALANCING SCENARIOS - COMPREHENSIVE COMPARISON  ".center(130))
    print(sep)
    print(f"  Input File        : {filepath}")
    print(f"  Customer Demand   : {sp['customer_demand']} units")
    print(f"  Available Time    : {sp['available_time_minutes']} minutes ({sp['available_time_seconds']:.0f} seconds)")
    print(f"  Customer Takt     : {sp['takt_time']:.1f} seconds")
    print(f"  Total Basic SAM   : {sp['total_sam']:.1f} seconds ({sp['total_sam_minutes']:.2f} minutes)")
    print(f"  Pitch Time (Auto) : {sp['pitch_time']:.1f} seconds  [LCL = {sp['lcl']:.1f}s, UCL = {sp['ucl']:.1f}s]")
    print(sep)

    print("\n" + subsep)
    print("  8 HEADLINE KPIS ACROSS ALL 7 SCENARIOS  ")
    print(subsep)

    rows = []
    headers = [
        "Metric",
        "Unit",
        "1. Before",
        "2. Takt (Same)",
        "3. Pitch (Same)",
        "4. Takt (Comp)",
        "5. Pitch (Comp)",
        "6. Auto (Same)",
        "7. Auto (Comp)",
        "Best Method",
    ]

    short_map = {
        "takt_same": "Takt (Same)",
        "pitch_same": "Pitch (Same)",
        "takt_composite": "Takt (Comp)",
        "pitch_composite": "Pitch (Comp)",
        "auto_same": "Auto (Same)",
        "auto_composite": "Auto (Comp)",
        "tie": "Tie",
    }

    for item in result["comparison_table"]:
        rows.append([
            item["metric"],
            item["unit"],
            item["formatted_before"],
            item["formatted_takt_same"],
            item["formatted_pitch_same"],
            item["formatted_takt_composite"],
            item["formatted_pitch_composite"],
            item["formatted_auto_same"],
            item["formatted_auto_composite"],
            short_map.get(item["best_scenario"], item["best_scenario"]),
        ])

    df_comp = pd.DataFrame(rows, columns=headers)
    if HAS_TABULATE:
        print(tabulate(df_comp, headers="keys", tablefmt="grid", showindex=False))
    else:
        print(df_comp.to_string(index=False))

    print("\n" + subsep)
    print("  WORKSTATIONS & MANPOWER SUMMARY  ")
    print(subsep)
    for sid in result["scenario_order"]:
        sc = result["scenarios"][sid]
        k = sc["kpis"]
        dm = "Demand MET" if sc["demand_met"] else "Demand NOT MET"
        print(f"  - {sc['name']:<42} : Stations={k['num_workstations']:2d} | M/P={k['total_manpower']:2d} | Cycle Time={k['cycle_time']:5.1f}s | Eff={k['efficiency']:5.1f}% | {dm}")
    print(sep + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="All 7 Line Balancing Scenarios Orchestrator"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        default="data/Input2.xlsx",
        help="Path to operations file (CSV/Excel). Default: data/Input2.xlsx",
    )
    parser.add_argument(
        "--demand",
        "-d",
        type=int,
        default=350,
        help="Customer demand units. Default: 350",
    )
    parser.add_argument(
        "--available-time",
        "-t",
        type=float,
        default=420.0,
        help="Available time in minutes. Default: 420",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.15,
        help="Tolerance for Pitch Time bands. Default: 0.15",
    )

    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists():
        repo_root = Path(__file__).resolve().parent.parent.parent
        alt_path = repo_root / args.file
        if alt_path.exists():
            filepath = alt_path
        else:
            print(f"Error: File '{args.file}' not found.")
            sys.exit(1)

    print(f"Reading operations from '{filepath}'...")
    operations = read_operations(str(filepath))
    flagged = [op for op in operations if op.flagged]
    if flagged:
        print(f"Warning: Found {len(flagged)} flagged operations:")
        for op in flagged:
            print(f"  - Op {op.op_id} ({op.name}): {op.flagged}")

    print(f"Running All 7 Balancing Scenarios (Demand={args.demand}, Time={args.available_time}m)...")
    res = run_all_scenarios(
        operations=operations,
        shift_time_minutes=args.available_time,
        production_target=args.demand,
        tolerance=args.tolerance,
    )

    print_all_scenarios_cli(res, str(filepath))


if __name__ == "__main__":
    main()
