#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Python baseline phase aggregator: P.1.1 through P.1.11.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import baseline_tests
from ._assertion_support import Result5

IMPL = "python"

TESTS: tuple[tuple[str, Callable[..., Result5]], ...] = (
    ("P.1.1", baseline_tests.test_tools_list),
    ("P.1.2", baseline_tests.test_authstatus_pre_login),
    ("P.1.3", baseline_tests.test_login_success),
    ("P.1.4", baseline_tests.test_authstatus_post_login),
    ("P.1.5", baseline_tests.test_login_already),
    ("P.1.6", baseline_tests.test_missing_credentials),
    ("P.1.7", baseline_tests.test_get_courses_logged_in),
    ("P.1.8", baseline_tests.test_logout_success),
    ("P.1.9", baseline_tests.test_authstatus_post_logout),
    ("P.1.10", baseline_tests.test_get_courses_not_logged_in),
    ("P.1.11", baseline_tests.test_logout_no_op),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run every Python baseline assertion and return the result mapping.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail,
        mode)`` where ``mode`` is the ``matching`` mode the row was
        accepted under, or ``None``.
    """
    results: dict[str, tuple[bool, str, str, str | None]] = {}
    for test_id, fn in TESTS:
        ok, msg, detail, _leak, mode = fn(IMPL, eclass_dir, mock_root, debug)
        results[test_id] = (ok, msg, detail, mode)
    return results
