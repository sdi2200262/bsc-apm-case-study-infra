# Data Processing Pipeline

Protocol for processing participant submissions from collection to aggregated datasets.

## Overview

The pipeline transforms raw participant submissions into:
- Grading scores per submission
- Interaction metrics from AI assistant logs
- Sanitized (encrypted) chat exports
- Aggregated datasets for statistical analysis

Processing is incremental and traceable. Each operation is logged in a manifest file with checksums and timestamps, enabling error recovery and audit trails.

## Prerequisites

- Python 3.10+
- Docker with docker compose v2 (for grading)
- `CHAT_PARSER_SECRET` environment variable (for sanitization)
- Workspace directory structure with:
  - `bsc-apm-case-study-task/` (this repository)
  - `bsc-apm-case-study-data/` (data repository)
  - `eclass-mcp-server/` (baseline repository)
  - `openeclass/` (OpenEclass source)

See [SETUP.md](SETUP.md) for complete setup instructions.

## Submission Format

Submissions follow format: `{PID}_{S1|2}_{Platform}_{Tool}_submission.zip`

- `{PID}` - Participant ID (e.g., `P001`)
- `{S1|2}` - Session number (`S1` = first tool, `S2` = second tool)
- `{Platform}` - `copilot` or `cursor`
- `{Tool}` - Tool identifier (`apm`, `spec-kit`, `cursor-plan`, `copilot-plan`)

Example: `P001_S1_copilot_apm_submission.zip`

Contents:
- `{PID}_{S1|2}_{Platform}_{Tool}_solution.patch`
- `{PID}_{S1|2}_{Platform}_{Tool}_logs/chats/*.{json|md}`
- (Cursor only) `{PID}_{S1|2}_{Platform}_{Tool}_logs/stats/*.csv`

## Processing Steps

The pipeline processes submissions through discrete stages:

1. **Validate** - Zip structure and naming format validation, extraction to workspace root
2. **Grade** - Automated grading with result tracking
3. **Parse** - Interaction metric extraction and chat sanitization
4. **Combine** - Merge grading results with metrics
5. **Add to Dataset** - Append to platform-level CSV
6. **Validate Dataset** - Integrity checks against manifest

Each stage is checkpointed in the manifest for error recovery. See [pipeline/README.md](pipeline/README.md) for script usage.

## Workspace Structure

The pipeline uses workspace auto-detection to find required directories:

```
workspace/
├── bsc-apm-case-study-task/    # This repository
│   └── grader/
│       └── pipeline/
├── bsc-apm-case-study-data/    # Data repository
│   └── submissions_sanitized/
│       ├── copilot/
│       │   ├── pipeline_manifest.json
│       │   ├── dataset.csv
│       │   └── {PID}/
│       │       └── S{S1|2}_{tool}/
│       └── cursor/
├── eclass-mcp-server/           # eClass MCP Server repository
└── openeclass/                  # Local openeclass repository
```

Scripts automatically detect the workspace root by searching for these directories. Run scripts from anywhere within the workspace.

## Quick Start

Set the encryption secret via environment variable or `.env` file:

```bash
export CHAT_PARSER_SECRET='your-key'
```

Process a submission:

```bash
cd bsc-apm-case-study-task/grader/pipeline

# Step 1: Validate and extract
./validate_submission.py P001_S1_copilot_apm_submission.zip

# Step 2: Grade
./grade_submission.py P001_S1_copilot_apm_submission

# Step 3: Parse metrics
./parse_submission.py P001_S1_copilot_apm_submission

# Step 4: Combine results
./combine_participant.py P001_S1_copilot_apm_submission

# Step 5: Add to dataset
./add_to_dataset.py P001_S1_copilot_apm_submission

# Step 6: Validate integrity
./validate_dataset.py --platform copilot
```

All scripts accept unpacked submission directory path (except `validate_submission.py` which takes zip, and `validate_dataset.py`/`inspect_submission.py` which are submission-agnostic).

See [pipeline/README.md](pipeline/README.md) for detailed usage and options.

## Data Repository Structure

Processed data is stored in `bsc-apm-case-study-data/submissions_sanitized/{platform}/`:

```
submissions_sanitized/
├── copilot/
│   ├── pipeline_manifest.json    # Audit trail for all operations
│   ├── dataset.csv                # Aggregated dataset
│   └── {PID}/
│       └── S{S1|2}_{tool}/
│           ├── {PID}_{S1|2}_{platform}_{tool}_solution.patch
│           ├── {PID}_{S1|2}_{platform}_{tool}_results.json
│           ├── {PID}_{S1|2}_{platform}_{tool}_metrics.json
│           ├── {PID}_{S1|2}_{platform}_{tool}_combined.json
│           └── chats/
│               └── sanitized_*.json
└── cursor/
    └── (same structure)
```

The `pipeline_manifest.json` file tracks all operations with checksums and timestamps, enabling validation at each checkpoint and error recovery.

## Manifest

Each platform maintains a manifest at `submissions_sanitized/{platform}/pipeline_manifest.json`. Manifest entries use key format: `{PID}_{S1|2}_{Platform}_{Tool}` (e.g., `P001_S1_copilot_apm`).

Use `inspect_submission.py` to view processing history for any submission. See [pipeline/README.md](pipeline/README.md) for manifest inspection.

## OpenEclass Background Process

OpenEclass must be running in the background for grading to function. Start services per [SETUP.md](SETUP.md):

```bash
docker start grader_db_1 grader_eclass_1
```

## Related

- [pipeline/README.md](pipeline/README.md) - Pipeline script usage and options
- [scripts/README.md](scripts/README.md) - Parser and viewer utilities
- [SETUP.md](SETUP.md) - Grader environment setup
