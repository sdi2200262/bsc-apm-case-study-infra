#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Copilot Chat Parser - CLI utility for analyzing GitHub Copilot chat exports.

Provides:
- Project-level metric extraction with multi-file aggregation (JSON/CSV output)
- Reversible PII sanitization via encryption (zero data loss)
- User behavior classification (Short/Protocol/Standard buckets)

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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv is optional


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
    """
    Derive keystream using HMAC-SHA256 expansion.
    
    Args:
        secret: Secret key bytes for HMAC.
        salt: Salt bytes for keystream derivation.
        length: Desired keystream length in bytes.
    
    Returns:
        Keystream bytes of specified length.
    """
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
    """
    Encrypt string using XOR with HMAC-derived keystream.
    
    Args:
        plaintext: Plaintext string to encrypt.
        secret: Secret key bytes for encryption.
    
    Returns:
        Encrypted string in format "ENC:{salt_b64}:{cipher_b64}".
        Returns original plaintext if empty.
    """
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
    """
    Decrypt string encrypted with encrypt().
    
    Args:
        encrypted: Encrypted string in format "ENC:{salt_b64}:{cipher_b64}".
        secret: Secret key bytes for decryption (must match encryption key).
    
    Returns:
        Decrypted plaintext string. Returns original string if not encrypted.
    
    Raises:
        ValueError: If encrypted format is invalid or malformed.
    """
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

def load_chat(filepath: Path) -> Dict[str, Any]:
    """
    Load and parse Copilot chat JSON file.
    
    Args:
        filepath: Path to the Copilot chat export JSON file.
    
    Returns:
        Parsed JSON data as dictionary.
    
    Raises:
        json.JSONDecodeError: If file contains invalid JSON.
        OSError: If file cannot be read.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], filepath: Path) -> None:
    """
    Save data as formatted JSON file.
    
    Args:
        data: Dictionary to save as JSON.
        filepath: Path where JSON file will be written.
    
    Raises:
        OSError: If file cannot be written.
    """
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_sanitized(data: Dict[str, Any]) -> bool:
    """
    Check if chat data has been sanitized.
    
    Args:
        data: Chat data dictionary to check.
    
    Returns:
        True if data contains sanitization metadata, False otherwise.
    """
    return META_KEY in data


# =============================================================================
# User Behavior Classification
# =============================================================================

def is_apm_protocol(text: str) -> bool:
    """
    Check if text contains APM protocol signatures.
    
    Args:
        text: Text string to check for APM protocol markers.
    
    Returns:
        True if text contains APM YAML keys or headers, False otherwise.
    """
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
    
    Args:
        text: User input text to classify.
    
    Returns:
        Classification bucket: "protocol", "short", or "standard".
        Returns "short" if text is empty.
    """
    if not text:
        return "short"

    if is_apm_protocol(text):
        return "protocol"

    if len(text) < SHORT_INPUT_THRESHOLD:
        return "short"

    return "standard"


# =============================================================================
# Metric Extraction Helpers
# =============================================================================

def count_tool_invocations(request: Dict[str, Any]) -> int:
    """
    Count tool invocations in a request's response array.
    
    Args:
        request: Request dictionary containing response array.
    
    Returns:
        Number of tool invocations found in the request.
    """
    count = 0
    for item in request.get('response', []):
        if item.get('kind') == 'toolInvocationSerialized':
            count += 1
    return count


def count_tool_successes(request: Dict[str, Any]) -> int:
    """
    Count successfully completed tool invocations.
    
    Args:
        request: Request dictionary containing response array.
    
    Returns:
        Number of successfully completed tool invocations.
    """
    successes = 0
    for item in request.get('response', []):
        if item.get('kind') != 'toolInvocationSerialized':
            continue
        if item.get('isComplete', False):
            successes += 1
    return successes


