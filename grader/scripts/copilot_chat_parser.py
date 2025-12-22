#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Copilot Chat Parser - CLI utility for analyzing GitHub Copilot chat exports.

Provides:
- Project-level metric extraction with multi-file aggregation (JSON/CSV output)
- Reversible PII sanitization with zero data loss
- User behavior classification (Short/Protocol/Standard buckets)

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# =============================================================================
# Constants
# =============================================================================

SANITIZATION_VERSION = 1
SANITIZATION_MARKER = "ENC"
META_KEY = "_sanitization_meta"

# Regex patterns for path detection
PATH_PATTERNS = [
    re.compile(r'file:///[^\s"\'\]}>]+'),           # file:// URIs
    re.compile(r'/Users/[^\s"\'\]}>]+'),            # macOS paths
    re.compile(r'/home/[^\s"\'\]}>]+'),             # Linux paths
    re.compile(r'[A-Za-z]:\\[^\s"\'\]}>]+'),        # Windows paths
]

# APM Protocol Signatures for user behavior classification
# YAML frontmatter keys (case-insensitive, line starts with)
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

# Markdown headers (case-insensitive, substring match)
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

# Short input threshold
SHORT_INPUT_THRESHOLD = 50


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
# User Behavior Classification
# =============================================================================

def is_apm_protocol(text: str) -> bool:
    """
    Check if text contains APM protocol signatures.
    
    Args:
        text: User input text to classify.
    
    Returns:
        True if text contains any APM signature.
    """
    if not text:
        return False
    
    text_lower = text.lower()
    
    # Check for APM headers (substring match)
    for header in APM_HEADERS:
        if header in text_lower:
            return True
    
    # Check for YAML frontmatter keys (line starts with)
    lines = text_lower.split('\n')
    for line in lines:
        stripped = line.strip()
        for key in APM_YAML_KEYS:
            if stripped.startswith(key):
                return True
    
    return False


def classify_user_input(text: str) -> str:
    """
    Classify user input into one of three buckets.
    
    Classification order (mutually exclusive):
    1. Protocol: Contains APM signatures (checked first)
    2. Short: Length < 50 characters (checked second)
    3. Standard: Everything else
    
    Args:
        text: User input text to classify.
    
    Returns:
        One of: "protocol", "short", "standard"
    """
    if not text:
        return "short"
    
    # Check protocol first (regardless of length)
    if is_apm_protocol(text):
        return "protocol"
    
    # Then check short
    if len(text) < SHORT_INPUT_THRESHOLD:
        return "short"
    
    # Everything else is standard
    return "standard"


# =============================================================================
# Metric Extraction Helpers
# =============================================================================

def count_tool_invocations(request: Dict[str, Any]) -> int:
    """Count tool invocations in a request's response array."""
    count = 0
    for item in request.get('response', []):
        if item.get('kind') == 'toolInvocationSerialized':
            count += 1
    return count


def count_tool_successes(request: Dict[str, Any]) -> int:
    """Count successfully completed tool invocations."""
    successes = 0
    for item in request.get('response', []):
        if item.get('kind') != 'toolInvocationSerialized':
            continue
        if item.get('isComplete', False):
            successes += 1
    return successes


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


def get_rounds_info(request: Dict[str, Any]) -> Tuple[int, int]:
    """Get tool round and retry information. Returns (round_count, retry_count)."""
    result = request.get('result', {})
    metadata = result.get('metadata', {})
    rounds = metadata.get('toolCallRounds', [])
    
    round_count = len(rounds)
    retry_count = sum(r.get('toolInputRetry', 0) for r in rounds)
    
    return round_count, retry_count


def extract_user_text(request: Dict[str, Any]) -> Optional[str]:
    """Extract user message text from a request."""
    message = request.get('message', {})
    if message.get('role') == 'user':
        return message.get('text', '')
    return None


