#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Typed accessors for the VS Code Copilot chat export schema (tag 1.116.0).

The accessors here read exact fields of the exported JSON. They do not
tolerate missing required fields or legacy shapes; a mismatch raises
``SchemaError`` that names the file and request index so the caller can
point at the broken record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PLANNER_ROLE = "planner"
MANAGER_ROLE = "manager"
WORKER_ROLE = "worker"
UNASSIGNED_ROLE = "unassigned"

PLANNING_PHASE = "planning"
IMPLEMENTATION_PHASE = "implementation"
OTHER_PHASE = "other"

FRAMEWORK_APM = "apm"
FRAMEWORK_SPECKIT = "speckit"
FRAMEWORK_UNKNOWN = "unknown"

TOOL_CONFIRM_DENIED = 0
TOOL_CONFIRM_CONFIRMATION_NOT_NEEDED = 1
TOOL_CONFIRM_SETTING = 2
TOOL_CONFIRM_LM_SERVICE_PER_TOOL = 3
TOOL_CONFIRM_USER_ACTION = 4
TOOL_CONFIRM_SKIPPED = 5

RESPONSE_STATE_PENDING = 0
RESPONSE_STATE_COMPLETE = 1
RESPONSE_STATE_CANCELLED = 2
RESPONSE_STATE_FAILED = 3
RESPONSE_STATE_NEEDS_INPUT = 4


class SchemaError(Exception):
    """Raised when an export file does not match the expected shape."""


@dataclass(frozen=True)
class SlashCommand:
    """A structured slash-command invocation parsed from ``message.parts[]``.

    Attributes:
        name: The command stem after the slash, exactly as written in the
            export (for example ``apm-1-initiate-planner`` or
            ``speckit.specify``).
    """

    name: str


@dataclass(frozen=True)
class ToolCallRound:
    """One round of tool calls inside a request's agent loop.

    Attributes:
        tool_input_retry: Number of times the agent re-called a tool with
            adjusted arguments within this round.
        phase_model_id: The model identifier the round ran on, or ``None``
            when the field is absent.
    """

    tool_input_retry: int
    phase_model_id: str | None


@dataclass(frozen=True)
class TerminalToolInvocation:
    """A terminal tool invocation extracted from a request's response stream.

    The fields below are the only ones the parser consumes. Other
    terminal-tool kinds (input, subagent, resources, ...) are ignored at
    parse time and do not appear as instances of this class.

    Attributes:
        is_confirmed_type: Value of the ``ToolConfirmKind`` enum
            (0 Denied, 1 ConfirmationNotNeeded, 2 Setting,
            3 LmServicePerTool, 4 UserAction, 5 Skipped).
        command_original: The command line the model proposed.
        command_user_edited: The command text that was in the edit-before-
            approve editor at serialization, if the user typed anything;
            ``None`` when the field was not populated. When the user
            approves the invocation, this is what runs.
        exit_code: The process exit code after execution, or ``None`` when
            execution did not reach a terminal state.
    """

    is_confirmed_type: int
    command_original: str
    command_user_edited: str | None
    exit_code: int | None


@dataclass(frozen=True)
class RawRequest:
    """One request parsed from the export, before session-level annotation.

    Attributes:
        conversation_file: Absolute path of the source JSON file.
        request_index: Zero-based position within the source file.
        timestamp_ms: User-send time in milliseconds since epoch.
        completed_at_ms: Agent-response completion time in milliseconds
            since epoch, or ``None`` when the response never reached a
            terminal state.
        model_state_value: The response's ``modelState.value`` enum.
        message_text: Concatenated text of all ``text`` parts in the
            message.
        slash_commands: Slash-command invocations found in
            ``message.parts[]`` in document order.
        terminal_invocations: Terminal tool invocations found in
            ``response[]`` in document order.
        tool_call_rounds: Tool-call rounds found in
            ``result.metadata.toolCallRounds``.
    """

    conversation_file: str
    request_index: int
    timestamp_ms: int
    completed_at_ms: int | None
    model_state_value: int
    message_text: str
    slash_commands: tuple[SlashCommand, ...]
    terminal_invocations: tuple[TerminalToolInvocation, ...]
    tool_call_rounds: tuple[ToolCallRound, ...]


def parse_request(
    raw: dict[str, Any],
    conversation_file: str,
    request_index: int,
) -> RawRequest:
    """Parse one request object from the export JSON.

    Args:
        raw: Single entry from ``requests[]`` in the export.
        conversation_file: Path of the source file for error reporting.
        request_index: Position within the source file for error reporting.

    Returns:
        A populated ``RawRequest``.

    Raises:
        SchemaError: When a required field is missing or has the wrong
            type.
    """
    timestamp_ms = _require_int(raw, "timestamp", conversation_file, request_index)
    model_state = _require_dict(raw, "modelState", conversation_file, request_index)
    model_state_value = _require_int(
        model_state, "value", conversation_file, request_index, field_label="modelState.value"
    )

    completed_at_ms: int | None
    if model_state_value in (
        RESPONSE_STATE_COMPLETE,
        RESPONSE_STATE_CANCELLED,
        RESPONSE_STATE_FAILED,
    ):
        completed_at_ms = _require_int(
            model_state,
            "completedAt",
            conversation_file,
            request_index,
            field_label="modelState.completedAt",
        )
    else:
        completed_at_ms = None

    message = _require_dict(raw, "message", conversation_file, request_index)
    parts = _require_list(message, "parts", conversation_file, request_index, field_label="message.parts")

    message_text = "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "text"
    )

    slash_commands = tuple(
        SlashCommand(name=str(part["name"]))
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "prompt" and isinstance(part.get("name"), str)
    )

    response_items = raw.get("response") or []
    if not isinstance(response_items, list):
        raise SchemaError(
            f"{conversation_file} request {request_index}: response is not a list"
        )
    terminal_invocations = tuple(
        _parse_terminal_invocation(item)
        for item in response_items
        if _is_terminal_invocation(item)
    )

    rounds_source: list[dict[str, Any]] = []
    result = raw.get("result")
    if isinstance(result, dict):
        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            rounds_raw = metadata.get("toolCallRounds")
            if rounds_raw is not None and not isinstance(rounds_raw, list):
                raise SchemaError(
                    f"{conversation_file} request {request_index}: "
                    "result.metadata.toolCallRounds is not a list"
                )
            rounds_source = rounds_raw or []

    tool_call_rounds = tuple(_parse_tool_round(entry) for entry in rounds_source)

    return RawRequest(
        conversation_file=conversation_file,
        request_index=request_index,
        timestamp_ms=timestamp_ms,
        completed_at_ms=completed_at_ms,
        model_state_value=model_state_value,
        message_text=message_text,
        slash_commands=slash_commands,
        terminal_invocations=terminal_invocations,
        tool_call_rounds=tool_call_rounds,
    )


