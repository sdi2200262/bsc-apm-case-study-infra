#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Command-line interface for the Claude Code chat parser.

The modes are selected by flag and combinable. ``--inspect``,
``--economic``, and ``--process`` print human-readable summaries.
``--metrics`` writes the two per-session artifacts (``parser_data.json``
and ``parser_metrics.json``) into the ``-o`` directory. ``--schema`` writes
the field contract (``parser_schema.json``) once and needs no session.
``--sanitize`` and ``--unsanitize`` seal and unseal the raw JSONL files for
archival.

Usage:
    python -m parser <path> --framework {apm,speckit} --metrics -o out_dir
    python -m parser --schema -o out_dir
    python -m parser <path> --framework {apm,speckit} --inspect
    python -m parser <path> --framework {apm,speckit} --economic
    python -m parser <path> --framework {apm,speckit} --process
    python -m parser <path> --sanitize
    python -m parser <path> --unsanitize

``<path>`` is either a single ``*.jsonl`` file or a directory of
``*.jsonl`` files copied straight from
``~/.claude/projects/<dashed-cwd>/``. ``--framework`` is required
for the metric and inspection modes (auto-detection by content is
not performed because in production the framework is known from
the submission directory naming, and ad-hoc inspection callers
declare it explicitly so misclassification of a non-protocol
opening prompt cannot happen silently). The sanitisation modes do
not require ``--framework`` because they operate on the raw bytes
without parsing the protocol vocabulary.

Sanitisation requires the ``CC_PARSER_SECRET`` environment
variable (or a ``.env`` entry of the same name) to hold the
encryption key. Use the same key for matched ``--sanitize`` and
``--unsanitize`` invocations.

Exit codes:
    0: Success.
    1: Runtime failure (parse error, missing secret, write error).
    2: Usage error (bad flags, no mode selected, missing input).
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

from . import log
from .contract import schema_document
from .data.aggregate.tokens import compute_session_token_data, merge_subagent_indices
from .data.buckets import DEFAULT_SHORT_THRESHOLD
from .data.commands import FRAMEWORK_APM, FRAMEWORK_SPECKIT
from .data.conversation import discover_sanitisable_jsonl_files
from .data.jsonl import is_sanitised_payload, read_json, write_file_text, write_json
from .data.schema import SchemaError
from .data.session import DEFAULT_CAP_HOURS, load_session
from .metrics.cost import compute_cost_for_records
from .rates import (
    RateTableError,
    load_rate_table,
)
from .report.build import build_artifacts
from .report.notices import collect_notices
from .report.render import print_economic, print_inspection, print_process
from .sanitize import sanitise_jsonl_file, unsanitise_to_text

SECRET_ENV_VAR = "CC_PARSER_SECRET"
DATA_ARTIFACT_FILENAME = "parser_data.json"
METRICS_ARTIFACT_FILENAME = "parser_metrics.json"
SCHEMA_ARTIFACT_FILENAME = "parser_schema.json"
SANITIZED_FILENAME_PREFIX = "sanitized_"
UNSANITIZED_FILENAME_PREFIX = "unsanitized_"


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
    if args.sanitize and args.unsanitize:
        parser.error("--sanitize and --unsanitize are mutually exclusive")
    if args.schema:
        schema_status = _run_schema(args.output)
        if not (
            args.inspect
            or args.economic
            or args.process
            or args.metrics
            or args.sanitize
            or args.unsanitize
        ):
            return schema_status
        if schema_status != 0:
            return schema_status
    if args.sanitize:
        if args.path is None:
            parser.error("--sanitize requires a path argument")
        return _run_sanitize(args.path)
    if args.unsanitize:
        if args.path is None:
            parser.error("--unsanitize requires a path argument")
        return _run_unsanitize(args.path)
    if not (args.inspect or args.economic or args.process or args.metrics or args.schema):
        parser.error(
            "no mode selected; choose --inspect, --economic, --process, "
            "--metrics, --schema, --sanitize, or --unsanitize"
        )
    if not (args.inspect or args.economic or args.process or args.metrics):
        return 0
    if args.path is None:
        parser.error("a path argument is required for inspection and metric modes")
    if args.framework is None:
        parser.error("--framework is required for inspection and metric modes")
    if args.metrics and args.output is None:
        parser.error("--metrics requires -o <output directory> for the data and metrics artifacts")
    try:
        session = load_session(args.path, args.framework, args.cap_hours)
    except SchemaError as error:
        log.error(str(error))
        return 1
    printed_any = False
    if args.inspect:
        print_inspection(session)
        printed_any = True
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


