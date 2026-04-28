#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Grader CLI entry point.

Parses arguments, resolves configuration, runs the
testing-environment pre-flight, runs the reset script, then
sequences the per-phase test modules. Exits 0 on a clean run,
non-zero on configuration errors, pre-flight failures, reset
failures, or phase test failures.

Invoke as ``python -m grader`` from a working directory that has
the ``grader`` package on ``sys.path``. The script accepts either
a patch file (patch mode) or ``--no-patch`` (baseline mode);
other phase-related flags pass through to the phase modules.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .src import preflight, reset
from .src.config import resolve_config, require_path
from .src.errors import GraderError


def main() -> int:
    """Parse arguments and run the grading sequence.

    Returns:
        ``0`` on success; ``2`` on argument error or missing patch
        file; ``1`` on any ``GraderError`` raised during the run.
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
        ``0`` on a clean run; ``2`` when a supplied patch file
        does not exist on disk.

    Raises:
        GraderError: When configuration is missing, pre-flight
            fails, or reset fails.
    """
    config = resolve_config(
        mock_root_flag=args.mock_root,
        eclass_root_flag=args.eclass_dir,
    )
    mock_root = require_path(config.mock_root, "mock root", "grader")
    require_path(config.eclass_root, "eclass root", "grader")

    print("preflight: probing testing environment endpoints")
    preflight.run_preflight()
    print("preflight: passed")

    print("reset: running testing environment reset")
    reset.run_reset(mock_root)
    print("reset: complete")

    if args.no_patch:
        print("no patch to apply, no tests to run")
        return 0

    patch_path = Path(args.patch_file).resolve()
    if not patch_path.exists():
        print(f"error: patch file not found: {patch_path}", file=sys.stderr)
        return 2
    print(f"patch {patch_path.name}: not applied")
    print("no tests to run")
    return 0


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
