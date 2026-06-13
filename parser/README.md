# Parser

Transcript parser for the case study. Reads Claude Code CLI rollout
JSONL files produced by participant sessions and emits the data and
metrics artifacts used by the analysis pipeline.

## Package

- **[parser/](parser/)**: Python package implementing
  the metric set defined for the case study. Reads one or more
  `<sessionId>.jsonl` files copied from
  `~/.claude/projects/<dashed-cwd>/`, computes per-scope values
  (session, phase, role for APM submissions), and writes two
  artifacts: `parser_data.json` (the data: token sums, counts, the
  session identity facts, and the per-call and per-turn series) and
  `parser_metrics.json`
  (the metrics: cost, time statistics, bucket distributions, the
  success rate). A one-time `--schema` mode writes `parser_schema.json`,
  the field contract describing each leaf's kind, label, and formula.
  A separate sub-command renders emitted artifacts in a human-readable
  form for inspection.

## Quick start

The package is runnable without installation; invoke it as a Python
module from this directory so the package resolves on the import
path:

```bash
cd bsc-apm-case-study-infra/parser

# Build the data and metrics artifacts into an output directory
python -m parser <submission-path> --framework {apm,speckit} --metrics -o out_dir

# Write the field-contract schema (needs no session)
python -m parser --schema -o out_dir

# Inspect built artifacts (metrics file optional; --schema annotates
# each leaf with its kind and label)
python -m parser.inspect out_dir/parser_data.json out_dir/parser_metrics.json \
    --schema out_dir/parser_schema.json

# Counts-and-events summary of a loaded session
python -m parser <submission-path> --framework {apm,speckit} --inspect

# Economic or process dimension summary at session scope
python -m parser <submission-path> --framework {apm,speckit} --economic
python -m parser <submission-path> --framework {apm,speckit} --process

# Sanitise raw JSONL files for archival; secret via CC_PARSER_SECRET
python -m parser <submission-path> --sanitize
python -m parser <sidecar-path>    --unsanitize

# Full option list
python -m parser --help
```

`<submission-path>` is either a single `*.jsonl` file (development
convenience) or a directory of `*.jsonl` files. Sibling
subdirectories such as `<sessionId>/subagents/` and
`<sessionId>/tool-results/` are tolerated and ignored.

The `--framework` flag is required for every parsing mode and is
never inferred from file content; production callers know the
framework from the submission directory naming, and ad-hoc inspection
callers declare it explicitly so a non-protocol opening prompt cannot
silently mis-classify.

## Environment variables

- **CC_PARSER_SECRET**: required for `--sanitize` and `--unsanitize`.
  Must match across encrypt and decrypt. Read from the environment or
  a `.env` entry of the same name.
- **CC_PARSER_RATE_TABLE**: optional override path to an alternate
  rate-table YAML file. Useful for re-running an older session
  against historical rates without modifying the canonical
  `parser/rates.yaml`.

## Documentation

For the kind, label, and formula of every emitted leaf, run
`--schema` and read `parser_schema.json`, whose contract is defined
in `parser/contract.py`. For module-level details and rationale, see
the docstrings inside each module under `parser/` and its `data/`,
`metrics/`, and `report/` subpackages.

## Related

- [../pipeline/README.md](../pipeline/README.md): the pipeline's
  parse stage subprocesses this package to build per-submission
  metrics artifacts.
