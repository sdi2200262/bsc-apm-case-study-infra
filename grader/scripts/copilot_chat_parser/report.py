#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Report assembly: combine the individual metric-family outputs into one
session-level report ready for JSON or CSV serialization.

The assembled report is snake_case throughout. A single ``project_metadata``
section carries file-level context; the ``metrics`` section carries every
metric family the parser computes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .buckets import DEFAULT_SHORT_THRESHOLD
from .metrics.buckets import (
    compute_phase_bucket_shares,
    compute_session_bucket_shares,
    compute_short_threshold_sensitivity,
)
from .metrics.requests import compute_request_counts
from .metrics.roles import compute_per_role_metrics
from .metrics.timing import (
    compute_phase_timing,
    compute_session_duration,
    compute_turn_duration,
)
from .metrics.tools import (
    compute_tool_retry_rate,
    compute_tool_success_rate,
    compute_user_edit_rate,
)
from .session import Session


def build_report(session: Session, short_threshold: int = DEFAULT_SHORT_THRESHOLD) -> dict[str, Any]:
    """Build the full session report.

    Args:
        session: The assembled session.
        short_threshold: Primary ``short`` bucket threshold to use for
            headline bucket metrics. The sensitivity sweep always covers
            a fixed set of thresholds independent of this argument.

    Returns:
        A dict with ``project_metadata`` and ``metrics`` sections, plus
        a top-level ``parameters`` section recording the primary
        ``short_threshold`` used for headline metrics.
    """
    metrics: dict[str, Any] = {}
    metrics.update(compute_request_counts(session))
    metrics.update(compute_session_duration(session))
    metrics.update(compute_turn_duration(session))
    metrics.update(compute_phase_timing(session))
    metrics.update(compute_tool_success_rate(session))
    metrics.update(compute_tool_retry_rate(session))
    metrics.update(compute_user_edit_rate(session))
    metrics.update(compute_session_bucket_shares(session, short_threshold))
    metrics.update(compute_phase_bucket_shares(session, short_threshold))
    metrics["per_role"] = compute_per_role_metrics(session, short_threshold)
    metrics["short_threshold_sensitivity"] = compute_short_threshold_sensitivity(session)

    return {
        "project_metadata": _build_project_metadata(session),
        "parameters": {"short_threshold": short_threshold},
        "metrics": metrics,
    }


def _build_project_metadata(session: Session) -> dict[str, Any]:
    """Summarise the session's input files, framework, and time bounds.

    Args:
        session: The assembled session.

    Returns:
        A dict with ``file_count``, ``framework``, per-conversation
        summaries, session start and end as ISO-8601 UTC timestamps, and
        the distinct model ids observed.
    """
    global_start = _isoformat_ms(
        min((r.raw.timestamp_ms for r in session.requests), default=None)
    )
    global_end_ms: int | None
    end_candidates = [
        r.raw.completed_at_ms for r in session.requests
        if r.raw.completed_at_ms is not None
    ]
    if end_candidates:
        global_end_ms = max(end_candidates)
    elif session.requests:
        global_end_ms = max(r.raw.timestamp_ms for r in session.requests)
    else:
        global_end_ms = None

    return {
        "file_count": len(session.conversations),
        "framework": session.framework,
        "conversations": [
            {
                "path": conversation.path,
                "framework": conversation.framework,
                "role": conversation.role,
                "request_count": conversation.request_count,
                "chat_id": _chat_id_for_conversation(session, conversation.path),
                "unknown_commands": list(conversation.unknown_commands),
            }
            for conversation in session.conversations
        ],
        "global_start": global_start,
        "global_end": _isoformat_ms(global_end_ms),
        "unique_model_ids": list(session.model_ids),
    }


def _chat_id_for_conversation(session: Session, conversation_path: str) -> str:
    """Compute a stable 16-char hex identifier for one conversation's user messages."""
    messages = [
        r.raw.message_text
        for r in session.requests
        if r.raw.conversation_file == conversation_path
    ]
    combined = "".join(messages)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def _isoformat_ms(value_ms: int | None) -> str | None:
    """Format a millisecond-epoch timestamp as an ISO-8601 UTC string.

    Args:
        value_ms: Timestamp in milliseconds since epoch, or ``None``.

    Returns:
        The ISO-8601 UTC representation, or ``None`` when the input is
        ``None``.
    """
    if value_ms is None:
        return None
    return datetime.fromtimestamp(value_ms / 1000.0, tz=timezone.utc).isoformat()
