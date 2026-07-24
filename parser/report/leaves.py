# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Bare-value leaf rendering for the data and metrics artifacts.

This module owns the per-dimension renderers that turn computed data and
metric blocks into flat ``name: value`` dicts. The kind, analysis label,
and formula are not repeated per leaf: they live in ``parser.contract``.
The renderers are grouped by which of the two artifacts they feed (the
data/metrics split is owned by ``build``); an empty scope renders zero
values to keep the per-scope shape uniform.
"""

from __future__ import annotations

from typing import Any

from ..data.aggregate.counts import RequestCounts, SubagentCounts, ToolCounts, UserInputCounts
from ..data.aggregate.tokens import TokenData
from ..metrics.cost import CostMetrics
from ..metrics.time import TimeMetrics
from ..metrics.user_input import TurnPromptBuckets

_TOKEN_CATEGORIES: tuple[str, ...] = ("input", "output", "cache_read", "cache_5m", "cache_1h")


def token_leaves(tokens: TokenData | None) -> dict[str, int]:
    """Render the per-scope token-sum data leaves.

    An empty scope (``tokens is None``) renders every token leaf at zero so
    the data artifact's per-scope shape is uniform.

    Args:
        tokens: The scope's token data, or ``None`` for an empty scope.

    Returns:
        The sixteen token-sum leaves: the five categories for each of the
        main, delegated, and total populations, plus ``total_prompt_tokens``.
    """
    if tokens is None:
        keys = [
            f"{population}_{category}_tokens"
            for population in ("main", "delegated", "total")
            for category in _TOKEN_CATEGORIES
        ]
        return {key: 0 for key in keys} | {"total_prompt_tokens": 0}
    return {
        "main_input_tokens": tokens.main.input,
        "main_output_tokens": tokens.main.output,
        "main_cache_read_tokens": tokens.main.cache_read,
        "main_cache_5m_tokens": tokens.main.cache_5m,
        "main_cache_1h_tokens": tokens.main.cache_1h,
        "delegated_input_tokens": tokens.delegated.input,
        "delegated_output_tokens": tokens.delegated.output,
        "delegated_cache_read_tokens": tokens.delegated.cache_read,
        "delegated_cache_5m_tokens": tokens.delegated.cache_5m,
        "delegated_cache_1h_tokens": tokens.delegated.cache_1h,
        "total_input_tokens": tokens.total.input,
        "total_output_tokens": tokens.total.output,
        "total_cache_read_tokens": tokens.total.cache_read,
        "total_cache_5m_tokens": tokens.total.cache_5m,
        "total_cache_1h_tokens": tokens.total.cache_1h,
        "total_prompt_tokens": tokens.total_prompt_tokens,
    }


def model_token_distribution_leaves(tokens: TokenData | None) -> dict[str, dict[str, int]]:
    """Render the per-scope model-token-distribution data leaf.

    An empty scope (``tokens is None``) renders an empty distribution.

    Args:
        tokens: The scope's token data, or ``None`` for an empty scope.

    Returns:
        The ``model_token_distribution`` leaf.
    """
    return {"model_token_distribution": {} if tokens is None else tokens.model_token_distribution}


def request_count_leaves(counts: RequestCounts) -> dict[str, int]:
    """Render the per-scope request-count data leaves.

    Args:
        counts: The scope's request counts.

    Returns:
        The ``request_count``, ``delegated_request_count``, and
        ``requests_with_tool_use_count`` leaves.
    """
    # Emitted once, in the data artifact: a request is the same population
    # whether used as a cost denominator or a model-action count.
    return {
        "request_count": counts.request_count,
        "delegated_request_count": counts.delegated_request_count,
        "requests_with_tool_use_count": counts.requests_with_tool_use_count,
    }


def user_input_count_leaves(counts: UserInputCounts) -> dict[str, int]:
    """Render the per-scope user-input count data leaves.

    Args:
        counts: The scope's user-input counts.

    Returns:
        The turn-prompt count and the two disjoint steer counts.
    """
    return {
        "turn_prompt_count": counts.turn_prompt_count,
        "steer_delivered_count": counts.steer_delivered_count,
        "steer_abandoned_count": counts.steer_abandoned_count,
    }


def supplementary_data_leaves(counts: SubagentCounts) -> dict[str, int]:
    """Render the per-scope subagent-activity count data leaves.

    Args:
        counts: The scope's subagent counts.

    Returns:
        The ``subagent_count``, ``subagent_tool_count``,
        ``subagent_request_count``, and ``model_invoked_skill_count``
        leaves.
    """
    return {
        "subagent_count": counts.subagent_count,
        "subagent_tool_count": counts.subagent_tool_count,
        "subagent_request_count": counts.subagent_request_count,
        "model_invoked_skill_count": counts.model_invoked_skill_count,
    }


def tool_count_leaves(counts: ToolCounts) -> dict[str, int]:
    """Render the per-scope tool-result count data leaves.

    Args:
        counts: The scope's tool counts.

    Returns:
        The ``tool_result_count`` and ``tool_error_count`` leaves.
    """
    return {
        "tool_result_count": counts.tool_result_count,
        "tool_error_count": counts.tool_error_count,
    }


def cost_leaves(cost: CostMetrics | None) -> dict[str, float]:
    """Render the per-scope cost metric leaves.

    The shape is conditional. An empty scope or a scope whose every
    dispatch priced deterministically renders a single ``cost_usd``; a
    scope with at least one bracketed dispatch renders
    ``cost_usd_lower_bound`` and ``cost_usd_upper_bound`` and omits
    ``cost_usd``. Values are rounded to four decimal places.

    Args:
        cost: The scope's cost metric, or ``None`` for an empty scope.

    Returns:
        Either ``{"cost_usd": ...}`` or the bounded pair.
    """
    if cost is None:
        return {"cost_usd": 0.0}
    if cost.cost_usd is not None:
        return {"cost_usd": round(cost.cost_usd, 4)}
    return {
        "cost_usd_lower_bound": round(cost.cost_usd_lower_bound or 0.0, 4),
        "cost_usd_upper_bound": round(cost.cost_usd_upper_bound or 0.0, 4),
    }


def time_leaves(metrics: TimeMetrics) -> dict[str, float]:
    """Render a session-or-phase time metric block.

    Args:
        metrics: The scope's time metrics.

    Returns:
        The nine time-statistic metric leaves.
    """
    return {
        "duration": metrics.duration,
        "turn_time": metrics.turn_time,
        "turn_time_solo": metrics.turn_time_solo,
        "turn_time_concurrent": metrics.turn_time_concurrent,
        "inter_turn_time": metrics.inter_turn_time,
        "mean_turn_duration": metrics.mean_turn_duration,
        "turn_duration_p50": metrics.turn_duration_p50,
        "turn_duration_p95": metrics.turn_duration_p95,
        "turn_duration_stdev": metrics.turn_duration_stdev,
    }


def time_leaves_role(metrics: TimeMetrics, turn_count: int) -> dict[str, float]:
    """Render a role-scope time metric block.

    A role's ``turn_time`` is the sum of per-turn durations rather than the
    union of intervals: within a single conversation file the participant
    cannot drive two overlapping prompts, so the two coincide, and the sum
    form surfaces if a future role rollup ever folds in turns from multiple
    files.

    Args:
        metrics: The role's time metrics.
        turn_count: The role's turn count, used to form the summed
            ``turn_time``.

    Returns:
        The five role-scope time-statistic metric leaves.
    """
    return {
        "turn_time": metrics.mean_turn_duration * turn_count,
        "mean_turn_duration": metrics.mean_turn_duration,
        "turn_duration_p50": metrics.turn_duration_p50,
        "turn_duration_p95": metrics.turn_duration_p95,
        "turn_duration_stdev": metrics.turn_duration_stdev,
    }


def turn_prompt_bucket_leaves(buckets: TurnPromptBuckets) -> dict[str, Any]:
    """Render the per-scope turn-prompt bucket metric leaves.

    Args:
        buckets: The scope's turn-prompt bucket shares and magnitudes.

    Returns:
        The bucket-share and magnitude metric leaves.
    """
    return {
        "turn_prompts_bucket_shares": buckets.turn_prompts_bucket_shares,
        "turn_prompts_magnitude_by_bucket": buckets.turn_prompts_magnitude_by_bucket,
    }
