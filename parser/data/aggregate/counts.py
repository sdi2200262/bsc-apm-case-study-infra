# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-scope counts: requests, subagents, tools, turns, and user inputs.

Every count the parser exposes is data: a value read or tallied from the
transcript whose only freedom is which records are selected. This module
owns those counts: the request, subagent, tool, and user-input groups as
one dataclass each (see each dataclass's ``Attributes`` for the exact
populations), the turn count as the standalone ``turn_count`` function,
and the per-prompt ``BucketedPrompt`` bucket-and-length series the
turn-prompt metric folds without re-reading records.

The request, subagent, and tool counts share their selection rules with
the token and reliability folds rather than redefining them: the main-call
rule lives once in ``call_records`` and is consumed here, and the
``tool_result`` rule is the same block predicate the reliability rate
divides over.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..buckets import classify_bucket
from ..conversation import STEER_FATE_ABANDONED, STEER_FATE_DELIVERED, SteerEvent
from ..prompts import is_model_invoked_skill_rendering
from ..schema import (
    AGENT_TOOL_NAME,
    CONTENT_BLOCK_TOOL_RESULT,
    CONTENT_BLOCK_TOOL_USE,
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    Record,
    assistant_content_blocks,
    is_synthetic_assistant,
    user_content_blocks,
    user_prompt_text,
)
from ..subagent_usage import SubagentDispatchIndex
from ..turns import Turn
from .call_records import is_main_request_record


@dataclass(frozen=True)
class RequestCounts:
    """Request-count block for a single scope.

    Attributes:
        request_count: Number of distinct non-synthetic, non-API-error
            main ``requestId`` values in scope.
        delegated_request_count: Number of Agent ``tool_use`` blocks
            dispatched by main agents in scope.
        requests_with_tool_use_count: Number of distinct main
            ``requestId`` values whose assistant records emitted at least
            one ``tool_use`` block.
    """

    request_count: int
    delegated_request_count: int
    requests_with_tool_use_count: int


@dataclass(frozen=True)
class SubagentCounts:
    """Subagent-activity count block for a single scope.

    Attributes:
        subagent_count: Number of Agent tool_use blocks dispatched by the
            main agents in scope.
        subagent_tool_count: Sum of ``toolUseResult.totalToolUseCount``
            across user records that returned a populated subagent result.
        subagent_request_count: Sum of the dispatched subagents' own billed
            request counts, one dispatch's count added at the scope record
            that returned its result. A dispatch whose subagent transcript
            did not ship is not in the index and contributes nothing.
        model_invoked_skill_count: Number of user-side records in scope
            that are platform-rendered Skill bodies the model itself
            caused to be injected via the Skill tool.
    """

    subagent_count: int
    subagent_tool_count: int
    subagent_request_count: int
    model_invoked_skill_count: int


@dataclass(frozen=True)
class ToolCounts:
    """Tool-result count block for a single scope.

    Attributes:
        tool_result_count: Total number of ``tool_result`` blocks observed
            in the scope (the success-rate denominator).
        tool_error_count: Subset of ``tool_result_count`` carrying
            ``is_error: true``.
    """

    tool_result_count: int
    tool_error_count: int


@dataclass(frozen=True)
class BucketedPrompt:
    """One turn prompt reduced to its bucket label and character length.

    Attributes:
        bucket: The prompt-size bucket constant (``protocol`` / ``short`` /
            ``standard``) the prompt's text classified into.
        length: The character length of the prompt's text.
    """

    bucket: str
    length: int


@dataclass(frozen=True)
class UserInputCounts:
    """User-input counts plus the per-prompt bucket-and-length series.

    Attributes:
        turn_prompt_count: Number of turn-starting user prompts.
        steer_delivered_count: Steers whose queued content reached the
            model.
        steer_abandoned_count: Steers not delivered because they were
            cancelled or remained unresolved when the conversation ended.
        turn_prompt_inputs: One ``BucketedPrompt`` per turn-starting prompt,
            in turn order.
    """

    turn_prompt_count: int
    steer_delivered_count: int
    steer_abandoned_count: int
    turn_prompt_inputs: tuple[BucketedPrompt, ...]


def compute_request_counts(records: Iterable[Record]) -> RequestCounts:
    """Compute request-count metrics over an arbitrary record subset.

    The three counts are computed in a single pass. The main-request
    population is selected by the shared
    ``call_records.is_main_request_record`` rule; ``request_count`` is
    the number of distinct ``requestId`` values, and the tool-use and
    delegated counts scan the content blocks of every selected record so a
    ``tool_use`` block on any record of a call is observed.

    Args:
        records: The records in scope, in any order.

    Returns:
        The three counts wrapped in a ``RequestCounts``.
    """
    main_request_ids: set[str] = set()
    requests_with_tool_use: set[str] = set()
    delegated_request_count = 0
    for record in records:
        if not is_main_request_record(record):
            continue
        request_id = record.payload["requestId"]
        main_request_ids.add(request_id)
        for block in assistant_content_blocks(record):
            if block.get("type") != CONTENT_BLOCK_TOOL_USE:
                continue
            requests_with_tool_use.add(request_id)
            if block.get("name") == AGENT_TOOL_NAME:
                delegated_request_count += 1
    return RequestCounts(
        request_count=len(main_request_ids),
        delegated_request_count=delegated_request_count,
        requests_with_tool_use_count=len(requests_with_tool_use),
    )


