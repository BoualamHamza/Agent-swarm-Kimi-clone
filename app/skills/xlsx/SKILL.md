---
name: xlsx
description: INVOKE for ANY task whose primary input or output is a spreadsheet (.xlsx, .xlsm, .csv, .tsv). Covers creating new Excel models from scratch, editing existing workbooks, building financial dashboards, cleaning messy tabular data, producing multi-sheet reports, and converting between tabular formats. Triggers — "Excel", "spreadsheet", "xlsx", "workbook", "dashboard", "pivot", "financial model", "build me a sheet", or any user-supplied .xlsx path. Do NOT trigger when the deliverable is a Word doc, PDF report, HTML page, or a database/API pipeline.
---

# Excel (xlsx) Skill

## Overview
The deliverable is **always a real .xlsx file** that opens cleanly in Excel/Google Sheets with **zero formula errors** and uses **Excel formulas** (not Python-computed numbers) wherever a calculation is involved. Workbooks should be production-grade: consistent fonts, color-coded inputs vs formulas, currency-aware number formats, and a Dashboard sheet when the model has more than 2 sheets of data.

Run the pipeline inside the sandbox via `run_python` and write outputs to `/home/user/workspace/artifacts/`.

## Critical Reminders
1. **`run_python` is stateless** — do all the work in ONE script per call, or persist intermediate results under `/home/user/workspace/`.
2. **Deliverables go in `/home/user/workspace/artifacts/`** — files there are exposed to the user.
3. **Use formulas, not hardcoded numbers**. `sheet['B10'] = '=SUM(B2:B9)'`, NOT `sheet['B10'] = df['Sales'].sum()`. The workbook must recalculate when an input changes.
4. **Always recalc after writing**. openpyxl writes formulas as text — LibreOffice must compute the cached values, otherwise the user sees a blank cell. Use `scripts/recalc.py` (see below).
5. **Zero formula errors on delivery**. `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A` are all blockers. The recalc script reports them; fix them and re-run.

## Output Standards (apply to every deliverable)

### Professional Font
Use a single, professional font (default: Calibri 11). Don't mix fonts inside a workbook.

### Color Coding (industry-standard, especially for financial models)
| Color | RGB | Used for |
|-------|-----|----------|
| **Blue** | 0,0,255 | Hardcoded inputs / assumptions the user will tweak |
| **Black** | 0,0,0 | All formulas and calculations |
| **Green** | 0,128,0 | Links pulling from other sheets within the same workbook |
| **Red** | 255,0,0 | External links to other files |
| **Yellow fill** | 255,255,0 | Key assumptions that need attention or are placeholders |

### Number Formats
- **Years**: text strings (`"2024"`), never `2,024`
- **Currency**: `$#,##0;($#,##0);-` — parentheses for negatives, dash for zero
- **Percentages**: `0.0%` (one decimal by default)
- **Multiples**: `0.0x` (e.g., EV/EBITDA, P/E)
- **Headers must declare units**: `Revenue ($mm)`, not `Revenue`

### Formula Hygiene
- Assumptions live in dedicated cells; formulas reference them: `=B5*(1+$B$6)`, NOT `=B5*1.05`
- Use absolute refs (`$A$1`) for assumption cells so the formula copies cleanly
- Guard divisions: `=IFERROR(A/B, 0)` to dodge `#DIV/0!`
- Cross-sheet refs use the form `'Sheet Name'!A1` (single quotes when the sheet name has spaces)

### Updating Existing Templates
- READ the existing workbook first — match its font, colors, header style, and column widths
- Existing template conventions ALWAYS override these defaults

## Tooling

### Library Selection
- **pandas** — best for reading, cleaning, and bulk export of tabular data
- **openpyxl** — best for formulas, formatting, charts, named ranges, conditional formatting
- **xlsxwriter** — alternative for write-only workflows; great chart support, can't edit existing files

### Reading & Analyzing
```python
import pandas as pd
df = pd.read_excel('file.xlsx')                       # first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # dict of DataFrames
df.head(); df.info(); df.describe()
```

### Reading formula values (only after recalc)
```python
from openpyxl import load_workbook
wb = load_workbook('out.xlsx', data_only=True)  # returns cached values; raw formulas are gone if saved
```
⚠️ NEVER save a workbook that was opened with `data_only=True` — you'd permanently destroy the formulas.

### Creating a new workbook (canonical pattern)
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, NamedStyle
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "Inputs"

