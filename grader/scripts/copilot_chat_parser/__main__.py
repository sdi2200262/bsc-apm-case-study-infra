#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Command-line interface for the Copilot Chat Parser.

Usage:
    python -m copilot_chat_parser FILE [FILE ...] --metrics [--format json|csv]
        [-o OUTPUT] [--short-threshold N]
    python -m copilot_chat_parser FILE [FILE ...] --sanitize
    python -m copilot_chat_parser FILE [FILE ...] --unsanitize

The environment variable ``CHAT_PARSER_SECRET`` is required for
``--sanitize`` and ``--unsanitize``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .buckets import DEFAULT_SHORT_THRESHOLD
from .io import is_sanitized, load_chat, save_csv_report, save_json_report
from .report import build_report
from .sanitize import sanitize_chat, unsanitize_chat
from .schema import SchemaError
from .session import Session, load_session


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.

    Returns:
        A configured ``argparse.ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m copilot_chat_parser",
        description="Extract metrics from GitHub Copilot chat exports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input_files",
        type=Path,
        nargs="+",
        help="Paths to one or more chat export JSON files.",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Extract aggregated metrics across all input files.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default=None,
        help="Output format for metrics. Default emits both.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination path for the metrics output.",
    )
    parser.add_argument(
        "--short-threshold",
        type=int,
        default=DEFAULT_SHORT_THRESHOLD,
        help=(
            "Upper bound on user-message length for the 'short' bucket, "
            "in characters. Default 50."
        ),
    )
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Encrypt each input file's payload with CHAT_PARSER_SECRET.",
    )
    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help="Decrypt each input file with CHAT_PARSER_SECRET.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional list of argument strings. When ``None`` the
            interpreter's ``sys.argv[1:]`` is used.

    Returns:
        Process exit code: ``0`` on success, non-zero on error.
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    for input_file in args.input_files:
        if not input_file.exists():
            print(f"Error: File not found: {input_file}", file=sys.stderr)
            return 1

    if args.sanitize:
        return _run_sanitize(args.input_files)
    if args.unsanitize:
        return _run_unsanitize(args.input_files)
    if args.metrics:
        return _run_metrics(args)

    parser.print_help()
    return 0


def _run_metrics(args: argparse.Namespace) -> int:
    """Parse every input file, build the session report, and write output."""
    for input_file in args.input_files:
        try:
            data = load_chat(input_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Error: {input_file}: {error}", file=sys.stderr)
            return 1
        if is_sanitized(data):
            print(
                f"Error: {input_file} is sanitized. Extract metrics before sanitization.",
                file=sys.stderr,
            )
            return 1

    try:
        session = load_session(args.input_files)
    except SchemaError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    _warn_on_model_drift(session)

    report = build_report(session, short_threshold=args.short_threshold)

    _print_status_line(session)

    default_parent = args.input_files[0].parent
    if args.format == "json":
        path = args.output or (default_parent / "metrics_project.json")
        save_json_report(report, path)
        print(f"Metrics exported to: {path}")
        return 0
    if args.format == "csv":
        path = args.output or (default_parent / "metrics_project.csv")
        save_csv_report(report, path)
        print(f"Metrics exported to: {path}")
        return 0

    json_path = (
        args.output.with_suffix(".json") if args.output
        else (default_parent / "metrics_project.json")
    )
    csv_path = (
        args.output.with_suffix(".csv") if args.output
        else (default_parent / "metrics_project.csv")
    )
    save_json_report(report, json_path)
    print(f"Metrics exported to: {json_path}")
    save_csv_report(report, csv_path)
    print(f"Metrics exported to: {csv_path}")
    return 0


def _run_sanitize(input_files: list[Path]) -> int:
    """Encrypt every input file and write the sanitized sidecar next to it."""
    secret = os.environ.get("CHAT_PARSER_SECRET", "").encode("utf-8")
    if not secret:
        print(
            "Error: CHAT_PARSER_SECRET environment variable not set.",
            file=sys.stderr,
        )
        return 1
    for input_file in input_files:
        try:
            data = load_chat(input_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Error: {input_file}: {error}", file=sys.stderr)
            return 1
        if is_sanitized(data):
            print(
                f"Warning: {input_file} is already sanitized, skipping.",
                file=sys.stderr,
            )
            continue
        sanitized = sanitize_chat(data, secret)
        output_path = input_file.parent / f"sanitized_{input_file.name}"
        save_json_report(sanitized, output_path)
        print(f"Sanitized export saved to: {output_path}")
    return 0


def _run_unsanitize(input_files: list[Path]) -> int:
    """Decrypt every input file with the configured secret."""
    secret = os.environ.get("CHAT_PARSER_SECRET", "").encode("utf-8")
    if not secret:
        print(
            "Error: CHAT_PARSER_SECRET environment variable not set.",
            file=sys.stderr,
        )
        return 1
    for input_file in input_files:
        try:
            data = load_chat(input_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Error: {input_file}: {error}", file=sys.stderr)
            return 1
        if not is_sanitized(data):
            print(
                f"Warning: {input_file} is not a sanitized file, skipping.",
                file=sys.stderr,
            )
            continue
        try:
            restored = unsanitize_chat(data, secret)
        except (ValueError, json.JSONDecodeError) as error:
            print(
                f"Error: Failed to unsanitize {input_file}: {error}",
                file=sys.stderr,
            )
            return 1
        output_path = input_file.parent / f"unsanitized_{input_file.name}"
        save_json_report(restored, output_path)
        print(f"Restored export saved to: {output_path}")
    return 0


def _warn_on_model_drift(session: Session) -> None:
    """Emit a stderr warning when more than one model id appears in a session."""
    if len(session.model_ids) > 1:
        print(
            "Warning: session contains multiple phaseModelId values: "
            + ", ".join(session.model_ids),
            file=sys.stderr,
        )


def _print_status_line(session: Session) -> None:
    """Emit a short stderr status line summarising what was parsed."""
    conversation_summary = ", ".join(
        f"{conversation.role}({conversation.request_count})"
        for conversation in session.conversations
    )
    print(
        f"Parsed {len(session.conversations)} file(s), "
        f"{len(session.requests)} request(s), framework={session.framework}; "
        f"{conversation_summary}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