def count_user_edits(request: Dict[str, Any]) -> Tuple[int, int]:
    """
    Count user edits and terminal invocations.
    
    Args:
        request: Request dictionary containing response array.
    
    Returns:
        Tuple of (edit_count: int, terminal_count: int).
        edit_count is number of terminal commands that were edited by user.
        terminal_count is total number of terminal invocations.
    """
    edits = 0
    terminals = 0

    for item in request.get('response', []):
        if item.get('kind') != 'toolInvocationSerialized':
            continue

        tsd = item.get('toolSpecificData', {})
        if tsd.get('kind') != 'terminal':
            continue

        terminals += 1

        cmd_line = tsd.get('commandLine', {})
        original = cmd_line.get('original', '')
        user_edited = cmd_line.get('userEdited', '')

        if original and user_edited and original != user_edited:
            edits += 1

    return edits, terminals


def get_rounds_info(request: Dict[str, Any]) -> Tuple[int, int]:
    """
    Get tool round and retry counts.
    
    Args:
        request: Request dictionary containing result metadata.
    
    Returns:
        Tuple of (round_count: int, retry_count: int).
        round_count is number of tool call rounds.
        retry_count is total number of tool input retries.
    """
    result = request.get('result', {})
    metadata = result.get('metadata', {})
    rounds = metadata.get('toolCallRounds', [])

    round_count = len(rounds)
    retry_count = sum(r.get('toolInputRetry', 0) for r in rounds)

    return round_count, retry_count


def extract_user_text(request: Dict[str, Any]) -> Optional[str]:
    """
    Extract user message text from a request.
    
    Args:
        request: Request dictionary containing message data.
    
    Returns:
        User message text string, or None if not found.
    """
    message = request.get('message', {})
    return message.get('text', '')


