# Grader Scripts

CLI utilities for analyzing grading outputs and chat exports.

## Overview

- **copilot_chat_parser.py** - Project-level analyzer for Copilot chat exports with multi-file aggregation and PII sanitization
- **results_viewer.py** - Interactive browser for grading results JSON files

## copilot_chat_parser.py

Project-level analyzer for GitHub Copilot chat export JSON files. Aggregates metrics across multiple chat sessions, classifies user behavior, and sanitizes PII data.

### Features

- **Multi-File Aggregation** - Combine N chat files into a single project-level analysis
- **User Behavior Classification** - Classify inputs into Short/Protocol/Standard buckets with APM signature detection
- **PII Sanitization** - Encrypt sensitive paths and content with reversible HMAC-XOR encryption (zero data loss)
- **Multiple Output Formats** - JSON and CSV export with project metadata

### Quick Start

```bash
# Extract project-level metrics from multiple files (JSON + CSV)
./copilot_chat_parser.py chat1.json chat2.json chat3.json --metrics

# Extract metrics in specific format
./copilot_chat_parser.py *.json --metrics --format json
./copilot_chat_parser.py *.json --metrics --format csv

# Sanitize chat exports individually (requires CHAT_PARSER_SECRET)
export CHAT_PARSER_SECRET='your-secret-key'
./copilot_chat_parser.py chat1.json chat2.json --sanitize

# Restore sanitized data (use same secret)
./copilot_chat_parser.py sanitized1.json sanitized2.json --unsanitize
```

### Environment Variables

- **CHAT_PARSER_SECRET** - Required for sanitization/unsanitization. Must be the same for both encrypt and decrypt operations.

### Output Structure

**Project Metadata**
- `file_count` - Number of input files aggregated
- `session_ids` - SHA256 hashes of each session's first request ID (16 chars)
- `unique_model_ids` - Distinct model identifiers across all files (e.g., claude-3-5-sonnet)
- `global_start` - ISO timestamp of earliest request across all files
- `global_end` - ISO timestamp of latest completion across all files

### Metrics Reference

**Tier 1: Reliability (Global Rates)**
- `tool_success_rate` - Σ(successes) / Σ(invocations)
- `tool_retry_rate` - Σ(retries) / Σ(rounds)
- `user_edit_rate` - Σ(terminal edits) / Σ(terminal invocations)

**Tier 2: Volume (Global Sums)**
- `total_requests` - Sum of user messages across all files
- `session_duration_minutes` - (global_end - global_start) / 60000

**Tier 3: Behavior Distribution (Ratios)**
- `ratio_short_inputs` - Count(Short) / total_requests
- `ratio_protocol_inputs` - Count(Protocol) / total_requests
- `ratio_standard_inputs` - Count(Standard) / total_requests

**Tier 4: Behavior Magnitude (Character Counts)**
- `avg_chars_short` - Σ(chars in Short) / Count(Short)
- `avg_chars_protocol` - Σ(chars in Protocol) / Count(Protocol)
- `avg_chars_standard` - Σ(chars in Standard) / Count(Standard)

### User Behavior Classification

Inputs are classified into three mutually exclusive buckets (evaluated in order):

1. **Protocol** - Contains APM signatures (YAML keys or Markdown headers from APM templates)
2. **Short** - Length < 50 characters (e.g., "ok", "continue", "yes")
3. **Standard** - Everything else (natural language debugging/intervention)

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
