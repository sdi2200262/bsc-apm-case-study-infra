# Grader Scripts

CLI utilities for analyzing grading outputs and chat exports.

## Overview

- **copilot_chat_parser.py** - Analyzes GitHub Copilot chat exports
- **cursor_chat_parser.py** - Analyzes Cursor markdown chat exports
- **results_viewer.py** - Interactive browser for grading results JSON files

## Quick Start

### copilot_chat_parser.py

```bash
# Extract metrics from multiple files
./copilot_chat_parser.py chat1.json chat2.json --metrics

# Sanitize files (requires CHAT_PARSER_SECRET)
export CHAT_PARSER_SECRET='your-secret-key'
./copilot_chat_parser.py chat1.json --sanitize

# View full usage
./copilot_chat_parser.py --help
```

### cursor_chat_parser.py

```bash
# Extract metrics from multiple files
./cursor_chat_parser.py chat1.md chat2.md --metrics

# Sanitize files (requires CHAT_PARSER_SECRET)
export CHAT_PARSER_SECRET='your-secret-key'
./cursor_chat_parser.py chat1.md --sanitize

# View full usage
./cursor_chat_parser.py --help
```

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

- **CHAT_PARSER_SECRET** - Required for sanitization/unsanitization operations in chat parsers. Must be the same for both encrypt and decrypt operations. Can be set via environment variable or `.env` file.

## Documentation

For detailed usage, command-line options, and output formats, see:
- Script help: `./<script_name> --help`
- Source code docstrings: See function documentation in each script file

## Pipeline Scripts

The `pipeline/` subdirectory contains scripts for end-to-end submission processing.

See [pipeline/README.md](pipeline/README.md) for script documentation and [../PIPELINE.md](../PIPELINE.md) for the full protocol.
