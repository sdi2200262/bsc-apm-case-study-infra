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

Two responsibilities sit here above the per-conversation work the
loader does:

1. Detect each conversation's role from its first slash command (APM
   only) and assign role keys. Roles are numbered sequentially by
   first-record timestamp ascending, with no parsing of participant-
   supplied identifiers. The reasoning is that participants type
   worker identifiers by hand on ``/apm-3-initiate-worker <id>``;
   typos in re-invocations would split what is semantically the same
   worker into two distinct keys (``frontend-agent`` and
   ``fronend-agent``) if the parser tried to use the participant's id.
   Sequential numbering avoids the trap; the verbatim first command of
   each conversation is preserved per file so a downstream reviewer
   can spot two role-keys with similar-but-typo-different first
   commands and decide whether to merge them.

2. Assign a phase label to every record that participates in
   per-prompt phase aggregation. The two frameworks use different
   phase models:

   * APM: phase is a property of the conversation's role. A Planner
     conversation is entirely planning; a Manager or Worker
     conversation is entirely implementation. The mapping is fixed
     per file and stamped onto every prompt in that file.

   * Spec-kit: phase is per-prompt and follows a forward-only
     ratchet. The ratchet starts at ``other`` and advances along
     ``other`` -> ``planning`` -> ``implementation``. Three event
     populations feed the ratchet: genuine user-prompt records,
     the enqueue records of delivered user-authored steers, and
     assistant ``Skill`` tool_use blocks whose declared skill is
     a recognised Spec-kit phase command (the model self-invoking
     a skill). All three are merge-sorted by timestamp; a prompt,
     steer, or Skill tool_use carrying a recognised command takes
     that command's phase as its own. The ratchet advances only
     when the command's phase index is strictly greater than the
     current ratchet index; a prompt with no recognised command
     inherits the ratchet. Once implementation has begun,
     individual planning commands count their own prompt as
     planning but do not move the ratchet back. For a Skill
     tool_use, the declared phase is tagged onto the triggering
     assistant record and onto every record in the same
     conversation file sharing its ``requestId`` (the full
     streaming response of that API call), so the implementation
     work the model performs after self-invoking the skill is
     accounted for in the ratchet's output rather than left at
     the prior phase. Backward Skill tool_uses (declared phase
     behind the ratchet) still tag the request group but do not
     move the ratchet back; the parser surfaces them in the
     diagnostics block so a reviewer can see how often the model
     reaches back into planning while implementing. For a spec-kit
     submission with more than one conversation file (uncommon,
     but possible if a participant diverges), the ratchet is
     session-scoped, not per-conversation: events from all files
     are merge-sorted by timestamp and the ratchet advances over
     the global stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .commands import (
    APM_PHASE_BY_ROLE,
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
    PHASE_OTHER,
    ROLE_UNASSIGNED,
    extract_command_names,
    role_from_initiate_command,
)
from .loader import (
    Conversation,
    discover_conversation_files,
    load_conversation,
)
from .phase_walker import assign_speckit_phases
from .schema import (
    Record,
    SchemaError,
    user_prompt_text,
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
        phase_by_record_uuid: Phase label keyed by record uuid, covering
            three populations: genuine user prompt records that
            participate in the per-prompt phase aggregation, the enqueue
            records of delivered user-authored steers, and assistant
            records grouped by ``requestId`` around a ``Skill`` tool_use
            naming a Spec-kit phase command (the triggering record and
            every same-``requestId`` record share the Skill's declared
            phase). Other record types inherit phase from their
            containing turn at metric time.
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
        backward_skill_invocations: One entry per assistant Skill
            tool_use whose declared Spec-kit phase sits behind the
            ratchet at the moment the event arrives, in chronological
            order. Each entry has keys ``record_uuid``, ``timestamp``
            (ISO string), ``skill`` (the Spec-kit command name), and
            ``ratchet_phase_at_event`` (the ratchet phase observed
            when the event arrived). Empty tuple for APM sessions and
            for Spec-kit sessions with no backward Skill invocations.
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

    Each conversation's role is derived from its first recognised
    slash command. Conversations are then numbered sequentially per
    role kind by their earliest record timestamp ascending so that
    handoffs produce ``manager-2``, ``manager-3`` and parallel workers
    produce ``worker-1``, ``worker-2`` in chronological order.
    """
    initial: list[tuple[Conversation, str, str, Record | None, datetime | None]] = []
    for conversation in conversations:
        first_command, first_record = _first_slash_command(conversation)
        base_role = role_from_initiate_command(first_command) if first_command else ROLE_UNASSIGNED
        initial.append((
            conversation,
            base_role,
            first_command,
            first_record,
            _earliest_user_authored_timestamp(conversation.records),
        ))
    initial.sort(key=lambda item: (item[4] is None, item[4]))
    counters: dict[str, int] = {}
    views: list[ConversationView] = []
    for conversation, base_role, first_command, first_record, first_ts in initial:
        counters[base_role] = counters.get(base_role, 0) + 1
        role_key = f"{base_role}-{counters[base_role]}"
        phase_by_uuid = _phase_by_uuid_apm_walker(conversation.records, base_role)
        views.append(ConversationView(
            conversation=conversation,
            role=role_key,
            first_command=first_command,
            first_command_record=first_record,
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
        first_command, first_record = _first_slash_command(conversation)
        initial.append((
            conversation,
            first_command,
            first_record,
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


def _phase_by_uuid_apm_walker(records: tuple[Record, ...], base_role: str) -> dict[str, str]:
    """Return a mapping of prompt UUID to phase for an APM conversation.

    Walks the records sequentially. Every genuine user prompt is
    assigned ``PHASE_OTHER`` until a role-initiating command is
    found. Once an initiator appears, that prompt and every
    subsequent prompt in the conversation are assigned to the
    real phase associated with ``base_role``.
    """
    result: dict[str, str] = {}
    current_phase = PHASE_OTHER
    real_phase = APM_PHASE_BY_ROLE.get(base_role, PHASE_OTHER)

    for record in records:
        if not is_user_authored_prompt(record):
            continue
        if record.uuid is None:
            continue

        if current_phase == PHASE_OTHER:
            for command in extract_command_names(user_prompt_text(record)):
                if role_from_initiate_command(command) != ROLE_UNASSIGNED:
                    current_phase = real_phase
                    break

        result[record.uuid] = current_phase
    return result


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


def _first_slash_command(conversation: Conversation) -> tuple[str, Record | None]:
    """Return the first role-initiating framework command in a conversation.

    Walks the conversation's records in document order. The first
    genuine user prompt that carries an APM role-initiating command
    (``apm-1/2/3``) defines the conversation's role. Commands that
    precede the initiator (including recovery or status commands)
    do not trigger role assignment; those conversations remain
    unassigned until an initiator is encountered. Claude Code
    built-ins are ignored. When no initiator appears anywhere in the
    conversation, returns an empty string and ``None``.
    """
    for record in conversation.records:
        if not is_user_authored_prompt(record):
            continue
        for command in extract_command_names(user_prompt_text(record)):
            if role_from_initiate_command(command) != ROLE_UNASSIGNED:
                return command, record
    return "", None


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
