#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Grading-report writers: JSON and console summary.

The JSON report at ``<workspace>/results_<patch>.json`` is the
machine-readable artefact the pipeline's grade stage promotes; its
shape is fixed so downstream consumers continue to read it. The
console summary lists each rubric section with its status,
description, and short message; the eight sections (Python
baseline, Python course, Python general, C infra, C baseline, C
course, C general, C memory) mirror the rubric structure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .protocol.matching import (
    ANNOUNCEMENTS_UNORDERED,
    CAP_DOCUMENTED,
    DESCRIPTION_PRESENCE_ONLY,
    GET_COURSES_DOCUMENTED,
    LENIENT_MODES,
)
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
    all_tests,
)

VERBOSE_MESSAGE_LIMIT = 60
WARNING_RESPONSE_LIMIT = 800

# Plain-words label per lenient form for the human-facing WARNINGS
# block. ``LENIENT_MODES`` (imported from ``matching``) is the single
# source of which modes are lenient; this map is presentation only,
# and an unmapped future lenient mode falls back to a generic phrase
# so adding one still requires only the ``matching`` constant.
_LENIENT_FORM_PHRASE = {
    ANNOUNCEMENTS_UNORDERED: "accepted via the order-insensitive announcement form",
    GET_COURSES_DOCUMENTED: "accepted via the documented-clean get_courses form",
    CAP_DOCUMENTED: "accepted via the documented initialize.capabilities form",
    DESCRIPTION_PRESENCE_ONLY: (
        "accepted via the presence-only description check; "
        "review the participant's wording in the response below"
    ),
}

# Rubric rows whose pass/fail is determined by SDK-emitted serialisation
# rather than the participant's own response body. A failure here may
# reflect a participant defect OR an SDK behavioural change since the
# expected values were captured, so the WARNINGS block surfaces these
# failures alongside the lenient acceptances and tells the reviewer to
# inspect the detail.
HANDSHAKE_ROW_IDS = frozenset({"P.1.1", "C.2.1", "C.2.2"})

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
    for line in _warnings(scorer):
        print(line)
    print("")
    print(f"  JSON report: {paths.json_path}")
    print("=" * 50)


def _warnings(scorer: Scorer) -> list[str]:
    """Build the WARNINGS block for rows that need a human's eye.

    Two row classes appear in this block:

    - Lenient acceptances. A row whose recorded diagnostic is in
      :data:`grader.src.protocol.matching.LENIENT_MODES` was accepted
      via a second documented form rather than the faithful one. The
      acceptance is legitimate and carries no automatic deduction,
      but a reviewer may want to assess whether the divergence merits
      a manual sidecar note.
    - Handshake-row failures. A failed row in
      :data:`HANDSHAKE_ROW_IDS` may reflect a participant defect, an
      SDK behavioural change since the expected values were
      captured, or a grader-side over-specification of the PRD. The
      rendered text lays out these candidates and the cue from
      uniform cohort failure.

    Each flagged row names its id, description, the reason it was
    flagged, and a bounded tail of its retained response (the full
    response is in the JSON report). Returns an empty list when
    neither class has entries.

    Args:
        scorer: Populated scorer whose results carry the recorded
            diagnostic and pass/fail per row.

    Returns:
        The WARNINGS block lines, or an empty list when none apply.
    """
    defs = all_tests()
    lenient_rows = [
        (test_id, result)
        for test_id, result in scorer.results.items()
        if result.diagnostic in LENIENT_MODES
    ]
    handshake_failures = [
        (test_id, result)
        for test_id, result in scorer.results.items()
        if test_id in HANDSHAKE_ROW_IDS and not result.passed
    ]
    if not lenient_rows and not handshake_failures:
        return []
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("WARNINGS")
    lines.append("=" * 70)
    if lenient_rows:
        lines.append(
            "  These rows were accepted via a lenient form. A human must"
        )
        lines.append(
            "  review each and decide any manual sidecar deduction; the"
        )
        lines.append(
            "  lenient form is a legitimate accept with no automatic effect."
        )
        lines.append("")
        for test_id, result in lenient_rows:
            definition = defs.get(test_id)
            description = definition.description if definition else ""
            # ``lenient_rows`` keeps only rows whose ``diagnostic`` is
            # in ``LENIENT_MODES`` (a frozenset of strings), so the
            # value is non-``None`` here; binding it locally narrows
            # the type for ``.get``.
            diagnostic = result.diagnostic or ""
            phrase = _LENIENT_FORM_PHRASE.get(
                diagnostic,
                f"accepted via a lenient form ({diagnostic})",
            )
            lines.append(f"  [REVIEW] {test_id}: {description}")
            lines.append(f"           {phrase}")
            lines.append(
                f"           response: "
                f"{_truncate(result.full_output, WARNING_RESPONSE_LIMIT)}"
            )
        lines.append("")
    if handshake_failures:
        lines.append(
            "  These handshake rows failed. The expected values are the"
        )
        lines.append(
            "  serialisation the MCP SDK emits, so a failure may be a"
        )
        lines.append(
            "  participant defect, an SDK behavioural change since"
        )
        lines.append(
            "  the expected values were captured, or a grader-side"
        )
        lines.append(
            "  expected value that over-specifies what the PRD"
        )
        lines.append(
            "  designates. A uniform failure across submissions"
        )
        lines.append(
            "  weighs against the first cause. Inspect the detail and"
        )
        lines.append("  the JSON report before judging.")
        lines.append("")
        for test_id, result in handshake_failures:
            definition = defs.get(test_id)
            description = definition.description if definition else ""
            lines.append(f"  [REVIEW] {test_id}: {description}")
            lines.append(f"           {result.message}")
            lines.append(
                f"           response: "
                f"{_truncate(result.full_output, WARNING_RESPONSE_LIMIT)}"
            )
        lines.append("")
    lines.append("=" * 70)
    return lines


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
