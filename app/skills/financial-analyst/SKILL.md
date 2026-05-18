---
name: financial-analyst
description: INVOKE for ANY equity/financial analysis of a public company — fundamental analysis, valuation, DCF, buy/sell/hold recommendations, peer comparisons, ratio analysis, or financial-model spreadsheets. ALWAYS prefer yfinance in run_python over web scraping for public tickers. The deliverable is a polished multi-sheet Excel workbook produced via the `xlsx` skill conventions (formula-driven, color-coded inputs, Dashboard sheet, zero formula errors). Triggers — "financial analysis", "valuation", "DCF", "is it a good time to buy", "buy/sell/hold", "stock pick", "earnings", "peer comparison", "ticker", "10-K", "build a model".
---

# Financial Analyst

## Overview
End-to-end financial analysis on a public company — pull historical financials, compute ratios, build a **formula-driven DCF**, compare to peers, and deliver a multi-sheet Excel artifact that follows the `xlsx` skill standards: blue hardcoded inputs, black formulas, currency-aware number formats, a Dashboard sheet at index 0, and zero `#REF!`/`#DIV/0!` errors after a LibreOffice recalc.

**Always read `/home/user/skills/xlsx/SKILL.md` first** — this skill composes with it.

## When to Use
- Task names a public company or ticker (e.g., "PLTR", "Microsoft")
- User asks for valuation, buy/sell/hold, or a "financial model"
- User asks for a multi-sheet Excel with financials and a recommendation

## Critical reminders before you write code
1. **`run_python` is stateless** — do all the work in ONE script per call, or persist intermediate results under `/home/user/workspace/`.
2. **Deliverables go in `/home/user/workspace/artifacts/`**.
3. **Prefer `yfinance`** over scraping investor pages. It's free and structured.
4. **Use Excel formulas**, not Python-computed numbers, for every calculation. Inputs (growth rates, discount rate, terminal growth) are typed into the `Inputs` sheet in **blue**; all derived numbers reference them via formulas in **black**.
5. **Pandas modern API**: `freq="ME"` not deprecated `"M"`; quote bare identifiers like `"2026E"` inside list literals.
6. **Always run `scripts/recalc.py`** from the xlsx skill after writing the workbook. Fix any errors it reports and re-run before reporting success.
7. **NEVER fall back to hardcoded numbers when a formula errors.** If recalc reports `#DIV/0!` or `#VALUE!` in the Sensitivity / DCF / Ratios sheets, **fix the formula** — wrap denominators with `IF(a=b, 1E-9, a-b)`, wrap risky expressions in `IFERROR(..., "")`, or split a complex closed-form into helper rows. **Do not** compute the values in Python and paste them in: that silently breaks the entire purpose of the model (the user can no longer tweak Inputs and see the table update).

## Workbook Structure (canonical)
```
Dashboard           ← KPI tiles + recommendation + price/intrinsic chart
Inputs              ← all assumptions (blue cells the user will tweak)
Income Statement    ← historical, pulled from yfinance
Balance Sheet       ← historical
Cash Flow           ← historical
Ratios              ← formulas referencing IS/BS
DCF                 ← formula-driven 10-yr projection + terminal value
Sensitivity         ← 2D data table: discount rate × terminal growth
Peers               ← (optional) peer multiples comparison
Price History       ← last 1Y daily closes
```

## End-to-end Recipe (one `run_python` call)

