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

## Mandatory Chart Lint Step (if the workbook has charts)

Recalc only checks formulas — it is blind to charts. openpyxl writes only a chart's
formula references (never the plotted values), so a chart pointing at the wrong range or
the wrong orientation raises no error and silently renders blank. After recalc, lint every
chart with the bundled script:

```python
import subprocess, json
res = subprocess.run(
    ["python", "/home/user/skills/xlsx/scripts/chart_lint.py",
     "/home/user/workspace/artifacts/model.xlsx"],
    capture_output=True, text=True, timeout=60,
)
chart_report = json.loads(res.stdout)
print(chart_report)
```

`chart_report` is JSON with `status` (`"success"` | `"issues_found"`), `total_charts`,
`total_issues`, and `issues` — each issue naming the chart, its title, and a `type`:
- `empty_chart` — chart has no data series
- `untitled_series` — a series with no title (legend will show `Series1…N`)
- `single_point_series` — a line series referencing a single cell (renders blank; usually a missing `from_rows=True`)
- `overlapping_charts` — two charts collide on the same sheet

If `issues_found`, fix the chart code (see the rules below) and re-run. **Do not deliver a
workbook whose charts don't lint clean.**

## Building a Dashboard Sheet
When the model has 3+ data sheets, always add a `Dashboard` sheet at index 0 with:
- **KPI tiles** — large numbers (revenue, EBITDA margin, intrinsic value) pulled by formula from the model sheets, styled with the `kpi_tile` helper below
- **Charts** — see the chart rules below (this is where dashboards most often break)
- **A scenario / sensitivity table** when the model has user-tweakable assumptions
- Freeze panes (`ws.freeze_panes = "A2"`) and hide gridlines (`ws.sheet_view.showGridLines = False`)

### Dashboard styling — fixed palette, KPI tiles, section bands
A dashboard looks clean when it uses **one accent color**, boxed KPI tiles, and labelled
section bands — not ad-hoc bold text. Use this palette (the navy `1E2761` matches the
canonical header style above) and these two helpers verbatim; don't invent new colors.

```python
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

NAVY, TINT, GRID, WHITE = "1E2761", "EEF0F7", "D9D9D9", "FFFFFF"   # accent / tile fill / hairline / text
USED_COLS = 12                                                     # how wide your dashboard content is
_thin = Side(style="thin", color=GRID)
BOX = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

def band(ws, row, text, size=11):                 # navy section header spanning the dashboard width
    ws.cell(row, 1, text).font = Font(name="Calibri", size=size, bold=True, color=WHITE)
    ws.cell(row, 1).alignment = Alignment(vertical="center")
    for col in range(1, USED_COLS + 1):
        ws.cell(row, col).fill = PatternFill("solid", fgColor=NAVY)
    ws.row_dimensions[row].height = 30 if size > 12 else 26

def kpi_tile(ws, col, top, label, value_ref, num_fmt="$#,##0"):    # boxed label-over-value card
    lab, val = ws[f"{col}{top}"], ws[f"{col}{top + 1}"]
    lab.value, val.value = label, value_ref       # value_ref is a formula, e.g. "='Income Statement'!F9"
    lab.font = Font(name="Calibri", size=9, bold=True, color=NAVY)
    val.font = Font(name="Calibri", size=18, bold=True, color="000000")
    for c in (lab, val):
        c.fill = PatternFill("solid", fgColor=TINT)
        c.alignment = Alignment(horizontal="left", vertical="center")
        c.border = BOX
    val.number_format = num_fmt
    ws.column_dimensions[col].width = 18
    ws.row_dimensions[top + 1].height = 28
```

Lay the dashboard out top-to-bottom:

```python
# 1) Title band (row 1)
dash["A1"] = "NVIDIA (NVDA) - Dashboard"
dash["A1"].font = Font(name="Calibri", size=16, bold=True, color=WHITE)
for col in range(1, USED_COLS + 1):
    dash.cell(1, col).fill = PatternFill("solid", fgColor=NAVY)
dash.row_dimensions[1].height = 30

# 2) KPI strip — tiles in B/D/F/H leave a 1-column gap between cards
band(dash, 3, "Key Metrics")
kpi_tile(dash, "B", 4, "Revenue ($mm)",   "='Income Statement'!F9",  "$#,##0")
kpi_tile(dash, "D", 4, "Diluted EPS ($)", "='Income Statement'!F21", "$#,##0.00")
kpi_tile(dash, "F", 4, "Intrinsic ($)",   "=_chartdata!B2",          "$#,##0.00")

# 3) Charts section
band(dash, 8, "Trends & Comparison")
# ... add charts below (see chart rules) ...
```

