#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C course-announcements phase aggregator: C.3.1 through C.3.8.
"""

from __future__ import annotations

from pathlib import Path

from . import course_announcements_tests

IMPL = "c"

TESTS = (
    ("C.3.1", course_announcements_tests.test_course_not_logged_in),
    ("C.3.2", course_announcements_tests.test_course_invalid_url),
    ("C.3.3", course_announcements_tests.test_course_negative_days),
    ("C.3.4", course_announcements_tests.test_course_empty_course),
    ("C.3.5", course_announcements_tests.test_course_days_zero),
    ("C.3.6", course_announcements_tests.test_course_days_15),
    ("C.3.7", course_announcements_tests.test_course_default),
    ("C.3.8", course_announcements_tests.test_course_days_60),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every C course-announcement assertion and return the result mapping.

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
