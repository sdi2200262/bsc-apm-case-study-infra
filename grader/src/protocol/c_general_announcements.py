#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C general-announcements phase aggregator: C.4.1 through C.4.6.
"""

from __future__ import annotations

from pathlib import Path

from . import general_announcements_tests

IMPL = "c"

TESTS = (
    ("C.4.1", general_announcements_tests.test_general_not_logged_in),
    ("C.4.2", general_announcements_tests.test_general_negative_days),
    ("C.4.3", general_announcements_tests.test_general_over_thirty),
    ("C.4.4", general_announcements_tests.test_general_days_zero),
    ("C.4.5", general_announcements_tests.test_general_days_15),
    ("C.4.6", general_announcements_tests.test_general_default_aggregation),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every C general-announcement assertion and return the result mapping.

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
