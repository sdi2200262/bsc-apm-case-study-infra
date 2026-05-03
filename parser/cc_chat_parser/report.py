#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Assemble the canonical scope-nested metrics artifact.

The artifact has six top-level sections: ``session_metadata``,
``parameters``, ``session``, ``phases``, optional ``roles`` (APM
only), ``turns``, and ``diagnostics``. Each measurement leaf is a
``{value, anchor, constructed}`` triple so the analysis layer can
iterate over Primary metrics to assemble its hypothesis-test family
and flag every Constructed metric for the literature-grounding
cross-check without consulting an external index.

This module owns the overall artifact assembly and the per-scope
turn and record selection. The leaf-block rendering for each
dimension lives in ``report_blocks``; the diagnostics block and
invariant evaluator live in ``report_diagnostics``.

**Naming convention.** Every artifact key is snake_case.
Per-conversation metadata (role key, session id, first slash
command, first record timestamp, record count) is consolidated
into a single ``conversations`` array of objects under
``session_metadata`` rather than split across two parallel
fields, so downstream consumers iterate one array regardless of
framework. The ``other`` phase is rendered with zeroed values
when the session has no unmarked-phase prompts so the artifact's
shape is uniform across sessions; analysis consumers should
filter empty phases by ``turn_count == 0`` rather than by
missing keys.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Iterable

from .buckets import DEFAULT_SHORT_THRESHOLD
from .commands import (
    FRAMEWORK_APM,
    PHASE_IMPLEMENTATION,
    PHASE_OTHER,
    PHASE_PLANNING,
)
from .loader import SteerEvent
from .metrics.economic import (
    EconomicSession,
    compute_economic_for_records,
    compute_session_economic,
    resolve_pinned_model,
)
from .metrics.reliability import compute_reliability_metrics
from .metrics.supplementary import compute_supplementary_metrics
from .metrics.time import compute_time_metrics
from .metrics.user_input import compute_user_input_metrics
from .rates import RateTable
from .report_blocks import (
    economic_block,
    reliability_block,
    supplementary_block,
    time_block,
    time_block_role,
    user_input_block,
)
from .report_diagnostics import build_diagnostics
from .schema import (
    Record,
    SYNTHETIC_MODEL_MARKER,
    is_synthetic_assistant,
)
from .session import ConversationView, Session
from .turns import Turn

PHASE_KEYS: tuple[str, ...] = (PHASE_PLANNING, PHASE_IMPLEMENTATION, PHASE_OTHER)

REAL_ROLE_PREFIXES: tuple[str, ...] = ("planner-", "manager-", "worker-")


def build_report(
    session: Session,
    rate_table: RateTable,
    short_threshold: int = DEFAULT_SHORT_THRESHOLD,
) -> dict[str, Any]:
    """Build the canonical scope-nested metrics artifact for a session.

    Args:
        session: An assembled session.
        rate_table: The rate table to compute economic metrics
            against.
        short_threshold: Bucket classifier threshold for the
            user-input dimension.

    Returns:
        The artifact as a JSON-serialisable dict.
    """
    metadata = _build_session_metadata(session)
    parameters = _build_parameters(session, rate_table, short_threshold)
    session_start_dt = _earliest_real_timestamp(session)
    session_end_dt = _latest_real_timestamp(session)
    session_block = _build_scope_block(
        session, session.turns, rate_table, short_threshold,
        scope_kind="session",
        scope_start=session_start_dt,
        scope_end=session_end_dt,
    )
    phases_block = {
        phase: _build_scope_block(
            session,
            tuple(_turns_in_phase(session, phase)),
            rate_table,
            short_threshold,
            scope_kind="phase",
            phase_label=phase,
        )
        for phase in PHASE_KEYS
    }
    artifact: dict[str, Any] = {
        "session_metadata": metadata,
        "parameters": parameters,
        "session": session_block,
        "phases": phases_block,
        "turns": _build_turn_records(session),
    }
    if session.framework == FRAMEWORK_APM:
        artifact["roles"] = {
            view.role: _build_scope_block(
                session,
                tuple(_turns_in_role(session, view.role)),
                rate_table,
                short_threshold,
                scope_kind="role",
                role_view=view,
            )
            for view in session.views
            if _is_real_apm_role(view.role)
        }
    artifact["diagnostics"] = build_diagnostics(session, artifact, rate_table, _is_real_apm_role)
    return artifact


