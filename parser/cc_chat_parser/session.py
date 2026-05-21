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
     ``other`` -> ``planning`` -> ``implementation``. A prompt
     carrying a recognised Spec-kit command takes that command's
     phase as its own; the ratchet advances only when the command's
     phase index is strictly greater than the current ratchet index.
     A prompt with no recognised command inherits the ratchet. Once
     implementation has begun, individual planning commands count
     their own prompt as planning but do not move the ratchet back.
     For a spec-kit submission with more than one conversation file
     (uncommon, but possible if a participant diverges), the ratchet
     is session-scoped, not per-conversation: prompts from all files
     are merge-sorted by timestamp and the ratchet advances over the
     global stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .commands import (
    APM_PHASE_BY_ROLE,
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
    PHASE_OTHER,
    ROLE_UNASSIGNED,
    classify_command,
    extract_command_names,
    phase_index,
    role_from_initiate_command,
    speckit_command_phase,
)
from .loader import (
    STEER_FATE_DELIVERED,
    Conversation,
    discover_conversation_files,
    load_conversation,
)
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
        first_record_timestamp: Earliest timestamp across the
            conversation's records. Used to order conversations for
            sequential role numbering.
        phase_by_record_uuid: Phase label keyed by record uuid, only
            populated for genuine user prompt records that participate
            in the per-prompt phase aggregation. Other record types
            inherit phase from their containing turn at metric time.
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
    """

    framework: str
    views: tuple[ConversationView, ...]
    turns: tuple[Turn, ...]


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
    if framework == FRAMEWORK_APM:
        views = _build_apm_views(conversations)
    else:
        views = _build_speckit_views(conversations)
    turns = _collect_turns(views)
    return Session(framework=framework, views=views, turns=turns)


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
            _earliest_timestamp(conversation.records),
        ))
    initial.sort(key=lambda item: (item[4] is None, item[4]))
    counters: dict[str, int] = {}
    views: list[ConversationView] = []
    for conversation, base_role, first_command, first_record, first_ts in initial:
        counters[base_role] = counters.get(base_role, 0) + 1
        role_key = f"{base_role}-{counters[base_role]}"
        phase = APM_PHASE_BY_ROLE.get(base_role, PHASE_OTHER)
        phase_by_uuid = _phase_by_uuid_constant(conversation.records, phase)
        views.append(ConversationView(
            conversation=conversation,
            role=role_key,
            first_command=first_command,
            first_command_record=first_record,
            first_record_timestamp=first_ts,
            phase_by_record_uuid=phase_by_uuid,
        ))
    return tuple(views)


def _build_speckit_views(conversations: list[Conversation]) -> tuple[ConversationView, ...]:
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
            _earliest_timestamp(conversation.records),
        ))
    initial.sort(key=lambda item: (item[3] is None, item[3]))
    phase_by_uuid_global = _ratchet_phase_assignments(conversations)
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
    return tuple(views)


def _ratchet_phase_assignments(conversations: list[Conversation]) -> dict[str, str]:
    """Run the Spec-kit phase ratchet over a globally-sorted prompt stream.

    The stream merges two populations: genuine user-prompt records
    and the enqueue records of delivered user-authored steers.
    Including delivered steers is required because Claude Code
    writes a steer's content only on the queue-operation enqueue
    record; when the steer is dequeued, its content goes directly
    into the model's context with no synthesised user-prompt
    record to carry it. Without the enqueue records in the stream,
    the ratchet would never see slash commands the participant
    typed mid-turn.

    The ratchet maintains a session-scoped current phase that
    advances forward only along ``other`` -> ``planning`` ->
    ``implementation``. A prompt or steer carrying a Spec-kit
    command takes that command's phase as its own; the ratchet
    advances only when the command's phase index is strictly
    greater than the current ratchet index. Surgical commands
    behind the ratchet count their own prompt as the command's
    phase but do not move the ratchet back. Tiebreak on equal
    timestamps is deterministic on ``(session_id, parent_uuid,
    uuid)`` so the ratchet's output does not depend on input
    iteration order.

    Returns a map keyed by record uuid for genuine user-prompt
    records and by enqueue record uuid for delivered steer
    enqueues. Both populations contribute to the ratchet but only
    the genuine prompt records' phases feed the per-record phase
    lookup the rest of the parser uses; the steer-enqueue entries
    are kept in the same map so the diagnostics layer can audit
    what the ratchet saw.
    """
    prompt_entries: list[tuple[Record, str]] = []
    for conversation in conversations:
        for record in conversation.records:
            if not is_user_authored_prompt(record):
                continue
            if record.timestamp is None or record.uuid is None:
                continue
            prompt_entries.append((record, user_prompt_text(record)))
        for event in conversation.steer_events:
            if not event.is_user_authored or event.fate != STEER_FATE_DELIVERED:
                continue
            enqueue = event.enqueue_record
            if enqueue.timestamp is None or enqueue.uuid is None:
                continue
            content = enqueue.payload.get("content")
            if not isinstance(content, str):
                content = ""
            prompt_entries.append((enqueue, content))
    prompt_entries.sort(
        key=lambda entry: (
            entry[0].timestamp,
            entry[0].session_id or "",
            entry[0].parent_uuid or "",
            entry[0].uuid or "",
        )
    )
    current_phase = PHASE_OTHER
    phase_by_uuid: dict[str, str] = {}
    for record, text in prompt_entries:
        commands = extract_command_names(text)
        speckit_phases = [
            phase
            for command in commands
            for phase in (speckit_command_phase(command),)
            if phase is not None
        ]
        if speckit_phases:
            prompt_phase = speckit_phases[0]
            if phase_index(prompt_phase) > phase_index(current_phase):
                current_phase = prompt_phase
            phase_by_uuid[record.uuid] = prompt_phase
        else:
            phase_by_uuid[record.uuid] = current_phase
    return phase_by_uuid


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
    """Return the verbatim first framework command in a conversation.

    Walks the conversation's records in document order. The first
    genuine user prompt that carries at least one APM or Spec-kit
    command in its ``<command-name>`` markers contributes the first
    such command as the conversation's first command. Claude Code
    built-ins such as ``/clear``, ``/exit``, ``/usage``, ``/compact``,
    and ``/model`` are skipped: they are platform vocabulary, not
    framework participation, and would mis-classify a Manager or
    Worker conversation as unassigned simply because the participant
    issued a built-in before the framework command. When no framework
    command appears anywhere in the conversation, the empty string
    and ``None`` are returned and the caller assigns the unassigned
    role.
    """
    for record in conversation.records:
        if not is_user_authored_prompt(record):
            continue
        for command in extract_command_names(user_prompt_text(record)):
            if classify_command(command):
                return command, record
    return "", None


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
