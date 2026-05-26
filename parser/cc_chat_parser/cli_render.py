#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Human-readable renderers for the parser's three terminal modes.

The CLI in ``__main__`` drives ``--inspect``, ``--economic``, and
``--process`` against a loaded session and prints a summary that
fits a terminal. The summary shapes are intentionally different
from the canonical metrics artifact: the artifact is a single
nested JSON document optimised for downstream consumers, while
these renderers walk the same in-memory session and lay out
counts, distributions, and invariants in a form a human can read
at a glance during development or troubleshooting.

Each renderer is a pure side-effect function that writes to
stdout and returns ``None``; they share no state with the CLI
beyond the loaded session and the rate table their mode requires.
"""

from __future__ import annotations

from collections import Counter

from .buckets import BUCKETS
from .loader import STEER_FATE_DELIVERED
from .metrics.economic import EconomicSession
from .metrics.reliability import compute_reliability_metrics
from .metrics.time import compute_time_metrics
from .metrics.user_input import compute_user_input_metrics
from .rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
)
from .schema import (
    is_compact_summary_user,
    is_synthetic_assistant,
    queue_operation,
)
from .session import Session
from .user_prompts import is_user_authored_prompt


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
            if is_user_authored_prompt(record):
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
            print("    subtypes:")
            for (record_type, subtype), count in sorted(per_file_subtypes.items()):
                print(f"      {record_type}/{subtype:24} {count}")
        if per_file_queue:
            print("    queue operations:")
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
            print("    queue lifecycle warnings:")
            for warning in conversation.queue_lifecycle_warnings:
                print(f"      - {warning}")
    print()
    print("session totals:")
    print(f"  records:                       {total_records}")
    print("  record types:")
    for record_type, count in sorted(record_counts.items()):
        print(f"    {record_type:32} {count}")
    if subtype_counts:
        print("  subtypes:")
        for (record_type, subtype), count in sorted(subtype_counts.items()):
            print(f"    {record_type}/{subtype:24} {count}")
    if queue_op_counts:
        print("  queue operations:")
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
    (main API calls, delegated subagent dispatches, and their sum),
    shows the modal main-call model alongside the rate-table
    metadata, and reports the per-model token distribution and the
    delegated-attribution mix that drove the headline cost figure.
    """
    print("economic dimension (session scope):")
    print(f"  modal main model:             {economic.model or '(none)'}")
    print(f"  rate table snapshot date:     {rate_table.snapshot_date}")
    print(f"  rate table source path:       {rate_table.source_path}")
    print("  pricing sources:")
    for url in rate_table.sources:
        print(f"    - {url}")
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
    print("  per-model billed token volume:")
    for model, tokens in sorted(
        economic.model_token_distribution.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(f"    {model:30} {tokens:>14,}")
    print()
    if economic.cost_usd is not None:
        print(f"  cost_usd:                     ${economic.cost_usd:.4f}")
    else:
        lower = economic.cost_usd_lower_bound or 0.0
        upper = economic.cost_usd_upper_bound or 0.0
        print(f"  cost_usd_lower_bound:         ${lower:.4f}")
        print(f"  cost_usd_upper_bound:         ${upper:.4f}")
    if economic.dispatches_resolved_without_index > 0:
        print(
            f"  dispatches priced via fallback resolver: "
            f"{economic.dispatches_resolved_without_index} "
            f"(bracketed: {economic.dispatches_bracketed})"
        )


def print_process(session: Session, short_threshold: int) -> None:
    """Render the session-scope process metric blocks (time, user input) and the supplementary tool-success rate."""
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
    print("    turn_prompts_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.turn_prompts_bucket_shares[bucket]:.4f}")
    print("    steer_delivered_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.steer_delivered_bucket_shares[bucket]:.4f}")
    print("    all_inputs_bucket_shares:")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.all_inputs_bucket_shares[bucket]:.4f}")
    print("    turn_prompts_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.turn_prompts_magnitude_by_bucket[bucket]:.1f}")
    print("    steer_delivered_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        print(f"      {bucket:10} {user_input_metrics.steer_delivered_magnitude_by_bucket[bucket]:.1f}")
    print()
    print("  supplementary:")
    print(f"    tool_success_rate:       {reliability_metrics.tool_success_rate:.4f}")
