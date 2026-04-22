# Grader Scripts

CLI utilities for analyzing grading outputs and chat exports.

## Overview

- **copilot_chat_parser/** - Package that analyzes GitHub Copilot chat exports.
- **results_viewer.py** - Interactive browser for grading results JSON files.

## Quick Start

### copilot_chat_parser

Invoke as a Python module from the `scripts/` directory (the package
location). The package is runnable without installation:

```bash
cd bsc-apm-case-study-task/grader/scripts

# Extract metrics from one or more chat exports
python -m copilot_chat_parser chat1.json chat2.json --metrics

# Pick a single output format and location
python -m copilot_chat_parser chat1.json --metrics --format json -o metrics.json

# Sanitize files (requires CHAT_PARSER_SECRET)
export CHAT_PARSER_SECRET='your-secret-key'
python -m copilot_chat_parser chat1.json --sanitize

# Adjust the short-input threshold
python -m copilot_chat_parser chat1.json --metrics --short-threshold 30

# View full usage
python -m copilot_chat_parser --help
```

The pipeline (`../pipeline/parse_submission.py`) invokes the package the
same way, setting `PYTHONPATH` to this `scripts/` directory.

### results_viewer.py

```bash
# Interactive mode (default)
./results_viewer.py results.json

# Show summary
./results_viewer.py results.json --summary

# View full usage
./results_viewer.py --help
```

## Environment Variables

- **CHAT_PARSER_SECRET** - Required for sanitization/unsanitization operations in the chat parser. Must match across encrypt and decrypt. Can be set via environment variable or `.env` file.

## Documentation

For detailed usage, command-line options, and output formats, see:
- Module help: `python -m copilot_chat_parser --help`
- Source code docstrings: each module in `copilot_chat_parser/` and its
  `metrics/` subpackage.

## Pipeline Scripts

Pipeline scripts for end-to-end submission processing live in `../pipeline/`.
See [../pipeline/README.md](../pipeline/README.md) for script documentation and [../PIPELINE.md](../PIPELINE.md) for the full protocol.
