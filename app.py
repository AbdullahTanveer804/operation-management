"""
Line Balancing Tool - Modern Web Application

A professional Flask web app for:
- IE departments (planning view): full features on desktop
- Real-time balancing calculations and manual overrides
"""

import json
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from flask import Flask, jsonify, render_template_string, request, send_file
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.line_balancer.models import Operation, Workstation
from src.line_balancer.io_utils import read_operations
from src.line_balancer.sequencing import sort_by_id
from src.line_balancer.metrics import calculate_pitch_time, calculate_pitch_time_from_target, calculate_tolerance_bands, calculate_line_balancing_rate, calculate_balance_delay, calculate_line_efficiency, calculate_smoothing_index
from src.line_balancer.balancing import group_and_balance
from src.line_balancer.report import build_report_dataframe, determine_status
from src.line_balancer.before_balancing_metrics import calculate_all_before_metrics

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max

# In-memory session storage (use Redis/DB for production)
SESSIONS = {}


def generate_session_id():
    """Generate a unique session ID."""
    return str(uuid.uuid4())[:8]


def store_calculation(session_id: str, data: Dict):
    """Store calculation results in session."""
    SESSIONS[session_id] = data
    print(f"Stored calculation for session {session_id}. Total sessions: {len(SESSIONS)}")


def get_calculation(session_id: str) -> Optional[Dict]:
    """Retrieve calculation results from session."""
    result = SESSIONS.get(session_id)
    print(f"Retrieved calculation for session {session_id}: {result is not None}")
    return result


def calculate_balance(operations: List[Operation], tolerance: float = 0.15, manual_pitch_time: Optional[float] = None, production_target: Optional[int] = None, shift_time_minutes: Optional[float] = None, pitch_time_method: str = "auto") -> Dict:
    """
    Run the complete balancing calculation and return all results.
    
    Args:
        operations: List of Operation objects from CSV/Excel
        tolerance: UCL/LCL tolerance (default 15%)
        manual_pitch_time: Optional manual pitch time override
        production_target: Optional production target for line efficiency calculation and pitch time calculation
        shift_time_minutes: Optional shift time in minutes for line efficiency calculation and pitch time calculation
        pitch_time_method: Method for calculating pitch time ("auto", "manual", "target")
    
    Returns:
        Dictionary with all calculation results
    """
    # Step 1: Sort operations by ID
    sorted_ops = sort_by_id(operations)
    
    # Step 2: Calculate Pitch Time / Takt Time based on method
    if pitch_time_method == "manual":
        if manual_pitch_time is None or manual_pitch_time <= 0:
            raise ValueError("Manual pitch time must be provided and positive when method is 'manual'.")
        pitch_time = manual_pitch_time
        pitch_time_source = "manual"
        # Clear target-related parameters for manual method
        production_target = None
        shift_time_minutes = None
    elif pitch_time_method == "target":
        if production_target is None or production_target <= 0:
            raise ValueError("Production target must be provided and positive when method is 'target'.")
        if shift_time_minutes is None or shift_time_minutes <= 0:
            raise ValueError("Shift time must be provided and positive when method is 'target'.")
        pitch_time = calculate_pitch_time_from_target(production_target, shift_time_minutes, tolerance)
        pitch_time_source = "By Target"
    else:  # auto (default)
        pitch_time = calculate_pitch_time(sorted_ops)
        pitch_time_source = "calculated"
        # Clear target-related parameters for auto method
        production_target = None
        shift_time_minutes = None
    
    ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)
    
    # Step 3: Balance operations into workstations
    workstations = group_and_balance(sorted_ops, ucl, lcl)
    
    # Step 4: Calculate line balancing rate
    line_balancing_rate = calculate_line_balancing_rate(workstations)
    
    # Step 4.5: Calculate balance delay
    balance_delay = calculate_balance_delay(workstations, sorted_ops)
    
    # Step 4.6: Calculate line efficiency (if production target and shift time provided and method is target)
    line_efficiency = None
    if pitch_time_method == "target" and production_target is not None and shift_time_minutes is not None:
        if production_target <= 0 or shift_time_minutes <= 0:
            raise ValueError("Production target and shift time must be positive numbers.")
        line_efficiency = calculate_line_efficiency(workstations, sorted_ops, production_target, shift_time_minutes)
    
    # Step 4.7: Calculate smoothing index
    smoothing_index = calculate_smoothing_index(workstations)
    
    # Step 4.8: Calculate total basic time (SAM) in minutes
    total_basic_time = sum(op.basic_time for op in sorted_ops) / 60  # Convert seconds to minutes
    
    # Step 4.9: Calculate before-balancing metrics
    before_metrics = calculate_all_before_metrics(sorted_ops, production_target, shift_time_minutes, tolerance, pitch_time_method, manual_pitch_time)
    
    # Step 5: Build report
    report_df = build_report_dataframe(workstations, ucl, lcl, pitch_time, pitch_time_source)
    
    return {
        "operations": operations,
        "sorted_operations": sorted_ops,
        "pitch_time": pitch_time,
        "pitch_time_source": pitch_time_source,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "line_balancing_rate": line_balancing_rate,
        "balance_delay": balance_delay,
        "line_efficiency": line_efficiency,
        "smoothing_index": smoothing_index,
        "total_basic_time": total_basic_time,
        "production_target": production_target,
        "shift_time_minutes": shift_time_minutes,
        "report_df": report_df,
        "tolerance": tolerance,
        "before_metrics": before_metrics,
    }


def generate_chart_image(workstations, pitch_time, ucl, lcl, pitch_time_source="calculated") -> io.BytesIO:
    """
    Generate a bar chart image using matplotlib that matches the client-side Chart.js styling.
    
    Args:
        workstations: List of Workstation objects
        pitch_time: Target pitch time
        ucl: Upper control limit
        lcl: Lower control limit
        pitch_time_source: Source of pitch time calculation ("manual", "By Target", or "calculated")
    
    Returns:
        BytesIO object containing the PNG image
    """
    # Use non-interactive backend to avoid display issues
    matplotlib.use('Agg')
    
    # Prepare data
    workstation_names = []
    balancing_sam = []
    
    for ws in workstations:
        # Join operation names with " + " for each workstation
        op_names = " + ".join(op.name for op in ws.operations)
        workstation_names.append(op_names)
        balancing_sam.append(ws.balancing_sam)
    
    # Determine pitch time label based on source
    if pitch_time_source == "manual" or pitch_time_source == "By Target":
        pitch_time_label = "Takt Time"
    else:
        pitch_time_label = "Pitch Time"
    
    # Create figure with appropriate size
    fig, ax = plt.subplots(figsize=(18, 9))
    
    # Create bar chart with blue color matching Chart.js
    bars = ax.bar(range(len(workstation_names)), balancing_sam, 
                  color=(59/255, 130/255, 246/255, 0.8), 
                  edgecolor=(59/255, 130/255, 246/255, 1.0),
                  linewidth=1,
                  width=0.6)
    
    # Add reference lines
    ax.axhline(y=ucl, color=(239/255, 68/255, 68/255), linestyle='--', linewidth=2, label='UCL')
    ax.axhline(y=pitch_time, color=(34/255, 197/255, 94/255), linestyle='--', linewidth=2, label=pitch_time_label)
    ax.axhline(y=lcl, color=(249/255, 115/255, 22/255), linestyle='--', linewidth=2, label='LCL')
    
    # Set labels and title
    ax.set_xlabel('Workstations', fontsize=12, fontweight='500')
    ax.set_ylabel('Time (seconds)', fontsize=12, fontweight='500')
    ax.set_title('Line Balancing Chart', fontsize=14, fontweight='600', color='#3b82f6')
    
    # Set x-axis ticks to workstation names
    ax.set_xticks(range(len(workstation_names)))
    ax.set_xticklabels(workstation_names, rotation=45, ha='right', fontsize=9)
    
    # Format y-axis labels
    ax.set_yticklabels([f'{x:.1f}s' for x in ax.get_yticks()], fontsize=10)
    
    # Add legend
    ax.legend(loc='upper right', fontsize=10)
    
    # Add grid for better readability
    ax.grid(axis='y', alpha=0.1, linestyle='-')
    ax.grid(axis='x', alpha=0.1, linestyle='-')
    
    # Set background color to white for Excel export
    ax.set_facecolor('white')
    fig.patch.set_facecolor('white')
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Save to BytesIO
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
    img_buffer.seek(0)
    
    # Close the figure to free memory
    plt.close(fig)
    
    return img_buffer


