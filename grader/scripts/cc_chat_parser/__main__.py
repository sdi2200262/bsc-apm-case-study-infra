#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Command-line interface for the Claude Code chat parser.

Five modes are available, all selected by flag and combinable
(``--inspect``, ``--economic``, and ``--process`` print
human-readable summaries; ``--metrics`` writes the canonical
scope-nested JSON artifact; ``--sanitize`` and ``--unsanitize``
seal and unseal the raw JSONL files for archival).

Usage:
    python -m cc_chat_parser <path> --framework {apm,speckit} --metrics -o out.json
    python -m cc_chat_parser <path> --framework {apm,speckit} --inspect
    python -m cc_chat_parser <path> --framework {apm,speckit} --economic
    python -m cc_chat_parser <path> --framework {apm,speckit} --process
    python -m cc_chat_parser <path> --sanitize
    python -m cc_chat_parser <path> --unsanitize

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
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

import json

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from .buckets import BUCKETS, DEFAULT_SHORT_THRESHOLD
from .commands import FRAMEWORK_APM, FRAMEWORK_SPECKIT
from .io import is_sanitised_payload, load_json, write_file_text, write_json
from .loader import STEER_FATE_DELIVERED, discover_conversation_files
from .metrics.economic import EconomicSession, compute_session_economic
from .metrics.reliability import ReliabilityMetrics, compute_reliability_metrics
from .metrics.time import TimeMetrics, compute_time_metrics
from .metrics.user_input import UserInputMetrics, compute_user_input_metrics
from .rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
    RateTableError,
    load_rate_table,
    rates_for_model,
)
from .report import build_report
from .sanitize import sanitise_jsonl_file, unsanitise_to_text
from .schema import (
    SchemaError,
    is_compact_summary_user,
    is_genuine_user_prompt,
    is_synthetic_assistant,
    queue_operation,
)
from .session import Session, load_session

SECRET_ENV_VAR = "CC_PARSER_SECRET"
SANITIZED_FILENAME_PREFIX = "sanitized_"
UNSANITIZED_FILENAME_PREFIX = "unsanitized_"


