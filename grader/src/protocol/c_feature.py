#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
C feature phase aggregator: AN1_c-AN6_c, GAN1_c-GAN6_c.
"""

from __future__ import annotations

from pathlib import Path

from . import feature_tests

IMPL = "c"
SUFFIX = "_c"

TESTS = (
    ("AN1", feature_tests.test_announcements_not_logged_in),
    ("AN2", feature_tests.test_announcements_invalid_url),
    ("AN3", feature_tests.test_announcements_none_found),
    ("AN4", feature_tests.test_announcements_default_days),
    ("AN5", feature_tests.test_announcements_custom_days),
    ("AN6", feature_tests.test_announcements_invalid_days),
    ("GAN1", feature_tests.test_general_not_logged_in),
    ("GAN2", feature_tests.test_general_invalid_days_low),
    ("GAN3", feature_tests.test_general_invalid_days_high),
    ("GAN4", feature_tests.test_general_none_found),
    ("GAN5", feature_tests.test_general_aggregation),
    ("GAN6", feature_tests.test_general_filtering),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str]]:
    """Run every C feature assertion and return the result mapping.

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