def parse_export(data: dict[str, Any], conversation_file: str) -> list[RawRequest]:
    """Parse a full export object into a list of ``RawRequest``.

    Args:
        data: The decoded JSON object from one conversation file.
        conversation_file: Path of the source file, used for error
            reporting on any malformed request.

    Returns:
        Parsed requests in the same order they appear in the export.

    Raises:
        SchemaError: On any shape mismatch.
    """
    requests_raw = data.get("requests")
    if not isinstance(requests_raw, list):
        raise SchemaError(f"{conversation_file}: top-level 'requests' is missing or not a list")
    return [
        parse_request(entry, conversation_file, index)
        for index, entry in enumerate(requests_raw)
    ]


def _is_terminal_invocation(item: Any) -> bool:
    """Return ``True`` when the response item is a completed terminal tool call."""
    if not isinstance(item, dict):
        return False
    if item.get("kind") != "toolInvocationSerialized":
        return False
    tool_specific = item.get("toolSpecificData")
    if not isinstance(tool_specific, dict):
        return False
    return tool_specific.get("kind") == "terminal"


def _parse_terminal_invocation(item: dict[str, Any]) -> TerminalToolInvocation:
    """Translate one terminal tool-invocation entry into a dataclass."""
    tool_specific: dict[str, Any] = item["toolSpecificData"]
    confirmed = item.get("isConfirmed")
    if not isinstance(confirmed, dict) or "type" not in confirmed:
        raise SchemaError("terminal tool invocation missing isConfirmed.type")
    is_confirmed_type = int(confirmed["type"])

    command_line = tool_specific.get("commandLine")
    if not isinstance(command_line, dict) or "original" not in command_line:
        raise SchemaError("terminal tool invocation missing commandLine.original")
    command_original = str(command_line["original"])

    user_edited_raw = command_line.get("userEdited")
    command_user_edited = str(user_edited_raw) if isinstance(user_edited_raw, str) else None

    state = tool_specific.get("terminalCommandState")
    if isinstance(state, dict) and isinstance(state.get("exitCode"), int):
        exit_code: int | None = state["exitCode"]
    else:
        exit_code = None

    return TerminalToolInvocation(
        is_confirmed_type=is_confirmed_type,
        command_original=command_original,
        command_user_edited=command_user_edited,
        exit_code=exit_code,
    )


def _parse_tool_round(entry: Any) -> ToolCallRound:
    """Translate one ``toolCallRounds[]`` entry into a dataclass."""
    if not isinstance(entry, dict):
        raise SchemaError("toolCallRounds entry is not an object")
    retry = entry.get("toolInputRetry", 0)
    if not isinstance(retry, int):
        raise SchemaError("toolCallRounds entry has non-integer toolInputRetry")
    phase_model_id_raw = entry.get("phaseModelId")
    phase_model_id = phase_model_id_raw if isinstance(phase_model_id_raw, str) else None
    return ToolCallRound(tool_input_retry=retry, phase_model_id=phase_model_id)


def _require_dict(
    source: dict[str, Any],
    key: str,
    conversation_file: str,
    request_index: int,
    field_label: str | None = None,
) -> dict[str, Any]:
    """Return a nested dict, raising ``SchemaError`` if it is missing or wrong type."""
    label = field_label or key
    value = source.get(key)
    if not isinstance(value, dict):
        raise SchemaError(
            f"{conversation_file} request {request_index}: "
            f"{label} is missing or not an object"
        )
    return value


def _require_list(
    source: dict[str, Any],
    key: str,
    conversation_file: str,
    request_index: int,
    field_label: str | None = None,
) -> list[Any]:
    """Return a nested list, raising ``SchemaError`` if it is missing or wrong type."""
    label = field_label or key
    value = source.get(key)
    if not isinstance(value, list):
        raise SchemaError(
            f"{conversation_file} request {request_index}: "
            f"{label} is missing or not a list"
        )
    return value


def _require_int(
    source: dict[str, Any],
    key: str,
    conversation_file: str,
    request_index: int,
    field_label: str | None = None,
) -> int:
    """Return a nested integer, raising ``SchemaError`` if it is missing or wrong type."""
    label = field_label or key
    value = source.get(key)
    if not isinstance(value, int):
        raise SchemaError(
            f"{conversation_file} request {request_index}: "
            f"{label} is missing or not an integer"
        )
    return value
