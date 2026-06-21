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

from .commands import APM_HANDOFF_COMMANDS, extract_command_names
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


def reset_event_blocks(
    role_conversations: Iterable[tuple[str, Conversation]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the compaction and handoff blocks for a session's conversations.

    Args:
        role_conversations: The session's ``(role_key, conversation)`` pairs in
            session order.

    Returns:
        A ``(compaction_events, handoffs)`` pair, each a flat list across all
        conversations in the given order; either is empty when no such reset
        occurred.
    """
    compaction_events: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    for role_key, conversation in role_conversations:
        compaction_events.extend(_compaction_entries(role_key, conversation))
        handoffs.extend(_handoff_entries(role_key, conversation))
    return compaction_events, handoffs
