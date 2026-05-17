#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C baseline phase aggregator: C.2.1 through C.2.10.

C.2.1 through C.2.3 and C.2.5 through C.2.10 are context-free
assertions from the uniform map. C.2.4 (missing-credentials) is
billed per implemented surface, so ``config_surface`` evaluates it
against the recorded C.1.3/C.1.4 verdicts passed in via
``passed_tests``, mirroring how the c_memory phase reads prior
results.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from . import baseline_tests, config_surface

IMPL = "c"

TESTS = (
    ("C.2.1", baseline_tests.test_initialize_and_tools_list),
    ("C.2.2", baseline_tests.test_login_success),
    ("C.2.3", baseline_tests.test_login_already_logged_in),
    ("C.2.5", baseline_tests.test_logout_success),
    ("C.2.6", baseline_tests.test_logout_no_op),
    ("C.2.7", baseline_tests.test_get_courses_logged_in),
    ("C.2.8", baseline_tests.test_get_courses_not_logged_in),
    ("C.2.9", baseline_tests.test_authstatus_logged_in),
    ("C.2.10", baseline_tests.test_authstatus_not_logged_in),
)


def run(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool = False,
    passed_tests: Iterable[str] = (),
) -> dict[str, tuple[bool, str, str]]:
    """Run every C baseline assertion and return the result mapping.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path.
        mock_root: Resolved testing environment install path.
        debug: When ``True``, server stdio is echoed to stdout.
        passed_tests: Rubric identifiers already passed in this run.
            C.2.4 reads ``"C.1.3"``/``"C.1.4"`` from this set to
            decide which surfaces it scores; the c config phase
            records both before this phase runs.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail)``.
    """
    passed_set = frozenset(passed_tests)
    results = {
        test_id: assertion(IMPL, eclass_dir, mock_root, debug)
        for test_id, assertion in TESTS
    }
    results["C.2.4"] = config_surface.test_missing_credentials_attributed(
        eclass_dir,
        mock_root,
        debug,
        env_surface_implemented="C.1.3" in passed_set,
        dotenv_surface_implemented="C.1.4" in passed_set,
    )
    return results
