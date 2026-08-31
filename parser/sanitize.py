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
``ENC2:<base64-salt>:<base64-cipher>:<base64-tag>`` and carries no
plaintext metadata. A fresh random salt per file is stored alongside
the ciphertext so the keystream can be regenerated. The authentication
tag rejects an incorrect secret or modified ciphertext before plaintext
is written.

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

CIPHER_MARKER = "ENC2"
SALT_LENGTH_BYTES = 16
SECRET_ENV_VAR = "CC_PARSER_SECRET"
AUTHENTICATION_CONTEXT = b"bsc-apm-sanitizer-authentication"
ENCRYPTION_CONTEXT = b"bsc-apm-sanitizer-encryption"
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
    parser.add_argument(
        "--output",
        type=Path,
        help="Write a single input file to this new path; existing paths are rejected.",
    )
    args = parser.parse_args(argv)
    secret = _read_secret()
    if secret is None:
        return 1
    if args.unsanitize:
        return _run_unsanitize(args.path, secret, args.output)
    return _run_sanitize(args.path, secret, args.output)


def sanitise_file(path: Path, secret: bytes) -> str:
    """Return the sealed cipher line for one file's raw bytes.

    Args:
        path: Absolute path to the file to seal.
        secret: Encryption key, as raw bytes.

    Returns:
        The encoded ciphertext as a single
        ``ENC2:<base64-salt>:<base64-cipher>:<base64-tag>`` string.

    Raises:
        OSError: When the file cannot be read.
    """
    return _encrypt(path.read_bytes(), secret)


def unsanitise_to_bytes(encoded: str, secret: bytes) -> bytes:
    """Reverse a sealed cipher line and return the original bytes.

    Args:
        encoded: The ``ENC2:<base64-salt>:<base64-cipher>:<base64-tag>`` line
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


def _run_sanitize(path: Path, secret: bytes, output: Path | None = None) -> int:
    """Seal every file under ``path`` and write the artefacts in place.

    Writes a ``sanitized_<name>`` artefact next to each input,
    keeping the original file's full name so the round-trip can
    restore its extension.

    Args:
        path: Submission directory or single file to seal.
        secret: Secret bytes used to seal each file.
        output: Explicit destination for a single input file.

    Returns:
        ``0`` on success or ``1`` on failure.
    """
    if output is not None and not path.is_file():
        log.error("--output requires a single input file")
        return 1
    if output is not None and output.exists():
        log.error(f"output already exists: {output}")
        return 1
    try:
        files = discover_sanitisable_files(path)
    except SchemaError as error:
        log.error(str(error))
        return 1
    for input_file in files:
        sealed = sanitise_file(input_file, secret)
        output_path = output or input_file.parent / f"{SANITIZED_FILENAME_PREFIX}{input_file.name}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_file_text(output_path, sealed)
        log.info(f"sanitised: {input_file.name} -> {output_path.name}")
    return 0


def _run_unsanitize(path: Path, secret: bytes, output: Path | None = None) -> int:
    """Restore every sealed artefact under ``path`` to its original bytes.

    Walks every ``sanitized_*`` artefact under ``path`` so each one
    round-trips back to its original content, restoring the original
    filename by stripping the ``sanitized_`` prefix.

    Args:
        path: Sealed directory or single file to restore.
        secret: Secret bytes used to authenticate and restore each file.
        output: Explicit destination for a single input file.

    Returns:
        ``0`` on success or ``1`` on failure.
    """
    resolved = path.resolve()
    if not resolved.exists():
        log.error(f"path not found: {resolved}")
        return 1
    if output is not None and not resolved.is_file():
        log.error("--output requires a single input file")
        return 1
    if output is not None and output.exists():
        log.error(f"output already exists: {output}")
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
        output_path = output or input_file.parent / original_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
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
    """Encrypt and authenticate raw bytes, then return the encoded line.

    Args:
        plaintext: Raw bytes to seal.
        secret: Secret bytes used to derive the cipher keys.

    Returns:
        The encoded ciphertext and its authentication data.
    """
    salt = os.urandom(SALT_LENGTH_BYTES)
    encryption_key, authentication_key = _derive_keys(secret)
    keystream = _derive_keystream(encryption_key, salt, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream, strict=False))
    tag = hmac.new(
        authentication_key,
        CIPHER_MARKER.encode("ascii") + salt + ciphertext,
        hashlib.sha256,
    ).digest()
    salt_b64 = base64.b64encode(salt).decode("ascii")
    cipher_b64 = base64.b64encode(ciphertext).decode("ascii")
    tag_b64 = base64.b64encode(tag).decode("ascii")
    return f"{CIPHER_MARKER}:{salt_b64}:{cipher_b64}:{tag_b64}"


def _decrypt(encoded: str, secret: bytes) -> bytes:
    """Authenticate and reverse ``_encrypt`` with the same secret.

    Args:
        encoded: Encoded ciphertext and authentication data.
        secret: Secret bytes used to derive the cipher keys.

    Returns:
        The authenticated plaintext bytes.

    Raises:
        ValueError: When the input is malformed or authentication fails.
    """
    parts = encoded.split(":", 3)
    if len(parts) != 4 or parts[0] != CIPHER_MARKER:
        raise ValueError("sealed artefact has the wrong format")
    _, salt_b64, cipher_b64, tag_b64 = parts
    try:
        salt = base64.b64decode(salt_b64, validate=True)
        ciphertext = base64.b64decode(cipher_b64, validate=True)
        supplied_tag = base64.b64decode(tag_b64, validate=True)
    except ValueError as error:
        raise ValueError("sealed artefact has invalid base64 data") from error
    if len(salt) != SALT_LENGTH_BYTES or len(supplied_tag) != hashlib.sha256().digest_size:
        raise ValueError("sealed artefact has the wrong format")
    encryption_key, authentication_key = _derive_keys(secret)
    expected_tag = hmac.new(
        authentication_key,
        CIPHER_MARKER.encode("ascii") + salt + ciphertext,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied_tag, expected_tag):
        raise ValueError("authentication failed: wrong secret or modified ciphertext")
    keystream = _derive_keystream(encryption_key, salt, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False))


def _derive_keys(secret: bytes) -> tuple[bytes, bytes]:
    """Derive separate encryption and authentication keys from one secret.

    Args:
        secret: Source secret bytes.

    Returns:
        The encryption key followed by the authentication key.
    """
    encryption_key = hmac.new(secret, ENCRYPTION_CONTEXT, hashlib.sha256).digest()
    authentication_key = hmac.new(secret, AUTHENTICATION_CONTEXT, hashlib.sha256).digest()
    return encryption_key, authentication_key


def _derive_keystream(secret: bytes, salt: bytes, length: int) -> bytes:
    """Expand a salt into a keystream of the requested length via HMAC-SHA256.

    Args:
        secret: Encryption key bytes.
        salt: Per-file random salt.
        length: Required keystream length in bytes.

    Returns:
        A keystream of exactly ``length`` bytes.
    """
    keystream = bytearray()
    counter = 0
    while len(keystream) < length:
        block = hmac.new(
            secret,
            salt + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        keystream.extend(block)
        counter += 1
    return bytes(keystream[:length])


if __name__ == "__main__":
    sys.exit(main())
