---
name: financial-analyst
description: INVOKE for ANY equity/financial analysis of a public company — fundamental analysis, valuation, DCF, buy/sell/hold recommendations, peer comparisons, ratio analysis, or financial-model spreadsheets. ALWAYS prefer yfinance in run_python over web scraping for public tickers. Triggers — "financial analysis", "valuation", "DCF", "is it a good time to buy", "buy/sell/hold", "stock pick", "earnings", "peer comparison", "ticker", "10-K", "build a model".
---

# Financial Analyst

## Overview
Conduct end-to-end financial analysis on a public company — gather historical financials, compute ratios, build a DCF, compare to peers, and deliver a structured multi-sheet artifact. The whole pipeline runs inside the sandbox via `run_python` + `yfinance`. **Do not waste tool calls scraping investor-relations pages when the data is one `yfinance` call away.**

## When to Use
- The task names a public company or ticker
- The user asks for valuation, buy/sell recommendation, or "financial model"
- The user asks for a multi-sheet Excel/CSV with financials

## Critical reminders before you write code
1. **`run_python` is stateless across calls** — each invocation is a fresh interpreter. Do all the work in ONE script per call, or persist intermediate results to disk under `/home/user/workspace/`.
2. **Deliverables go in `/home/user/workspace/artifacts/`** — files there are exposed to the user. Other locations are throwaway.
3. **Prefer `yfinance` over `web_search` + `scrape_url`** for public-company financial data. It's structured, dated, and free.
4. **Pandas modern API**: use `freq="ME"` (not deprecated `"M"`), and don't put bare identifiers like `2026E` inside list literals — quote them as strings.

## Recipe — full pipeline in one `run_python` call

