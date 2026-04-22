#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Reversible sanitization of chat export payloads.

Sanitization encrypts the entire export body with an HMAC-SHA256 derived
keystream keyed off a caller-supplied secret, and wraps the ciphertext
in a sidecar object that preserves cataloguing metadata (timestamp,
original byte size, request count, chat identifier, model ids) in
plaintext. Unsanitization inverts the transform with the same secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from .io import META_KEY

SANITIZATION_MARKER = "ENC"
SALT_LENGTH_BYTES = 16


def sanitize_chat(data: dict[str, Any], secret: bytes) -> dict[str, Any]:
    """Return a sanitized wrapper around a chat export payload.

    Args:
        data: The decoded export JSON.
        secret: The encryption key.

    Returns:
        A dict with the sanitization metadata and an encrypted
        ``payload`` string.
    """
    requests = data.get("requests", [])
    if not isinstance(requests, list):
        requests = []
    user_messages = _collect_user_messages(requests)
    chat_id = _chat_id(user_messages)
    model_ids = _distinct_model_ids(requests)

    plaintext = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    encrypted_payload = _encrypt(plaintext, secret)

    return {
        META_KEY: {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original_size": len(plaintext),
            "requests_count": len(requests),
            "chat_id": chat_id,
            "model_ids": model_ids,
        },
        "payload": encrypted_payload,
    }


def unsanitize_chat(data: dict[str, Any], secret: bytes) -> dict[str, Any]:
    """Restore a sanitized chat export by decrypting its payload.

    Args:
        data: The sanitized wrapper produced by :func:`sanitize_chat`.
        secret: The decryption key. Must match the key used for
            encryption.

    Returns:
        The original export JSON.

    Raises:
        ValueError: If the ``payload`` field is missing or malformed.
        json.JSONDecodeError: If the decrypted payload is not valid JSON.
    """
    payload = data.get("payload")
    if not isinstance(payload, str) or not payload.startswith(f"{SANITIZATION_MARKER}:"):
        raise ValueError("Sanitized file missing 'payload' field or invalid format")
    plaintext = _decrypt(payload, secret)
    return json.loads(plaintext)


def _encrypt(plaintext: str, secret: bytes) -> str:
    """Encrypt a string with an HMAC-derived keystream and return an encoded form."""
    if not plaintext:
        return plaintext
    salt = os.urandom(SALT_LENGTH_BYTES)
    plaintext_bytes = plaintext.encode("utf-8")
    keystream = _derive_keystream(secret, salt, len(plaintext_bytes))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext_bytes, keystream))
    salt_b64 = base64.b64encode(salt).decode("ascii")
    cipher_b64 = base64.b64encode(ciphertext).decode("ascii")
    return f"{SANITIZATION_MARKER}:{salt_b64}:{cipher_b64}"


def _decrypt(encoded: str, secret: bytes) -> str:
    """Reverse :func:`_encrypt` given the same secret."""
    if not encoded or not encoded.startswith(f"{SANITIZATION_MARKER}:"):
        return encoded
    parts = encoded.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"Invalid encrypted format: {encoded[:50]}...")
    _, salt_b64, cipher_b64 = parts
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


def _collect_user_messages(requests: list[Any]) -> list[str]:
    """Extract user message text strings from an export's requests list."""
    texts: list[str] = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        message = request.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            if isinstance(text, str):
                texts.append(text)
    return texts


def _distinct_model_ids(requests: list[Any]) -> list[str]:
    """Return the sorted distinct ``modelId`` values observed across requests."""
    ids: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            continue
        model_id = request.get("modelId")
        if isinstance(model_id, str) and model_id:
            ids.add(model_id)
    return sorted(ids)


def _chat_id(user_messages: list[str]) -> str:
    """Return a stable 16-char hex identifier for a list of user messages."""
    combined = "".join(user_messages)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
