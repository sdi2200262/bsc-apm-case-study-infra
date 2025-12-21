#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Copilot Chat Parser - CLI utility for analyzing GitHub Copilot chat exports.

Provides:
- Metric extraction (JSON/CSV output)
- Reversible PII sanitization with zero data loss
- Interactive menu mode for human exploration

Environment Variables:
    CHAT_PARSER_SECRET: Required for sanitization/unsanitization operations.
                        Must be the same key for both encrypt and decrypt.
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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


# =============================================================================
# Constants
# =============================================================================

LINE_WIDTH = 60
SANITIZATION_VERSION = 1
SANITIZATION_MARKER = "ENC"
META_KEY = "_sanitization_meta"

# Tool classifications for read/write metrics
READ_TOOLS = frozenset([
    "copilot_readFile", "read_file", "copilot_findFiles", "file_search",
    "copilot_findTextInFiles", "grep_search", "semantic_search",
    "copilot_listDirectory", "list_dir", "copilot_fetchWebPage",
    "fetch_webpage", "vscode_fetchWebPage_internal"
])

WRITE_TOOLS = frozenset([
    "copilot_createFile", "create_file", "replace_string_in_file",
    "multi_replace_string_in_file", "edit_notebook_file", "run_in_terminal"
])

FILE_MODIFICATION_TOOLS = frozenset([
    "copilot_createFile", "create_file", "replace_string_in_file",
    "multi_replace_string_in_file", "edit_notebook_file"
])

# Regex patterns for path detection
PATH_PATTERNS = [
    re.compile(r'file:///[^\s"\'\]}>]+'),           # file:// URIs
    re.compile(r'/Users/[^\s"\'\]}>]+'),            # macOS paths
    re.compile(r'/home/[^\s"\'\]}>]+'),             # Linux paths
    re.compile(r'[A-Za-z]:\\[^\s"\'\]}>]+'),        # Windows paths
]


# =============================================================================
# Encryption Utilities (Stdlib-only, HMAC-SHA256 + XOR)
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


def encrypt_field(plaintext: str, secret: bytes) -> str:
    """Encrypt string with XOR against HMAC keystream (format: ENC:<salt>:<cipher>)."""
    if not plaintext:
        return plaintext
    
    salt = os.urandom(16)
    plaintext_bytes = plaintext.encode('utf-8')
    keystream = _derive_keystream(secret, salt, len(plaintext_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))
    
    salt_b64 = base64.b64encode(salt).decode('ascii')
    cipher_b64 = base64.b64encode(ciphertext).decode('ascii')
    
    return f"{SANITIZATION_MARKER}:{salt_b64}:{cipher_b64}"


def decrypt_field(encrypted: str, secret: bytes) -> str:
    """Decrypt ENC:<salt>:<cipher> string. Raises ValueError on invalid format."""
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


def is_encrypted(value: str) -> bool:
    """Check if a string value is in encrypted format."""
    return isinstance(value, str) and value.startswith(f"{SANITIZATION_MARKER}:")


def encrypt_paths_in_text(text: str, secret: bytes) -> str:
    """
    Find and encrypt all file paths within a text string.
    
    Args:
        text: Text potentially containing file paths.
        secret: Encryption secret.
    
    Returns:
        Text with all detected paths encrypted.
    """
    if not text:
        return text
    
    # Collect all path matches
    matches: List[Tuple[int, int, str]] = []
    for pattern in PATH_PATTERNS:
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end(), match.group()))
    
    # Sort by position descending to replace from end
    matches.sort(key=lambda x: x[0], reverse=True)
    
    # Remove overlapping matches (keep longest)
    filtered: List[Tuple[int, int, str]] = []
    for start, end, path in matches:
        if not any(s <= start < e or s < end <= e for s, e, _ in filtered):
            filtered.append((start, end, path))
    
    # Replace paths with encrypted versions
    result = text
    for start, end, path in filtered:
        encrypted_path = encrypt_field(path, secret)
        result = result[:start] + encrypted_path + result[end:]
    
    return result


def decrypt_paths_in_text(text: str, secret: bytes) -> str:
    """
    Find and decrypt all encrypted paths within a text string.
    
    Args:
        text: Text potentially containing encrypted paths.
        secret: Decryption secret.
    
    Returns:
        Text with all encrypted paths restored.
    """
    if not text:
        return text
    
    # Find all ENC:...:... patterns
    pattern = re.compile(rf'{SANITIZATION_MARKER}:[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+')
    
    def replacer(match: re.Match) -> str:
        try:
            return decrypt_field(match.group(), secret)
        except Exception:
            return match.group()  # Leave unchanged if decryption fails
    
    return pattern.sub(replacer, text)


