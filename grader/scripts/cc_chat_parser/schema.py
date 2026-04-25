#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Typed view over the Claude Code CLI JSONL rollout format.

Each line of a Claude Code JSONL file is one record. Records carry a
``type`` field identifying their kind (``assistant``, ``user``,
``attachment``, ``file-history-snapshot``, ``queue-operation``,
``system``, ``permission-mode``, ``last-prompt``). System records carry
a further ``subtype`` (``turn_duration``, ``api_error``,
``local_command``, ``compact_boundary``).

This module defines the record-type vocabulary as constants, the
``Record`` dataclass that wraps one parsed line with the fields the rest
of the package needs without giving up access to the underlying payload,
and a small set of pure helpers for extracting type-specific structures
from a record's payload (assistant content blocks, user content blocks,
queue-operation details, compaction metadata).

Two derived record kinds receive special handling because they look like
ordinary user-authored prompts but are not. A ``user`` record with
``isCompactSummary == True`` is the post-compaction synthesised summary
that Claude Code emits to seed the model with rebuilt context after a
compaction event; it is not a turn-starting prompt and does not enter
prompt-population aggregations. A ``system`` record with
``subtype == "compact_boundary"`` marks the compaction event itself; its
``compactMetadata`` carries the trigger, pre-compaction and
post-compaction context sizes, and the wall-clock duration of the
compaction operation. The compaction synthesis API call itself is not
recorded as a regular ``assistant`` record, so its token usage is not
visible to this parser; that gap is surfaced downstream as a diagnostic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

RECORD_TYPE_ASSISTANT = "assistant"
RECORD_TYPE_USER = "user"
RECORD_TYPE_ATTACHMENT = "attachment"
RECORD_TYPE_FILE_HISTORY_SNAPSHOT = "file-history-snapshot"
RECORD_TYPE_QUEUE_OPERATION = "queue-operation"
RECORD_TYPE_SYSTEM = "system"
RECORD_TYPE_PERMISSION_MODE = "permission-mode"
RECORD_TYPE_LAST_PROMPT = "last-prompt"

KNOWN_RECORD_TYPES: frozenset[str] = frozenset({
    RECORD_TYPE_ASSISTANT,
    RECORD_TYPE_USER,
    RECORD_TYPE_ATTACHMENT,
    RECORD_TYPE_FILE_HISTORY_SNAPSHOT,
    RECORD_TYPE_QUEUE_OPERATION,
    RECORD_TYPE_SYSTEM,
    RECORD_TYPE_PERMISSION_MODE,
    RECORD_TYPE_LAST_PROMPT,
})

SYSTEM_SUBTYPE_TURN_DURATION = "turn_duration"
SYSTEM_SUBTYPE_API_ERROR = "api_error"
SYSTEM_SUBTYPE_LOCAL_COMMAND = "local_command"
SYSTEM_SUBTYPE_COMPACT_BOUNDARY = "compact_boundary"

CONTENT_BLOCK_TEXT = "text"
CONTENT_BLOCK_THINKING = "thinking"
CONTENT_BLOCK_TOOL_USE = "tool_use"
CONTENT_BLOCK_TOOL_RESULT = "tool_result"
CONTENT_BLOCK_IMAGE = "image"

QUEUE_OP_ENQUEUE = "enqueue"
QUEUE_OP_DEQUEUE = "dequeue"
QUEUE_OP_REMOVE = "remove"
QUEUE_OP_POP_ALL = "popAll"

ATTACHMENT_TYPE_QUEUED_COMMAND = "queued_command"

SYNTHETIC_MODEL_MARKER = "<synthetic>"


class SchemaError(Exception):
    """Raised when a JSONL line does not match the expected record shape.

    Carries the source file and line index in its message so the caller
    can point at the offending line without further introspection.
    """


