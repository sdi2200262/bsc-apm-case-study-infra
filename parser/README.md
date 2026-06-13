# Parser

Transcript parser for the case study. It reads the Claude Code CLI
rollout JSONL a participant session produces and emits the data and
metrics artifacts the analysis pipeline consumes.

## Overview

The package reads one or more `<sessionId>.jsonl` files (copied from
`~/.claude/projects/<dashed-cwd>/`), computes per-scope values (session,
phase, and role for APM submissions), and writes two artifacts.
`parser_data.json` holds what the data layer read, the token sums,
counts, session identity facts, and the per-call and per-turn series.
`parser_metrics.json` holds the derived metrics, the cost, time
statistics, bucket distributions, and success rate. A one-time
`--schema` mode writes `parser_schema.json`, the field contract giving
each leaf's kind, label, and formula. `python -m parser.inspect` renders
the artifacts in a human-readable form.

The package is layered `data -> metrics -> report`, with `contract` the
schema authority; each module's docstring carries the detail.

## Quick start

The package runs without installation; invoke it as a module from this
directory so it resolves on the import path.

```bash
cd bsc-apm-case-study-infra/parser

# Build the data and metrics artifacts into an output directory
python -m parser <submission-path> --framework {apm,speckit} --metrics -o out_dir

# Write the field-contract schema (needs no session)
python -m parser --schema -o out_dir

# Inspect built artifacts (metrics optional; --schema annotates each
# leaf with its kind and label)
python -m parser.inspect out_dir/parser_data.json out_dir/parser_metrics.json \
    --schema out_dir/parser_schema.json

# Counts-and-events summary of a loaded session
python -m parser <submission-path> --framework {apm,speckit} --inspect

# Economic or process dimension summary at session scope
python -m parser <submission-path> --framework {apm,speckit} --economic
python -m parser <submission-path> --framework {apm,speckit} --process

# Sanitise raw JSONL for archival (secret via CC_PARSER_SECRET)
python -m parser <submission-path> --sanitize
python -m parser <sidecar-path>    --unsanitize

# Full option list
python -m parser --help
```

`<submission-path>` is a single `*.jsonl` file (development convenience)
or a directory of them; sibling `<sessionId>/subagents/` and
`<sessionId>/tool-results/` subdirectories are tolerated and ignored.
`--framework` is required for every mode and never inferred from file
content, so a non-protocol opening prompt cannot silently mis-classify a
session.

## Environment variables

- **CC_PARSER_SECRET**, required for `--sanitize` and `--unsanitize`,
  must match across encrypt and decrypt. Read from the environment or a
  `.env` entry of the same name.
- **CC_PARSER_RATE_TABLE**, optional, overrides the rate-table YAML path
  so an older session can re-run against historical rates without
  editing the canonical `parser/rates.yaml`.

## Related

- [../pipeline/README.md](../pipeline/README.md): the pipeline's parse stage subprocesses this package.
- [../grader/README.md](../grader/README.md): the grading suite.