def create_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m cc_chat_parser",
        description=(
            "Read Claude Code CLI JSONL conversation files from a submission "
            "and report the parser's view of their structure."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        type=Path,
        help=(
            "Path to a single .jsonl file or a directory of .jsonl files "
            "copied straight from ~/.claude/projects/<dashed-cwd>/."
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
            "input, reliability) at session scope."
        ),
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help=(
            "Build the canonical scope-nested metrics artifact "
            "(session, phases, roles for APM, turns, diagnostics) "
            "and write it to --output, or stdout when --output is "
            "absent."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Destination path for --metrics output. Default writes to stdout.",
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
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional list of argument strings; defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Process exit code: ``0`` on success, non-zero on error.
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.sanitize and args.unsanitize:
        print("error: --sanitize and --unsanitize are mutually exclusive", file=sys.stderr)
        return 2
    if args.sanitize:
        return _run_sanitize(args.path)
    if args.unsanitize:
        return _run_unsanitize(args.path)
    if not (args.inspect or args.economic or args.process or args.metrics):
        parser.print_help(sys.stderr)
        return 2
    if args.framework is None:
        print(
            "error: --framework is required for inspection and metric modes",
            file=sys.stderr,
        )
        return 2
    try:
        session = load_session(args.path, args.framework)
    except SchemaError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    printed_any = False
    if args.inspect:
        print_inspection(session)
        printed_any = True
    if args.economic:
        if printed_any:
            print()
        try:
            rate_table = load_rate_table()
            economic = compute_session_economic(session, rate_table)
        except RateTableError as error:
            print(f"error: cost computation failed: {error}", file=sys.stderr)
            return 1
        print_economic(economic, rate_table)
        printed_any = True
    if args.process:
        if printed_any:
            print()
        print_process(session, args.short_threshold)
        printed_any = True
    if args.metrics:
        try:
            rate_table = load_rate_table()
            artifact = build_report(session, rate_table, args.short_threshold)
        except RateTableError as error:
            print(f"error: metrics build failed: {error}", file=sys.stderr)
            return 1
        if args.output is not None:
            with args.output.open("w", encoding="utf-8") as sink:
                json.dump(artifact, sink, indent=2, ensure_ascii=False)
            print(f"metrics written to {args.output}", file=sys.stderr)
        else:
            json.dump(artifact, sys.stdout, indent=2, ensure_ascii=False)
            print()
    return 0


def print_inspection(session: Session) -> None:
    """Render a counts-and-events summary of a loaded session to stdout."""
    print(f"framework: {session.framework}")
    print(f"conversation files: {len(session.views)}")
    record_counts: Counter[str] = Counter()
    subtype_counts: Counter[tuple[str, str]] = Counter()
    queue_op_counts: Counter[str] = Counter()
    genuine_user_prompts = 0
    compact_summary_records = 0
    synthetic_assistant_records = 0
    total_records = 0
    total_unique_request_ids = 0
    total_steer_events = 0
    total_steers_delivered = 0
    total_steers_abandoned = 0
    total_compaction_events = 0
    total_queue_warnings = 0
    print()
    print("per-conversation:")
    for view in session.views:
        conversation = view.conversation
        records = conversation.records
        total_records += len(records)
        per_file_counts: Counter[str] = Counter()
        per_file_subtypes: Counter[tuple[str, str]] = Counter()
        per_file_queue: Counter[str] = Counter()
        per_file_user_prompts = 0
        per_file_compact_summary = 0
        per_file_synthetic = 0
        for record in records:
            per_file_counts[record.record_type] += 1
            record_counts[record.record_type] += 1
            if record.subtype:
                per_file_subtypes[(record.record_type, record.subtype)] += 1
                subtype_counts[(record.record_type, record.subtype)] += 1
            op = queue_operation(record)
            if op:
                per_file_queue[op] += 1
                queue_op_counts[op] += 1
            if is_genuine_user_prompt(record):
                per_file_user_prompts += 1
                genuine_user_prompts += 1
            if is_compact_summary_user(record):
                per_file_compact_summary += 1
                compact_summary_records += 1
            if is_synthetic_assistant(record):
                per_file_synthetic += 1
                synthetic_assistant_records += 1
        unique_request_ids = len(conversation.usage_index.usage_by_request_id)
        total_unique_request_ids += unique_request_ids
        user_steer_events = [ev for ev in conversation.steer_events if ev.is_user_authored]
        steer_count = len(user_steer_events)
        total_steer_events += steer_count
        delivered = sum(1 for ev in user_steer_events if ev.fate == STEER_FATE_DELIVERED)
        abandoned = steer_count - delivered
        total_steers_delivered += delivered
        total_steers_abandoned += abandoned
        compaction_count = len(conversation.compaction_events)
        total_compaction_events += compaction_count
        warnings_count = len(conversation.queue_lifecycle_warnings)
        total_queue_warnings += warnings_count
        turns = [t for t in session.turns if t.conversation_path == conversation.path]
        print(f"  {conversation.path}")
        print(f"    role:                       {view.role}")
        print(f"    first_command:              {view.first_command!r}")
        print(f"    first_record_timestamp:     {view.first_record_timestamp}")
        print(f"    records:                    {len(records)}")
        for record_type, count in sorted(per_file_counts.items()):
            print(f"      {record_type:32} {count}")
        if per_file_subtypes:
            print(f"    subtypes:")
            for (record_type, subtype), count in sorted(per_file_subtypes.items()):
                print(f"      {record_type}/{subtype:24} {count}")
        if per_file_queue:
            print(f"    queue operations:")
            for op, count in sorted(per_file_queue.items()):
                print(f"      {op:32} {count}")
        print(f"    genuine user prompts:       {per_file_user_prompts}")
        print(f"    compact-summary records:    {per_file_compact_summary}")
        print(f"    synthetic assistant records: {per_file_synthetic}")
        print(f"    unique requestIds:          {unique_request_ids}")
        print(f"    steers (delivered/abandoned): {delivered}/{abandoned}")
        print(f"    compaction events:          {compaction_count}")
        print(f"    derived turns:              {len(turns)}")
        if warnings_count:
            print(f"    queue lifecycle warnings:")
            for warning in conversation.queue_lifecycle_warnings:
                print(f"      - {warning}")
    print()
    print("session totals:")
    print(f"  records:                       {total_records}")
    print(f"  record types:")
    for record_type, count in sorted(record_counts.items()):
        print(f"    {record_type:32} {count}")
    if subtype_counts:
        print(f"  subtypes:")
        for (record_type, subtype), count in sorted(subtype_counts.items()):
            print(f"    {record_type}/{subtype:24} {count}")
    if queue_op_counts:
        print(f"  queue operations:")
        for op, count in sorted(queue_op_counts.items()):
            print(f"    {op:32} {count}")
    print(f"  genuine user prompts:          {genuine_user_prompts}")
    print(f"  compact-summary records:       {compact_summary_records}")
    print(f"  synthetic assistant records:   {synthetic_assistant_records}")
    print(f"  unique requestIds (deduped):   {total_unique_request_ids}")
    print(f"  steers (delivered/abandoned):  {total_steers_delivered}/{total_steers_abandoned}")
    print(f"  compaction events:             {total_compaction_events}")
    print(f"  queue lifecycle warnings:      {total_queue_warnings}")
    print(f"  derived turns:                 {len(session.turns)}")


def print_economic(economic: EconomicSession, rate_table: RateTable) -> None:
    """Render the session-scope economic metric block to stdout.

    The output groups the three populations the parser distinguishes
    (main API calls, delegated subagent dispatches, and their sum)
    and shows the per-call cost contribution by category against the
    pinned model's rates so the rate table's effect on the headline
    figure is auditable.
    """
    rates = rates_for_model(rate_table, economic.model)
    print(f"economic dimension (session scope):")
    print(f"  pinned model:                 {economic.model}")
    print(f"  rate table snapshot date:     {rate_table.snapshot_date}")
    print(f"  rate table source path:       {rate_table.source_path}")
    print(f"  pricing sources:")
    for url in rate_table.sources:
        print(f"    - {url}")
    print()
    print(f"  per-million USD rates:        input={rates.input:.2f} "
          f"output={rates.output:.2f} cache_read={rates.cache_read:.2f} "
          f"cache_5m={rates.cache_5m:.2f} cache_1h={rates.cache_1h:.2f}")
    print()
    print(f"  agent dispatches (total/with usage): "
          f"{economic.agent_dispatches_total}/{economic.agent_dispatches_with_usage}")
    print()
    print(f"  {'category':12} {'main':>14} {'delegated':>14} {'total':>14}")
    for category, main, delegated, total in (
        (CATEGORY_INPUT,      economic.main.input,      economic.delegated.input,      economic.total.input),
        (CATEGORY_OUTPUT,     economic.main.output,     economic.delegated.output,     economic.total.output),
        (CATEGORY_CACHE_READ, economic.main.cache_read, economic.delegated.cache_read, economic.total.cache_read),
        (CATEGORY_CACHE_5M,   economic.main.cache_5m,   economic.delegated.cache_5m,   economic.total.cache_5m),
        (CATEGORY_CACHE_1H,   economic.main.cache_1h,   economic.delegated.cache_1h,   economic.total.cache_1h),
    ):
        print(f"  {category:12} {main:>14,} {delegated:>14,} {total:>14,}")
    print()
    print(f"  total prompt tokens:          {economic.total_prompt_tokens:>14,}")
    print()
    print(f"  cost breakdown (USD):")
    breakdown = (
        ("input",      economic.total.input      * rates.input),
        ("output",     economic.total.output     * rates.output),
        ("cache_read", economic.total.cache_read * rates.cache_read),
        ("cache_5m",   economic.total.cache_5m   * rates.cache_5m),
        ("cache_1h",   economic.total.cache_1h   * rates.cache_1h),
    )
    for label, amount in breakdown:
        print(f"    {label:12} ${amount / 1_000_000.0:>10.4f}")
    print(f"  cost_usd:                     ${economic.cost_usd:.4f}")


def print_process(session: Session, short_threshold: int) -> None:
    """Render the session-scope process metric blocks (time, user input, reliability)."""
    all_steers = tuple(
        event
        for view in session.views
        for event in view.conversation.steer_events
    )
    all_records = [
        record
        for view in session.views
        for record in view.conversation.records
    ]
    time_metrics = compute_time_metrics(session.turns)
    user_input_metrics = compute_user_input_metrics(
        session.turns, all_steers, short_threshold
    )
    reliability_metrics = compute_reliability_metrics(all_records)
    print("process dimension (session scope):")
    print()
    print("  time:")
    print(f"    duration:                {time_metrics.duration:14.2f} sec")
    print(f"    turn_time:               {time_metrics.turn_time:14.2f} sec")
    print(f"    turn_time_solo:          {time_metrics.turn_time_solo:14.2f} sec")
    print(f"    turn_time_concurrent:    {time_metrics.turn_time_concurrent:14.2f} sec")
    print(f"    inter_turn_time:         {time_metrics.inter_turn_time:14.2f} sec")
    print(f"    turn_count:              {time_metrics.turn_count:14d}")
    print(f"    mean_turn_duration:      {time_metrics.mean_turn_duration:14.2f} sec")
    print(f"    turn_duration_p50:       {time_metrics.turn_duration_p50:14.2f} sec")
    print(f"    turn_duration_p95:       {time_metrics.turn_duration_p95:14.2f} sec")
    print(f"    turn_duration_stdev:     {time_metrics.turn_duration_stdev:14.2f} sec")
    print(f"    invariant duration ?= turn_time + inter_turn_time: "
          f"{time_metrics.duration:.2f} ?= {time_metrics.turn_time + time_metrics.inter_turn_time:.2f}")
    print(f"    invariant turn_time ?= solo + concurrent:          "
          f"{time_metrics.turn_time:.2f} ?= "
          f"{time_metrics.turn_time_solo + time_metrics.turn_time_concurrent:.2f}")
    print()
    print("  user_input:")
    print(f"    short_threshold:         {short_threshold}")
    print(f"    turn_prompt_count:       {user_input_metrics.turn_prompt_count}")
    print(f"    steer_delivered_count:   {user_input_metrics.steer_delivered_count}")
    print(f"    steer_abandoned_count:   {user_input_metrics.steer_abandoned_count}")
    print(f"    steer_attempted_count:   {user_input_metrics.steer_attempted_count}")
    print(f"    turn_prompts_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.turn_prompts_bucket_shares[bucket]:.4f}")
    print(f"    steer_delivered_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.steer_delivered_bucket_shares[bucket]:.4f}")
    print(f"    all_inputs_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.all_inputs_bucket_shares[bucket]:.4f}")
    print(f"    turn_prompts_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.turn_prompts_magnitude_by_bucket[bucket]:.1f}")
    print(f"    steer_delivered_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.steer_delivered_magnitude_by_bucket[bucket]:.1f}")
    print()
    print("  reliability:")
    print(f"    tool_result_count:       {reliability_metrics.tool_result_count}")
    print(f"    tool_error_count:        {reliability_metrics.tool_error_count}")
    print(f"    tool_success_rate:       {reliability_metrics.tool_success_rate:.4f}")


def _run_sanitize(path: Path) -> int:
    """Encrypt every ``*.jsonl`` file at ``path`` and write a sidecar next to it."""
    secret = _read_secret()
    if secret is None:
        return 1
    try:
        files = discover_conversation_files(path)
    except SchemaError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for input_file in files:
        sidecar = sanitise_jsonl_file(input_file, secret)
        output_path = input_file.parent / f"{SANITIZED_FILENAME_PREFIX}{input_file.stem}.json"
        write_json(sidecar, output_path)
        print(f"sanitised: {input_file.name} -> {output_path.name}")
    return 0


def _run_unsanitize(path: Path) -> int:
    """Decrypt every sanitised sidecar at ``path`` and write the restored JSONL."""
    secret = _read_secret()
    if secret is None:
        return 1
    resolved = path.resolve()
    if not resolved.exists():
        print(f"error: path not found: {resolved}", file=sys.stderr)
        return 1
    if resolved.is_file():
        candidates = [resolved]
    else:
        candidates = sorted(resolved.glob("*.json"))
    if not candidates:
        print(f"error: no sanitised sidecar files found at {resolved}", file=sys.stderr)
        return 1
    processed = 0
    for input_file in candidates:
        try:
            payload = load_json(input_file)
        except (OSError, json.JSONDecodeError) as error:
            print(f"warning: skipping {input_file.name}: {error}", file=sys.stderr)
            continue
        if not is_sanitised_payload(payload):
            continue
        try:
            plaintext = unsanitise_to_text(payload, secret)
        except ValueError as error:
            print(f"error: cannot unsanitize {input_file.name}: {error}", file=sys.stderr)
            return 1
        stem = input_file.stem
        if stem.startswith(SANITIZED_FILENAME_PREFIX):
            stem = stem[len(SANITIZED_FILENAME_PREFIX):]
        output_path = input_file.parent / f"{UNSANITIZED_FILENAME_PREFIX}{stem}.jsonl"
        write_file_text(output_path, plaintext)
        print(f"unsanitised: {input_file.name} -> {output_path.name}")
        processed += 1
    if processed == 0:
        print(f"error: no sanitised sidecars matched at {resolved}", file=sys.stderr)
        return 1
    return 0


def _read_secret() -> bytes | None:
    """Return the configured encryption key, or ``None`` after printing an error."""
    secret = os.environ.get(SECRET_ENV_VAR, "")
    if not secret:
        print(
            f"error: environment variable {SECRET_ENV_VAR} must be set "
            "for sanitisation operations",
            file=sys.stderr,
        )
        return None
    return secret.encode("utf-8")


if __name__ == "__main__":
    sys.exit(main())
