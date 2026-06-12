#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""File input and output helpers shared across the parser package.

Two file formats matter to the package: the raw Claude Code JSONL
rollout (one JSON record per line) that comes in from a submission
directory, and the sanitised sidecar wrapper (a single JSON object
containing an HMAC-encrypted form of a JSONL file's full content
plus plaintext cataloguing metadata) that ships into the analysis
dataset. The helpers here cover reading and writing both formats
and a small classifier that distinguishes a sanitised sidecar from
a raw JSONL file at a glance.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .schema import KNOWN_RECORD_TYPES

SANITIZATION_META_KEY = "_sanitization_meta"


def iter_jsonl_lines(path: Path) -> Iterable[str]:
    """Yield each non-empty line of a JSONL file as a stripped string."""
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            stripped = line.strip()
            if not stripped:
                continue
            yield stripped


def read_file_text(path: Path) -> str:
    """Return the full text content of a file, decoded as UTF-8."""
    with path.open("r", encoding="utf-8") as source:
        return source.read()


def write_file_text(path: Path, text: str) -> None:
    """Write text content to a file as UTF-8."""
    with path.open("w", encoding="utf-8") as sink:
        sink.write(text)


def write_json(payload: Any, path: Path) -> None:
    """Write a JSON-serialisable payload to a file via an atomic replace.

    Serialises with two-space indentation and ``ensure_ascii=False`` so
    non-ASCII transcript content stays human-readable, writes the bytes to
    a temporary file in the destination directory, then atomically swaps it
    into place with ``os.replace`` so a reader never observes a partially
    written file.

    Args:
        payload: Any JSON-serialisable object.
        path: Destination file path. Its parent directory must exist.
    """
    serialised = json.dumps(payload, indent=2, ensure_ascii=False)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as sink:
        sink.write(serialised)
        temp_path = Path(sink.name)
    os.replace(temp_path, path)


def read_json(path: Path) -> Any:
    """Read and parse one JSON file."""
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def is_sanitised_payload(payload: Any) -> bool:
    """Return ``True`` when ``payload`` carries the sanitisation sidecar marker.

    A sanitised sidecar is a JSON object with the
    ``_sanitization_meta`` key set; the raw rollout has no such
    object at the top level (and is JSONL, not JSON).
    """
    return isinstance(payload, dict) and SANITIZATION_META_KEY in payload


def looks_like_jsonl(path: Path) -> bool:
    """Return ``True`` when the first non-empty line of a file decodes to a known record type.

    Used to distinguish a raw Claude Code JSONL file from a
    sanitised JSON sidecar without committing to a full parse.
    """
    try:
        for line in iter_jsonl_lines(path):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                return False
            if not isinstance(rec, dict):
                return False
            return rec.get("type") in KNOWN_RECORD_TYPES
    except OSError:
        return False
    return False
