#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""The shared main-call selection rule and the per-call / per-dispatch model series.

Token usage on a Claude Code conversation comes from two disjoint
populations. Main usage is the per-API-call usage of a conversation's
main agent: Claude Code emits one JSONL record per content block of a
streaming response, every record of one call carrying an identical
``message.usage``, so a per-``requestId`` dedup is needed before summing.
Delegated usage is the rolled-up usage of subagent dispatches, reported
back on the parent user record's ``toolUseResult.usage``.

This module owns the one selection rule for the main-call population and
the resolution of which model billed each call and each dispatch. It
produces resolution-only series (model plus token bag, no pricing); the
token-sum fold over them lives in ``tokens`` (data) and the rate fold in
``metrics/cost`` (metric). Holding the selection rule and the model
resolution here keeps a single implementation for every consumer:

- ``is_main_request_record`` / ``iter_main_request_records`` are consumed
  by ``tokens``, ``counts``, and ``turn_series`` (data) and by
  ``metrics/cost`` (metric) for the main-call population.
- ``iter_resolved_main_calls`` yields each main call's canonical model and
  token bag; the token-volume distribution and the cost fold consume it.
- ``iter_resolved_dispatches`` yields each Agent dispatch's resolved model,
  optional rate bracket, and token bag; the same two consumers fold it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from ...rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    canonical_model_id,
)
from ..schema import (
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    SYNTHETIC_MODEL_MARKER,
    Record,
    iter_agent_dispatch_blocks,
)
from ..subagent_models import resolve_unindexed_subagent_model


@dataclass(frozen=True)
class ResolvedMainCall:
    """One priced-population main call: its canonical model and token bag.

    Attributes:
        canonical_model: The canonicalised ``message.model`` of the
            call's first record for its ``requestId``.
        token_bag: The five-category token bag keyed by the
            ``rates.CATEGORY_*`` constants.
    """

    canonical_model: str
    token_bag: dict[str, int]


@dataclass(frozen=True)
class ResolvedDispatch:
    """One Agent dispatch with its resolved model, optional bracket, and token bag.

    Attributes:
        point_model: The point-estimate model the dispatch billed at:
            the indexed model when the dispatch's ``agentId`` was in the
            subagent-model index, else the unindexed resolver's
            canonical model.
        bracket: ``(lower_model, upper_model)`` when the unindexed
            resolver could not commit to a single model, else ``None``.
        token_bag: The five-category token bag keyed by the
            ``rates.CATEGORY_*`` constants.
        resolved_without_index: ``True`` when the dispatch's ``agentId``
            was not in the subagent-model index and the unindexed
            resolver was consulted.
    """

    point_model: str
    bracket: tuple[str, str] | None
    token_bag: dict[str, int]
    resolved_without_index: bool


