# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Human-readable renderers for the parser's two terminal modes.

The CLI in ``__main__`` drives ``--economic`` and ``--process`` against a
loaded session and prints a terminal-fit summary for development and
troubleshooting. These views walk the same in-memory
session as the canonical artifact (assembled in ``build``) but lay it out
for a human reader rather than a downstream consumer.

Each renderer is a pure side-effect function that emits through the
terminal logging module and returns ``None``.
"""

from __future__ import annotations

from .. import log
from ..data.aggregate.counts import (
    compute_tool_counts,
    compute_user_input_counts,
    turn_count,
)
from ..data.aggregate.tokens import TokenData
from ..data.buckets import BUCKETS
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


def print_economic(tokens: TokenData, cost: CostMetrics, rate_table: RateTable) -> None:
    """Render the session-scope economic metric block to stdout.

    Lays out per-category token volumes across the three populations the
    parser distinguishes (main calls, delegated dispatches, their sum), the
    rate-table metadata, the per-model token distribution, and the cost.
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
    rate_text = f"{success_rate:.4f}" if success_rate is not None else "n/a (no tool results)"
    log.info(f"    tool_success_rate:       {rate_text}")
    log.notice_block((n.tag, n.label, n.summary, n.detail) for n in collect_notices(session))
