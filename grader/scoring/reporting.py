# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Grading-report writers: JSON and console summary.

The JSON report at ``<workspace>/results_<patch>.json`` is the
machine-readable artefact the pipeline's grade stage promotes; its
shape is fixed so downstream consumers continue to read it. The
console summary reports each rubric section's score against its
maximum; in verbose mode it also lists every row's pass/fail status
and short message. The eight sections (Python baseline, Python
course, Python general, C infra, C baseline, C course, C general, C
memory) mirror the rubric structure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import log
from .notices import collect_notices
from .scoring import (
    C_BASELINE_TESTS,
    C_COURSE_TESTS,
    C_GENERAL_TESTS,
    C_INFRA_TESTS,
    C_MEMORY_TESTS,
    PYTHON_BASELINE_TESTS,
    PYTHON_COURSE_TESTS,
    PYTHON_GENERAL_TESTS,
    Scorer,
    TestDefinition,
)

VERBOSE_MESSAGE_LIMIT = 60

SECTION_LAYOUT: tuple[tuple[str, tuple[TestDefinition, ...]], ...] = (
    ("PYTHON BASELINE", PYTHON_BASELINE_TESTS),
    ("PYTHON COURSE", PYTHON_COURSE_TESTS),
    ("PYTHON GENERAL", PYTHON_GENERAL_TESTS),
    ("C INFRA", C_INFRA_TESTS),
    ("C BASELINE", C_BASELINE_TESTS),
    ("C COURSE", C_COURSE_TESTS),
    ("C GENERAL", C_GENERAL_TESTS),
    ("C MEMORY", C_MEMORY_TESTS),
)


@dataclass(frozen=True)
class ReportPaths:
    """Output paths the report writer targets.

    Attributes:
        workspace_root: Resolved directory the reports are written
            into. The grader uses the parent of the eclass-mcp-server
            checkout so the reports sit beside the patched tree.
        patch_name: Stem the report filenames are derived from.
        json_path: Full path to ``results_<patch>.json``.
    """

    workspace_root: Path
    patch_name: str
    json_path: Path


def report_paths(workspace_root: Path, patch_name: str) -> ReportPaths:
    """Resolve the JSON report path for a grading run."""
    workspace_root = Path(workspace_root).resolve()
    return ReportPaths(
        workspace_root=workspace_root,
        patch_name=patch_name,
        json_path=workspace_root / f"results_{patch_name}.json",
    )


def write_json(
    paths: ReportPaths,
    scorer: Scorer,
    metadata: dict | None = None,
) -> Path:
    """Write the machine-readable JSON report.

    Args:
        paths: Report path resolution from ``report_paths``.
        scorer: Populated scorer whose ``to_dict`` output is
            embedded in the report.
        metadata: Optional extra fields merged into the report's
            ``metadata`` block.

    Returns:
        The JSON path that was written.
    """
    payload = {
        "metadata": {
            "patch_name": paths.patch_name,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        },
        **scorer.to_dict(),
    }
    paths.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return paths.json_path


def print_console_summary(
    paths: ReportPaths, scorer: Scorer, verbose: bool = False
) -> None:
    """Print the summary block to stdout, with optional per-test detail.

    Args:
        paths: Report path resolution from ``report_paths``.
        scorer: Populated scorer for the totals.
        verbose: When ``True``, prints each rubric row's status
            and short message under the matching section header.
    """
    log.blank()
    log.line()
    log.info("GRADING SUMMARY")
    log.line()

    if verbose:
        _print_verbose(scorer)

    for header, tests in SECTION_LAYOUT:
        section_score, section_max = _section_totals(scorer, tests)
        log.info(f"{header.title():18s} {section_score:3d}/{section_max:<3d}")
    log.line()
    py_total = scorer.python_total_score()
    c_total = scorer.c_score()
    grand = scorer.total_score()
    log.info(f"Python Total:      {py_total[0]:3d}/{py_total[1]:<3d}")
    log.info(f"C Total:           {c_total[0]:3d}/{c_total[1]:<3d}")
    log.info(f"TOTAL:             {grand[0]:3d}/{grand[1]:<3d}")

    log.notice_block(
        (n.tag, n.label, n.summary, n.detail) for n in collect_notices(scorer)
    )
    log.blank()
    log.info(f"JSON report: {paths.json_path}")
    log.line()


def _section_totals(
    scorer: Scorer, tests: tuple[TestDefinition, ...]
) -> tuple[int, int]:
    """Return ``(score, max)`` for one rubric section's tests."""
    score = 0
    section_max = 0
    for test in tests:
        section_max += test.points
        result = scorer.results.get(test.id)
        if result is not None and result.passed:
            score += test.points
    return score, section_max


def _print_verbose(scorer: Scorer) -> None:
    """Print per-test status under each rubric section header."""
    for header, tests in SECTION_LAYOUT:
        log.blank()
        log.info(f"{header}:")
        for test in tests:
            result = scorer.results.get(test.id)
            if result is None:
                continue
            status = "PASS" if result.passed else "FAIL"
            log.info(
                f"  {test.id} {status}: "
                f"{_truncate(result.message, VERBOSE_MESSAGE_LIMIT)}"
            )
    log.blank()


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` characters with an ellipsis suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
