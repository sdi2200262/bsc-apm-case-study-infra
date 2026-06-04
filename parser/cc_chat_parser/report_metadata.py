#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Session-metadata block and session-level field extractors.

The session-metadata block carries the per-session descriptive
fields the analysis layer reads before any metric: the modal
Claude Code version, model, authentication-mode indicator,
entrypoint, and service tier, the session start and end
timestamps, and the per-conversation array. Session start is the
earliest user-authored prompt across the session; session end is
the latest non-synthetic record.

This module is a leaf: it depends only on the session model and
the schema vocabulary, and it is imported by ``report`` for the
artifact assembly.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .schema import (
    RECORD_TYPE_ASSISTANT,
    SYNTHETIC_MODEL_MARKER,
    is_synthetic_assistant,
)
from .session import Session
from .user_prompts import is_user_authored_prompt


def _build_session_metadata(session: Session) -> dict[str, Any]:
    """Assemble the session-metadata block."""
    cc_versions = _modal_string_field(session, "version")
    auth_modes = _modal_string_field(session, "userType")
    entrypoints = _modal_string_field(session, "entrypoint")
    service_tiers = _modal_assistant_usage_field(session, "service_tier")
    models = _models_observed(session)
    pinned_model = max(models.items(), key=lambda item: item[1])[0] if models else ""
    start = _iso_or_none(_session_start_timestamp(session))
    end = _latest_real_timestamp_iso(session)
    conversations = [
        {
            "role_key": view.role,
            "session_id": view.conversation.session_id,
            "first_command": view.first_command,
            "first_record_timestamp": _iso_or_none(view.first_record_timestamp),
            "record_count": len(view.conversation.records),
        }
        for view in session.views
    ]
    return {
        "cc_version": cc_versions,
        "model": pinned_model,
        "model_drift": len(models) > 1,
        "auth_mode_indicator": auth_modes,
        "entrypoint": entrypoints,
        "service_tier": service_tiers,
        "session_start_timestamp": start,
        "session_end_timestamp": end,
        "conversations": conversations,
    }


def _modal_string_field(session: Session, key: str) -> str:
    """Return the modal value of a top-level string field across every record."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            value = record.payload.get(key)
            if isinstance(value, str) and value:
                counter[value] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _modal_assistant_usage_field(session: Session, key: str) -> str:
    """Return the modal value of a string field inside ``message.usage`` on assistant records."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != RECORD_TYPE_ASSISTANT:
                continue
            if is_synthetic_assistant(record):
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            value = usage.get(key)
            if isinstance(value, str) and value:
                counter[value] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _models_observed(session: Session) -> dict[str, int]:
    """Return a count of distinct non-synthetic models observed across assistant records."""
    counter: Counter[str] = Counter()
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != RECORD_TYPE_ASSISTANT:
                continue
            if is_synthetic_assistant(record):
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if isinstance(model, str) and model and model != SYNTHETIC_MODEL_MARKER:
                counter[model] += 1
    return dict(counter)


def _session_start_timestamp(session: Session) -> datetime | None:
    """Return the start timestamp of the session's first turn.

    Falls back to the earliest user-authored prompt, then to
    :func:`_earliest_real_timestamp`, when the session has no turns.

    Args:
        session: The assembled session.

    Returns:
        The session-start timestamp, or ``None`` when no timestamped
        record exists.
    """
    if session.turns:
        return session.turns[0].start_timestamp
    earliest: datetime | None = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if not is_user_authored_prompt(record):
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    if earliest is not None:
        return earliest
    return _earliest_real_timestamp(session)


def _earliest_real_timestamp(session: Session) -> datetime | None:
    """Return the earliest non-synthetic record timestamp across the session, or ``None``."""
    earliest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if is_synthetic_assistant(record):
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    return earliest


def _latest_real_timestamp(session: Session) -> datetime | None:
    """Return the latest non-synthetic record timestamp across the session, or ``None``."""
    latest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if is_synthetic_assistant(record):
                continue
            if latest is None or record.timestamp > latest:
                latest = record.timestamp
    return latest


def _latest_real_timestamp_iso(session: Session) -> str | None:
    """Return the latest non-synthetic record timestamp as ISO-8601, or ``None``."""
    return _iso_or_none(_latest_real_timestamp(session))


def _iso_or_none(value: datetime | None) -> str | None:
    """Return an ISO-8601 string for a timestamp, or ``None`` when absent."""
    return value.isoformat() if value is not None else None
