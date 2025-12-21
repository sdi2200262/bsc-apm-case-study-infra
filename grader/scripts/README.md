# Grader Scripts

CLI utilities for analyzing grading outputs and chat exports.

## Overview

- **copilot_chat_parser.py** - Advanced analyzer for Copilot chat exports with PII sanitization
- **results_viewer.py** - Interactive browser for grading results JSON files

## copilot_chat_parser.py

Comprehensive analyzer for GitHub Copilot chat export JSON files. Extracts metrics, sanitizes PII data, and provides both CLI and interactive modes.

### Features

- **Metrics Extraction** - Extract 20+ metrics including tool usage, success rates, session duration, and agentic activity patterns
- **PII Sanitization** - Encrypt sensitive paths and content with reversible HMAC-XOR encryption (zero data loss)
- **Multiple Output Formats** - JSON, CSV, interactive menu, or formatted terminal display
- **Flexible CLI** - Command-line arguments for scripting or interactive menu for exploration

### Quick Start

```bash
# Interactive mode (default)
./copilot_chat_parser.py chat.json

# Extract all metrics (JSON + CSV)
./copilot_chat_parser.py chat.json --metrics

# Extract metrics in specific format
./copilot_chat_parser.py chat.json --metrics --format json
./copilot_chat_parser.py chat.json --metrics --format csv

# Sanitize chat export (requires CHAT_PARSER_SECRET)
export CHAT_PARSER_SECRET='your-secret-key'
./copilot_chat_parser.py chat.json --sanitize -o sanitized.json

# Restore sanitized data (use same secret)
./copilot_chat_parser.py sanitized.json --unsanitize -o restored.json
```

### Environment Variables

- **CHAT_PARSER_SECRET** - Required for sanitization/unsanitization. Must be the same for both encrypt and decrypt operations.

### Metrics Reference

**Session Metadata**
- `session_id` - SHA256 hash of request ID (first 16 chars)
- `model_id` - Model identifier (e.g., copilot/claude-opus-4.5)

**Core Metrics (Tier 1)**
- `total_requests` - Number of user requests
- `total_tool_invocations` - Total tool calls across all requests
- `user_edit_count` - Count of user edits to terminal commands
- `terminal_invocations` - Total terminal command invocations
- `user_edit_rate` - Ratio of edited to total terminal invocations
- `tool_success_count` - Completed tool invocations
- `tool_success_rate` - Success rate of all tool invocations
- `session_duration_ms` - Total session time in milliseconds

**Supporting Metrics (Tier 2)**
- `total_rounds` - Count of tool execution rounds
- `retry_count` - Tool invocation retries across all rounds
- `tool_retry_rate` - Ratio of retries to total rounds
- `invocations_per_request` - Average tools used per request
- `unique_tools_used` - Count of distinct tool types

**Agentic Activity (Tier 3)**
- `file_modifications` - Count of file creation/edit operations
- `read_operations` - Total file read operations
- `write_operations` - Total file write operations
- `read_write_ratio` - Ratio of reads to writes

---

## results_viewer.py

Interactive browser for grading results JSON files. Displays test scores, filtering, detailed output, and search capabilities.

### Quick Start

```bash
# Interactive mode (default)
./results_viewer.py results.json

# Show summary
./results_viewer.py results.json --summary

# List failed tests
./results_viewer.py results.json --failed

# View specific test with full output
./results_viewer.py results.json --test AN1

# Get raw test output for piping
./results_viewer.py results.json -o P2 | python3 -m json.tool
```

### Interactive Menu Options

1. Show summary - Score breakdown by category
2. List all tests - All test results with status
3. Show failed tests - Failed tests only
4. Show passed tests - Passed tests only
5. Filter by category - Tests in specific category
6. View specific test - Full output for one test
7. Search in full outputs - Search across all test results

### Test IDs

**Python Tests**: B1, P1, P2, L1-L3, O1-O2, C1-C2, A1, AN1-AN5  
**C Tests**: B2, M1, P1_c, P2_c, L1_c-L3_c, O1_c-O2_c, C1_c-C2_c, A1_c, AN1_c-AN5_c

### Categories

build, protocol, login, logout, courses, authstatus, announcements, memory