def is_main_request_record(record: Record) -> bool:
    """Return ``True`` for a record in the main-call selection population.

    The rule is: a non-synthetic, non-API-error assistant record carrying
    a string ``requestId``. ``message.model`` equal to the synthetic
    marker, a missing or non-dict ``message``, an ``isApiErrorMessage``
    flag, or a missing or non-string ``requestId`` each exclude the
    record. This is the single selection rule for the main-call
    population; the per-``requestId`` dedup is applied by
    ``iter_main_request_records``.

    Args:
        record: A conversation record.

    Returns:
        Whether the record belongs to the main-call population.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return False
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return False
    if message.get("model") == SYNTHETIC_MODEL_MARKER:
        return False
    if record.payload.get("isApiErrorMessage") is True:
        return False
    return isinstance(record.payload.get("requestId"), str)


def iter_main_request_records(records: Iterable[Record]) -> Iterator[Record]:
    """Yield the first assistant record observed for each main-call requestId.

    Walks ``records`` in order and yields one record per unique
    ``message.requestId`` among records that satisfy
    ``is_main_request_record``, skipping duplicates for an
    already-yielded requestId. The dedup is local to the ``records``
    iterable; callers wanting a global dedup must pass a single iterable
    covering their scope.

    Args:
        records: Conversation records in document order. Mixed record
            types are tolerated; only main-call records are yielded.

    Yields:
        The first ``Record`` carrying each unique main-call ``requestId``
        encountered in ``records``.
    """
    seen: set[str] = set()
    for record in records:
        if not is_main_request_record(record):
            continue
        request_id = record.payload["requestId"]
        if request_id in seen:
            continue
        seen.add(request_id)
        yield record


def iter_resolved_main_calls(records: Iterable[Record]) -> Iterator[ResolvedMainCall]:
    """Yield the canonical model and token bag of each billed main call.

    Walks ``records`` deduplicating by ``requestId`` and, for the first
    record of each call whose ``message.model`` is a non-synthetic string
    and whose ``message.usage`` is present, yields the call's canonical
    model and token bag. A call whose first record lacks a usable usage
    block contributes no entry, exactly as the per-call pricing walk does
    today; its ``requestId`` is still consumed so a later record for the
    same call does not re-enter the population.

    Args:
        records: Conversation records in document order.

    Yields:
        One ``ResolvedMainCall`` per billed main call, in record
        order.
    """
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
        yield ResolvedMainCall(
            canonical_model=canonical_model_id(model),
            token_bag=token_sums_dict_from_usage(usage),
        )


def iter_resolved_dispatches(
    records: list[Record],
    subagent_models_by_agent_id: dict[str, str],
) -> Iterator[ResolvedDispatch]:
    """Yield the resolved model and token bag of each Agent dispatch.

    For each user record carrying a populated ``toolUseResult.usage`` that
    matches an Agent dispatch in ``records``, resolves the model that
    billed the dispatch. When the dispatch's ``agentId`` is in
    ``subagent_models_by_agent_id`` the indexed model is used and no
    bracket is set. Otherwise the unindexed resolver is consulted using
    the dispatch context captured from the matching assistant tool_use,
    and the resolver's bracket (when it could not commit to one model) is
    carried through.

    Args:
        records: The records in scope.
        subagent_models_by_agent_id: ``agentId``-keyed map from the
            session's merged subagent-model index.

    Yields:
        One ``ResolvedDispatch`` per matched dispatch, in record
        order.
    """
    contexts = _build_dispatch_contexts(records)
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
        token_bag = token_sums_dict_from_usage(usage)
        if isinstance(agent_id, str) and agent_id in subagent_models_by_agent_id:
            yield ResolvedDispatch(
                point_model=subagent_models_by_agent_id[agent_id],
                bracket=None,
                token_bag=token_bag,
                resolved_without_index=False,
            )
            continue
        context = contexts[matched_tool_use_id]
        resolved = resolve_unindexed_subagent_model(
            subagent_type=context.subagent_type,
            input_model=context.input_model,
            parent_main_model=context.parent_main_model,
        )
        yield ResolvedDispatch(
            point_model=resolved.canonical_model,
            bracket=resolved.bracket,
            token_bag=token_bag,
            resolved_without_index=True,
        )


@dataclass(frozen=True)
class _DispatchContext:
    """Context for one Agent dispatch needed by the unindexed-model resolver.

    Attributes:
        subagent_type: ``input.subagent_type`` on the dispatch's tool_use
            block, or ``None`` when the field was omitted.
        input_model: ``input.model`` on the dispatch's tool_use block, or
            ``None`` when the field was not set.
        parent_main_model: The ``message.model`` of the assistant record
            that emitted the dispatch.
    """

    subagent_type: str | None
    input_model: str | None
    parent_main_model: str


def _build_dispatch_contexts(records: list[Record]) -> dict[str, _DispatchContext]:
    """Build a tool_use_id -> dispatch context map from a record subset.

    Walks non-synthetic assistant records, capturing every ``Agent``
    tool_use block's ``input.subagent_type`` and ``input.model`` along
    with the emitting record's ``message.model`` (the parent's main
    model). The resulting map is the join input the unindexed-model
    resolver consumes when an ``agentId`` is not in the subagent-model
    index.
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

    The user record carries one ``tool_result`` block per dispatched tool
    call; this helper returns the first ``tool_use_id`` whose matching
    assistant ``tool_use`` block was an ``Agent`` dispatch (i.e. is keyed
    in ``contexts``). Returns ``None`` when the user record is not an
    Agent-dispatch result.
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


def token_sums_dict_from_usage(usage: dict[str, Any]) -> dict[str, int]:
    """Extract the five-category token bag from a ``message.usage`` block.

    Returns a dict keyed by the ``rates.CATEGORY_*`` constants, ready to
    hand to ``rates.cost_in_usd`` or to fold into per-category sums.
    Missing or non-integer fields contribute zero.

    Args:
        usage: One ``message.usage`` block.

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
