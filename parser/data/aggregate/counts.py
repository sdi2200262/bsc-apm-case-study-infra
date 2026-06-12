#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Per-scope counts: requests, subagents, tools, turns, and user inputs.

Every count the parser exposes is data: a value read or tallied from the
transcript whose only freedom is which records are selected. This module
owns them, grouped by population:

- Requests: distinct non-synthetic non-error main ``requestId`` values,
  Agent dispatch blocks, and requests whose response carried any tool use.
- Subagents: Agent dispatch blocks, rolled-up subagent tool-use counts,
  and model-invoked Skill renderings.
- Tools: ``tool_result`` blocks and the subset carrying ``is_error``.
- Turns: the count of turns in scope.
- User inputs: turn-prompt and steer counts, and the per-input bucket
  label and character length attached as a series so the user-input
  metric can fold shares and magnitudes without re-reading the records.

The request, subagent, and tool counts share their selection rules with
the token and reliability folds: the main-call rule lives once in
``call_records`` and is consumed here, and the ``tool_result`` rule is the
same block predicate the reliability rate divides over.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..buckets import classify_bucket
from ..conversation import STEER_FATE_DELIVERED, SteerEvent
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
    queue_record_content,
    user_content_blocks,
    user_prompt_text,
)
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
        model_invoked_skill_count: Number of user-side records in scope
            that are platform-rendered Skill bodies the model itself
            caused to be injected via the Skill tool.
    """

    subagent_count: int
    subagent_tool_count: int
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
class BucketedInput:
    """One user input reduced to its bucket label and character length.

    Attributes:
        bucket: The input-size bucket constant (``protocol`` / ``short`` /
            ``standard``) the input's text classified into.
        length: The character length of the input's text.
    """

    bucket: str
    length: int


@dataclass(frozen=True)
class UserInputCounts:
    """User-input count block plus the per-input bucket-and-length series.

    Attributes:
        turn_prompt_count: Number of turn-starting user prompts.
        steer_delivered_count: Steers whose queued content reached the
            model.
        steer_abandoned_count: Steers cancelled before delivery.
        steer_attempted_count:
            ``steer_delivered_count + steer_abandoned_count``.
        turn_prompt_inputs: One ``BucketedInput`` per turn-starting prompt,
            in turn order.
        delivered_steer_inputs: One ``BucketedInput`` per delivered steer,
            in steer order.
    """

    turn_prompt_count: int
    steer_delivered_count: int
    steer_abandoned_count: int
    steer_attempted_count: int
    turn_prompt_inputs: tuple[BucketedInput, ...]
    delivered_steer_inputs: tuple[BucketedInput, ...]


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


def compute_subagent_counts(records: Iterable[Record]) -> SubagentCounts:
    """Compute subagent-activity counts over an arbitrary record subset.

    Args:
        records: The records in scope, in any order.

    Returns:
        The Agent dispatch count, the summed subagent tool-use count, and
        the model-invoked Skill count for the scope.
    """
    subagent_count = 0
    subagent_tool_count = 0
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
            if is_model_invoked_skill_rendering(record):
                model_invoked_skill_count += 1
    return SubagentCounts(
        subagent_count=subagent_count,
        subagent_tool_count=subagent_tool_count,
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
    """Compute user-input counts and the per-input bucket-and-length series.

    The turn-prompt and delivered-steer populations are each reduced to a
    ``BucketedInput`` series here, in the data layer, so the user-input
    metric folds shares and magnitudes without reading records or calling
    the schema extractors.

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
    abandoned_events = [e for e in user_events if e.fate != STEER_FATE_DELIVERED]
    turn_prompt_inputs = tuple(
        _bucketed_input(_text_of_turn_prompt(turn.starting_prompt), short_threshold)
        for turn in turn_list
    )
    delivered_steer_inputs = tuple(
        _bucketed_input(_text_of_steer(event), short_threshold) for event in delivered_events
    )
    return UserInputCounts(
        turn_prompt_count=len(turn_list),
        steer_delivered_count=len(delivered_events),
        steer_abandoned_count=len(abandoned_events),
        steer_attempted_count=len(delivered_events) + len(abandoned_events),
        turn_prompt_inputs=turn_prompt_inputs,
        delivered_steer_inputs=delivered_steer_inputs,
    )


def _bucketed_input(text: str, short_threshold: int) -> BucketedInput:
    """Reduce an input's text to its bucket label and character length."""
    return BucketedInput(bucket=classify_bucket(text, short_threshold), length=len(text))


def _text_of_turn_prompt(record: Record) -> str:
    """Return the prompt text used for bucket classification on a turn-starter."""
    return user_prompt_text(record)


def _text_of_steer(event: SteerEvent) -> str:
    """Return the queued content used for bucket classification on a steer."""
    content = queue_record_content(event.enqueue_record)
    return content if content is not None else ""


def _tool_result_blocks(record: Record) -> list[dict[str, Any]]:
    """Return every ``tool_result`` content block on a user record."""
    return [
        block
        for block in user_content_blocks(record)
        if block.get("type") == CONTENT_BLOCK_TOOL_RESULT
    ]
