# Pipeline Scripts

Checkpoint scripts for processing participant submissions. Each script represents a discrete step in the workflow and logs operations to a manifest file for traceability.

See [../PIPELINE.md](../PIPELINE.md) for the complete protocol and workflow.

## Overview

- **validate_submission.py** - Validates zip structure and naming format, extracts to workspace root
- **grade_submission.py** - Runs grader, outputs results JSON to dataset repo and TXT to workspace root
- **parse_submission.py** - Extracts interaction metrics, sanitizes chat logs
- **combine_participant.py** - Merges grading results with interaction metrics
- **add_to_dataset.py** - Appends row to platform-level dataset CSV
- **validate_dataset.py** - Validates dataset integrity against manifest (submission-agnostic)
- **inspect_submission.py** - Inspects processing history from manifest

## Quick Start

### validate_submission.py

```bash
# Validate and extract submission
./validate_submission.py P001_S1_copilot_apm_submission.zip

# View full usage
./validate_submission.py --help
```

### grade_submission.py

```bash
# Grade a validated submission
./grade_submission.py P001_S1_copilot_apm_submission

# View full usage
./grade_submission.py --help
```

### parse_submission.py

```bash
# Extract metrics and sanitize chats
./parse_submission.py P001_S1_copilot_apm_submission

# Extract metrics only (skip sanitization)
./parse_submission.py P001_S1_copilot_apm_submission --no-sanitize

# View full usage
./parse_submission.py --help
```

### combine_participant.py

```bash
# Combine results and metrics
./combine_participant.py P001_S1_copilot_apm_submission

# View full usage
./combine_participant.py --help
```

### add_to_dataset.py

```bash
# Add to dataset
./add_to_dataset.py P001_S1_copilot_apm_submission

# View full usage
./add_to_dataset.py --help
```

### validate_dataset.py

```bash
# Validate dataset for a platform
./validate_dataset.py --platform copilot

# Verbose output
./validate_dataset.py --platform copilot --verbose

# View full usage
./validate_dataset.py --help
```

### inspect_submission.py

```bash
# Inspect processing history
./inspect_submission.py P001_S1_copilot_apm

# JSON output
./inspect_submission.py P001_S1_copilot_apm --json

# View full usage
./inspect_submission.py --help
```

## Workspace Auto-Detection

All scripts automatically detect the workspace root by locating:
- `bsc-apm-case-study-task/`
- `bsc-apm-case-study-data/`
- `eclass-mcp-server/`
- `openeclass/`

No path arguments are required.

## Submission Format

All scripts expect submission format: `{PID}_{S1|2}_{Platform}_{Tool}_submission.zip`

Example: `P001_S1_copilot_apm_submission.zip`

## Environment Variables

- **CHAT_PARSER_SECRET** - Required for `parse_submission.py` when sanitization is enabled. Must be the same for both encrypt and decrypt operations. Can be set via environment variable or `.env` file. See [PIPELINE.md](../PIPELINE.md#quick-start) for setup.

## Manifest

Each platform maintains a `pipeline_manifest.json` at `submissions_sanitized/{platform}/` tracking all operations with timestamps, checksums, status, and warnings.

Manifest key format: `{PID}_{S1|2}_{Platform}_{Tool}` (e.g., `P001_S1_copilot_apm`)

See [manifest.py](manifest.py) for manifest operations and structure.

## Documentation

For detailed usage, command-line options, and output formats, see:
- Script help: `./<script_name> --help`
- Source code docstrings: See function documentation in each script file
- Full protocol: [PIPELINE.md](../PIPELINE.md)
