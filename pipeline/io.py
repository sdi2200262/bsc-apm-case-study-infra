#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
File input and output helpers shared across the pipeline package.

The pipeline reads and writes three file formats: JSON for grader
results, parser metrics, combined artifacts, and the manifest itself;
CSV for the aggregated dataset; YAML for the optional ``pipeline.yaml``
config. This module covers the JSON helpers (with atomic writes via
sibling-tempfile rename) and the SHA-256 checksum helper the manifest
uses for integrity tracking. CSV helpers live in ``add_to_dataset.py``
because they are tightly coupled to that stage's column schema; YAML
loading lives in ``config.py`` because YAML is used only for one
config shape.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Read and parse one JSON file as UTF-8."""
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def write_json(payload: Any, path: Path) -> None:
    """Write a JSON-serialisable payload to a file with atomic tempfile rename.

    The write is atomic on POSIX: data is written to a sibling
    temporary file and renamed into place once the write completes.
    Concurrent readers see either the previous content or the new
    content, never a partial write.

    Args:
        payload: The JSON-serialisable data to write.
        path: Destination path. The parent directory must exist;
            this helper does not create intermediate directories.
    """
    temp_path = path.parent / f".{path.name}.tmp"
    with temp_path.open("w", encoding="utf-8") as sink:
        json.dump(payload, sink, indent=2, ensure_ascii=False)
        sink.flush()
    temp_path.rename(path)


def compute_checksum(path: Path) -> str:
    """Return the SHA-256 checksum of a file as ``"sha256:<hex>"``.

    Args:
        path: Path to the file to checksum.

    Returns:
        The checksum string with the algorithm prefix, suitable for
        storage in the manifest's stage entries.

    Raises:
        OSError: When the file cannot be read.
    """
    sha256 = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def validate_checksum(path: Path, expected: str) -> bool:
    """Verify a file's content against an expected ``"sha256:<hex>"`` checksum.

    Args:
        path: Path to the file to verify. The caller is responsible
            for confirming the file exists; this helper does not
            check, and a missing file surfaces as ``OSError`` from
            the underlying read.
        expected: The expected checksum string with prefix.

    Returns:
        ``True`` when the recomputed checksum equals ``expected``,
        ``False`` otherwise.

    Raises:
        OSError: When the file cannot be read.
    """
    return compute_checksum(path) == expected