@dataclass(frozen=True)
class Record:
    """One parsed JSONL line tagged with its type and common fields.

    The ``payload`` attribute carries the full decoded line so that
    type-specific extraction can read fields not promoted to the
    dataclass surface. The promoted fields are the ones every record
    type can be expected to carry or omit predictably and that benefit
    from a typed accessor (the type tag itself, the optional subtype,
    the ISO-parsed timestamp, the uuid trio).

    Attributes:
        record_type: The record's ``type`` field. Always present;
            unrecognised types raise ``SchemaError`` at parse time.
        subtype: The ``subtype`` field for system records, ``None`` for
            other record types.
        timestamp: Parsed timestamp as a timezone-aware ``datetime``,
            or ``None`` when the record carries no timestamp (some
            ``file-history-snapshot`` and ``last-prompt`` records do
            not).
        uuid: The record's own uuid, or ``None`` when absent.
        parent_uuid: The parent record's uuid, or ``None`` when absent.
        session_id: The conversation file's session uuid as written on
            most records, or ``None`` when absent.
        source_file: Absolute path of the JSONL file the line came
            from, used for diagnostics and per-conversation grouping.
        source_line_index: Zero-based line index within the source
            file, used for error reporting.
        payload: The full decoded line as a dict, for type-specific
            extraction.
    """

    record_type: str
    subtype: str | None
    timestamp: datetime | None
    uuid: str | None
    parent_uuid: str | None
    session_id: str | None
    source_file: str
    source_line_index: int
    payload: dict[str, Any] = field(repr=False)


