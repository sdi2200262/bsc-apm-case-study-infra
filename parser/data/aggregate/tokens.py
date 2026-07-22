# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-scope token sums, the model-token distribution, and dispatch provenance.

This module folds the main-call and dispatch series from ``call_records``
into the data the economic dimension exposes apart from cost: the
per-category token totals for the main and delegated populations and
their sum, the modal main-call model (a diagnostic), the per-model billed
token distribution, the Agent dispatch totals, and the dispatch-resolution
provenance counters. Cost is not computed here; it is a study formula that
folds the rate table over the same series and lives in ``metrics/cost``.

Two disjoint populations are summed. Main usage is the per-``requestId``
deduplicated usage of a conversation's main agent: every record of one
streaming response carries an identical ``message.usage``, so summing per
record would multiply each call's tokens by its content-block count.
Delegated usage is each Agent dispatch's true token bag: the subagent's
own deduplicated usage summed from its nested transcript (via
``subagent_usage``) when that transcript shipped, falling back to the
rolled-up ``toolUseResult.usage`` otherwise. The roll-up under-represents
the bag (notably ``cache_5m = 0``, since subagents write the five-minute
cache while the main conversation writes the one-hour cache), so pricing
from the subagent transcript recovers the five-minute cache-creation
tokens the roll-up drops. Dispatches whose result lacked populated usage
contribute zero and are surfaced in the dispatch counts so the
complete-to-incomplete ratio is visible.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from ...rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
)
from ..schema import (
    AGENT_TOOL_NAME,
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    SYNTHETIC_MODEL_MARKER,
    Record,
    iter_agent_dispatch_blocks,
)
from ..session import Session
from ..subagent_usage import SubagentDispatchIndex
from ..token_usage import token_sums_dict_from_usage
from .call_records import (
    iter_main_request_records,
    iter_resolved_dispatches,
    iter_resolved_main_calls,
)


@dataclass(frozen=True)
class TokenSums:
    """Per-category token totals across one population.

    Attributes:
        input: Non-cached input tokens.
        output: Output tokens.
        cache_read: Cache-read input tokens.
        cache_5m: Tokens written to the 5-minute ephemeral cache.
        cache_1h: Tokens written to the 1-hour ephemeral cache.
    """

    input: int
    output: int
    cache_read: int
    cache_5m: int
    cache_1h: int

    @classmethod
    def zero(cls) -> TokenSums:
        """Return a ``TokenSums`` with all categories at zero."""
        return cls(input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0)

    def add(self, other: TokenSums) -> TokenSums:
        """Return the per-category sum of this and another ``TokenSums``."""
        return TokenSums(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_5m=self.cache_5m + other.cache_5m,
            cache_1h=self.cache_1h + other.cache_1h,
        )

    def as_dict(self) -> dict[str, int]:
        """Return a plain dict keyed by the category constants in ``rates.CATEGORIES``."""
        return {
            CATEGORY_INPUT: self.input,
            CATEGORY_OUTPUT: self.output,
            CATEGORY_CACHE_READ: self.cache_read,
            CATEGORY_CACHE_5M: self.cache_5m,
            CATEGORY_CACHE_1H: self.cache_1h,
        }


@dataclass(frozen=True)
class TokenData:
    """Per-scope token data: the economic dimension's data values apart from cost.

    Attributes:
        main: Main-call deduplicated token totals.
        delegated: Subagent-dispatch true token totals (the subagent's
            own summed usage where its transcript shipped, else the
            parent roll-up).
        total: Per-category sum of ``main`` and ``delegated``.
        total_prompt_tokens: ``input + cache_read + cache_5m + cache_1h``
            of ``total`` (the full input volume; output is disjoint).
        model: Modal non-synthetic ``message.model`` across main records
            (diagnostic; not the pricing input).
        agent_dispatches_total: Number of Agent tool_use blocks.
        agent_dispatches_with_usage: Subset whose ``toolUseResult.usage``
            was populated.
        model_token_distribution: ``model -> billed tokens`` summed over
            the five categories. For bracketed dispatches the
            point-estimate model is recorded.
        dispatches_resolved_without_index: Dispatches whose ``agentId``
            was not in the subagent dispatch index and which were resolved
            via the fallback resolver.
        dispatches_bracketed: Subset of the above that hit the bracket
            path.
    """

    main: TokenSums
    delegated: TokenSums
    total: TokenSums
    total_prompt_tokens: int
    model: str
    agent_dispatches_total: int
    agent_dispatches_with_usage: int
    model_token_distribution: dict[str, int]
    dispatches_resolved_without_index: int
    dispatches_bracketed: int


