# Scoring Rubric

Total: 48 points

## Python Baseline (12 points)

Tests existing functionality from the `main` branch. Participants should not break these.

| ID | Points | Description |
|----|--------|-------------|
| B1 | 2 | Python dependency installation (`uv sync` or `pip install -e .`) |
| P1 | 1 | `initialize` response structure correct |
| P2 | 1 | `tools/list` returns required tools |
| L1 | 1 | Successful login |
| L2 | 1 | Already logged in handling |
| L3 | 1 | Missing credentials error |
| O1 | 1 | Successful logout |
| O2 | 1 | Logout when not logged in |
| C1 | 1 | Get courses when logged in |
| C2 | 1 | Get courses when not logged in (error) |
| A1 | 1 | Authstatus when not logged in |

## Python Feature (12 points)

Tests the new `get_course_announcements` tool implementation.

| ID | Points | Description |
|----|--------|-------------|
| AN1 | 2 | Not logged in: exact string `"Error: Not logged in."` |
| AN2 | 2 | Invalid URL: exact string `"Error: Could not extract course code."` |
| AN3 | 2 | No announcements: exact string `"No announcements found."` |
| AN4 | 3 | Valid announcements with default `days_back=30` |
| AN5 | 3 | Valid announcements with custom `days_back` |

### Exact String Requirements

Per the specification, these exact strings are required:
- `"Error: Not logged in."`
- `"Error: Could not extract course code."`
- `"No announcements found."`

### Output Format (AN4, AN5)

Expected format when announcements are found:
```
Found [N] announcement(s):

1. [Title]
    Date: [Date String]
    Content: [Content...]

2. ...
```

## C Replica (24 points)

Tests the C implementation of the full MCP server.

| ID | Points | Description |
|----|--------|-------------|
| B2 | 3 | `make c-server` compiles and produces `server` binary |
| M1 | 3 | Valgrind clean (0 definitely lost, 0 indirectly lost) |
| P1_c | 1 | `initialize` response structure correct |
| P2_c | 1 | `tools/list` returns required tools |
| L1_c | 1 | Successful login |
| L2_c | 1 | Already logged in handling |
| L3_c | 1 | Missing credentials error |
| O1_c | 1 | Successful logout |
| O2_c | 1 | Logout when not logged in |
| C1_c | 1 | Get courses when logged in |
| C2_c | 1 | Get courses when not logged in (error) |
| A1_c | 1 | Authstatus when not logged in |
| AN1_c | 2 | Not logged in error |
| AN2_c | 2 | Invalid course URL error |
| AN3_c | 1 | No announcements found |
| AN4_c | 2 | Valid announcements with default `days_back` |
| AN5_c | 1 | Valid announcements with custom `days_back` |

## Expected Scores

| Submission Type | Python Baseline | Python Feature | C Replica | Total |
|-----------------|-----------------|----------------|-----------|-------|
| No patch (baseline) | 12/12 | 0/12 | 0/24 | 12/48 |
| Python implementation only | 12/12 | 12/12 | 0/24 | 24/48 |
| Complete implementation | 12/12 | 12/12 | 24/24 | 48/48 |
| Broken baseline | <12/12 | varies | varies | varies |

## Interpreting Results

- **Baseline regression**: If Python Baseline < 12, the patch broke existing functionality.
- **Partial feature**: If Python Feature between 1-11, the feature is partially implemented.
- **Missing C replica**: If B2 fails, no c-replica/ directory or Makefile issue.
- **Memory issues**: If M1 fails, memory leaks detected in C implementation.
