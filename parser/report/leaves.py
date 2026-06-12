# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Leaf-block rendering for the canonical metrics artifact.

Every measurement in the artifact is wrapped in a ``{value, label,
constructed}`` triple so the analysis layer can iterate over ``Primary``
metrics to assemble its hypothesis-test family and flag every
``constructed`` metric for the literature-grounding cross-check without
consulting an external index.

Label takes one of three values, naming the metric's role in the
analysis:

- ``Primary``: drives a research-question claim and is hypothesis-tested.
- ``Secondary``: supports or decomposes a ``Primary`` within the same
  dimension.
- ``Supplementary``: descriptive only, no hypothesis test.

``constructed`` is a Boolean. ``True`` means the metric was defined for this
study and rests on face validity until the literature-grounding pass
attaches a published construct; ``False`` means the metric maps directly
onto a JSONL, API, or grader field with aggregation as the only
study-author degree of freedom.

This module owns the per-dimension renderers that translate the data and
metric blocks into leaf-triple dicts. The ``label`` and ``constructed``
flags are hard-coded against the metric definitions; changing one means
editing one renderer here, not threading constants through the computation
modules.
"""

from __future__ import annotations

from typing import Any

from ..data.aggregate.counts import RequestCounts, SubagentCounts, UserInputCounts
from ..data.aggregate.tokens import TokenData
from ..metrics.cost import CostMetrics
from ..metrics.time import TimeMetrics
from ..metrics.user_input import UserInputShares

LABEL_PRIMARY = "Primary"
LABEL_SECONDARY = "Secondary"
LABEL_SUPPLEMENTARY = "Supplementary"


def metric_leaf(value: Any, label: str, constructed: bool) -> dict[str, Any]:
    """Wrap a measurement value in the canonical leaf triple."""
    return {"value": value, "label": label, "constructed": constructed}


def economic_block(
    tokens: TokenData | None,
    cost: CostMetrics | None,
    requests: RequestCounts,
) -> dict[str, Any]:
    """Render an economic block with leaf triples.

    The empty-scope branch emits zero-valued leaves so the artifact's
    shape is uniform across sessions; analysis consumers should filter
    empty scopes by ``turn_count == 0`` rather than by missing keys.

    The cost shape is conditional. A scope whose every delegated dispatch
    was priced deterministically emits a single ``cost_usd`` leaf. A scope
    with at least one bracketed dispatch instead emits
    ``cost_usd_lower_bound`` and ``cost_usd_upper_bound`` leaves and omits
    ``cost_usd`` entirely; consumers that read cost must check for both
    shapes.

    ``request_count`` and ``delegated_request_count`` are mirrored from
    the process-dimension ``requests`` block: the same numeric value
    appears in both locations because a request is a cost denominator
    under the economic dimension and the model-action count under the
    process dimension. Cross-referencing the value would force every
    leaf-iterating consumer to dereference; the duplication keeps the
    leaf-iteration contract intact.
    """
    if tokens is None:
        zero_token = metric_leaf(0, LABEL_SECONDARY, False)
        zero_cost = metric_leaf(0.0, LABEL_PRIMARY, True)
        zero_request = metric_leaf(0, LABEL_SECONDARY, False)
        token_keys = (
            f"{population}_{cat}_tokens"
            for population in ("main", "delegated", "total")
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        )
        return {key: zero_token for key in token_keys} | {
            "total_prompt_tokens": zero_token,
            "cost_usd": zero_cost,
            "request_count": zero_request,
            "delegated_request_count": zero_request,
        }
    block: dict[str, Any] = {
        "main_input_tokens": metric_leaf(tokens.main.input, LABEL_SECONDARY, False),
        "main_output_tokens": metric_leaf(tokens.main.output, LABEL_SECONDARY, False),
        "main_cache_read_tokens": metric_leaf(tokens.main.cache_read, LABEL_SECONDARY, False),
        "main_cache_5m_tokens": metric_leaf(tokens.main.cache_5m, LABEL_SECONDARY, False),
        "main_cache_1h_tokens": metric_leaf(tokens.main.cache_1h, LABEL_SECONDARY, False),
        "delegated_input_tokens": metric_leaf(tokens.delegated.input, LABEL_SECONDARY, False),
        "delegated_output_tokens": metric_leaf(tokens.delegated.output, LABEL_SECONDARY, False),
        "delegated_cache_read_tokens": metric_leaf(
            tokens.delegated.cache_read, LABEL_SECONDARY, False
        ),
        "delegated_cache_5m_tokens": metric_leaf(tokens.delegated.cache_5m, LABEL_SECONDARY, False),
        "delegated_cache_1h_tokens": metric_leaf(tokens.delegated.cache_1h, LABEL_SECONDARY, False),
        "total_input_tokens": metric_leaf(tokens.total.input, LABEL_SECONDARY, False),
        "total_output_tokens": metric_leaf(tokens.total.output, LABEL_SECONDARY, False),
        "total_cache_read_tokens": metric_leaf(tokens.total.cache_read, LABEL_SECONDARY, False),
        "total_cache_5m_tokens": metric_leaf(tokens.total.cache_5m, LABEL_SECONDARY, False),
        "total_cache_1h_tokens": metric_leaf(tokens.total.cache_1h, LABEL_SECONDARY, False),
        "total_prompt_tokens": metric_leaf(tokens.total_prompt_tokens, LABEL_SECONDARY, False),
    }
    if cost is not None and cost.cost_usd is not None:
        block["cost_usd"] = metric_leaf(round(cost.cost_usd, 4), LABEL_PRIMARY, True)
    else:
        lower = cost.cost_usd_lower_bound if cost is not None else None
        upper = cost.cost_usd_upper_bound if cost is not None else None
        block["cost_usd_lower_bound"] = metric_leaf(round(lower or 0.0, 4), LABEL_PRIMARY, True)
        block["cost_usd_upper_bound"] = metric_leaf(round(upper or 0.0, 4), LABEL_PRIMARY, True)
    block["request_count"] = metric_leaf(requests.request_count, LABEL_SECONDARY, False)
    block["delegated_request_count"] = metric_leaf(
        requests.delegated_request_count, LABEL_SECONDARY, False
    )
    return block


def requests_block(counts: RequestCounts) -> dict[str, Any]:
    """Render a process-dimension request-count block with leaf triples.

    ``request_count`` is the ``Primary`` measurement: it counts model API
    calls in scope and is the natural denominator for per-request process
    rates. ``delegated_request_count`` and ``requests_with_tool_use_count``
    are ``Secondary`` decompositions of the same population: the first picks
    out dispatches the main agent routed through a subagent; the second
    picks out requests whose response carried any tool-use action.
    """
    return {
        "request_count": metric_leaf(counts.request_count, LABEL_PRIMARY, False),
        "delegated_request_count": metric_leaf(
            counts.delegated_request_count, LABEL_SECONDARY, False
        ),
        "requests_with_tool_use_count": metric_leaf(
            counts.requests_with_tool_use_count, LABEL_SECONDARY, False
        ),
    }


def time_block(metrics: TimeMetrics, turn_count: int, scope_kind: str) -> dict[str, Any]:
    """Render a session-or-phase time block with leaf triples.

    The ``duration`` leaf carries the ``constructed`` flag at phase scope
    because the phase boundary is itself derived from the per-prompt phase
    labels rather than read directly from a JSONL field; at session scope
    ``duration`` is the wall-clock extent between the earliest and latest
    non-synthetic record and the flag is ``False``. ``turn_count`` is data and
    is supplied by the caller from ``data/aggregate/counts``.
    """
    duration_constructed = scope_kind == "phase"
    return {
        "duration": metric_leaf(metrics.duration, LABEL_SECONDARY, duration_constructed),
        "turn_time": metric_leaf(metrics.turn_time, LABEL_SECONDARY, True),
        "turn_time_solo": metric_leaf(metrics.turn_time_solo, LABEL_SECONDARY, True),
        "turn_time_concurrent": metric_leaf(metrics.turn_time_concurrent, LABEL_SECONDARY, True),
        "inter_turn_time": metric_leaf(metrics.inter_turn_time, LABEL_PRIMARY, True),
        "turn_count": metric_leaf(turn_count, LABEL_PRIMARY, True),
        "mean_turn_duration": metric_leaf(metrics.mean_turn_duration, LABEL_PRIMARY, True),
        "turn_duration_p50": metric_leaf(metrics.turn_duration_p50, LABEL_SECONDARY, True),
        "turn_duration_p95": metric_leaf(metrics.turn_duration_p95, LABEL_SECONDARY, True),
        "turn_duration_stdev": metric_leaf(metrics.turn_duration_stdev, LABEL_SECONDARY, True),
    }


def time_block_role(metrics: TimeMetrics, turn_count: int) -> dict[str, Any]:
    """Render a role-scope time block with its six measurement fields.

    A role's ``turn_time`` is the sum of per-turn durations rather than
    the union of intervals. Within a single conversation file the two
    coincide, because the participant cannot drive two overlapping prompts
    in one chat; the deliberate use of the sum form surfaces if a future
    role rollup ever folds in turns from multiple files. ``turn_count`` is
    data and is supplied by the caller.
    """
    sum_of_turn_durations = metrics.mean_turn_duration * turn_count
    return {
        "turn_count": metric_leaf(turn_count, LABEL_SECONDARY, True),
        "turn_time": metric_leaf(sum_of_turn_durations, LABEL_SECONDARY, True),
        "mean_turn_duration": metric_leaf(metrics.mean_turn_duration, LABEL_SECONDARY, True),
        "turn_duration_p50": metric_leaf(metrics.turn_duration_p50, LABEL_SECONDARY, True),
        "turn_duration_p95": metric_leaf(metrics.turn_duration_p95, LABEL_SECONDARY, True),
        "turn_duration_stdev": metric_leaf(metrics.turn_duration_stdev, LABEL_SECONDARY, True),
    }


def user_input_block(counts: UserInputCounts, shares: UserInputShares) -> dict[str, Any]:
    """Render a user-input block with leaf triples.

    The four counts are data and come from ``data/aggregate/counts``; the
    bucket shares and magnitudes are metrics folded over the per-input
    series.
    """
    return {
        "turn_prompt_count": metric_leaf(counts.turn_prompt_count, LABEL_PRIMARY, True),
        "steer_delivered_count": metric_leaf(counts.steer_delivered_count, LABEL_PRIMARY, True),
        "steer_abandoned_count": metric_leaf(counts.steer_abandoned_count, LABEL_SECONDARY, True),
        "steer_attempted_count": metric_leaf(counts.steer_attempted_count, LABEL_PRIMARY, True),
        "turn_prompts_bucket_shares": metric_leaf(
            shares.turn_prompts_bucket_shares, LABEL_SECONDARY, True
        ),
        "steer_delivered_bucket_shares": metric_leaf(
            shares.steer_delivered_bucket_shares, LABEL_SECONDARY, True
        ),
        "all_inputs_bucket_shares": metric_leaf(
            shares.all_inputs_bucket_shares, LABEL_PRIMARY, True
        ),
        "turn_prompts_magnitude_by_bucket": metric_leaf(
            shares.turn_prompts_magnitude_by_bucket, LABEL_SECONDARY, True
        ),
        "steer_delivered_magnitude_by_bucket": metric_leaf(
            shares.steer_delivered_magnitude_by_bucket, LABEL_SECONDARY, True
        ),
    }


def supplementary_block(
    counts: SubagentCounts,
    tool_success_rate: float,
) -> dict[str, Any]:
    """Render a supplementary block with leaf triples.

    ``tool_success_rate`` lives here alongside the other ``Supplementary``
    measurements. Its supporting counts ``tool_result_count`` and
    ``tool_error_count`` stay in the diagnostics block so iteration over
    measurement metrics does not pick them up as hypothesis-test
    candidates.
    """
    return {
        "tool_success_rate": metric_leaf(tool_success_rate, LABEL_SUPPLEMENTARY, False),
        "subagent_count": metric_leaf(counts.subagent_count, LABEL_SUPPLEMENTARY, False),
        "subagent_tool_count": metric_leaf(counts.subagent_tool_count, LABEL_SUPPLEMENTARY, False),
        "model_invoked_skill_count": metric_leaf(
            counts.model_invoked_skill_count, LABEL_SUPPLEMENTARY, False
        ),
    }
