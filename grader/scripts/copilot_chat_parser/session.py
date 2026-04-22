#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Session assembly: load multiple conversation files, annotate each request
with its conversation role and framework phase, merge into a single
timestamp-ordered stream.

A session consists of one or more conversation files belonging to the
same participant session. APM sessions typically ship three or more
files (one per Planner, Manager, and each Worker conversation).
Spec-kit sessions typically ship a single file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .commands import (
    command_framework,
    command_phase,
    first_slash_command,
    role_from_first_command,
)
from .schema import (
    FRAMEWORK_APM,
    FRAMEWORK_SPECKIT,
    FRAMEWORK_UNKNOWN,
    OTHER_PHASE,
    RawRequest,
    SchemaError,
    UNASSIGNED_ROLE,
    parse_export,
)


@dataclass(frozen=True)
class AnnotatedRequest:
    """A request enriched with per-conversation role, framework, and phase.

    Attributes:
        raw: The underlying ``RawRequest`` from the export.
        role: Conversation role (``planner``, ``manager``, ``worker``, or
            ``unassigned``). Always ``unassigned`` for Spec-kit and for
            conversations whose first command is not an APM role
            initiator.
        framework: Framework label (``apm``, ``speckit``, or ``unknown``)
            of the conversation file this request belongs to.
        phase: Framework phase (``planning``, ``implementation``, or
            ``other``) resolved against this request's conversation
            history.
    """

    raw: RawRequest
    role: str
    framework: str
    phase: str


@dataclass(frozen=True)
class ConversationSummary:
    """Summary information about a loaded conversation file.

    Attributes:
        path: Absolute path of the source file.
        framework: Framework label derived from the first slash command.
        role: Conversation role derived from the first APM slash command.
        request_count: Number of requests parsed from the file.
        unknown_commands: Tuple of slash-command names encountered in the
            file that did not match any entry in the APM or Spec-kit
            tables.
    """

    path: str
    framework: str
    role: str
    request_count: int
    unknown_commands: tuple[str, ...]


@dataclass(frozen=True)
class Session:
    """Assembled session across one or more conversation files.

    Attributes:
        requests: Every parsed request, sorted by ``timestamp_ms``, each
            annotated with its per-conversation role, framework, and
            phase.
        conversations: One summary entry per loaded conversation file,
            in input order.
        framework: Session-level framework label. ``apm`` when any
            conversation is APM; ``speckit`` when any conversation is
            Spec-kit and none are APM; ``unknown`` otherwise. A session
            that mixes APM and Spec-kit conversations is still labelled
            ``apm`` and the Spec-kit conversations remain tagged
            individually.
        model_ids: Sorted tuple of distinct ``phaseModelId`` values
            observed across every tool-call round of every request.
            Used for the model-pin consistency check.
    """

    requests: tuple[AnnotatedRequest, ...]
    conversations: tuple[ConversationSummary, ...]
    framework: str
    model_ids: tuple[str, ...]


def load_session(paths: Iterable[Path]) -> Session:
    """Load one or more conversation files and assemble an annotated session.

    Args:
        paths: Paths to conversation JSON files. Each file must be a
            valid VS Code Copilot chat export.

    Returns:
        A ``Session`` with requests sorted by timestamp and each request
        annotated with its per-conversation role, framework, and phase.

    Raises:
        SchemaError: If any file's shape does not match the expected
            export schema.
        OSError: If a file cannot be read.
        json.JSONDecodeError: If a file does not contain valid JSON.
    """
    conversations: list[ConversationSummary] = []
    annotated: list[AnnotatedRequest] = []
    model_id_set: set[str] = set()
    frameworks_seen: set[str] = set()

    for path in paths:
        resolved = Path(path).resolve()
        with resolved.open("r", encoding="utf-8") as source:
            data = json.load(source)
        raw_requests = parse_export(data, str(resolved))
        framework, role = _classify_conversation(raw_requests, str(resolved))
        frameworks_seen.add(framework)

        unknown: list[str] = []
        per_request_phase = _phase_per_request(raw_requests, unknown)

        for request, phase in zip(raw_requests, per_request_phase):
            annotated.append(
                AnnotatedRequest(raw=request, role=role, framework=framework, phase=phase)
            )
            for round_entry in request.tool_call_rounds:
                if round_entry.phase_model_id is not None:
                    model_id_set.add(round_entry.phase_model_id)

        conversations.append(
            ConversationSummary(
                path=str(resolved),
                framework=framework,
                role=role,
                request_count=len(raw_requests),
                unknown_commands=tuple(sorted(set(unknown))),
            )
        )

    annotated.sort(key=lambda annotated_request: annotated_request.raw.timestamp_ms)
    session_framework = _resolve_session_framework(frameworks_seen)

    return Session(
        requests=tuple(annotated),
        conversations=tuple(conversations),
        framework=session_framework,
        model_ids=tuple(sorted(model_id_set)),
    )