def compute_session_token_data(session: Session) -> TokenData:
    """Compute the session-scope token data.

    Args:
        session: An assembled session.

    Returns:
        A populated ``TokenData`` over every record across every
        conversation, with model and usage resolution against the
        session's merged subagent dispatch index.
    """
    all_records = [record for view in session.views for record in view.conversation.records]
    return compute_token_data_for_records(all_records, merge_subagent_indices(session))


def compute_token_data_for_records(
    records: list[Record],
    subagent_index: SubagentDispatchIndex,
) -> TokenData:
    """Compute token data over an arbitrary record subset.

    Deduplication by ``requestId`` is applied locally to the subset so
    each distinct API call contributes its usage exactly once even when
    the subset spans multiple turns of the same conversation.

    Args:
        records: The records to aggregate over.
        subagent_index: Merged ``agentId``-keyed subagent model-and-usage
            index for the session, used to resolve which model billed
            each dispatch and to price its true token usage in place of
            the parent roll-up.

    Returns:
        A populated ``TokenData``.
    """
    main_total = _sum_main_from_records(records)
    delegated_total, dispatches_total, dispatches_with_usage = _sum_delegated_from_records(
        records, subagent_index
    )
    total = main_total.add(delegated_total)
    total_prompt = total.input + total.cache_read + total.cache_5m + total.cache_1h
    distribution: dict[str, int] = {}
    for call in iter_resolved_main_calls(records):
        distribution[call.canonical_model] = distribution.get(call.canonical_model, 0) + sum(
            call.token_bag.values()
        )
    dispatches_resolved = 0
    dispatches_bracketed = 0
    for dispatch in iter_resolved_dispatches(records, subagent_index):
        distribution[dispatch.point_model] = distribution.get(dispatch.point_model, 0) + sum(
            dispatch.token_bag.values()
        )
        if dispatch.resolved_without_index:
            dispatches_resolved += 1
        if dispatch.bracket is not None:
            dispatches_bracketed += 1
    return TokenData(
        main=main_total,
        delegated=delegated_total,
        total=total,
        total_prompt_tokens=total_prompt,
        model=_modal_main_model_from_records(records),
        agent_dispatches_total=dispatches_total,
        agent_dispatches_with_usage=dispatches_with_usage,
        model_token_distribution=distribution,
        dispatches_resolved_without_index=dispatches_resolved,
        dispatches_bracketed=dispatches_bracketed,
    )


def merge_subagent_indices(session: Session) -> SubagentDispatchIndex:
    """Merge per-conversation subagent dispatch indices into one session-scope index.

    ``agentId`` values are globally unique across Claude Code, so a flat
    ``dict.update`` per conversation produces session-scope model and
    usage maps without collisions. When two conversations happen to
    re-use an id (which Claude Code is not expected to do), the later
    conversation's value wins; this is acceptable as a fall-through and
    is not surfaced separately. The per-conversation diagnostic counts
    (``files_seen``, ``files_without_model``) are summed; ``report``
    reads those off the individual conversations, so the merged counts
    serve only callers of the merged index.
    """
    model_by_agent_id: dict[str, str] = {}
    usage_by_agent_id: dict[str, dict[str, int]] = {}
    requests_by_agent_id: dict[str, int] = {}
    files_seen = 0
    files_without_model = 0
    for view in session.views:
        index = view.conversation.subagent_dispatch_index
        model_by_agent_id.update(index.model_by_agent_id)
        usage_by_agent_id.update(index.usage_by_agent_id)
        requests_by_agent_id.update(index.requests_by_agent_id)
        files_seen += index.files_seen
        files_without_model += index.files_without_model
    return SubagentDispatchIndex(
        model_by_agent_id=model_by_agent_id,
        usage_by_agent_id=usage_by_agent_id,
        requests_by_agent_id=requests_by_agent_id,
        files_seen=files_seen,
        files_without_model=files_without_model,
    )


