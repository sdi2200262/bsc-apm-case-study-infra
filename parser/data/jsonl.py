# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""File input and output helpers shared across the parser package.

The package reads the raw Claude Code JSONL rollout (one JSON
record per line) that arrives in a submission directory, and reads
and writes the JSON data and metric artefacts it produces. It also
moves the sealed sanitisation artefacts: a sealed file holds a
single ``ENC:...`` cipher line as text, so sealing writes that line
as text and unsealing reads it back as text and writes the restored
original as raw bytes.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_file_text(path: Path) -> str:
    """Return the full text content of a file, decoded as UTF-8."""
    with path.open("r", encoding="utf-8") as source:
        return source.read()


def write_file_text(path: Path, text: str) -> None:
    """Write text content to a file as UTF-8."""
    with path.open("w", encoding="utf-8") as sink:
        sink.write(text)


def write_file_bytes(path: Path, data: bytes) -> None:
    """Write raw bytes to a file."""
    with path.open("wb") as sink:
        sink.write(data)


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
