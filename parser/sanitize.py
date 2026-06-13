# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Reversible sanitisation of participant submission files.

Participant submissions carry filesystem paths, branch names, and
free-form prompt text that can identify the participant: the raw
Claude Code JSONL conversations copied from
``~/.claude/projects/<dashed-cwd>/``, the cached tool-results, and
the ``solution.patch`` itself. This tool seals each file's raw bytes
inside an HMAC-derived keystream cipher so only the encrypted form
ships into the analysis dataset; a holder of the secret can reverse
the transform when a re-analysis needs the original bytes.

Sealing operates on raw bytes, so it is file-type agnostic and
applies uniformly to a conversation file, a cached tool result, or a
patch. The sealed artefact is a single text line of the form
``ENC:<base64-salt>:<base64-cipher>`` and carries no plaintext
metadata: the parser's data and metric artefacts already catalogue
every submission. A fresh random salt per file is stored alongside
the ciphertext so the keystream can be regenerated.

Invoked as ``python -m parser.sanitize <path> [--unsanitize]``, kept
separate from the parser's metric and inspection surface because it
shares none of its framework, rate-table, or session machinery. The
key comes from the ``CC_PARSER_SECRET`` environment variable (or a
``.env`` entry of the same name) and must match between sealing and
restoring; the arguments are documented on ``main``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from . import log
from .data.jsonl import read_file_text, write_file_bytes, write_file_text
from .data.schema import SchemaError

CIPHER_MARKER = "ENC"
SALT_LENGTH_BYTES = 16
SECRET_ENV_VAR = "CC_PARSER_SECRET"
# A sealed artefact keeps the original file's full name under this
# prefix, so unsanitisation strips the prefix to restore the name and
# discovery skips prefixed files so a repeated seal cannot seal an
# already-sealed file.
SANITIZED_FILENAME_PREFIX = "sanitized_"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, non-zero on error.
    """
    parser = argparse.ArgumentParser(
        prog="python -m parser.sanitize",
        description=(
            "Seal every file under a submission with CC_PARSER_SECRET, or "
            "restore the sealed files with --unsanitize."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help="A submission directory to walk recursively, or a single file.",
    )
    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help="Restore each sealed file to its original name in place.",
    )
    args = parser.parse_args(argv)
    secret = _read_secret()
    if secret is None:
        return 1
    if args.unsanitize:
        return _run_unsanitize(args.path, secret)
    return _run_sanitize(args.path, secret)


def sanitise_file(path: Path, secret: bytes) -> str:
    """Return the sealed cipher line for one file's raw bytes.

    Args:
        path: Absolute path to the file to seal.
        secret: Encryption key, as raw bytes.

    Returns:
        The encoded ciphertext as a single
        ``ENC:<base64-salt>:<base64-cipher>`` string.

    Raises:
        OSError: When the file cannot be read.
    """
    return _encrypt(path.read_bytes(), secret)


def unsanitise_to_bytes(encoded: str, secret: bytes) -> bytes:
    """Reverse a sealed cipher line and return the original bytes.

    Args:
        encoded: The ``ENC:<base64-salt>:<base64-cipher>`` line
            produced by ``sanitise_file``.
        secret: The decryption key. Must equal the secret used to
            encrypt.

    Returns:
        The raw bytes of the original file.

    Raises:
        ValueError: When the encoded line is malformed (missing the
            cipher marker or carrying unparseable base64 sections).
    """
    if not encoded.startswith(f"{CIPHER_MARKER}:"):
        raise ValueError("sealed artefact is missing the cipher marker or has the wrong format")
    return _decrypt(encoded, secret)


def discover_sanitisable_files(path: Path) -> list[Path]:
    """Return every file the sanitiser should seal under a submission path.

    Sealing works on raw bytes, so a directory is walked recursively
    and every file beneath it is sealed regardless of kind; a single
    file path seals just that file. The sealed ``sanitized_``
    artefacts are skipped, so a repeated seal cannot seal an
    already-sealed file.

    Args:
        path: A submission directory to walk, or a single file.

    Returns:
        Absolute paths in filesystem order.

    Raises:
        SchemaError: When the path does not exist, or a directory
            holds no sealable file.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise SchemaError(f"submission path not found: {resolved}")
    if resolved.is_file():
        return [resolved]
    sanitisable = sorted(
        candidate
        for candidate in resolved.rglob("*")
        if candidate.is_file() and not candidate.name.startswith(SANITIZED_FILENAME_PREFIX)
    )
    if not sanitisable:
        raise SchemaError(f"submission directory contains no files to seal: {resolved}")
    return sanitisable


