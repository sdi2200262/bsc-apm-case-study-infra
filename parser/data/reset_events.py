# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Summarise a session's context-reset events for the identity block.

Two kinds of reset are surfaced per conversation. A compaction is a Claude
Code ``compact_boundary`` event, already parsed onto the conversation; it is
flattened to its trigger and before/after token sizes. A handoff is a
user-authored prompt invoking an ``APM_HANDOFF_COMMANDS`` member, detected the
same way role-initiation commands are. Each emitted entry names the
``role_key`` of the conversation it belongs to, so the identity block records
which instance reset.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .commands import APM_HANDOFF_COMMANDS, APM_RECOVER_COMMAND, extract_command_names
from .conversation import Conversation
from .prompts import is_user_authored_prompt
from .schema import user_prompt_text


def _compaction_entries(role_key: str, conversation: Conversation) -> list[dict[str, Any]]:
    """Return one dict per compaction event in a conversation.

    Args:
        role_key: Role label of the owning conversation.
        conversation: The conversation whose compaction events to summarise.

    Returns:
        One dict per event in record order, each carrying ``role_key`` and the
        event's ``trigger``, ``pre_tokens``, ``post_tokens``, and ``duration_ms``.
    """
    return [
        {
            "role_key": role_key,
            "trigger": event.trigger,
            "pre_tokens": event.pre_tokens,
            "post_tokens": event.post_tokens,
            "duration_ms": event.duration_ms,
        }
        for event in conversation.compaction_events
    ]


def _handoff_entries(role_key: str, conversation: Conversation) -> list[dict[str, Any]]:
    """Return one dict per handoff command invoked in a conversation.

    A handoff is a user-authored prompt carrying an ``APM_HANDOFF_COMMANDS``
    member in a ``<command-name>`` marker, detected exactly as role-initiation
    commands are. The ``role_key`` names the outgoing instance.

    Args:
        role_key: Role label of the conversation being scanned.
        conversation: The conversation to scan.

    Returns:
        One dict per handoff invocation in record order.
    """
    entries: list[dict[str, Any]] = []
    for record in conversation.records:
        if not is_user_authored_prompt(record):
            continue
        for command in extract_command_names(user_prompt_text(record)):
            if command in APM_HANDOFF_COMMANDS:
                entries.append({"role_key": role_key, "command": command})
    return entries


def _recovery_entries(
    role_key: str, conversation: Conversation
) -> tuple[list[dict[str, Any]], int]:
    """Return recovery entries and a count of anomalous recoveries for a conversation.

    A genuine recovery is an ``apm-9-recover`` invocation that follows a
    compaction boundary in the same conversation. A recovery with no preceding
    compaction is anomalous and counted separately rather than included in entries.

    Single pass: ``boundary_ids`` marks the ``id()`` of each
    ``CompactionEvent.boundary_record`` (the same object that sits in
    ``conversation.records``), so identity comparison correctly detects when the
    boundary record has been passed.

    Args:
        role_key: Role label of the conversation being scanned.
        conversation: The conversation to scan.

    Returns:
        A ``(entries, anomalous_count)`` pair. ``entries`` is one dict per
        genuine recovery invocation in record order. ``anomalous_count`` is the
        count of ``apm-9-recover`` invocations that had no preceding compaction.
    """
    boundary_ids: frozenset[int] = frozenset(
        id(event.boundary_record) for event in conversation.compaction_events
    )
    entries: list[dict[str, Any]] = []
    anomalous_count = 0
    seen_compaction = False
    for record in conversation.records:
        if id(record) in boundary_ids:
            seen_compaction = True
        if not is_user_authored_prompt(record):
            continue
        for command in extract_command_names(user_prompt_text(record)):
            if command == APM_RECOVER_COMMAND:
                if seen_compaction:
                    entries.append({"role_key": role_key, "command": command})
                else:
                    anomalous_count += 1
    return entries, anomalous_count


def count_anomalous_recoveries(
    role_conversations: Iterable[tuple[str, Conversation]],
) -> int:
    """Return the total count of ``apm-9-recover`` invocations with no preceding compaction.

    Counts across all conversations; a recover that follows no compaction in
    its conversation is anomalous.

    Args:
        role_conversations: The session's ``(role_key, conversation)`` pairs.

    Returns:
        The sum of anomalous recover counts across all conversations.
    """
    return sum(
        _recovery_entries(role_key, conversation)[1]
        for role_key, conversation in role_conversations
    )


def reset_event_blocks(
    role_conversations: Iterable[tuple[str, Conversation]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the compaction, handoff, and recovery blocks for a session's conversations.

    Args:
        role_conversations: The session's ``(role_key, conversation)`` pairs in
            session order.

    Returns:
        A ``(compaction_events, handoffs, recoveries)`` triple, each a flat list
        across all conversations in the given order; either is empty when no such
        reset occurred. ``recoveries`` contains only genuine recoveries (those
        following a compaction); anomalous recoveries are counted separately via
        ``count_anomalous_recoveries``.
    """
    compaction_events: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    for role_key, conversation in role_conversations:
        compaction_events.extend(_compaction_entries(role_key, conversation))
        handoffs.extend(_handoff_entries(role_key, conversation))
        recoveries.extend(_recovery_entries(role_key, conversation)[0])
    return compaction_events, handoffs, recoveries
