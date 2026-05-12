---
name: python-runner
description: Write and execute Python scripts inside the E2B sandbox, capturing stdout/stderr output
---

# Python Runner

## Overview
Execute Python code directly inside the sandboxed environment. The sandbox has Python 3.12 and common libraries pre-installed.

## When to Use
- User asks to run, test, or demonstrate Python code
- You need to compute something programmatically
- You want to verify logic before explaining it

## Available Libraries
`pandas`, `numpy`, `matplotlib`, `scipy`, `requests`, `beautifulsoup4`, `tabulate`

## Instructions

### Pattern: write-then-run
1. Use `write_file` to save the script to `/home/user/workspace/<name>.py`
2. Use `execute` to run it: `python /home/user/workspace/<name>.py`
3. Show the output to the user

### Example
```
write_file("/home/user/workspace/fib.py", "for i in range(10): print(i)")
execute("python /home/user/workspace/fib.py")
```

### Pattern: one-liner
For short expressions, use `execute` directly:
```
execute("python -c \"import math; print(math.factorial(10))\"")
```

### Tips
- Always check exit_code from execute; non-zero means an error occurred
- Use `/home/user/workspace/` as the working directory for scripts
- Print results explicitly — the agent only sees stdout/stderr