def _is_real_apm_role(role_key: str) -> bool:
    """Return ``True`` for the three real APM role kinds (planner/manager/worker).

    The session assembler also produces ``unassigned-N`` entries for
    APM conversations whose first slash command is not a role
    initiator. Those conversations stay listed in
    ``session_metadata.conversations`` for traceability but are not
    role-bearing under the APM model, so they do not belong in the
    ``roles`` block of the artifact.
    """
    return role_key.startswith(REAL_ROLE_PREFIXES)


def _build_session_metadata(session: Session) -> dict[str, Any]:
    """Assemble the session-metadata block."""
    cc_versions = _modal_string_field(session, "version")
    auth_modes = _modal_string_field(session, "userType")
    entrypoints = _modal_string_field(session, "entrypoint")
    service_tiers = _modal_assistant_usage_field(session, "service_tier")
    models = _models_observed(session)
    pinned_model = max(models.items(), key=lambda item: item[1])[0] if models else ""
    start = _earliest_real_timestamp_iso(session)
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


def _build_parameters(
    session: Session,
    rate_table: RateTable,
    short_threshold: int,
) -> dict[str, Any]:
    """Assemble the parameters block."""
    return {
        "framework": session.framework,
        "short_threshold": short_threshold,
        "rate_table_snapshot_date": rate_table.snapshot_date,
        "rate_table_source_path": rate_table.source_path,
        "pricing_source_urls": list(rate_table.sources),
    }


def _build_scope_block(
    session: Session,
    turns: tuple[Turn, ...],
    rate_table: RateTable,
    short_threshold: int,
    scope_kind: str,
    phase_label: str | None = None,
    role_view: ConversationView | None = None,
    scope_start: datetime | None = None,
    scope_end: datetime | None = None,
) -> dict[str, Any]:
    """Assemble one scope's economic, process, and supplementary blocks.

    ``scope_kind`` is one of ``"session"``, ``"phase"``, or
    ``"role"``. The kind controls two things: which records the
    reliability and supplementary modules iterate (full conversation
    walk for session and role, per-turn record concatenation for
    phase), and whether the time block emits the full set of fields
    (session and phase) or the role-scope subset (role). A role
    scope's ``turn_time`` is the sum of per-turn durations rather
    than the union of intervals, reflecting that a role is one
    conversation file whose own turns do not overlap.
    """
    steer_events = _steer_events_in_scope(session, scope_kind, role_view, turns)
    economic = _compute_economic_for_scope(session, turns, rate_table)
    time_metrics = compute_time_metrics(turns, scope_start, scope_end)
    user_input = compute_user_input_metrics(turns, steer_events, short_threshold)
    scope_records = _records_in_scope(session, turns, scope_kind, role_view)
    reliability = compute_reliability_metrics(scope_records)
    supplementary = compute_supplementary_metrics(scope_records)
    if scope_kind == "role":
        rendered_time = time_block_role(time_metrics)
    else:
        rendered_time = time_block(time_metrics, scope_kind)
    return {
        "economic": economic_block(economic),
        "process": {
            "time": rendered_time,
            "user_input": user_input_block(user_input),
            "reliability": reliability_block(reliability),
        },
        "supplementary": supplementary_block(supplementary),
    }


def _records_in_scope(
    session: Session,
    turns: tuple[Turn, ...],
    scope_kind: str,
    role_view: ConversationView | None,
) -> list[Record]:
    """Return the record stream for a scope's reliability/supplementary aggregation.

    Session scope iterates every conversation's records across
    every conversation file. Role scope iterates the records of
    the role's single conversation file. Phase scope cannot use
    a per-conversation record stream because a phase can span
    multiple conversations; it instead concatenates the records
    of every turn whose starting prompt's phase matches the scope.
    In well-formed Claude Code data the session and role record
    streams (full conversation walk) and the phase record stream
    (per-turn walk) cover the same metric-relevant records; the
    distinction is one of attribution, not of which records exist.
    """
    if scope_kind == "session":
        return [
            record
            for view in session.views
            for record in view.conversation.records
        ]
    if scope_kind == "role" and role_view is not None:
        return list(role_view.conversation.records)
    records: list[Record] = []
    for turn in turns:
        records.extend(turn.records)
    return records


