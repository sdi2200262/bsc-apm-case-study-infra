# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Assemble the data and metrics artifacts from a session.

The parser emits two per-session artifacts of bare ``name: value`` leaves,
and this module owns that two-artifact split. ``parser_data.json`` carries
the data (identity, token sums, counts, the per-call and per-turn series);
``parser_metrics.json`` carries the metrics (cost, time statistics, bucket
distributions, the success rate). A third artifact, ``parser_schema.json``,
is the field contract and is emitted once by ``--schema``, not per session.
The two per-session artifacts join downstream on ``request_id``.

Beyond the split, this module owns the per-scope turn and record selection.
It computes nothing transcript-derived (see ``report``); each leaf's kind
and label live in ``parser.contract``, and leaf formatting lives in
``leaves``.

Naming convention. Every artifact key is snake_case. Per-conversation
identity is collected into a single ``conversations`` array under
``identity``, so downstream consumers iterate one array regardless of
framework. The ``other`` phase and other empty scopes render zeroed values
for a uniform per-scope shape; consumers filter them by ``turn_count == 0``
rather than by missing keys.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..data.aggregate.counts import (
    compute_request_counts,
    compute_subagent_counts,
    compute_tool_counts,
    compute_user_input_counts,
    turn_count,
)
from ..data.aggregate.tokens import (
    TokenData,
    compute_token_data_for_records,
    merge_subagent_indices,
)
from ..data.aggregate.turn_series import (
    build_call_series,
    build_turn_records,
    turns_in_phase,
    turns_in_role,
)
from ..data.buckets import DEFAULT_SHORT_THRESHOLD
from ..data.commands import (
    FRAMEWORK_APM,
    PHASE_IMPLEMENTATION,
    PHASE_OTHER,
    PHASE_PLANNING,
)
from ..data.conversation import SteerEvent
from ..data.schema import Record
from ..data.session import (
    ConversationView,
    Session,
    build_identity,
    latest_real_timestamp,
    session_start_timestamp,
)
from ..data.subagent_usage import SubagentDispatchIndex
from ..data.turns import Turn
from ..metrics.cost import CostMetrics, compute_cost_for_records
from ..metrics.reliability import tool_success_rate
from ..metrics.time import compute_time_metrics
from ..metrics.user_input import compute_user_input_shares
from ..rates import RateTable
from .leaves import (
    cost_leaves,
    model_token_distribution_leaves,
    request_count_leaves,
    supplementary_data_leaves,
    time_leaves,
    time_leaves_role,
    token_leaves,
    tool_count_leaves,
    user_input_count_leaves,
    user_input_share_leaves,
)

PHASE_KEYS: tuple[str, ...] = (PHASE_PLANNING, PHASE_IMPLEMENTATION, PHASE_OTHER)

REAL_ROLE_PREFIXES: tuple[str, ...] = ("planner-", "manager-", "worker-")


