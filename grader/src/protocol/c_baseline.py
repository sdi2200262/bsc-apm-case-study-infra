#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C baseline phase aggregator: C.2.1 through C.2.10.
"""

from __future__ import annotations

from pathlib import Path

from . import baseline_tests

IMPL = "c"

TESTS = (
    ("C.2.1", baseline_tests.test_initialize_and_tools_list),
    ("C.2.2", baseline_tests.test_login_success),
    ("C.2.3", baseline_tests.test_login_already_logged_in),
    ("C.2.4", baseline_tests.test_login_missing_credentials),
    ("C.2.5", baseline_tests.test_logout_success),
    ("C.2.6", baseline_tests.test_logout_no_op),
    ("C.2.7", baseline_tests.test_get_courses_logged_in),
    ("C.2.8", baseline_tests.test_get_courses_not_logged_in),
    ("C.2.9", baseline_tests.test_authstatus_logged_in),
    ("C.2.10", baseline_tests.test_authstatus_not_logged_in),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every C baseline assertion and return the result mapping.

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
