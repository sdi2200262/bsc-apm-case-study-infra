# Pipeline Scripts

Checkpoint scripts for processing participant submissions. Each script represents a discrete step in the workflow and logs its operations to a manifest file for traceability.

See [../PIPELINE.md](../../PIPELINE.md) for the full protocol.

## Workspace Auto-Detection

All scripts automatically detect the workspace root by looking for:
- `bsc-apm-case-study-task/`
- `bsc-apm-case-study-data/`
- `eclass-mcp-server/`
- `openeclass/`

Path arguments (`--data-dir`, `--grader-dir`, `--eclass-dir`, `--output-dir`) are **optional** and will be auto-detected from the workspace structure. You can override them manually if needed.

## Environment

The `CHAT_PARSER_SECRET` environment variable is required for `parse_submission.py` when sanitization is enabled. See [PIPELINE.md](../PIPELINE.md#quick-start) for setup instructions (supports both environment variables and `.env` file).

## Scripts

### validate_submission.py

Validates and extracts a submission zip file.

```bash
./validate_submission.py <zip_file> [--output-dir <dir>] [--manifest-dir <dir>] [--workspace-dir <dir>]
```

- Auto-detects workspace and extracts to `bsc-apm-case-study-data/submissions_sanitized/{sub_study}/{PID}/tool_{tool}/`
- Auto-detects sub-study from zip file contents
- Exit codes: 0 (success), 1 (validation failure), 2 (system error)

### grade_submission.py

Runs the grader on a validated submission.

```bash
./grade_submission.py <participant_id> <tool> [--data-dir <dir>] [--grader-dir <dir>] [--eclass-dir <dir>] [--workspace-dir <dir>]
```

**Example:** For `P001_tool_a_submission.zip`, use `./grade_submission.py P001 a`

- Auto-detects data directory from manifest
- Auto-detects grader directory from workspace
- Auto-detects eclass-mcp-server directory from workspace
- Output: `{PID}_tool_X_results.json`

### parse_submission.py

Extracts interaction metrics and sanitizes chat logs.

```bash
./parse_submission.py <participant_id> <tool> [--data-dir <dir>] [--workspace-dir <dir>] [--no-sanitize]
```

**Example:** For `P001_tool_a_submission.zip`, use `./parse_submission.py P001 a`

- Auto-detects data directory from manifest
- Output: `{PID}_tool_X_metrics.json`, `chats/sanitized_*.json`

### combine_participant.py

Merges grading results with interaction metrics.

```bash
./combine_participant.py <participant_id> <tool> [--data-dir <dir>] [--workspace-dir <dir>]
```

**Example:** For `P001_tool_a_submission.zip`, use `./combine_participant.py P001 a`

- Auto-detects data directory from manifest
- Output: `{PID}_tool_X_combined.json`

### add_to_dataset.py

Appends a participant row to the dataset.

```bash
./add_to_dataset.py <participant_id> <tool> [--data-dir <dir>] [--workspace-dir <dir>]
```

**Example:** For `P001_tool_a_submission.zip`, use `./add_to_dataset.py P001 a`

- Auto-detects data directory from manifest
- Updates `dataset.csv` in the data directory

### validate_dataset.py

Validates dataset integrity against manifest.

```bash
./validate_dataset.py [--data-dir <dir>] [--sub-study <copilot|cursor>] [--workspace-dir <dir>] [--verbose]
```

- Can use either `--data-dir` or `--sub-study` (with workspace auto-detection)
- Validates checksums, checks for duplicates, verifies manifest consistency

## Manifest

Each sub-study has a `pipeline_manifest.json` in `bsc-apm-case-study-data/submissions_sanitized/{sub_study}/` tracking all operations with:
- Timestamps
- Input/output checksums
- Status and warnings
- Sub-study detection

The manifest enables:
- **Auto-detection**: Scripts check the manifest to determine sub-study and find participant entries
- **Error tracing**: Track which operations succeeded/failed
- **Re-processing**: Resume from any checkpoint
- **Validation**: Verify data integrity at each step
