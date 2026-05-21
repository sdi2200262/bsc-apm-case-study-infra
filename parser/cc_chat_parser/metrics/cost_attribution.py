#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Per-call cost attribution against the rate table.

The economic dimension exposes a per-population token breakdown and a
cost figure. Token sums are model-agnostic. Cost is not: the
case-study sessions mix Opus main work with Sonnet helper agents and
Haiku ``Explore`` dispatches, and pricing every token at the session's
modal model would over-bill the cheaper-model dispatches by multiples.
This module walks each record subset call-by-call, resolves the model
that actually billed each call, and sums per-call cost against that
model's row in the rate table.

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
  model. The canonical case-study submission ships a sibling
  ``<sessionId>/subagents/agent-<agentId>.jsonl`` with every main
  session JSONL and the subagent's actual ``message.model`` is read
  from there via ``SubagentModelIndex``. When the sibling files are
  absent, the dispatch is resolved through
  ``subagents.resolve_unindexed_subagent_model``, which returns a
  deterministic model for every subagent type the registry
  recognises and a ``(haiku, opus)`` bracket for any unknown custom
  subagent. A
  bracketed dispatch's tokens contribute to per-bound cost sums
  rather than a single point figure.

The cost output mirrors that branch: when no dispatch in the scope
was bracketed, ``CostAttribution.cost_usd`` is a single number and
the bound fields are ``None``. When at least one dispatch was
bracketed, ``cost_usd`` is ``None`` and the bound fields carry the
range (every non-bracketed dispatch contributes its certain price to
both bounds; bracketed dispatches contribute haiku-to-opus
uncertainty). A ``model_token_distribution`` map is exposed so a
reader can see how token volume splits across models without
re-walking the records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
    canonical_model_id,
    cost_in_usd,
)
from ..schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    Record,
    SYNTHETIC_MODEL_MARKER,
    iter_agent_dispatch_blocks,
)
from ..subagents import resolve_unindexed_subagent_model


