---
name: file-manager
description: Navigate, organize, search, and manipulate files in the E2B sandbox filesystem using ls, glob, grep, read_file, write_file, and edit_file
---

# File Manager

## Overview
Full filesystem access to the E2B sandbox. Use the built-in tools to explore directory trees, find files by pattern, search inside files, read, write, and edit content.

## When to Use
- Listing what files are in the sandbox
- Finding a file by name or content
- Reading, creating, or editing files
- Organizing the workspace

## Tool Reference

| Task | Tool | Example |
|------|------|---------|
| List directory | `ls` | `ls("/home/user/workspace")` |
| Find files by name | `glob` | `glob("*.csv", "/home/user")` |
| Search inside files | `grep` | `grep("error", "/home/user/workspace")` |
| Read a file | `read_file` | `read_file("/home/user/workspace/notes.txt")` |
| Create a file | `write_file` | `write_file("/home/user/workspace/out.txt", "hello")` |
| Edit a file | `edit_file` | `edit_file("/path/file.txt", "old text", "new text")` |
| Run shell command | `execute` | `execute("du -sh /home/user/workspace")` |

## Common Patterns

### Explore the sandbox root
```
ls("/home/user")
```

### Find all Python files
```
glob("*.py", "/home/user/workspace")
```

### Search for a keyword across all files
```
grep("TODO", "/home/user/workspace", glob="*.py")
```

### Disk usage
```
execute("du -sh /home/user/workspace/*")
```

### Create a directory
```
execute("mkdir -p /home/user/workspace/output")
```
