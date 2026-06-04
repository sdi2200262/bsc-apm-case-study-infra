#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Assemble a participant submission into a typed ``Session``.

A submission consists of one or more conversation files belonging to
the same participant session. Spec-kit submissions are expected to
contain a single conversation file by canonical workflow; an APM
submission contains one Planner conversation, one or more Manager
conversations (more when handoffs occurred), and one or more Worker
conversations (one per Worker the participant initiated, plus any
handoff continuations).

Two responsibilities sit here, above the per-conversation work the
loader does and the role and phase computation the framework
assigners do:

1. Number each APM conversation's role and key it. The role itself
   is determined by :func:`apm_role_assigner.assign_apm_roles`; this
   module numbers roles sequentially by first-record timestamp
   ascending, with no parsing of participant-supplied identifiers.
   Participants type worker identifiers by hand on
   ``/apm-3-initiate-worker <id>``, so typos in re-invocations would
   split what is semantically the same worker into two distinct keys
   (``frontend-agent`` and ``fronend-agent``) if the parser tried to
   use the participant's id. Sequential numbering avoids the trap;
   the verbatim first command of each conversation is preserved per
   file so a downstream reviewer can spot two role-keys with
   similar-but-typo-different first commands and decide whether to
   merge them.

2. Partition each framework assigner's per-record phase output back
   per conversation file and attach it to the view. APM role and phase
   come from :func:`apm_role_assigner.assign_apm_roles`, Spec-kit phase
   from :func:`speckit_phase_assigner.assign_speckit_phases`; this
   module does no phase computation of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .apm_role_assigner import ConversationRole, assign_apm_roles
from .commands import (
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
)
from .loader import (
    Conversation,
    discover_conversation_files,
    load_conversation,
)
from .speckit_phase_assigner import assign_speckit_phases
from .schema import (
    Record,
    SchemaError,
)
from .turns import Turn, derive_turns
from .user_prompts import is_user_authored_prompt


@dataclass(frozen=True)
class ConversationView:
    """Per-conversation view assembled at session level.

    Attributes:
        conversation: The loaded ``Conversation`` from the loader.
        role: Role label for APM conversations, including the
            sequential index suffix (``planner-1``, ``manager-2``,
            ``worker-3``); the literal string ``unassigned-N`` for
            APM conversations whose first slash command is not a role
            initiator; the literal string ``conversation-N`` for any
            Spec-kit conversation (Spec-kit has no role concept, so
            the label is descriptive rather than role-bearing).
        first_command: Verbatim first slash command observed in the
            conversation, including any arguments, typos, or
            whitespace as written by the participant. Empty string
            when no slash command appears in any record.
        first_command_record: The record carrying ``first_command``,
            or ``None`` when no such record exists.
        first_record_timestamp: Earliest user-authored prompt
            timestamp in the conversation; falls back to the earliest
            timestamped record only when no user-authored prompt
            exists. Used to order conversations for sequential role
            numbering.
        phase_by_record_uuid: Phase label keyed by record uuid. For
            APM this maps each genuine user-prompt record to the
            role's phase. For Spec-kit this is the per-conversation
            slice of
            :attr:`speckit_phase_assigner.PhaseWalkResult.phase_by_uuid`,
            which documents the three populations covered.
    """

    conversation: Conversation
    role: str
    first_command: str
    first_command_record: Record | None
    first_record_timestamp: datetime | None
    phase_by_record_uuid: dict[str, str]


@dataclass(frozen=True)
class Session:
    """A complete participant submission, ready for metric computation.

    Attributes:
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``, set by
            the strict ``--framework`` flag at load time.
        views: Per-conversation views in input order (filesystem
            order from the directory walk, single-file callers get a
            single-element tuple).
        turns: Every derived turn across every conversation, in global
            timestamp order. Each turn knows its conversation file via
            ``Turn.conversation_path``.
        backward_skill_invocations: Chronological log of backward
            Skill events from the Spec-kit phase assigner; entry schema is
            documented on
            :attr:`speckit_phase_assigner.PhaseWalkResult.backward_skill_invocations`.
            Empty tuple for APM sessions and for Spec-kit sessions
            with no backward Skill invocations.
    """

    framework: str
    views: tuple[ConversationView, ...]
    turns: tuple[Turn, ...]
    backward_skill_invocations: tuple[dict[str, Any], ...]


def load_session(path: Path, framework: str) -> Session:
    """Load a participant submission and assemble it into a ``Session``.

    Args:
        path: Either a single ``*.jsonl`` file or a directory of
            ``*.jsonl`` files copied straight from
            ``~/.claude/projects/<dashed-cwd>/``.
        framework: ``FRAMEWORK_APM`` or ``FRAMEWORK_SPECKIT``. The
            value is taken verbatim from the caller's strict flag and
            is never inferred from file content.

    Returns:
        A populated ``Session``.

    Raises:
        SchemaError: When the path does not resolve to JSONL files,
            when any file fails to parse, or when ``framework`` is not
            one of the two recognised values.
        OSError: When a file cannot be read.
    """
    if framework not in (FRAMEWORK_APM, FRAMEWORK_SPECKIT):
        raise SchemaError(
            f"unknown framework {framework!r}; expected {FRAMEWORK_APM!r} or {FRAMEWORK_SPECKIT!r}"
        )
    files = discover_conversation_files(path)
    conversations = [load_conversation(p) for p in files]
    backward_skill_invocations: tuple[dict[str, Any], ...] = ()
    if framework == FRAMEWORK_APM:
        views = _build_apm_views(conversations)
    else:
        views, backward_skill_invocations = _build_speckit_views(conversations)
    turns = _collect_turns(views)
    return Session(
        framework=framework,
        views=views,
        turns=turns,
        backward_skill_invocations=backward_skill_invocations,
    )