def build_artifacts(
    session: Session,
    rate_table: RateTable,
    short_threshold: int = DEFAULT_SHORT_THRESHOLD,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the data and metrics artifacts for a session.

    Args:
        session: An assembled session.
        rate_table: The rate table to compute cost against.
        short_threshold: Bucket classifier threshold for the user-input
            dimension.

    Returns:
        The ``(data_artifact, metrics_artifact)`` pair, each a
        JSON-serialisable dict with bare leaves.
    """
    identity = build_identity(session)
    metadata = _build_metadata(session, rate_table, short_threshold)
    subagent_index = merge_subagent_indices(session)
    session_start_dt = session_start_timestamp(session)
    session_end_dt = latest_real_timestamp(session)

    data_session, metric_session = _build_scope_blocks(
        session,
        session.turns,
        rate_table,
        subagent_index,
        short_threshold,
        scope_kind="session",
        scope_start=session_start_dt,
        scope_end=session_end_dt,
    )
    data_phases: dict[str, Any] = {}
    metric_phases: dict[str, Any] = {}
    for phase in PHASE_KEYS:
        data_block, metric_block = _build_scope_blocks(
            session,
            tuple(turns_in_phase(session, phase)),
            rate_table,
            subagent_index,
            short_threshold,
            scope_kind="phase",
            phase_label=phase,
        )
        data_phases[phase] = data_block
        metric_phases[phase] = metric_block

    data_scopes: dict[str, Any] = {"session": data_session, "phases": data_phases}
    metric_scopes: dict[str, Any] = {"session": metric_session, "phases": metric_phases}

    if session.framework == FRAMEWORK_APM:
        data_roles: dict[str, Any] = {}
        metric_roles: dict[str, Any] = {}
        for view in session.views:
            if not _is_real_apm_role(view.role):
                continue
            data_block, metric_block = _build_scope_blocks(
                session,
                tuple(turns_in_role(session, view.role)),
                rate_table,
                subagent_index,
                short_threshold,
                scope_kind="role",
                role_view=view,
            )
            data_roles[view.role] = data_block
            metric_roles[view.role] = metric_block
        data_scopes["roles"] = data_roles
        metric_scopes["roles"] = metric_roles

    data_artifact: dict[str, Any] = {
        "identity": identity,
        "metadata": metadata,
        "scopes": data_scopes,
        "calls": build_call_series(session),
        "turns": build_turn_records(session),
    }
    metrics_artifact: dict[str, Any] = {
        "identity": identity,
        "metadata": metadata,
        "scopes": metric_scopes,
    }
    return data_artifact, metrics_artifact


def _is_real_apm_role(role_key: str) -> bool:
    """Return ``True`` for the three real APM role kinds (planner/manager/worker).

    The session assembler also produces ``unassigned-N`` entries for APM
    conversations whose first slash command is not a role initiator. Those
    conversations stay listed in ``identity.conversations`` for
    traceability but are not role-bearing under the APM model, so they do
    not belong in the ``roles`` block of either artifact.
    """
    return role_key.startswith(REAL_ROLE_PREFIXES)


def _build_metadata(
    session: Session,
    rate_table: RateTable,
    short_threshold: int,
) -> dict[str, Any]:
    """Assemble the minimal run-input metadata block.

    The block holds only the run inputs that change the numbers: the
    framework, the short-prompt bucket threshold, and the rate-table
    snapshot date. The machine-specific rate-table path and the pricing
    source URLs are not run inputs and are not emitted.
    """
    return {
        "framework": session.framework,
        "short_threshold": short_threshold,
        "rate_table_snapshot_date": rate_table.snapshot_date,
    }


def _build_scope_blocks(
    session: Session,
    turns: tuple[Turn, ...],
    rate_table: RateTable,
    subagent_index: SubagentDispatchIndex,
    short_threshold: int,
    scope_kind: str,
    phase_label: str | None = None,
    role_view: ConversationView | None = None,
    scope_start: datetime | None = None,
    scope_end: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Assemble one scope's data and metric leaf blocks.

    ``scope_kind`` is one of ``"session"``, ``"phase"``, or ``"role"``.
    The kind controls two things: which records the count aggregations
    iterate (full conversation walk for session and role, per-turn record
    concatenation for phase), and whether the metric block emits the full
    set of time fields (session and phase) or the role-scope subset (role).
    A role scope's ``turn_time`` is the sum of per-turn durations rather
    than the union of intervals, reflecting that a role is one conversation
    file whose own turns do not overlap.

    Returns:
        The ``(data_block, metric_block)`` pair for the scope.
    """
    steer_events = _steer_events_in_scope(session, scope_kind, role_view, turns)
    scope_turn_count = turn_count(turns)
    token_data, cost = _compute_economic_for_scope(session, turns, rate_table, subagent_index)
    time_metrics = compute_time_metrics(
        turns, scope_start, scope_end, session=session, phase_label=phase_label
    )
    user_input_counts = compute_user_input_counts(turns, steer_events, short_threshold)
    user_input_shares = compute_user_input_shares(user_input_counts)
    scope_records = _records_in_scope(session, turns, scope_kind, role_view)
    tool_counts = compute_tool_counts(scope_records)
    subagent_counts = compute_subagent_counts(scope_records)
    request_counts = compute_request_counts(scope_records)

    data_block: dict[str, Any] = {
        **token_leaves(token_data),
        **model_token_distribution_leaves(token_data),
        "turn_count": scope_turn_count,
        **request_count_leaves(request_counts),
        **user_input_count_leaves(user_input_counts),
        **supplementary_data_leaves(subagent_counts),
        **tool_count_leaves(tool_counts),
    }

    if scope_kind == "role":
        time_block = time_leaves_role(time_metrics, scope_turn_count)
    else:
        time_block = time_leaves(time_metrics)
    metric_block: dict[str, Any] = {
        **cost_leaves(cost),
        **time_block,
        **user_input_share_leaves(user_input_shares),
        "tool_success_rate": tool_success_rate(tool_counts),
    }
    return data_block, metric_block


def _records_in_scope(
    session: Session,
    turns: tuple[Turn, ...],
    scope_kind: str,
    role_view: ConversationView | None,
) -> list[Record]:
    """Return the record stream for a scope's count aggregations.

    Session scope iterates every conversation's records across every
    conversation file. Role scope iterates the records of the role's
    single conversation file. Phase scope cannot use a per-conversation
    record stream because a phase can span multiple conversations; it
    instead concatenates the records of every turn whose starting prompt's
    phase matches the scope. In well-formed Claude Code data the session
    and role record streams (full conversation walk) and the phase record
    stream (per-turn walk) cover the same metric-relevant records; the
    distinction is one of attribution, not of which records exist.
    """
    if scope_kind == "session":
        return [record for view in session.views for record in view.conversation.records]
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

    Session scope sees every steer event across every conversation. Role
    scope sees every steer in the role's conversation, regardless of
    whether the steer's enqueue timestamp falls inside a turn's interval;
    this catches inter-turn steers that happen during a model-quiet
    moment. Phase scope attributes each steer to the phase of the turn
    whose interval contains its enqueue timestamp, which is the same
    containment relation the per-turn ``Turn.steer_events`` list already
    encodes; a steer between turns (rare, model-quiet) does not enter any
    phase aggregate, matching the per-prompt phase model.
    """
    if scope_kind == "session":
        return [event for view in session.views for event in view.conversation.steer_events]
    if scope_kind == "role" and role_view is not None:
        return list(role_view.conversation.steer_events)
    if scope_kind == "phase":
        return [event for turn in turns for event in turn.steer_events]
    return []


def _compute_economic_for_scope(
    session: Session,
    turns: tuple[Turn, ...],
    rate_table: RateTable,
    subagent_index: SubagentDispatchIndex,
) -> tuple[TokenData | None, CostMetrics | None]:
    """Compute a scope's token data and cost, or ``(None, None)`` for an empty scope.

    Session scope prices every record across every conversation; a phase
    or role scope prices the records of its turns. The subagent index is
    the session-wide merge for every scope, so a dispatch resolves to the
    same model and token bag regardless of which scope prices it.
    """
    if turns is session.turns:
        records = [record for view in session.views for record in view.conversation.records]
    elif not turns:
        return None, None
    else:
        records = []
        for turn in turns:
            records.extend(turn.records)
    token_data = compute_token_data_for_records(records, subagent_index)
    cost = compute_cost_for_records(records, rate_table, subagent_index)
    return token_data, cost
