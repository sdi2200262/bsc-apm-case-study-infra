#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Python general-announcements phase aggregator: P.3.1 through P.3.7.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import general_announcements_tests
from ._assertion_support import Result5
from .calibration import seed_instant

IMPL = "python"

TESTS: tuple[tuple[str, Callable[..., Result5]], ...] = (
    ("P.3.1", general_announcements_tests.test_general_not_logged_in),
    ("P.3.2", general_announcements_tests.test_general_negative_days),
    ("P.3.3", general_announcements_tests.test_general_over_thirty),
    ("P.3.4", general_announcements_tests.test_general_days_zero),
    ("P.3.5", general_announcements_tests.test_general_days_5),
    ("P.3.6", general_announcements_tests.test_general_days_8),
    ("P.3.7", general_announcements_tests.test_general_default),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run every Python general-announcement assertion and return the result mapping.

    The per-run seed instant is read once from the grading environment
    database and threaded into every row that constructs a date string.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail,
        mode)`` where ``mode`` is the ``matching`` mode the row was
        accepted under, or ``None``.
    """
    instant = seed_instant(mock_root)
    results: dict[str, tuple[bool, str, str, str | None]] = {}
    for test_id, fn in TESTS:
        ok, msg, detail, _leak, mode = fn(
            IMPL, eclass_dir, mock_root, debug, instant=instant
        )
        results[test_id] = (ok, msg, detail, mode)
    return results
