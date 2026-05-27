#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Grader CLI entry point.

Parses arguments, resolves configuration, runs the testing-
environment pre-flight and reset, applies the participant's patch
(or skips for baseline mode), then sequences the phase modules
and writes JSON and text reports beside the eclass-mcp-server
checkout.

Phase order, per implementation:

- Python: dependency install (prerequisite, not scored), then P.1
  baseline, P.2 course announcements, P.3 general announcements.
- C: C.1.1 compile (sole hard gate: on fail, skip-record every
  other C row including all ``.mem`` and C.5 rows and return).
  After compile: C.1.2/C.1.3/C.1.4 tech stack (no cascade);
  C.1.5/C.1.6 configuration surfaces (no cascade; restores
  dual-provisioned state); C.2 baseline (each C.2.3-12 row also
  records a ``.mem`` sub-assertion scored only if its functional
  assertion passes); C.3 course announcements and C.4 general
  announcements (same per-scenario ``.mem`` pattern); C.5
  multi-step memory last (gated on specific composed single-call
  scenarios named in each scenario's ``gates_on``).

Exit codes:

- ``0`` on a clean run; phase-test failures are recorded in the
  report and do not change this exit code.
- ``1`` on configuration errors, pre-flight failures, reset
  failures, provisioning failures, or patch-application failures.
- ``2`` on argument errors or a missing patch file.

Invoke as ``python -m grader`` from a working directory that has
the ``grader`` package on ``sys.path``.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Callable

from .src import (
    build_c,
    build_python,
    patch,
    preflight,
    provision,
    reporting,
    reset,
    scoring,
)
from .src.config import resolve_config, require_path
from .src.errors import GraderError
from .src.protocol import (
    c_baseline,
    c_config,
    c_course_announcements,
    c_general_announcements,
    c_memory,
    python_baseline,
    python_course_announcements,
    python_general_announcements,
)


def main() -> int:
    """Parse arguments and run the grading sequence.

    Returns:
        ``0`` on a clean run; ``2`` on an argparse usage error;
        ``1`` on any ``GraderError`` or a patch-application failure.
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


def _install_cleanup_signal_handlers(eclass_root: Path) -> None:
    """Install SIGINT and SIGTERM handlers that run the post-run cleanup before re-raising.

    Python's ``try/finally`` does not fire on a SIGTERM, so without
    these handlers a Ctrl-C or ``kill`` bypasses the cleanup in
    :func:`_run` and leaves the checkout dirty for the next grade.
    The handler runs :func:`provision.reset_provisioning` then
    :func:`patch.cleanup` (both idempotent), restores the default
    disposition, and re-raises by sending the same signal to this
    process so the calling shell sees the correct killed-by-signal
    exit status. SIGKILL and OOM remain uncatchable;
    :func:`patch._prepare_clean_checkout` recovers from those.

    Args:
        eclass_root: Resolved eclass-mcp-server checkout path.
    """
    def handler(signum: int, _frame: object) -> None:
        try:
            provision.reset_provisioning(eclass_root)
            patch.cleanup(eclass_root)
        finally:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _run(args: argparse.Namespace) -> int:
    """Execute the grading sequence with resolved configuration.

    Args:
        args: Parsed argparse namespace.

    Returns:
        ``0`` on a clean run; ``2`` when a patch file is missing;
        ``1`` when patch application or provisioning fails.

    Raises:
        GraderError: When configuration, pre-flight, or reset fails.
    """
    config = resolve_config(
        mock_root_flag=args.mock_root,
        eclass_root_flag=args.eclass_dir,
    )
    mock_root = require_path(config.mock_root, "mock root", "grader")
    eclass_root = require_path(config.eclass_root, "eclass root", "grader")

    _install_cleanup_signal_handlers(eclass_root)

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
            print(
                f"error: patch-apply failed: patch file not found: {patch_path}",
                file=sys.stderr,
            )
            return 1
        patch_name = patch_path.stem

    scorer = scoring.Scorer()
    paths = reporting.report_paths(eclass_root.parent, patch_name)

    if patch_path is not None:
        print(f"patch: applying {patch_path.name}")
        ok, summary, detail = patch.apply_patch(eclass_root, patch_path)
        if not ok:
            print(f"error: patch-apply failed: {summary}", file=sys.stderr)
            scorer.record("PATCH", False, summary, detail)
            _write_reports(paths, scorer, args.verbose)
            return 1
        print(f"patch: {summary}")

    try:
        provision.provision(eclass_root, mock_root)
        print(
            "provision: testing environment .env and certs/ copied "
            "verbatim into the checkout"
        )
    except provision.ProvisioningError as error:
        print(f"error: provisioning failed: {error}", file=sys.stderr)
        if patch_path is not None and not args.no_cleanup:
            patch.cleanup(eclass_root)
        provision.reset_provisioning(eclass_root)
        return 1

    try:
        _run_python_phases(scorer, eclass_root, mock_root, args.debug)
        _run_c_phases(scorer, eclass_root, mock_root, args.debug)
    finally:
        provision.reset_provisioning(eclass_root)
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
    """Run the Python dependency install, then the Python phases."""
    print("python build: uv sync")
    ok, summary, _detail = build_python.build(eclass_root)
    print(f"python build: {summary}")
    if not ok:
        _skip_remaining(
            scorer,
            scoring.PYTHON_TESTS,
            f"skipped: python build failed ({summary})",
        )
        return
    _record_phase(scorer, "python baseline", python_baseline.run,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "python course", python_course_announcements.run,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "python general", python_general_announcements.run,
                  eclass_root, mock_root, debug)


def _run_c_phases(
    scorer: scoring.Scorer,
    eclass_root: Path,
    mock_root: Path,
    debug: bool,
) -> None:
    """Run C compile, tech-stack, config surfaces, then protocol phases.

    C.1.1 compile is the sole hard gate: on fail every other C row
    (including all ``.mem`` and C.5 rows) is skip-recorded and the
    function returns. The tech-stack (C.1.2/C.1.3/C.1.4) and config-
    surface (C.1.5/C.1.6) phases run independently with no cascade.
    Per-scenario ``.mem`` sub-assertions ride each C functional run.
    The multi-step memory phase runs last, gated on its composed
    single-call scenarios.
    """
    print("c compile: make c-server")
    compile_ok, compile_summary, compile_detail = build_c.compile_c_replica(eclass_root)
    scorer.record("C.1.1", compile_ok, compile_summary, compile_detail)
    print(f"c compile: {compile_summary}")
    if not compile_ok:
        _skip_remaining(
            scorer,
            scoring.C_TESTS,
            f"skipped: c compile failed ({compile_summary})",
        )
        return

    print("c stack: ldd verification")
    stack_results = build_c.verify_stack(eclass_root)
    for test_id, result in stack_results.items():
        scorer.record(test_id, result[0], result[1], result[2])
        print(f"c stack {test_id}: {result[1]}")

    _record_phase(scorer, "c config", c_config.run, eclass_root, mock_root, debug)

    print("c baseline phase")
    for test_id, result in c_baseline.run(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2],
                      diagnostic=result[3])

    _record_phase(scorer, "c course", c_course_announcements.run,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "c general", c_general_announcements.run,
                  eclass_root, mock_root, debug)

    print("c memory phase")
    passed_tests = frozenset(
        test_id for test_id, result in scorer.results.items() if result.passed
    )
    for test_id, result in c_memory.run(
        eclass_root, mock_root, debug, passed_tests
    ).items():
        scorer.record(test_id, result[0], result[1], result[2],
                      diagnostic=result[3])


PhaseRunner = Callable[
    [Path, Path, bool], dict[str, tuple[bool, str, str, str | None]]
]


def _record_phase(
    scorer: scoring.Scorer,
    label: str,
    run_func: PhaseRunner,
    eclass_root: Path,
    mock_root: Path,
    debug: bool,
) -> None:
    """Drive one phase aggregator and record its results into the scorer.

    Every aggregator yields ``(passed, message, full_output, mode)``;
    ``mode`` is the ``matching`` mode the row was accepted under and
    is recorded as the unscored per-test diagnostic (``None`` for a
    failed or non-string-matched row).
    """
    print(f"{label} phase")
    for test_id, result in run_func(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2],
                       diagnostic=result[3])


def _skip_remaining(
    scorer: scoring.Scorer,
    tests: tuple[scoring.TestDefinition, ...],
    reason: str,
) -> None:
    """Record a skip for every rubric row in ``tests`` without an entry yet."""
    for test in tests:
        if test.id not in scorer.results:
            scorer.record(test.id, False, reason, reason)


def _write_reports(
    paths: reporting.ReportPaths,
    scorer: scoring.Scorer,
    verbose: bool,
) -> None:
    """Write the JSON report and print the console summary."""
    reporting.write_json(paths, scorer)
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