# =============================================================================
# Data Loading
# =============================================================================

def load_chat(filepath: Path) -> Dict[str, Any]:
    """Load and parse Copilot chat JSON file. Raises JSONDecodeError or FileNotFoundError."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], filepath: Path) -> None:
    """Save data as formatted JSON file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_sanitized(data: Dict[str, Any]) -> bool:
    """Check if chat data has been sanitized."""
    return META_KEY in data


# =============================================================================
# Metric Extraction
# =============================================================================

def count_tool_invocations(request: Dict[str, Any]) -> int:
    """Count tool invocations in a request's response array."""
    count = 0
    for item in request.get('response', []):
        if item.get('kind') == 'toolInvocationSerialized':
            count += 1
    return count


def count_user_edits(request: Dict[str, Any]) -> Tuple[int, int]:
    """Count user edits and terminal invocations. Returns (edit_count, terminal_count)."""
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


def get_tool_distribution(request: Dict[str, Any]) -> Dict[str, int]:
    """Get count of each tool type used in a request."""
    distribution: Dict[str, int] = {}
    
    for item in request.get('response', []):
        if item.get('kind') == 'toolInvocationSerialized':
            tool_id = item.get('toolId', 'unknown')
            distribution[tool_id] = distribution.get(tool_id, 0) + 1
    
    return distribution


def count_tool_successes(request: Dict[str, Any]) -> int:
    """Count successfully completed tool invocations."""
    successes = 0
    
    for item in request.get('response', []):
        if item.get('kind') != 'toolInvocationSerialized':
            continue
        if item.get('isComplete', False):
            successes += 1
    
    return successes


def get_rounds_info(request: Dict[str, Any]) -> Tuple[int, int]:
    """Get tool round and retry information. Returns (round_count, retry_count)."""
    result = request.get('result', {})
    metadata = result.get('metadata', {})
    rounds = metadata.get('toolCallRounds', [])
    
    round_count = len(rounds)
    retry_count = sum(r.get('toolInputRetry', 0) for r in rounds)
    
    return round_count, retry_count


