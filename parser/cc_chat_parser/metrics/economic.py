#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Economic-dimension metrics: per-category token sums and API-equivalent cost.

Token usage on a Claude Code conversation comes from two disjoint
populations and the parser sums both:

* **Main usage** is the per-API-call usage of the conversation's main
  agent. Claude Code emits one JSONL record per content block of a
  streaming API response, with every record from the same call
  carrying an identical ``message.usage``. Summing per record would
  multiply the call's tokens by the block count (up to roughly 11x
  on real data), so the loader's ``RequestUsageIndex`` provides one
  ``usage`` dict per unique non-synthetic ``requestId``; this module
  sums across that deduplicated population.

* **Delegated usage** is the rolled-up usage of subagent dispatches.
  When the main agent calls the ``Agent`` tool to dispatch a
  subagent, the subagent's full token consumption is reported back
  on the parent user record's ``toolUseResult.usage``. The two
  populations do not overlap: the parent assistant record's
  ``message.usage`` accounts for the Agent tool dispatch as a
  regular tool call (one ``tool_use`` block in the parent's content,
  cheap on its own), while the subagent's actual computation lives
  entirely under ``toolUseResult.usage``. Some Agent dispatches lack
  populated ``toolUseResult.usage`` (the dispatch was in flight or
  did not return at session end); those contribute zero tokens and
  are counted in diagnostics so the ratio of complete-to-incomplete
  dispatches is visible.

Cost is computed call-by-call against the pinned rate table by the
``cost_attribution`` sibling module. The session-scope ``model``
field exposed on ``EconomicSession`` is the modal non-synthetic
``message.model`` across main records and is a diagnostic, not the
pricing input. When at least one delegated dispatch was bracketed
by the unindexed-model resolver, ``EconomicSession.cost_usd`` is
``None`` and the ``cost_usd_lower_bound`` / ``cost_usd_upper_bound``
fields carry the range; otherwise ``cost_usd`` carries the single
attributed figure and the bound fields are ``None``.

A Claude Code autocompaction event mid-session is handled correctly
without any special boundary logic. Each call's ``message.usage``
reflects what that call actually consumed: pre-boundary calls were
billed against the pre-compaction context (large prefix, cache hits
likely), post-boundary calls against the new post-compaction context
(smaller, no surviving cache initially, fresh cache prefix building
up). Summing per-requestId-deduped usage across the whole file gives
the correct total for visible API calls, with no double-counting at
the boundary.

