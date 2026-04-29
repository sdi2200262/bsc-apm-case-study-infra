#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Grading-report writers: JSON, plain-text, and console summary.

The JSON report at ``<workspace>/results_<patch>.json`` is the
machine-readable artefact the pipeline's grade stage promotes; its
shape is fixed so downstream consumers continue to read it. The
text report at ``<workspace>/results_<patch>.txt`` and the console
summary share a layout that lists each rubric section with its
status, description, and short message; the eight sections (Python
baseline, Python course, Python general, C infra, C baseline, C
course, C general, C memory) mirror the rubric structure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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

CONSOLE_MESSAGE_LIMIT = 200
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
        txt_path: Full path to ``results_<patch>.txt``.
    """

    workspace_root: Path
    patch_name: str
    json_path: Path
    txt_path: Path


def report_paths(workspace_root: Path, patch_name: str) -> ReportPaths:
    """Resolve the JSON and text report paths for a grading run."""
    workspace_root = Path(workspace_root).resolve()
    return ReportPaths(
        workspace_root=workspace_root,
        patch_name=patch_name,
        json_path=workspace_root / f"results_{patch_name}.json",
        txt_path=workspace_root / f"results_{patch_name}.txt",
    )


def write_json(
    paths: ReportPaths,
    scorer: Scorer,
    metadata: dict | None = None,
) -> Path:
    """Write the machine-readable JSON report.

    Args:
        paths: Report path resolution from :func:`report_paths`.
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


def write_text(paths: ReportPaths, scorer: Scorer) -> Path:
    """Write the plain-text report.

    The layout has a header, one section per rubric bucket with
    per-test rows, and a summary block totalling each Python
    bucket and each C bucket plus the grand total.

    Args:
        paths: Report path resolution from :func:`report_paths`.
        scorer: Populated scorer whose totals drive the section
            headers and summary block.

    Returns:
        The text path that was written.
    """
    timestamp = datetime.now().isoformat()
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"GRADING REPORT: {paths.patch_name}")
    lines.append("=" * 70)
    lines.append(f"Generated: {timestamp}")
    lines.append("")

    for header, tests in SECTION_LAYOUT:
        section_score, section_max = _section_totals(scorer, tests)
        lines.extend(
            _section_lines(
                f"{header} ({section_score}/{section_max})",
                tests,
                scorer,
                CONSOLE_MESSAGE_LIMIT,
            )
        )

    lines.extend(_summary_lines(scorer))
    paths.txt_path.write_text("\n".join(lines), encoding="utf-8")
    return paths.txt_path


def print_console_summary(
    paths: ReportPaths, scorer: Scorer, verbose: bool = False
) -> None:
    """Print the summary block to stdout, with optional per-test detail.

    Args:
        paths: Report path resolution from :func:`report_paths`.
        scorer: Populated scorer for the totals.
        verbose: When ``True``, prints each rubric row's status
            and short message under the matching section header.
    """
    print("")
    print("=" * 50)
    print("GRADING SUMMARY")
    print("=" * 50)

    if verbose:
        _print_verbose(scorer)

    for line in _summary_lines(scorer):
        print(line)
    print("")
    print(f"  JSON report: {paths.json_path}")
    print(f"  Text report: {paths.txt_path}")
    print("=" * 50)


def _summary_lines(scorer: Scorer) -> list[str]:
    """Build the lines for the summary block at the foot of the report."""
    py_total = scorer.python_total_score()
    c_total = scorer.c_score()
    grand = scorer.total_score()

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("SUMMARY")
    lines.append("=" * 70)
    for header, tests in SECTION_LAYOUT:
        section_score, section_max = _section_totals(scorer, tests)
        label = header.title()
        lines.append(f"  {label:18s} {section_score:3d}/{section_max:<3d}")
    lines.append("  ----------------------------------------")
    lines.append(f"  Python Total:      {py_total[0]:3d}/{py_total[1]:<3d}")
    lines.append(f"  C Total:           {c_total[0]:3d}/{c_total[1]:<3d}")
    lines.append(f"  TOTAL:             {grand[0]:3d}/{grand[1]:<3d}")
    lines.append("")
    lines.append("=" * 70)
    return lines


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


def _section_lines(
    header: str,
    tests: tuple[TestDefinition, ...],
    scorer: Scorer,
    message_limit: int,
) -> list[str]:
    """Build the lines for one section of the text report."""
    lines = ["-" * 70, header, "-" * 70]
    for test in tests:
        result = scorer.results.get(test.id)
        if result is None:
            lines.append(f"  [SKIP] {test.id}: {test.description}")
            lines.append("          Not executed")
            continue
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"  [{status}] {test.id}: {test.description}")
        lines.append(f"          {_truncate(result.message, message_limit)}")
    lines.append("")
    return lines


def _print_verbose(scorer: Scorer) -> None:
    """Print per-test status under each rubric section header."""
    for header, tests in SECTION_LAYOUT:
        print(f"\n  {header}:")
        for test in tests:
            result = scorer.results.get(test.id)
            if result is None:
                continue
            status = "PASS" if result.passed else "FAIL"
            print(
                f"    [{status}] {test.id}: "
                f"{_truncate(result.message, VERBOSE_MESSAGE_LIMIT)}"
            )
    print("")


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` truncated to ``limit`` characters with an ellipsis suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
