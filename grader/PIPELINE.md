# Data Processing Pipeline

Protocol for processing participant submissions from collection to aggregated datasets.

## Overview

The pipeline transforms raw participant submissions into:
- Grading scores per submission
- Interaction metrics from AI assistant logs
- Sanitized (encrypted) chat exports
- Aggregated datasets for statistical analysis

Processing is incremental and traceable. Each operation is logged in a manifest file with checksums and timestamps, enabling error recovery and audit trails.

## Sub-Studies

| Sub-Study | IDE | Chat Format | Extra Artifacts |
|-----------|-----|-------------|-----------------|
| Cursor | Cursor | Markdown | Token usage CSV |
| Copilot | VS Code + GitHub Copilot | JSON | — |

Each sub-study maintains separate manifest and dataset files.

## Prerequisites

- Python 3.10+
- Docker with docker compose v2 (for grading)
- `CHAT_PARSER_SECRET` environment variable (for sanitization)
- Workspace directory structure with:
  - `bsc-apm-case-study-task/` (this repository)
  - `bsc-apm-case-study-data/` (data repository)
  - `eclass-mcp-server/` (baseline repository)
  - `openeclass/` (OpenEclass source)

## Submission Format

Participants submit: `{PID}_tool_{a|b}_submission.zip`

Contents:
- `{PID}_tool_{a|b}_solution.patch`
- `{PID}_tool_{a|b}_logs/chats/*.{json|md}`
- (Cursor only) `{PID}_tool_{a|b}_logs/stats/*.csv`

## Processing Steps

For each submission:

```mermaid
flowchart LR
    A[Download submission zip] --> B[validate_submission.py]
    B --> C[grade_submission.py]
    C --> D[parse_submission.py]
    D --> E[combine_participant.py]
    E --> F[add_to_dataset.py]
    F --> G[Commit to data repository]
```

| Step | Script | Output |
|------|--------|--------|
| Validate | `validate_submission.py` | Extracted submission folder |
| Grade | `grade_submission.py` | `{PID}_tool_X_results.json` |
| Parse | `parse_submission.py` | `{PID}_tool_X_metrics.json` + sanitized chats |
| Combine | `combine_participant.py` | `{PID}_tool_X_combined.json` |
| Add | `add_to_dataset.py` | Updated `dataset.csv` |

## Workspace Structure

The pipeline uses workspace auto-detection to find all required directories. Your workspace should have this structure:

```
workspace/
├── bsc-apm-case-study-task/    # This repository
│   └── grader/
│       └── scripts/pipeline/
├── bsc-apm-case-study-data/    # Data repository
│   └── submissions_sanitized/
│       ├── copilot/
│       │   ├── pipeline_manifest.json
│       │   ├── dataset.csv
│       │   └── P001/
│       └── cursor/
├── eclass-mcp-server/          # Baseline repository
└── openeclass/                  # OpenEclass source
```

The pipeline automatically detects the workspace root by searching for these directories. You can run scripts from anywhere within the workspace, and they will find the correct paths.

## Quick Start

Set the encryption secret either via environment variable or `.env` file:

```bash
# Option 1: Export environment variable
export CHAT_PARSER_SECRET='your-key'

# Option 2: Use .env file (recommended)
cp .env.example .env
# Edit .env and set CHAT_PARSER_SECRET=your-key
```

Then process a submission from your workspace root:

```bash
# All paths auto-detected from workspace!
cd bsc-apm-case-study-task/grader/scripts/pipeline

# Step 1: Validate and extract submission
./validate_submission.py P001_tool_a_submission.zip

# Step 2: Grade the submission (extracts P001 and 'a' from zip filename)
./grade_submission.py P001 a

# Step 3: Parse chat logs and extract metrics
./parse_submission.py P001 a

# Step 4: Combine grading results with metrics
./combine_participant.py P001 a

# Step 5: Add to aggregated dataset
./add_to_dataset.py P001 a

# Step 6: Verify integrity
./validate_dataset.py --sub-study copilot
```

**Note:** The participant ID (`P001`) and tool (`a`) are extracted from the zip filename `P001_tool_a_submission.zip`. All subsequent steps use these values.

**Note:** All path arguments (`--data-dir`, `--grader-dir`, `--eclass-dir`, `--output-dir`) are now optional and will be auto-detected from the workspace structure. You can still specify them manually if needed.

### Manual Path Override

If auto-detection fails or you need to override paths:

```bash
# Specify paths manually
./validate_submission.py P001_tool_a_submission.zip \
    --output-dir /custom/path/P001/tool_a \
    --workspace-dir /custom/workspace

# For subsequent steps, extract participant ID and tool from zip filename:
# P001_tool_a_submission.zip -> P001, a
./grade_submission.py P001 a \
    --data-dir /custom/data/copilot \
    --grader-dir /custom/grader \
    --eclass-dir /custom/eclass-mcp-server
```

## Data Repository Structure

The pipeline stores all processed data in `bsc-apm-case-study-data/submissions_sanitized/`:

```
bsc-apm-case-study-data/
└── submissions_sanitized/
    ├── cursor/
    │   ├── pipeline_manifest.json    # Audit trail for all operations
    │   ├── dataset.csv                # Aggregated dataset
    │   └── P001/
    │       └── tool_a/
    │           ├── P001_tool_a_solution.patch
    │           ├── P001_tool_a_results.json
    │           ├── P001_tool_a_metrics.json
    │           ├── P001_tool_a_combined.json
    │           └── P001_tool_a_logs/
    │               └── chats/
    │                   └── sanitized_*.json
    └── copilot/
        └── (same structure)
```

The `pipeline_manifest.json` file in each sub-study directory tracks all operations with checksums and timestamps, enabling validation at each checkpoint and error recovery.

## Related

- [Scripts README](scripts/README.md) — Parser and viewer utilities
- [SETUP.md](SETUP.md) — Grader environment setup