# Header row
ws['A1'] = "Assumption"
ws['B1'] = "Value"
for c in ws[1]:
    c.font = Font(bold=True, color='FFFFFF')
    c.fill = PatternFill('solid', start_color='1E2761')

# Blue input
ws['A2'] = "Growth rate"; ws['B2'] = 0.12
ws['B2'].font = Font(color='0000FF')      # blue = hardcoded input
ws['B2'].number_format = '0.0%'

# Formula on another sheet referencing the input
calc = wb.create_sheet("Model")
calc['A1'] = "Revenue"; calc['B1'] = 1_000_000
calc['B1'].number_format = '$#,##0'
calc['C1'] = "=B1*(1+Inputs!$B$2)"
calc['C1'].font = Font(color='000000')    # black = formula
calc['C1'].number_format = '$#,##0;($#,##0);-'

ws.column_dimensions['A'].width = 28
ws.column_dimensions['B'].width = 14

wb.save('/home/user/workspace/artifacts/model.xlsx')
```

## Mandatory Recalc Step

After writing any workbook with formulas, recalculate via the bundled script:

```python
import subprocess, json
res = subprocess.run(
    ["python", "/home/user/skills/xlsx/scripts/recalc.py",
     "/home/user/workspace/artifacts/model.xlsx"],
    capture_output=True, text=True, timeout=120,
)
report = json.loads(res.stdout)
print(report)
```

`report` is JSON with:
- `status`: `"success"` (zero errors) or `"errors_found"`
- `total_formulas`: count of formulas in the workbook
- `total_errors`: count of `#REF!`/`#DIV/0!`/etc cells
- `error_summary`: dict of `{error_type: {count, locations: ["Sheet!Cell", ...]}}`

If `errors_found`, fix the offending cells and re-run recalc. **Do not deliver a workbook with errors.**

## Building a Dashboard Sheet
When the model has 3+ data sheets, always add a `Dashboard` sheet at index 0 with:
- **KPI tiles** — large numbers (e.g., revenue, EBITDA margin, intrinsic value) pulled by formula from the model sheets, formatted boldly
- **A chart** — line chart for time series, bar chart for category comparisons. Use `openpyxl.chart`:
  ```python
  from openpyxl.chart import LineChart, Reference
  chart = LineChart()
  chart.title = "Revenue Forecast ($mm)"
  chart.style = 12
  chart.y_axis.title = "USD millions"
  chart.x_axis.title = "Year"
  data = Reference(ws, min_col=2, min_row=1, max_col=6, max_row=2)
  cats = Reference(ws, min_col=2, min_row=1, max_col=6, max_row=1)
  chart.add_data(data, titles_from_data=True)
  chart.set_categories(cats)
  ws.add_chart(chart, "B10")
  ```
- **A scenario / sensitivity table** when the model has user-tweakable assumptions
- Freeze panes (`ws.freeze_panes = "B2"`) and hide gridlines (`ws.sheet_view.showGridLines = False`) for a polished look

## Common Workflow
1. Pick libraries (pandas for bulk data, openpyxl for formulas/formatting)
2. Load existing or create new workbook
3. Lay out **Inputs** sheet first (blue, hardcoded)
4. Build **Model** / detail sheets with **formula references** to Inputs
5. Add a **Dashboard** sheet (sheet index 0) for any multi-sheet output
6. Save → recalc → fix errors → re-recalc until `status == "success"`
7. Write the artifact path to shared memory: `write_to_shared_memory(key="artifact:xlsx", value="<absolute path>")`
8. In your final message, summarise WHAT is in the workbook and the path — don't dump the data

## Quick Pitfalls Checklist
- [ ] Column letters match column numbers (col 27 = AA, not Z)
- [ ] Rows are 1-indexed (DataFrame row 0 = Excel row 2 if you wrote a header)
- [ ] Cross-sheet refs use `'Sheet Name'!A1` (quotes for spaces)
- [ ] Division denominators wrapped in IFERROR / IF
- [ ] No bare identifiers like `2026E` in Python list literals — quote them as strings
- [ ] `freq="ME"` for pandas (not deprecated `"M"`)
- [ ] Used number format strings, not Python f-strings ("$1,234" as a value is text, not currency)

## Code Style
- Minimal Python code, no needless comments inside scripts
- Inside the **Excel file**, DO add cell comments for non-obvious formulas and document sources for any hardcoded numbers in adjacent cells (`Source: Company 10-K FY2024 p.45`)
