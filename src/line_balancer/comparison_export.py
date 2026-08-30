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
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from .models import Operation, Workstation


def style_range(ws, cell_range, border=None, alignment=None, fill=None):
    """Apply styling across an entire cell range (e.g. merged title banner cells)."""
    for row in ws[cell_range]:
        for cell in row:
            if border:
                cell.border = border
            if alignment:
                cell.alignment = alignment
            if fill:
                cell.fill = fill


def autofit_columns(ws, start_row=3, padding=3, min_width=6):
    """Auto-fit column widths like Alt+H+O+I in Excel."""
    for col in ws.columns:
        cells_to_check = [
            c for c in col if c.row >= start_row and c.value is not None
        ]
        if not cells_to_check:
            continue
        max_len = max(len(str(c.value)) for c in cells_to_check)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + padding,
                                                     min_width)


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

    fill_header = PatternFill(start_color="2563EB",
                              end_color="2563EB",
                              fill_type="solid")
    fill_sub_a = PatternFill(start_color="3B82F6",
                             end_color="3B82F6",
                             fill_type="solid")
    fill_sub_b = PatternFill(start_color="10B981",
                             end_color="10B981",
                             fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC",
                             end_color="F8FAFC",
                             fill_type="solid")
    fill_winner = PatternFill(start_color="DCFCE7",
                              end_color="DCFCE7",
                              fill_type="solid")
    fill_warning = PatternFill(start_color="FEF3C7",
                               end_color="FEF3C7",
                               fill_type="solid")

    # True solid black border matching Excel's Alt+H+B+A (All Borders)
    thin_border_side = Side(border_style="thin", color="000000")
    cell_border = Border(left=thin_border_side,
                         right=thin_border_side,
                         top=thin_border_side,
                         bottom=thin_border_side)

    # =========================================================================
    # TAB 1: KPI Comparison & Summary
    # =========================================================================
    ws1 = wb.active
    ws1.title = "Comparison Summary"
    ws1.views.sheetView[0].showGridLines = True

    # Title Banner (Alt+H+B+A & Alt+H+A+C)
    ws1['A1'] = "Takt vs Pitch Balancing Comparison Report"
    ws1['A1'].font = font_title
    ws1.merge_cells('A1:E2')
    ws1['A1'].alignment = Alignment(horizontal="center", vertical="center")
    style_range(ws1, 'A1:E2', border=cell_border)
    ws1.row_dimensions[1].height = 30

    # Summary Metadata
    curr_row = 3
    meta_items = [
        ("Customer Demand", f"{calc['production_target']} units"),
        ("Available Shift Time", f"{calc['shift_time_minutes']:.1f} minutes"),
        ("Total Basic Time (SAM)",
         f"{calc['total_sam'] / 60:.2f} min ({calc['total_sam']:.1f} s)"),
        ("Takt Time (Method A Ceiling)", f"{calc['takt_time']:.2f} seconds"),
        ("IE Pitch Time (Method B Base)", f"{calc['pitch_time']:.2f} seconds"),
        ("Method B UCL / LCL (±15%)",
         f"{calc['ucl']:.2f} s / {calc['lcl']:.2f} s"),
    ]
    for label, val in meta_items:
        c_a = ws1[f'A{curr_row}']
        c_a.value = label
        c_a.font = font_bold
        c_a.border = cell_border
        c_b = ws1[f'B{curr_row}']
        c_b.value = val
        c_b.font = font_regular
        c_b.border = cell_border
        curr_row += 1

    curr_row += 1

    # Master Headline Comparison Table
    ws1[f'A{curr_row}'] = "Headline 8-KPI Side-by-Side Comparison"
    ws1[f'A{curr_row}'].font = font_section
    curr_row += 1

    headers = [
        "Metric Name", "Unit", "Before Balancing (Baseline)",
        "Method A — Takt Time", "Method B — IE Pitch"
    ]
    for col_idx, h in enumerate(headers, 1):
        cell = ws1.cell(row=curr_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(
            horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = cell_border
    ws1.row_dimensions[curr_row].height = 24
    curr_row += 1

    for r_idx, comp_row in enumerate(calc["comparison"]):
        c1 = ws1.cell(row=curr_row, column=1, value=comp_row["metric"])
        c2 = ws1.cell(row=curr_row, column=2, value=comp_row["unit"])
        c3 = ws1.cell(row=curr_row,
                      column=3,
                      value=comp_row["formatted_before"])
        c4 = ws1.cell(row=curr_row,
                      column=4,
                      value=comp_row["formatted_method_a"])
        c5 = ws1.cell(row=curr_row,
                      column=5,
                      value=comp_row["formatted_method_b"])

        for c in [c1, c2, c3, c4, c5]:
            c.font = font_regular
            c.border = cell_border
            c.alignment = Alignment(
                horizontal="center" if c.column > 1 else "left",
                vertical="center")
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
            style_range(ws1, f'A{curr_row}:E{curr_row}', border=cell_border)
            ws1[f'A{curr_row}'].alignment = Alignment(wrap_text=True,
                                                      vertical="center")
            curr_row += 1
        curr_row += 1

    # Auto column width for Sheet 1 (Alt+H+O+I)
    for col in ws1.columns:
        cells_to_check = [
            c for c in col[2:] if c.value and not str(c.value).startswith("•")
            and "Balancing Analysis" not in str(c.value)
        ]
        max_len = max((len(str(cell.value or '')) for cell in cells_to_check),
                      default=10)
        col_letter = get_column_letter(col[0].column)
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 14)

    # =========================================================================
    # TAB 3: Method A (Takt Time) Workstation Table
    # =========================================================================
    ws2 = wb.create_sheet(title="Method A - Takt Time")
    ws2.views.sheetView[0].showGridLines = True

    # Title Banner (Alt+H+B+A & Alt+H+A+C)
    ws2['A1'] = "Method A (Takt Time) — Balanced Workstations"
    ws2['A1'].font = font_title
    ws2.merge_cells('A1:K2')
    ws2['A1'].alignment = Alignment(horizontal="center", vertical="center")
    style_range(ws2, 'A1:K2', border=cell_border)

    df_a = calc["method_a"]["report_df"].rename(columns={"Basic Time": "SAM"})
    cols_a = [
        c for c in [
            "Composite Operations", "Serial/Id", "Operations", "Machine",
            "Predecessor", "SAM", "Combined SAM", "Balancing SAM", "M/P",
            "Takt Time", "Status"
        ] if c in df_a.columns
    ]
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
            # Alt + H + A + C: Center all cells horizontally and vertically
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if row_idx % 2 == 1:
                cell.fill = fill_zebra

    # Auto column width for Method A (Alt+H+O+I)
    autofit_columns(ws2, start_row=3, padding=3, min_width=6)

    # =========================================================================
    # TAB 4: Method B (IE Pitch) Workstation Table
    # =========================================================================
    ws3 = wb.create_sheet(title="Method B - IE Pitch")
    ws3.views.sheetView[0].showGridLines = True

    # Title Banner (Alt+H+B+A & Alt+H+A+C)
    ws3['A1'] = "Method B (IE Pitch) — Balanced Workstations"
    ws3['A1'].font = font_title
    ws3.merge_cells('A1:L2')
    ws3['A1'].alignment = Alignment(horizontal="center", vertical="center")
    style_range(ws3, 'A1:L2', border=cell_border)

    df_b = calc["method_b"]["report_df"].rename(columns={"Basic Time": "SAM"})
    cols_b = [
        c for c in [
            "Composite Operations", "Serial/Id", "Operations", "Machine",
            "Predecessor", "SAM", "Combined SAM", "Balancing SAM", "M/P",
            "Pitch Time", "UCL", "Status"
        ] if c in df_b.columns
    ]
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
            # Alt + H + A + C: Center all cells horizontally and vertically
            cell.alignment = Alignment(horizontal="center", vertical="center")
            if row_idx % 2 == 1:
                cell.fill = fill_zebra
            # Highlight review flags in amber
            if "Above UCL" in str(val) or "review" in str(val).lower():
                cell.fill = fill_warning
                cell.font = font_bold

    # Auto column width for Method B (Alt+H+O+I)
    autofit_columns(ws3, start_row=3, padding=3, min_width=6)

    # =========================================================================
    # TAB 2: Before Balancing (Baseline) Operations Table
    # =========================================================================
    ws4 = wb.create_sheet(title="Before Balancing", index=1)
    ws4.views.sheetView[0].showGridLines = True

    # Title Banner (Alt+H+B+A & Alt+H+A+C)
    ws4['A1'] = "Before Balancing — Input Operations Baseline"
    ws4['A1'].font = font_title
    ws4.merge_cells('A1:F2')
    ws4['A1'].alignment = Alignment(horizontal="center", vertical="center")
    style_range(ws4, 'A1:F2', border=cell_border)

    headers_before = [
        "Serial No.", "Operation Name", "Predecessor", "Machine Type", "SAM",
        "Manpower"
    ]
    for col_idx, h in enumerate(headers_before, 1):
        cell = ws4.cell(row=3, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.border = cell_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, op in enumerate(calc.get("sorted_operations", []), 4):
        preds_str = ",".join(map(str, op.predecessors)) if getattr(
            op, "predecessors", None) else "-"

        # Round SAM to 1 decimal place (e.g. 7.929207 -> 7.9, 21.884868 -> 21.9)
        sam_val = round(float(getattr(op, "basic_time", 0.0) or 0.0), 1)

        vals = [
            getattr(op, "op_id", ""),
            getattr(op, "name", ""), preds_str,
            getattr(op, "machine_type", ""), sam_val, 1
        ]
        for col_idx, val in enumerate(vals, 1):
            cell = ws4.cell(row=row_idx, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = cell_border
            # Alt + H + A + C: Center all cells horizontally and vertically
            cell.alignment = Alignment(horizontal="center", vertical="center")

            # Ensure Excel displays 1 decimal place even for whole numbers (e.g. 7.0)
            if col_idx == 5:
                cell.number_format = '0.0'

            if row_idx % 2 == 1:
                cell.fill = fill_zebra

    # Auto column width for Before Balancing (Alt+H+O+I)
    autofit_columns(ws4, start_row=3, padding=3, min_width=6)

    # Return as buffer
    excel_buf = io.BytesIO()
    wb.save(excel_buf)
    excel_buf.seek(0)
    return excel_buf
