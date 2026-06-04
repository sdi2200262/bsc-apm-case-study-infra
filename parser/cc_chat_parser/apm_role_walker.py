#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Derive APM conversation roles and per-record phases.

The APM counterpart to :mod:`speckit_phase_walker`. APM phase is
role-derived: each conversation file carries one role, which fixes
the phase for the whole conversation (Planner is planning, Manager
and Worker are implementation), with records before the role is
initiated phased ``other``.

A role is initiated when its initiation skill loads, by either of two
mechanisms; the first by record order fixes the role:

1. The participant types the role command and Claude Code expands it
   (a ``<command-name>`` marker in a user prompt).
2. The model invokes the role skill through the ``Skill`` tool when
   the typed command did not expand (an assistant ``Skill`` tool_use).

The structural detection of a ``Skill`` tool_use is shared with the
Spec-kit walker through :func:`commands.skill_tool_use_name`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .commands import (
    APM_PHASE_BY_ROLE,
    PHASE_OTHER,
    ROLE_UNASSIGNED,
    extract_command_names,
    is_apm_role_skill_tool_use,
    role_from_initiate_command,
)
from .loader import Conversation
from .schema import (
    Record,
    assistant_content_blocks,
    user_prompt_text,
)
from .user_prompts import is_user_authored_prompt


@dataclass(frozen=True)
class ConversationRole:
    """Role determination for one APM conversation file.

    Attributes:
        base_role: The role kind initiated (``planner``, ``manager``,
            ``worker``) or ``unassigned``. The sequential suffix
            (``planner-1``) is applied at session assembly.
        first_command: The verbatim role-initiating command the
            participant typed, or ``""`` when the role was set by a
            model ``Skill`` invocation or no role was initiated.
        first_command_record: The record carrying ``first_command``,
            or ``None``.
    """

    base_role: str
    first_command: str
    first_command_record: Record | None


@dataclass(frozen=True)
class ApmRoleResult:
    """Output of :func:`assign_apm_roles`.

    Attributes:
        conversation_roles: Per-conversation roles, aligned
            positionally to the ``conversations`` argument.
        phase_by_uuid: Phase keyed by record uuid, merged across
            conversations; ``other`` before each conversation's role
            is initiated, the role's phase after.
    """

    conversation_roles: tuple[ConversationRole, ...]
    phase_by_uuid: dict[str, str]


def assign_apm_roles(conversations: list[Conversation]) -> ApmRoleResult:
    """Determine each APM conversation's role and per-record phase.

    Each conversation's role is that of its first initiation event in
    record order (a typed command or a model ``Skill`` invocation);
    its user prompts are phased ``other`` until that event and the
    role's phase after.

    Args:
        conversations: The conversation files of one APM submission.

    Returns:
        An :class:`ApmRoleResult` aligned to ``conversations``.
    """
    roles: list[ConversationRole] = []
    phase_by_uuid: dict[str, str] = {}
    for conversation in conversations:
        base_role, first_command, first_record, init_index = _first_role_initiation(conversation)
        roles.append(ConversationRole(
            base_role=base_role,
            first_command=first_command,
            first_command_record=first_record,
        ))
        phase_by_uuid.update(_phase_by_uuid(conversation.records, base_role, init_index))
    return ApmRoleResult(
        conversation_roles=tuple(roles),
        phase_by_uuid=phase_by_uuid,
    )


def _first_role_initiation(
    conversation: Conversation,
) -> tuple[str, str, Record | None, int | None]:
    """Locate a conversation's first role-initiation event and its role.

    Walks records in order. A role initiation is a user prompt
    carrying a role-initiating command (``apm-1/2/3``) or an assistant
    ``Skill`` tool_use naming one; the first by record order wins.

    Args:
        conversation: The conversation to scan.

    Returns:
        ``(base_role, first_command, first_command_record,
        init_index)``. For a ``Skill`` initiation ``first_command`` is
        ``""`` and the record ``None``. ``base_role`` is
        ``unassigned`` and ``init_index`` is ``None`` when no
        initiation occurs.
    """
    for index, record in enumerate(conversation.records):
        if is_user_authored_prompt(record):
            for command in extract_command_names(user_prompt_text(record)):
                role = role_from_initiate_command(command)
                if role != ROLE_UNASSIGNED:
                    return role, command, record, index
        for block in assistant_content_blocks(record):
            skill = is_apm_role_skill_tool_use(block)
            if skill is not None:
                return role_from_initiate_command(skill), "", None, index
    return ROLE_UNASSIGNED, "", None, None


def _phase_by_uuid(
    records: tuple[Record, ...], base_role: str, init_index: int | None
) -> dict[str, str]:
    """Map each genuine user-prompt uuid to its phase.

    Prompts before ``init_index`` are ``other``; from ``init_index``
    on they are ``base_role``'s phase. All ``other`` when
    ``init_index`` is ``None``.

    Args:
        records: The conversation's records in document order.
        base_role: The conversation's role kind.
        init_index: Record index of the initiation event, or ``None``.

    Returns:
        A mapping of user-prompt uuid to phase label.
    """
    result: dict[str, str] = {}
    real_phase = APM_PHASE_BY_ROLE.get(base_role, PHASE_OTHER)
    for index, record in enumerate(records):
        if not is_user_authored_prompt(record):
            continue
        if record.uuid is None:
            continue
        if init_index is not None and index >= init_index:
            result[record.uuid] = real_phase
        else:
            result[record.uuid] = PHASE_OTHER
    return result
