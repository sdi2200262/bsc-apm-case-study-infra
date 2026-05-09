#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Leaf-block rendering for the canonical metrics artifact.

Every measurement in the artifact is wrapped in a ``{value, anchor,
constructed}`` triple so the analysis layer can iterate over Primary
metrics to assemble its hypothesis-test family and flag every
Constructed metric for the literature-grounding cross-check without
consulting an external index.

Anchor takes one of three values:

* ``Primary``: drives a research-question claim and is
  hypothesis-tested.
* ``Secondary``: supports or decomposes a Primary within the same
  dimension.
* ``Supplementary``: descriptive only, no hypothesis test.

Constructed is a Boolean. ``true`` means the metric was defined for
this study and rests on face validity until the literature-grounding
pass attaches a published construct; ``false`` means the metric maps
directly onto a JSONL, API, or grader field with aggregation as the
only study-author degree of freedom.

This module owns the per-dimension renderers that translate the
metric dataclasses produced under ``metrics/`` into leaf-triple
dicts. Anchor and constructed flags are hard-coded against the
metric definitions; changing one means editing one renderer here,
not threading constants through the metric computation modules.
"""

from __future__ import annotations

from typing import Any

from .metrics.economic import EconomicSession
from .metrics.reliability import ReliabilityMetrics
from .metrics.supplementary import SupplementaryMetrics
from .metrics.time import TimeMetrics
from .metrics.user_input import UserInputMetrics

ANCHOR_PRIMARY = "Primary"
ANCHOR_SECONDARY = "Secondary"
ANCHOR_SUPPLEMENTARY = "Supplementary"


def metric_leaf(value: Any, anchor: str, constructed: bool) -> dict[str, Any]:
    """Wrap a measurement value in the canonical leaf triple."""
    return {"value": value, "anchor": anchor, "constructed": constructed}


def economic_block(economic: EconomicSession | None) -> dict[str, Any]:
    """Render an economic block with leaf triples.

    The empty-scope branch emits zero-valued leaves so the artifact's
    shape is uniform across sessions; analysis consumers should
    filter empty scopes by ``turn_count == 0`` rather than by
    missing keys.

    The cost shape is conditional. A scope whose every delegated
    dispatch was priced deterministically emits a single
    ``cost_usd`` leaf. A scope with at least one bracketed dispatch
    instead emits ``cost_usd_lower_bound`` and ``cost_usd_upper_bound``
    leaves and omits ``cost_usd`` entirely; consumers that read cost
    must check for both shapes.
    """
    if economic is None:
        zero_token = metric_leaf(0, ANCHOR_SECONDARY, False)
        zero_cost = metric_leaf(0.0, ANCHOR_PRIMARY, True)
        token_keys = (
            f"{population}_{cat}_tokens"
            for population in ("main", "delegated", "total")
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        )
        return {key: zero_token for key in token_keys} | {
            "total_prompt_tokens": zero_token,
            "cost_usd": zero_cost,
        }
    block: dict[str, Any] = {
        "main_input_tokens":            metric_leaf(economic.main.input,            ANCHOR_SECONDARY, False),
        "main_output_tokens":           metric_leaf(economic.main.output,           ANCHOR_SECONDARY, False),
        "main_cache_read_tokens":       metric_leaf(economic.main.cache_read,       ANCHOR_SECONDARY, False),
        "main_cache_5m_tokens":         metric_leaf(economic.main.cache_5m,         ANCHOR_SECONDARY, False),
        "main_cache_1h_tokens":         metric_leaf(economic.main.cache_1h,         ANCHOR_SECONDARY, False),
        "delegated_input_tokens":       metric_leaf(economic.delegated.input,       ANCHOR_SECONDARY, False),
        "delegated_output_tokens":      metric_leaf(economic.delegated.output,      ANCHOR_SECONDARY, False),
        "delegated_cache_read_tokens":  metric_leaf(economic.delegated.cache_read,  ANCHOR_SECONDARY, False),
        "delegated_cache_5m_tokens":    metric_leaf(economic.delegated.cache_5m,    ANCHOR_SECONDARY, False),
        "delegated_cache_1h_tokens":    metric_leaf(economic.delegated.cache_1h,    ANCHOR_SECONDARY, False),
        "total_input_tokens":           metric_leaf(economic.total.input,           ANCHOR_SECONDARY, False),
        "total_output_tokens":          metric_leaf(economic.total.output,          ANCHOR_SECONDARY, False),
        "total_cache_read_tokens":      metric_leaf(economic.total.cache_read,      ANCHOR_SECONDARY, False),
        "total_cache_5m_tokens":        metric_leaf(economic.total.cache_5m,        ANCHOR_SECONDARY, False),
        "total_cache_1h_tokens":        metric_leaf(economic.total.cache_1h,        ANCHOR_SECONDARY, False),
        "total_prompt_tokens":          metric_leaf(economic.total_prompt_tokens,   ANCHOR_SECONDARY, False),
    }
    if economic.cost_usd is not None:
        block["cost_usd"] = metric_leaf(round(economic.cost_usd, 4), ANCHOR_PRIMARY, True)
    else:
        block["cost_usd_lower_bound"] = metric_leaf(
            round(economic.cost_usd_lower_bound or 0.0, 4), ANCHOR_PRIMARY, True
        )
        block["cost_usd_upper_bound"] = metric_leaf(
            round(economic.cost_usd_upper_bound or 0.0, 4), ANCHOR_PRIMARY, True
        )
    return block


def time_block(metrics: TimeMetrics, scope_kind: str) -> dict[str, Any]:
    """Render a session-or-phase time block with leaf triples.

    The ``duration`` leaf carries the constructed flag at phase
    scope because the phase boundary is itself derived from the
    per-prompt phase labels rather than read directly from a JSONL
    field; at session scope ``duration`` is the wall-clock extent
    between the earliest and latest non-synthetic record and the
    flag is false.
    """
    duration_constructed = scope_kind == "phase"
    return {
        "duration":             metric_leaf(metrics.duration,             ANCHOR_SECONDARY, duration_constructed),
        "turn_time":            metric_leaf(metrics.turn_time,            ANCHOR_SECONDARY, True),
        "turn_time_solo":       metric_leaf(metrics.turn_time_solo,       ANCHOR_SECONDARY, True),
        "turn_time_concurrent": metric_leaf(metrics.turn_time_concurrent, ANCHOR_SECONDARY, True),
        "inter_turn_time":      metric_leaf(metrics.inter_turn_time,      ANCHOR_PRIMARY,   True),
        "turn_count":           metric_leaf(metrics.turn_count,           ANCHOR_PRIMARY,   True),
        "mean_turn_duration":   metric_leaf(metrics.mean_turn_duration,   ANCHOR_PRIMARY,   True),
        "turn_duration_p50":    metric_leaf(metrics.turn_duration_p50,    ANCHOR_SECONDARY, True),
        "turn_duration_p95":    metric_leaf(metrics.turn_duration_p95,    ANCHOR_SECONDARY, True),
        "turn_duration_stdev":  metric_leaf(metrics.turn_duration_stdev,  ANCHOR_SECONDARY, True),
    }


def time_block_role(metrics: TimeMetrics) -> dict[str, Any]:
    """Render a role-scope time block with its six measurement fields.

    A role's ``turn_time`` is the sum of per-turn durations rather
    than the union of intervals. Within a single conversation file
    the two coincide, because the participant cannot drive two
    overlapping prompts in one chat; the deliberate use of the
    sum form surfaces if a future role rollup ever folds in turns
    from multiple files.
    """
    sum_of_turn_durations = metrics.mean_turn_duration * metrics.turn_count
    return {
        "turn_count":          metric_leaf(metrics.turn_count,          ANCHOR_SECONDARY, True),
        "turn_time":           metric_leaf(sum_of_turn_durations,       ANCHOR_SECONDARY, True),
        "mean_turn_duration":  metric_leaf(metrics.mean_turn_duration,  ANCHOR_SECONDARY, True),
        "turn_duration_p50":   metric_leaf(metrics.turn_duration_p50,   ANCHOR_SECONDARY, True),
        "turn_duration_p95":   metric_leaf(metrics.turn_duration_p95,   ANCHOR_SECONDARY, True),
        "turn_duration_stdev": metric_leaf(metrics.turn_duration_stdev, ANCHOR_SECONDARY, True),
    }


def user_input_block(metrics: UserInputMetrics) -> dict[str, Any]:
    """Render a user-input block with leaf triples."""
    return {
        "turn_prompt_count":      metric_leaf(metrics.turn_prompt_count,      ANCHOR_PRIMARY,   True),
        "steer_delivered_count":  metric_leaf(metrics.steer_delivered_count,  ANCHOR_PRIMARY,   True),
        "steer_abandoned_count":  metric_leaf(metrics.steer_abandoned_count,  ANCHOR_SECONDARY, True),
        "steer_attempted_count":  metric_leaf(metrics.steer_attempted_count,  ANCHOR_PRIMARY,   True),
        "turn_prompts_bucket_shares":          metric_leaf(metrics.turn_prompts_bucket_shares,          ANCHOR_SECONDARY, True),
        "steer_delivered_bucket_shares":       metric_leaf(metrics.steer_delivered_bucket_shares,       ANCHOR_SECONDARY, True),
        "all_inputs_bucket_shares":            metric_leaf(metrics.all_inputs_bucket_shares,            ANCHOR_PRIMARY,   True),
        "turn_prompts_magnitude_by_bucket":    metric_leaf(metrics.turn_prompts_magnitude_by_bucket,    ANCHOR_SECONDARY, True),
        "steer_delivered_magnitude_by_bucket": metric_leaf(metrics.steer_delivered_magnitude_by_bucket, ANCHOR_SECONDARY, True),
    }


def reliability_block(metrics: ReliabilityMetrics) -> dict[str, Any]:
    """Render a reliability block with leaf triples.

    Only ``tool_success_rate`` is exposed here as a measurement
    leaf. The supporting ``tool_result_count`` and
    ``tool_error_count`` values move into the diagnostics block so
    iteration over measurement metrics does not pick them up as
    hypothesis-test candidates.
    """
    return {
        "tool_success_rate": metric_leaf(metrics.tool_success_rate, ANCHOR_PRIMARY, False),
    }


def supplementary_block(metrics: SupplementaryMetrics) -> dict[str, Any]:
    """Render a supplementary block with leaf triples."""
    return {
        "subagent_count":        metric_leaf(metrics.subagent_count,        ANCHOR_SUPPLEMENTARY, False),
        "subagent_tool_count":   metric_leaf(metrics.subagent_tool_count,   ANCHOR_SUPPLEMENTARY, False),
        "reasoning_token_share": metric_leaf(round(metrics.reasoning_token_share, 6), ANCHOR_SUPPLEMENTARY, True),
    }
