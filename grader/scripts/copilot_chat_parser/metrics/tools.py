#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Tool-call metrics: success rate on terminal invocations, retry rate
across tool-call rounds, and user-edit rate.

``user_edit_rate`` is the share of terminal invocations where the user
modified the command in the edit-before-approve editor. An invocation
counts as a user edit when ``commandLine.userEdited`` is populated and
differs from ``commandLine.original``. The ``confirmation.commandLine``
field is a display artefact and does not always reflect what the shell
executed; terminal output from real sessions confirms that the
``userEdited`` form is what runs when the user approves the tool call.
"""

from __future__ import annotations

from typing import Any

from ..schema import (
    TOOL_CONFIRM_DENIED,
    TOOL_CONFIRM_SKIPPED,
    TerminalToolInvocation,
)

_NEVER_EXECUTED_CONFIRM_TYPES: frozenset[int] = frozenset(
    {TOOL_CONFIRM_DENIED, TOOL_CONFIRM_SKIPPED}
)
from ..session import Session


def compute_tool_success_rate(session: Session) -> dict[str, Any]:
    """Compute the share of terminal invocations with a zero exit code.

    Invocations that never executed are excluded from both the numerator
    and denominator. In the current VS Code UX those are invocations
    confirmed with ``Denied`` (``isConfirmed.type == 0``) or ``Skipped``
    (``isConfirmed.type == 5``).

    Args:
        session: The assembled session.

    Returns:
        A dict with ``tool_success_rate``, ``terminal_success_count``,
        and ``terminal_considered_count`` (the denominator). When the
        denominator is zero ``tool_success_rate`` is ``0.0``.
    """
    considered = [
        invocation
        for annotated in session.requests
        for invocation in annotated.raw.terminal_invocations
        if invocation.is_confirmed_type not in _NEVER_EXECUTED_CONFIRM_TYPES
    ]
    success_count = sum(1 for t in considered if t.exit_code == 0)
    denominator = len(considered)
    rate = success_count / denominator if denominator > 0 else 0.0
    return {
        "tool_success_rate": rate,
        "terminal_success_count": success_count,
        "terminal_considered_count": denominator,
    }


def compute_tool_retry_rate(session: Session) -> dict[str, Any]:
    """Compute the mean number of retries per tool-call round.

    Formula: ``sum(toolInputRetry) / number_of_rounds`` across every
    tool-call round of every request.

    Args:
        session: The assembled session.

    Returns:
        A dict with ``tool_retry_rate``, ``tool_retry_total``, and
        ``tool_rounds_count``. When the session has no tool-call rounds
        the rate is ``0.0``.
    """
    total_retries = 0
    total_rounds = 0
    for annotated in session.requests:
        for round_entry in annotated.raw.tool_call_rounds:
            total_rounds += 1
            total_retries += round_entry.tool_input_retry
    rate = total_retries / total_rounds if total_rounds > 0 else 0.0
    return {
        "tool_retry_rate": rate,
        "tool_retry_total": total_retries,
        "tool_rounds_count": total_rounds,
    }


def compute_user_edit_rate(session: Session) -> dict[str, Any]:
    """Compute the share of terminal invocations where the user edited the command.

    Invocations that never executed (``Denied`` type 0 or ``Skipped``
    type 5) are excluded from the denominator; no shell-side effect
    could be attributed to a user edit on them. All other confirmed
    invocations enter the denominator, including auto-approvals, which
    contribute zero to the numerator because the edit UI never appeared.

    Args:
        session: The assembled session.

    Returns:
        A dict with ``user_edit_rate``, ``user_edit_count``, and
        ``terminal_considered_count``. When the denominator is zero
        the rate is ``0.0``.
    """
    considered = [
        invocation
        for annotated in session.requests
        for invocation in annotated.raw.terminal_invocations
        if invocation.is_confirmed_type not in _NEVER_EXECUTED_CONFIRM_TYPES
    ]
    edit_count = sum(1 for t in considered if _is_user_edit(t))
    denominator = len(considered)
    rate = edit_count / denominator if denominator > 0 else 0.0
    return {
        "user_edit_rate": rate,
        "user_edit_count": edit_count,
        "terminal_considered_count": denominator,
    }


def _is_user_edit(invocation: TerminalToolInvocation) -> bool:
    """Return ``True`` when the user typed a non-trivial change into the edit UI."""
    user_edited = invocation.command_user_edited
    if user_edited is None:
        return False
    return user_edited.strip() != invocation.command_original.strip()
