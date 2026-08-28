"""
Excel Exporter for Takt vs Pitch Comparison Mode

Produces a professional multi-tab Excel workbook containing:
1. KPI Comparison & Summary (with 8-KPI comparison table, recommendations, and embedded matplotlib charts)
2. Method A (Takt Time) Workstation Table
3. Method B (IE Pitch) Workstation Table (with amber review flag highlights)
4. Before Balancing Operations Table
"""

import io
from typing import Dict, List, Optional
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from openpyxl import Workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import Operation, Workstation


def generate_comparison_profile_chart(
    workstations_a: List[Workstation],
    workstations_b: List[Workstation],
    takt_time: float,
    pitch_time: float,
    ucl: float,
    lcl: float
) -> io.BytesIO:
    """Generate dual balancing curve line chart for Excel embedding."""
    fig, ax = plt.subplots(figsize=(14, 6), dpi=150)

    # Prepare data
    max_stations = max(len(workstations_a), len(workstations_b))
    x_indices = list(range(1, max_stations + 1))

    times_a = [ws.balancing_sam for ws in workstations_a]
    times_b = [ws.balancing_sam for ws in workstations_b]

    # Method A Line (Blue)
    ax.plot(
        range(1, len(times_a) + 1),
        times_a,
        marker='o',
        linewidth=2.5,
        color='#3b82f6',
        label=f'Method A — Takt Time ({len(workstations_a)} Stns)',
        zorder=4
    )

    # Method B Line (Emerald Green)
    ax.plot(
        range(1, len(times_b) + 1),
        times_b,
        marker='s',
        linewidth=2.5,
        color='#10b981',
        label=f'Method B — IE Pitch ({len(workstations_b)} Stns)',
        zorder=4
    )

    # Reference lines
    ax.axhline(y=takt_time, color='#ef4444', linestyle='--', linewidth=2, label=f'Takt Time Ceiling ({takt_time:.1f}s)', zorder=3)
    ax.axhline(y=ucl, color='#f59e0b', linestyle=':', linewidth=1.8, label=f'Method B UCL ({ucl:.1f}s)', zorder=3)
    ax.axhline(y=lcl, color='#f97316', linestyle=':', linewidth=1.8, label=f'Method B LCL ({lcl:.1f}s)', zorder=3)

    # Style plot
    ax.set_title("Balancing Profiles: Method A (Takt Time) vs Method B (IE Pitch)", fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel("Workstation Index", fontsize=11, fontweight='bold', labelpad=8)
    ax.set_ylabel("Cycle Time / Balancing SAM (seconds)", fontsize=11, fontweight='bold', labelpad=8)
    ax.set_xticks(x_indices)
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper right', framealpha=0.9)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_comparison_kpi_bar_chart(comparison_data: Dict) -> io.BytesIO:
    """Generate grouped bar chart comparing key KPIs for Excel embedding."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=150)

    # Chart 1: Core Metrics (Manpower & Workstations)
    categories_1 = ['Total Manpower\n(Operators)', 'Composite Ops\n(Workstations)']
    before_1 = [comparison_data['before']['total_manpower'], comparison_data['before']['num_operations']]
    method_a_1 = [comparison_data['method_a']['total_manpower'], comparison_data['method_a']['num_workstations']]
    method_b_1 = [comparison_data['method_b']['total_manpower'], comparison_data['method_b']['num_workstations']]

    x = np.arange(len(categories_1))
    width = 0.25

    ax1.bar(x - width, before_1, width, label='Before (Baseline)', color='#94a3b8')
    ax1.bar(x, method_a_1, width, label='Method A (Takt)', color='#3b82f6')
    ax1.bar(x + width, method_b_1, width, label='Method B (Pitch)', color='#10b981')

    ax1.set_title("Headcount & Station Count", fontsize=12, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(categories_1, fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.4, axis='y')
    ax1.legend(loc='upper right')

    # Chart 2: Efficiency & Balance Delay %
    categories_2 = ['Line Efficiency\n(%)', 'Balance Delay\n(%)']
    before_2 = [comparison_data['before']['efficiency_balancing_rate'], comparison_data['before']['comparison_balance_delay']]
    method_a_2 = [comparison_data['method_a']['efficiency_balancing_rate'], comparison_data['method_a']['comparison_balance_delay']]
    method_b_2 = [comparison_data['method_b']['efficiency_balancing_rate'], comparison_data['method_b']['comparison_balance_delay']]

    x2 = np.arange(len(categories_2))
    ax2.bar(x2 - width, before_2, width, label='Before (Baseline)', color='#94a3b8')
    ax2.bar(x2, method_a_2, width, label='Method A (Takt)', color='#3b82f6')
    ax2.bar(x2 + width, method_b_2, width, label='Method B (Pitch)', color='#10b981')

    ax2.set_title("Efficiency & Delay Rates (%)", fontsize=12, fontweight='bold')
    ax2.set_xticks(x2)
    ax2.set_xticklabels(categories_2, fontsize=10, fontweight='bold')
    ax2.set_ylim(0, 105)
    ax2.grid(True, linestyle='--', alpha=0.4, axis='y')
    ax2.legend(loc='upper right')

    plt.suptitle("Takt vs Pitch Headline Performance Metrics", fontsize=14, fontweight='bold', y=0.98)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_comparison_excel(calc: Dict) -> io.BytesIO:
    """
    Build a multi-tab Excel workbook with complete side-by-side comparison tables,
    detailed workstation views for Method A and Method B, baseline data, and embedded charts.
    """
    wb = Workbook()

    # Define standard styles
    font_title = Font(size=15, bold=True, color="1E40AF")
    font_section = Font(size=12, bold=True, color="1E293B")
    font_bold = Font(size=10, bold=True)
    font_regular = Font(size=10)
    font_header = Font(size=10, bold=True, color="FFFFFF")
    font_winner = Font(size=10, bold=True, color="166534")

    fill_header = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    fill_sub_a = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
    fill_sub_b = PatternFill(start_color="10B981", end_color="10B981", fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_winner = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    fill_warning = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")

    thin_border_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    # =========================================================================
    # TAB 1: KPI Comparison & Summary
    # =========================================================================
    ws1 = wb.active
    ws1.title = "Comparison Summary"
    ws1.views.sheetView[0].showGridLines = True

    # Title
    ws1['A1'] = "Takt vs Pitch Balancing Comparison Report"
    ws1['A1'].font = font_title
    ws1.merge_cells('A1:E1')
    ws1['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 30

    # Summary Metadata
    curr_row = 3
    meta_items = [
        ("Customer Demand", f"{calc['production_target']} units"),
        ("Available Shift Time", f"{calc['shift_time_minutes']:.1f} minutes"),
        ("Total Basic Time (SAM)", f"{calc['total_sam'] / 60:.2f} min ({calc['total_sam']:.1f} s)"),
        ("Takt Time (Method A Ceiling)", f"{calc['takt_time']:.2f} seconds"),
        ("IE Pitch Time (Method B Base)", f"{calc['pitch_time']:.2f} seconds"),
        ("Method B UCL / LCL (±15%)", f"{calc['ucl']:.2f} s / {calc['lcl']:.2f} s"),
    ]
    for label, val in meta_items:
        ws1[f'A{curr_row}'] = label
        ws1[f'A{curr_row}'].font = font_bold
        ws1[f'B{curr_row}'] = val
        ws1[f'B{curr_row}'].font = font_regular
        curr_row += 1

    curr_row += 1

    # Master Headline Comparison Table
    ws1[f'A{curr_row}'] = "Headline 8-KPI Side-by-Side Comparison"
    ws1[f'A{curr_row}'].font = font_section
    curr_row += 1

    headers = ["Metric Name", "Unit", "Before Balancing (Baseline)", "Method A — Takt Time", "Method B — IE Pitch"]
    for col_idx, h in enumerate(headers, 1):
        cell = ws1.cell(row=curr_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = cell_border
    ws1.row_dimensions[curr_row].height = 24
    curr_row += 1

    for r_idx, comp_row in enumerate(calc["comparison"]):
        c1 = ws1.cell(row=curr_row, column=1, value=comp_row["metric"])
        c2 = ws1.cell(row=curr_row, column=2, value=comp_row["unit"])
        c3 = ws1.cell(row=curr_row, column=3, value=comp_row["formatted_before"])
        c4 = ws1.cell(row=curr_row, column=4, value=comp_row["formatted_method_a"])
        c5 = ws1.cell(row=curr_row, column=5, value=comp_row["formatted_method_b"])

        for c in [c1, c2, c3, c4, c5]:
            c.font = font_regular
            c.border = cell_border
            c.alignment = Alignment(horizontal="center" if c.column > 1 else "left", vertical="center")
            if r_idx % 2 == 1:
                c.fill = fill_zebra

        # Highlight winner cell
        winner = comp_row.get("winner", "none")
        if winner == "method_a":
            c4.fill = fill_winner
            c4.font = font_winner
        elif winner == "method_b":
            c5.fill = fill_winner
            c5.font = font_winner
        elif winner == "tie":
            c4.fill = fill_winner
            c5.fill = fill_winner

        ws1.row_dimensions[curr_row].height = 20
        curr_row += 1

    curr_row += 1

    # Recommendation Callout Section
    recs = calc.get("recommendations", [])
    if recs:
        ws1[f'A{curr_row}'] = "Balancing Analysis & Recommendations"
        ws1[f'A{curr_row}'].font = font_section
        curr_row += 1
        for rec in recs:
            ws1[f'A{curr_row}'] = f"• {rec}"
            ws1[f'A{curr_row}'].font = font_regular
            ws1.merge_cells(f'A{curr_row}:E{curr_row}')
            ws1[f'A{curr_row}'].alignment = Alignment(wrap_text=True, vertical="center")
            curr_row += 1
        curr_row += 1

    # Embed Matplotlib Charts
    try:
        kpi_chart_buf = generate_comparison_kpi_bar_chart(calc)
        kpi_img = OpenpyxlImage(kpi_chart_buf)
        kpi_img.width = 650
        kpi_img.height = 250
        ws1.add_image(kpi_img, f'A{curr_row}')
        curr_row += 14

        profile_chart_buf = generate_comparison_profile_chart(
            calc['method_a']['workstations'],
            calc['method_b']['workstations'],
            calc['takt_time'],
            calc['pitch_time'],
            calc['ucl'],
            calc['lcl']
        )
        profile_img = OpenpyxlImage(profile_chart_buf)
        profile_img.width = 650
        profile_img.height = 280
        ws1.add_image(profile_img, f'A{curr_row}')
    except Exception as e:
        print(f"Warning embedding chart image in Excel: {e}")

    # Auto column width for Sheet 1
    for col in ws1.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # =========================================================================
    # TAB 2: Method A (Takt Time) Workstation Table
    # =========================================================================
    ws2 = wb.create_sheet(title="Method A - Takt Time")
    ws2.views.sheetView[0].showGridLines = True

    ws2['A1'] = "Method A (Takt Time) — Balanced Workstations"
    ws2['A1'].font = font_title
    ws2.merge_cells('A1:K1')
    ws2['A1'].alignment = Alignment(horizontal="center", vertical="center")

    df_a = calc["method_a"]["report_df"]
    cols_a = [c for c in ["Composite Operations", "Serial/Id", "Operations", "Machine", "Predecessor", "Basic Time", "Combined SAM", "Balancing SAM", "M/P", "Takt Time", "Status"] if c in df_a.columns]
    df_a_export = df_a[cols_a] if not df_a.empty else df_a

    headers_a = list(df_a_export.columns)
    for col_idx, col_name in enumerate(headers_a, 1):
        cell = ws2.cell(row=3, column=col_idx, value=col_name)
        cell.font = font_header
        cell.fill = fill_sub_a
        cell.border = cell_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, row_data in enumerate(df_a_export.values, 4):
        for col_idx, val in enumerate(row_data, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            cell.alignment = Alignment(horizontal="center" if col_idx in (1, 7, 8, 9, 10, 11) else "left", vertical="center")
            if row_idx % 2 == 1:
                cell.fill = fill_zebra

    for col in ws2.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws2.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # =========================================================================
    # TAB 3: Method B (IE Pitch) Workstation Table
    # =========================================================================
    ws3 = wb.create_sheet(title="Method B - IE Pitch")
    ws3.views.sheetView[0].showGridLines = True

    ws3['A1'] = "Method B (IE Pitch) — Balanced Workstations"
    ws3['A1'].font = font_title
    ws3.merge_cells('A1:M1')
    ws3['A1'].alignment = Alignment(horizontal="center", vertical="center")

    df_b = calc["method_b"]["report_df"]
    cols_b = [c for c in ["Composite Operations", "Serial/Id", "Operations", "Machine", "Predecessor", "Basic Time", "Combined SAM", "Balancing SAM", "M/P", "Pitch Time", "LCL", "UCL", "Status"] if c in df_b.columns]
    df_b_export = df_b[cols_b] if not df_b.empty else df_b

    headers_b = list(df_b_export.columns)
    for col_idx, col_name in enumerate(headers_b, 1):
        cell = ws3.cell(row=3, column=col_idx, value=col_name)
        cell.font = font_header
        cell.fill = fill_sub_b
        cell.border = cell_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, row_data in enumerate(df_b_export.values, 4):
        for col_idx, val in enumerate(row_data, 1):
            cell = ws3.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            cell.alignment = Alignment(horizontal="center" if col_idx in (1, 7, 8, 9, 10, 11, 12, 13) else "left", vertical="center")
            if row_idx % 2 == 1:
                cell.fill = fill_zebra
            # Highlight review flags in amber
            if "Above UCL" in str(val) or "review" in str(val).lower():
                cell.fill = fill_warning
                cell.font = font_bold

    for col in ws3.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws3.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # =========================================================================
    # TAB 4: Before Balancing (Baseline) Operations Table
    # =========================================================================
    ws4 = wb.create_sheet(title="Before Balancing")
    ws4.views.sheetView[0].showGridLines = True

    ws4['A1'] = "Before Balancing — Input Operations Baseline"
    ws4['A1'].font = font_title
    ws4.merge_cells('A1:F1')
    ws4['A1'].alignment = Alignment(horizontal="center", vertical="center")

    headers_before = ["Serial No.", "Operation Name", "Predecessor", "Machine Type", "Basic Time (s)", "Manpower"]
    for col_idx, h in enumerate(headers_before, 1):
        cell = ws4.cell(row=3, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.border = cell_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, op in enumerate(calc.get("sorted_operations", []), 4):
        preds_str = ",".join(map(str, op.predecessors)) if getattr(op, "predecessors", None) else "-"
        vals = [getattr(op, "op_id", ""), getattr(op, "name", ""), preds_str, getattr(op, "machine_type", ""), getattr(op, "basic_time", 0.0), 1]
        for col_idx, val in enumerate(vals, 1):
            cell = ws4.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            cell.alignment = Alignment(horizontal="center" if col_idx in (1, 3, 5, 6) else "left", vertical="center")
            if row_idx % 2 == 1:
                cell.fill = fill_zebra

    for col in ws4.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws4.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # Return as buffer
    excel_buf = io.BytesIO()
    wb.save(excel_buf)
    excel_buf.seek(0)
    return excel_buf
