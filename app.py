"""
Line Balancing Tool - Modern Web Application

A professional Flask web app for:
- IE departments (planning view): full features on desktop
- Floor supervisors (monitoring view): responsive on tablets
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
from flask import Flask, jsonify, render_template_string, request, send_file

from src.line_balancer.models import Operation, Workstation
from src.line_balancer.io_utils import read_operations
from src.line_balancer.sequencing import sort_by_id
from src.line_balancer.metrics import calculate_pitch_time, calculate_tolerance_bands, calculate_line_balancing_rate
from src.line_balancer.balancing import group_and_balance
from src.line_balancer.report import build_report_dataframe, determine_status

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


def calculate_balance(operations: List[Operation], tolerance: float = 0.15, manual_pitch_time: Optional[float] = None) -> Dict:
    """
    Run the complete balancing calculation and return all results.
    
    Args:
        operations: List of Operation objects from CSV/Excel
        tolerance: UCL/LCL tolerance (default 15%)
        manual_pitch_time: Optional manual pitch time override
    
    Returns:
        Dictionary with all calculation results
    """
    # Step 1: Sort operations by ID
    sorted_ops = sort_by_id(operations)
    
    # Step 2: Calculate or use manual Pitch Time and control limits
    if manual_pitch_time is not None:
        if manual_pitch_time <= 0:
            raise ValueError("Manual pitch time must be a positive number.")
        pitch_time = manual_pitch_time
        pitch_time_source = "manual"
    else:
        pitch_time = calculate_pitch_time(sorted_ops)
        pitch_time_source = "calculated"
    
    ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)
    
    # Step 3: Balance operations into workstations
    workstations = group_and_balance(sorted_ops, ucl, lcl)
    
    # Step 4: Calculate line balancing rate
    line_balancing_rate = calculate_line_balancing_rate(workstations)
    
    # Step 5: Build report
    report_df = build_report_dataframe(workstations, ucl, lcl, pitch_time)
    
    return {
        "operations": operations,
        "sorted_operations": sorted_ops,
        "pitch_time": pitch_time,
        "pitch_time_source": pitch_time_source,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "line_balancing_rate": line_balancing_rate,
        "report_df": report_df,
        "tolerance": tolerance,
    }


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
            pitch_time_str = request.form.get("pitch_time", "")
            tolerance_str = request.form.get("tolerance", "0.15")
            
            if not file or file.filename == "":
                error = "Please select a file to upload."
            else:
                # Parse parameters
                manual_pitch_time = float(pitch_time_str) if pitch_time_str else None
                tolerance = float(tolerance_str)
                
                # Validate manual pitch time if provided
                if manual_pitch_time is not None and manual_pitch_time <= 0:
                    error = "Manual pitch time must be a positive number."
                else:
                    # Read operations from file
                    filepath = Path(file.filename)
                    if filepath.suffix.lower() not in (".csv", ".xlsx", ".xls"):
                        error = "File must be CSV or Excel (.xlsx, .xls)."
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
                                result = calculate_balance(operations, tolerance, manual_pitch_time)
                                
                                # Convert dataframe to list of dicts for template
                                df = result["report_df"]
                                rows = df.to_dict("records")
                                
                                # Format numeric values
                                for row in rows:
                                    row["Combined Basic Time"] = f"{row['Combined Basic Time']:.1f}"
                                    row["Balancing SAM"] = f"{row['Balancing SAM']:.1f}"
                                    # Format new columns if they are numeric
                                    if row["Pitch Time"]:
                                        row["Pitch Time"] = f"{row['Pitch Time']:.1f}"
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
    """Export results to CSV or Excel."""
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found"}), 404
    
    df = calc["report_df"]
    
    if format == "csv":
        buffer = io.StringIO()
        df.to_csv(buffer, index=False)
        buffer.seek(0)
        return send_file(
            io.BytesIO(buffer.getvalue().encode()),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"line_balance_{session_id}.csv"
        )
    elif format == "xlsx":
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"line_balance_{session_id}.xlsx"
        )
    
    return jsonify({"error": "Invalid format"}), 400


@app.route("/api/recalculate", methods=["POST"])
def recalculate():
    """Recalculate with manual overrides including pitch time."""
    data = request.json
    session_id = data.get("session_id")
    manual_pitch_time = data.get("pitch_time")
    
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
    
    # Recalculate with new pitch time if provided
    try:
        operations = calc["operations"]
        tolerance = calc.get("tolerance", 0.15)
        
        result = calculate_balance(operations, tolerance, manual_pitch_time)
        
        # Update session with new calculation
        store_calculation(session_id, result)
        
        return jsonify({
            "status": "ok", 
            "result": {
                "pitch_time": result["pitch_time"],
                "pitch_time_source": result["pitch_time_source"],
                "ucl": result["ucl"],
                "lcl": result["lcl"],
                "line_balancing_rate": result["line_balancing_rate"],
                "workstations_count": len(result["workstations"])
            }
        })
    except Exception as e:
        return jsonify({"error": f"Recalculation failed: {str(e)}"}), 500


@app.route("/api/chart-data/<session_id>")
def get_chart_data(session_id: str):
    """Get chart data for the monitoring view."""
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
        "line_balancing_rate": calc["line_balancing_rate"]
    }
    
    return jsonify(chart_data)


@app.route("/monitor")
@app.route("/monitor/<session_id>")
def monitor(session_id: str = None):
    """Floor monitoring view (simplified, responsive)."""
    calc = None
    if session_id:
        calc = get_calculation(session_id)
    
    return render_template_string(MONITOR_TEMPLATE, session_id=session_id, has_data=calc is not None)


# ============== HTML TEMPLATES ==============

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Line Balancing Optimizer</title>
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

        /* Navbar */
        .navbar {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 12px 20px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: var(--shadow);
        }

        .nav-links {
            display: flex;
            gap: 8px;
        }

        .nav-link {
            background: var(--surface-2);
            color: var(--text-muted);
            text-decoration: none;
            padding: 8px 16px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-weight: 500;
            transition: all var(--transition);
            border: 1px solid transparent;
        }

        .nav-link:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }

        .nav-link.active {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
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

        /* Form Card */
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

        label {
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
        }

        input[type="file"],
        input[type="number"] {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            color: var(--text);
            padding: 12px 14px;
            font-size: 14px;
            transition: all var(--transition);
        }

        input:focus {
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

        .export-buttons .monitor-btn {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
            text-decoration: none;
        }

        .export-buttons .monitor-btn:hover {
            background: var(--accent-hover);
            border-color: var(--accent-hover);
        }

        .export-buttons .monitor-btn svg {
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

            .navbar {
                flex-direction: column;
                gap: 12px;
            }

            .nav-links {
                width: 100%;
                justify-content: center;
            }

            button[type="submit"] {
                width: 100%;
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

            .navbar {
                padding: 10px 12px;
            }

            .nav-link {
                padding: 6px 12px;
                font-size: 11px;
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
        <nav class="navbar">
            <div class="nav-links">
                <a href="/" class="nav-link active">Home</a>
                <a href="/monitor{% if session_id %}/{{ session_id }}{% endif %}" class="nav-link">Monitor</a>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
        </nav>

        <div class="header">
            <div>
                <h1>Line Balancing Optimizer</h1>
                <p>Upload operation data and configure parameters to optimize workstation balance</p>
            </div>
        </div>

        <form method="post" enctype="multipart/form-data" class="form-card">
            <h2>Configuration</h2>
            <div class="form-grid">
                <div class="field file-upload-field">
                    <label>Upload CSV/XLSX file</label>
                    <input type="file" name="file" accept=".csv,.xlsx,.xls" required>
                </div>
                <div class="field">
                    <label>Pitch Time (optional)</label>
                    <input type="number" name="pitch_time" value="" placeholder="Auto-calculate if empty" min="0" step="0.1">
                </div>
                <div class="field">
                    <label>Tolerance</label>
                    <input type="number" name="tolerance" value="0.15" min="0" max="1" step="0.01">
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
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="label">Pitch Time</div>
                    <div class="value">
                        {{ "%.1f"|format(result.pitch_time) }}<span style="font-size: 12px; color: var(--text-muted);">s</span>
                        {% if result.pitch_time_source == "manual" %}
                        <span class="pitch-source-badge manual">Manual</span>
                        {% else %}
                        <span class="pitch-source-badge auto">Auto</span>
                        {% endif %}
                    </div>
                </div>
                <div class="metric-card">
                    <div class="label">UCL</div>
                    <div class="value">{{ "%.1f"|format(result.ucl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">LCL</div>
                    <div class="value">{{ "%.1f"|format(result.lcl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">BALANCING RATE</div>
                    <div class="value">{{ "%.1f"|format(result.line_balancing_rate) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">Workstations</div>
                    <div class="value">{{ result.workstations|length }}</div>
                </div>
                <div class="metric-card">
                    <div class="label">Total Manpower</div>
                    <div class="value">{{ result.workstations|map(attribute='manpower')|sum }}</div>
                </div>
            </div>

            <div class="table-section">
                <div class="table-header">
                    <h3>Workstation Report</h3>
                    <div class="export-buttons">
                        <a href="/monitor/{{ session_id }}" class="nav-link monitor-btn">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                            </svg>
                            Monitor
                        </a>
                        <button onclick="exportFile('csv', '{{ session_id }}')">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                            CSV
                        </button>
                        <button onclick="exportFile('xlsx', '{{ session_id }}')">
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                            Excel
                        </button>
                    </div>
                </div>
                <div class="table-wrapper">
                    <div class="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    <th>Workstation</th>
                                    <th>Serial/Id</th>
                                    <th>Operations</th>
                                    <th>Machine</th>
                                    <th>Predecessor</th>
                                    <th>Basic<br>Time</th>
                                    <th>Combined Basic<br>Time</th>
                                    <th>Balancing<br>SAM</th>
                                    <th>M/P</th>
                                    <th>Pitch Time</th>
                                    <th>UCL</th>
                                    <th>LCL</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for row in rows %}
                                <tr>
                                    <td>{{ row['Workstation'] }}</td>
                                    <td class="smart-break-cell">{{ row['Serial/Id'] }}</td>
                                    <td class="smart-break-cell">{{ row['Operations'] }}</td>
                                    <td class="smart-break-cell">{{ row['Machine'] }}</td>
                                    <td class="smart-break-cell">{{ row['Predecessor'] }}</td>
                                    <td class="smart-break-cell">{{ row['Basic Time'] }}</td>
                                    <td>{{ row['Combined Basic Time'] }}</td>
                                    <td>{{ row['Balancing SAM'] }}</td>
                                    <td>{{ row['M/P'] }}</td>
                                    <td>{{ row['Pitch Time'] }}</td>
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
            document.querySelector('.theme-toggle').textContent = newTheme === 'dark' ? '🌙 Dark' : '☀️ Light';
        }

        // Restore theme on load
        window.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            document.querySelector('.theme-toggle').textContent = savedTheme === 'dark' ? '🌙 Dark' : '☀️ Light';

            // Set active nav link based on current path
            const currentPath = window.location.pathname;
            const navLinks = document.querySelectorAll('.nav-link');
            navLinks.forEach(link => {
                link.classList.remove('active');
                if (link.getAttribute('href') === currentPath) {
                    link.classList.add('active');
                }
            });

            // Handle smart + breaking for specific columns (Serial/Id, Operations, Machine, Predecessor, Basic Time)
            const smartBreakCells = document.querySelectorAll('.smart-break-cell');
            smartBreakCells.forEach(cell => {
                const text = cell.textContent;
                if (text.includes('+')) {
                    // Smart breaking: (a + b) + c breaks as (a + b) on line 1, + on line 2, c on line 3
                    let result = '';
                    let parenDepth = 0;
                    let i = 0;
                    let lastNonSpaceIndex = -1;
                    
                    while (i < text.length) {
                        const char = text[i];
                        
                        if (char === '(') {
                            parenDepth++;
                            result += char;
                        } else if (char === ')') {
                            parenDepth--;
                            result += char;
                        } else if (char === '+' && parenDepth === 0) {
                        // Only break if + is outside parentheses
                        // Break before + if there's non-space content before it
                        if (lastNonSpaceIndex >= 0) {
                            // Remove trailing spaces from Line 1
                            result = result.trimEnd();
                            result += '<br>';
                        }
                        // Put + on its own line
                        result += '+<br>';
                        lastNonSpaceIndex = -1;
                        
                        // Skip any whitespace after the + (for Line 3)
                        while (i + 1 < text.length && text[i + 1].trim() === '') {
                            i++;
                        }
                    } else {
                            result += char;
                            if (char.trim() !== '') {
                                lastNonSpaceIndex = i;
                            }
                        }
                        i++;
                    }
                    
                    cell.innerHTML = result;
                }
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

MONITOR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Line Monitor</title>
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

        /* Navbar */
        .navbar {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 12px 20px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: var(--shadow);
        }

        .nav-links {
            display: flex;
            gap: 8px;
        }

        .nav-link {
            background: var(--surface-2);
            color: var(--text-muted);
            text-decoration: none;
            padding: 8px 16px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-weight: 500;
            transition: all var(--transition);
            border: 1px solid transparent;
        }

        .nav-link:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }

        .nav-link.active {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
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
        }

        .chart-button:hover {
            background: var(--accent-hover);
            transform: translateY(-1px);
        }

        .chart-button svg {
            width: 16px;
            height: 16px;
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

        /* Metrics Section */
        .metrics-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }

        .chart-buttons {
            display: flex;
            gap: 8px;
        }

        .metric-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            text-align: center;
            box-shadow: var(--shadow);
        }

        .metric-label {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .metric-value {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .metric-sub {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
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
            .navbar {
                flex-direction: column;
                gap: 12px;
            }

            .nav-links {
                width: 100%;
                justify-content: center;
            }

            .chart-header {
                flex-direction: column;
                align-items: flex-start;
            }

            .chart-container {
                height: 300px;
            }

            .metrics-section {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <nav class="navbar">
            <div class="nav-links">
                <a href="/" class="nav-link">Home</a>
                <a href="/monitor{% if session_id %}/{{ session_id }}{% endif %}" class="nav-link active">Monitor</a>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
        </nav>

        {% if has_data %}
        <div class="metrics-section">
            <div class="metric-card">
                <div class="metric-label">Line Balancing Rate</div>
                <div class="metric-value" id="lbrValue">--%</div>
                <div class="metric-sub">Efficiency metric</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Pitch Time</div>
                <div class="metric-value">
                    <span id="pitchValue">--s</span>
                    <span id="pitchSourceBadge" class="pitch-source-badge auto">Auto</span>
                </div>
                <div class="metric-sub">Target time per workstation</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">UCL</div>
                <div class="metric-value" id="uclValue" style="color: var(--danger)">--s</div>
                <div class="metric-sub">Upper Control Limit</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">LCL</div>
                <div class="metric-value" id="lclValue" style="color: var(--warning)">--s</div>
                <div class="metric-sub">Lower Control Limit</div>
            </div>
        </div>

        <div class="chart-section">
            <div class="chart-header">
                <div class="chart-title">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                    </svg>
                    Line Balancing Chart
                </div>
                <div class="chart-buttons">
                    <button class="chart-button" onclick="saveChart()">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        Save Chart
                    </button>
                    <button class="chart-button" onclick="goBack()">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                        </svg>
                        Back to Home
                    </button>
                </div>
            </div>
            <div class="chart-container">
                <canvas id="balanceChart"></canvas>
            </div>
        </div>
        {% else %}
        <div class="status">
            <p>Floor monitoring view - real-time line balancing visualization</p>
            <p style="margin-top: 10px; font-size: 14px;">
                <a href="/" class="status-link">Load a calculation from the main view</a> to display the chart
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
            document.querySelector('.theme-toggle').textContent = newTheme === 'dark' ? '🌙 Dark' : '☀️ Light';
            
            // Update chart colors if chart exists
            if (window.balanceChartInstance) {
                const isDark = newTheme === 'dark';
                const textColor = isDark ? '#ffffff' : '#64748b'; // White in dark, grey in light
                const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
                
                window.balanceChartInstance.options.plugins.legend.labels.color = textColor;
                window.balanceChartInstance.options.plugins.tooltip.backgroundColor = '#1a2332'; // Always dark background
                window.balanceChartInstance.options.plugins.tooltip.titleColor = '#ffffff'; // Always white in tooltip
                window.balanceChartInstance.options.plugins.tooltip.bodyColor = '#ffffff'; // Always white in tooltip
                window.balanceChartInstance.options.plugins.tooltip.borderColor = gridColor;
                window.balanceChartInstance.options.scales.x.ticks.color = textColor;
                window.balanceChartInstance.options.scales.x.grid.color = gridColor;
                window.balanceChartInstance.options.scales.y.ticks.color = textColor;
                window.balanceChartInstance.options.scales.y.grid.color = gridColor;
                window.balanceChartInstance.options.scales.y.title.color = textColor;
                
                window.balanceChartInstance.update();
            }
        }

        // Restore theme on load
        window.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme') || 'dark';
            document.documentElement.setAttribute('data-theme', savedTheme);
            document.querySelector('.theme-toggle').textContent = savedTheme === 'dark' ? '🌙 Dark' : '☀️ Light';

            // Set active nav link based on current path
            const currentPath = window.location.pathname;
            const navLinks = document.querySelectorAll('.nav-link');
            navLinks.forEach(link => {
                link.classList.remove('active');
                if (link.getAttribute('href') === currentPath) {
                    link.classList.add('active');
                }
            });

            // Load chart if session_id is available
            {% if session_id %}
            loadChart('{{ session_id }}');
            {% endif %}
        });

        function goBack() {
            window.location.href = '/';
        }

        function saveChart() {
            if (!window.balanceChartInstance) {
                alert('Chart not loaded yet');
                return;
            }
            
            // Save current colors
            const originalColors = {
                textColor: window.balanceChartInstance.options.scales.x.ticks.color,
                legendColor: window.balanceChartInstance.options.plugins.legend.labels.color,
                yTitleColor: window.balanceChartInstance.options.scales.y.title.color,
                yTicksColor: window.balanceChartInstance.options.scales.y.ticks.color,
                gridColor: window.balanceChartInstance.options.scales.x.grid.color
            };
            
            // Set light mode colors with grey text for export
            window.balanceChartInstance.options.scales.x.ticks.color = '#64748b';
            window.balanceChartInstance.options.plugins.legend.labels.color = '#64748b';
            window.balanceChartInstance.options.scales.y.title.color = '#64748b';
            window.balanceChartInstance.options.scales.y.ticks.color = '#64748b';
            window.balanceChartInstance.options.scales.x.grid.color = 'rgba(0, 0, 0, 0.1)';
            window.balanceChartInstance.options.scales.y.grid.color = 'rgba(0, 0, 0, 0.1)';
            
            // Save current background color
            const canvas = document.getElementById('balanceChart');
            const originalBg = canvas.style.background;
            
            // Set white background for export
            canvas.style.background = '#ffffff';
            
            // Force update
            window.balanceChartInstance.update();
            
            // Small delay to ensure rendering is complete
            setTimeout(() => {
                const link = document.createElement('a');
                link.download = 'line-balancing-chart.png';
                link.href = canvas.toDataURL('image/png');
                link.click();
                
                // Restore original colors
                window.balanceChartInstance.options.scales.x.ticks.color = originalColors.textColor;
                window.balanceChartInstance.options.plugins.legend.labels.color = originalColors.legendColor;
                window.balanceChartInstance.options.scales.y.title.color = originalColors.yTitleColor;
                window.balanceChartInstance.options.scales.y.ticks.color = originalColors.yTicksColor;
                window.balanceChartInstance.options.scales.x.grid.color = originalColors.gridColor;
                window.balanceChartInstance.options.scales.y.grid.color = originalColors.gridColor;
                
                // Restore original background
                canvas.style.background = originalBg;
                
                // Force update to restore
                window.balanceChartInstance.update();
            }, 100);
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
                
                // Update metrics
                document.getElementById('lbrValue').textContent = data.line_balancing_rate.toFixed(1) + '%';
                document.getElementById('pitchValue').textContent = data.pitch_time.toFixed(1) + 's';
                
                // Update pitch time source indicator
                const pitchSourceBadge = document.getElementById('pitchSourceBadge');
                if (pitchSourceBadge) {
                    pitchSourceBadge.textContent = data.pitch_time_source === 'manual' ? 'Manual' : 'Auto';
                    pitchSourceBadge.className = 'pitch-source-badge ' + (data.pitch_time_source === 'manual' ? 'manual' : 'auto');
                }
                
                document.getElementById('uclValue').textContent = data.ucl.toFixed(1) + 's';
                document.getElementById('lclValue').textContent = data.lcl.toFixed(1) + 's';
                
                // Create chart
                createChart(data);
            } catch (error) {
                console.error('Error loading chart:', error);
                alert('Error loading chart data: ' + error.message);
                window.location.href = '/';
            }
        }

        function createChart(chartData) {
            const ctx = document.getElementById('balanceChart').getContext('2d');
            
            // Get theme colors - grey text for light mode, white for dark mode
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const textColor = isDark ? '#ffffff' : '#64748b'; // White in dark, grey in light
            const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
            
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
                                        content: 'Pitch Time',
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