def _steer_events_in_scope(
    session: Session,
    scope_kind: str,
    role_view: ConversationView | None,
    turns: tuple[Turn, ...],
) -> list[SteerEvent]:
    """Return the steer events that belong to a scope.

    Session scope sees every steer event across every conversation.
    Role scope sees every steer in the role's conversation,
    regardless of whether the steer's enqueue timestamp falls
    inside a turn's interval; this catches inter-turn steers that
    happen during a model-quiet moment. Phase scope attributes
    each steer to the phase of the turn whose interval contains
    its enqueue timestamp, which is the same containment relation
    the per-turn ``Turn.steer_events`` list already encodes; a
    steer between turns (rare, model-quiet) does not enter any
    phase aggregate, matching the per-prompt phase model.
    """
    if scope_kind == "session":
        return [
            event
            for view in session.views
            for event in view.conversation.steer_events
        ]
    if scope_kind == "role" and role_view is not None:
        return list(role_view.conversation.steer_events)
    if scope_kind == "phase":
        return [event for turn in turns for event in turn.steer_events]
    return []


def _compute_economic_for_scope(
    session: Session,
    turns: tuple[Turn, ...],
    rate_table: RateTable,
) -> EconomicSession | None:
    """Compute economic metrics for a scope, or ``None`` for an empty scope."""
    if turns is session.turns:
        return compute_session_economic(session, rate_table)
    if not turns:
        return None
    records: list[Record] = []
    for turn in turns:
        records.extend(turn.records)
    model = resolve_pinned_model(session)
    return compute_economic_for_records(records, rate_table, model)


def _build_turn_records(session: Session) -> list[dict[str, Any]]:
    """Render the per-turn record-level output array."""
    records: list[dict[str, Any]] = []
    for turn in session.turns:
        records.append({
            "turn_id": turn.starting_prompt.uuid,
            "conversation_id": _conversation_session_id(session, turn.conversation_path),
            "role_key": _role_of_turn(session, turn),
            "phase": _phase_of_turn(session, turn),
            "start_timestamp": _iso_or_none(turn.start_timestamp),
            "end_timestamp": _iso_or_none(turn.end_timestamp),
            "duration_seconds": (turn.end_timestamp - turn.start_timestamp).total_seconds(),
            "steer_count": len(turn.steer_events),
        })
    return records


def _turns_in_phase(session: Session, phase: str) -> Iterable[Turn]:
    """Yield turns whose starting-prompt phase matches ``phase``."""
    for turn in session.turns:
        if _phase_of_turn(session, turn) == phase:
            yield turn


def _turns_in_role(session: Session, role_key: str) -> Iterable[Turn]:
    """Yield turns whose conversation has the given role key."""
    for view in session.views:
        if view.role != role_key:
            continue
        for turn in session.turns:
            if turn.conversation_path == view.conversation.path:
                yield turn


def _phase_of_turn(session: Session, turn: Turn) -> str:
    """Return the phase label for a turn."""
    starting_uuid = turn.starting_prompt.uuid
    for view in session.views:
        if view.conversation.path != turn.conversation_path:
            continue
        if starting_uuid and starting_uuid in view.phase_by_record_uuid:
            return view.phase_by_record_uuid[starting_uuid]
        return PHASE_OTHER
    return PHASE_OTHER


def _role_of_turn(session: Session, turn: Turn) -> str:
    """Return the role key for a turn."""
    for view in session.views:
        if view.conversation.path == turn.conversation_path:
            return view.role
    return ""


def _conversation_session_id(session: Session, conversation_path: str) -> str | None:
    """Return the sessionId for a conversation path, or ``None`` when not found."""
    for view in session.views:
        if view.conversation.path == conversation_path:
            return view.conversation.session_id
    return None


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
            if record.record_type != "assistant":
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
            if record.record_type != "assistant":
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


def _earliest_real_timestamp_iso(session: Session) -> str | None:
    """Return the earliest non-synthetic record timestamp as ISO-8601, or ``None``."""
    return _iso_or_none(_earliest_real_timestamp(session))


def _latest_real_timestamp_iso(session: Session) -> str | None:
    """Return the latest non-synthetic record timestamp as ISO-8601, or ``None``."""
    return _iso_or_none(_latest_real_timestamp(session))


def _iso_or_none(value: datetime | None) -> str | None:
    """Return an ISO-8601 string for a timestamp, or ``None`` when absent."""
    return value.isoformat() if value is not None else None
