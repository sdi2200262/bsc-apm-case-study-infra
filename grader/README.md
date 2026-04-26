# Grader

Black-box testing suite for evaluating participant submissions.
Replicates the production environment with a local OpenEclass
instance and an HTTPS mock SSO redirect so that submissions are
graded under the same conditions participants worked against.

## Overview

The grader applies a participant's submission as a git patch on top
of pinned baselines, builds and runs the resulting code in the
replica environment, and scores the result against a 100-point
rubric covering Python baseline preservation, Python features, and
the C replica.

## Quick Start

```bash
# Start services (first time: see SETUP.md)
docker start grader_db_1 grader_eclass_1

# Test baseline (no patch)
./grade --no-patch

# Grade a patch file
./grade <patch_file>

# Browse grading results JSON in the terminal
./inspect.py <results.json>

# Full options
./grade --help
```

## Architecture

The grader evaluates submissions as git patches applied against
pinned baseline repositories:

- `eclass-mcp-server` at commit `8b4e39c`
- `openeclass` at commit `e8b3329` (Docker image `openeclass:test`)

Tests cover Python baseline preservation (12 points), Python
features (36 points), and the C replica (52 points). The baseline
score (no patch applied) is **12/100**.

See source-code docstrings in `src/` for detailed test specifications.

## Directory Structure

```
grader/
├── grade                       # Grading entry point
├── inspect.py                  # Results browser
├── docker-compose.eclass.yaml  # Replica environment composition
├── src/                        # Core grading modules
│   ├── patch_manager.py        # Git operations for patches
│   ├── build_tester.py         # Build verification
│   ├── protocol_tester.py      # MCP protocol and tool tests
│   ├── memory_tester.py        # Valgrind memory tests
│   ├── mock_server.py          # CAS authentication mock
│   ├── eclass_manager.py       # OpenEclass availability checks
│   ├── scorer.py               # Point allocation
│   └── report.py               # Report generation
├── fixtures/                   # SSO mock HTML fixtures
├── README.md
└── SETUP.md
```

## Documentation

- **[SETUP.md](SETUP.md)**: environment setup and prerequisites.
- **Source code docstrings**: detailed API documentation in `src/`
  modules.

## Related

- **[../parser/](../parser/)**: transcript parser; metric extraction
  from participant Claude Code session logs.
- **[../pipeline/](../pipeline/)**: submission processing pipeline;
  orchestrates validation, grading, parsing, and dataset aggregation.
- **[Task Specification](../task/)**: submission requirements and
  scoring rubric.
