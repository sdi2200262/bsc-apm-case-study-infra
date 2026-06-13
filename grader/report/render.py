# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Console grading summary: the human-readable run view.

Prints each rubric group's strict score against its maximum and, in
verbose mode, every row's pass/fail status and short message, then the
review and warning notices. The eight report groups here roll the
rubric's two memory budget groups (multi-step and per-scenario) into one
"C MEMORY" group, so they cover the nine budget groups the scorer
enforces.
"""

from __future__ import annotations

from .. import log
from ..scoring.rubric import (
    C_BASELINE_TESTS,
    C_COURSE_TESTS,
    C_GENERAL_TESTS,
    C_INFRA_TESTS,
    C_MEMORY_TESTS,
    PYTHON_BASELINE_TESTS,
    PYTHON_COURSE_TESTS,
    PYTHON_GENERAL_TESTS,
    TestDefinition,
)
from ..scoring.scoring import Scorer
from .build import ReportPaths
from .notices import collect_notices

VERBOSE_MESSAGE_LIMIT = 60

GROUP_LAYOUT: tuple[tuple[str, tuple[TestDefinition, ...]], ...] = (
    ("PYTHON BASELINE", PYTHON_BASELINE_TESTS),
    ("PYTHON COURSE", PYTHON_COURSE_TESTS),
    ("PYTHON GENERAL", PYTHON_GENERAL_TESTS),
    ("C INFRA", C_INFRA_TESTS),
    ("C BASELINE", C_BASELINE_TESTS),
    ("C COURSE", C_COURSE_TESTS),
    ("C GENERAL", C_GENERAL_TESTS),
    ("C MEMORY", C_MEMORY_TESTS),
)


def print_console_summary(paths: ReportPaths, scorer: Scorer, verbose: bool = False) -> None:
    """Print the summary block to stdout, with optional per-test detail.

    Args:
        paths: Report path resolution from ``report_paths``.
        scorer: Populated scorer for the totals.
        verbose: When ``True``, prints each rubric row's status
            and short message under the matching group header.
    """
    log.blank()
    log.line()
    log.info("GRADING SUMMARY")
    log.line()

    if verbose:
        _print_verbose(scorer)

    for header, tests in GROUP_LAYOUT:
        group_score, group_max = _group_totals(scorer, tests)
        log.info(f"{header.title():18s} {group_score:3d}/{group_max:<3d}")
    log.line()
    py_total = scorer.python_total_score()
    c_total = scorer.c_score()
    grand = scorer.total_score()
    log.info(f"Python Total:      {py_total[0]:3d}/{py_total[1]:<3d}")
    log.info(f"C Total:           {c_total[0]:3d}/{c_total[1]:<3d}")
    log.info(f"TOTAL:             {grand[0]:3d}/{grand[1]:<3d}")

    log.notice_block((n.tag, n.label, n.summary, n.detail) for n in collect_notices(scorer))
    log.blank()
    log.info(f"JSON report: {paths.json_path}")
    log.line()


def _group_totals(scorer: Scorer, tests: tuple[TestDefinition, ...]) -> tuple[int, int]:
    """Return ``(score, max)`` for one rubric group's tests."""
    score = 0
    group_max = 0
    for test in tests:
        group_max += test.points
        result = scorer.results.get(test.id)
        if result is not None and result.passed:
            score += test.points
    return score, group_max


def _print_verbose(scorer: Scorer) -> None:
    """Print per-test status under each rubric group header."""
    for header, tests in GROUP_LAYOUT:
        log.blank()
        log.info(f"{header}:")
        for test in tests:
            result = scorer.results.get(test.id)
            if result is None:
                continue
            status = "PASS" if result.passed else "FAIL"
            log.info(f"  {test.id} {status}: {_truncate(result.message, VERBOSE_MESSAGE_LIMIT)}")
    log.blank()


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` characters with an ellipsis suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