def get_timestamps(requests: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    """
    Get min and max timestamps from requests.
    
    Returns:
        Tuple of (min_timestamp, max_timestamp) in milliseconds, or (None, None) if empty.
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
        
        # Also check completedAt in modelState
        model_state = r.get('modelState', {})
        completed_at = model_state.get('completedAt')
        if completed_at is not None:
            if max_ts is None or completed_at > max_ts:
                max_ts = completed_at
    
    return min_ts, max_ts


def get_session_id(data: Dict[str, Any]) -> str:
    """Generate a session ID hash from the first request's requestId."""
    requests = data.get('requests', [])
    if requests:
        first_request = requests[0]
        request_id = first_request.get('requestId', '')
        return hashlib.sha256(request_id.encode()).hexdigest()[:16]
    return ''


def get_model_ids(data: Dict[str, Any]) -> Set[str]:
    """Extract all unique model IDs from chat data."""
    model_ids: Set[str] = set()
    for request in data.get('requests', []):
        model_id = request.get('modelId', '')
        if model_id:
            model_ids.add(model_id)
    return model_ids


# =============================================================================
# Raw Event Extraction (Per-File)
# =============================================================================

def extract_raw_events(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract raw event counts from a single chat file.
    
    Args:
        data: Parsed chat export data.
    
    Returns:
        Dictionary containing raw counts and user texts for aggregation.
    """
    requests = data.get('requests', [])
    
    # Initialize counters
    total_requests = len(requests)
    total_invocations = 0
    total_successes = 0
    total_edits = 0
    total_terminals = 0
    total_rounds = 0
    total_retries = 0
    
    # User behavior data
    user_texts: List[str] = []
    
    # Process each request
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
    
    # Get timestamps
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
        'session_id': get_session_id(data),
        'model_ids': get_model_ids(data),
    }


# =============================================================================
# Project-Level Aggregation
# =============================================================================

def aggregate_metrics(raw_events_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate raw events from multiple files into project-level metrics.
    
    Args:
        raw_events_list: List of raw event dictionaries from extract_raw_events.
    
    Returns:
        Dictionary with project_metadata and metrics.
    """
    # Aggregate counters
    total_requests = 0
    total_invocations = 0
    total_successes = 0
    total_edits = 0
    total_terminals = 0
    total_rounds = 0
    total_retries = 0
    
    # Collect all user texts
    all_user_texts: List[str] = []
    
    # Track timestamps
    global_min_ts: Optional[int] = None
    global_max_ts: Optional[int] = None
    
    # Collect session IDs and model IDs
    session_ids: List[str] = []
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
        
        if events['session_id']:
            session_ids.append(events['session_id'])
        
        all_model_ids.update(events['model_ids'])
    
    # Calculate Tier 1: Reliability rates
    tool_success_rate = total_successes / total_invocations if total_invocations > 0 else 0.0
    tool_retry_rate = total_retries / total_rounds if total_rounds > 0 else 0.0
    user_edit_rate = total_edits / total_terminals if total_terminals > 0 else 0.0
    
    # Calculate Tier 2: Volume
    session_duration_minutes = 0.0
    if global_min_ts is not None and global_max_ts is not None:
        session_duration_minutes = (global_max_ts - global_min_ts) / 60000.0
    
    # Calculate Tier 3 & 4: User behavior classification
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
        else:  # standard
            count_standard += 1
            chars_standard += text_len
    
    # Calculate ratios (Tier 3)
    total_classified = len(all_user_texts)
    ratio_short = count_short / total_classified if total_classified > 0 else 0.0
    ratio_protocol = count_protocol / total_classified if total_classified > 0 else 0.0
    ratio_standard = count_standard / total_classified if total_classified > 0 else 0.0
    
    # Calculate average chars (Tier 4)
    avg_chars_short = chars_short / count_short if count_short > 0 else 0.0
    avg_chars_protocol = chars_protocol / count_protocol if count_protocol > 0 else 0.0
    avg_chars_standard = chars_standard / count_standard if count_standard > 0 else 0.0
    
    # Format timestamps as ISO strings
    global_start = None
    global_end = None
    if global_min_ts is not None:
        global_start = datetime.fromtimestamp(global_min_ts / 1000, tz=timezone.utc).isoformat()
    if global_max_ts is not None:
        global_end = datetime.fromtimestamp(global_max_ts / 1000, tz=timezone.utc).isoformat()
    
    return {
        "project_metadata": {
            "file_count": len(raw_events_list),
            "session_ids": session_ids,
            "unique_model_ids": sorted(list(all_model_ids)),
            "global_start": global_start,
            "global_end": global_end,
        },
        "metrics": {
            # Tier 1: Reliability
            "tool_success_rate": round(tool_success_rate, 4),
            "tool_retry_rate": round(tool_retry_rate, 4),
            "user_edit_rate": round(user_edit_rate, 4),
            # Tier 2: Volume
            "total_requests": total_requests,
            "session_duration_minutes": round(session_duration_minutes, 2),
            # Tier 3: Behavior Distribution
            "ratio_short_inputs": round(ratio_short, 4),
            "ratio_protocol_inputs": round(ratio_protocol, 4),
            "ratio_standard_inputs": round(ratio_standard, 4),
            # Tier 4: Behavior Magnitude
            "avg_chars_short": round(avg_chars_short, 2),
            "avg_chars_protocol": round(avg_chars_protocol, 2),
            "avg_chars_standard": round(avg_chars_standard, 2),
        }
    }


def extract_project_metrics(data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract project-level metrics from multiple chat files.
    
    Args:
        data_list: List of parsed chat export data dictionaries.
    
    Returns:
        Dictionary with project_metadata and metrics.
    """
    raw_events_list = [extract_raw_events(data) for data in data_list]
    return aggregate_metrics(raw_events_list)


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

def export_metrics_json(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as JSON file."""
    save_json(metrics, filepath)
    print(f"Metrics exported to: {filepath}")


def export_metrics_csv(metrics: Dict[str, Any], filepath: Path) -> None:
    """Export metrics as CSV file (single row with flattened structure)."""
    # Flatten project_metadata and metrics into single row
    row = {}
    
    # Flatten project_metadata
    pm = metrics.get('project_metadata', {})
    row['file_count'] = pm.get('file_count', 0)
    row['session_ids'] = ';'.join(pm.get('session_ids', []))
    row['unique_model_ids'] = ';'.join(pm.get('unique_model_ids', []))
    row['global_start'] = pm.get('global_start', '')
    row['global_end'] = pm.get('global_end', '')
    
    # Flatten metrics
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
        prog="copilot_chat_parser.py",
        description="CLI utility for analyzing GitHub Copilot chat exports with project-level aggregation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Extract project-level metrics from multiple files:
    ./copilot_chat_parser.py chat1.json chat2.json chat3.json --metrics
    ./copilot_chat_parser.py *.json --metrics --format json
    ./copilot_chat_parser.py *.json --metrics --format csv

  Sanitize files individually (requires CHAT_PARSER_SECRET env var):
    export CHAT_PARSER_SECRET='your-secret-key'
    ./copilot_chat_parser.py chat1.json chat2.json --sanitize

  Unsanitize files individually (requires same secret):
    ./copilot_chat_parser.py sanitized1.json sanitized2.json --unsanitize

Environment Variables:
  CHAT_PARSER_SECRET  Required for --sanitize and --unsanitize operations.
                      Must use the same secret for encrypt and decrypt.
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
        help="Sanitize chat exports (encrypt PII fields) - processes each file individually"
    )
    
    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help="Unsanitize chat exports (decrypt PII fields) - processes each file individually"
    )
    
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file path for metrics (default: metrics_project.json/csv in first file's directory)"
    )
    
    return parser


def main() -> int:
    """Main entry point. Returns exit code (0 for success, 1 for error)."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Validate all input files exist
    for input_file in args.input_files:
        if not input_file.exists():
            print(f"Error: File not found: {input_file}", file=sys.stderr)
            return 1
    
    # Handle --sanitize (file-by-file)
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
    
    # Handle --unsanitize (file-by-file)
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
            
            restored = unsanitize_chat(data, secret)
            output_path = input_file.parent / f"unsanitized_{input_file.name}"
            save_json(restored, output_path)
            print(f"Restored export saved to: {output_path}")
        
        return 0
    
    # Handle --metrics (aggregation mode)
    if args.metrics:
        data_list = []
        has_sanitized_warning = False
        
        for input_file in args.input_files:
            try:
                data = load_chat(input_file)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON in {input_file}: {e}", file=sys.stderr)
                return 1
            except OSError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1
            
            if is_sanitized(data) and not has_sanitized_warning:
                print("Warning: One or more input files are sanitized. "
                      "Metrics extracted from sanitized data.", file=sys.stderr)
                has_sanitized_warning = True
            
            data_list.append(data)
        
        metrics = extract_project_metrics(data_list)
        
        # Determine output paths
        first_parent = args.input_files[0].parent
        
        if args.format == "json":
            output_path = args.output or (first_parent / "metrics_project.json")
            export_metrics_json(metrics, output_path)
        elif args.format == "csv":
            output_path = args.output or (first_parent / "metrics_project.csv")
            export_metrics_csv(metrics, output_path)
        else:
            # Export both formats
            json_path = args.output.with_suffix('.json') if args.output else (first_parent / "metrics_project.json")
            csv_path = args.output.with_suffix('.csv') if args.output else (first_parent / "metrics_project.csv")
            export_metrics_json(metrics, json_path)
            export_metrics_csv(metrics, csv_path)
        
        return 0
    
    # No action specified - show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