def _modal_main_model_from_records(records: list[Record]) -> str:
    """Return the modal non-synthetic ``message.model`` across a record subset.

    Returns the empty string when the subset contains no qualifying main
    assistant record, which can happen for a phase or role scope that
    holds only delegated activity.
    """
    counts: Counter[str] = Counter()
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if not isinstance(model, str) or not model or model == SYNTHETIC_MODEL_MARKER:
            continue
        counts[model] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def _sum_main_from_records(records: list[Record]) -> TokenSums:
    """Sum main-call tokens across a record subset, deduplicated by requestId.

    Walks ``records`` with ``call_records.iter_main_request_records``
    so the main-call selection rule and the per-scope dedup are shared
    across every consumer of that population.
    """
    total = TokenSums.zero()
    for record in iter_main_request_records(records):
        message = record.payload["message"]
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        total = total.add(_token_sums_from_usage(usage))
    return total


def _sum_delegated_from_records(
    records: list[Record],
    subagent_index: SubagentDispatchIndex,
) -> tuple[TokenSums, int, int]:
    """Sum subagent-dispatch tokens across a record subset and report dispatch counts.

    Returns ``(delegated_sums, dispatches_total, dispatches_with_usage)``
    where ``dispatches_total`` counts every ``Agent`` tool_use block in
    the assistant records of the subset and ``dispatches_with_usage``
    counts how many of those dispatches had populated
    ``toolUseResult.usage`` on a matching user record in the same subset.

    For a dispatch whose ``agentId`` is in ``subagent_index``, the
    subagent's own true token bag is summed in place of the parent
    ``toolUseResult.usage`` roll-up, which under-represents it (notably
    ``cache_5m = 0``; see ``subagent_usage``). The roll-up is summed only
    when no subagent file shipped for the ``agentId``. The bag is summed
    once per dispatch, so the two sources are never double-counted.
    """
    agent_tool_use_ids = _agent_tool_use_id_index(records)
    dispatches_total = len(agent_tool_use_ids)
    delegated = TokenSums.zero()
    dispatches_with_usage = 0
    for record in records:
        if record.record_type != RECORD_TYPE_USER:
            continue
        tool_use_result = record.payload.get("toolUseResult")
        if not isinstance(tool_use_result, dict):
            continue
        usage = tool_use_result.get("usage")
        if not isinstance(usage, dict):
            continue
        if not _matches_agent_dispatch(record, agent_tool_use_ids):
            continue
        agent_id = tool_use_result.get("agentId")
        indexed = (
            subagent_index.usage_by_agent_id.get(agent_id) if isinstance(agent_id, str) else None
        )
        if indexed is not None:
            delegated = delegated.add(_token_sums_from_dict(indexed))
        else:
            delegated = delegated.add(_token_sums_from_usage(usage))
        dispatches_with_usage += 1
    return delegated, dispatches_total, dispatches_with_usage


def _agent_tool_use_id_index(records: list[Record]) -> dict[str, str]:
    """Return a map from Agent ``tool_use`` block id to the tool name across a record subset."""
    index: dict[str, str] = {}
    for _record, block in iter_agent_dispatch_blocks(records):
        tool_use_id = block.get("id")
        if isinstance(tool_use_id, str):
            index[tool_use_id] = AGENT_TOOL_NAME
    return index


def _matches_agent_dispatch(
    user_record: Record,
    agent_tool_use_ids: dict[str, str],
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
        if isinstance(tool_use_id, str) and tool_use_id in agent_tool_use_ids:
            return True
    return False


def _token_sums_from_usage(usage: dict[str, Any]) -> TokenSums:
    """Extract the five-category ``TokenSums`` from one ``message.usage`` block.

    Repackages the category-keyed dict from
    ``token_usage.token_sums_dict_from_usage`` into the typed
    ``TokenSums`` dataclass.

    Args:
        usage: One ``message.usage`` block.

    Returns:
        A ``TokenSums`` carrying the five per-category totals.
    """
    return _token_sums_from_dict(token_sums_dict_from_usage(usage))


def _token_sums_from_dict(sums: dict[str, int]) -> TokenSums:
    """Pack a ``rates.CATEGORY_*``-keyed token bag into a ``TokenSums``.

    Used for the subagent index's pre-summed bags, which are already in
    the five-category dict shape.
    """
    return TokenSums(
        input=sums[CATEGORY_INPUT],
        output=sums[CATEGORY_OUTPUT],
        cache_read=sums[CATEGORY_CACHE_READ],
        cache_5m=sums[CATEGORY_CACHE_5M],
        cache_1h=sums[CATEGORY_CACHE_1H],
    )
