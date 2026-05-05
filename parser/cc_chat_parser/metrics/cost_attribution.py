#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Per-call cost attribution against the rate table.

The economic dimension exposes a single ``cost_usd`` figure and a
per-population token breakdown. Token sums are model-agnostic. Cost is
not: the case-study sessions mix Opus main work with Sonnet helper
agents and Haiku ``Explore`` dispatches, and pricing every token at the
session's modal model would over-bill the cheaper-model dispatches by
multiples. This module walks each record subset call-by-call, resolves
the model that actually billed each call, and sums per-call cost
against that model's row in the rate table.

Two populations are priced separately:

* **Main calls.** Each non-synthetic, non-errored assistant record
  contributes its ``message.usage`` once per ``requestId``; the
  record's own ``message.model`` drives the lookup. The ``requestId``
  dedup matches the loader's contract: Claude Code emits one record
  per content block of a streaming response and every such record
  carries an identical ``usage`` object, so summing per record would
  multiply each call's tokens by the block count.

* **Delegated dispatches.** Each ``Agent`` tool dispatch's rolled-up
  ``toolUseResult.usage`` is priced against the subagent's actual
  model, looked up by ``agentId`` in the conversation's
  ``SubagentModelIndex``. The submission contract requires the
  sibling ``<sessionId>/subagents/agent-<agentId>.jsonl`` to ship
  with every main session JSONL; an unindexed ``agentId`` therefore
  surfaces as a loud ``KeyError`` rather than silently falling back
  to a parent-derived approximation, so a contract violation is
  caught at parse time instead of attributed against the wrong
  model.

A ``model_token_distribution`` map is exposed on ``CostAttribution``
so a reader can see how token volume splits across models without
re-walking the records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rates import (
    RateTable,
    canonical_model_id,
    cost_in_usd,
)
from ..schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    CONTENT_BLOCK_TOOL_USE,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    Record,
    SYNTHETIC_MODEL_MARKER,
)

AGENT_TOOL_NAME = "Agent"


@dataclass(frozen=True)
class CostAttribution:
    """Per-call cost figures plus the per-model token volume.

    Attributes:
        main_cost_usd: Sum across all main calls in the record subset
            of (call's deduplicated usage) priced at (call's own
            ``message.model``).
        delegated_cost_usd: Sum across all ``Agent`` dispatches in the
            record subset of (dispatch's rolled-up
            ``toolUseResult.usage``) priced at the subagent's model
            from the conversation's ``SubagentModelIndex``.
        total_cost_usd: ``main_cost_usd + delegated_cost_usd``.
        model_token_distribution: ``model -> total billed tokens``
            (sum across the five categories) for every model that
            contributed cost in either population.
    """

    main_cost_usd: float
    delegated_cost_usd: float
    total_cost_usd: float
    model_token_distribution: dict[str, int] = field(default_factory=dict)


def attribute_cost_for_records(
    records: list[Record],
    rate_table: RateTable,
    subagent_models_by_agent_id: dict[str, str],
) -> CostAttribution:
    """Walk a record subset call-by-call and price each call against the resolved model.

    Args:
        records: The records to price. Typically every record across
            every conversation in the session for session scope, or
            the records belonging to a phase or role for narrower
            scopes.
        rate_table: The rate table to compute cost against.
        subagent_models_by_agent_id: ``agentId``-keyed map from the
            session's merged ``SubagentModelIndex`` data. The
            submission contract requires this to be populated for
            every dispatch's ``agentId``; an unindexed ``agentId``
            raises ``KeyError`` rather than falling back to an
            approximation.

    Returns:
        A populated ``CostAttribution`` with both costs and the
        per-model token distribution.

    Raises:
        KeyError: When an ``Agent`` dispatch's ``agentId`` is not
            present in ``subagent_models_by_agent_id``. Surfaces a
            submission-contract violation (the sibling subagent
            file was not shipped) at parse time.
        rates.RateTableError: When a resolved model is not present
            in ``rate_table.models``.
    """
    main_cost, main_dist = _cost_main_per_call(records, rate_table)
    delegated_cost, delegated_dist = _cost_delegated_per_call(
        records, rate_table, subagent_models_by_agent_id
    )
    distribution: dict[str, int] = dict(main_dist)
    for model_id, tokens in delegated_dist.items():
        distribution[model_id] = distribution.get(model_id, 0) + tokens
    return CostAttribution(
        main_cost_usd=main_cost,
        delegated_cost_usd=delegated_cost,
        total_cost_usd=main_cost + delegated_cost,
        model_token_distribution=distribution,
    )