```python
# Single self-contained script — run with run_python(code=..., timeout=120)
import subprocess, sys

# Ensure deps (works even if the sandbox template is older).
def _ensure(pkgs):
    missing = []
    for p in pkgs:
        mod = p.split("==")[0].split(">")[0].replace("-", "_")
        try:
            __import__(mod)
        except ImportError:
            missing.append(p)
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing])

_ensure(["yfinance", "openpyxl", "pandas", "numpy"])

import os, io
import numpy as np
import pandas as pd
import yfinance as yf

TICKER  = "PLTR"             # <-- replace with the company's ticker
OUTDIR  = "/home/user/workspace/artifacts"
os.makedirs(OUTDIR, exist_ok=True)

t = yf.Ticker(TICKER)

# ── 1. Pull primary financials ────────────────────────────────────────────
income       = t.financials                # annual income statement
balance      = t.balance_sheet             # annual balance sheet
cashflow     = t.cashflow                  # annual cash flow
quarterly_is = t.quarterly_financials
info         = t.info                      # snapshot dict (P/E, market cap, etc.)
hist         = t.history(period="5y")      # price history

# ── 2. Compute key ratios from the statements ─────────────────────────────
def safe_div(a, b):
    return (a / b).replace([np.inf, -np.inf], np.nan)

ratios = pd.DataFrame(index=income.columns)
if "Total Revenue" in income.index and "Gross Profit" in income.index:
    ratios["Gross Margin"]     = safe_div(income.loc["Gross Profit"], income.loc["Total Revenue"])
if "Operating Income" in income.index:
    ratios["Operating Margin"] = safe_div(income.loc["Operating Income"], income.loc["Total Revenue"])
if "Net Income" in income.index:
    ratios["Net Margin"]       = safe_div(income.loc["Net Income"], income.loc["Total Revenue"])

# ── 3. Simple DCF (perpetuity-growth terminal value) ──────────────────────
# All assumptions are explicit so the user can audit them.
assumptions = {
    "discount_rate":            0.10,
    "terminal_growth":          0.03,
    "fcf_growth_yrs_1_5":       0.20,
    "fcf_growth_yrs_6_10":      0.10,
    "starting_fcf_usd":         float(cashflow.loc["Free Cash Flow"].iloc[0])
                                if "Free Cash Flow" in cashflow.index else 1e9,
}
fcf = assumptions["starting_fcf_usd"]
pv  = 0.0
for yr in range(1, 11):
    g  = assumptions["fcf_growth_yrs_1_5"] if yr <= 5 else assumptions["fcf_growth_yrs_6_10"]
    fcf = fcf * (1 + g)
    pv += fcf / (1 + assumptions["discount_rate"]) ** yr
terminal = (fcf * (1 + assumptions["terminal_growth"])
            / (assumptions["discount_rate"] - assumptions["terminal_growth"]))
ev = pv + terminal / (1 + assumptions["discount_rate"]) ** 10
shares_out = info.get("sharesOutstanding") or 1
intrinsic_per_share = ev / shares_out
current_price       = info.get("currentPrice") or hist["Close"].iloc[-1]
recommendation = (
    "BUY"   if intrinsic_per_share > current_price * 1.2 else
    "SELL"  if intrinsic_per_share < current_price * 0.8 else
    "HOLD"
)

dcf_summary = pd.DataFrame({
    "Metric": [
        "Starting FCF (USD)", "PV of 10-yr FCF", "Terminal Value",
        "Enterprise Value", "Shares Outstanding",
        "Intrinsic Value / Share", "Current Price", "Recommendation",
    ],
    "Value": [
        assumptions["starting_fcf_usd"], pv, terminal, ev, shares_out,
        intrinsic_per_share, current_price, recommendation,
    ],
})

# ── 4. Multi-sheet Excel artifact ─────────────────────────────────────────
xlsx_path = f"{OUTDIR}/{TICKER}_financial_analysis.xlsx"
with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
    income.to_excel(w,                  sheet_name="Income Statement")
    balance.to_excel(w,                 sheet_name="Balance Sheet")
    cashflow.to_excel(w,                sheet_name="Cash Flow")
    quarterly_is.to_excel(w,            sheet_name="Quarterly IS")
    ratios.to_excel(w,                  sheet_name="Ratios")
    pd.DataFrame(list(assumptions.items()),
                 columns=["Assumption", "Value"]).to_excel(w, sheet_name="DCF Assumptions", index=False)
    dcf_summary.to_excel(w,             sheet_name="DCF Summary", index=False)
    hist.tail(252).to_excel(w,          sheet_name="Price (1y)")

# Also emit a CSV fallback (multi-section) for users without Excel
csv_path = f"{OUTDIR}/{TICKER}_financial_analysis.csv"
with open(csv_path, "w") as f:
    for name, df in [
        ("Income Statement", income), ("Balance Sheet", balance), ("Cash Flow", cashflow),
        ("Ratios", ratios), ("DCF Summary", dcf_summary),
    ]:
        f.write(f"### {name} ###\n")
        df.to_csv(f)
        f.write("\n\n")

print("Artifacts written:")
print(" -", xlsx_path)
print(" -", csv_path)
print()
print(f"Recommendation for {TICKER}: {recommendation}")
print(f"  Intrinsic / share: ${intrinsic_per_share:,.2f}")
print(f"  Current price:     ${current_price:,.2f}")
```

## After running
1. Record the artifact paths in shared memory with `write_to_shared_memory(key="artifact:financial-analysis", value="<path>")`.
2. In your final response, summarise the recommendation, the 3-5 most decisive ratios, and the key DCF assumptions — the artifact has the rest.

## Tips
- For peer comparison, repeat the `yf.Ticker(t).info` lookup over a list of peers and assemble into a DataFrame; only fall back to `web_search` if a metric is genuinely missing.
- For sensitivity analysis, wrap the DCF block in a function and sweep `discount_rate` / `terminal_growth` over a grid — write the resulting matrix as another sheet.
- Pair with the **data-vulgariser** skill when the user wants a plain-English summary of the recommendation.