Keep chart styling consistent too: give every chart the **same** `chart.style` (e.g. `10`)
so colors and gridlines match across the dashboard.

### Charts — read this before adding ANY chart
openpyxl chart bugs are silent: openpyxl writes only the *formula references*, not the
plotted values, so a broken chart looks fine in code and only renders as blank/garbled
after recalc. The four failure modes below account for ~every bad dashboard. Follow the
rules exactly.

**1. Orientation — the #1 cause of blank line charts.**
`add_data()` reads **column-by-column by default**. Financial models put periods *across
columns* (years in `B1:F1`, a metric in `B9:F9`). Adding that horizontal range with the
default orientation produces **N single-point series** — a line needs ≥2 points, so it
draws *nothing* and the legend shows `Series1…SeriesN`. For a metric laid out across a
row you MUST pass `from_rows=True` **and** include the label cell so the series is named:

```python
from openpyxl.chart import LineChart, BarChart, Reference
from openpyxl.utils import get_column_letter

# 'Income Statement': A9="Revenue", B9:F9 = values, B1:F1 = years
c1 = LineChart()
c1.title = "Revenue Trend ($mm)"; c1.style = 10; c1.y_axis.title = "USD mm"
c1.width, c1.height = 13, 7                                          # cm — set so layout is predictable
data = Reference(inc, min_col=1, max_col=6, min_row=9, max_row=9)    # A9:F9, incl the label in A9
c1.add_data(data, titles_from_data=True, from_rows=True)            # -> 1 series, 5 points, named "Revenue"
c1.set_categories(Reference(inc, min_col=2, max_col=6, min_row=1, max_row=1))  # B1:F1 years
```

For a **category comparison** the data is usually already in a *column*, so the default
orientation is correct — just include the header cell as the title:

```python
# hidden helper: B1="$/share" (header), B2=intrinsic, B3=market ; A2/A3 = labels
c3 = BarChart(); c3.title = "Intrinsic vs Market ($/share)"; c3.width, c3.height = 13, 7
c3.add_data(Reference(hlp, min_col=2, max_col=2, min_row=1, max_row=3), titles_from_data=True)
c3.set_categories(Reference(hlp, min_col=1, max_col=1, min_row=2, max_row=3))
```

**2. Every series MUST be named.** A series with no title renders as `Series1…SeriesN`
(or `Série1…` in non-English Excel). Always either include the label cell in the data
range with `titles_from_data=True`, or set `series.tx` explicitly via `SeriesLabel`.

**3. Keep scratch data OFF the dashboard.** Helper cells the charts read from leak into
the visible sheet as clutter like `Intrinsic_tmp` / `Market_tmp`. Put them on a dedicated
sheet and hide it: `hlp = wb.create_sheet("_chartdata"); hlp.sheet_state = "hidden"`.

**4. Lay charts on a grid so they don't overlap.** A 13×7 cm chart occupies ~**8 columns
× 14 rows**. Hand-picked anchors like `A7`/`B10` collide. Use a grid whose pitch exceeds
the footprint:

```python
COL_PITCH, ROW_PITCH, FIRST_ROW = 10, 16, 9   # start below the KPI tiles
def anchor(i):                                 # 2-column grid
    return f"{get_column_letter(2 + (i % 2) * COL_PITCH)}{FIRST_ROW + (i // 2) * ROW_PITCH}"
for i, ch in enumerate([c1, c2, c3]):
    dash.add_chart(ch, anchor(i))
```

**5. Widen columns.** Default width clips text and numbers (`Revenu…`, `######`). Set
widths on every dashboard column that holds a label or KPI:
`dash.column_dimensions['A'].width = 22`.

## Common Workflow
1. Pick libraries (pandas for bulk data, openpyxl for formulas/formatting)
2. Load existing or create new workbook
3. Lay out **Inputs** sheet first (blue, hardcoded)
4. Build **Model** / detail sheets with **formula references** to Inputs
5. Add a **Dashboard** sheet (sheet index 0) for any multi-sheet output
6. Save → recalc → fix errors → re-recalc until `status == "success"`
7. If the workbook has charts → run `chart_lint.py` → fix chart code → re-lint until `status == "success"`
8. Write the artifact path to shared memory: `write_to_shared_memory(key="artifact:xlsx", value="<absolute path>")`
9. In your final message, summarise WHAT is in the workbook and the path — don't dump the data

## Quick Pitfalls Checklist
- [ ] Charts: horizontal (period-across-columns) data uses `from_rows=True`; every series has a title; charts placed on a non-overlapping grid; dashboard columns widened; helper data on a hidden sheet
- [ ] Dashboard styling: one accent color (navy `1E2761`), `kpi_tile`/`band` helpers for KPIs and section headers, a single shared `chart.style`
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
