#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Orchestrate every pipeline stage on one submission zip in sequence.

This script chains validate, grade, parse, combine, and
add_to_dataset on a single submission, stopping immediately on the
first stage that returns a non-zero exit code. Each stage is
invoked as a Python subprocess so its argparse-driven error
handling, stderr formatting, and exit-code semantics carry through
unchanged; the orchestrator inherits those exits and propagates
the first failure to its own caller.

The orchestrator is a convenience layer, not a rewrite of stage
logic: every flag the individual stages accept can be passed
through here, and ``pipeline.yaml`` at the dataset root provides
defaults exactly as it does for direct stage invocations.

The chain does not include cleanup. After a successful run the
operator can invoke ``python -m pipeline.cleanup
<submission_name> --output-root <root>`` to remove the staging
copy, or leave it in place for re-runnability across parser
version bumps and similar.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .errors import (
    PipelineError,
    SubmissionFormatError,
)
from .submissions import parse_submission_name


PIPELINE_STAGES_BARE: tuple[str, ...] = (
    "pipeline.combine",
    "pipeline.add_to_dataset",
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the orchestrator.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` when every stage succeeded,
        otherwise the exit code of the first failing stage. ``2``
        on operator error before any stage runs.
    """
    args = _parse_args(argv)
    try:
        submission = parse_submission_name(args.submission_zip.name)
    except SubmissionFormatError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except PipelineError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    chain = _build_chain(args, submission.manifest_key)
    for stage_name, stage_argv in chain:
        print(f"\n[run] {stage_name}", flush=True)
        completed = subprocess.run(stage_argv)
        if completed.returncode != 0:
            print(
                f"\n[run] {stage_name} failed with exit code "
                f"{completed.returncode}; halting chain",
                file=sys.stderr,
            )
            return completed.returncode
    print(f"\n[run] all stages succeeded for {submission.manifest_key}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description=(
            "Run validate, grade, parse, combine, and add_to_dataset "
            "in sequence on one submission; halt on first failure."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "submission_zip",
        type=Path,
        help="Path to the submission zip ({PID}_S{1|2}_{apm|speckit}.zip).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Dataset output root directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional pipeline.yaml path; defaults to <output-root>/pipeline.yaml.",
    )
    parser.add_argument(
        "--grader-root",
        type=Path,
        default=None,
        help="Path to the grader directory (passed through to the grade stage).",
    )
    parser.add_argument(
        "--eclass-root",
        type=Path,
        default=None,
        help="Path to the eclass-mcp-server checkout (passed through to the grade stage).",
    )
    parser.add_argument(
        "--parser-root",
        type=Path,
        default=None,
        help="Path to the parser directory (passed through to the parse stage).",
    )
    parser.add_argument(
        "--mock-root",
        type=Path,
        default=None,
        help="Path to the testing-environment install (passed through to the grade stage).",
    )
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Skip sanitisation in the parse stage.",
    )
    return parser.parse_args(argv)


def _build_chain(
    args: argparse.Namespace,
    manifest_key: str,
) -> list[tuple[str, list[str]]]:
    """Return the ordered list of ``(stage_name, argv)`` tuples to invoke.

    Each entry is a complete argv ready for ``subprocess.run``.
    Common flags (``--output-root``, ``--config``) propagate to
    every stage that takes them; stage-specific flags propagate
    only to the stages that accept them.
    """
    common = _common_flags(args)
    chain: list[tuple[str, list[str]]] = []
    chain.append((
        "pipeline.validate",
        [
            sys.executable, "-m", "pipeline.validate",
            str(args.submission_zip),
            *common,
        ],
    ))
    grade_argv = [
        sys.executable, "-m", "pipeline.grade",
        manifest_key,
        *common,
    ]
    grade_argv += _path_flag("--grader-root", args.grader_root)
    grade_argv += _path_flag("--eclass-root", args.eclass_root)
    grade_argv += _path_flag("--mock-root", args.mock_root)
    chain.append(("pipeline.grade", grade_argv))
    parse_argv = [
        sys.executable, "-m", "pipeline.parse",
        manifest_key,
        *common,
    ]
    parse_argv += _path_flag("--parser-root", args.parser_root)
    if args.no_sanitize:
        parse_argv.append("--no-sanitize")
    chain.append(("pipeline.parse", parse_argv))
    for module in PIPELINE_STAGES_BARE:
        chain.append((
            module,
            [sys.executable, "-m", module, manifest_key, *common],
        ))
    return chain


def _common_flags(args: argparse.Namespace) -> list[str]:
    """Return the common ``--output-root`` and ``--config`` flags."""
    flags = ["--output-root", str(args.output_root)]
    if args.config is not None:
        flags += ["--config", str(args.config)]
    return flags


def _path_flag(name: str, value: Path | None) -> list[str]:
    """Return ``[name, str(value)]`` when set, otherwise an empty list."""
    if value is None:
        return []
    return [name, str(value)]


if __name__ == "__main__":
    sys.exit(main())