```python
import subprocess, sys, os, json
from pathlib import Path

def _ensure(pkgs):
    missing = []
    for p in pkgs:
        mod = p.split("==")[0].split(">")[0].replace("-", "_")
        try: __import__(mod)
        except ImportError: missing.append(p)
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])

_ensure(["yfinance", "openpyxl", "pandas", "numpy"])

import numpy as np
import pandas as pd
import yfinance as yf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import LineChart, BarChart, Reference

TICKER = "PLTR"                                          # <-- replace
OUTDIR = Path("/home/user/workspace/artifacts"); OUTDIR.mkdir(parents=True, exist_ok=True)
OUT = OUTDIR / f"{TICKER}_financial_model.xlsx"

# ── 1. Pull data ───────────────────────────────────────────────────────────
t = yf.Ticker(TICKER)
income, balance, cashflow = t.financials, t.balance_sheet, t.cashflow
info = t.info
hist = t.history(period="1y")

# Years (newest -> oldest from yfinance). Convert to strings to dodge Excel year-formatting.
years = [str(c.year) for c in income.columns]
n_years = len(years)

# ── 2. Build workbook ──────────────────────────────────────────────────────
wb = Workbook()
wb.remove(wb.active)  # start clean

BLUE   = Font(color="0000FF", name="Calibri", size=11)
BLACK  = Font(color="000000", name="Calibri", size=11)
GREEN  = Font(color="008000", name="Calibri", size=11)
BOLD   = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
NAVY_FILL = PatternFill("solid", start_color="1E2761")
YELLOW    = PatternFill("solid", start_color="FFFF00")
CUR  = '$#,##0;($#,##0);-'
PCT  = '0.0%'
MULT = '0.0"x"'

def header_row(ws, row, labels, fills=True):
    for i, lab in enumerate(labels, 1):
        c = ws.cell(row=row, column=i, value=lab)
        c.font = BOLD
        if fills: c.fill = NAVY_FILL
        c.alignment = Alignment(horizontal="center")

# ─── Inputs sheet ──────────────────────────────────────────────────────────
inp = wb.create_sheet("Inputs")
inp.sheet_view.showGridLines = False
inp["A1"] = "Assumption"; inp["B1"] = "Value"; inp["C1"] = "Notes"
header_row(inp, 1, ["Assumption", "Value", "Notes"])

assumptions = [
    ("Ticker",                  TICKER,        "Yahoo Finance ticker"),
    ("Discount rate (WACC)",    0.10,          "Cost of capital, %"),
    ("Terminal growth",         0.03,          "Long-run FCF growth, %"),
    ("FCF growth — yrs 1–5",    0.20,          "Explicit forecast growth, %"),
    ("FCF growth — yrs 6–10",   0.10,          "Fade growth, %"),
    ("Shares outstanding (mm)", (info.get("sharesOutstanding") or 1) / 1e6, "Source: yfinance .info"),
    ("Current price",           info.get("currentPrice") or float(hist["Close"].iloc[-1]), "Source: yfinance"),
    ("Starting FCF ($mm)",
        float(cashflow.loc["Free Cash Flow"].iloc[0]) / 1e6
            if "Free Cash Flow" in cashflow.index else 1000.0,
        "Source: yfinance cashflow, latest FY"),
]
for i, (label, value, note) in enumerate(assumptions, 2):
    inp.cell(row=i, column=1, value=label)
    c = inp.cell(row=i, column=2, value=value)
    c.font = BLUE
    if isinstance(value, float) and abs(value) < 1: c.number_format = PCT
    elif isinstance(value, (int, float)):           c.number_format = '#,##0.00'
    inp.cell(row=i, column=3, value=note)

inp.column_dimensions["A"].width = 28
inp.column_dimensions["B"].width = 16
inp.column_dimensions["C"].width = 48

# Cell references we'll need repeatedly
R_WACC          = "Inputs!$B$3"
R_TERMG         = "Inputs!$B$4"
R_GROWTH_1_5    = "Inputs!$B$5"
R_GROWTH_6_10   = "Inputs!$B$6"
R_SHARES_MM     = "Inputs!$B$7"
R_PRICE         = "Inputs!$B$8"
R_FCF_0         = "Inputs!$B$9"

# ─── Historical statements ────────────────────────────────────────────────
def dump(ws_name, df):
    ws = wb.create_sheet(ws_name)
    ws.sheet_view.showGridLines = False
    ws.cell(row=1, column=1, value=ws_name).font = BOLD
    for j, col in enumerate(df.columns, 2):
        ws.cell(row=1, column=j, value=str(col.year)).font = BOLD
    for i, idx in enumerate(df.index, 2):
        ws.cell(row=i, column=1, value=str(idx))
        for j, col in enumerate(df.columns, 2):
            val = df.loc[idx, col]
            c = ws.cell(row=i, column=j, value=None if pd.isna(val) else float(val))
            c.number_format = CUR
            c.font = BLACK
    ws.column_dimensions["A"].width = 36
    for j in range(2, df.shape[1] + 2):
        ws.column_dimensions[get_column_letter(j)].width = 16
    return ws

dump("Income Statement", income)
dump("Balance Sheet",    balance)
dump("Cash Flow",        cashflow)

# ─── Ratios sheet (formula-driven cross-sheet refs) ───────────────────────
ra = wb.create_sheet("Ratios")
ra.sheet_view.showGridLines = False
ra["A1"] = "Ratio"; ra["A1"].font = BOLD
for j, y in enumerate(years, 2):
    c = ra.cell(row=1, column=j, value=y); c.font = BOLD

def find_row(ws_name, label):
    """1-indexed row number of `label` in the first column of the given sheet."""
    ws = wb[ws_name]
    for r in range(1, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == label:
            return r
    return None

def ratio(name, ws_name, num_label, den_label, fmt=PCT):
    nr = find_row(ws_name, num_label); dr = find_row(ws_name, den_label)
    if nr is None or dr is None: return
    row = ra.max_row + 1
    ra.cell(row=row, column=1, value=name)
    for j in range(2, n_years + 2):
        col = get_column_letter(j)
        f = f"=IFERROR('{ws_name}'!{col}{nr}/'{ws_name}'!{col}{dr},0)"
        c = ra.cell(row=row, column=j, value=f)
        c.font = GREEN  # cross-sheet link
        c.number_format = fmt

ratio("Gross Margin",     "Income Statement", "Gross Profit",     "Total Revenue")
ratio("Operating Margin", "Income Statement", "Operating Income", "Total Revenue")
ratio("Net Margin",       "Income Statement", "Net Income",       "Total Revenue")
ra.column_dimensions["A"].width = 28
for j in range(2, n_years + 2):
    ra.column_dimensions[get_column_letter(j)].width = 14

# ─── DCF sheet (formula-driven) ───────────────────────────────────────────
dcf = wb.create_sheet("DCF")
dcf.sheet_view.showGridLines = False
header_row(dcf, 1, ["Year"] + [f"Y{i}" for i in range(1, 11)] + ["Terminal"])

# Row 2: FCF growth (formula referencing Inputs)
dcf.cell(row=2, column=1, value="FCF growth")
for i in range(1, 11):
    col = get_column_letter(i + 1)
    f = f"=IF({i}<=5,{R_GROWTH_1_5},{R_GROWTH_6_10})"
    c = dcf.cell(row=2, column=i + 1, value=f); c.font = BLACK; c.number_format = PCT

# Row 3: FCF projection
dcf.cell(row=3, column=1, value="FCF ($mm)")
dcf.cell(row=3, column=2, value=f"={R_FCF_0}*(1+B2)").font = BLACK
dcf.cell(row=3, column=2).number_format = CUR
for i in range(2, 11):
    prev = get_column_letter(i); cur = get_column_letter(i + 1)
    c = dcf.cell(row=3, column=i + 1, value=f"={prev}3*(1+{cur}2)")
    c.font = BLACK; c.number_format = CUR

# Row 4: Discount factor
dcf.cell(row=4, column=1, value="Discount factor")
for i in range(1, 11):
    col = get_column_letter(i + 1)
    c = dcf.cell(row=4, column=i + 1, value=f"=1/(1+{R_WACC})^{i}")
    c.font = BLACK; c.number_format = '0.000'

# Row 5: PV of FCF
dcf.cell(row=5, column=1, value="PV of FCF ($mm)")
for i in range(1, 11):
    col = get_column_letter(i + 1)
    c = dcf.cell(row=5, column=i + 1, value=f"={col}3*{col}4")
    c.font = BLACK; c.number_format = CUR

# Terminal value column (L = col 12)
dcf.cell(row=3, column=12, value=f"=K3*(1+{R_TERMG})/({R_WACC}-{R_TERMG})").number_format = CUR
dcf.cell(row=3, column=12).font = BLACK
dcf.cell(row=4, column=12, value="=K4")
dcf.cell(row=5, column=12, value="=L3*L4").number_format = CUR

# Summary block (rows 7–13)
dcf.cell(row=7,  column=1, value="Enterprise Value ($mm)")
dcf.cell(row=7,  column=2, value="=SUM(B5:L5)").number_format = CUR
dcf.cell(row=8,  column=1, value="Shares outstanding (mm)")
dcf.cell(row=8,  column=2, value=f"={R_SHARES_MM}").number_format = '#,##0.00'
dcf.cell(row=9,  column=1, value="Intrinsic value / share")
dcf.cell(row=9,  column=2, value="=IFERROR(B7/B8,0)").number_format = CUR
dcf.cell(row=10, column=1, value="Current price")
dcf.cell(row=10, column=2, value=f"={R_PRICE}").number_format = CUR
dcf.cell(row=11, column=1, value="Upside / (downside)")
dcf.cell(row=11, column=2, value="=IFERROR(B9/B10-1,0)").number_format = PCT
dcf.cell(row=12, column=1, value="Recommendation")
dcf.cell(row=12, column=2, value='=IF(B11>0.2,"BUY",IF(B11<-0.2,"SELL","HOLD"))')
dcf.cell(row=12, column=2).font = Font(bold=True, name="Calibri")

dcf.column_dimensions["A"].width = 30
for j in range(2, 13):
    dcf.column_dimensions[get_column_letter(j)].width = 14

# ─── Sensitivity: discount rate (rows) × terminal growth (cols) ─────────
# IMPORTANT — formulas here MUST stay live (not Python-computed hardcodes).
# Three robustness rules embedded below:
#   1. Each (dr - g) denominator wrapped in IF(dr=g, 1e-9, dr-g) → no #DIV/0!
#   2. Whole expression wrapped in IFERROR(..., "") → no #VALUE! leaks
#   3. Discount rate referenced via $A2 / terminal growth via B$1 (cell refs,
#      not Python interpolation) so the table responds to user edits.
sens = wb.create_sheet("Sensitivity")
sens.sheet_view.showGridLines = False
sens["A1"] = "Discount rate ↓ / Terminal growth →"; sens["A1"].font = BOLD
disc_rates   = [0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13]
term_growths = [0.01, 0.02, 0.03, 0.04, 0.05]
for j, tg in enumerate(term_growths, 2):
    c = sens.cell(row=1, column=j, value=tg); c.number_format = PCT; c.font = BOLD
for i, dr_val in enumerate(disc_rates, 2):
    c = sens.cell(row=i, column=1, value=dr_val); c.number_format = PCT; c.font = BOLD
    for j, _ in enumerate(term_growths, 2):
        col = get_column_letter(j)
        DR = f"$A{i}"          # discount rate cell ref (column-locked)
        TG = f"{col}$1"        # terminal growth cell ref (row-locked)
        G1 = R_GROWTH_1_5      # Inputs!$B$5
        G2 = R_GROWTH_6_10     # Inputs!$B$6
        FCF0 = R_FCF_0
        SH   = R_SHARES_MM
        # Each denominator guarded against equality with discount rate.
        # 1e-9 is a tiny non-zero stub — vanishingly small effect, but no crash.
        D1 = f"IF({DR}={G1},1E-9,{DR}-{G1})"
        D2 = f"IF({DR}={G2},1E-9,{DR}-{G2})"
        D3 = f"IF({DR}={TG},1E-9,{DR}-{TG})"
        f = (
            f"=IFERROR(("
            f"{FCF0}*(1+{G1})*(1-((1+{G1})/(1+{DR}))^5)/{D1}"
            f"+{FCF0}*(1+{G1})^5*(1+{G2})*(1-((1+{G2})/(1+{DR}))^5)/{D2}/(1+{DR})^5"
            f"+{FCF0}*(1+{G1})^5*(1+{G2})^5*(1+{TG})/{D3}/(1+{DR})^10"
            f")/{SH},\"\")"
        )
        c = sens.cell(row=i, column=j, value=f); c.font = BLACK; c.number_format = CUR

sens.column_dimensions["A"].width = 14
for j in range(2, len(term_growths) + 2):
    sens.column_dimensions[get_column_letter(j)].width = 12

# ─── Price history ─────────────────────────────────────────────────────────
ph = wb.create_sheet("Price History")
ph.sheet_view.showGridLines = False
ph["A1"], ph["B1"] = "Date", "Close"
for c in ph[1]: c.font = BOLD
last_year = hist.tail(252)
for i, (idx, row) in enumerate(last_year.iterrows(), 2):
    ph.cell(row=i, column=1, value=idx.date())
    ph.cell(row=i, column=2, value=float(row["Close"])).number_format = CUR
ph.column_dimensions["A"].width = 14
ph.column_dimensions["B"].width = 14

# ─── Dashboard (sheet 0) ───────────────────────────────────────────────────
dash = wb.create_sheet("Dashboard", 0)
dash.sheet_view.showGridLines = False
dash["A1"] = f"{TICKER} — Valuation Dashboard"
dash["A1"].font = Font(size=20, bold=True, color="1E2761", name="Calibri")
dash.merge_cells("A1:F1")

# KPI tiles
kpis = [
    ("Recommendation",      "=DCF!B12",                        None),
    ("Intrinsic / share",   "=DCF!B9",                         CUR),
    ("Current price",       f"={R_PRICE}",                     CUR),
    ("Upside / downside",   "=DCF!B11",                        PCT),
    ("Enterprise Value $mm","=DCF!B7",                         CUR),
    ("Discount rate",       f"={R_WACC}",                      PCT),
]
for i, (label, formula, fmt) in enumerate(kpis):
    col = get_column_letter(1 + i)
    dash.cell(row=3, column=1 + i, value=label).font = Font(size=10, bold=True, color="808080")
    cell = dash.cell(row=4, column=1 + i, value=formula)
    cell.font = Font(size=22, bold=True, color="1E2761", name="Calibri")
    if fmt: cell.number_format = fmt
    dash.column_dimensions[col].width = 22

# Price history chart
chart = LineChart()
chart.title = f"{TICKER} — Last 12 months"
chart.style = 12
chart.y_axis.title = "Close ($)"
chart.x_axis.title = "Date"
data = Reference(ph, min_col=2, min_row=1, max_row=ph.max_row)
cats = Reference(ph, min_col=1, min_row=2, max_row=ph.max_row)
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
chart.height = 10; chart.width = 22
dash.add_chart(chart, "A7")

# Reorder sheets for a clean experience
wb.move_sheet("Dashboard", offset=-wb.sheetnames.index("Dashboard"))
wb.save(OUT)

# ─── Mandatory recalc ──────────────────────────────────────────────────────
res = subprocess.run(
    ["python", "/home/user/skills/xlsx/scripts/recalc.py", str(OUT), "120"],
    capture_output=True, text=True, timeout=180,
)
report = json.loads(res.stdout) if res.stdout.strip().startswith("{") else {"raw": res.stdout, "err": res.stderr}
print(json.dumps(report, indent=2))
print(f"\nArtifact: {OUT}")
```

## After Running
1. If `report["status"] != "success"`, inspect `report["error_summary"]` — fix offending cells and re-run the whole script (or the recalc step) until clean.
2. Record the artifact path: `write_to_shared_memory(key="artifact:financial-analysis", value="<absolute path>")`
3. In your final response: state the recommendation, intrinsic / current / upside, and 3–5 most decisive ratios. Don't dump the workbook contents — the file is the deliverable.

## Tips
- **Peer comparison**: repeat the `yf.Ticker(p).info` lookup over a list of peers, assemble into a `Peers` sheet with cross-sheet formulas linking to multiples (P/E, EV/EBITDA).
- **Scenario sheet**: add a small Inputs-style block with "Base", "Bull", "Bear" columns, each containing the trio of (WACC, terminal g, FCF growth). The DCF can read whichever column is selected via INDEX/MATCH.
- **When yfinance is missing a metric**: fall back to `web_search` + `scrape_url` only as a last resort, and document the source in the Inputs sheet `Notes` column.
- Pair with the **data-vulgariser** skill when the user wants a plain-English summary alongside the workbook.
