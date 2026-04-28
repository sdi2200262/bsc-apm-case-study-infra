#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
C baseline phase aggregator: P1_c, P2_c, L1_c-L3_c, O1_c-O2_c, C1_c-C2_c, A1_c.
"""

from __future__ import annotations

from pathlib import Path

from . import baseline_tests

IMPL = "c"
SUFFIX = "_c"

TESTS = (
    ("P1", baseline_tests.test_initialize),
    ("P2", baseline_tests.test_tools_list),
    ("L1", baseline_tests.test_login_success),
    ("L2", baseline_tests.test_login_already_logged_in),
    ("L3", baseline_tests.test_login_missing_credentials),
    ("O1", baseline_tests.test_logout_success),
    ("O2", baseline_tests.test_logout_not_logged_in),
    ("C1", baseline_tests.test_courses_logged_in),
    ("C2", baseline_tests.test_courses_not_logged_in),
    ("A1", baseline_tests.test_authstatus_not_logged_in),
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
        Mapping of rubric identifier (with ``_c`` suffix) to
        ``(passed, summary, detail)``.
    """
    return {
        f"{test_id}{SUFFIX}": assertion(IMPL, eclass_dir, mock_root, debug)
        for test_id, assertion in TESTS
    }
