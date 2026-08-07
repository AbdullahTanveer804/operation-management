# Line Balancing Optimizer

A Python implementation of your factory's manual line-balancing workflow:
read operations -> sequence by predecessor -> calculate Pitch Time / UCL / LCL
-> group & balance into workstations -> report Line Efficiency.

## Project Structure

```
line_balancer/
├── data/
│   └── sample_operations.csv     # sample dataset (24-op garment style)
├── src/line_balancer/
│   ├── models.py                 # Operation, Workstation
│   ├── io_utils.py                # STEP 1 - read/validate CSV or XLSX
│   ├── sequencing.py              # STEP 2 - predecessor-based topological sort
│   ├── metrics.py                 # STEP 3, 4, 6 - pitch time, UCL/LCL, efficiency
│   ├── balancing.py               # STEP 5 - grouping & manpower splitting
│   ├── report.py                  # STEP 7 - display & export report
│   └── main.py                    # orchestrates the pipeline + CLI
└── tests/                         # pytest unit tests
```

## Setup in VS Code

1. **Open the folder**
   Extract the zip, then in VS Code: `File > Open Folder...` and select `line_balancer/`.
2. **Create a virtual environment** (VS Code terminal: ``Ctrl+` ``)

   ```bash
   python3 -m venv .venv
   ```
3. **Activate it**

   - macOS/Linux: `source .venv/bin/activate`
   - Windows: `.venv\Scripts\activate`

   VS Code will usually prompt *"Select interpreter"* — pick the one inside `.venv`.
4. **Install the package + dependencies**

   ```bash
   pip install -e .
   pip install pytest
   ```

   `-e .` installs it in "editable" mode, using `pyproject.toml`, so edits to the code take effect immediately without reinstalling.

## Running it

```bash
python -m line_balancer.main data/sample_operations.csv --total-ops 27 --export data/report.csv
```

- `--total-ops 27` — matches your factory's convention of dividing by the true total operation count, even if this file only lists 24 stitching operations.
- `--tolerance 0.15` — UCL/LCL band width (defaults to 15%).
- `--export` — optional, writes the workstation report to CSV or XLSX.

## Testing

```bash
python -m pytest tests/ -v
```

All logic (sequencing, pitch time, grouping/splitting) has unit tests you can extend as you add features.

## Using your own data

Your input file just needs these four columns (CSV or XLSX):

| Operation_Name | Predecessor | Machine_Type | Basic_Time |
| -------------- | ----------- | ------------ | ---------- |

- `Predecessor` can be empty/`-` (no predecessor), a single ID, or comma-separated (`9,11`) for multiple predecessors — matches row position as the operation ID, same as your factory sheet.
- `Basic_Time` should be in seconds.

## Known limitation (by design, for now)

Workstations flagged `> UCL (review)` or `< LCL (review)` mean the algorithm's grouping/splitting logic couldn't land inside the tolerance band with a whole number of operators — the closest achievable fit was used instead. This is expected: your IE team's manual judgment (line layout, cross-training, holistic balance) captures things this data alone can't. Treat these as the tool's "please double-check this one" flags, not failures — the next step for the tool is a UI where these groupings can be manually overridden.