The compaction synthesis call itself is a real billable event on the
participant's account (the model is asked to summarise the
pre-compaction context into the post-compaction summary), but Claude
Code does not write that call as a regular ``assistant`` record. Its
token usage is therefore not visible to this parser and not included
in the cost figure. When a session contains one or more compaction
events, the cost it reports is a *minimum* on the participant's
actual API-equivalent bill; the diagnostics block surfaces the
compaction event count so downstream analysis can flag affected
sessions. When the session contains zero compaction events, the
figure is exact for visible calls and the framing is moot.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from ..rates import (
    CATEGORY_CACHE_1H,
    CATEGORY_CACHE_5M,
    CATEGORY_CACHE_READ,
    CATEGORY_INPUT,
    CATEGORY_OUTPUT,
    RateTable,
)
from ..schema import (
    AGENT_TOOL_NAME,
    CONTENT_BLOCK_TOOL_RESULT,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    Record,
    SYNTHETIC_MODEL_MARKER,
    iter_agent_dispatch_blocks,
)
from ..session import Session
from .cost_attribution import (
    _token_sums_dict_from_usage,
    attribute_cost_for_records,
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
    def zero(cls) -> "TokenSums":
        """Return a ``TokenSums`` with all categories at zero."""
        return cls(input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0)

    def add(self, other: "TokenSums") -> "TokenSums":
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
class EconomicSession:
    """Session-scope economic metric block.

    Cost is reported either as a single ``cost_usd`` figure or as a
    ``cost_usd_lower_bound`` / ``cost_usd_upper_bound`` pair, never
    both. The pair shape is used when at least one delegated
    dispatch in the scope was bracketed by the unindexed-model
    resolver; otherwise cost is a single number.

    Attributes:
        main: Main-call deduplicated token totals.
        delegated: Subagent-dispatch rolled-up token totals.
        total: Per-category sum of ``main`` and ``delegated``.
        total_prompt_tokens: ``input + cache_read + cache_5m + cache_1h``
            of ``total`` (the full input volume; output is disjoint).
        cost_usd: API-equivalent USD cost; ``None`` when bracketed.
        cost_usd_lower_bound: Lower bound when bracketed; else ``None``.
        cost_usd_upper_bound: Upper bound when bracketed; else ``None``.
        model: Modal non-synthetic ``message.model`` across main
            records (diagnostic; not the pricing input).
        agent_dispatches_total: Number of Agent tool_use blocks.
        agent_dispatches_with_usage: Subset whose
            ``toolUseResult.usage`` was populated.
        model_token_distribution: ``model -> billed tokens`` summed
            over the five categories. For bracketed dispatches the
            point-estimate model is recorded.
        dispatches_resolved_without_index: Dispatches whose
            ``agentId`` was not in the ``SubagentModelIndex`` and
            which were priced via the fallback resolver.
        dispatches_bracketed: Subset of the above that hit the
            bracket path.
    """

    main: TokenSums
    delegated: TokenSums
    total: TokenSums
    total_prompt_tokens: int
    cost_usd: float | None
    cost_usd_lower_bound: float | None
    cost_usd_upper_bound: float | None
    model: str
    agent_dispatches_total: int
    agent_dispatches_with_usage: int
    model_token_distribution: dict[str, int]
    dispatches_resolved_without_index: int
    dispatches_bracketed: int


def compute_session_economic(session: Session, rate_table: RateTable) -> EconomicSession:
    """Compute the session-scope economic metric block.

    Args:
        session: An assembled session.
        rate_table: The rate table to compute cost against. Loaded
            by the caller via ``rates.load_rate_table`` so the
            choice of canonical or override file is explicit at the
            call site.

    Returns:
        A populated ``EconomicSession``.

    Raises:
        rates.RateTableError: When a model encountered during per-call
            pricing is not present in ``rate_table.models``. The
            caller is responsible for either adding the model to the
            YAML or surfacing the unpinned model as an actionable
            error.
    """
    all_records = [
        record
        for view in session.views
        for record in view.conversation.records
    ]
    subagent_models = _merge_subagent_indices(session)
    return compute_economic_for_records(all_records, rate_table, subagent_models)


def compute_economic_for_records(
    records: list[Record],
    rate_table: RateTable,
    subagent_models_by_agent_id: dict[str, str],
) -> EconomicSession:
    """Compute economic metrics over an arbitrary subset of records.

    Used both for session-scope aggregation (every record across
    every conversation) and for phase or role scope (the records
    that belong to turns whose phase or role match). Deduplication
    by ``requestId`` is applied locally to the subset so each
    distinct API call contributes its usage exactly once even when
    the subset spans multiple turns of the same conversation.

    Args:
        records: The records to aggregate over.
        rate_table: The rate table to compute cost against.
        subagent_models_by_agent_id: Merged
            ``SubagentModelIndex.by_agent_id`` map across every
            conversation in the session. Used by
            ``cost_attribution`` to price each delegated dispatch at
            the actual subagent's model when the sibling file was
            shipped.

    Returns:
        A populated ``EconomicSession``.

    Raises:
        rates.RateTableError: When a per-call model resolves to an
            id not present in ``rate_table.models``.
    """
    main_total = _sum_main_from_records(records)
    delegated_total, dispatches_total, dispatches_with_usage = _sum_delegated_from_records(records)
    total = main_total.add(delegated_total)
    total_prompt = total.input + total.cache_read + total.cache_5m + total.cache_1h
    attribution = attribute_cost_for_records(records, rate_table, subagent_models_by_agent_id)
    return EconomicSession(
        main=main_total,
        delegated=delegated_total,
        total=total,
        total_prompt_tokens=total_prompt,
        cost_usd=attribution.cost_usd,
        cost_usd_lower_bound=attribution.cost_usd_lower_bound,
        cost_usd_upper_bound=attribution.cost_usd_upper_bound,
        model=_modal_main_model_from_records(records),
        agent_dispatches_total=dispatches_total,
        agent_dispatches_with_usage=dispatches_with_usage,
        model_token_distribution=attribution.model_token_distribution,
        dispatches_resolved_without_index=attribution.dispatches_resolved_without_index,
        dispatches_bracketed=attribution.dispatches_bracketed,
    )


def _merge_subagent_indices(session: Session) -> dict[str, str]:
    """Merge per-conversation subagent-model indices into one session-scope map.

    ``agentId`` values are globally unique across Claude Code, so a
    flat ``dict.update`` per conversation produces a session-scope
    index without collisions. When two conversations happen to
    re-use an id (which Claude Code is not expected to do), the
    later conversation's value wins; this is acceptable as a
    fall-through and is not surfaced separately.
    """
    merged: dict[str, str] = {}
    for view in session.views:
        merged.update(view.conversation.subagent_model_index.by_agent_id)
    return merged


def _modal_main_model_from_records(records: list[Record]) -> str:
    """Return the modal non-synthetic ``message.model`` across a record subset.

    Returns the empty string when the subset contains no qualifying
    main assistant record, which can happen for a phase or role
    scope that holds only delegated activity. Callers treat the
    empty string as "no main-call modal model" and rely on the
    per-call cost computation for the figure.
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


def iter_main_request_records(records: Iterable[Record]) -> Iterator[Record]:
    """Yield the first assistant record observed for each main-call requestId.

    Walks ``records`` in order and yields one record per unique
    ``message.requestId`` among non-synthetic, non-API-error
    assistant records. Skips records that fail the main-call
    selection rule (wrong record type, synthetic model marker, API
    error flag, missing or non-string ``requestId``) and skips
    duplicate records for an already-yielded requestId. The dedup
    is local to the ``records`` iterable; callers wanting a global
    dedup must pass a single iterable that covers their scope.

    Args:
        records: Conversation records in document order. Mixed
            record types are tolerated; only assistant records that
            pass the main-call filter are yielded.

    Yields:
        The first ``Record`` instance carrying each unique main-call
        ``requestId`` encountered in ``records``.
    """
    seen: set[str] = set()
    for record in records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") == SYNTHETIC_MODEL_MARKER:
            continue
        if record.payload.get("isApiErrorMessage") is True:
            continue
        request_id = record.payload.get("requestId")
        if not isinstance(request_id, str):
            continue
        if request_id in seen:
            continue
        seen.add(request_id)
        yield record


def _sum_main_from_records(records: list[Record]) -> TokenSums:
    """Sum main-call tokens across an arbitrary record subset, deduplicated by requestId.

    Walks ``records`` with :func:`iter_main_request_records` so the
    main-call selection rule and the per-scope dedup are shared
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
) -> tuple[TokenSums, int, int]:
    """Sum subagent-dispatch tokens across a record subset and report dispatch counts.

    Returns ``(delegated_sums, dispatches_total, dispatches_with_usage)``
    where ``dispatches_total`` counts every ``Agent`` tool_use block
    in the assistant records of the subset and
    ``dispatches_with_usage`` counts how many of those dispatches
    had populated ``toolUseResult.usage`` on a matching user record
    in the same subset. The remaining gap reflects dispatches whose
    response did not return into this scope.
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

    Thin adapter over ``cost_attribution._token_sums_dict_from_usage``:
    the shared core does the extraction and this wrapper repackages
    the category-keyed dict into the typed ``TokenSums`` dataclass.

    Args:
        usage: One ``message.usage`` block.

    Returns:
        A ``TokenSums`` carrying the five per-category totals.
    """
    sums = _token_sums_dict_from_usage(usage)
    return TokenSums(
        input=sums[CATEGORY_INPUT],
        output=sums[CATEGORY_OUTPUT],
        cache_read=sums[CATEGORY_CACHE_READ],
        cache_5m=sums[CATEGORY_CACHE_5M],
        cache_1h=sums[CATEGORY_CACHE_1H],
    )
