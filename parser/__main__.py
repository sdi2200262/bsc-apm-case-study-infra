#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Command-line interface for the Claude Code chat parser.

Owns the CLI surface: the mode flags (combinable), argument validation, and
the dispatch into the data, metrics, and schema layers. Each flag's
behaviour is documented on the argument in ``_build_parser``. Reversible
sanitisation is a separate concern with its own entry point,
``python -m parser.sanitize``.

Usage:
    python -m parser <path> --framework {apm,speckit} --metrics -o out_dir
    python -m parser --schema -o out_dir
    python -m parser <path> --framework {apm,speckit} --economic
    python -m parser <path> --framework {apm,speckit} --process

``<path>`` is a single ``*.jsonl`` file or a directory of ``*.jsonl`` files
copied straight from ``~/.claude/projects/<dashed-cwd>/``. ``--framework``
(whose vocabulary is owned by ``data.commands``) is required for the metric
modes: content auto-detection is deliberately not performed,
so that a non-protocol opening prompt cannot be silently misclassified; in
production the framework is known from the submission directory naming.

Exit codes:
    0: Success.
    1: Runtime failure (parse error, write error).
    2: Usage error (bad flags, no mode selected, missing input).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from . import log
from .contract import schema_document
from .data.aggregate.tokens import compute_session_token_data, merge_subagent_indices
from .data.buckets import DEFAULT_SHORT_THRESHOLD
from .data.commands import FRAMEWORK_APM, FRAMEWORK_SPECKIT
from .data.jsonl import write_json
from .data.schema import SchemaError
from .data.session import DEFAULT_CAP_HOURS, load_session
from .metrics.cost import compute_cost_for_records
from .rates import (
    RateTableError,
    load_rate_table,
)
from .report.build import build_artifacts
from .report.notices import collect_notices
from .report.render import print_economic, print_process

DATA_ARTIFACT_FILENAME = "parser_data.json"
METRICS_ARTIFACT_FILENAME = "parser_metrics.json"
SCHEMA_ARTIFACT_FILENAME = "parser_schema.json"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, non-zero on error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.debug:
        log.enable_debug()
    if args.schema:
        schema_status = _run_schema(args.output)
        if not (args.economic or args.process or args.metrics):
            return schema_status
        if schema_status != 0:
            return schema_status
    if not (args.economic or args.process or args.metrics or args.schema):
        parser.error("no mode selected; choose --economic, --process, --metrics, or --schema")
    if not (args.economic or args.process or args.metrics):
        return 0
    if args.path is None:
        parser.error("a path argument is required for the metric modes")
    if args.framework is None:
        parser.error("--framework is required for the metric modes")
    if args.metrics and args.output is None:
        parser.error("--metrics requires -o <output directory> for the data and metrics artifacts")
    try:
        session = load_session(args.path, args.framework, args.cap_hours)
    except SchemaError as error:
        log.error(str(error))
        return 1
    printed_any = False
    if args.economic:
        if printed_any:
            log.blank()
        try:
            rate_table = load_rate_table()
            token_data = compute_session_token_data(session)
            all_records = [record for view in session.views for record in view.conversation.records]
            cost = compute_cost_for_records(
                all_records, rate_table, merge_subagent_indices(session)
            )
        except RateTableError as error:
            log.error(f"cost computation failed: {error}")
            return 1
        print_economic(token_data, cost, rate_table)
        log.notice_block((n.tag, n.label, n.summary, n.detail) for n in collect_notices(session))
        printed_any = True
    if args.process:
        if printed_any:
            log.blank()
        print_process(session, args.short_threshold)
        printed_any = True
    if args.metrics:
        try:
            rate_table = load_rate_table()
            data_artifact, metrics_artifact = build_artifacts(
                session, rate_table, args.short_threshold
            )
        except RateTableError as error:
            log.error(f"metrics build failed: {error}")
            return 1
        data_path = args.output / DATA_ARTIFACT_FILENAME
        metrics_path = args.output / METRICS_ARTIFACT_FILENAME
        try:
            args.output.mkdir(parents=True, exist_ok=True)
            write_json(data_artifact, data_path)
            write_json(metrics_artifact, metrics_path)
        except OSError as error:
            log.error(f"could not write artifacts to {args.output}: {error}")
            return 1
        log.info(f"data written to {data_path}")
        log.info(f"metrics written to {metrics_path}")
        log.notice_block((n.tag, n.label, n.summary, n.detail) for n in collect_notices(session))
    return 0


def _run_schema(output: Path | None) -> int:
    """Emit the field-contract schema artifact.

    Writes ``parser_schema.json`` into ``output`` when a directory is
    given, otherwise dumps the schema to stdout. The schema is independent
    of any session, so this mode reads no transcript.

    Args:
        output: The output directory, or ``None`` to write to stdout.

    Returns:
        ``0`` on success, ``1`` on a write error.
    """
    document = schema_document()
    if output is None:
        json.dump(document, sys.stdout, indent=2, ensure_ascii=False)
        log.blank()
        return 0
    schema_path = output / SCHEMA_ARTIFACT_FILENAME
    try:
        output.mkdir(parents=True, exist_ok=True)
        write_json(document, schema_path)
    except OSError as error:
        log.error(f"could not write schema to {schema_path}: {error}")
        return 1
    log.info(f"schema written to {schema_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser defining the combinable mode flags and shared inputs."""
    parser = argparse.ArgumentParser(
        prog="python -m parser",
        description=(
            "Read Claude Code CLI JSONL conversation files from a submission "
            "and report the parser's view of their structure."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Path to a single .jsonl file or a directory of .jsonl files "
            "copied straight from ~/.claude/projects/<dashed-cwd>/. Not "
            "required by --schema."
        ),
    )
    parser.add_argument(
        "--framework",
        choices=[FRAMEWORK_APM, FRAMEWORK_SPECKIT],
        required=False,
        default=None,
        help="Framework label for the submission. Required for the metric modes.",
    )
    parser.add_argument(
        "--economic",
        action="store_true",
        help=(
            "Print the economic-dimension metric block (per-category "
            "token sums for main and delegated populations, totals, "
            "and API-equivalent cost) at session scope."
        ),
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help=(
            "Print the process-dimension metric blocks (time, user "
            "input) and the supplementary tool-success rate at session scope."
        ),
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help=(
            "Build the data and metrics artifacts (parser_data.json, "
            "parser_metrics.json) and write them into the -o directory."
        ),
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help=(
            "Emit the field-contract schema (parser_schema.json) into the "
            "-o directory, or stdout when -o is absent. Needs no session."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Output directory for --metrics (parser_data.json, "
            "parser_metrics.json) and --schema (parser_schema.json)."
        ),
    )
    parser.add_argument(
        "--short-threshold",
        type=int,
        default=DEFAULT_SHORT_THRESHOLD,
        help=(
            "Upper bound (exclusive) on text length for the 'short' "
            "turn-prompt bucket, in characters. Affects the turn-prompt "
            "bucket distributions and magnitudes."
        ),
    )
    parser.add_argument(
        "--cap-hours",
        type=float,
        default=DEFAULT_CAP_HOURS,
        help=(
            "Session-duration cap in hours. Records timestamped strictly "
            "beyond the session's first user prompt plus this span are "
            "dropped and every downstream aggregate is recomputed against "
            "the survivors. A non-positive value disables the cap."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging.",
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
