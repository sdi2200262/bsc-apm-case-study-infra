# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Context-window segment series for ``parser_data.json``.

Claude Code records a ``compact_boundary`` system event whenever a main
conversation is compacted. This module turns each main conversation into one
or more context segments: a closed segment for each compaction boundary, and a
final open segment for the tail after the last compaction. Closed segments use
Claude Code's own pre-compaction token count as the peak; open segments use the
maximum prompt-side token usage observed in assistant calls within that segment.
"""

from __future__ import annotations

from typing import Any

from .schema import (
    RECORD_TYPE_ASSISTANT,
    SYSTEM_SUBTYPE_COMPACT_BOUNDARY,
    Record,
    assistant_message_usage,
)
from .session import Session


def build_context_segments(session: Session) -> list[dict[str, Any]]:
    """Return context-window segments for every main conversation in ``session``.

    Args:
        session: The assembled parser session.

    Returns:
        A JSON-serialisable list of context-segment records. The list is
        ordered by parser conversation view order, then by segment index.
    """
    segments: list[dict[str, Any]] = []
    for view in session.views:
        segments.extend(
            _conversation_segments(
                conversation_id=view.conversation.session_id or "",
                role_key=view.role,
                records=view.conversation.records,
            )
        )
    return segments


def _conversation_segments(
    conversation_id: str,
    role_key: str,
    records: tuple[Record, ...],
) -> list[dict[str, Any]]:
    """Return context segments for one conversation's record stream.

    Args:
        conversation_id: The conversation's session id, or the empty
            string when the conversation has none.
        role_key: The conversation's role key.
        records: The conversation's records in document order.

    Returns:
        One dict per context segment, in segment-index order.
    """
    segments: list[dict[str, Any]] = []
    running_peak = 0
    segment_index = 0
    for record in records:
        if _is_compaction_boundary(record):
            metadata = _compaction_metadata(record)
            pre_tokens = _optional_int(metadata.get("preTokens"))
            peak = pre_tokens if pre_tokens is not None else running_peak
            segments.append(
                {
                    "conversation_id": conversation_id,
                    "role_key": role_key,
                    "segment_index": segment_index,
                    "closed_by_compaction": True,
                    "peak_context_tokens": peak,
                    "peak_source": (
                        "compaction_boundary" if pre_tokens is not None else "prompt_tokens"
                    ),
                    "compaction_trigger": _optional_str(metadata.get("trigger")),
                    "compaction_pre_tokens": pre_tokens,
                    "compaction_post_tokens": _optional_int(metadata.get("postTokens")),
                    "compaction_duration_ms": _optional_int(metadata.get("durationMs")),
                }
            )
            running_peak = 0
            segment_index += 1
            continue
        running_peak = max(running_peak, _prompt_side_tokens(record))
    segments.append(
        {
            "conversation_id": conversation_id,
            "role_key": role_key,
            "segment_index": segment_index,
            "closed_by_compaction": False,
            "peak_context_tokens": running_peak,
            "peak_source": "prompt_tokens",
            "compaction_trigger": "",
            "compaction_pre_tokens": None,
            "compaction_post_tokens": None,
            "compaction_duration_ms": None,
        }
    )
    return segments


def _is_compaction_boundary(record: Record) -> bool:
    """Return whether ``record`` closes a context segment.

    Args:
        record: The record to classify.

    Returns:
        ``True`` when the record is a ``compact_boundary`` system event.
    """
    return record.record_type == "system" and record.subtype == SYSTEM_SUBTYPE_COMPACT_BOUNDARY


def _compaction_metadata(record: Record) -> dict[str, Any]:
    """Return the compaction metadata block, or an empty mapping.

    Args:
        record: A compaction-boundary system record.

    Returns:
        The record's ``compactMetadata`` payload when present and a
        mapping, otherwise an empty mapping.
    """
    metadata = record.payload.get("compactMetadata")
    return metadata if isinstance(metadata, dict) else {}


def _prompt_side_tokens(record: Record) -> int:
    """Return prompt-side token occupancy for an assistant record.

    Args:
        record: The record to read; a non-assistant record contributes
            zero.

    Returns:
        The sum of input, cache-read, and cache-creation tokens from the
        record's usage block, or zero when the record carries none.
    """
    if record.record_type != RECORD_TYPE_ASSISTANT:
        return 0
    usage = assistant_message_usage(record)
    if usage is None:
        return 0
    return (
        _int_or_zero(usage.get("input_tokens"))
        + _int_or_zero(usage.get("cache_read_input_tokens"))
        + _int_or_zero(usage.get("cache_creation_input_tokens"))
    )


def _int_or_zero(value: Any) -> int:
    """Return ``value`` when it is an int, otherwise zero.

    Args:
        value: The value to coerce.

    Returns:
        ``value`` unchanged when it is an ``int``, else ``0``.
    """
    return value if isinstance(value, int) else 0


def _optional_int(value: Any) -> int | None:
    """Return ``value`` when it is an int, otherwise ``None``.

    Args:
        value: The value to coerce.

    Returns:
        ``value`` unchanged when it is an ``int``, else ``None``.
    """
    return value if isinstance(value, int) else None


def _optional_str(value: Any) -> str:
    """Return ``value`` when it is a string, otherwise an empty string.

    Args:
        value: The value to coerce.

    Returns:
        ``value`` unchanged when it is a ``str``, else ``""``.
    """
    return value if isinstance(value, str) else ""
