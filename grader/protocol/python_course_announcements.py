#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Python course-announcements phase aggregator: P.2.1 through P.2.9.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import course_announcements_tests
from ._assertion_support import Result5
from .calibration import seed_instant

IMPL = "python"

TESTS: tuple[tuple[str, Callable[..., Result5]], ...] = (
    ("P.2.1", course_announcements_tests.test_course_not_logged_in),
    ("P.2.2", course_announcements_tests.test_course_bad_url),
    ("P.2.3", course_announcements_tests.test_course_negative_days),
    ("P.2.4", course_announcements_tests.test_course_empty_window),
    ("P.2.5", course_announcements_tests.test_course_days_zero),
    ("P.2.6", course_announcements_tests.test_course_zero_absolute),
    ("P.2.7", course_announcements_tests.test_course_default),
    ("P.2.8", course_announcements_tests.test_course_days_10),
    ("P.2.9", course_announcements_tests.test_course_days_40),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run every Python course-announcement assertion and return the result mapping.

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
