#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
C memory phase aggregator: C.5.1 through C.5.4.

Each scenario carries a ``gates_on`` tuple naming the rubric rows
its call sequence exercises. The aggregator skips a scenario
whose gates have not all already passed because valgrind on a
feature path the participant did not implement correctly verifies
leak hygiene on a short-circuited error path rather than on the
path the rubric awards points for; the skip records as a
zero-point fail with a structured message naming the missing
rows.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from . import memory_tests


def run(
    eclass_dir: Path,
    mock_root: Path,
    debug: bool = False,
    passed_tests: Iterable[str] = (),
) -> dict[str, tuple[bool, str, str]]:
    """Run every memory scenario whose feature gates have passed.

    Args:
        eclass_dir: Resolved eclass-mcp-server checkout path
            (the C replica lives at ``c-replica/`` beneath it).
        mock_root: Resolved testing environment install path.
        debug: Reserved for parity with the other aggregators;
            valgrind output is captured into the result detail.
        passed_tests: Rubric identifiers whose tests have already
            passed in this grading run. A scenario whose
            ``gates_on`` is not a subset of this set is skipped
            rather than driven under valgrind.

    Returns:
        Mapping of rubric identifier to ``(passed, summary, detail)``.
        Skipped scenarios appear in the mapping with
        ``passed=False`` and a message naming the gate(s) that
        did not pass.
    """
    del debug
    passed_set = frozenset(passed_tests)
    results: dict[str, tuple[bool, str, str]] = {}
    for scenario in memory_tests.SCENARIOS:
        missing = tuple(
            test_id for test_id in scenario.gates_on if test_id not in passed_set
        )
        if missing:
            reason = (
                f"{scenario.scenario_id}: skipped, feature gate did not pass "
                f"({', '.join(missing)})"
            )
            results[scenario.scenario_id] = (False, reason, reason)
            continue
        results[scenario.scenario_id] = memory_tests.run_scenario(
            scenario, eclass_dir, mock_root
        )
    return results
