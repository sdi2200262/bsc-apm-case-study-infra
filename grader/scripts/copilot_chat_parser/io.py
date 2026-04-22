#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Input and output helpers for the parser package.

``load_chat`` reads a single chat export JSON file. ``save_json_report``
writes a full session report as pretty-printed JSON.
``save_csv_report`` writes a single-row CSV flattening of the report's
scalar fields for downstream consumption.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

META_KEY = "_sanitization_meta"


def load_chat(path: Path) -> dict[str, Any]:
    """Load and parse one Copilot chat export file.

    Args:
        path: Path to the export JSON file.

    Returns:
        The decoded JSON object.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file does not contain valid JSON.
    """
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def save_json_report(report: dict[str, Any], path: Path) -> None:
    """Write a session report to disk as UTF-8 JSON with two-space indent.

    Args:
        report: The report object assembled by ``build_report``.
        path: Destination path.

    Raises:
        OSError: If the file cannot be written.
    """
    with path.open("w", encoding="utf-8") as sink:
        json.dump(report, sink, indent=2, ensure_ascii=False)


def save_csv_report(report: dict[str, Any], path: Path) -> None:
    """Write the report's scalar fields to a single-row CSV.

    Nested sections are flattened with dotted keys (for example
    ``metrics.per_role.planner.mean_turn_duration_seconds``). Lists are
    joined with ``;``. Nested dicts inside the per-role and per-phase
    breakdowns expand into individual columns.

    Args:
        report: The report object assembled by ``build_report``.
        path: Destination path.

    Raises:
        OSError: If the file cannot be written.
    """
    row = _flatten_for_csv(report, prefix="")
    fieldnames = list(row.keys())
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def is_sanitized(data: dict[str, Any]) -> bool:
    """Return whether a loaded payload is a sanitized export.

    Args:
        data: The decoded JSON object from a loaded file.

    Returns:
        ``True`` when the payload carries the sanitization metadata
        marker, ``False`` otherwise.
    """
    return META_KEY in data


def _flatten_for_csv(value: Any, prefix: str) -> dict[str, Any]:
    """Flatten nested dicts into dotted-key scalar columns for CSV output."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, sub in value.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten_for_csv(sub, new_prefix))
    elif isinstance(value, list):
        flat[prefix] = ";".join(str(entry) for entry in value)
    else:
        flat[prefix] = value
    return flat
