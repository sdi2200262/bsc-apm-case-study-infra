# Grading & Data Processing Infrastructure

Black-box testing suite and data processing pipeline for evaluating participant submissions. Replicates production environment with local OpenEclass instance and HTTPS mock SSO redirect.

## Overview

This infrastructure provides:

- **Automated grading** - Black-box tests against Python and C implementations
- **Data processing pipeline** - Submission validation, metric extraction, sanitization, and dataset aggregation
- **Audit trails** - Manifest-based tracking with checksums for reproducibility

## Quick Start

```bash
# Start services (first time: see SETUP.md)
docker start grader_db_1 grader_eclass_1

# Test baseline (no patch)
./grade --no-patch

# Grade a patch file
./grade <patch_file>

# View options
./grade --help
```

For pipeline usage, see [PIPELINE.md](PIPELINE.md).

## Architecture

### Grading System

The grader evaluates submissions as git patches applied against baseline repositories:
- `eclass-mcp-server` at commit `8b4e39c`
- `openeclass` at commit `e8b3329` (Docker image `openeclass:test`)

Tests cover Python baseline (12 points), Python features (36 points), and C replica (52 points). Baseline score (no patch): **12/100**.

See source code docstrings in `src/` for detailed test specifications.

### Data Processing Pipeline

The pipeline processes submissions through discrete stages: validation, grading, parsing, combination, dataset aggregation, and integrity validation. Each stage is checkpointed in the manifest for error recovery.

See [PIPELINE.md](PIPELINE.md) for complete protocol and submission format.

## Directory Structure

```
grader/
├── grade                        # Grading entry point
├── src/                         # Core grading modules
│   ├── patch_manager.py        # Git operations for patches
│   ├── build_tester.py          # Build verification
│   ├── protocol_tester.py       # MCP protocol and tool tests
│   ├── memory_tester.py         # Valgrind memory tests
│   ├── mock_server.py           # CAS authentication mock
│   ├── eclass_manager.py        # OpenEclass availability checks
│   ├── scorer.py                # Point allocation
│   └── report.py                # Report generation
├── scripts/                     # Grader utility scripts
│   ├── copilot_chat_parser.py  # Copilot chat analyzer
│   ├── cursor_chat_parser.py   # Cursor chat analyzer
│   └── results_viewer.py       # Results browser
├── pipeline/                    # Pipeline infrastructure
│   ├── validate_submission.py  # Validation and extraction
│   ├── grade_submission.py     # Automated grading
│   ├── parse_submission.py     # Metric extraction
│   ├── combine_participant.py  # Result merging
│   ├── add_to_dataset.py       # Dataset aggregation
│   ├── validate_dataset.py     # Integrity validation
│   ├── inspect_submission.py   # Manifest inspection
│   ├── workspace.py            # Workspace detection
│   └── manifest.py             # Manifest operations
├── fixtures/                    # SSO mock HTML fixtures
├── PIPELINE.md                  # Pipeline protocol documentation
└── SETUP.md                     # Environment setup
```

## Documentation

- **[SETUP.md](SETUP.md)** - Environment setup and prerequisites
- **[PIPELINE.md](PIPELINE.md)** - Data processing pipeline protocol
- **[scripts/README.md](scripts/README.md)** - Utility script usage
- **[pipeline/README.md](pipeline/README.md)** - Pipeline script usage
- **Source code docstrings** - Detailed API documentation in `src/` modules

## Related

- [Task Specification](../task/) - Submission requirements
- [Scoring Rubric](../task/SCORING.md) - Test-by-test point allocation
