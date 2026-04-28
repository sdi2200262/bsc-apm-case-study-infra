#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Grader CLI entry point.

Parses arguments, resolves configuration, runs the
testing-environment pre-flight and reset, applies the participant's
patch (or skips for baseline mode), then sequences the phase
modules and writes JSON and text reports beside the eclass-mcp-
server checkout.

Exit codes:

- ``0`` on a clean run; phase-test failures are recorded in the
  report and do not change this exit code.
- ``1`` on configuration errors, pre-flight failures, reset
  failures, or patch-application failures.
- ``2`` on argument errors or a missing patch file.

Invoke as ``python -m grader`` from a working directory that has
the ``grader`` package on ``sys.path``. The script accepts either
a patch file (patch mode) or ``--no-patch`` (baseline mode).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .src import (
    build_c,
    build_python,
    memory,
    patch,
    preflight,
    reporting,
    reset,
    scoring,
)
from .src.config import resolve_config, require_path
from .src.errors import GraderError
from .src.protocol import (
    c_baseline,
    c_feature,
    python_baseline,
    python_feature,
)


def main() -> int:
    """Parse arguments and run the grading sequence.

    Returns:
        ``0`` on a clean run; ``2`` on argument error or missing
        patch file; ``1`` on any ``GraderError`` raised during
        the pre-grading sequence or on a patch-application
        failure.
    """
    parser = _build_parser()
    args = parser.parse_args()

    if not args.no_patch and not args.patch_file:
        parser.error("either provide a patch file or use --no-patch")
    if args.no_patch and args.patch_file:
        parser.error("--no-patch is incompatible with a patch file")

    try:
        return _run(args)
    except GraderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    """Execute the grading sequence with resolved configuration.

    Args:
        args: Parsed argparse namespace.

    Returns:
        ``0`` on a clean run with the phase reports written;
        ``2`` when a supplied patch file does not exist on disk;
        ``1`` when patch application fails.

    Raises:
        GraderError: When configuration is missing, pre-flight
            fails, or reset fails.
    """
    config = resolve_config(
        mock_root_flag=args.mock_root,
        eclass_root_flag=args.eclass_dir,
    )
    mock_root = require_path(config.mock_root, "mock root", "grader")
    eclass_root = require_path(config.eclass_root, "eclass root", "grader")

    print("preflight: probing testing environment endpoints")
    preflight.run_preflight()
    print("preflight: passed")

    print("reset: running testing environment reset")
    reset.run_reset(mock_root)
    print("reset: complete")

    if args.no_patch:
        patch_path: Path | None = None
        patch_name = "baseline"
    else:
        patch_path = Path(args.patch_file).resolve()
        if not patch_path.exists():
            print(f"error: patch file not found: {patch_path}", file=sys.stderr)
            return 2
        patch_name = patch_path.stem

    scorer = scoring.Scorer()
    paths = reporting.report_paths(eclass_root.parent, patch_name)

    if patch_path is not None:
        print(f"patch: applying {patch_path.name}")
        ok, summary, detail = patch.apply_patch(eclass_root, patch_path)
        if not ok:
            print(f"patch: {summary}")
            scorer.record("PATCH", False, summary, detail)
            _write_reports(paths, scorer, args.verbose)
            return 1
        print(f"patch: {summary}")

    try:
        _run_python_phases(scorer, eclass_root, mock_root, args.debug)
        _run_c_phases(scorer, eclass_root, mock_root, args.debug)
    finally:
        if patch_path is not None and not args.no_cleanup:
            print("patch: cleaning up test branch")
            patch.cleanup(eclass_root)

    _write_reports(paths, scorer, args.verbose)
    return 0


def _run_python_phases(
    scorer: scoring.Scorer,
    eclass_root: Path,
    mock_root: Path,
    debug: bool,
) -> None:
    """Run the Python build, baseline tests, and feature tests in order."""
    print("python build: uv sync")
    ok, summary, detail = build_python.build(eclass_root)
    scorer.record("B1", ok, summary, detail)
    print(f"python build: {summary}")
    if not ok:
        _skip_remaining(scorer, scoring.PYTHON_TESTS, "skipped: python build failed")
        return
    print("python baseline phase")
    for test_id, result in python_baseline.run(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2])
    print("python feature phase")
    for test_id, result in python_feature.run(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2])


def _run_c_phases(
    scorer: scoring.Scorer,
    eclass_root: Path,
    mock_root: Path,
    debug: bool,
) -> None:
    """Run the C build, memory test, baseline tests, and feature tests in order."""
    print("c build: make c-server")
    ok, summary, detail = build_c.build(eclass_root)
    scorer.record("B2", ok, summary, detail)
    print(f"c build: {summary}")
    if not ok:
        _skip_remaining(scorer, scoring.C_TESTS, "skipped: c build failed")
        return
    print("c memory phase: valgrind")
    mem_ok, mem_summary, mem_detail = memory.valgrind(eclass_root, mock_root)
    scorer.record("M1", mem_ok, mem_summary, mem_detail)
    print(f"c memory: {mem_summary}")
    print("c baseline phase")
    for test_id, result in c_baseline.run(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2])
    print("c feature phase")
    for test_id, result in c_feature.run(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2])


def _skip_remaining(
    scorer: scoring.Scorer,
    tests: tuple[scoring.TestDefinition, ...],
    reason: str,
) -> None:
    """Record a skip result for every rubric row in ``tests`` that has no entry yet."""
    for test in tests:
        if test.id not in scorer.results:
            scorer.record(test.id, False, reason, reason)


def _write_reports(
    paths: reporting.ReportPaths,
    scorer: scoring.Scorer,
    verbose: bool,
) -> None:
    """Write the JSON and text reports and print the console summary."""
    reporting.write_json(paths, scorer)
    reporting.write_text(paths, scorer)
    reporting.print_console_summary(paths, scorer, verbose)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the grader CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m grader",
        description="Grade participant submissions against the testing environment.",
    )
    parser.add_argument(
        "patch_file",
        nargs="?",
        type=Path,
        default=None,
        help="path to the patch file to evaluate (omit with --no-patch)",
    )
    parser.add_argument(
        "--no-patch",
        action="store_true",
        help="run against the unmodified eclass-mcp-server tree",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="leave the test branch in place after grading",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="print individual test results to stdout",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print MCP-server stdio for each phase test",
    )
    parser.add_argument(
        "--eclass-dir",
        type=Path,
        required=True,
        help="path to the eclass-mcp-server checkout the patch applies to",
    )
    parser.add_argument(
        "--mock-root",
        type=Path,
        default=None,
        help="path to the testing environment install (overrides grader.yaml)",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