def _classify_conversation(
    raw_requests: list[RawRequest],
    conversation_file: str,
) -> tuple[str, str]:
    """Resolve the framework and role of a single conversation file.

    Args:
        raw_requests: Every request parsed from the file.
        conversation_file: Path of the file, used for error reporting.

    Returns:
        A ``(framework, role)`` tuple. Framework is derived from the
        first slash command encountered in any request (first request
        first). Role applies only to APM conversations; for Spec-kit and
        unknown-framework files it is ``unassigned``.

    Raises:
        SchemaError: If the conversation contains no slash command at
            all, which would prevent framework detection.
    """
    first_command = None
    for request in raw_requests:
        candidate = first_slash_command(request.slash_commands)
        if candidate is not None:
            first_command = candidate
            break
    if first_command is None:
        raise SchemaError(
            f"{conversation_file}: no slash command found in any request; "
            "framework and role cannot be determined"
        )
    framework = command_framework(first_command)
    if framework == FRAMEWORK_APM:
        role = role_from_first_command(first_command)
    else:
        role = UNASSIGNED_ROLE
    return framework, role


def _phase_per_request(
    raw_requests: list[RawRequest],
    unknown_commands_sink: list[str],
) -> list[str]:
    """Assign a phase label to every request in a conversation file.

    A request's phase is:
      * the phase of the first known slash command in that request, or
      * inherited from the previous request's phase, or
      * ``OTHER_PHASE`` when no prior request has a known command.

    Unknown slash commands (names not present in either phase table) do
    not drive phase assignment; their names are collected into
    ``unknown_commands_sink`` so the conversation summary can surface
    them.

    Args:
        raw_requests: Every request in the conversation, in document
            order.
        unknown_commands_sink: Mutable list that receives unknown
            slash-command names observed while walking the conversation.

    Returns:
        A list of phase labels, one per request, in the same order as
        the input.
    """
    phases: list[str] = []
    current_phase = OTHER_PHASE
    for request in raw_requests:
        request_phase: str | None = None
        for command in request.slash_commands:
            resolved_phase = command_phase(command)
            if resolved_phase is None:
                unknown_commands_sink.append(command.name)
                continue
            if request_phase is None:
                request_phase = resolved_phase
        if request_phase is not None:
            current_phase = request_phase
        phases.append(current_phase)
    return phases


def _resolve_session_framework(frameworks_seen: set[str]) -> str:
    """Resolve a single framework label for the whole session.

    Args:
        frameworks_seen: Set of per-conversation framework labels
            observed across the session's files.

    Returns:
        ``FRAMEWORK_APM`` if any conversation is APM; otherwise
        ``FRAMEWORK_SPECKIT`` if any conversation is Spec-kit; otherwise
        ``FRAMEWORK_UNKNOWN``.
    """
    if FRAMEWORK_APM in frameworks_seen:
        return FRAMEWORK_APM
    if FRAMEWORK_SPECKIT in frameworks_seen:
        return FRAMEWORK_SPECKIT
    return FRAMEWORK_UNKNOWN
