"""
Line Balancing & Efficiency Tool - Modern Web Application

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
from src.line_balancer.metrics import calculate_pitch_time, calculate_tolerance_bands, calculate_line_efficiency
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


def get_calculation(session_id: str) -> Optional[Dict]:
    """Retrieve calculation results from session."""
    return SESSIONS.get(session_id)


def calculate_balance(operations: List[Operation], total_ops: Optional[int] = None, tolerance: float = 0.15) -> Dict:
    """
    Run the complete balancing calculation and return all results.
    
    Args:
        operations: List of Operation objects from CSV/Excel
        total_ops: Total operation count (for Pitch Time calculation)
        tolerance: UCL/LCL tolerance (default 15%)
    
    Returns:
        Dictionary with all calculation results
    """
    # Step 1: Sort operations by ID
    sorted_ops = sort_by_id(operations)
    
    # Step 2: Calculate Pitch Time and control limits
    pitch_time = calculate_pitch_time(sorted_ops, total_ops)
    ucl, lcl = calculate_tolerance_bands(pitch_time, tolerance)
    
    # Step 3: Balance operations into workstations
    workstations = group_and_balance(sorted_ops, ucl, lcl)
    
    # Step 4: Calculate line efficiency
    line_efficiency = calculate_line_efficiency(sorted_ops, workstations, pitch_time)
    
    # Step 5: Build report
    report_df = build_report_dataframe(workstations, ucl, lcl)
    
    return {
        "operations": operations,
        "sorted_operations": sorted_ops,
        "pitch_time": pitch_time,
        "ucl": ucl,
        "lcl": lcl,
        "workstations": workstations,
        "line_efficiency": line_efficiency,
        "report_df": report_df,
        "total_ops": total_ops or len(operations),
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
            total_ops_str = request.form.get("total_ops", "")
            tolerance_str = request.form.get("tolerance", "0.15")
            
            if not file or file.filename == "":
                error = "Please select a file to upload."
            else:
                # Parse parameters
                total_ops = int(total_ops_str) if total_ops_str else None
                tolerance = float(tolerance_str)
                
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
                            result = calculate_balance(operations, total_ops, tolerance)
                            
                            # Convert dataframe to list of dicts for template
                            df = result["report_df"]
                            rows = df.to_dict("records")
                            
                            # Format numeric values
                            for row in rows:
                                row["Combined Basic Time"] = f"{row['Combined Basic Time']:.2f}"
                                row["Balancing SAM"] = f"{row['Balancing SAM']:.2f}"
                            
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
    """Recalculate with manual overrides."""
    data = request.json
    session_id = data.get("session_id")
    
    calc = get_calculation(session_id)
    if not calc:
        return jsonify({"error": "Session not found"}), 404
    
    # TODO: Implement manual override logic here
    # For now, just return the same calculation
    
    return jsonify({"status": "ok", "result": calc})


@app.route("/monitor")
def monitor():
    """Floor monitoring view (simplified, responsive)."""
    return render_template_string(MONITOR_TEMPLATE)


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

        .header h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #fff 0%, #94a3b8 100%);
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
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            color: var(--text);
        }

        .metric-card.highlight .value {
            color: var(--accent);
        }

        /* Table Section */
        .table-section h3 {
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
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
        }

        th {
            background: var(--surface-2);
            padding: 14px 16px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            text-align: left;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }

        td {
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
            font-variant-numeric: tabular-nums;
        }

        tbody tr:hover {
            background: rgba(59, 130, 246, 0.06);
        }

        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
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
            gap: 12px;
            margin-top: 24px;
            flex-wrap: wrap;
        }

        .export-buttons button {
            background: var(--surface-2);
            color: var(--text);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            padding: 10px 20px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all var(--transition);
        }

        .export-buttons button:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
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
            }
            
            .header {
                flex-direction: column;
                align-items: flex-start;
            }

            .header h1 {
                font-size: 24px;
            }

            .form-grid {
                grid-template-columns: 1fr;
            }

            .metrics-grid {
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            }

            table {
                font-size: 12px;
            }

            th, td {
                padding: 10px 12px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Line Balancing Optimizer</h1>
                <p>Upload operation data and configure parameters to optimize workstation balance</p>
            </div>
            <button class="theme-toggle" onclick="toggleTheme()">🌙 Dark</button>
        </div>

        <form method="post" enctype="multipart/form-data" class="form-card">
            <h2>Configuration</h2>
            <div class="form-grid">
                <div class="field" style="grid-column: span 2;">
                    <label>Upload CSV/XLSX file</label>
                    <input type="file" name="file" accept=".csv,.xlsx,.xls" required>
                </div>
                <div class="field">
                    <label>Total operation count</label>
                    <input type="number" name="total_ops" value="27" min="1">
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
                    <div class="value">{{ "%.2f"|format(result.pitch_time) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">UCL</div>
                    <div class="value">{{ "%.2f"|format(result.ucl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card">
                    <div class="label">LCL</div>
                    <div class="value">{{ "%.2f"|format(result.lcl) }}<span style="font-size: 12px; color: var(--text-muted);">s</span></div>
                </div>
                <div class="metric-card highlight">
                    <div class="label">Efficiency</div>
                    <div class="value">{{ "%.1f"|format(result.line_efficiency) }}<span style="font-size: 12px; color: var(--text-muted);">%</span></div>
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
                <h3>Workstation Report</h3>
                <div class="table-wrapper">
                    <div class="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    <th>Serial/Id</th>
                                    <th>Workstation</th>
                                    <th>Operations</th>
                                    <th>Basic Time</th>
                                    <th>Combined Basic Time</th>
                                    <th>M/P</th>
                                    <th>Balancing SAM</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for row in rows %}
                                <tr>
                                    <td>{{ row['Serial/Id'] }}</td>
                                    <td>{{ row['Workstation'] }}</td>
                                    <td>{{ row['Operations'] }}</td>
                                    <td>{{ row['Basic Time'] }}</td>
                                    <td>{{ row['Combined Basic Time'] }}</td>
                                    <td>{{ row['M/P'] }}</td>
                                    <td>{{ row['Balancing SAM'] }}</td>
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

            <div class="export-buttons">
                <button onclick="exportFile('csv', '{{ session_id }}')">📥 Export CSV</button>
                <button onclick="exportFile('xlsx', '{{ session_id }}')">📥 Export Excel</button>
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
    <style>
        :root {
            --bg: #0f1419;
            --surface: #1a2332;
            --border: rgba(255, 255, 255, 0.08);
            --text: #e8edf4;
            --accent: #3b82f6;
            --success: #22c55e;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 20px;
        }
        .monitor {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            font-size: 28px;
            margin-bottom: 20px;
            color: var(--accent);
        }
        .status {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            margin-top: 40px;
        }
        .status p {
            color: #8b9cb3;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <div class="monitor">
        <h1>📊 Line Monitoring</h1>
        <div class="status">
            <p>Floor monitoring view - real-time line efficiency metrics</p>
            <p style="margin-top: 10px; font-size: 14px;">(Load a calculation from the main view to display metrics)</p>
        </div>
    </div>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
