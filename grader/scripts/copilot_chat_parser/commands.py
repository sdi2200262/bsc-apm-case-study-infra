#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Known APM and Spec-kit slash commands, with role and phase lookups.

The tables here are the authoritative ground truth for the parser's
phase and role classifiers. APM commands come from the APM documentation
at ``agentic-project-management.dev`` (Getting Started, Quick Reference,
Introduction). Spec-kit commands come from the Spec Kit quickstart.
"""

from __future__ import annotations

from .schema import (
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
    FRAMEWORK_UNKNOWN,
    IMPLEMENTATION_PHASE,
    MANAGER_ROLE,
    OTHER_PHASE,
    PLANNER_ROLE,
    PLANNING_PHASE,
    SlashCommand,
    UNASSIGNED_ROLE,
    WORKER_ROLE,
)

APM_PHASE_BY_COMMAND: dict[str, str] = {
    "apm-1-initiate-planner": PLANNING_PHASE,
    "apm-2-initiate-manager": IMPLEMENTATION_PHASE,
    "apm-3-initiate-worker": IMPLEMENTATION_PHASE,
    "apm-4-check-tasks": IMPLEMENTATION_PHASE,
    "apm-5-check-reports": IMPLEMENTATION_PHASE,
    "apm-6-handoff-manager": IMPLEMENTATION_PHASE,
    "apm-7-handoff-worker": IMPLEMENTATION_PHASE,
    "apm-8-summarize-session": OTHER_PHASE,
    "apm-9-recover": OTHER_PHASE,
}

APM_ROLE_BY_INITIATE_COMMAND: dict[str, str] = {
    "apm-1-initiate-planner": PLANNER_ROLE,
    "apm-2-initiate-manager": MANAGER_ROLE,
    "apm-3-initiate-worker": WORKER_ROLE,
}

SPECKIT_PHASE_BY_COMMAND: dict[str, str] = {
    "speckit.constitution": PLANNING_PHASE,
    "speckit.specify": PLANNING_PHASE,
    "speckit.clarify": PLANNING_PHASE,
    "speckit.plan": PLANNING_PHASE,
    "speckit.tasks": PLANNING_PHASE,
    "speckit.checklist": PLANNING_PHASE,
    "speckit.analyze": IMPLEMENTATION_PHASE,
    "speckit.implement": IMPLEMENTATION_PHASE,
}


def command_framework(command: SlashCommand) -> str:
    """Return the framework a slash command belongs to.

    Args:
        command: Slash-command invocation parsed from ``message.parts[]``.

    Returns:
        ``FRAMEWORK_APM`` when the command name starts with ``apm-``,
        ``FRAMEWORK_SPECKIT`` when it starts with ``speckit.``, otherwise
        ``FRAMEWORK_UNKNOWN``.
    """
    name = command.name
    if name.startswith("apm-"):
        return FRAMEWORK_APM
    if name.startswith("speckit."):
        return FRAMEWORK_SPECKIT
    return FRAMEWORK_UNKNOWN


def command_phase(command: SlashCommand) -> str | None:
    """Return the framework phase for a slash command, or ``None`` when unknown.

    Args:
        command: Slash-command invocation parsed from ``message.parts[]``.

    Returns:
        One of ``PLANNING_PHASE``, ``IMPLEMENTATION_PHASE``,
        ``OTHER_PHASE`` for a command in the known tables; ``None`` for
        any command name not present in either table.
    """
    if command.name in APM_PHASE_BY_COMMAND:
        return APM_PHASE_BY_COMMAND[command.name]
    if command.name in SPECKIT_PHASE_BY_COMMAND:
        return SPECKIT_PHASE_BY_COMMAND[command.name]
    return None


def role_from_first_command(command: SlashCommand) -> str:
    """Resolve a conversation's role from its first APM slash command.

    Args:
        command: The first slash-command invocation in a conversation
            file's first request.

    Returns:
        ``PLANNER_ROLE``, ``MANAGER_ROLE``, or ``WORKER_ROLE`` when the
        command is one of the three role-initiating commands. Any other
        APM command (``apm-4-check-tasks``, handoff, summarize, recover)
        is not a role initiator and resolves to ``UNASSIGNED_ROLE``.
    """
    return APM_ROLE_BY_INITIATE_COMMAND.get(command.name, UNASSIGNED_ROLE)


def first_slash_command(commands: tuple[SlashCommand, ...]) -> SlashCommand | None:
    """Return the first slash command in a tuple, or ``None`` when empty.

    Args:
        commands: Slash commands parsed from a single request.

    Returns:
        The first element of the tuple, or ``None`` when the tuple is
        empty.
    """
    return commands[0] if commands else None
