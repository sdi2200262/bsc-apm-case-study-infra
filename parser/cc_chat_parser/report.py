#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Assemble the canonical scope-nested metrics artifact.

The artifact has six top-level sections: ``session_metadata``,
``parameters``, ``session``, ``phases``, optional ``roles`` (APM
only), ``turns``, and ``diagnostics``. Each measurement leaf is a
``{value, label, constructed}`` triple so the analysis layer can
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
from typing import Any

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
from .metrics.requests import compute_requests_for_records
from .metrics.supplementary import compute_supplementary_metrics
from .metrics.time import compute_time_metrics
from .metrics.user_input import compute_user_input_metrics
from .rates import RateTable
from .report_blocks import (
    economic_block,
    requests_block,
    supplementary_block,
    time_block,
    time_block_role,
    user_input_block,
)
from .report_diagnostics import build_diagnostics
from .report_metadata import (
    _build_session_metadata,
    _latest_real_timestamp,
    _session_start_timestamp,
)
from .report_turns import (
    build_turn_records,
    phase_of_turn,
    turns_in_phase,
    turns_in_role,
)
from .schema import Record
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
            tuple(turns_in_phase(session, phase)),
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
        "turns": build_turn_records(session),
    }
    if session.framework == FRAMEWORK_APM:
        artifact["roles"] = {
            view.role: _build_scope_block(
                session,
                tuple(turns_in_role(session, view.role)),
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
    supplementary aggregation iterates (full conversation walk for
    session and role, per-turn record concatenation for phase), and
    whether the time block emits the full set of fields (session and
    phase) or the role-scope subset (role). A role
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
    requests = compute_requests_for_records(scope_records)
    if scope_kind == "role":
        rendered_time = time_block_role(time_metrics)
    else:
        rendered_time = time_block(time_metrics, scope_kind)

    return {
        "economic": economic_block(economic, requests),
        "process": {
            "time": rendered_time,
            "user_input": user_input_block(user_input),
            "requests": requests_block(requests),
        },
        "supplementary": supplementary_block(supplementary, reliability),
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
    if phase_of_turn(session, all_turns[0]) == phase_label:
        if all_turns[0].start_timestamp > scope_start:
            total_inter_turn += (all_turns[0].start_timestamp - scope_start).total_seconds()

    # Gaps between turns
    for i in range(len(all_turns) - 1):
        if phase_of_turn(session, all_turns[i]) == phase_label:
            gap = (all_turns[i+1].start_timestamp - all_turns[i].end_timestamp).total_seconds()
            total_inter_turn += max(0.0, gap)

    # Gap after last turn
    if phase_of_turn(session, all_turns[-1]) == phase_label:
        if scope_end > all_turns[-1].end_timestamp:
            total_inter_turn += (scope_end - all_turns[-1].end_timestamp).total_seconds()

    return total_inter_turn


def _records_in_scope(
    session: Session,
    turns: tuple[Turn, ...],
    scope_kind: str,
    role_view: ConversationView | None,
) -> list[Record]:
    """Return the record stream for a scope's reliability and supplementary aggregation.

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