# ============== ROUTES ==============

@app.route("/", methods=["GET", "POST"])
def index():
    """Main page: upload file, configure parameters, view results."""
    error = None
    result = None
    session_id = None
    rows = []
    
    if request.method == "POST":
        try:
            # Get file and parameters
            file = request.files.get("file")
            pitch_time_method = request.form.get("pitch_time_method", "auto")
            pitch_time_str = request.form.get("pitch_time", "")
            tolerance_str = request.form.get("tolerance", "15")
            production_target_str = request.form.get("production_target", "")
            shift_time_str = request.form.get("shift_time", "")
            
            if not file or file.filename == "":
                error = "Please select a file to upload."
            else:
                # Parse parameters
                manual_pitch_time = float(pitch_time_str) if pitch_time_str else None
                tolerance_percentage = float(tolerance_str)
                production_target = int(production_target_str) if production_target_str else None
                shift_time_minutes = float(shift_time_str) if shift_time_str else None
                
                # Validate tolerance range (0-100% input)
                if tolerance_percentage < 0 or tolerance_percentage > 100:
                    error = "Tolerance must be between 0 and 100%."
                tolerance = tolerance_percentage / 100  # Convert percentage to decimal
                
                # Validate based on pitch time method
                if pitch_time_method == "manual":
                    if manual_pitch_time is None or manual_pitch_time <= 0:
                        error = "Manual Takt time must be provided and positive when method is 'manual'."
                    # Clear shift time and production target for manual method
                    shift_time_minutes = None
                    production_target = None
                elif pitch_time_method == "target":
                    if production_target is None or production_target <= 0:
                        error = "Production target must be provided and positive when method is 'target'."
                    elif shift_time_minutes is None or shift_time_minutes <= 0:
                        error = "Shift time must be provided and positive when method is 'target'."
                else:  # auto
                    # No validation needed for auto method
                    # Clear shift time and production target for auto method
                    shift_time_minutes = None
                    production_target = None
                
                if not error:
                    # Read operations from file
                    filepath = Path(file.filename)
                    if filepath.suffix.lower() not in (".csv", ".xlsx", ".xls"):
                        error = "File must be Excel (.xlsx, .xls) or CSV."
                    else:
                        # Save temporarily and read
                        temp_path = None
                        try:
                            with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=Path(file.filename).suffix) as tmp:
                                file.save(tmp.name)
                                temp_path = tmp.name
                            
                            operations = read_operations(temp_path)
                            
                            # Check for errors in operations
                            flagged = [op for op in operations if op.flagged]
                            if flagged:
                                error_list = "<br>".join([f"Op {op.op_id}: {op.flagged}" for op in flagged])
                                error = f"File has validation errors:<br>{error_list}"
                            else:
                                # Run calculation
                                result = calculate_balance(operations, tolerance, manual_pitch_time, production_target, shift_time_minutes, pitch_time_method)
                                
                                # Convert dataframe to list of dicts for template
                                df = result["report_df"]
                                rows = df.to_dict("records")
                                
                                # Format numeric values
                                for row in rows:
                                    row["Combined Basic Time"] = f"{row['Combined Basic Time']:.1f}"
                                    row["Balancing SAM"] = f"{row['Balancing SAM']:.1f}"
                                    # Format new columns if they are numeric - handle dynamic column name
                                    if "Pitch Time" in row and row["Pitch Time"]:
                                        row["Pitch Time"] = f"{row['Pitch Time']:.1f}"
                                    elif "Takt Time" in row and row["Takt Time"]:
                                        row["Takt Time"] = f"{row['Takt Time']:.1f}"
                                    if row["UCL"]:
                                        row["UCL"] = f"{row['UCL']:.1f}"
                                    if row["LCL"]:
                                        row["LCL"] = f"{row['LCL']:.1f}"
                                
                                # Generate session ID
                                session_id = generate_session_id()
                                store_calculation(session_id, result)
                        
                        finally:
                            # Clean up temp file
                            if temp_path and os.path.exists(temp_path):
                                try:
                                    os.remove(temp_path)
                                except:
                                    pass
        
        except Exception as e:
            error = f"Error processing file: {str(e)}"
    
    return render_template_string(HTML_TEMPLATE, 
                                  error=error, 
                                  result=result, 
                                  rows=rows, 
                                  session_id=session_id)


@app.route("/api/export/<format>/<session_id>")
def export(format: str, session_id: str):
    """Export results to Excel."""
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found"}), 404
    
    df = calc["report_df"]
    
    if format == "xlsx":
        # Generate chart image
        chart_img = generate_chart_image(
            calc["workstations"],
            calc["pitch_time"],
            calc["ucl"],
            calc["lcl"],
            calc.get("pitch_time_source", "calculated")
        )
        
        # Create Excel workbook with openpyxl
        wb = Workbook()
        worksheet = wb.active
        worksheet.title = "Line Balance Report"
        
        # Add title and metrics
        worksheet['A1'] = "Line Balancing Report"
        worksheet['A1'].font = Font(size=16, bold=True, color="3B82F6")
        worksheet['A1'].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.merge_cells('A1:M1')
        
        # Add metrics below title in the specified order
        current_row = 2
        
        # 1. Production Target (If available)
        production_target = calc.get('production_target')
        if production_target is not None:
            worksheet[f'A{current_row}'] = f"Production Target: {production_target} units"
            worksheet[f'A{current_row}'].font = Font(bold=True)
            current_row += 1
        
        # 2. Shift Time (If available)
        shift_time = calc.get('shift_time_minutes')
        if shift_time is not None:
            worksheet[f'A{current_row}'] = f"Shift Time: {shift_time:.1f} minutes"
            worksheet[f'A{current_row}'].font = Font(bold=True)
            current_row += 1
        
        # 3. No. of Composite operations
        total_composite_operations = len(calc['workstations'])
        worksheet[f'A{current_row}'] = f"Composite operations: {total_composite_operations}"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 4. Total Basic Time (SAM)
        total_basic_time = calc['total_basic_time']  # Already calculated in minutes
        worksheet[f'A{current_row}'] = f"Total Basic Time (SAM): {total_basic_time:.1f} min"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 5. Line Efficiency% (If available)
        line_efficiency = calc.get('line_efficiency')
        if line_efficiency is not None:
            worksheet[f'A{current_row}'] = f"Line Efficiency%: {line_efficiency:.1f}%"
            worksheet[f'A{current_row}'].font = Font(bold=True)
            current_row += 1
        
        # 6. Total ManPower
        manpower_sum = 0
        for each_ws in calc['workstations']:
            manpower_sum += each_ws.manpower
        total_manpower = manpower_sum
        worksheet[f'A{current_row}'] = f"Total ManPower: {total_manpower}"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 7. Pitch Time / Takt Time
        pitch_time_source_tag = calc.get('pitch_time_source', 'calculated')
        if pitch_time_source_tag == "manual":
            source_display = "(Manual)"
            time_display_name = "Takt Time"
        elif pitch_time_source_tag == "By Target":
            source_display = "(By Target)"
            time_display_name = "Takt Time"
        else:  # "calculated" or any other value
            source_display = "(Auto)"
            time_display_name = "Pitch Time"
        
        worksheet[f'A{current_row}'] = f"{time_display_name}: {calc['pitch_time']:.1f}s {source_display}"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 8. Tolerance
        tolerance_value = calc.get('tolerance', 0.15)
        tolerance_percentage = tolerance_value * 100
        if tolerance_percentage != 15.0:
            tolerance_label = f"Tolerance (Manual): {tolerance_percentage:.1f}%"
        else:
            tolerance_label = f"Tolerance: {tolerance_percentage:.1f}%"
        worksheet[f'A{current_row}'] = tolerance_label
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 9. UCL
        worksheet[f'A{current_row}'] = f"UCL: {calc['ucl']:.1f}s"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 10. LCL
        worksheet[f'A{current_row}'] = f"LCL: {calc['lcl']:.1f}s"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 11. Balancing Rate
        worksheet[f'A{current_row}'] = f"Balancing Rate: {calc['line_balancing_rate']:.1f}%"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 12. Balance Delay
        worksheet[f'A{current_row}'] = f"Balance Delay: {calc['balance_delay']:.1f}%"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # 13. Smoothing Index
        worksheet[f'A{current_row}'] = f"Smoothing Index: {calc['smoothing_index']:.2f} min"
        worksheet[f'A{current_row}'].font = Font(bold=True)
        current_row += 1
        
        # Set start_row for data table (add one row spacing after metrics)
        start_row = current_row + 1
        
        # Write headers
        headers = list(df.columns)
        for col_idx, header in enumerate(headers, 1):
            cell = worksheet.cell(row=start_row, column=col_idx, value=header)
            cell.font = Font(bold=True, size=11)
            cell.fill = PatternFill(start_color="E8EDF4", end_color="E8EDF4", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        # Write data
        for row_idx, row in enumerate(df.itertuples(index=False), start_row + 1):
            for col_idx, value in enumerate(row, 1):
                cell = worksheet.cell(row=row_idx, column=col_idx, value=value)
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                
                # Format numeric values - but keep workstation identifiers as whole numbers
                if isinstance(value, (int, float)):
                    if headers[col_idx - 1] == 'Workstation' or isinstance(value, int):
                        cell.number_format = '0'  # No decimal for workstation identifiers and integers
                    else:
                        cell.number_format = '0.1'  # One decimal for other numeric values
        
        # Auto-adjust column widths for data columns only
        for col_idx in range(1, len(headers) + 1):
            max_length = 0
            for row_idx in range(start_row, start_row + len(df) + 1):
                cell = worksheet.cell(row=row_idx, column=col_idx)
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 30)  # Cap at 30 to prevent overly wide columns
            worksheet.column_dimensions[get_column_letter(col_idx)].width = adjusted_width
        
        # Insert chart image after the data table
        chart_row = start_row + len(df) + 3  # 3 rows gap after data table
        img = Image(chart_img)
        img.width = 800
        img.height = 400
        worksheet.add_image(img, f'A{chart_row}')
        
        # Save to buffer
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"line_balance_{session_id}.xlsx"
        )