def count_read_write_operations(requests: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    """Count read/write operations and file modifications. Returns (read_ops, write_ops, file_mods)."""
    read_ops = 0
    write_ops = 0
    file_mods = 0
    
    for request in requests:
        for item in request.get('response', []):
            if item.get('kind') != 'toolInvocationSerialized':
                continue
            
            tool_id = item.get('toolId', '')
            
            if tool_id in READ_TOOLS:
                read_ops += 1
            if tool_id in WRITE_TOOLS:
                write_ops += 1
            if tool_id in FILE_MODIFICATION_TOOLS:
                file_mods += 1
    
    return read_ops, write_ops, file_mods


def extract_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract all metrics from chat data.
    
    Args:
        data: Parsed chat export data.
    
    Returns:
        Dictionary containing metadata and computed metrics.
    """
    requests = data.get('requests', [])
    
    # Collect metadata (session/model info)
    metadata = {}
    if requests:
        first_request = requests[0]
        metadata['session_id'] = hashlib.sha256(
            first_request.get('requestId', '').encode()
        ).hexdigest()[:16]
        metadata['model_id'] = first_request.get('modelId', '')
    
    # Compute metrics
    metrics = {}
    
    if not requests:
        metrics = {
            "total_requests": 0,
            "total_tool_invocations": 0,
            "user_edit_count": 0,
            "terminal_invocations": 0,
            "user_edit_rate": 0.0,
            "tool_success_count": 0,
            "tool_success_rate": 0.0,
            "session_duration_ms": 0,
            "total_rounds": 0,
            "retry_count": 0,
            "tool_retry_rate": 0.0,
            "invocations_per_request": 0.0,
            "unique_tools_used": 0,
            "file_modifications": 0,
            "read_operations": 0,
            "write_operations": 0,
            "read_write_ratio": 0.0,
        }
    else:
        # Basic counts
        total_requests = len(requests)
        total_invocations = sum(count_tool_invocations(r) for r in requests)
        
        # User edit metrics
        total_edits = 0
        total_terminals = 0
        for r in requests:
            edits, terminals = count_user_edits(r)
            total_edits += edits
            total_terminals += terminals
        
        user_edit_rate = total_edits / total_terminals if total_terminals > 0 else 0.0
        
        # Tool success metrics
        total_successes = sum(count_tool_successes(r) for r in requests)
        tool_success_rate = total_successes / total_invocations if total_invocations > 0 else 0.0
        
        # Session timing
        first_timestamp = requests[0].get('timestamp', 0)
        last_completed = None
        for r in reversed(requests):
            model_state = r.get('modelState', {})
            if model_state and 'completedAt' in model_state:
                last_completed = model_state['completedAt']
                break
        
        session_duration_ms = (last_completed - first_timestamp) if last_completed else 0
        
        # Round metrics
        total_rounds = 0
        total_retries = 0
        for r in requests:
            rounds, retries = get_rounds_info(r)
            total_rounds += rounds
            total_retries += retries
        
        tool_retry_rate = total_retries / total_rounds if total_rounds > 0 else 0.0
        
        # Tool distribution
        all_tools: Set[str] = set()
        for r in requests:
            dist = get_tool_distribution(r)
            all_tools.update(dist.keys())
        
        unique_tools = len(all_tools)
        invocations_per_request = total_invocations / total_requests if total_requests > 0 else 0.0
        
        # Read/write metrics
        read_ops, write_ops, file_mods = count_read_write_operations(requests)
        read_write_ratio = read_ops / write_ops if write_ops > 0 else 0.0
        
        metrics = {
            "total_requests": total_requests,
            "total_tool_invocations": total_invocations,
            "user_edit_count": total_edits,
            "terminal_invocations": total_terminals,
            "user_edit_rate": round(user_edit_rate, 4),
            "tool_success_count": total_successes,
            "tool_success_rate": round(tool_success_rate, 4),
            "session_duration_ms": session_duration_ms,
            "total_rounds": total_rounds,
            "retry_count": total_retries,
            "tool_retry_rate": round(tool_retry_rate, 4),
            "invocations_per_request": round(invocations_per_request, 2),
            "unique_tools_used": unique_tools,
            "file_modifications": file_mods,
            "read_operations": read_ops,
            "write_operations": write_ops,
            "read_write_ratio": round(read_write_ratio, 2),
        }
    
    # Combine metadata and metrics
    return {**metadata, **metrics}


# =============================================================================
# Sanitization
# =============================================================================

# Keys that should have their string values fully encrypted
FULL_ENCRYPT_KEYS = frozenset([
    'text', 'original', 'userEdited', 'toolEdited', 'arguments',
    'fsPath', 'path', 'external', 'terminalCommandOutput'
])

# Keys that contain paths and should be path-sanitized
PATH_KEYS = frozenset([
    'value', 'response', 'invocationMessage', 'pastTenseMessage'
])

# Keys for URI objects that contain paths
URI_KEYS = frozenset([
    'baseUri', 'inlineReference', 'uri', 'terminalCommandUri'
])


def _sanitize_value(value: Any, secret: bytes, key: str = '') -> Any:
    """
    Recursively sanitize a value, encrypting strings containing PII.
    
    Args:
        value: The value to sanitize (can be any JSON type).
        secret: Encryption secret.
        key: The key name associated with this value (for context).
    
    Returns:
        Sanitized copy of the value.
    """
    if value is None:
        return None
    
    if isinstance(value, str):
        if not value:
            return value
        # Already encrypted - skip
        if value.startswith(f"{SANITIZATION_MARKER}:"):
            return value
        # Full encryption for known PII keys
        if key in FULL_ENCRYPT_KEYS:
            return encrypt_field(value, secret)
        # Path encryption for text content keys
        if key in PATH_KEYS:
            return encrypt_paths_in_text(value, secret)
        # Check if string looks like a path and encrypt it
        for pattern in PATH_PATTERNS:
            if pattern.search(value):
                return encrypt_paths_in_text(value, secret)
        return value
    
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            # Handle URI objects specially - encrypt path fields
            if k in URI_KEYS and isinstance(v, dict):
                result[k] = _sanitize_uri_object(v, secret)
            # Handle 'uris' dict mapping - keys are file URIs that contain paths
            elif k == 'uris' and isinstance(v, dict):
                # Encrypt both the keys (file URIs) and values (URI objects)
                encrypted_uris = {}
                for uri_key, uri_val in v.items():
                    # Encrypt the key if it contains a path pattern
                    new_key = uri_key
                    for pattern in PATH_PATTERNS:
                        if pattern.search(uri_key):
                            new_key = encrypt_field(uri_key, secret)
                            break
                    encrypted_uris[new_key] = _sanitize_uri_object(uri_val, secret)
                result[k] = encrypted_uris
            # Handle resultDetails array of URIs
            elif k == 'resultDetails' and isinstance(v, list):
                result[k] = [_sanitize_uri_object(item, secret) for item in v]
            else:
                result[k] = _sanitize_value(v, secret, k)
        return result
    
    if isinstance(value, list):
        return [_sanitize_value(item, secret, key) for item in value]
    
    # Numbers, booleans, etc. pass through unchanged
    return value


def _sanitize_uri_object(uri_obj: Any, secret: bytes) -> Any:
    """
    Sanitize a URI object, encrypting all path-related fields.
    
    Args:
        uri_obj: URI object (dict with fsPath, path, external, etc.)
        secret: Encryption secret.
    
    Returns:
        Sanitized URI object.
    """
    if not isinstance(uri_obj, dict):
        return uri_obj
    
    result = {}
    for k, v in uri_obj.items():
        if k in ('fsPath', 'path', 'external') and isinstance(v, str) and v:
            if not v.startswith(f"{SANITIZATION_MARKER}:"):
                result[k] = encrypt_field(v, secret)
            else:
                result[k] = v
        elif k == 'fragment' and isinstance(v, str):
            # Keep fragment as-is (usually just line numbers like "1-1")
            result[k] = v
        else:
            result[k] = _sanitize_value(v, secret, k)
    return result


def _unsanitize_value(value: Any, secret: bytes, key: str = '') -> Any:
    """
    Recursively unsanitize a value, decrypting encrypted strings.
    
    Args:
        value: The value to unsanitize (can be any JSON type).
        secret: Decryption secret.
        key: The key name associated with this value (for context).
    
    Returns:
        Unsanitized copy of the value.
    """
    if value is None:
        return None
    
    if isinstance(value, str):
        if not value:
            return value
        # Check for encrypted marker and decrypt
        if value.startswith(f"{SANITIZATION_MARKER}:"):
            return decrypt_field(value, secret)
        # Check for embedded encrypted paths
        if f"{SANITIZATION_MARKER}:" in value:
            return decrypt_paths_in_text(value, secret)
        return value
    
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            # Handle 'uris' dict mapping - keys may be encrypted file URIs
            if k == 'uris' and isinstance(v, dict):
                decrypted_uris = {}
                for uri_key, uri_val in v.items():
                    # Decrypt the key if it's encrypted
                    new_key = uri_key
                    if is_encrypted(uri_key):
                        new_key = decrypt_field(uri_key, secret)
                    decrypted_uris[new_key] = _unsanitize_value(uri_val, secret)
                result[k] = decrypted_uris
            else:
                result[k] = _unsanitize_value(v, secret, k)
        return result
    
    if isinstance(value, list):
        return [_unsanitize_value(item, secret, key) for item in value]
    
    return value


def sanitize_request(request: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Sanitize a single request, encrypting all PII fields.
    
    Args:
        request: The request dictionary to sanitize.
        secret: Encryption secret.
    
    Returns:
        Sanitized copy of the request.
    """
    return _sanitize_value(request, secret)


def unsanitize_request(request: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Unsanitize a single request, decrypting all encrypted fields.
    
    Uses recursive _unsanitize_value to handle all nested structures.
    
    Args:
        request: The sanitized request dictionary.
        secret: Decryption secret.
    
    Returns:
        Restored copy of the request.
    """
    return _unsanitize_value(request, secret)


def sanitize_chat(data: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Sanitize entire chat export.
    
    Args:
        data: Parsed chat export data.
        secret: Encryption secret.
    
    Returns:
        Sanitized copy with metadata marker.
    """
    result = {
        META_KEY: {
            "version": SANITIZATION_VERSION,
            "marker": SANITIZATION_MARKER,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "requests_count": len(data.get('requests', [])),
        }
    }
    
    # Copy non-request fields
    for key in data:
        if key == 'requests':
            result['requests'] = [
                sanitize_request(r, secret) for r in data['requests']
            ]
        else:
            result[key] = data[key]
    
    return result


def unsanitize_chat(data: Dict[str, Any], secret: bytes) -> Dict[str, Any]:
    """
    Unsanitize entire chat export.
    
    Args:
        data: Sanitized chat export data.
        secret: Decryption secret.
    
    Returns:
        Restored chat data without metadata marker.
    """
    result = {}
    
    for key in data:
        if key == META_KEY:
            continue  # Remove sanitization metadata
        elif key == 'requests':
            result['requests'] = [
                unsanitize_request(r, secret) for r in data['requests']
            ]
        else:
            result[key] = data[key]
    
    return result


# =============================================================================
# Output Formatting
# =============================================================================

def print_header(text: str, char: str = "=") -> None:
    """Print section header with separator lines."""
    print(f"\n{char * LINE_WIDTH}")
    print(f" {text}")
    print(f"{char * LINE_WIDTH}")


def print_metrics(metrics: Dict[str, Any]) -> None:
    """Print metrics summary with metadata and tiers."""
    print_header("CHAT METRICS SUMMARY")
    
    # Session metadata
    print_header("SESSION METADATA", "-")
    print(f"  Session ID:           {metrics.get('session_id', 'N/A')}")
    print(f"  Model ID:             {metrics.get('model_id', 'N/A')}")
    
    print_header("CORE METRICS (Tier 1)", "-")
    print(f"  Total Requests:       {metrics['total_requests']}")
    print(f"  Total Invocations:    {metrics['total_tool_invocations']}")
    print(f"  User Edit Count:      {metrics['user_edit_count']}")
    print(f"  Terminal Invocations: {metrics['terminal_invocations']}")
    print(f"  User Edit Rate:       {metrics['user_edit_rate']:.2%}")
    print(f"  Tool Success Count:   {metrics['tool_success_count']}")
    print(f"  Tool Success Rate:    {metrics['tool_success_rate']:.2%}")
    print(f"  Session Duration:     {metrics['session_duration_ms']:,} ms")
    
    print_header("SUPPORTING METRICS (Tier 2)", "-")
    print(f"  Total Rounds:         {metrics['total_rounds']}")
    print(f"  Retry Count:          {metrics['retry_count']}")
    print(f"  Tool Retry Rate:      {metrics['tool_retry_rate']:.2%}")
    print(f"  Invocations/Request:  {metrics['invocations_per_request']:.2f}")
    print(f"  Unique Tools Used:    {metrics['unique_tools_used']}")
    
    print_header("AGENTIC ACTIVITY (Tier 3)", "-")
    print(f"  File Modifications:   {metrics['file_modifications']}")
    print(f"  Read Operations:      {metrics['read_operations']}")
    print(f"  Write Operations:     {metrics['write_operations']}")
    print(f"  Read/Write Ratio:     {metrics['read_write_ratio']:.2f}")


def export_metrics_json(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as JSON file."""
    save_json(metrics, filepath)
    print(f"Metrics exported to: {filepath}")


def export_metrics_csv(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as CSV file (single row)."""
    fieldnames = list(metrics.keys())
    
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(metrics)
    
    print(f"Metrics exported to: {filepath}")


# =============================================================================
# Interactive Menu
# =============================================================================

def interactive_menu(data: Dict[str, Any], input_path: Path) -> None:
    """Run interactive menu for browsing and exporting chat data."""
    stem = input_path.stem
    parent = input_path.parent
    
    # Pre-compute metrics
    if is_sanitized(data):
        print("\nWarning: Input is sanitized. Metrics may not be accurate.")
        print("Use --unsanitize first to restore original data.\n")
    
    metrics = extract_metrics(data)
    
    while True:
        print_header("COPILOT CHAT PARSER")
        print("  1. Show metrics (print to terminal)")
        print("  2. Export metrics (JSON)")
        print("  3. Export metrics (CSV)")
        print("  4. Export sanitized JSON")
        print("  q. Quit")
        
        choice = input("\nEnter choice: ").strip().lower()
        
        if choice == 'q':
            print("Exiting.")
            break
        elif choice == '1':
            print_metrics(metrics)
        elif choice == '2':
            output_path = parent / f"metrics_{stem}.json"
            export_metrics_json(metrics, output_path)
        elif choice == '3':
            output_path = parent / f"metrics_{stem}.csv"
            export_metrics_csv(metrics, output_path)
        elif choice == '4':
            secret = os.environ.get('CHAT_PARSER_SECRET', '').encode('utf-8')
            if not secret:
                print("\nError: CHAT_PARSER_SECRET environment variable not set.")
                print("Set it with: export CHAT_PARSER_SECRET='your-secret-key'")
            elif is_sanitized(data):
                print("\nError: Data is already sanitized.")
            else:
                sanitized = sanitize_chat(data, secret)
                output_path = parent / f"sanitized_{stem}.json"
                save_json(sanitized, output_path)
                print(f"\nSanitized export saved to: {output_path}")
        else:
            print("Invalid choice. Please try again.")
        
        input("\nPress Enter to continue...")


# =============================================================================
# CLI
# =============================================================================

def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        prog="copilot_chat_parser.py",
        description="CLI utility for analyzing GitHub Copilot chat exports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Interactive mode (default):
    ./copilot_chat_parser.py chat.json

  Extract metrics:
    ./copilot_chat_parser.py chat.json --metrics
    ./copilot_chat_parser.py chat.json --metrics --format json
    ./copilot_chat_parser.py chat.json --metrics --format csv

  Sanitize (requires CHAT_PARSER_SECRET env var):
    export CHAT_PARSER_SECRET='your-secret-key'
    ./copilot_chat_parser.py chat.json --sanitize
    ./copilot_chat_parser.py chat.json --sanitize -o sanitized.json

  Unsanitize (requires same secret):
    ./copilot_chat_parser.py sanitized.json --unsanitize
    ./copilot_chat_parser.py sanitized.json --unsanitize -o restored.json

Environment Variables:
  CHAT_PARSER_SECRET  Required for --sanitize and --unsanitize operations.
                      Must use the same secret for encrypt and decrypt.
        """
    )
    
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to the chat export JSON file"
    )
    
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Extract and export metrics (JSON + CSV by default)"
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
        help="Sanitize chat export (encrypt PII fields)"
    )
    
    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help="Unsanitize chat export (decrypt PII fields)"
    )
    
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file path (default: same directory as input)"
    )
    
    return parser


def main() -> int:
    """Main entry point. Returns exit code (0 for success, 1 for error)."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Validate input file
    if not args.input_file.exists():
        print(f"Error: File not found: {args.input_file}", file=sys.stderr)
        return 1
    
    # Load JSON data
    try:
        data = load_chat(args.input_file)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    
    stem = args.input_file.stem
    parent = args.input_file.parent
    
    # Handle --sanitize
    if args.sanitize:
        secret = os.environ.get('CHAT_PARSER_SECRET', '').encode('utf-8')
        if not secret:
            print("Error: CHAT_PARSER_SECRET environment variable not set.",
                  file=sys.stderr)
            return 1
        
        if is_sanitized(data):
            print("Error: Input is already sanitized.", file=sys.stderr)
            return 1
        
        sanitized = sanitize_chat(data, secret)
        output_path = args.output or (parent / f"sanitized_{stem}.json")
        save_json(sanitized, output_path)
        print(f"Sanitized export saved to: {output_path}")
        return 0
    
    # Handle --unsanitize
    if args.unsanitize:
        secret = os.environ.get('CHAT_PARSER_SECRET', '').encode('utf-8')
        if not secret:
            print("Error: CHAT_PARSER_SECRET environment variable not set.",
                  file=sys.stderr)
            return 1
        
        if not is_sanitized(data):
            print("Error: Input is not a sanitized file.", file=sys.stderr)
            return 1
        
        restored = unsanitize_chat(data, secret)
        output_path = args.output or (parent / f"unsanitized_{stem}.json")
        save_json(restored, output_path)
        print(f"Restored export saved to: {output_path}")
        return 0
    
    # Handle --metrics
    if args.metrics:
        if is_sanitized(data):
            print("Warning: Input is sanitized. Metrics extracted from sanitized data.",
                  file=sys.stderr)
        
        metrics = extract_metrics(data)
        
        if args.format == "json":
            output_path = args.output or (parent / f"metrics_{stem}.json")
            export_metrics_json(metrics, output_path)
        elif args.format == "csv":
            output_path = args.output or (parent / f"metrics_{stem}.csv")
            export_metrics_csv(metrics, output_path)
        else:
            # Export both formats
            json_path = parent / f"metrics_{stem}.json"
            csv_path = parent / f"metrics_{stem}.csv"
            export_metrics_json(metrics, json_path)
            export_metrics_csv(metrics, csv_path)
        
        return 0
    
    # Default: interactive mode
    interactive_menu(data, args.input_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