def compute_subagent_counts(
    records: Iterable[Record], subagent_index: SubagentDispatchIndex
) -> SubagentCounts:
    """Compute subagent-activity counts over an arbitrary record subset.

    The dispatch and tool-use counts are read from the scope records
    themselves; the subagent request count is looked up per returning
    record from ``subagent_index``, keyed by the dispatch's ``agentId``, so
    it attributes to the same scope record the tool-use count does.

    Args:
        records: The records in scope, in any order.
        subagent_index: ``agentId``-keyed index carrying each dispatched
            subagent's own billed request count.

    Returns:
        The Agent dispatch count, the summed subagent tool-use count, the
        summed subagent request count, and the model-invoked Skill count
        for the scope.
    """
    subagent_count = 0
    subagent_tool_count = 0
    subagent_request_count = 0
    model_invoked_skill_count = 0
    for record in records:
        if is_synthetic_assistant(record):
            continue
        if record.record_type == RECORD_TYPE_ASSISTANT:
            for block in assistant_content_blocks(record):
                if (
                    block.get("type") == CONTENT_BLOCK_TOOL_USE
                    and block.get("name") == AGENT_TOOL_NAME
                ):
                    subagent_count += 1
        elif record.record_type == RECORD_TYPE_USER:
            tool_use_result = record.payload.get("toolUseResult")
            if isinstance(tool_use_result, dict):
                total = tool_use_result.get("totalToolUseCount")
                if isinstance(total, int):
                    subagent_tool_count += total
                agent_id = tool_use_result.get("agentId")
                if isinstance(agent_id, str):
                    subagent_request_count += subagent_index.requests_by_agent_id.get(agent_id, 0)
            if is_model_invoked_skill_rendering(record):
                model_invoked_skill_count += 1
    return SubagentCounts(
        subagent_count=subagent_count,
        subagent_tool_count=subagent_tool_count,
        subagent_request_count=subagent_request_count,
        model_invoked_skill_count=model_invoked_skill_count,
    )


def compute_tool_counts(records: Iterable[Record]) -> ToolCounts:
    """Count ``tool_result`` blocks and the subset carrying an error flag.

    Only user records contribute. Iterating the scope's full record
    stream keeps the denominator stable across session, phase, and role
    aggregations.

    Args:
        records: The records to scan.

    Returns:
        A populated ``ToolCounts``.
    """
    total = 0
    errors = 0
    for record in records:
        for block in _tool_result_blocks(record):
            total += 1
            if block.get("is_error") is True:
                errors += 1
    return ToolCounts(tool_result_count=total, tool_error_count=errors)


def turn_count(turns: Iterable[Turn]) -> int:
    """Return the number of turns in a scope."""
    return sum(1 for _ in turns)


def compute_user_input_counts(
    turns: Iterable[Turn],
    steer_events: Iterable[SteerEvent],
    short_threshold: int,
) -> UserInputCounts:
    """Compute user-input counts and the turn-prompt bucket series.

    Turn prompts are reduced to a ``BucketedPrompt`` series here, in the
    data layer, so the metric folds shares and magnitudes without reading
    records or calling the schema extractors. Steers retain only their
    disjoint delivered and abandoned counts.

    Args:
        turns: Turns whose starting prompts make up the turn-prompt
            population.
        steer_events: Steer events whose enqueues are classified into
            delivered and abandoned populations.
        short_threshold: Bucket classifier threshold in characters.

    Returns:
        A populated ``UserInputCounts``.
    """
    turn_list = list(turns)
    user_events = [e for e in steer_events if e.is_user_authored]
    delivered_events = [e for e in user_events if e.fate == STEER_FATE_DELIVERED]
    abandoned_events = [e for e in user_events if e.fate == STEER_FATE_ABANDONED]
    turn_prompt_inputs = tuple(
        _bucketed_prompt(_text_of_turn_prompt(turn.starting_prompt), short_threshold)
        for turn in turn_list
    )
    return UserInputCounts(
        turn_prompt_count=len(turn_list),
        steer_delivered_count=len(delivered_events),
        steer_abandoned_count=len(abandoned_events),
        turn_prompt_inputs=turn_prompt_inputs,
    )


def _bucketed_prompt(text: str, short_threshold: int) -> BucketedPrompt:
    """Reduce a turn prompt to its bucket label and character length."""
    return BucketedPrompt(bucket=classify_bucket(text, short_threshold), length=len(text))


def _text_of_turn_prompt(record: Record) -> str:
    """Return the prompt text used for bucket classification on a turn-starter."""
    return user_prompt_text(record)


def _tool_result_blocks(record: Record) -> list[dict[str, Any]]:
    """Return every ``tool_result`` content block on a user record."""
    return [
        block
        for block in user_content_blocks(record)
        if block.get("type") == CONTENT_BLOCK_TOOL_RESULT
    ]
