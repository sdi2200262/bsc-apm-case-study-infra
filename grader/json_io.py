# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""JSON file IO helpers: atomic write and read for the grader's artefacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json(payload: Any, path: Path) -> None:
    """Write a JSON-serialisable payload to a file via an atomic replace.

    Serialises with two-space indentation and ``ensure_ascii=False`` so
    non-ASCII response content stays human-readable, writes the bytes to
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
