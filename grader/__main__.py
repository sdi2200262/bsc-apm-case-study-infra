# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Grader CLI entry point: grade one participant patch end to end.

Parses arguments, resolves the testing-environment and eclass paths,
runs the preflight and reset, applies the participant's patch (or skips
it in baseline mode), sequences the Python and C phase modules, writes
the JSON report beside the eclass-mcp-server checkout, and prints the
console summary. The per-phase ordering and the C compile gate live with
the phase runners ``_run_python_phases`` and ``_run_c_phases``.

Exit codes: ``0`` on a clean run (phase-test failures are recorded in the
report and do not change the exit code); ``1`` on a configuration,
preflight, reset, provisioning, or patch-application failure; ``2`` on an
argument error or a missing patch file.

Invoke as ``python -m grader`` from a working directory with the
``grader`` package on ``sys.path``.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

from . import log
from .config import require_path, resolve_config
from .environment import (
    build_c,
    build_python,
    patch,
    preflight,
    provision,
    reset,
)
from .errors import GraderError
from .protocol import phases
from .scoring import reporting, scoring

PhaseRunner = Callable[
    [Path, Path, bool], dict[str, tuple[bool, str, str, str | None]]
]


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the grading sequence.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on a clean run; ``2`` on an argparse usage error;
        ``1`` on any ``GraderError`` or a patch-application failure.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.no_patch and not args.patch_file:
        parser.error("either provide a patch file or use --no-patch")
    if args.no_patch and args.patch_file:
        parser.error("--no-patch is incompatible with a patch file")

    if args.debug:
        log.enable_debug()

    try:
        return _run(args)
    except GraderError as error:
        log.error(str(error))
        return 1


def _install_cleanup_signal_handlers(eclass_root: Path) -> None:
    """Install SIGINT and SIGTERM handlers that run the post-run cleanup before re-raising.

    Python's ``try/finally`` does not fire on a SIGTERM, so without
    these handlers a Ctrl-C or ``kill`` bypasses the cleanup in
    ``_run`` and leaves the checkout dirty for the next grade.
    The handler runs ``provision.reset_provisioning`` then
    ``patch.cleanup`` (both idempotent), restores the default
    disposition, and re-raises by sending the same signal to this
    process so the calling shell sees the correct killed-by-signal
    exit status. SIGKILL and OOM remain uncatchable;
    ``patch._prepare_clean_checkout`` recovers from those.

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

    log.info("preflight: probing testing environment endpoints")
    preflight.run_preflight()
    log.info("preflight: passed")

    log.info("reset: running testing environment reset")
    reset.run_reset(mock_root)
    log.info("reset: complete")

    if args.no_patch:
        patch_path: Path | None = None
        patch_name = "baseline"
    else:
        patch_path = Path(args.patch_file).resolve()
        if not patch_path.exists():
            log.error(f"patch-apply failed: patch file not found: {patch_path}")
            return 1
        patch_name = patch_path.stem

    scorer = scoring.Scorer()
    paths = reporting.report_paths(eclass_root.parent, patch_name)

    if patch_path is not None:
        log.info(f"patch: applying {patch_path.name}")
        ok, summary, detail = patch.apply_patch(eclass_root, patch_path)
        if not ok:
            log.error(f"patch-apply failed: {summary}")
            scorer.record("PATCH", False, summary, detail)
            _write_reports(paths, scorer, args.verbose)
            return 1
        log.info(f"patch: {summary}")

    try:
        provision.provision(eclass_root, mock_root)
        log.info(
            "provision: testing environment .env and certs/ copied "
            "verbatim into the checkout"
        )
    except provision.ProvisioningError as error:
        log.error(f"provisioning failed: {error}")
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
            log.info("patch: cleaning up test branch")
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
    log.info("python build: uv sync")
    ok, summary, _detail = build_python.build(eclass_root)
    log.info(f"python build: {summary}")
    if not ok:
        _skip_remaining(
            scorer,
            scoring.PYTHON_TESTS,
            f"skipped: python build failed ({summary})",
        )
        return
    _record_phase(scorer, "python baseline", phases.run_python_baseline,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "python course", phases.run_python_course_announcements,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "python general", phases.run_python_general_announcements,
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
    log.info("c compile: make c-server")
    compile_ok, compile_summary, compile_detail = build_c.compile_c_replica(eclass_root)
    scorer.record("C.1.1", compile_ok, compile_summary, compile_detail)
    log.info(f"c compile: {compile_summary}")
    if not compile_ok:
        _skip_remaining(
            scorer,
            scoring.C_TESTS,
            f"skipped: c compile failed ({compile_summary})",
        )
        return

    log.info("c stack: ldd verification")
    stack_results = build_c.verify_stack(eclass_root)
    for test_id, result in stack_results.items():
        scorer.record(test_id, result[0], result[1], result[2])
        log.info(f"c stack {test_id}: {result[1]}")

    _record_phase(scorer, "c config", phases.run_c_config, eclass_root, mock_root, debug)

    log.info("c baseline phase")
    for test_id, result in phases.run_c_baseline(eclass_root, mock_root, debug).items():
        scorer.record(test_id, result[0], result[1], result[2],
                      diagnostic=result[3])

    _record_phase(scorer, "c course", phases.run_c_course_announcements,
                  eclass_root, mock_root, debug)
    _record_phase(scorer, "c general", phases.run_c_general_announcements,
                  eclass_root, mock_root, debug)

    log.info("c memory phase")
    passed_tests = frozenset(
        test_id for test_id, result in scorer.results.items() if result.passed
    )
    for test_id, result in phases.run_c_memory(
        eclass_root, mock_root, debug, passed_tests
    ).items():
        scorer.record(test_id, result[0], result[1], result[2],
                      diagnostic=result[3])


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
    log.info(f"{label} phase")
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
