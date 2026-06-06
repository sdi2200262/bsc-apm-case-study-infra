#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C general-announcements phase aggregator: C.4.1 through C.4.7.

All seven rows run with ``memcheck=True``; each records a functional
result under ``<id>`` and a memory sub-assertion under ``<id>.mem``
scored only if the functional assertion passed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import general_announcements_tests
from ._assertion_support import Result5, record_mem
from .calibration import seed_instant

IMPL = "c"

TESTS: tuple[tuple[str, Callable[..., Result5]], ...] = (
    ("C.4.1", general_announcements_tests.test_general_not_logged_in),
    ("C.4.2", general_announcements_tests.test_general_negative_days),
    ("C.4.3", general_announcements_tests.test_general_over_thirty),
    ("C.4.4", general_announcements_tests.test_general_days_zero),
    ("C.4.5", general_announcements_tests.test_general_days_5),
    ("C.4.6", general_announcements_tests.test_general_days_8),
    ("C.4.7", general_announcements_tests.test_general_default),
)


def run(
    eclass_dir: Path, mock_root: Path, debug: bool = False
) -> dict[str, tuple[bool, str, str, str | None]]:
    """Run every C general-announcement assertion and return the result mapping.

    All rows run under valgrind (``memcheck=True``). Each records a
    functional verdict ``<id>`` and a memory sub-assertion ``<id>.mem``
    that passes only when the functional assertion passed AND the
    valgrind run was leak-clean.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail,
        mode)``; the functional row carries the ``matching`` mode it
        was accepted under, the ``.mem`` sub-assertion carries
        ``None`` (a leak verdict is not a string match).
    """
    instant = seed_instant(mock_root)
    results: dict[str, tuple[bool, str, str, str | None]] = {}
    for test_id, fn in TESTS:
        ok, msg, detail, leak, mode = fn(
            IMPL, eclass_dir, mock_root, debug,
            instant=instant, memcheck=True,
        )
        results[test_id] = (ok, msg, detail, mode)
        no_verdict_msg = (
            f"skipped: {test_id} produced no leak verdict "
            "(server did not start)"
        )
        record_mem(results, test_id, ok, leak, no_verdict_msg)
    return results