def _build_apm_views(conversations: list[Conversation]) -> tuple[ConversationView, ...]:
    """Assemble per-conversation views for an APM submission.

    Roles and per-record phases are computed by
    :func:`apm_role_assigner.assign_apm_roles`. Conversations are then
    numbered sequentially per role kind by their earliest record
    timestamp ascending so that handoffs produce ``manager-2``,
    ``manager-3`` and parallel workers produce ``worker-1``,
    ``worker-2`` in chronological order.
    """
    result = assign_apm_roles(conversations)
    initial: list[tuple[Conversation, ConversationRole, datetime | None]] = [
        (conversation, role, _earliest_user_authored_timestamp(conversation.records))
        for conversation, role in zip(conversations, result.conversation_roles)
    ]
    initial.sort(key=lambda item: (item[2] is None, item[2]))
    counters: dict[str, int] = {}
    views: list[ConversationView] = []
    for conversation, role, first_ts in initial:
        counters[role.base_role] = counters.get(role.base_role, 0) + 1
        role_key = f"{role.base_role}-{counters[role.base_role]}"
        phase_by_uuid = {
            record.uuid: result.phase_by_uuid[record.uuid]
            for record in conversation.records
            if record.uuid and record.uuid in result.phase_by_uuid
        }
        views.append(ConversationView(
            conversation=conversation,
            role=role_key,
            first_command=role.first_command,
            first_command_record=role.first_command_record,
            first_record_timestamp=first_ts,
            phase_by_record_uuid=phase_by_uuid,
        ))
    return tuple(views)


def _build_speckit_views(
    conversations: list[Conversation],
) -> tuple[tuple[ConversationView, ...], tuple[dict[str, Any], ...]]:
    """Assemble per-conversation views for a Spec-kit submission.

    Spec-kit has no role concept; every conversation is labelled
    ``conversation-N`` for parallel structure with APM. The ratchet
    walk runs over the global timestamp-sorted prompt stream so that
    a multi-conversation Spec-kit submission still produces correct
    phase assignment for prompts in any conversation; the per-record
    phase assignments are then partitioned back per conversation
    file.
    """
    initial: list[tuple[Conversation, str, Record | None, datetime | None]] = []
    for conversation in conversations:
        # Spec-kit has no role-initiating command, so the view's
        # first_command is empty by definition; only APM conversations
        # carry one.
        initial.append((
            conversation,
            "",
            None,
            _earliest_user_authored_timestamp(conversation.records),
        ))
    initial.sort(key=lambda item: (item[3] is None, item[3]))
    walk_result = assign_speckit_phases(conversations)
    phase_by_uuid_global = walk_result.phase_by_uuid
    backward_skill_invocations = walk_result.backward_skill_invocations
    views: list[ConversationView] = []
    for index, (conversation, first_command, first_record, first_ts) in enumerate(initial, start=1):
        per_conversation: dict[str, str] = {
            record.uuid: phase_by_uuid_global[record.uuid]
            for record in conversation.records
            if record.uuid and record.uuid in phase_by_uuid_global
        }
        views.append(ConversationView(
            conversation=conversation,
            role=f"conversation-{index}",
            first_command=first_command,
            first_command_record=first_record,
            first_record_timestamp=first_ts,
            phase_by_record_uuid=per_conversation,
        ))
    return tuple(views), backward_skill_invocations


def _phase_by_uuid_constant(records: tuple[Record, ...], phase: str) -> dict[str, str]:
    """Stamp every genuine user prompt record's uuid with the same phase label."""
    result: dict[str, str] = {}
    for record in records:
        if not is_user_authored_prompt(record):
            continue
        if record.uuid is None:
            continue
        result[record.uuid] = phase
    return result


def _earliest_user_authored_timestamp(records: tuple[Record, ...]) -> datetime | None:
    """Return the earliest user-authored prompt timestamp in the records.

    Falls back to :func:`_earliest_timestamp` when no user-authored
    prompt exists.

    Args:
        records: Conversation records in load order.

    Returns:
        The timestamp, or ``None`` when no timestamped record exists.
    """
    earliest: datetime | None = None
    for record in records:
        if record.timestamp is None:
            continue
        if not is_user_authored_prompt(record):
            continue
        if earliest is None or record.timestamp < earliest:
            earliest = record.timestamp
    if earliest is not None:
        return earliest
    return _earliest_timestamp(records)


def _earliest_timestamp(records: tuple[Record, ...]) -> datetime | None:
    """Return the earliest timestamp across the records, or ``None`` when none carry one."""
    earliest: datetime | None = None
    for record in records:
        if record.timestamp is None:
            continue
        if earliest is None or record.timestamp < earliest:
            earliest = record.timestamp
    return earliest


def _collect_turns(views: tuple[ConversationView, ...]) -> tuple[Turn, ...]:
    """Derive turns for every conversation view and return them in global timestamp order."""
    all_turns: list[Turn] = []
    for view in views:
        all_turns.extend(derive_turns(view.conversation))
    all_turns.sort(key=lambda turn: turn.start_timestamp)
    return tuple(all_turns)