def _cost_main_per_call(
    records: list[Record],
    rate_table: RateTable,
) -> tuple[float, dict[str, int]]:
    """Sum main-call cost over a record subset, deduplicated by ``requestId``.

    The selection rule mirrors ``loader._build_usage_index``: skip
    non-assistant records, skip synthetic assistants, skip records
    whose ``isApiErrorMessage`` is ``True``, take the first record
    seen for each ``requestId``. Each kept record's
    ``message.usage`` is priced at the canonicalised
    ``message.model``.
    """
    cost = 0.0
    distribution: dict[str, int] = {}
    seen: set[str] = set()
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        if record.payload.get("isApiErrorMessage") is True:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if not isinstance(model, str) or model == SYNTHETIC_MODEL_MARKER:
            continue
        request_id = record.payload.get("requestId")
        if not isinstance(request_id, str) or request_id in seen:
            continue
        seen.add(request_id)
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        sums = _token_sums_dict_from_usage(usage)
        canonical = canonical_model_id(model)
        cost += cost_in_usd(rate_table, canonical, sums)
        distribution[canonical] = distribution.get(canonical, 0) + sum(sums.values())
    return cost, distribution


def _cost_delegated_per_call(
    records: list[Record],
    rate_table: RateTable,
    subagent_models_by_agent_id: dict[str, str],
) -> tuple[float, dict[str, int]]:
    """Sum delegated-dispatch cost, looking up each dispatch's subagent model.

    Returns ``(cost_usd, model_token_distribution)``. Each dispatch's
    ``agentId`` (read from ``toolUseResult.agentId``) must be present
    in ``subagent_models_by_agent_id``; an unindexed id raises
    ``KeyError`` so a missing sibling subagent file surfaces as a
    contract violation rather than a silent attribution drift.
    """
    agent_dispatch_tool_use_ids = _agent_dispatch_tool_use_ids(records)
    cost = 0.0
    distribution: dict[str, int] = {}
    for record in records:
        if record.record_type != RECORD_TYPE_USER:
            continue
        tool_use_result = record.payload.get("toolUseResult")
        if not isinstance(tool_use_result, dict):
            continue
        usage = tool_use_result.get("usage")
        if not isinstance(usage, dict):
            continue
        if not _matches_agent_dispatch(record, agent_dispatch_tool_use_ids):
            continue
        agent_id = tool_use_result.get("agentId")
        if not isinstance(agent_id, str):
            raise KeyError(
                "delegated dispatch user record has no string agentId on "
                "toolUseResult; cannot resolve subagent model"
            )
        if agent_id not in subagent_models_by_agent_id:
            raise KeyError(
                f"agentId {agent_id!r} is not in the SubagentModelIndex; "
                f"the submission must include the sibling subagents/ "
                f"directory with agent-{agent_id}.jsonl"
            )
        resolved = subagent_models_by_agent_id[agent_id]
        sums = _token_sums_dict_from_usage(usage)
        cost += cost_in_usd(rate_table, resolved, sums)
        distribution[resolved] = distribution.get(resolved, 0) + sum(sums.values())
    return cost, distribution


def _agent_dispatch_tool_use_ids(records: list[Record]) -> set[str]:
    """Return the set of ``Agent`` ``tool_use`` block ids across a record subset."""
    ids: set[str] = set()
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") == SYNTHETIC_MODEL_MARKER:
            continue
        for block in message.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") != CONTENT_BLOCK_TOOL_USE:
                continue
            if block.get("name") != AGENT_TOOL_NAME:
                continue
            tool_use_id = block.get("id")
            if isinstance(tool_use_id, str):
                ids.add(tool_use_id)
    return ids


def _matches_agent_dispatch(
    user_record: Record,
    agent_dispatch_tool_use_ids: set[str],
) -> bool:
    """Return ``True`` when a user record's tool_result references an Agent dispatch."""
    message = user_record.payload.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != CONTENT_BLOCK_TOOL_RESULT:
            continue
        tool_use_id = block.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id in agent_dispatch_tool_use_ids:
            return True
    return False


def _token_sums_dict_from_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Extract the five-category token bag from a ``message.usage`` block.

    Returns a dict keyed by the ``rates.CATEGORY_*`` constants ready
    to hand to ``cost_in_usd``. Mirrors
    ``economic._token_sums_from_usage`` but skips the intermediate
    ``TokenSums`` dataclass since the caller does not need
    per-category typed access.
    """
    from ..rates import (
        CATEGORY_CACHE_1H,
        CATEGORY_CACHE_5M,
        CATEGORY_CACHE_READ,
        CATEGORY_INPUT,
        CATEGORY_OUTPUT,
    )

    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        cache_5m = _int_or_zero(cache_creation.get("ephemeral_5m_input_tokens"))
        cache_1h = _int_or_zero(cache_creation.get("ephemeral_1h_input_tokens"))
    else:
        cache_5m = 0
        cache_1h = 0
    return {
        CATEGORY_INPUT: _int_or_zero(usage.get("input_tokens")),
        CATEGORY_OUTPUT: _int_or_zero(usage.get("output_tokens")),
        CATEGORY_CACHE_READ: _int_or_zero(usage.get("cache_read_input_tokens")),
        CATEGORY_CACHE_5M: cache_5m,
        CATEGORY_CACHE_1H: cache_1h,
    }


def _int_or_zero(value: Any) -> int:
    """Return ``value`` when it is an int, otherwise ``0``."""
    return value if isinstance(value, int) else 0
