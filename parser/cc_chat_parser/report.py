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
command, first record timestamp, record count) is collected
into a single ``conversations`` array of objects under
``session_metadata``, so downstream consumers iterate one array
regardless of framework. The ``other`` phase is rendered with zeroed values
when the session has no unmarked-phase prompts so the artifact's
shape is uniform across sessions; analysis consumers should
filter empty phases by ``turn_count == 0`` rather than by
missing keys.
"""

from __future__ import annotations

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
from .report_metadata import (
    _build_session_metadata,
    _iso_or_none,
    _latest_real_timestamp,
    _session_start_timestamp,
)
from .schema import (
    RECORD_TYPE_ASSISTANT,
    SYNTHETIC_MODEL_MARKER,
    Record,
    assistant_request_id,
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
    session_start_dt = _session_start_timestamp(session)
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
    inter_turn_override = None
    if scope_kind == "phase" and phase_label is not None:
        session_start = _session_start_timestamp(session)
        session_end = _latest_real_timestamp(session)
        if session_start is not None and session_end is not None:
            inter_turn_override = _calculate_partitioned_inter_turn_time(
                session, phase_label, session_start, session_end
            )

    steer_events = _steer_events_in_scope(session, scope_kind, role_view, turns)
    economic = _compute_economic_for_scope(session, turns, rate_table)
    time_metrics = compute_time_metrics(
        turns, scope_start, scope_end,
        inter_turn_time_override=inter_turn_override
    )
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


def _calculate_partitioned_inter_turn_time(
    session: Session,
    phase_label: str,
    scope_start: datetime,
    scope_end: datetime,
) -> float:
    """Return the total inter-turn time attributed to a specific phase.

    Partitions the session's wall-clock gaps by assigning each gap
    to the phase of the turn that preceded it. This ensures that phase
    durations are disjoint and their sum matches the total session
    duration.
    """
    total_inter_turn = 0.0
    all_turns = session.turns
    if not all_turns:
        return 0.0

    # Gap before first turn: assigned to first turn's phase
    if _phase_of_turn(session, all_turns[0]) == phase_label:
        if all_turns[0].start_timestamp > scope_start:
            total_inter_turn += (all_turns[0].start_timestamp - scope_start).total_seconds()

    # Gaps between turns
    for i in range(len(all_turns) - 1):
        if _phase_of_turn(session, all_turns[i]) == phase_label:
            gap = (all_turns[i+1].start_timestamp - all_turns[i].end_timestamp).total_seconds()
            total_inter_turn += max(0.0, gap)

    # Gap after last turn
    if _phase_of_turn(session, all_turns[-1]) == phase_label:
        if scope_end > all_turns[-1].end_timestamp:
            total_inter_turn += (scope_end - all_turns[-1].end_timestamp).total_seconds()

    return total_inter_turn


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
    subagent_models: dict[str, str] = {}
    for view in session.views:
        subagent_models.update(view.conversation.subagent_model_index.by_agent_id)
    return compute_economic_for_records(records, rate_table, subagent_models)


def _build_turn_records(session: Session) -> list[dict[str, Any]]:
    """Render the per-turn record-level output array.

    Each turn carries a ``phase_request_share`` dict with the three
    phase keys (``planning``, ``implementation``, ``other``). The
    values are integer counts of the turn's non-synthetic
    non-API-error main requests (deduplicated by ``requestId``,
    matching the recipe in ``metrics.economic._sum_main_from_records``)
    bucketed by each request's phase. A request's phase is the phase
    of its first emitting assistant record in the conversation file's
    document order, looked up against a per-conversation phase index
    derived from the walker output. The turn-level ``phase`` field
    still carries the phase of the turn's starting prompt.
    """
    request_phase_by_conversation = _build_request_phase_index(session)
    records: list[dict[str, Any]] = []
    for turn in session.turns:
        request_phase_index = request_phase_by_conversation.get(
            turn.conversation_path, {}
        )
        records.append({
            "turn_id": turn.starting_prompt.uuid,
            "conversation_id": _conversation_session_id(session, turn.conversation_path),
            "role_key": _role_of_turn(session, turn),
            "phase": _phase_of_turn(session, turn),
            "start_timestamp": _iso_or_none(turn.start_timestamp),
            "end_timestamp": _iso_or_none(turn.end_timestamp),
            "duration_seconds": (turn.end_timestamp - turn.start_timestamp).total_seconds(),
            "steer_count": len(turn.steer_events),
            "phase_request_share": _phase_request_share(turn, request_phase_index),
        })
    return records


def _build_request_phase_index(session: Session) -> dict[str, dict[str, str]]:
    """Build a per-conversation ``requestId -> phase`` index.

    For each conversation file the function walks records in document
    order and tracks a running phase: it is bumped whenever a record's
    uuid appears in the conversation view's ``phase_by_record_uuid``
    map (user prompts and steer enqueues set the prompt's phase;
    Skill-tagged request groups override every same-``requestId``
    assistant record). The phase observed at a request's first
    assistant record becomes that request's phase. For APM the
    running phase is set by each user prompt to the role phase, so
    every request inherits the role's phase. For Spec-kit the phase
    is set by the most recent prompt or steer until a Skill request
    group rewrites it.
    """
    index: dict[str, dict[str, str]] = {}
    for view in session.views:
        per_request: dict[str, str] = {}
        current_phase: str = PHASE_OTHER
        for record in view.conversation.records:
            if record.uuid is not None:
                tagged = view.phase_by_record_uuid.get(record.uuid)
                if tagged is not None:
                    current_phase = tagged
            request_id = assistant_request_id(record)
            if request_id is None:
                continue
            if request_id in per_request:
                continue
            per_request[request_id] = current_phase
        index[view.conversation.path] = per_request
    return index


def _phase_request_share(
    turn: Turn,
    request_phase_index: dict[str, str],
) -> dict[str, int]:
    """Return the per-phase request count for a turn.

    The denominator is the count of unique ``requestId`` values among
    the turn's non-synthetic non-API-error assistant records (the
    main-call dedup recipe). Each unique requestId is bucketed by the
    phase recorded for it in ``request_phase_index``; requests whose
    phase falls outside the three canonical labels are dropped to
    keep the dict shape uniform.
    """
    buckets: dict[str, int] = {phase: 0 for phase in PHASE_KEYS}
    seen: set[str] = set()
    for record in turn.records:
        if record.record_type != RECORD_TYPE_ASSISTANT:
            continue
        message = record.payload.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") == SYNTHETIC_MODEL_MARKER:
            continue
        if record.payload.get("isApiErrorMessage") is True:
            continue
        request_id = record.payload.get("requestId")
        if not isinstance(request_id, str):
            continue
        if request_id in seen:
            continue
        seen.add(request_id)
        phase = request_phase_index.get(request_id, PHASE_OTHER)
        if phase in buckets:
            buckets[phase] += 1
    return buckets


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
