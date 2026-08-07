import os
import tempfile
from pathlib import Path
from typing import Optional

from flask import Flask, render_template_string, request, send_file
from werkzeug.exceptions import BadRequest

from src.line_balancer.main import run_workflow

app = Flask(__name__)

HTML = """
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Line Balancer</title>
  <style>
    :root,
    [data-theme="dark"] {
      --bg: #0f1419;
      --surface: #1a2332;
      --surface-2: #243044;
      --border: rgba(255, 255, 255, 0.08);
      --text: #e8edf4;
      --text-muted: #8b9cb3;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --accent-glow: rgba(59, 130, 246, 0.25);
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --header-gradient: linear-gradient(135deg, #fff 0%, #94a3b8 100%);
      --row-hover: rgba(59, 130, 246, 0.06);
      --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
      --toggle-bg: var(--surface-2);
      --toggle-border: var(--border);
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
      --accent-glow: rgba(37, 99, 235, 0.18);
      --success: #16a34a;
      --warning: #d97706;
      --danger: #dc2626;
      --header-gradient: linear-gradient(135deg, #0f172a 0%, #475569 100%);
      --row-hover: rgba(37, 99, 235, 0.05);
      --shadow: 0 4px 24px rgba(15, 23, 42, 0.08);
      --toggle-bg: #ffffff;
      --toggle-border: rgba(15, 23, 42, 0.12);
    }

    :root {
      --radius: 12px;
      --radius-sm: 8px;
      --transition: 0.2s ease;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
      transition: background var(--transition), color var(--transition);
    }

    .page {
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }

    /* Header */
    .header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 32px;
    }
    .header-text h1 {
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      background: var(--header-gradient);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    .header-text p {
      color: var(--text-muted);
      font-size: 0.9rem;
      margin-top: 6px;
    }

    /* Theme Toggle */
    .theme-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--toggle-bg);
      border: 1px solid var(--toggle-border);
      border-radius: 999px;
      padding: 6px 14px 6px 10px;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text-muted);
      transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition);
      flex-shrink: 0;
    }
    .theme-toggle:hover {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .theme-toggle:active {
      transform: scale(0.97);
    }
    .theme-toggle svg {
      width: 18px;
      height: 18px;
      fill: currentColor;
    }
    .theme-toggle .icon-sun { display: none; }
    .theme-toggle .icon-moon { display: block; }
    [data-theme="light"] .theme-toggle .icon-sun { display: block; }
    [data-theme="light"] .theme-toggle .icon-moon { display: none; }

    /* Form Card */
    .form-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 28px;
      margin-bottom: 32px;
      box-shadow: var(--shadow);
      transition: background var(--transition), border-color var(--transition), box-shadow var(--transition);
    }
    .form-card h2 {
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-muted);
      margin-bottom: 20px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 20px;
      align-items: end;
    }
    @media (max-width: 768px) {
      .form-grid { grid-template-columns: 1fr; }
      .header { flex-direction: column; align-items: stretch; }
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .field.full-width {
      grid-column: 1 / -1;
    }
    label {
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text-muted);
    }
    input[type="number"],
    input[type="file"] {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--text);
      padding: 12px 14px;
      font-size: 0.95rem;
      transition: border-color var(--transition), box-shadow var(--transition), background var(--transition);
      width: 100%;
    }
    input[type="number"]:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    input[type="file"] {
      cursor: pointer;
      padding: 10px 14px;
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
      padding: 14px 28px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform var(--transition), box-shadow var(--transition);
      box-shadow: 0 4px 14px var(--accent-glow);
      width: 100%;
    }
    button[type="submit"]:hover {
      transform: translateY(-1px);
      box-shadow: 0 6px 20px var(--accent-glow);
    }
    button[type="submit"]:active {
      transform: translateY(0);
    }

    /* Results Section */
    .results-section {
      animation: fadeIn 0.4s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .results-section h2 {
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 20px;
      color: var(--text);
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }
    .metric-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      transition: border-color var(--transition), transform var(--transition), background var(--transition), box-shadow var(--transition);
    }
    .metric-card:hover {
      border-color: rgba(59, 130, 246, 0.3);
      transform: translateY(-2px);
    }
    .metric-card .label {
      font-size: 0.75rem;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 6px;
    }
    .metric-card .value {
      font-size: 1.35rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      color: var(--text);
    }
    .metric-card.highlight .value {
      color: var(--accent);
    }

    /* Table Section */
    .table-section h3 {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 16px;
      color: var(--text-muted);
    }
    .table-wrapper {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      box-shadow: var(--shadow);
      transition: background var(--transition), border-color var(--transition), box-shadow var(--transition);
    }
    .table-scroll {
      overflow-x: auto;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      font-size: 0.9rem;
    }
    th, td {
      padding: 14px 16px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }
    th {
      background: var(--surface-2);
      font-size: 0.75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      white-space: nowrap;
      transition: background var(--transition);
    }
    tr:last-child td {
      border-bottom: none;
    }
    tbody tr {
      transition: background var(--transition);
    }
    tbody tr:hover {
      background: var(--row-hover);
    }
    td {
      color: var(--text);
      font-variant-numeric: tabular-nums;
    }
    td:nth-child(2) {
      font-variant-numeric: normal;
      max-width: 280px;
    }
    .status-ok {
      display: inline-block;
      background: rgba(34, 197, 94, 0.15);
      color: var(--success);
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .status-warn-high {
      display: inline-block;
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .status-warn-low {
      display: inline-block;
      background: rgba(245, 158, 11, 0.15);
      color: var(--warning);
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 0.8rem;
      font-weight: 600;
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="header">
      <div class="header-text">
        <h1>Line Balancing Optimizer</h1>
        <p>Upload your operation data and configure parameters to optimize workstation balance.</p>
      </div>
      <button type="button" class="theme-toggle" id="themeToggle" aria-label="Toggle theme">
        <svg class="icon-moon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
        <svg class="icon-sun" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="5"/>
          <line x1="12" y1="1" x2="12" y2="3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="12" y1="21" x2="12" y2="23" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="1" y1="12" x2="3" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="21" y1="12" x2="23" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span class="toggle-label">Light mode</span>
      </button>
    </header>

    <form method="post" enctype="multipart/form-data" class="form-card">
      <h2>Configuration</h2>
      <div class="form-grid">
        <div class="field full-width">
          <label>Upload CSV/XLSX file</label>
          <input type="file" name="file" accept=".csv,.xlsx,.xls">
        </div>
        <div class="field">
          <label>Total operation count</label>
          <input type="number" name="total_ops" value="27">
        </div>
        <div class="field">
          <label>Tolerance</label>
          <input type="number" step="0.01" name="tolerance" value="0.15">
        </div>
        <div class="field">
          <label>&nbsp;</label>
          <button type="submit">Run calculations</button>
        </div>
      </div>
    </form>

    {% if error %}
      <div class="form-card" style="border-color: var(--danger); background: rgba(239,68,68,0.08); color: var(--danger); margin-bottom: 24px;">
        <strong>Error:</strong> {{ error }}
      </div>
    {% endif %}

    {% if result %}
    <section class="results-section">
      <h2>Results</h2>
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="label">Pitch Time</div>
          <div class="value">{{ "%.2f"|format(result.pitch_time) }}</div>
        </div>
        <div class="metric-card">
          <div class="label">UCL</div>
          <div class="value">{{ "%.2f"|format(result.ucl) }}</div>
        </div>
        <div class="metric-card">
          <div class="label">LCL</div>
          <div class="value">{{ "%.2f"|format(result.lcl) }}</div>
        </div>
        <div class="metric-card highlight">
          <div class="label">Line Efficiency</div>
          <div class="value">{{ "%.1f"|format(result.line_efficiency) }}%</div>
        </div>
        <div class="metric-card">
          <div class="label">Total Workstations</div>
          <div class="value">{{ result.total_workstations }}</div>
        </div>
        <div class="metric-card">
          <div class="label">Total Manpower</div>
          <div class="value">{{ result.total_manpower }}</div>
        </div>
      </div>

      <div class="table-section">
        <h3>Workstation Report</h3>
        <div class="table-wrapper">
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Workstation</th>
                  <th>Operations</th>
                  <th>Combined Basic Time</th>
                  <th>M/P</th>
                  <th>Balancing SAM</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {% for row in rows %}
                <tr>
                  <td>{{ row['Workstation'] }}</td>
                  <td>{{ row['Operations'] }}</td>
                  <td>{{ row['Combined_Basic_Time'] }}</td>
                  <td>{{ row['M/P'] }}</td>
                  <td>{{ row['Balancing_SAM'] }}</td>
                  <td>
                    {% if row['Status'] == 'OK' %}
                      <span class="status-ok">OK</span>
                    {% elif '> UCL' in row['Status'] %}
                      <span class="status-warn-high">{{ row['Status'] }}</span>
                    {% elif '< LCL' in row['Status'] %}
                      <span class="status-warn-low">{{ row['Status'] }}</span>
                    {% else %}
                      {{ row['Status'] }}
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
    (function () {
      var html = document.documentElement;
      var toggle = document.getElementById('themeToggle');
      var label = toggle.querySelector('.toggle-label');
      var saved = localStorage.getItem('lineBalancerTheme');

      function applyTheme(theme) {
        html.setAttribute('data-theme', theme);
        label.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
        localStorage.setItem('lineBalancerTheme', theme);
      }

      if (saved === 'light' || saved === 'dark') {
        applyTheme(saved);
      }

      toggle.addEventListener('click', function () {
        var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        applyTheme(next);
      });
    })();
  </script>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    rows = []
    error = None
    if request.method == "POST":
        try:
            uploaded_file = request.files.get("file")
            total_ops = request.form.get("total_ops", "27")
            tolerance = request.form.get("tolerance", "0.15")

            if not uploaded_file or not uploaded_file.filename:
                error = "Please select a valid CSV/XLSX file to upload."
            else:
                temp_dir = tempfile.mkdtemp(prefix="line_balancer_", dir=".")
                temp_path = Path(temp_dir) / uploaded_file.filename
                uploaded_file.save(temp_path)
                workflow = run_workflow(
                    input_path=str(temp_path),
                    total_operation_count=int(total_ops) if total_ops else None,
                    tolerance=float(tolerance) if tolerance else 0.15,
                )
                result = {
                    "pitch_time": workflow["pitch_time"],
                    "ucl": workflow["ucl"],
                    "lcl": workflow["lcl"],
                    "line_efficiency": workflow["line_efficiency"],
                    "total_workstations": len(workflow["workstations"]),
                    "total_manpower": sum(ws.manpower for ws in workflow["workstations"]),
                }
                rows = workflow["report_df"].to_dict("records")
                app.config["LAST_RESULT"] = workflow
                app.config["LAST_ROWS"] = rows
        except BadRequest as exc:
            error = "Upload failed: the submitted form was malformed or the file data could not be parsed."
        except Exception as exc:
            error = f"Processing failed: {exc}"

    return render_template_string(HTML, result=result, rows=rows, error=error)


@app.errorhandler(BadRequest)
def handle_bad_request(exc):
    error = (
        "Upload failed: the submitted request could not be parsed. "
        "Please verify the file is valid and that the form is submitted as multipart/form-data."
    )
    return render_template_string(HTML, result=None, rows=[], error=error), 400


@app.route("/download")
def download():
    fmt = request.args.get("format", "csv").lower()
    workflow = app.config.get("LAST_RESULT")
    if not workflow:
        return "No results available", 400

    temp_dir = tempfile.mkdtemp(prefix="line_balancer_export_", dir=".")
    out_path = Path(temp_dir) / f"report.{fmt if fmt in {'csv', 'xlsx'} else 'csv'}"
    if fmt == "xlsx":
        workflow["report_df"].to_excel(out_path, index=False)
    else:
        workflow["report_df"].to_csv(out_path, index=False)
    return send_file(out_path, as_attachment=True, download_name=out_path.name)


if __name__ == "__main__":
    app.run(debug=True)
