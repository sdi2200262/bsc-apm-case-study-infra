#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Cursor Chat Parser - CLI utility for analyzing Cursor chat exports.

Provides:
- User behavior classification (Short/Protocol/Standard buckets)
- Reversible PII sanitization via encryption (zero data loss)

Environment Variables:
    CHAT_PARSER_SECRET: Required for sanitization/unsanitization operations.
"""

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Constants
# =============================================================================

SANITIZATION_MARKER = "ENC"
META_KEY = "_sanitization_meta"

# APM protocol signatures for user behavior classification
APM_YAML_KEYS = [
    "task_ref:",
    "agent_assignment:",
    "execution_type:",
    "memory_log_path:",
    "dependency_context:",
    "ad_hoc_delegation:",
    "bug_type:",
    "complexity:",
    "delegation_attempt:",
    "research_type:",
    "information_scope:",
    "knowledge_gap:",
]

APM_HEADERS = [
    "# apm task assignment",
    "## task reference",
    "## context from dependencies",
    "## objective",
    "## detailed instructions",
    "## expected output",
    "## memory logging",
    "## reporting protocol",
    "# debug delegation:",
    "# research delegation:",
    "# apm implementation agent handover",
    "# apm manager agent handover",
    "## apm context integration protocol",
    "## context integration protocol",
]

SHORT_INPUT_THRESHOLD = 50


# =============================================================================
# Encryption Utilities
# =============================================================================

def _derive_keystream(secret: bytes, salt: bytes, length: int) -> bytes:
    """Derive keystream using HMAC-SHA256 expansion."""
    keystream = b""
    counter = 0
    while len(keystream) < length:
        block = hmac.new(
            secret,
            salt + counter.to_bytes(4, 'big'),
            hashlib.sha256
        ).digest()
        keystream += block
        counter += 1
    return keystream[:length]


def encrypt(plaintext: str, secret: bytes) -> str:
    """Encrypt string using XOR with HMAC-derived keystream."""
    if not plaintext:
        return plaintext

    salt = os.urandom(16)
    plaintext_bytes = plaintext.encode('utf-8')
    keystream = _derive_keystream(secret, salt, len(plaintext_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))

    salt_b64 = base64.b64encode(salt).decode('ascii')
    cipher_b64 = base64.b64encode(ciphertext).decode('ascii')

    return f"{SANITIZATION_MARKER}:{salt_b64}:{cipher_b64}"


def decrypt(encrypted: str, secret: bytes) -> str:
    """Decrypt string encrypted with encrypt(). Raises ValueError on invalid format."""
    if not encrypted or not encrypted.startswith(f"{SANITIZATION_MARKER}:"):
        return encrypted

    parts = encrypted.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid encrypted format: {encrypted[:50]}...")

    _, salt_b64, cipher_b64 = parts
    salt = base64.b64decode(salt_b64)
    ciphertext = base64.b64decode(cipher_b64)

    keystream = _derive_keystream(secret, salt, len(ciphertext))
    plaintext_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream))

    return plaintext_bytes.decode('utf-8')


# =============================================================================
# Data Loading
# =============================================================================

def load_markdown(filepath: Path) -> str:
    """Load Cursor chat markdown file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def load_json(filepath: Path) -> Dict[str, Any]:
    """Load sanitized JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], filepath: Path) -> None:
    """Save data as formatted JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_markdown(content: str, filepath: Path) -> None:
    """Save markdown content to file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def is_sanitized(data: Any) -> bool:
    """Check if data is a sanitized JSON structure."""
    return isinstance(data, dict) and META_KEY in data


# =============================================================================
# Markdown Parsing
# =============================================================================

def parse_chat(content: str) -> Dict[str, Any]:
    """
    Parse Cursor markdown export into structured data.

    Returns:
        Dictionary with messages list containing role and text.
    """
    messages: List[Dict[str, str]] = []

    # Split by horizontal rules
    sections = re.split(r'\n---\n', content)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Check for User section
        if section.startswith('**User**'):
            text = section[len('**User**'):].strip()
            messages.append({'role': 'user', 'text': text})

        # Check for Cursor section
        elif section.startswith('**Cursor**'):
            text = section[len('**Cursor**'):].strip()
            messages.append({'role': 'cursor', 'text': text})

    return {'messages': messages}


def get_user_messages(data: Dict[str, Any]) -> List[str]:
    """Extract all user message texts from parsed data."""
    return [m['text'] for m in data.get('messages', []) if m['role'] == 'user']


def get_chat_id(user_messages: List[str]) -> str:
    """Generate chat ID from concatenated user messages."""
    combined = "".join(user_messages)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


# =============================================================================
# User Behavior Classification
# =============================================================================

def is_apm_protocol(text: str) -> bool:
    """Check if text contains APM protocol signatures."""
    if not text:
        return False

    text_lower = text.lower()

    for header in APM_HEADERS:
        if header in text_lower:
            return True

    for line in text_lower.split('\n'):
        stripped = line.strip()
        for key in APM_YAML_KEYS:
            if stripped.startswith(key):
                return True

    return False


def classify_user_input(text: str) -> str:
    """
    Classify user input into buckets: "protocol", "short", or "standard".

    Classification priority: protocol > short > standard.
    """
    if not text:
        return "short"

    if is_apm_protocol(text):
        return "protocol"

    if len(text) < SHORT_INPUT_THRESHOLD:
        return "short"

    return "standard"


# =============================================================================
# Metrics Extraction
# =============================================================================

def extract_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract available metrics from parsed Cursor chat.

    Returns:
        Dictionary with project_metadata and metrics.
    """
    user_messages = get_user_messages(data)

    # User behavior classification
    count_short = 0
    count_protocol = 0
    count_standard = 0
    chars_short = 0
    chars_protocol = 0
    chars_standard = 0

    for text in user_messages:
        bucket = classify_user_input(text)
        text_len = len(text) if text else 0

        if bucket == "short":
            count_short += 1
            chars_short += text_len
        elif bucket == "protocol":
            count_protocol += 1
            chars_protocol += text_len
        else:
            count_standard += 1
            chars_standard += text_len

    total_classified = len(user_messages)
    ratio_short = count_short / total_classified if total_classified > 0 else 0.0
    ratio_protocol = count_protocol / total_classified if total_classified > 0 else 0.0
    ratio_standard = count_standard / total_classified if total_classified > 0 else 0.0

    avg_chars_short = chars_short / count_short if count_short > 0 else 0.0
    avg_chars_protocol = chars_protocol / count_protocol if count_protocol > 0 else 0.0
    avg_chars_standard = chars_standard / count_standard if count_standard > 0 else 0.0

    return {
        "project_metadata": {
            "file_count": 1,
            "chat_ids": [get_chat_id(user_messages)],
        },
        "metrics": {
            "total_requests": total_classified,
            "ratio_short_inputs": round(ratio_short, 4),
            "ratio_protocol_inputs": round(ratio_protocol, 4),
            "ratio_standard_inputs": round(ratio_standard, 4),
            "avg_chars_short": round(avg_chars_short, 2),
            "avg_chars_protocol": round(avg_chars_protocol, 2),
            "avg_chars_standard": round(avg_chars_standard, 2),
        }
    }


