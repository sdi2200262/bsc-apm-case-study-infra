# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Human-readable renderers for the parser's three terminal modes.

The CLI in ``__main__`` drives ``--inspect``, ``--economic``, and
``--process`` against a loaded session and prints a summary that
fits a terminal. The summary shapes are intentionally different
from the canonical metrics artifact: the artifact is a single
nested JSON document optimised for downstream consumers, while
these renderers walk the same in-memory session and lay out
counts, distributions, and invariants in a form a human can read
at a glance during development or troubleshooting.

Each renderer is a pure side-effect function that emits through the
terminal logging module and returns ``None``; they share no state
with the CLI beyond the loaded session and the rate table their
mode requires.
"""

from __future__ import annotations

from collections import Counter

from .. import log
from ..data.aggregate.counts import (
    compute_tool_counts,
    compute_user_input_counts,
    turn_count,
)
from ..data.aggregate.tokens import TokenData
from ..data.buckets import BUCKETS
from ..data.conversation import STEER_FATE_DELIVERED
from ..data.prompts import is_user_authored_prompt
from ..data.schema import (
    is_compact_summary_user,
    is_synthetic_assistant,
    queue_operation,
)
from ..data.session import Session
from ..metrics.cost import CostMetrics
from ..metrics.reliability import tool_success_rate
from ..metrics.time import compute_time_metrics
from ..metrics.user_input import compute_user_input_shares
from ..rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
)
from .notices import collect_notices


def print_inspection(session: Session) -> None:
    """Render a counts-and-events summary of a loaded session to stdout."""
    log.info(f"framework: {session.framework}")
    log.info(f"conversation files: {len(session.views)}")
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
    log.blank()
    log.info("per-conversation:")
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
        log.info(f"  {conversation.path}")
        log.info(f"    role:                       {view.role}")
        log.info(f"    first_command:              {view.first_command!r}")
        log.info(f"    first_record_timestamp:     {view.first_record_timestamp}")
        log.info(f"    records:                    {len(records)}")
        for record_type, count in sorted(per_file_counts.items()):
            log.info(f"      {record_type:32} {count}")
        if per_file_subtypes:
            log.info("    subtypes:")
            for (record_type, subtype), count in sorted(per_file_subtypes.items()):
                log.info(f"      {record_type}/{subtype:24} {count}")
        if per_file_queue:
            log.info("    queue operations:")
            for op, count in sorted(per_file_queue.items()):
                log.info(f"      {op:32} {count}")
        log.info(f"    genuine user prompts:       {per_file_user_prompts}")
        log.info(f"    compact-summary records:    {per_file_compact_summary}")
        log.info(f"    synthetic assistant records: {per_file_synthetic}")
        log.info(f"    unique requestIds:          {unique_request_ids}")
        log.info(f"    steers (delivered/abandoned): {delivered}/{abandoned}")
        log.info(f"    compaction events:          {compaction_count}")
        log.info(f"    derived turns:              {len(turns)}")
        if warnings_count:
            log.info("    queue lifecycle warnings:")
            for warning in conversation.queue_lifecycle_warnings:
                log.info(f"      - {warning}")
    log.blank()
    log.info("session totals:")
    log.info(f"  records:                       {total_records}")
    log.info("  record types:")
    for record_type, count in sorted(record_counts.items()):
        log.info(f"    {record_type:32} {count}")
    if subtype_counts:
        log.info("  subtypes:")
        for (record_type, subtype), count in sorted(subtype_counts.items()):
            log.info(f"    {record_type}/{subtype:24} {count}")
    if queue_op_counts:
        log.info("  queue operations:")
        for op, count in sorted(queue_op_counts.items()):
            log.info(f"    {op:32} {count}")
    log.info(f"  genuine user prompts:          {genuine_user_prompts}")
    log.info(f"  compact-summary records:       {compact_summary_records}")
    log.info(f"  synthetic assistant records:   {synthetic_assistant_records}")
    log.info(f"  unique requestIds (deduped):   {total_unique_request_ids}")
    log.info(f"  steers (delivered/abandoned):  {total_steers_delivered}/{total_steers_abandoned}")
    log.info(f"  compaction events:             {total_compaction_events}")
    log.info(f"  queue lifecycle warnings:      {total_queue_warnings}")
    log.info(f"  derived turns:                 {len(session.turns)}")


def print_economic(tokens: TokenData, cost: CostMetrics, rate_table: RateTable) -> None:
    """Render the session-scope economic metric block to stdout.

    The output groups the three populations the parser distinguishes
    (main API calls, delegated subagent dispatches, and their sum),
    shows the modal main-call model alongside the rate-table
    metadata, and reports the per-model token distribution and the
    delegated-attribution mix that drove the headline cost figure.
    """
    log.info("economic dimension (session scope):")
    log.info(f"  modal main model:             {tokens.model or '(none)'}")
    log.info(f"  rate table snapshot date:     {rate_table.snapshot_date}")
    log.info(f"  rate table source path:       {rate_table.source_path}")
    log.info("  pricing sources:")
    for url in rate_table.sources:
        log.info(f"    - {url}")
    log.blank()
    log.info(
        f"  agent dispatches (total/with usage): "
        f"{tokens.agent_dispatches_total}/{tokens.agent_dispatches_with_usage}"
    )
    log.blank()
    log.info(f"  {'category':12} {'main':>14} {'delegated':>14} {'total':>14}")
    for category, main, delegated, total in (
        (CATEGORY_INPUT, tokens.main.input, tokens.delegated.input, tokens.total.input),
        (CATEGORY_OUTPUT, tokens.main.output, tokens.delegated.output, tokens.total.output),
        (
            CATEGORY_CACHE_READ,
            tokens.main.cache_read,
            tokens.delegated.cache_read,
            tokens.total.cache_read,
        ),
        (CATEGORY_CACHE_5M, tokens.main.cache_5m, tokens.delegated.cache_5m, tokens.total.cache_5m),
        (CATEGORY_CACHE_1H, tokens.main.cache_1h, tokens.delegated.cache_1h, tokens.total.cache_1h),
    ):
        log.info(f"  {category:12} {main:>14,} {delegated:>14,} {total:>14,}")
    log.blank()
    log.info(f"  total prompt tokens:          {tokens.total_prompt_tokens:>14,}")
    log.blank()
    log.info("  per-model billed token volume:")
    for model, volume in sorted(
        tokens.model_token_distribution.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        log.info(f"    {model:30} {volume:>14,}")
    log.blank()
    if cost.cost_usd is not None:
        log.info(f"  cost_usd:                     ${cost.cost_usd:.4f}")
    else:
        lower = cost.cost_usd_lower_bound or 0.0
        upper = cost.cost_usd_upper_bound or 0.0
        log.info(f"  cost_usd_lower_bound:         ${lower:.4f}")
        log.info(f"  cost_usd_upper_bound:         ${upper:.4f}")
    if tokens.dispatches_resolved_without_index > 0:
        log.info(
            f"  dispatches priced via fallback resolver: "
            f"{tokens.dispatches_resolved_without_index} "
            f"(bracketed: {tokens.dispatches_bracketed})"
        )


def print_process(session: Session, short_threshold: int) -> None:
    """Render the session-scope process metric blocks to stdout.

    Lays out the time sub-block, the user_input sub-block, and the
    supplementary tool-success rate.
    """
    all_steers = tuple(event for view in session.views for event in view.conversation.steer_events)
    all_records = [record for view in session.views for record in view.conversation.records]
    time_metrics = compute_time_metrics(session.turns)
    scope_turn_count = turn_count(session.turns)
    user_input_counts = compute_user_input_counts(session.turns, all_steers, short_threshold)
    user_input_shares = compute_user_input_shares(user_input_counts)
    success_rate = tool_success_rate(compute_tool_counts(all_records))
    log.info("process dimension (session scope):")
    log.blank()
    log.info("  time:")
    log.info(f"    duration:                {time_metrics.duration:14.2f} sec")
    log.info(f"    turn_time:               {time_metrics.turn_time:14.2f} sec")
    log.info(f"    turn_time_solo:          {time_metrics.turn_time_solo:14.2f} sec")
    log.info(f"    turn_time_concurrent:    {time_metrics.turn_time_concurrent:14.2f} sec")
    log.info(f"    inter_turn_time:         {time_metrics.inter_turn_time:14.2f} sec")
    log.info(f"    turn_count:              {scope_turn_count:14d}")
    log.info(f"    mean_turn_duration:      {time_metrics.mean_turn_duration:14.2f} sec")
    log.info(f"    turn_duration_p50:       {time_metrics.turn_duration_p50:14.2f} sec")
    log.info(f"    turn_duration_p95:       {time_metrics.turn_duration_p95:14.2f} sec")
    log.info(f"    turn_duration_stdev:     {time_metrics.turn_duration_stdev:14.2f} sec")
    log.info(
        f"    invariant duration ?= turn_time + inter_turn_time: "
        f"{time_metrics.duration:.2f} ?= "
        f"{time_metrics.turn_time + time_metrics.inter_turn_time:.2f}"
    )
    log.info(
        f"    invariant turn_time ?= solo + concurrent:          "
        f"{time_metrics.turn_time:.2f} ?= "
        f"{time_metrics.turn_time_solo + time_metrics.turn_time_concurrent:.2f}"
    )
    log.blank()
    log.info("  user_input:")
    log.info(f"    short_threshold:         {short_threshold}")
    log.info(f"    turn_prompt_count:       {user_input_counts.turn_prompt_count}")
    log.info(f"    steer_delivered_count:   {user_input_counts.steer_delivered_count}")
    log.info(f"    steer_abandoned_count:   {user_input_counts.steer_abandoned_count}")
    log.info(f"    steer_attempted_count:   {user_input_counts.steer_attempted_count}")
    log.info("    turn_prompts_bucket_shares:")
    for bucket in BUCKETS:
        log.info(f"      {bucket:10} {user_input_shares.turn_prompts_bucket_shares[bucket]:.4f}")
    log.info("    steer_delivered_bucket_shares:")
    for bucket in BUCKETS:
        log.info(f"      {bucket:10} {user_input_shares.steer_delivered_bucket_shares[bucket]:.4f}")
    log.info("    all_inputs_bucket_shares:")
    for bucket in BUCKETS:
        log.info(f"      {bucket:10} {user_input_shares.all_inputs_bucket_shares[bucket]:.4f}")
    log.info("    turn_prompts_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        log.info(
            f"      {bucket:10} {user_input_shares.turn_prompts_magnitude_by_bucket[bucket]:.1f}"
        )
    log.info("    steer_delivered_magnitude_by_bucket (mean chars):")
    for bucket in BUCKETS:
        log.info(
            f"      {bucket:10} {user_input_shares.steer_delivered_magnitude_by_bucket[bucket]:.1f}"
        )
    log.blank()
    log.info("  supplementary:")
    log.info(f"    tool_success_rate:       {success_rate:.4f}")
    log.notice_block((n.tag, n.label, n.summary, n.detail) for n in collect_notices(session))
