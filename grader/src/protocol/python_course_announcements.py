#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Python course-announcements phase aggregator: P.2.1 through P.2.8.
"""

from __future__ import annotations

from pathlib import Path

from . import course_announcements_tests

IMPL = "python"

TESTS = (
    ("P.2.1", course_announcements_tests.test_course_not_logged_in),
    ("P.2.2", course_announcements_tests.test_course_invalid_url),
    ("P.2.3", course_announcements_tests.test_course_negative_days),
    ("P.2.4", course_announcements_tests.test_course_empty_course),
    ("P.2.5", course_announcements_tests.test_course_days_zero),
    ("P.2.6", course_announcements_tests.test_course_days_15),
    ("P.2.7", course_announcements_tests.test_course_default),
    ("P.2.8", course_announcements_tests.test_course_days_60),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every Python course-announcement assertion and return the result mapping.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail)``.
    """
    return {
        test_id: assertion(IMPL, eclass_dir, mock_root, debug)
        for test_id, assertion in TESTS
    }
