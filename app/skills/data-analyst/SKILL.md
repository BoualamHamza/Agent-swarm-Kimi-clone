---
name: data-analyst
description: Analyze datasets using pandas and numpy inside the sandbox, produce statistics, charts, and insights
---

# Data Analyst

## Overview
Load, clean, and analyze structured data (CSV, JSON, Excel) using pandas and numpy. Generate summary statistics, correlations, and matplotlib visualizations saved as files.

## When to Use
- User provides a data file or asks for data analysis
- Computing descriptive statistics, aggregations, or trends
- Creating charts or visualizations

## Instructions

### Step 1 — Upload or locate the data
- If the user provides a file, use `write_file` to place it in `/home/user/workspace/data/`
- Confirm with `ls("/home/user/workspace/data/")`

### Step 2 — Write the analysis script
Save to `/home/user/workspace/analysis.py`. Always include:
```python
import pandas as pd
import numpy as np

df = pd.read_csv("/home/user/workspace/data/file.csv")
print(df.shape)
print(df.describe())
print(df.dtypes)
```

### Step 3 — Run and interpret
```
execute("python /home/user/workspace/analysis.py")
```

### Step 4 — Save charts
```python
import matplotlib
matplotlib.use("Agg")          # headless mode — required in sandbox
import matplotlib.pyplot as plt

df["column"].hist()
plt.savefig("/home/user/workspace/chart.png")
```

### Tips
- Always use `matplotlib.use("Agg")` before importing pyplot — the sandbox has no display
- Use `tabulate` for readable table output: `print(tabulate(df.head(), headers="keys"))`
- Pair with the **data-vulgariser** skill to translate results for non-technical users
