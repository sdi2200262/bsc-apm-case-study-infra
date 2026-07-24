# Parser

Transcript parser for the case study. It reads the Claude Code CLI
rollout JSONL a participant session produces and emits the data and
metrics artifacts for the case study analysis.

## Overview

The package reads one or more `<sessionId>.jsonl` files (copied from
`~/.claude/projects/<dashed-cwd>/`), computes per-scope values (session,
phase, and role for APM submissions), and writes two artifacts.
`parser_data.json` holds what the data layer read, the token sums,
counts, session identity facts, and the per-call, per-turn,
per-context-window, and per-dispatch series.
`parser_metrics.json` holds the derived metrics, the cost, time
statistics, turn-prompt bucket distributions, and success rate. A one-time
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

# Economic or process dimension summary at session scope
python -m parser <submission-path> --framework {apm,speckit} --economic
python -m parser <submission-path> --framework {apm,speckit} --process

# Seal every file under a submission for archival
python -m parser.sanitize <submission-path>
python -m parser.sanitize <submission-path> --unsanitize

# Full option list
python -m parser --help
```

`<submission-path>` is a single `*.jsonl` file (development convenience)
or a directory of them; sibling `<sessionId>/subagents/` and
`<sessionId>/tool-results/` subdirectories handled accordingly.
`--framework` is required for every mode and never inferred from file
content, so a non-protocol opening prompt cannot silently mis-classify a
session.

Sanitisation has its own entry point, `python -m parser.sanitize`, because
it shares none of the parser's framework, rate-table, or session
machinery. It walks a directory recursively and seals every file beneath
it (the transcripts, the `subagents/` and `tool-results/` contents, and
the `solution.patch`), or seals a single file when given one; `--unsanitize`
restores each sealed file to its original name in place.

## Environment variables

- **CC_PARSER_SECRET**, required by `python -m parser.sanitize`, must match
  across sealing and restoring. Read from the environment or a
  `.env` entry of the same name.
- **CC_PARSER_RATE_TABLE**, optional, overrides the rate-table YAML path
  so an older session can re-run against historical rates without
  editing the canonical `parser/rates.yaml`.

## Related

- [../grader/README.md](../grader/README.md): the grading suite.
