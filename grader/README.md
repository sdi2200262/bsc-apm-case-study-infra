# Grading & Data Processing Suite

Black-box testing suite and data processing pipeline for evaluating participant submissions against the task specification. The grader replicates the production environment by running a local `openeclass` instance and an HTTPS mock SSO redirect. The pipeline scripts handle submission validation, metric extraction, sanitization, and dataset aggregation.

## Overview

### Grading

This grader evaluates submissions against:
- **Python implementation** - the eclass-mcp-server baseline and new features
- **C replica** - a high-performance native C implementation

Submissions are provided as git patch files applied against the baseline `eclass-mcp-server` repository. "Baseline" refers to commit `8b4e39c` without any patch.

## Quick Start

```bash
# Start services (first time: see SETUP.md)
docker start grader_db_1 grader_eclass_1

# Test baseline (no patch)
./grade --no-patch

# Grade a submission
./grade <patch_file>

# Options
./grade patch.patch --verbose    # Show test details
./grade patch.patch --debug      # Debug server communication
./grade patch.patch --no-cleanup # Keep git branch after grading
```

## Output

- `results_<patch>.json` - Complete machine-parsable report
- `results_<patch>.txt` - Human-readable report
- Console summary

## Baseline Score

Running on clean `main` branch (commit `8b4e39c`) without any patch:

| Category | Score | Description |
|----------|-------|-------------|
| Python Baseline | 12/12 | Existing tools (login, logout, get_courses, authstatus) |
| Python Feature | 0/12 | get_course_announcements (not implemented in baseline) |
| C Replica | 0/24 | Full C implementation (not present in baseline) |

**Total: 12/48** 

## Directory Structure

```
grader/
├── grade                        # Entry point script
├── PIPELINE.md                  # Data processing pipeline documentation
├── SETUP.md                     # Environment setup instructions
├── docker-compose.eclass.yaml   # OpenEclass Docker config
├── sso_cert.pem                 # SSL certificate (generated, see SETUP.md)
├── sso_key.pem                  # SSL private key (generated, see SETUP.md)
├── src/                         # Grading modules
│   ├── __init__.py
│   ├── build_tester.py          # Build verification
│   ├── eclass_manager.py        # OpenEclass availability checks
│   ├── memory_tester.py         # Valgrind memory tests (C)
│   ├── mock_server.py           # CAS authentication mock
│   ├── patch_manager.py         # Git operations
│   ├── protocol_tester.py       # MCP protocol and tool tests
│   ├── report.py                # Report generation
│   └── scorer.py                # Point allocation and aggregation
├── fixtures/                    # HTML fixtures for SSO mock
│   ├── sso_login.html
│   └── sso_login_error.html
├── scripts/                     # Utility scripts
│   ├── README.md                # Scripts documentation
│   ├── copilot_chat_parser.py   # Chat export analyzer with sanitization
│   ├── cursor_chat_parser.py    # Cursor chat analyzer with sanitization
│   ├── results_viewer.py        # Results JSON browser
│   └── pipeline/                # Data processing pipeline scripts
│       ├── README.md            # Pipeline scripts documentation
│       └── *.py                 # See pipeline/README.md for details
```

### Data Processing Pipeline

For processing participant submissions from collection through to final datasets, see [PIPELINE.md](PIPELINE.md). The pipeline provides:

- **Workspace auto-detection** - Automatically finds all required directories
- Submission validation and extraction
- Automated grading with result tracking
- Chat log parsing and metric extraction
- PII sanitization via reversible encryption
- Incremental dataset building with audit trails
- **Checkpoint validation** - Verify data integrity at each step via manifest

The pipeline automatically detects your workspace structure and finds manifests in `bsc-apm-case-study-data/submissions_sanitized/{sub_study}/pipeline_manifest.json` for tracking and validation.

## System Requirements

- Ubuntu 22.04+ (or similar Linux)
- Python 3.10+ with `uv` or `pip`
- Docker with docker compose v2
- For C tests: `libcurl-dev`, `libxml2-dev`, `valgrind`

See [SETUP.md](SETUP.md) for complete setup instructions.

## Related

- [Task Specification](../task/) - What submissions are implementing
- [Scoring Rubric](../task/SCORING.md) - Detailed test-by-test point allocation