def _run_sanitize(path: Path, secret: bytes) -> int:
    """Seal every file under ``path`` and write the artefacts in place.

    Writes a ``sanitized_<name>`` artefact next to each input,
    keeping the original file's full name so the round-trip can
    restore its extension.
    """
    try:
        files = discover_sanitisable_files(path)
    except SchemaError as error:
        log.error(str(error))
        return 1
    for input_file in files:
        sealed = sanitise_file(input_file, secret)
        output_path = input_file.parent / f"{SANITIZED_FILENAME_PREFIX}{input_file.name}"
        write_file_text(output_path, sealed)
        log.info(f"sanitised: {input_file.name} -> {output_path.name}")
    return 0


def _run_unsanitize(path: Path, secret: bytes) -> int:
    """Restore every sealed artefact under ``path`` to its original bytes.

    Walks every ``sanitized_*`` artefact under ``path`` so each one
    round-trips back to its original content, restoring the original
    filename by stripping the ``sanitized_`` prefix.
    """
    resolved = path.resolve()
    if not resolved.exists():
        log.error(f"path not found: {resolved}")
        return 1
    if resolved.is_file():
        candidates = [resolved]
    else:
        candidates = sorted(
            candidate
            for candidate in resolved.rglob(f"{SANITIZED_FILENAME_PREFIX}*")
            if candidate.is_file()
        )
    if not candidates:
        log.error(f"no sealed artefacts found at {resolved}")
        return 1
    processed = 0
    for input_file in candidates:
        try:
            encoded = read_file_text(input_file)
        except OSError as error:
            log.warn(f"skipping {input_file.name}: {error}")
            continue
        try:
            restored = unsanitise_to_bytes(encoded, secret)
        except ValueError as error:
            log.error(f"cannot unsanitize {input_file.name}: {error}")
            return 1
        original_name = input_file.name
        if original_name.startswith(SANITIZED_FILENAME_PREFIX):
            original_name = original_name[len(SANITIZED_FILENAME_PREFIX) :]
        output_path = input_file.parent / original_name
        write_file_bytes(output_path, restored)
        log.info(f"unsanitised: {input_file.name} -> {output_path.name}")
        processed += 1
    if processed == 0:
        log.error(f"no sealed artefacts matched at {resolved}")
        return 1
    return 0


def _read_secret() -> bytes | None:
    """Return the configured encryption key, or ``None`` after logging an error."""
    secret = os.environ.get(SECRET_ENV_VAR, "")
    if not secret:
        log.error(f"environment variable {SECRET_ENV_VAR} must be set for sanitisation operations")
        return None
    return secret.encode("utf-8")


def _encrypt(plaintext: bytes, secret: bytes) -> str:
    """Encrypt raw bytes with an HMAC-derived keystream and return the encoded line."""
    if not plaintext:
        return f"{CIPHER_MARKER}::"
    salt = os.urandom(SALT_LENGTH_BYTES)
    keystream = _derive_keystream(secret, salt, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream, strict=False))
    salt_b64 = base64.b64encode(salt).decode("ascii")
    cipher_b64 = base64.b64encode(ciphertext).decode("ascii")
    return f"{CIPHER_MARKER}:{salt_b64}:{cipher_b64}"


def _decrypt(encoded: str, secret: bytes) -> bytes:
    """Reverse ``_encrypt`` with the same secret."""
    parts = encoded.split(":", 2)
    if len(parts) != 3 or parts[0] != CIPHER_MARKER:
        raise ValueError(f"invalid encoded format: {encoded[:50]}...")
    _, salt_b64, cipher_b64 = parts
    if not salt_b64 and not cipher_b64:
        return b""
    salt = base64.b64decode(salt_b64)
    ciphertext = base64.b64decode(cipher_b64)
    keystream = _derive_keystream(secret, salt, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False))


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


if __name__ == "__main__":
    sys.exit(main())
