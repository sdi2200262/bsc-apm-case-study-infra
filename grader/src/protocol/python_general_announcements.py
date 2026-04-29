#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Python general-announcements phase aggregator: P.3.1 through P.3.6.
"""

from __future__ import annotations

from pathlib import Path

from . import general_announcements_tests

IMPL = "python"

TESTS = (
    ("P.3.1", general_announcements_tests.test_general_not_logged_in),
    ("P.3.2", general_announcements_tests.test_general_negative_days),
    ("P.3.3", general_announcements_tests.test_general_over_thirty),
    ("P.3.4", general_announcements_tests.test_general_days_zero),
    ("P.3.5", general_announcements_tests.test_general_days_15),
    ("P.3.6", general_announcements_tests.test_general_default_aggregation),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every Python general-announcement assertion and return the result mapping.

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