@app.route("/api/recalculate", methods=["POST"])
def recalculate():
    """Recalculate with manual overrides including pitch time."""
    data = request.json
    session_id = data.get("session_id")
    manual_pitch_time = data.get("pitch_time")
    production_target = data.get("production_target")
    shift_time_minutes = data.get("shift_time_minutes")
    tolerance = data.get("tolerance")
    
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found"}), 404
    
    # Validate manual pitch time if provided
    if manual_pitch_time is not None:
        try:
            manual_pitch_time = float(manual_pitch_time)
            if manual_pitch_time <= 0:
                return jsonify({"error": "Manual pitch time must be a positive number."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid pitch time value."}), 400
    
    # Validate production target and shift time if provided
    if production_target is not None:
        try:
            production_target = int(production_target)
            if production_target <= 0:
                return jsonify({"error": "Production target must be a positive number."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid production target value."}), 400
    
    if shift_time_minutes is not None:
        try:
            shift_time_minutes = float(shift_time_minutes)
            if shift_time_minutes <= 0:
                return jsonify({"error": "Shift time must be a positive number."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid shift time value."}), 400
    
    # Validate tolerance if provided
    if tolerance is not None:
        try:
            tolerance = float(tolerance)
            if tolerance < 0 or tolerance > 100:
                return jsonify({"error": "Tolerance must be between 0 and 100."}), 400
            tolerance = tolerance / 100  # Convert percentage to decimal
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid tolerance value."}), 400
    
    # Recalculate with new parameters if provided
    try:
        operations = calc["operations"]
        if tolerance is None:
            tolerance = calc.get("tolerance", 0.15)
        
        # Determine pitch time method based on what parameters are provided
        if manual_pitch_time is not None:
            pitch_time_method = "manual"
            # Clear other parameters for manual method
            production_target = None
            shift_time_minutes = None
        elif production_target is not None and shift_time_minutes is not None:
            pitch_time_method = "target"
        else:
            pitch_time_method = "auto"
            # Clear other parameters for auto method
            production_target = None
            shift_time_minutes = None
        
        result = calculate_balance(operations, tolerance, manual_pitch_time, production_target, shift_time_minutes, pitch_time_method)
        
        # Update session with new calculation
        store_calculation(session_id, result)
        
        response_data = {
            "status": "ok", 
            "result": {
                "pitch_time": result["pitch_time"],
                "pitch_time_source": result["pitch_time_source"],
                "ucl": result["ucl"],
                "lcl": result["lcl"],
                "line_balancing_rate": result["line_balancing_rate"],
                "balance_delay": result["balance_delay"],
                "smoothing_index": result["smoothing_index"],
                "total_basic_time": result["total_basic_time"],
                "production_target": result["production_target"],
                "shift_time_minutes": result["shift_time_minutes"],
                "workstations_count": len(result["workstations"]),
                "tolerance": result["tolerance"] * 100,  # Convert to percentage for display
                "before_metrics": result["before_metrics"]
            },
            "before_metrics": result["before_metrics"]
        }
        
        if result["line_efficiency"] is not None:
            response_data["result"]["line_efficiency"] = result["line_efficiency"]
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": f"Recalculation failed: {str(e)}"}), 500


@app.route("/api/chart-data/<session_id>")
def get_chart_data(session_id: str):
    """Get chart data for the home view."""
    print(f"API request for session: {session_id}")
    print(f"Available sessions: {list(SESSIONS.keys())}")
    
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found", "message": "The calculation session has expired. Please reload the data from the home page."}), 404
    
    # Extract workstation data
    workstations = calc["workstations"]
    pitch_time = calc["pitch_time"]
    ucl = calc["ucl"]
    lcl = calc["lcl"]
    
    # Prepare data for chart with operation names for each workstation
    workstation_names = []
    for ws in workstations:
        # Join operation names with " + " for each workstation
        op_names = " + ".join(op.name for op in ws.operations)
        workstation_names.append(op_names)
    
    chart_data = {
        "workstations": workstation_names,
        "balancing_sam": [ws.balancing_sam for ws in workstations],
        "pitch_time": pitch_time,
        "pitch_time_source": calc.get("pitch_time_source", "calculated"),
        "ucl": ucl,
        "lcl": lcl,
        "line_balancing_rate": calc["line_balancing_rate"],
        "balance_delay": calc["balance_delay"],
        "smoothing_index": calc["smoothing_index"],
        "total_basic_time": calc["total_basic_time"],
        "production_target": calc.get("production_target"),
        "shift_time_minutes": calc.get("shift_time_minutes"),
        "tolerance": calc.get("tolerance", 0.15) * 100  # Convert to percentage for display
    }
    
    if calc.get("line_efficiency") is not None:
        chart_data["line_efficiency"] = calc["line_efficiency"]
    
    return jsonify(chart_data)


@app.route("/api/before-chart-data/<session_id>")
def get_before_chart_data(session_id: str):
    """Get before balancing chart data for the home view."""
    print(f"API request for before chart session: {session_id}")
    
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found", "message": "The calculation session has expired. Please reload the data from the home page."}), 404
    
    # Extract before balancing metrics
    before_metrics = calc["before_metrics"]
    operations = calc["sorted_operations"]
    
    # Prepare data for chart with operation names and basic times
    operation_names = [op.name for op in operations]
    basic_times = [op.basic_time for op in operations]
    
    chart_data = {
        "operations": operation_names,
        "basic_times": basic_times,
        "pitch_time": before_metrics["pitch_time"],
        "pitch_time_source": before_metrics.get("pitch_time_source", "calculated"),
        "ucl": before_metrics["ucl"],
        "lcl": before_metrics["lcl"],
        "balancing_rate": before_metrics["balancing_rate"],
        "balance_delay": before_metrics["balance_delay"],
        "smoothing_index": before_metrics["smoothing_index"],
        "total_basic_time": before_metrics["total_basic_time"],
        "tolerance": before_metrics["tolerance"] * 100  # Convert to percentage for display
    }
    
    if before_metrics.get("line_efficiency") is not None:
        chart_data["line_efficiency"] = before_metrics["line_efficiency"]
    
    return jsonify(chart_data)


@app.route("/layout")
@app.route("/layout/<session_id>")
def layout(session_id: str = None):
    """Layout view with line balancing report table and metrics."""
    calc = None
    rows = []
    if session_id:
        calc = get_calculation(session_id)
        if calc:
            # Convert dataframe to list of dicts for template
            df = calc["report_df"]
            rows = df.to_dict("records")
            
            # Format numeric values
            for row in rows:
                row["Combined Basic Time"] = f"{row['Combined Basic Time']:.1f}"
                row["Balancing SAM"] = f"{row['Balancing SAM']:.1f}"
                # Format new columns if they are numeric - handle dynamic column name
                if "Pitch Time" in row and row["Pitch Time"]:
                    row["Pitch Time"] = f"{row['Pitch Time']:.1f}"
                elif "Takt Time" in row and row["Takt Time"]:
                    row["Takt Time"] = f"{row['Takt Time']:.1f}"
                if row["UCL"]:
                    row["UCL"] = f"{row['UCL']:.1f}"
                if row["LCL"]:
                    row["LCL"] = f"{row['LCL']:.1f}"
    
    return render_template_string(LAYOUT_TEMPLATE, session_id=session_id, has_data=calc is not None, result=calc, rows=rows)


# ============== HTML TEMPLATES ==============

LAYOUT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Layout View</title>
    <style>
        :root {
            --bg: #0f1419;
            --surface: #1a2332;
            --surface-2: #243044;
            --border: rgba(255, 255, 255, 0.08);
            --text: #e8edf4;
            --text-muted: #8b9cb3;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
            --radius: 12px;
            --radius-sm: 8px;
            --transition: 0.2s ease;
        }

        [data-theme="light"] {
            --bg: #f1f5f9;
            --surface: #ffffff;
            --surface-2: #f8fafc;
            --border: rgba(15, 23, 42, 0.1);
            --text: #0f172a;
            --text-muted: #64748b;
            --accent: #2563eb;
            --accent-hover: #1d4ed8;
            --success: #16a34a;
            --warning: #d97706;
            --danger: #dc2626;
            --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
        }

        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            transition: background var(--transition), color var(--transition);
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 32px 24px;
        }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            flex-wrap: wrap;
            gap: 20px;
        }

        .header-content {
            flex: 1;
        }

        .header h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 0%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        [data-theme="light"] .header h1 {
            background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .header p {
            color: var(--text-muted);
            font-size: 14px;
        }

        .theme-toggle {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: var(--text-muted);
            transition: all var(--transition);
        }

        .theme-toggle:hover {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
        }

        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }

        .metric-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: all var(--transition);
        }

        .metric-card:hover {
            border-color: rgba(59, 130, 246, 0.3);
            transform: translateY(-2px);
        }

        .metric-card .label {
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .metric-card .value {
            font-size: 24px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .pitch-source-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .pitch-source-badge.manual {
            background: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .pitch-source-badge.auto {
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .pitch-source-badge.target {
            background: rgba(245, 158, 11, 0.2);
            color: #f59e0b;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }

        .tolerance-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .tolerance-badge.manual {
            background: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .metric-card .value {
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: var(--text);
        }

        .metric-card.highlight .value {
            color: var(--accent);
        }

        /* Table Section */
        .table-section {
            position: relative;
        }

        .table-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .table-section h3 {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0;
        }

        .table-wrapper {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            box-shadow: var(--shadow);
        }

        .table-scroll {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }

        th {
            background: var(--surface-2);
            padding: 12px 6px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: var(--text-muted);
            text-align: center;
            border-bottom: 1px solid var(--border);
            white-space: normal;
            line-height: 1.3;
        }

        th:nth-child(1) { width: 7%; }  /* Workstation */
        th:nth-child(2) { width: 7%; }  /* Serial/Id */
        th:nth-child(3) { width: 16%; } /* Operations */
        th:nth-child(4) { width: 9%; }  /* Machine */
        th:nth-child(5) { width: 9%; }  /* Predecessor */
        th:nth-child(6) { width: 9%; }  /* Basic Time */
        th:nth-child(7) { width: 11%; } /* Combined Basic Time */
        th:nth-child(8) { width: 9%; }  /* Balancing SAM */
        th:nth-child(9) { width: 6%; }  /* M/P */
        th:nth-child(10) { width: 8%; } /* Pitch Time */
        th:nth-child(11) { width: 8%; } /* UCL */
        th:nth-child(12) { width: 8%; } /* LCL */
        th:nth-child(13) { width: 10%; } /* Status */

        td {
            padding: 12px 8px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
            font-variant-numeric: tabular-nums;
            text-align: center;
            vertical-align: middle;
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: normal;
        }

        .smart-break-cell {
            white-space: pre-wrap;
            line-height: 1.4;
            word-break: break-word;
        }

        tbody tr:hover {
            background: rgba(59, 130, 246, 0.06);
        }

        .status-badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            min-width: 60px;
            white-space: nowrap;
        }

        .status-ok {
            background: rgba(34, 197, 94, 0.15);
            color: var(--success);
        }

        .status-ucl {
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
        }

        .status-lcl {
            background: rgba(245, 158, 11, 0.15);
            color: var(--warning);
        }

        /* Export Buttons */
        .export-buttons {
            display: flex;
            gap: 8px;
        }

        .export-button, .export-buttons button, .export-buttons a {
            background: var(--surface-2);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
            display: flex;
            align-items: center;
            gap: 6px;
            text-decoration: none;
        }

        .export-button:hover, .export-buttons button:hover, .export-buttons a:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }

        .export-button svg, .export-buttons button svg, .export-buttons a svg {
            width: 14px;
            height: 14px;
        }

        /* Status Section */
        .status {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            text-align: center;
            margin-top: 40px;
        }

        .status p {
            color: var(--text-muted);
            font-size: 16px;
        }

        .status-link {
            color: var(--accent);
            text-decoration: none;
            font-weight: 500;
        }

        .status-link:hover {
            text-decoration: underline;
        }

        @media (max-width: 768px) {
            .container {
                padding: 16px 12px;
                max-width: 100%;
            }

            .header {
                flex-direction: column;
                align-items: flex-start;
                gap: 16px;
            }

            .header h1 {
                font-size: 20px;
            }

            .header p {
                font-size: 12px;
            }

            .metrics-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
            }

            .metric-card {
                padding: 16px;
            }

            .metric-card .value {
                font-size: 20px;
            }

            .table-section h3 {
                font-size: 12px;
            }

            .table-wrapper {
                border-radius: 8px;
            }

            .table-scroll {
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }

            table {
                font-size: 11px;
                min-width: 800px;
            }

            th {
                padding: 10px 4px;
                font-size: 9px;
                line-height: 1.2;
            }

            td {
                padding: 10px 4px;
                font-size: 10px;
            }

            .status-badge {
                padding: 4px 8px;
                font-size: 10px;
                min-width: 50px;
            }

            .export-buttons {
                flex-direction: column;
            }

            .export-buttons button, .export-buttons a {
                padding: 8px 12px;
                font-size: 11px;
            }

            .table-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>Layout View</h1>
                <p>Detailed line balancing report table</p>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <a href="/" class="export-button" style="text-decoration: none; display: flex; align-items: center; gap: 6px;">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" style="width: 14px; height: 14px;">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
                    </svg>
                    Home
                </a>
                <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
            </div>
        </div>

        {% if has_data %}
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin: 0;">After Balancing</h3>
            <div class="export-buttons">
                <button onclick="exportFile('xlsx', '{{ session_id }}')">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Excel
                </button>
            </div>
        </div>
        <div class="metrics-grid">
            {% if result.production_target %}
            <div class="metric-card">
                <div class="label">Customer Demand<br></div>
                <div class="value">{{ result.production_target }}<span style="font-size: 12px; color: var(--text-muted);"> units</span></div>
            </div>
            {% endif %}
            {% if result.shift_time_minutes %}
            <div class="metric-card">
                <div class="label">Available Time<br><br></div>
                <div class="value">{{ "%.1f"|format(result.shift_time_minutes) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
            </div>
            {% endif %}
            <div class="metric-card">
                <div class="label">Composite Operations<br></div>
                <div class="value">{{ result.workstations|length }}</div>
            </div>
            <div class="metric-card">
                <div class="label">SAM<br><br></div>
                <div class="value">{{ "%.1f"|format(result.total_basic_time) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
            </div>
            <div class="metric-card">
                <div class="label">Manpower<br><br></div>
                <div class="value">{{ result.workstations|map(attribute='manpower')|sum }}</div>
            </div>
            <div class="metric-card">
                <div class="label">{% if result.pitch_time_source == "manual" or result.pitch_time_source == "By Target" %}Takt Time<br><br>{% else %}Pitch Time<br><br>{% endif %}</div>
                <div class="value">
                    {{ "%.1f"|format(result.pitch_time) }}<span style="font-size: 12px; color: var(--text-muted);">s</span>
                    {% if result.pitch_time_source == "manual" %}
                    <span class="pitch-source-badge manual">Manual</span>
                    {% elif result.pitch_time_source == "By Target" %}
                    <span class="pitch-source-badge target">By Target</span>
                    {% else %}
                    <span class="pitch-source-badge auto">Auto</span>
                    {% endif %}
                </div>
            </div>
            <div class="metric-card">
                <div class="label">Tolerance<br><br></div>
                <div class="value">
                    {{ "%.1f"|format(result.tolerance * 100) }}<span style="font-size: 12px; color: var(--text-muted);">%</span>
                    {% if result.tolerance * 100 != 15.0 %}
                    <span class="tolerance-badge manual">Manual</span>
                    {% endif %}
                </div>
            </div>
            <div class="metric-card">
                <div class="label">UCL<br><br></div>
                <div class="value">{{ "%.1f"|format(result.ucl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
            </div>
            <div class="metric-card">
                <div class="label">LCL<br><br></div>
                <div class="value">{{ "%.1f"|format(result.lcl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
            </div>
        </div>

        <div class="table-section">
            <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px;">Line Balancing Report</h3>
            <div class="table-wrapper">
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>Composite Operations</th>
                                <th>Serial/Id</th>
                                <th>Operations</th>
                                <th>Machine</th>
                                <th>Predecessor</th>
                                <th>Basic<br>Time</th>
                                <th>Combined Basic<br>Time</th>
                                <th>Balancing<br>SAM</th>
                                <th>M/P</th>
                                <th>{% if result.pitch_time_source == "manual" or result.pitch_time_source == "By Target" %}Takt Time{% else %}Pitch Time{% endif %}</th>
                                <th>UCL</th>
                                <th>LCL</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in rows %}
                            <tr>
                                <td>{{ row['Composite Operations'] }}</td>
                                <td class="smart-break-cell">{{ row['Serial/Id'] }}</td>
                                <td class="smart-break-cell">{{ row['Operations'] }}</td>
                                <td class="smart-break-cell">{{ row['Machine'] }}</td>
                                <td class="smart-break-cell">{{ row['Predecessor'] }}</td>
                                <td class="smart-break-cell">{{ row['Basic Time'] }}</td>
                                <td>{{ row['Combined Basic Time'] }}</td>
                                <td>{{ row['Balancing SAM'] }}</td>
                                <td>{{ row['M/P'] }}</td>
                                <td>{% if result.pitch_time_source == "manual" or result.pitch_time_source == "By Target" %}{{ row['Takt Time'] }}{% else %}{{ row['Pitch Time'] }}{% endif %}</td>
                                <td>{{ row['UCL'] }}</td>
                                <td>{{ row['LCL'] }}</td>
                                <td>
                                    {% if 'OK' in row['Status'] %}
                                        <span class="status-badge status-ok">OK</span>
                                    {% elif 'UCL' in row['Status'] %}
                                        <span class="status-badge status-ucl">> UCL</span>
                                    {% else %}
                                        <span class="status-badge status-lcl">< LCL</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        {% else %}
        <div class="status">
            <p>Layout view - detailed line balancing report table</p>
            <p style="margin-top: 10px; font-size: 14px;">
                <a href="/" class="status-link">Load a calculation from the main view</a> to display the layout
            </p>
        </div>
        {% endif %}
    </div>

    <script>
        // Theme Toggle
        function toggleTheme() {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-theme') || 'dark';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            // Show what you're switching TO (opposite of current/new theme)
            // Update all theme toggle buttons on the page
            document.querySelectorAll('.theme-toggle').forEach(button => {
                button.textContent = newTheme === 'dark' ? '☀️ Light' : '🌙 Dark';
            });
        }

        // Restore theme on load
        window.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            // Show what you're switching TO (opposite of current theme)
            // Update all theme toggle buttons on the page
            document.querySelectorAll('.theme-toggle').forEach(button => {
                button.textContent = savedTheme === 'dark' ? '☀️ Light' : '🌙 Dark';
            });
        });

        // Export function
        function exportFile(format, sessionId) {
            window.location.href = `/api/export/${format}/${sessionId}`;
        }
    </script>
</body>
</html>
"""

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Line Balancing Optimizer</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
    <style>
        :root {
            --bg: #0f1419;
            --surface: #1a2332;
            --surface-2: #243044;
            --border: rgba(255, 255, 255, 0.08);
            --text: #e8edf4;
            --text-muted: #8b9cb3;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
            --radius: 12px;
            --radius-sm: 8px;
            --transition: 0.2s ease;
        }

        [data-theme="light"] {
            --bg: #f1f5f9;
            --surface: #ffffff;
            --surface-2: #f8fafc;
            --border: rgba(15, 23, 42, 0.1);
            --text: #0f172a;
            --text-muted: #64748b;
            --accent: #2563eb;
            --accent-hover: #1d4ed8;
            --success: #16a34a;
            --warning: #d97706;
            --danger: #dc2626;
            --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
        }

        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            transition: background var(--transition), color var(--transition);
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 32px 24px;
        }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
            flex-wrap: wrap;
            gap: 20px;
        }

        .header-content {
            flex: 1;
        }

        .header h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 0%, #94a3b8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        [data-theme="light"] .header h1 {
            background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .header p {
            color: var(--text-muted);
            font-size: 14px;
        }

        .theme-toggle {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            color: var(--text-muted);
            transition: all var(--transition);
        }

        .theme-toggle:hover {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
        }

        /* Metrics Grid */
        .form-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 28px;
            margin-bottom: 32px;
            box-shadow: var(--shadow);
        }

        .form-card h2 {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 20px;
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            align-items: end;
        }

        .field {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .field.hidden {
            display: none;
        }

        label {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
        }

        input[type="file"],
        input[type="number"],
        select {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            color: var(--text);
            padding: 12px 14px;
            font-size: 14px;
            transition: all var(--transition);
        }

        input:focus,
        select:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
        }

        input[type="file"]::file-selector-button {
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            margin-right: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: background var(--transition);
        }

        input[type="file"]::file-selector-button:hover {
            background: var(--accent-hover);
        }

        button[type="submit"] {
            background: linear-gradient(135deg, var(--accent) 0%, #6366f1 100%);
            color: white;
            border: none;
            border-radius: var(--radius-sm);
            padding: 12px 28px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4);
            transition: all var(--transition);
        }

        button[type="submit"]:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(59, 130, 246, 0.5);
        }

        button[type="submit"]:active {
            transform: translateY(0);
        }

        /* Error Message */
        .error-box {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid var(--danger);
            border-radius: var(--radius);
            color: var(--danger);
            padding: 16px 20px;
            margin-bottom: 24px;
            font-size: 14px;
        }

        /* Metrics Grid */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }

        .metric-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            transition: all var(--transition);
        }

        .metric-card:hover {
            border-color: rgba(59, 130, 246, 0.3);
            transform: translateY(-2px);
        }

        .metric-card .label {
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .metric-card .value {
            font-size: 24px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .pitch-source-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .pitch-source-badge.manual {
            background: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .pitch-source-badge.auto {
            background: rgba(34, 197, 94, 0.2);
            color: #22c55e;
            border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .pitch-source-badge.target {
            background: rgba(245, 158, 11, 0.2);
            color: #f59e0b;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }

        .tolerance-badge {
            font-size: 10px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .tolerance-badge.manual {
            background: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .metric-card .value {
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: var(--text);
        }

        .metric-card.highlight .value {
            color: var(--accent);
        }

        /* Table Section */
        .table-section {
            position: relative;
        }

        .table-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }

        .table-section h3 {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0;
        }

        .table-wrapper {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
            box-shadow: var(--shadow);
        }

        .table-scroll {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            table-layout: fixed;
        }

        th {
            background: var(--surface-2);
            padding: 12px 6px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: var(--text-muted);
            text-align: center;
            border-bottom: 1px solid var(--border);
            white-space: normal;
            line-height: 1.3;
        }

        th:nth-child(1) { width: 7%; }  /* Workstation */
        th:nth-child(2) { width: 7%; }  /* Serial/Id */
        th:nth-child(3) { width: 16%; } /* Operations */
        th:nth-child(4) { width: 9%; }  /* Machine */
        th:nth-child(5) { width: 9%; }  /* Predecessor */
        th:nth-child(6) { width: 9%; }  /* Basic Time */
        th:nth-child(7) { width: 11%; } /* Combined Basic Time */
        th:nth-child(8) { width: 9%; }  /* Balancing SAM */
        th:nth-child(9) { width: 6%; }  /* M/P */
        th:nth-child(10) { width: 8%; } /* Pitch Time */
        th:nth-child(11) { width: 8%; } /* UCL */
        th:nth-child(12) { width: 8%; } /* LCL */
        th:nth-child(13) { width: 10%; } /* Status */

        td {
            padding: 12px 8px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
            font-variant-numeric: tabular-nums;
            text-align: center;
            vertical-align: middle;
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: normal;
        }

        /* Handle + values on new line */
        td .multiline {
            white-space: pre-wrap;
            line-height: 1.4;
        }

        .smart-break-cell {
            white-space: pre-wrap;
            line-height: 1.4;
            word-break: break-word;
        }

        tbody tr:hover {
            background: rgba(59, 130, 246, 0.06);
        }

        .status-badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            min-width: 60px;
            white-space: nowrap;
        }

        .status-ok {
            background: rgba(34, 197, 94, 0.15);
            color: var(--success);
        }

        .status-ucl {
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
        }

        .status-lcl {
            background: rgba(245, 158, 11, 0.15);
            color: var(--warning);
        }

        /* Export Buttons */
        .export-buttons {
            display: flex;
            gap: 8px;
        }

        .export-buttons button {
            background: var(--surface-2);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .export-buttons button:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }

        .export-buttons button svg {
            width: 14px;
            height: 14px;
        }

        /* Results Section */
        .results-section {
            animation: fadeIn 0.4s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Chart Section */
        .chart-section {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: var(--shadow);
        }

        .chart-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 16px;
        }

        .chart-title {
            font-size: 24px;
            font-weight: 600;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .chart-title svg {
            width: 28px;
            height: 28px;
        }

        .chart-button {
            background: var(--accent);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: var(--radius-sm);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
            display: flex;
            align-items: center;
            gap: 8px;
            text-decoration: none;
        }

        .chart-button:hover {
            background: var(--accent-hover);
            transform: translateY(-1px);
        }

        .chart-button svg {
            width: 16px;
            height: 16px;
        }

        .chart-buttons {
            display: flex;
            gap: 8px;
        }

        .chart-container {
            position: relative;
            height: 400px;
            width: 100%;
            background: var(--surface);
            border-radius: var(--radius-sm);
            padding: 16px;
        }

        .chart-container canvas {
            background: var(--surface);
            border-radius: var(--radius-sm);
        }

        @media (max-width: 768px) {
            .container {
                padding: 16px 12px;
                max-width: 100%;
            }

            .header {
                flex-direction: column;
                align-items: flex-start;
                gap: 16px;
            }

            .header h1 {
                font-size: 20px;
            }

            .header p {
                font-size: 12px;
            }

            .form-card {
                padding: 20px;
            }

            .form-grid {
                grid-template-columns: 1fr;
                gap: 16px;
            }

            .field {
                width: 100%;
            }

            .file-upload-field {
                grid-column: span 1 !important;
            }

            .metrics-grid {
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
            }

            .metric-card {
                padding: 16px;
            }

            .metric-card .value {
                font-size: 20px;
            }

            .table-section h3 {
                font-size: 12px;
            }

            .table-wrapper {
                border-radius: 8px;
            }

            .table-scroll {
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }

            table {
                font-size: 11px;
                min-width: 800px;
            }

            th {
                padding: 10px 4px;
                font-size: 9px;
                line-height: 1.2;
            }

            td {
                padding: 10px 4px;
                font-size: 10px;
            }

            .status-badge {
                padding: 4px 8px;
                font-size: 10px;
                min-width: 50px;
            }

            .export-buttons {
                flex-direction: column;
            }

            .export-buttons button {
                padding: 8px 12px;
                font-size: 11px;
            }

            .table-header {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }

            button[type="submit"] {
                width: 100%;
            }

            .chart-header {
                flex-direction: column;
                align-items: flex-start;
            }

            .chart-container {
                height: 300px;
            }

            .chart-buttons {
                flex-direction: column;
                width: 100%;
            }

            .chart-button {
                width: 100%;
                justify-content: center;
            }
        }

        @media (max-width: 480px) {
            .container {
                padding: 12px 8px;
            }

            .header h1 {
                font-size: 18px;
            }

            .metrics-grid {
                grid-template-columns: 1fr;
            }

            .form-card {
                padding: 16px;
            }

            th, td {
                padding: 8px 3px;
            }

            th {
                font-size: 8px;
                line-height: 1.1;
            }

            td {
                font-size: 9px;
            }

            .status-badge {
                padding: 3px 6px;
                font-size: 9px;
                min-width: 45px;
            }

            .export-buttons button {
                padding: 6px 10px;
                font-size: 10px;
            }

            .export-buttons button svg {
                width: 12px;
                height: 12px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>Line Balancing Optimizer</h1>
                <p>Upload operation data and configure parameters to optimize workstation balance</p>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
        </div>

        <form method="post" enctype="multipart/form-data" class="form-card">
            <h2>Configuration</h2>
            <div class="form-grid">
                <div class="field file-upload-field">
                    <label>Upload Excel/CSV file</label>
                    <input type="file" name="file" accept=".csv,.xlsx,.xls" required>
                </div>
                <div class="field">
                    <label>Time Method</label>
                    <select name="pitch_time_method" id="pitch_time_method" onchange="togglePitchTimeInput()">
                        <option value="auto">Pitch time</option>
                        <option value="manual">Takt time (Manual)</option>
                        <option value="target">Takt time (By target)</option>
                    </select>
                </div>
                <div class="field" id="pitch_time_field">
                    <label>Time Value</label>
                    <input type="number" name="pitch_time" id="pitch_time_input" value="" placeholder="Time in seconds" min="0" step="0.1">
                </div>
                <div class="field">
                    <label>Tolerance %</label>
                    <input type="number" name="tolerance" value="15" min="0" max="100" step="1">
                </div>
                <div class="field" id="production_target_field">
                    <label>Production Target</label>
                    <input type="number" name="production_target" id="production_target_input" value="" placeholder="Number of units" min="0" step="1">
                </div>
                <div class="field" id="shift_time_field">
                    <label>Shift Time</label>
                    <input type="number" name="shift_time" id="shift_time_input" value="420" placeholder="Shift duration in minutes" min="0" step="1">
                </div>
                <div class="field">
                    <label>&nbsp;</label>
                    <button type="submit">Run calculations</button>
                </div>
            </div>
        </form>

        {% if error %}
        <div class="error-box">
            <strong>Error:</strong> {{ error }}
        </div>
        {% endif %}

        {% if result %}
        <section class="results-section">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin: 0;">Before Balancing</h3>
                <div class="export-buttons">
                    <button class="export-button" onclick="window.location.href='/layout/{{ session_id }}'">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                        View Layout
                    </button>
                    <button class="export-button" onclick="exportFile('xlsx', '{{ session_id }}')">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Export Report
                    </button>
                </div>
            </div>
            <div class="metrics-grid">
                {% if result.production_target %}
                <div class="metric-card">
                    <div class="label">Production<br>Target</div>
                    <div class="value">{{ result.production_target }}<span style="font-size: 12px; color: var(--text-muted);"> units</span></div>
                </div>
                {% endif %}
                {% if result.shift_time_minutes %}
                <div class="metric-card">
                    <div class="label">Shift<br>Time</div>
                    <div class="value">{{ "%.1f"|format(result.shift_time_minutes) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
                {% endif %}
                <div class="metric-card">
                    <div class="label">Total<br>Operations</div>
                    <div class="value">{{ result.before_metrics.num_operations }}</div>
                </div>
                <div class="metric-card">
                    <div class="label">SAM<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.total_basic_time_minutes) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
                {% if result.before_metrics.line_efficiency %}
                <div class="metric-card highlight">
                    <div class="label">Line<br>Efficiency%</div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.line_efficiency) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                {% endif %}
                <div class="metric-card">
                    <div class="label">Total<br>Manpower</div>
                    <div class="value">{{ result.before_metrics.total_manpower }}</div>
                </div>
                <div class="metric-card">
                    <div class="label">{% if result.before_metrics.pitch_time_source == "manual" or result.before_metrics.pitch_time_source == "By Target" %}Takt<br>Time{% else %}Pitch<br>Time{% endif %}</div>
                    <div class="value">
                        {{ "%.1f"|format(result.before_metrics.pitch_time) }}<span style="font-size: 12px; color: var(--text-muted);">s</span>
                        {% if result.before_metrics.pitch_time_source == "manual" %}
                        <span class="pitch-source-badge manual">Manual</span>
                        {% elif result.before_metrics.pitch_time_source == "By Target" %}
                        <span class="pitch-source-badge target">By Target</span>
                        {% else %}
                        <span class="pitch-source-badge auto">Auto</span>
                        {% endif %}
                    </div>
                </div>
                <div class="metric-card">
                    <div class="label">Tolerance<br><br></div>
                    <div class="value">
                        {{ "%.1f"|format(result.before_metrics.tolerance * 100) }}<span style="font-size: 12px; color: var(--text-muted);">%</span>
                        {% if result.before_metrics.tolerance * 100 != 15.0 %}
                        <span class="tolerance-badge manual">Manual</span>
                        {% endif %}
                    </div>
                </div>
                <div class="metric-card">
                    <div class="label">UCL<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.ucl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">LCL<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.lcl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Balancing<br>Rate</div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.balancing_rate) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Balance<br>Delay</div>
                    <div class="value">{{ "%.1f"|format(result.before_metrics.balance_delay) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Smoothing<br>Index</div>
                    <div class="value">{{ "%.2f"|format(result.before_metrics.smoothing_index) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
            </div>

            <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; margin-top: 32px;">After Balancing</h3>
            <div class="metrics-grid">
                {% if result.production_target %}
                <div class="metric-card">
                    <div class="label">Production<br>Target</div>
                    <div class="value">{{ result.production_target }}<span style="font-size: 12px; color: var(--text-muted);"> units</span></div>
                </div>
                {% endif %}
                {% if result.shift_time_minutes %}
                <div class="metric-card">
                    <div class="label">Shift<br>Time</div>
                    <div class="value">{{ "%.1f"|format(result.shift_time_minutes) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
                {% endif %}
                <div class="metric-card">
                    <div class="label">Composite<br>operations</div>
                    <div class="value">{{ result.workstations|length }}</div>
                </div>
                <div class="metric-card">
                    <div class="label">SAM<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.total_basic_time) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
                {% if result.line_efficiency %}
                <div class="metric-card highlight">
                    <div class="label">Line<br>Efficiency%</div>
                    <div class="value">{{ "%.1f"|format(result.line_efficiency) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                {% endif %}
                <div class="metric-card">
                    <div class="label">Total<br>Manpower</div>
                    <div class="value">{{ result.workstations|map(attribute='manpower')|sum }}</div>
                </div>
                <div class="metric-card">
                    <div class="label">{% if result.pitch_time_source == "manual" or result.pitch_time_source == "By Target" %}Takt<br>Time{% else %}Pitch<br>Time{% endif %}</div>
                    <div class="value">
                        {{ "%.1f"|format(result.pitch_time) }}<span style="font-size: 12px; color: var(--text-muted);">s</span>
                        {% if result.pitch_time_source == "manual" %}
                        <span class="pitch-source-badge manual">Manual</span>
                        {% elif result.pitch_time_source == "By Target" %}
                        <span class="pitch-source-badge target">By Target</span>
                        {% else %}
                        <span class="pitch-source-badge auto">Auto</span>
                        {% endif %}
                    </div>
                </div>
                <div class="metric-card">
                    <div class="label">Tolerance<br><br></div>
                    <div class="value">
                        {{ "%.1f"|format(result.tolerance * 100) }}<span style="font-size: 12px; color: var(--text-muted);">%</span>
                        {% if result.tolerance * 100 != 15.0 %}
                        <span class="tolerance-badge manual">Manual</span>
                        {% endif %}
                    </div>
                </div>
                <div class="metric-card">
                    <div class="label">UCL<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.ucl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">LCL<br><br></div>
                    <div class="value">{{ "%.1f"|format(result.lcl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Balancing<br>Rate</div>
                    <div class="value">{{ "%.1f"|format(result.line_balancing_rate) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Balance<br>Delay</div>
                    <div class="value">{{ "%.1f"|format(result.balance_delay) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Smoothing<br>Index</div>
                    <div class="value">{{ "%.2f"|format(result.smoothing_index) }}<span style="font-size: 12px; color: var(--text-muted);"> min</span></div>
                </div>
            </div>

            <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; margin-top: 32px;">Before Balancing Chart</h3>
            
            <div class="chart-section">
                <div class="chart-header">
                    <div class="chart-title">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        Before Balancing
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="beforeBalanceChart"></canvas>
                </div>
            </div>

            <h3 style="font-size: 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; margin-top: 32px;">After Balancing Chart</h3>
            
            <div class="chart-section">
                <div class="chart-header">
                    <div class="chart-title">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        After Balancing
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="balanceChart"></canvas>
                </div>
            </div>
        </section>
        {% endif %}
    </div>

    <script>
        // Theme Toggle
        function toggleTheme() {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-theme') || 'dark';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            // Show what you're switching TO (opposite of current/new theme)
            // Update all theme toggle buttons on the page
            document.querySelectorAll('.theme-toggle').forEach(button => {
                button.textContent = newTheme === 'dark' ? '☀️ Light' : '🌙 Dark';
            });
        }

        // Toggle pitch time input field based on method selection
        function togglePitchTimeInput() {
            const method = document.getElementById('pitch_time_method').value;
            const pitchTimeField = document.getElementById('pitch_time_field');
            const pitchTimeInput = document.getElementById('pitch_time_input');
            const productionTargetField = document.getElementById('production_target_field');
            const shiftTimeField = document.getElementById('shift_time_field');
            const shiftTimeInput = document.getElementById('shift_time_input');
            
            if (method === 'manual') {
                pitchTimeField.style.display = 'flex';
                pitchTimeInput.required = true;
                productionTargetField.style.display = 'none';
                shiftTimeField.style.display = 'none';
                shiftTimeInput.value = '';
            } else if (method === 'target') {
                pitchTimeField.style.display = 'none';
                pitchTimeInput.required = false;
                pitchTimeInput.value = '';
                productionTargetField.style.display = 'flex';
                shiftTimeField.style.display = 'flex';
                // Set default shift time only if field is empty
                if (!shiftTimeInput.value) {
                    shiftTimeInput.value = '420';
                }
            } else { // auto
                pitchTimeField.style.display = 'none';
                pitchTimeInput.required = false;
                pitchTimeInput.value = '';
                productionTargetField.style.display = 'none';
                shiftTimeField.style.display = 'none';
                shiftTimeInput.value = '';
            }
        }

        // Restore theme on load
        window.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            // Show what you're switching TO (opposite of current theme)
            // Update all theme toggle buttons on the page
            document.querySelectorAll('.theme-toggle').forEach(button => {
                button.textContent = savedTheme === 'dark' ? '☀️ Light' : '🌙 Dark';
            });

            // Initialize pitch time field visibility
            togglePitchTimeInput();

            // Load charts if session_id is available
            {% if session_id %}
            loadBeforeChart('{{ session_id }}');
            loadChart('{{ session_id }}');
            {% endif %}
        });

        // Export function
        function exportFile(format, sessionId) {
            window.location.href = `/api/export/${format}/${sessionId}`;
        }

        async function loadBeforeChart(sessionId) {
            try {
                const response = await fetch(`/api/before-chart-data/${sessionId}`);
                if (!response.ok) {
                    const errorData = await response.json();
                    if (response.status === 404) {
                        // Session expired, redirect to home with message
                        alert(errorData.message || 'Session expired. Please reload the data.');
                        window.location.href = '/';
                        return;
                    }
                    throw new Error(errorData.error || 'Failed to load before chart data');
                }
                
                const data = await response.json();
                
                // Create before chart
                createBeforeChart(data);
            } catch (error) {
                console.error('Error loading before chart:', error);
                alert('Error loading before chart data: ' + error.message);
                window.location.href = '/';
            }
        }

        async function loadChart(sessionId) {
            try {
                const response = await fetch(`/api/chart-data/${sessionId}`);
                if (!response.ok) {
                    const errorData = await response.json();
                    if (response.status === 404) {
                        // Session expired, redirect to home with message
                        alert(errorData.message || 'Session expired. Please reload the data.');
                        window.location.href = '/';
                        return;
                    }
                    throw new Error(errorData.error || 'Failed to load chart data');
                }
                
                const data = await response.json();
                
                // Create chart
                createChart(data);
            } catch (error) {
                console.error('Error loading chart:', error);
                alert('Error loading chart data: ' + error.message);
                window.location.href = '/';
            }
        }

        function createBeforeChart(chartData) {
            const ctx = document.getElementById('beforeBalanceChart').getContext('2d');
            
            // Get theme colors - grey text for light mode, white for dark mode
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const textColor = isDark ? '#ffffff' : '#64748b'; // White in dark, grey in light
            const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
            
            // Determine pitch time label based on source
            const pitchTimeLabel = (chartData.pitch_time_source === "manual" || chartData.pitch_time_source === "By Target") ? 'Takt Time' : 'Pitch Time';
            
            window.beforeBalanceChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: chartData.operations,
                    datasets: [{
                        label: 'Basic Time (SAM)',
                        data: chartData.basic_times,
                        backgroundColor: 'rgba(59, 130, 246, 0.8)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                color: textColor,
                                font: {
                                    size: 13,
                                    weight: 500
                                }
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1a2332', // Always dark background for tooltip
                            titleColor: '#ffffff', // Always white in tooltip
                            bodyColor: '#ffffff', // Always white in tooltip
                            borderColor: gridColor,
                            borderWidth: 1,
                            padding: 12,
                            displayColors: true,
                            titleFont: {
                                size: 11,
                                weight: 'bold'
                            },
                            bodyFont: {
                                size: 12
                            },
                            callbacks: {
                                title: function(context) {
                                    // Show full operation name in tooltip
                                    return context[0].label;
                                },
                                label: function(context) {
                                    return `Basic Time (SAM): ${context.raw.toFixed(1)}s`;
                                }
                            }
                        },
                        annotation: {
                            annotations: {
                                uclLine: {
                                    type: 'line',
                                    yMin: chartData.ucl,
                                    yMax: chartData.ucl,
                                    borderColor: 'rgb(239, 68, 68)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: 'UCL',
                                        position: 'end',
                                        backgroundColor: 'rgb(239, 68, 68)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                },
                                pitchLine: {
                                    type: 'line',
                                    yMin: chartData.pitch_time,
                                    yMax: chartData.pitch_time,
                                    borderColor: 'rgb(34, 197, 94)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: pitchTimeLabel,
                                        position: 'end',
                                        backgroundColor: 'rgb(34, 197, 94)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                },
                                lclLine: {
                                    type: 'line',
                                    yMin: chartData.lcl,
                                    yMax: chartData.lcl,
                                    borderColor: 'rgb(249, 115, 22)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: 'LCL',
                                        position: 'end',
                                        backgroundColor: 'rgb(249, 115, 22)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: gridColor
                            },
                            ticks: {
                                color: textColor,
                                font: {
                                    size: 9
                                },
                                // Show all labels without skipping
                                autoSkip: false,
                                maxRotation: 45,
                                minRotation: 45,
                                callback: function(value, index, values) {
                                    const label = this.getLabelForValue(value);
                                    // Truncate very long labels for display
                                    if (label.length > 25) {
                                        return label.substring(0, 25) + '...';
                                    }
                                    return label;
                                }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            grid: {
                                color: gridColor
                            },
                            ticks: {
                                color: textColor,
                                font: {
                                    size: 12
                                },
                                callback: function(value) {
                                    return value.toFixed(1) + 's';
                                }
                            },
                            title: {
                                display: true,
                                text: 'Time (seconds)',
                                color: textColor,
                                font: {
                                    size: 13,
                                    weight: 500
                                }
                            }
                        }
                    }
                }
            });
        }

        function createChart(chartData) {
            const ctx = document.getElementById('balanceChart').getContext('2d');
            
            // Get theme colors - grey text for light mode, white for dark mode
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const textColor = isDark ? '#ffffff' : '#64748b'; // White in dark, grey in light
            const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
            
            // Determine pitch time label based on source
            const pitchTimeLabel = (chartData.pitch_time_source === "manual" || chartData.pitch_time_source === "By Target") ? 'Takt Time' : 'Pitch Time';
            
            window.balanceChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: chartData.workstations,
                    datasets: [{
                        label: 'Balancing SAM',
                        data: chartData.balancing_sam,
                        backgroundColor: 'rgba(59, 130, 246, 0.8)',
                        borderColor: 'rgba(59, 130, 246, 1)',
                        borderWidth: 1,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                color: textColor,
                                font: {
                                    size: 13,
                                    weight: 500
                                }
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1a2332', // Always dark background for tooltip
                            titleColor: '#ffffff', // Always white in tooltip
                            bodyColor: '#ffffff', // Always white in tooltip
                            borderColor: gridColor,
                            borderWidth: 1,
                            padding: 12,
                            displayColors: true,
                            titleFont: {
                                size: 11,
                                weight: 'bold'
                            },
                            bodyFont: {
                                size: 12
                            },
                            callbacks: {
                                title: function(context) {
                                    // Show full operation name in tooltip
                                    return context[0].label;
                                },
                                label: function(context) {
                                    return `Balancing SAM: ${context.raw.toFixed(1)}s`;
                                }
                            }
                        },
                        annotation: {
                            annotations: {
                                uclLine: {
                                    type: 'line',
                                    yMin: chartData.ucl,
                                    yMax: chartData.ucl,
                                    borderColor: 'rgb(239, 68, 68)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: 'UCL',
                                        position: 'end',
                                        backgroundColor: 'rgb(239, 68, 68)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                },
                                pitchLine: {
                                    type: 'line',
                                    yMin: chartData.pitch_time,
                                    yMax: chartData.pitch_time,
                                    borderColor: 'rgb(34, 197, 94)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: pitchTimeLabel,
                                        position: 'end',
                                        backgroundColor: 'rgb(34, 197, 94)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                },
                                lclLine: {
                                    type: 'line',
                                    yMin: chartData.lcl,
                                    yMax: chartData.lcl,
                                    borderColor: 'rgb(249, 115, 22)',
                                    borderWidth: 2,
                                    borderDash: [5, 5],
                                    label: {
                                        display: true,
                                        content: 'LCL',
                                        position: 'end',
                                        backgroundColor: 'rgb(249, 115, 22)',
                                        color: 'white',
                                        font: {
                                            size: 11,
                                            weight: 'bold'
                                        },
                                        padding: 6
                                    }
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                color: gridColor
                            },
                            ticks: {
                                color: textColor,
                                font: {
                                    size: 9
                                },
                                // Show all labels without skipping
                                autoSkip: false,
                                maxRotation: 45,
                                minRotation: 45,
                                callback: function(value, index, values) {
                                    const label = this.getLabelForValue(value);
                                    // Truncate very long labels for display
                                    if (label.length > 25) {
                                        return label.substring(0, 25) + '...';
                                    }
                                    return label;
                                }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            grid: {
                                color: gridColor
                            },
                            ticks: {
                                color: textColor,
                                font: {
                                    size: 12
                                },
                                callback: function(value) {
                                    return value.toFixed(1) + 's';
                                }
                            },
                            title: {
                                display: true,
                                text: 'Time (seconds)',
                                color: textColor,
                                font: {
                                    size: 13,
                                    weight: 500
                                }
                            }
                        }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
