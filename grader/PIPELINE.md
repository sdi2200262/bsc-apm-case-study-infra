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
- Access to `bsc-apm-case-study-data` repository

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

## Quick Start

```bash
export CHAT_PARSER_SECRET='your-key'

# Process a submission
./scripts/pipeline/validate_submission.py P001_tool_a_submission.zip --output-dir /data/copilot/P001/tool_a
./scripts/pipeline/grade_submission.py P001 a --data-dir /data/copilot
./scripts/pipeline/parse_submission.py P001 a --data-dir /data/copilot
./scripts/pipeline/combine_participant.py P001 a --data-dir /data/copilot
./scripts/pipeline/add_to_dataset.py P001 a --data-dir /data/copilot

# Verify integrity
./scripts/pipeline/validate_dataset.py --data-dir /data/copilot
```

## Data Repository Structure

```
submissions_sanitized/
├── cursor/
│   ├── pipeline_manifest.json
│   ├── dataset.csv
│   └── P001/
│       └── tool_a/
│           ├── *.patch
│           ├── *_results.json
│           ├── *_metrics.json
│           ├── *_combined.json
│           └── chats/sanitized_*.json
└── copilot/
    └── (same structure)
```

## Related

- [Scripts README](scripts/README.md) — Parser and viewer utilities
- [SETUP.md](SETUP.md) — Grader environment setup
- [Scoring Rubric](../task/SCORING.md) — Grading point allocation
