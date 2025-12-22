# Pipeline Scripts

Checkpoint scripts for processing participant submissions. Each script represents a discrete step in the workflow and logs its operations to a manifest file for traceability.

See [../PIPELINE.md](../../PIPELINE.md) for the full protocol.

## Environment

The `CHAT_PARSER_SECRET` environment variable is required for `parse_submission.py` when sanitization is enabled. See [PIPELINE.md](../PIPELINE.md#quick-start) for setup instructions (supports both environment variables and `.env` file).

## Scripts

### validate_submission.py

Validates and extracts a submission zip file.

```bash
./validate_submission.py <zip_file> [--output-dir <dir>] [--manifest-dir <dir>]
```

Exit codes: 0 (success), 1 (validation failure), 2 (system error)

### grade_submission.py

Runs the grader on a validated submission.

```bash
./grade_submission.py <participant_id> <tool> --data-dir <dir> [--grader-dir <dir>]
```

Output: `{PID}_tool_X_results.json`

### parse_submission.py

Extracts interaction metrics and sanitizes chat logs.

```bash
./parse_submission.py <participant_id> <tool> --data-dir <dir> [--no-sanitize]
```

Output: `{PID}_tool_X_metrics.json`, `chats/sanitized_*.json`

### combine_participant.py

Merges grading results with interaction metrics.

```bash
./combine_participant.py <participant_id> <tool> --data-dir <dir>
```

Output: `{PID}_tool_X_combined.json`

### add_to_dataset.py

Appends a participant row to the dataset.

```bash
./add_to_dataset.py <participant_id> <tool> --data-dir <dir>
```

### validate_dataset.py

Validates dataset integrity against manifest.

```bash
./validate_dataset.py --data-dir <dir> [--verbose]
```

## Manifest

Each sub-study has a `pipeline_manifest.json` tracking all operations with:
- Timestamps
- Input/output checksums
- Status and warnings

This enables error tracing and re-processing from any checkpoint.