def get_timestamps(requests: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    """
    Get min and max timestamps from requests in milliseconds.
    
    Args:
        requests: List of request dictionaries.
    
    Returns:
        Tuple of (min_timestamp: Optional[int], max_timestamp: Optional[int]).
        Timestamps are in milliseconds. Returns (None, None) if requests list is empty.
        max_timestamp considers both request timestamp and completedAt from modelState.
    """
    if not requests:
        return None, None

    min_ts = None
    max_ts = None

    for r in requests:
        ts = r.get('timestamp')
        if ts is not None:
            if min_ts is None or ts < min_ts:
                min_ts = ts
            if max_ts is None or ts > max_ts:
                max_ts = ts

        model_state = r.get('modelState', {})
        completed_at = model_state.get('completedAt')
        if completed_at is not None:
            if max_ts is None or completed_at > max_ts:
                max_ts = completed_at

    return min_ts, max_ts


def get_chat_id(user_texts: List[str]) -> str:
    """
    Generate chat ID from concatenated user messages.
    
    Args:
        user_texts: List of user message text strings.
    
    Returns:
        SHA256 hash of concatenated messages (first 16 characters).
    """
    combined = "".join(user_texts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def get_model_ids(data: Dict[str, Any]) -> List[str]:
    """
    Extract all unique model IDs from chat data.
    
    Args:
        data: Chat data dictionary containing requests.
    
    Returns:
        Sorted list of unique model ID strings.
    """
    model_ids: Set[str] = set()
    for request in data.get('requests', []):
        model_id = request.get('modelId', '')
        if model_id:
            model_ids.add(model_id)
    return sorted(model_ids)


# =============================================================================
# Raw Event Extraction
# =============================================================================

def extract_raw_events(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract raw event counts from a single chat file for aggregation.
    
    Args:
        data: Chat data dictionary containing requests.
    
    Returns:
        Dictionary with raw event counts and metadata:
        - total_requests: Number of requests
        - total_invocations: Total tool invocations
        - total_successes: Successful tool invocations
        - total_edits: User terminal edits
        - total_terminals: Terminal invocations
        - total_rounds: Tool call rounds
        - total_retries: Tool input retries
        - user_texts: List of user message texts
        - min_timestamp: Earliest timestamp (ms)
        - max_timestamp: Latest timestamp (ms)
        - chat_id: SHA256 hash of user messages
        - model_ids: List of model IDs
    """
    requests = data.get('requests', [])

    total_requests = len(requests)
    total_invocations = 0
    total_successes = 0
    total_edits = 0
    total_terminals = 0
    total_rounds = 0
    total_retries = 0
    user_texts: List[str] = []

    for r in requests:
        total_invocations += count_tool_invocations(r)
        total_successes += count_tool_successes(r)

        edits, terminals = count_user_edits(r)
        total_edits += edits
        total_terminals += terminals

        rounds, retries = get_rounds_info(r)
        total_rounds += rounds
        total_retries += retries

        user_text = extract_user_text(r)
        if user_text is not None:
            user_texts.append(user_text)

    min_ts, max_ts = get_timestamps(requests)

    return {
        'total_requests': total_requests,
        'total_invocations': total_invocations,
        'total_successes': total_successes,
        'total_edits': total_edits,
        'total_terminals': total_terminals,
        'total_rounds': total_rounds,
        'total_retries': total_retries,
        'user_texts': user_texts,
        'min_timestamp': min_ts,
        'max_timestamp': max_ts,
        'chat_id': get_chat_id(user_texts),
        'model_ids': get_model_ids(data),
    }


# =============================================================================
# Project-Level Aggregation
# =============================================================================

def aggregate_metrics(raw_events_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate raw events from multiple files into project-level metrics.
    
    Args:
        raw_events_list: List of raw event dictionaries from extract_raw_events().
    
    Returns:
        Dictionary with project_metadata and metrics:
        - project_metadata: file_count, chat_ids, unique_model_ids, global_start, global_end
        - metrics: tool_success_rate, tool_retry_rate, user_edit_rate, total_requests,
          session_duration_minutes, ratio_short_inputs, ratio_protocol_inputs,
          ratio_standard_inputs, avg_chars_short, avg_chars_protocol, avg_chars_standard
    """
    total_requests = 0
    total_invocations = 0
    total_successes = 0
    total_edits = 0
    total_terminals = 0
    total_rounds = 0
    total_retries = 0

    all_user_texts: List[str] = []
    global_min_ts: Optional[int] = None
    global_max_ts: Optional[int] = None
    chat_ids: List[str] = []
    all_model_ids: Set[str] = set()

    for events in raw_events_list:
        total_requests += events['total_requests']
        total_invocations += events['total_invocations']
        total_successes += events['total_successes']
        total_edits += events['total_edits']
        total_terminals += events['total_terminals']
        total_rounds += events['total_rounds']
        total_retries += events['total_retries']

        all_user_texts.extend(events['user_texts'])

        min_ts = events['min_timestamp']
        max_ts = events['max_timestamp']

        if min_ts is not None:
            if global_min_ts is None or min_ts < global_min_ts:
                global_min_ts = min_ts
        if max_ts is not None:
            if global_max_ts is None or max_ts > global_max_ts:
                global_max_ts = max_ts

        if events['chat_id']:
            chat_ids.append(events['chat_id'])

        all_model_ids.update(events['model_ids'])

    # Reliability rates
    tool_success_rate = total_successes / total_invocations if total_invocations > 0 else 0.0
    tool_retry_rate = total_retries / total_rounds if total_rounds > 0 else 0.0
    user_edit_rate = total_edits / total_terminals if total_terminals > 0 else 0.0

    # Session duration
    session_duration_minutes = 0.0
    if global_min_ts is not None and global_max_ts is not None:
        session_duration_minutes = (global_max_ts - global_min_ts) / 60000.0

    # User behavior classification
    count_short = 0
    count_protocol = 0
    count_standard = 0
    chars_short = 0
    chars_protocol = 0
    chars_standard = 0

    for text in all_user_texts:
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

    total_classified = len(all_user_texts)
    ratio_short = count_short / total_classified if total_classified > 0 else 0.0
    ratio_protocol = count_protocol / total_classified if total_classified > 0 else 0.0
    ratio_standard = count_standard / total_classified if total_classified > 0 else 0.0

    avg_chars_short = chars_short / count_short if count_short > 0 else 0.0
    avg_chars_protocol = chars_protocol / count_protocol if count_protocol > 0 else 0.0
    avg_chars_standard = chars_standard / count_standard if count_standard > 0 else 0.0

    global_start = None
    global_end = None
    if global_min_ts is not None:
        global_start = datetime.fromtimestamp(global_min_ts / 1000, tz=timezone.utc).isoformat()
    if global_max_ts is not None:
        global_end = datetime.fromtimestamp(global_max_ts / 1000, tz=timezone.utc).isoformat()

    return {
        "project_metadata": {
            "file_count": len(raw_events_list),
            "chat_ids": chat_ids,
            "unique_model_ids": sorted(all_model_ids),
            "global_start": global_start,
            "global_end": global_end,
        },
        "metrics": {
            "tool_success_rate": round(tool_success_rate, 4),
            "tool_retry_rate": round(tool_retry_rate, 4),
            "user_edit_rate": round(user_edit_rate, 4),
            "total_requests": total_requests,
            "session_duration_minutes": round(session_duration_minutes, 2),
            "ratio_short_inputs": round(ratio_short, 4),
            "ratio_protocol_inputs": round(ratio_protocol, 4),
            "ratio_standard_inputs": round(ratio_standard, 4),
            "avg_chars_short": round(avg_chars_short, 2),
            "avg_chars_protocol": round(avg_chars_protocol, 2),
            "avg_chars_standard": round(avg_chars_standard, 2),
        }
    }


def extract_project_metrics(data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract project-level metrics from multiple chat files.
    
    Args:
        data_list: List of chat data dictionaries from load_chat().
    
    Returns:
        Dictionary with aggregated project-level metrics (same structure as aggregate_metrics()).
    """
    raw_events_list = [extract_raw_events(data) for data in data_list]
    return aggregate_metrics(raw_events_list)


# =============================================================================
# Sanitization
# =============================================================================

def sanitize_chat(data: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Sanitize chat export by encrypting the entire payload.
    
    Metadata is preserved in plaintext for cataloging without decryption.
    
    Args:
        data: Chat data dictionary to sanitize.
        secret: Secret key bytes for encryption.
    
    Returns:
        Dictionary with sanitization metadata and encrypted payload:
        - _sanitization_meta: timestamp, original_size, requests_count, chat_id, model_ids
        - payload: Encrypted chat data string
    """
    requests = data.get('requests', [])
    user_texts = [extract_user_text(r) for r in requests if extract_user_text(r) is not None]
    chat_id = get_chat_id(user_texts)
    model_ids = get_model_ids(data)
    requests_count = len(requests)

    plaintext = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    encrypted_payload = encrypt(plaintext, secret)

    return {
        META_KEY: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original_size": len(plaintext),
            "requests_count": requests_count,
            "chat_id": chat_id,
            "model_ids": model_ids,
        },
        "payload": encrypted_payload
    }


def unsanitize_chat(data: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Restore sanitized chat export by decrypting the payload.

    Args:
        data: Chat data dictionary containing encrypted payload.
        secret: Secret key bytes for decryption (must match encryption key).
    
    Returns:
        Dictionary with decrypted payload.
    
    Raises:
        ValueError: If payload is missing or malformed.
        json.JSONDecodeError: If decrypted payload is not valid JSON.
    """
    encrypted_payload = data.get("payload")
    if not encrypted_payload or not encrypted_payload.startswith(f"{SANITIZATION_MARKER}:"):
        raise ValueError("Sanitized file missing 'payload' field or invalid format")

    plaintext = decrypt(encrypted_payload, secret)
    try:
        return json.loads(plaintext)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in decrypted payload: {e}")

# =============================================================================
# Output Formatting
# =============================================================================

def export_metrics_json(metrics: Dict[str, Any], filepath: Path) -> None:
    """
    Export metrics as JSON file.
    
    Args:
        metrics: Metrics dictionary from aggregate_metrics() or extract_project_metrics().
        filepath: Path where JSON file will be written.
    
    Raises:
        OSError: If file cannot be written.
    """
    save_json(metrics, filepath)
    print(f"Metrics exported to: {filepath}")


def export_metrics_csv(metrics: Dict[str, Any], filepath: Path) -> None:
    """
    Export metrics as CSV file with flattened structure.
    
    Args:
        metrics: Metrics dictionary from aggregate_metrics() or extract_project_metrics().
        filepath: Path where CSV file will be written.
    
    Raises:
        OSError: If file cannot be written.
    """
    row = {}

    pm = metrics.get('project_metadata', {})
    row['file_count'] = pm.get('file_count', 0)
    row['chat_ids'] = ';'.join(pm.get('chat_ids', []))
    row['unique_model_ids'] = ';'.join(pm.get('unique_model_ids', []))
    row['global_start'] = pm.get('global_start', '')
    row['global_end'] = pm.get('global_end', '')

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
    """
    Create and configure argument parser.
    
    Returns:
        Configured ArgumentParser instance with all CLI arguments.
    """
    parser = argparse.ArgumentParser(
        prog="copilot_chat_parser.py",
        description="CLI utility for analyzing GitHub Copilot chat exports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Extract metrics from multiple files:
    ./copilot_chat_parser.py chat1.json chat2.json --metrics
    ./copilot_chat_parser.py *.json --metrics --format json
    ./copilot_chat_parser.py *.json --metrics --format csv

  Sanitize files (requires CHAT_PARSER_SECRET env var):
    export CHAT_PARSER_SECRET='your-secret-key'
    ./copilot_chat_parser.py chat1.json chat2.json --sanitize

  Unsanitize files (requires same secret):
    ./copilot_chat_parser.py sanitized1.json sanitized2.json --unsanitize

Environment Variables:
  CHAT_PARSER_SECRET  Required for --sanitize and --unsanitize operations.
        """
    )

    parser.add_argument(
        "input_files",
        type=Path,
        nargs='+',
        help="Path(s) to the chat export JSON file(s)"
    )

    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Extract and export project-level metrics (aggregated across all input files)"
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
    """
    Main entry point for CLI execution.
    
    Returns:
        Exit code: 0 for success, 1 for error.
    """
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
            try:
                data = load_chat(input_file)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON in {input_file}: {e}", file=sys.stderr)
                return 1
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            if is_sanitized(data):
                print(f"Warning: {input_file} is already sanitized, skipping.",
                      file=sys.stderr)
                continue

            sanitized = sanitize_chat(data, secret)
            output_path = input_file.parent / f"sanitized_{input_file.name}"
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
            try:
                data = load_chat(input_file)
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
            except (ValueError, json.JSONDecodeError) as e:
                print(f"Error: Failed to unsanitize {input_file}: {e}", file=sys.stderr)
                return 1

            output_path = input_file.parent / f"unsanitized_{input_file.name}"
            save_json(restored, output_path)
            print(f"Restored export saved to: {output_path}")

        return 0

    if args.metrics:
        data_list = []

        for input_file in args.input_files:
            try:
                data = load_chat(input_file)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON in {input_file}: {e}", file=sys.stderr)
                return 1
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            if is_sanitized(data):
                print(f"Error: {input_file} is sanitized. Extract metrics before sanitization.",
                      file=sys.stderr)
                return 1

            data_list.append(data)

        metrics = extract_project_metrics(data_list)

        first_parent = args.input_files[0].parent

        if args.format == "json":
            output_path = args.output or (first_parent / "metrics_project.json")
            export_metrics_json(metrics, output_path)
        elif args.format == "csv":
            output_path = args.output or (first_parent / "metrics_project.csv")
            export_metrics_csv(metrics, output_path)
        else:
            json_path = args.output.with_suffix('.json') if args.output else (first_parent / "metrics_project.json")
            csv_path = args.output.with_suffix('.csv') if args.output else (first_parent / "metrics_project.csv")
            export_metrics_json(metrics, json_path)
            export_metrics_csv(metrics, csv_path)

        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