def parse_record(line: str, source_file: str, line_index: int) -> Record:
    """Parse one JSONL line into a ``Record``.

    Args:
        line: The raw line text. Trailing whitespace is tolerated.
        source_file: Absolute path of the file the line came from.
        line_index: Zero-based position within the file.

    Returns:
        A populated ``Record``.

    Raises:
        SchemaError: When the line is not valid JSON, or when the
            decoded object lacks a recognised ``type`` field.
    """
    text = line.strip()
    if not text:
        raise SchemaError(
            f"{source_file} line {line_index}: empty line"
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise SchemaError(
            f"{source_file} line {line_index}: invalid JSON ({error})"
        ) from error
    if not isinstance(payload, dict):
        raise SchemaError(
            f"{source_file} line {line_index}: top-level value is not an object"
        )
    record_type = payload.get("type")
    if not isinstance(record_type, str):
        raise SchemaError(
            f"{source_file} line {line_index}: missing or non-string 'type' field"
        )
    # Unknown record types are tolerated. Claude Code adds new record
    # types over time (``pr-link`` for the GitHub integration is one
    # such addition that was not present in earlier rollouts). Any
    # downstream helper here dispatches on the specific known types it
    # cares about; an unknown type is naturally inert for every metric
    # because no helper fires for it. The set of known types is kept
    # as the constant ``KNOWN_RECORD_TYPES`` so callers that want to
    # surface "unrecognised types observed" in diagnostics can compute
    # the difference.
    subtype_raw = payload.get("subtype")
    subtype = subtype_raw if isinstance(subtype_raw, str) else None
    timestamp = _parse_timestamp(payload.get("timestamp"))
    uuid_raw = payload.get("uuid")
    parent_raw = payload.get("parentUuid")
    session_raw = payload.get("sessionId")
    return Record(
        record_type=record_type,
        subtype=subtype,
        timestamp=timestamp,
        uuid=uuid_raw if isinstance(uuid_raw, str) else None,
        parent_uuid=parent_raw if isinstance(parent_raw, str) else None,
        session_id=session_raw if isinstance(session_raw, str) else None,
        source_file=source_file,
        source_line_index=line_index,
        payload=payload,
    )


def is_synthetic_assistant(record: Record) -> bool:
    """Return ``True`` for assistant records emitted by Claude Code's internal synthesis path.

    Synthetic assistant records carry ``message.model == "<synthetic>"``
    and zeroed usage fields. They appear around session boundaries and
    immediately preceding compaction events as placeholder responses;
    they are not real model output and must be excluded from every
    metric aggregation.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return False
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return False
    return message.get("model") == SYNTHETIC_MODEL_MARKER


def is_compact_summary_user(record: Record) -> bool:
    """Return ``True`` for the post-compaction synthesised user summary record.

    After a ``compact_boundary`` event, Claude Code writes a ``user``
    record with ``isCompactSummary == True`` and
    ``isVisibleInTranscriptOnly == True``. Its content is the rebuilt
    context Claude needs to keep working post-compaction; it is not a
    user-authored prompt. It must be excluded from turn-starting prompt
    detection, the bucket classifier, and the steer lifecycle.
    """
    if record.record_type != RECORD_TYPE_USER:
        return False
    return record.payload.get("isCompactSummary") is True


def is_genuine_user_prompt(record: Record) -> bool:
    """Return ``True`` for user records that carry user-authored prompt text.

    Distinguishes user-authored prompts from tool-result returns. A
    user record is a tool-result return when its content is a list
    that contains at least one ``tool_result`` block; it is a genuine
    prompt when its content is a string, or a list with no
    ``tool_result`` block. Compact-summary records are excluded
    explicitly even though they meet the structural criterion of a
    genuine prompt.
    """
    if record.record_type != RECORD_TYPE_USER:
        return False
    if is_compact_summary_user(record):
        return False
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == CONTENT_BLOCK_TOOL_RESULT:
                return False
        return True
    return False


def assistant_request_id(record: Record) -> str | None:
    """Return the ``requestId`` of an assistant record, or ``None``.

    A single API streaming response writes one JSONL record per content
    block; all records sharing one ``requestId`` carry identical
    ``message.usage`` values. The request id is the deduplication key
    for token-usage summing.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return None
    request_id = record.payload.get("requestId")
    return request_id if isinstance(request_id, str) else None


def assistant_message_usage(record: Record) -> dict[str, Any] | None:
    """Return the ``message.usage`` block of an assistant record, or ``None``."""
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return None
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    return usage if isinstance(usage, dict) else None


def assistant_content_blocks(record: Record) -> list[dict[str, Any]]:
    """Return the list of content blocks on an assistant record.

    Empty list when the record has no content blocks. Non-list content
    is treated as no blocks rather than an error; callers that need to
    know can check the payload directly.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return []
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def user_content_blocks(record: Record) -> list[dict[str, Any]]:
    """Return the list of content blocks on a user record, normalising string content.

    A user record's content can be either a plain string or a list of
    content blocks. To give callers one shape to work with, a string
    content is wrapped in a single ``text`` block; missing content
    yields an empty list.
    """
    if record.record_type != RECORD_TYPE_USER:
        return []
    message = record.payload.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": CONTENT_BLOCK_TEXT, "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def user_prompt_text(record: Record) -> str:
    """Return the concatenated text content of a user prompt record.

    Tool-result blocks are excluded because their text is the agent's
    own emitted output, not user input. Image blocks contribute no
    characters. Used by the bucket classifier and by command-marker
    extraction.
    """
    pieces: list[str] = []
    for block in user_content_blocks(record):
        block_type = block.get("type")
        if block_type == CONTENT_BLOCK_TEXT:
            text = block.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces)


def queue_operation(record: Record) -> str | None:
    """Return the operation field on a queue-operation record, or ``None``."""
    if record.record_type != RECORD_TYPE_QUEUE_OPERATION:
        return None
    op = record.payload.get("operation")
    return op if isinstance(op, str) else None


def queue_record_content(record: Record) -> str | None:
    """Return the ``content`` field on a queue-operation record, or ``None``.

    Used to distinguish user-authored enqueues from system-generated
    ones. System enqueues carry XML-wrapped task notification text
    (``<task-notification>...``); user enqueues carry plain prompt text
    or include the user's typed message.
    """
    if record.record_type != RECORD_TYPE_QUEUE_OPERATION:
        return None
    content = record.payload.get("content")
    return content if isinstance(content, str) else None


def is_user_authored_enqueue(record: Record) -> bool:
    """Return ``True`` for enqueue records whose content is a user-typed message.

    System-generated enqueues (typically task-notification envelopes
    wrapped in ``<task-notification>``) are filtered from the steer
    lifecycle so they do not pollute the open-enqueue queue used to
    classify dequeues and removes.
    """
    if queue_operation(record) != QUEUE_OP_ENQUEUE:
        return False
    content = queue_record_content(record)
    if content is None:
        return False
    return not content.lstrip().startswith("<task-notification")


def compact_boundary_metadata(record: Record) -> dict[str, Any] | None:
    """Return the ``compactMetadata`` block of a compact_boundary record, or ``None``."""
    if record.record_type != RECORD_TYPE_SYSTEM:
        return None
    if record.subtype != SYSTEM_SUBTYPE_COMPACT_BOUNDARY:
        return None
    metadata = record.payload.get("compactMetadata")
    return metadata if isinstance(metadata, dict) else None


def iter_assistant_tool_use_blocks(records: Iterable[Record]) -> Iterable[tuple[Record, dict[str, Any]]]:
    """Yield ``(record, block)`` pairs for every tool_use block across assistant records.

    Synthetic assistant records are skipped; their content blocks are
    placeholder responses that do not represent real tool dispatches.
    """
    for record in records:
        if is_synthetic_assistant(record):
            continue
        for block in assistant_content_blocks(record):
            if block.get("type") == CONTENT_BLOCK_TOOL_USE:
                yield record, block


def _parse_timestamp(value: Any) -> datetime | None:
    """Return a timezone-aware datetime from an ISO-8601 timestamp string, or ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
