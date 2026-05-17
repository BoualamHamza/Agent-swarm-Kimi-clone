---
name: python-runner
description: INVOKE whenever you need to execute Python in the sandbox — calculations, scripts, ad-hoc verification. CRITICAL — each run_python call is a fresh interpreter; variables do NOT persist across calls. Persist state by writing to /home/user/workspace/. Triggers — "run Python", "execute script", "compute", "simulate", "build a model".
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
