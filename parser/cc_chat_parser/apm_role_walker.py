#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Derive APM conversation roles and per-record phases.

The APM counterpart to :mod:`speckit_phase_walker`. Where the
Spec-kit walker runs a per-prompt phase ratchet, APM phase is
role-derived: each conversation file carries exactly one role, and
that role fixes the phase for the whole conversation (a Planner
conversation is planning; Manager and Worker conversations are
implementation). The records before the role is initiated are
``other``.

The conversation's role is the role of the first role-initiating
command (``apm-1/2/3``) the participant types in it. Roles are not
numbered here: the sequential suffix (``planner-1``) depends on
cross-conversation ordering and is applied at session assembly. The
verbatim first command is preserved per conversation so a downstream
reviewer can spot two role-keys with similar-but-typo-different first
commands and decide whether to merge them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .commands import (
    APM_PHASE_BY_ROLE,
    PHASE_OTHER,
    ROLE_UNASSIGNED,
    extract_command_names,
    role_from_initiate_command,
)
from .loader import Conversation
from .schema import (
    Record,
    user_prompt_text,
)
from .user_prompts import is_user_authored_prompt


@dataclass(frozen=True)
class ConversationRole:
    """Role determination for a single APM conversation file.

    Attributes:
        base_role: The role kind the conversation initiates
            (``planner``, ``manager``, ``worker``) or
            ``unassigned`` when no role-initiating command appears.
            The sequential suffix (``planner-1``) is applied later,
            at session assembly, since it depends on
            cross-conversation ordering.
        first_command: Verbatim first role-initiating slash command
            the participant typed, including arguments, typos, and
            whitespace as written. Empty string when no role-initiating
            command appears in the conversation.
        first_command_record: The user record carrying
            ``first_command``, or ``None`` when there is none.
    """

    base_role: str
    first_command: str
    first_command_record: Record | None


@dataclass(frozen=True)
class ApmRoleResult:
    """Output of :func:`assign_apm_roles`.

    Attributes:
        conversation_roles: Per-conversation role determinations,
            aligned positionally to the ``conversations`` passed to
            :func:`assign_apm_roles`.
        phase_by_uuid: Phase label keyed by record uuid, merged
            across every conversation. Each genuine user-prompt
            record maps to ``other`` before its conversation's role
            is initiated and to the role's phase from the initiating
            command onward.
    """

    conversation_roles: tuple[ConversationRole, ...]
    phase_by_uuid: dict[str, str]


def assign_apm_roles(conversations: list[Conversation]) -> ApmRoleResult:
    """Determine each APM conversation's role and per-record phase.

    Each conversation is treated independently: its role is the role
    of the first role-initiating command in record order, and every
    genuine user-prompt record is phased ``other`` until that command
    and the role's phase thereafter.

    Args:
        conversations: The conversation files of one APM submission.

    Returns:
        An :class:`ApmRoleResult` whose ``conversation_roles`` align
        positionally to ``conversations`` and whose ``phase_by_uuid``
        merges every conversation's per-record phase mapping.
    """
    roles: list[ConversationRole] = []
    phase_by_uuid: dict[str, str] = {}
    for conversation in conversations:
        first_command, first_record = _first_role_command(conversation)
        base_role = (
            role_from_initiate_command(first_command)
            if first_command
            else ROLE_UNASSIGNED
        )
        roles.append(ConversationRole(
            base_role=base_role,
            first_command=first_command,
            first_command_record=first_record,
        ))
        phase_by_uuid.update(_phase_by_uuid(conversation.records, base_role))
    return ApmRoleResult(
        conversation_roles=tuple(roles),
        phase_by_uuid=phase_by_uuid,
    )


def _first_role_command(conversation: Conversation) -> tuple[str, Record | None]:
    """Return the first role-initiating framework command in a conversation.

    Walks the conversation's records in document order. The first
    genuine user prompt that carries an APM role-initiating command
    (``apm-1/2/3``) defines the conversation's role. Commands that
    precede the initiator (including recovery or status commands) do
    not trigger role assignment; those conversations remain
    unassigned until an initiator is encountered. Claude Code
    built-ins are ignored. When no initiator appears anywhere in the
    conversation, returns an empty string and ``None``.

    Args:
        conversation: The conversation to scan.

    Returns:
        A pair ``(first_command, first_command_record)``; ``("", None)``
        when no role-initiating command appears.
    """
    for record in conversation.records:
        if not is_user_authored_prompt(record):
            continue
        for command in extract_command_names(user_prompt_text(record)):
            if role_from_initiate_command(command) != ROLE_UNASSIGNED:
                return command, record
    return "", None


def _phase_by_uuid(records: tuple[Record, ...], base_role: str) -> dict[str, str]:
    """Return a mapping of prompt uuid to phase for an APM conversation.

    Walks the records sequentially. Every genuine user prompt is
    assigned ``other`` until a role-initiating command is found. Once
    an initiator appears, that prompt and every subsequent prompt in
    the conversation are assigned to the real phase associated with
    ``base_role``.

    Args:
        records: The conversation's records in document order.
        base_role: The conversation's role kind, mapping to the phase
            via :data:`commands.APM_PHASE_BY_ROLE`.

    Returns:
        A mapping of genuine user-prompt record uuid to phase label.
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