def _run_sanitize(path: Path) -> int:
    """Encrypt every JSONL under ``path`` and write a sidecar next to each input.

    Walks the main session ``*.jsonl`` files at the top level plus
    every ``<sessionId>/subagents/agent-*.jsonl`` file Claude Code
    writes alongside them, so subagent transcripts are sealed
    alongside their parents instead of staying in plaintext.
    """
    secret = _read_secret()
    if secret is None:
        return 1
    try:
        files = discover_sanitisable_jsonl_files(path)
    except SchemaError as error:
        log.error(str(error))
        return 1
    for input_file in files:
        sidecar = sanitise_jsonl_file(input_file, secret)
        output_path = input_file.parent / f"{SANITIZED_FILENAME_PREFIX}{input_file.stem}.json"
        write_json(sidecar, output_path)
        log.info(f"sanitised: {input_file.name} -> {output_path.name}")
    return 0


def _run_unsanitize(path: Path) -> int:
    """Decrypt every sanitised sidecar at ``path`` and write the restored JSONL.

    Walks both the top-level ``sanitized_*.json`` sidecars and any
    sibling ``<sessionId>/subagents/sanitized_*.json`` so subagent
    sidecars produced by ``--sanitize`` round-trip back to their
    original JSONLs in place.
    """
    secret = _read_secret()
    if secret is None:
        return 1
    resolved = path.resolve()
    if not resolved.exists():
        log.error(f"path not found: {resolved}")
        return 1
    if resolved.is_file():
        candidates = [resolved]
    else:
        top_level = sorted(resolved.glob("*.json"))
        nested = sorted(resolved.glob("*/subagents/*.json"))
        candidates = top_level + nested
    if not candidates:
        log.error(f"no sanitised sidecar files found at {resolved}")
        return 1
    processed = 0
    for input_file in candidates:
        try:
            payload = read_json(input_file)
        except (OSError, json.JSONDecodeError) as error:
            log.warn(f"skipping {input_file.name}: {error}")
            continue
        if not is_sanitised_payload(payload):
            continue
        try:
            plaintext = unsanitise_to_text(payload, secret)
        except ValueError as error:
            log.error(f"cannot unsanitize {input_file.name}: {error}")
            return 1
        stem = input_file.stem
        if stem.startswith(SANITIZED_FILENAME_PREFIX):
            stem = stem[len(SANITIZED_FILENAME_PREFIX) :]
        output_path = input_file.parent / f"{UNSANITIZED_FILENAME_PREFIX}{stem}.jsonl"
        write_file_text(output_path, plaintext)
        log.info(f"unsanitised: {input_file.name} -> {output_path.name}")
        processed += 1
    if processed == 0:
        log.error(f"no sanitised sidecars matched at {resolved}")
        return 1
    return 0


def _read_secret() -> bytes | None:
    """Return the configured encryption key, or ``None`` after logging an error."""
    secret = os.environ.get(SECRET_ENV_VAR, "")
    if not secret:
        log.error(f"environment variable {SECRET_ENV_VAR} must be set for sanitisation operations")
        return None
    return secret.encode("utf-8")


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser for the CLI."""
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
        help=(
            "Framework label for the submission. Required for "
            "metric and inspection modes; ignored by --sanitize "
            "and --unsanitize."
        ),
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help=(
            "Print a counts-and-events summary for the submission "
            "(record-type counts, per-conversation roles, queue "
            "lifecycle counts, derived turn counts)."
        ),
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
            "input bucket, in characters. Affects the user-input "
            "dimension's bucket distributions and magnitudes."
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
        "--sanitize",
        action="store_true",
        help=(
            "Encrypt every *.jsonl file at the path with "
            "CC_PARSER_SECRET and write a sanitised sidecar "
            "(sanitized_<name>.json) alongside each input."
        ),
    )
    parser.add_argument(
        "--unsanitize",
        action="store_true",
        help=(
            "Decrypt every sanitised JSON sidecar at the path "
            "with CC_PARSER_SECRET and write the restored JSONL "
            "(unsanitized_<name>.jsonl) alongside each input."
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