@dataclass(frozen=True)
class CostAttribution:
    """Per-call cost figures plus the per-model token volume.

    Cost is reported either as a single ``cost_usd`` figure (when
    every delegated dispatch in the scope was priced
    deterministically) or as a ``cost_usd_lower_bound`` /
    ``cost_usd_upper_bound`` pair (when at least one dispatch was
    bracketed by the unindexed-model resolver). Exactly one of the
    two shapes is populated for any given attribution.

    Attributes:
        main_cost_usd: Sum across all main calls in the record
            subset of (call's deduplicated usage) priced at (call's
            own ``message.model``).
        delegated_cost_usd: Sum across all ``Agent`` dispatches in
            the record subset of (dispatch's rolled-up
            ``toolUseResult.usage``) priced at the dispatch's
            point-estimate model.
        cost_usd: ``main_cost_usd + delegated_cost_usd`` when the
            scope contains no bracketed dispatch; ``None`` when it
            does.
        cost_usd_lower_bound: Lower bound of the cost range when
            the scope contains at least one bracketed dispatch.
            Equal to main cost plus, per dispatch: the certain
            price for non-bracketed dispatches and the
            haiku-priced cost for bracketed ones. ``None`` when
            no dispatch was bracketed.
        cost_usd_upper_bound: Upper bound, defined symmetrically
            with ``cost_usd_lower_bound`` but using the bracket's
            opus rate for bracketed dispatches.
        model_token_distribution: ``model -> total billed tokens``
            (sum across the five categories) for every model that
            contributed cost in either population. For bracketed
            dispatches the point-estimate model is recorded.
        dispatches_resolved_without_index: Count of dispatches whose
            ``agentId`` was not in the index and which were priced
            via ``resolve_unindexed_subagent_model``.
        dispatches_bracketed: Subset of the above that hit the
            bracket path (the resolver could not commit to a single
            model). ``0`` when every resolved dispatch was
            deterministic.
    """

    main_cost_usd: float
    delegated_cost_usd: float
    cost_usd: float | None
    cost_usd_lower_bound: float | None
    cost_usd_upper_bound: float | None
    model_token_distribution: dict[str, int] = field(default_factory=dict)
    dispatches_resolved_without_index: int = 0
    dispatches_bracketed: int = 0


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
            session's merged ``SubagentModelIndex`` data. Dispatches
            whose ``agentId`` is in this map are priced from the
            indexed model. Dispatches whose ``agentId`` is missing
            (the case-study submission shipped without sibling
            subagent files) are priced via
            ``resolve_unindexed_subagent_model``.

    Returns:
        A populated ``CostAttribution`` with the per-model token
        distribution and either a single ``cost_usd`` or a
        ``cost_usd_lower_bound`` / ``cost_usd_upper_bound`` pair,
        depending on whether any dispatch in the scope was
        bracketed.

    Raises:
        RateTableError: When a resolved model is not present
            in ``rate_table.models``.
    """
    main_cost, main_dist = _cost_main_per_call(records, rate_table)
    delegated = _cost_delegated_per_call(records, rate_table, subagent_models_by_agent_id)
    distribution: dict[str, int] = dict(main_dist)
    for model_id, tokens in delegated.distribution.items():
        distribution[model_id] = distribution.get(model_id, 0) + tokens
    if delegated.dispatches_bracketed > 0:
        cost_usd: float | None = None
        lower_bound: float | None = main_cost + delegated.cost_lower_bound
        upper_bound: float | None = main_cost + delegated.cost_upper_bound
    else:
        cost_usd = main_cost + delegated.cost_point
        lower_bound = None
        upper_bound = None
    return CostAttribution(
        main_cost_usd=main_cost,
        delegated_cost_usd=delegated.cost_point,
        cost_usd=cost_usd,
        cost_usd_lower_bound=lower_bound,
        cost_usd_upper_bound=upper_bound,
        model_token_distribution=distribution,
        dispatches_resolved_without_index=delegated.dispatches_resolved_without_index,
        dispatches_bracketed=delegated.dispatches_bracketed,
    )


@dataclass(frozen=True)
class _DispatchContext:
    """Context for one Agent dispatch needed by the unindexed-model resolver.

    Attributes:
        subagent_type: ``input.subagent_type`` on the dispatch's
            tool_use block, or ``None`` when the field was omitted.
        input_model: ``input.model`` on the dispatch's tool_use
            block, or ``None`` when the field was not set.
        parent_main_model: The ``message.model`` of the assistant
            record that emitted the dispatch.
    """

    subagent_type: str | None
    input_model: str | None
    parent_main_model: str


@dataclass(frozen=True)
class _DelegatedSums:
    """Internal per-bound delegated-cost sums and counters.

    Attributes:
        cost_point: Sum of every dispatch's point-estimate cost.
        cost_lower_bound: Sum where each bracketed dispatch is
            priced at the bracket's lower model and each
            deterministic dispatch is priced at its point estimate.
        cost_upper_bound: Symmetric with ``cost_lower_bound`` but
            using the bracket's upper model for bracketed
            dispatches.
        distribution: ``model -> billed tokens`` aggregated over the
            point-estimate model of every dispatch.
        dispatches_resolved_without_index: Count of dispatches
            handled by the unindexed-model resolver.
        dispatches_bracketed: Subset of the above that hit the
            bracket path.
    """

    cost_point: float
    cost_lower_bound: float
    cost_upper_bound: float
    distribution: dict[str, int]
    dispatches_resolved_without_index: int
    dispatches_bracketed: int


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
) -> _DelegatedSums:
    """Sum delegated-dispatch cost and counters, looking up each dispatch's model.

    Each dispatch's ``agentId`` (read from ``toolUseResult.agentId``)
    is first checked against ``subagent_models_by_agent_id``. When
    the id is present, the indexed model is used and the dispatch
    contributes to all three bound sums identically (point, lower,
    upper) at that single rate. When the id is absent (the sibling
    subagent file was not shipped) the dispatch is routed through
    ``resolve_unindexed_subagent_model`` using the dispatch context
    captured from the matching assistant tool_use; a deterministic
    resolution again contributes a single rate, while a bracketed
    resolution contributes three different rates (point, lower,
    upper) so the eventual session-scope bounds frame the cost as
    a range.
    """
    contexts = _build_dispatch_contexts(records)
    cost_point = 0.0
    cost_lower = 0.0
    cost_upper = 0.0
    distribution: dict[str, int] = {}
    dispatches_resolved = 0
    dispatches_bracketed = 0
    for record in records:
        if record.record_type != RECORD_TYPE_USER:
            continue
        tool_use_result = record.payload.get("toolUseResult")
        if not isinstance(tool_use_result, dict):
            continue
        usage = tool_use_result.get("usage")
        if not isinstance(usage, dict):
            continue
        matched_tool_use_id = _matched_dispatch_tool_use_id(record, contexts)
        if matched_tool_use_id is None:
            continue
        agent_id = tool_use_result.get("agentId")
        sums = _token_sums_dict_from_usage(usage)
        if isinstance(agent_id, str) and agent_id in subagent_models_by_agent_id:
            indexed_model = subagent_models_by_agent_id[agent_id]
            point_cost = cost_in_usd(rate_table, indexed_model, sums)
            cost_point += point_cost
            cost_lower += point_cost
            cost_upper += point_cost
            distribution[indexed_model] = (
                distribution.get(indexed_model, 0) + sum(sums.values())
            )
            continue
        context = contexts[matched_tool_use_id]
        resolved = resolve_unindexed_subagent_model(
            subagent_type=context.subagent_type,
            input_model=context.input_model,
            parent_main_model=context.parent_main_model,
        )
        dispatches_resolved += 1
        point_cost = cost_in_usd(rate_table, resolved.canonical_model, sums)
        cost_point += point_cost
        if resolved.bracket is None:
            cost_lower += point_cost
            cost_upper += point_cost
        else:
            dispatches_bracketed += 1
            lower_model, upper_model = resolved.bracket
            cost_lower += cost_in_usd(rate_table, lower_model, sums)
            cost_upper += cost_in_usd(rate_table, upper_model, sums)
        distribution[resolved.canonical_model] = (
            distribution.get(resolved.canonical_model, 0) + sum(sums.values())
        )
    return _DelegatedSums(
        cost_point=cost_point,
        cost_lower_bound=cost_lower,
        cost_upper_bound=cost_upper,
        distribution=distribution,
        dispatches_resolved_without_index=dispatches_resolved,
        dispatches_bracketed=dispatches_bracketed,
    )


def _build_dispatch_contexts(records: list[Record]) -> dict[str, _DispatchContext]:
    """Build a tool_use_id -> dispatch context map from a record subset.

    Walks non-synthetic assistant records, captures every ``Agent``
    tool_use block's ``input.subagent_type`` and ``input.model``
    along with the emitting record's ``message.model`` (the
    parent's main model). The resulting map is the join input the
    unindexed-model resolver consumes when an ``agentId`` is not
    in the ``SubagentModelIndex``.
    """
    contexts: dict[str, _DispatchContext] = {}
    for record, block in iter_agent_dispatch_blocks(records):
        parent_model = record.payload["message"].get("model")
        if not isinstance(parent_model, str):
            continue
        tool_use_id = block.get("id")
        if not isinstance(tool_use_id, str):
            continue
        inputs = block.get("input")
        if not isinstance(inputs, dict):
            inputs = {}
        subagent_type = inputs.get("subagent_type")
        if not isinstance(subagent_type, str):
            subagent_type = None
        input_model = inputs.get("model")
        if not isinstance(input_model, str):
            input_model = None
        contexts[tool_use_id] = _DispatchContext(
            subagent_type=subagent_type,
            input_model=input_model,
            parent_main_model=parent_model,
        )
    return contexts


def _matched_dispatch_tool_use_id(
    user_record: Record,
    contexts: dict[str, _DispatchContext],
) -> str | None:
    """Return the tool_use_id of the Agent dispatch this user record carries.

    The user record carries one ``tool_result`` block per dispatched
    tool call; this helper returns the first ``tool_use_id`` whose
    matching assistant ``tool_use`` block was an ``Agent`` dispatch
    (i.e. is keyed in ``contexts``). Returns ``None`` when the user
    record is not an Agent-dispatch result.
    """
    message = user_record.payload.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != CONTENT_BLOCK_TOOL_RESULT:
            continue
        tool_use_id = block.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id in contexts:
            return tool_use_id
    return None


def _token_sums_dict_from_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Extract the five-category token bag from a ``message.usage`` block.

    This is the shared extraction core for the economic dimension.
    It returns a dict keyed by the ``rates.CATEGORY_*`` constants,
    ready to hand to ``cost_in_usd``. ``economic._token_sums_from_usage``
    adapts this dict into a ``TokenSums`` dataclass for callers that
    need per-category typed access.

    Args:
        usage: One ``message.usage`` block. Missing or non-integer
            fields contribute zero.

    Returns:
        A dict with one entry per ``rates.CATEGORY_*`` constant.
    """
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
