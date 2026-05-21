#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Reversible sanitisation of Claude Code JSONL conversation files.

Participant submissions arrive as raw JSONL files copied straight
from ``~/.claude/projects/<dashed-cwd>/``. Those files contain
filesystem paths in ``cwd`` fields, branch names in ``gitBranch``
fields, and free-form prompt text that may carry identifying
information about the participant. Before the chat content lands
in the analysis dataset alongside the metric output, the raw text
is sealed inside an HMAC-derived keystream cipher: the dataset
keeps the encrypted form for archival and the cataloguing
metadata in plaintext, and a holder of the secret can reverse the
transform if a future re-analysis needs to consult the raw text.

The cipher uses a fresh random salt per file. Decryption requires
the same secret used for encryption; the salt is stored alongside
the ciphertext in the sidecar so the keystream can be regenerated.

The sanitised sidecar is a JSON object with two keys:

* ``_sanitization_meta``: cataloguing metadata kept in plaintext
  so the dataset is searchable and listable without the secret.
  Carries the timestamp of sanitisation, the original file's byte
  size, the record count, the conversation's session id and Claude
  Code version, and the modal model identifier.
* ``payload``: the encoded ciphertext as a single string of the
  form ``ENC:<base64-salt>:<base64-cipher>``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import (
    SANITIZATION_META_KEY,
    iter_jsonl_lines,
    read_file_text,
)
from .schema import SYNTHETIC_MODEL_MARKER

CIPHER_MARKER = "ENC"
SALT_LENGTH_BYTES = 16


def sanitise_jsonl_file(path: Path, secret: bytes) -> dict[str, Any]:
    """Return the sanitised sidecar object for one Claude Code JSONL file.

    Args:
        path: Absolute path to a raw ``*.jsonl`` conversation file.
        secret: Encryption key, as raw bytes.

    Returns:
        A JSON-serialisable dict with ``_sanitization_meta`` and
        ``payload`` keys; the caller writes it to disk with the
        package's ``io.write_json`` helper.

    Raises:
        OSError: When the file cannot be read.
    """
    plaintext = read_file_text(path)
    encoded = _encrypt(plaintext, secret)
    metadata = _collect_metadata(path, plaintext)
    return {
        SANITIZATION_META_KEY: metadata,
        "payload": encoded,
    }


def unsanitise_to_text(payload: dict[str, Any], secret: bytes) -> str:
    """Reverse a sanitised sidecar object and return the original JSONL text.

    Args:
        payload: The decoded JSON object produced by
            :func:`sanitise_jsonl_file`.
        secret: The decryption key. Must equal the secret used for
            encryption.

    Returns:
        The plaintext content of the original ``*.jsonl`` file as a
        single string.

    Raises:
        ValueError: When the payload is malformed (missing
            ``payload`` key, missing cipher marker, or unparseable
            base64 sections).
    """
    encoded = payload.get("payload")
    if not isinstance(encoded, str) or not encoded.startswith(f"{CIPHER_MARKER}:"):
        raise ValueError("sidecar is missing the payload field or has the wrong format")
    return _decrypt(encoded, secret)


def _encrypt(plaintext: str, secret: bytes) -> str:
    """Encrypt a string with an HMAC-derived keystream and return an encoded form."""
    if not plaintext:
        return f"{CIPHER_MARKER}::"
    salt = os.urandom(SALT_LENGTH_BYTES)
    plaintext_bytes = plaintext.encode("utf-8")
    keystream = _derive_keystream(secret, salt, len(plaintext_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))
    salt_b64 = base64.b64encode(salt).decode("ascii")
    cipher_b64 = base64.b64encode(ciphertext).decode("ascii")
    return f"{CIPHER_MARKER}:{salt_b64}:{cipher_b64}"


def _decrypt(encoded: str, secret: bytes) -> str:
    """Reverse :func:`_encrypt` with the same secret."""
    parts = encoded.split(":", 2)
    if len(parts) != 3 or parts[0] != CIPHER_MARKER:
        raise ValueError(f"invalid encoded format: {encoded[:50]}...")
    _, salt_b64, cipher_b64 = parts
    if not salt_b64 and not cipher_b64:
        return ""
    salt = base64.b64decode(salt_b64)
    ciphertext = base64.b64decode(cipher_b64)
    keystream = _derive_keystream(secret, salt, len(ciphertext))
    plaintext_bytes = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    return plaintext_bytes.decode("utf-8")


def _derive_keystream(secret: bytes, salt: bytes, length: int) -> bytes:
    """Expand a salt into a keystream of the requested length via HMAC-SHA256."""
    keystream = b""
    counter = 0
    while len(keystream) < length:
        block = hmac.new(
            secret,
            salt + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        keystream += block
        counter += 1
    return keystream[:length]


def _collect_metadata(path: Path, plaintext: str) -> dict[str, Any]:
    """Extract plaintext cataloguing metadata from a JSONL file.

    Walks the file once to collect the record count, the
    conversation's session id (modal value), the Claude Code
    version, and the modal non-synthetic model identifier. These
    fields stay in plaintext so the dataset can be enumerated and
    sorted without unsealing each sidecar.
    """
    record_count = 0
    session_ids: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    models: Counter[str] = Counter()
    for line in iter_jsonl_lines(path):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        record_count += 1
        session_id = record.get("sessionId")
        if isinstance(session_id, str) and session_id:
            session_ids[session_id] += 1
        version = record.get("version")
        if isinstance(version, str) and version:
            versions[version] += 1
        if record.get("type") == "assistant":
            message = record.get("message")
            if isinstance(message, dict):
                model = message.get("model")
                if isinstance(model, str) and model and model != SYNTHETIC_MODEL_MARKER:
                    models[model] += 1
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "original_size_bytes": len(plaintext.encode("utf-8")),
        "record_count": record_count,
        "session_id": session_ids.most_common(1)[0][0] if session_ids else None,
        "cc_version": versions.most_common(1)[0][0] if versions else None,
        "model": models.most_common(1)[0][0] if models else None,
    }
