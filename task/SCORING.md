# Scoring Rubric

Total: 100 points

## Python Implementation (48 points)

### Baseline (12 points)

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

### Feature: Course Announcements (18 points)

Tests the `get_course_announcements` tool implementation.

| ID | Points | Description |
|----|--------|-------------|
| AN1 | 3 | Not logged in: exact string `"Error: Not logged in."` |
| AN2 | 3 | Invalid URL: exact string `"Error: Could not extract course code."` |
| AN3 | 3 | No announcements: exact string `"No announcements found."` |
| AN4 | 3 | Valid announcements with default `days_back=30` |
| AN5 | 3 | Valid announcements with custom `days_back` |
| AN6 | 3 | Invalid `days_back`: exact string `"Error: days_back must be a positive integer."` |

### Feature: General Announcements (18 points)

Tests the `get_general_announcements` tool implementation.

| ID | Points | Description |
|----|--------|-------------|
| GAN1 | 3 | Not logged in error |
| GAN2 | 3 | Invalid `days_back` (<=0): exact string `"Error: days_back must be a positive integer."` |
| GAN3 | 3 | Invalid `days_back` (>30): exact string `"Error: Cannot retrieve announcements older than 30 days."` |
| GAN4 | 3 | No announcements: exact string `"No announcements found."` |
| GAN5 | 3 | Valid Aggregation (Contains System + Course source attribution) |
| GAN6 | 3 | Valid Filtering (Respects `days_back`) |

## C Replica Implementation (52 points)

Tests the C implementation of the full MCP server.

### Infrastructure (6 points)

| ID | Points | Description |
|----|--------|-------------|
| B2 | 3 | `make c-server` compiles and produces `server` binary |
| M1 | 3 | Valgrind clean (0 definitely lost, 0 indirectly lost) |

### Baseline (10 points)

Verifies standard protocol functionality in C.

| ID | Points | Description |
|----|--------|-------------|
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

### Feature: Course Announcements (18 points)

| ID | Points | Description |
|----|--------|-------------|
| AN1_c | 3 | Not logged in error |
| AN2_c | 3 | Invalid course URL error |
| AN3_c | 3 | No announcements found |
| AN4_c | 3 | Valid announcements with default `days_back` |
| AN5_c | 3 | Valid announcements with custom `days_back` |
| AN6_c | 3 | Invalid `days_back` error |

### Feature: General Announcements (18 points)

| ID | Points | Description |
|----|--------|-------------|
| GAN1_c | 3 | Not logged in error |
| GAN2_c | 3 | Invalid `days_back` (<=0) error |
| GAN3_c | 3 | Invalid `days_back` (>30) error |
| GAN4_c | 3 | No announcements found |
| GAN5_c | 3 | Valid Aggregation (System + Course) |
| GAN6_c | 3 | Valid Filtering |

## Expected Scores

| Submission Type | Python Baseline | Python Features | C Replica | Total |
|-----------------|-----------------|-----------------|-----------|-------|
| No patch (baseline) | 12/12 | 0/36 | 0/52 | 12/100 |
| Python implementation only | 12/12 | 36/36 | 0/52 | 48/100 |
| Complete implementation | 12/12 | 36/36 | 52/52 | 100/100 |