def aggregate_metrics(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate metrics from multiple parsed chats."""
    all_chat_ids: List[str] = []
    total_requests = 0

    count_short = 0
    count_protocol = 0
    count_standard = 0
    chars_short = 0
    chars_protocol = 0
    chars_standard = 0

    for m in metrics_list:
        pm = m.get('project_metadata', {})
        all_chat_ids.extend(pm.get('chat_ids', []))

        metrics = m.get('metrics', {})
        req = metrics.get('total_requests', 0)
        total_requests += req

        # Reconstruct counts from ratios and totals
        count_short += int(metrics.get('ratio_short_inputs', 0) * req)
        count_protocol += int(metrics.get('ratio_protocol_inputs', 0) * req)
        count_standard += int(metrics.get('ratio_standard_inputs', 0) * req)

        # Reconstruct char totals from averages
        short_count = int(metrics.get('ratio_short_inputs', 0) * req)
        protocol_count = int(metrics.get('ratio_protocol_inputs', 0) * req)
        standard_count = int(metrics.get('ratio_standard_inputs', 0) * req)

        chars_short += metrics.get('avg_chars_short', 0) * short_count
        chars_protocol += metrics.get('avg_chars_protocol', 0) * protocol_count
        chars_standard += metrics.get('avg_chars_standard', 0) * standard_count

    ratio_short = count_short / total_requests if total_requests > 0 else 0.0
    ratio_protocol = count_protocol / total_requests if total_requests > 0 else 0.0
    ratio_standard = count_standard / total_requests if total_requests > 0 else 0.0

    avg_chars_short = chars_short / count_short if count_short > 0 else 0.0
    avg_chars_protocol = chars_protocol / count_protocol if count_protocol > 0 else 0.0
    avg_chars_standard = chars_standard / count_standard if count_standard > 0 else 0.0

    return {
        "project_metadata": {
            "file_count": len(metrics_list),
            "chat_ids": all_chat_ids,
        },
        "metrics": {
            "total_requests": total_requests,
            "ratio_short_inputs": round(ratio_short, 4),
            "ratio_protocol_inputs": round(ratio_protocol, 4),
            "ratio_standard_inputs": round(ratio_standard, 4),
            "avg_chars_short": round(avg_chars_short, 2),
            "avg_chars_protocol": round(avg_chars_protocol, 2),
            "avg_chars_standard": round(avg_chars_standard, 2),
        }
    }


# =============================================================================
# Sanitization
# =============================================================================

def sanitize_chat(content: str, secret: bytes) -> Dict[str, Any]:
    """
    Sanitize chat export by encrypting the entire payload.

    Metadata is preserved in plaintext for cataloging without decryption.
    """
    data = parse_chat(content)
    user_messages = get_user_messages(data)
    chat_id = get_chat_id(user_messages)
    requests_count = len(user_messages)

    encrypted_payload = encrypt(content, secret)

    return {
        META_KEY: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original_size": len(content.encode('utf-8')),
            "requests_count": requests_count,
            "chat_id": chat_id,
        },
        "payload": encrypted_payload
    }


def unsanitize_chat(data: Dict[str, Any], secret: bytes) -> str:
    """
    Restore sanitized chat export by decrypting the payload.

    Raises:
        ValueError: If payload is missing or malformed.
    """
    encrypted_payload = data.get("payload")
    if not encrypted_payload:
        raise ValueError("Sanitized file missing 'payload' field")

    return decrypt(encrypted_payload, secret)


# =============================================================================
# Output Formatting
# =============================================================================

def export_metrics_json(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as JSON file."""
    save_json(metrics, filepath)
    print(f"Metrics exported to: {filepath}")


def export_metrics_csv(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as CSV file with flattened structure."""
    row = {}

    pm = metrics.get('project_metadata', {})
    row['file_count'] = pm.get('file_count', 0)
    row['chat_ids'] = ';'.join(pm.get('chat_ids', []))

    m = metrics.get('metrics', {})
    row.update(m)

    fieldnames = list(row.keys())

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)

    print(f"Metrics exported to: {filepath}")


# =============================================================================
# CLI
# =============================================================================

def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        prog="cursor_chat_parser.py",
        description="CLI utility for analyzing Cursor chat exports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Extract metrics from multiple files:
    ./cursor_chat_parser.py chat1.md chat2.md --metrics
    ./cursor_chat_parser.py *.md --metrics --format json
    ./cursor_chat_parser.py *.md --metrics --format csv

  Sanitize files (requires CHAT_PARSER_SECRET env var):
    export CHAT_PARSER_SECRET='your-secret-key'
    ./cursor_chat_parser.py chat1.md chat2.md --sanitize

  Unsanitize files (requires same secret):
    ./cursor_chat_parser.py sanitized1.json sanitized2.json --unsanitize

Environment Variables:
  CHAT_PARSER_SECRET  Required for --sanitize and --unsanitize operations.
        """
    )

    parser.add_argument(
        "input_files",
        type=Path,
        nargs='+',
        help="Path(s) to the chat export file(s) (.md for raw, .json for sanitized)"
    )

    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Extract and export metrics (aggregated across all input files)"
    )

    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default=None,
        help="Output format for metrics (default: both)"
    )

    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Sanitize chat exports via encryption (processes each file individually)"
    )

    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help="Unsanitize chat exports via decryption (processes each file individually)"
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file path for metrics (default: metrics_project.json/csv)"
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    for input_file in args.input_files:
        if not input_file.exists():
            print(f"Error: File not found: {input_file}", file=sys.stderr)
            return 1

    if args.sanitize:
        secret = os.environ.get('CHAT_PARSER_SECRET', '').encode('utf-8')
        if not secret:
            print("Error: CHAT_PARSER_SECRET environment variable not set.",
                  file=sys.stderr)
            return 1

        for input_file in args.input_files:
            if input_file.suffix == '.json':
                print(f"Warning: {input_file} appears to be JSON (already sanitized?), skipping.",
                      file=sys.stderr)
                continue

            try:
                content = load_markdown(input_file)
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            sanitized = sanitize_chat(content, secret)
            output_path = input_file.parent / f"sanitized_{input_file.stem}.json"
            save_json(sanitized, output_path)
            print(f"Sanitized export saved to: {output_path}")

        return 0

    if args.unsanitize:
        secret = os.environ.get('CHAT_PARSER_SECRET', '').encode('utf-8')
        if not secret:
            print("Error: CHAT_PARSER_SECRET environment variable not set.",
                  file=sys.stderr)
            return 1

        for input_file in args.input_files:
            if input_file.suffix != '.json':
                print(f"Warning: {input_file} is not a JSON file, skipping.",
                      file=sys.stderr)
                continue

            try:
                data = load_json(input_file)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON in {input_file}: {e}", file=sys.stderr)
                return 1
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            if not is_sanitized(data):
                print(f"Warning: {input_file} is not a sanitized file, skipping.",
                      file=sys.stderr)
                continue

            try:
                restored = unsanitize_chat(data, secret)
            except ValueError as e:
                print(f"Error: Failed to unsanitize {input_file}: {e}", file=sys.stderr)
                return 1

            output_path = input_file.parent / f"unsanitized_{input_file.stem}.md"
            save_markdown(restored, output_path)
            print(f"Restored export saved to: {output_path}")

        return 0

    if args.metrics:
        metrics_list = []

        for input_file in args.input_files:
            if input_file.suffix == '.json':
                print(f"Error: {input_file} is sanitized. Extract metrics before sanitization.",
                      file=sys.stderr)
                return 1

            try:
                content = load_markdown(input_file)
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            data = parse_chat(content)
            metrics = extract_metrics(data)
            metrics_list.append(metrics)

        if len(metrics_list) == 1:
            aggregated = metrics_list[0]
        else:
            aggregated = aggregate_metrics(metrics_list)

        first_parent = args.input_files[0].parent

        if args.format == "json":
            output_path = args.output or (first_parent / "metrics_project.json")
            export_metrics_json(aggregated, output_path)
        elif args.format == "csv":
            output_path = args.output or (first_parent / "metrics_project.csv")
            export_metrics_csv(aggregated, output_path)
        else:
            json_path = args.output.with_suffix('.json') if args.output else (first_parent / "metrics_project.json")
            csv_path = args.output.with_suffix('.csv') if args.output else (first_parent / "metrics_project.csv")
            export_metrics_json(aggregated, json_path)
            export_metrics_csv(aggregated, csv_path)

        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
