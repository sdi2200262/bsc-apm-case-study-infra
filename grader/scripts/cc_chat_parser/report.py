#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 BSc Case Study Grader Contributors
"""
Assemble the canonical scope-nested metrics artifact.

The artifact has six top-level sections: ``session_metadata``,
``parameters``, ``session``, ``phases``, optional ``roles`` (APM
only), ``turns``, and ``diagnostics``. Each measurement leaf is a
``{value, anchor, constructed}`` triple so the analysis layer can
iterate over Primary metrics to assemble its hypothesis-test family
and flag every Constructed metric for the literature-grounding
cross-check without consulting an external index.

Anchor takes one of three values:

* ``Primary``: drives a research-question claim and is
  hypothesis-tested.
* ``Secondary``: supports or decomposes a Primary within the same
  dimension.
* ``Supplementary``: descriptive only, no hypothesis test.

Constructed is a Boolean. ``true`` means the metric was defined for
this study and rests on face validity until the literature-grounding
pass attaches a published construct; ``false`` means the metric
maps directly onto a JSONL, API, or grader field with aggregation
as the only study-author degree of freedom.

The diagnostics block surfaces everything the analysis layer needs
to decide whether to include, exclude, or annotate a session: the
count of compaction events (cost reported is a minimum when
non-zero), the number of synthetic assistant records excluded, the
number of Agent dispatches that did not return populated usage,
queue lifecycle warnings, unknown command markers observed, and
the per-invariant pass-or-fail status with a numerical residual
when a check fails.
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
    extract_command_names,
    is_known_command,
)
from .loader import STEER_FATE_DELIVERED, Conversation, SteerEvent
from .metrics.economic import (
    EconomicSession,
    compute_economic_for_records,
    compute_session_economic,
    resolve_pinned_model,
)
from .metrics.reliability import ReliabilityMetrics, compute_reliability_metrics
from .metrics.supplementary import SupplementaryMetrics, compute_supplementary_metrics
from .metrics.time import TimeMetrics, compute_time_metrics
from .metrics.user_input import UserInputMetrics, compute_user_input_metrics
from .rates import RateTable
from .schema import (
    Record,
    SYNTHETIC_MODEL_MARKER,
    is_genuine_user_prompt,
    user_prompt_text,
)
from .session import ConversationView, Session
from .turns import Turn

ANCHOR_PRIMARY = "Primary"
ANCHOR_SECONDARY = "Secondary"
ANCHOR_SUPPLEMENTARY = "Supplementary"

PHASE_KEYS: tuple[str, ...] = (PHASE_PLANNING, PHASE_IMPLEMENTATION, PHASE_OTHER)

INVARIANT_TOLERANCE_SECONDS = 0.001
INVARIANT_TOLERANCE_RATIO = 1e-9
INVARIANT_TOLERANCE_USD = 0.01


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
    session_block = _build_scope_block(session, session.turns, rate_table, short_threshold)
    phases_block = {
        phase: _build_scope_block(
            session,
            tuple(_turns_in_phase(session, phase)),
            rate_table,
            short_threshold,
        )
        for phase in PHASE_KEYS
    }
    artifact: dict[str, Any] = {
        "session_metadata": metadata,
        "parameters": parameters,
        "session": session_block,
        "phases": phases_block,
        "turns": _build_turn_records(session),
        "diagnostics": _build_diagnostics(session, session_block),
    }
    if session.framework == FRAMEWORK_APM:
        artifact["roles"] = {
            view.role: _build_scope_block(
                session,
                tuple(_turns_in_role(session, view.role)),
                rate_table,
                short_threshold,
            )
            for view in session.views
        }
    return artifact


def _metric(value: Any, anchor: str, constructed: bool) -> dict[str, Any]:
    """Wrap a measurement value in the canonical leaf triple."""
    return {"value": value, "anchor": anchor, "constructed": constructed}


def _build_session_metadata(session: Session) -> dict[str, Any]:
    """Assemble the session-metadata block."""
    cc_versions = _modal_string_field(session, "version")
    auth_modes = _modal_string_field(session, "userType")
    entrypoints = _modal_string_field(session, "entrypoint")
    service_tiers = _modal_assistant_usage_field(session, "service_tier")
    models = _models_observed(session)
    pinned_model = max(models.items(), key=lambda item: item[1])[0] if models else ""
    start = _earliest_timestamp_iso(session)
    end = _latest_timestamp_iso(session)
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
) -> dict[str, Any]:
    """Assemble one scope's economic, process, and supplementary blocks."""
    steer_events = _steer_events_in_turns(session, turns)
    economic = _compute_economic_for_scope(session, turns, rate_table)
    time_metrics = compute_time_metrics(turns)
    user_input = compute_user_input_metrics(turns, steer_events, short_threshold)
    reliability = compute_reliability_metrics(turns)
    supplementary = compute_supplementary_metrics(turns)
    return {
        "economic": _economic_block(economic),
        "process": {
            "time": _time_block(time_metrics),
            "user_input": _user_input_block(user_input),
            "reliability": _reliability_block(reliability),
        },
        "supplementary": _supplementary_block(supplementary),
    }


def _compute_economic_for_scope(
    session: Session,
    turns: tuple[Turn, ...],
    rate_table: RateTable,
) -> EconomicSession | None:
    """Compute economic metrics for a turn subset, or ``None`` for an empty scope.

    The session-scope path uses the package-level
    ``compute_session_economic`` so the headline numbers stay
    aligned with the standalone ``--economic`` mode. Phase and
    role scopes restrict the records to those belonging to the
    scope's turns and recompute against the same pinned model;
    a scope with no turns returns ``None`` and renders as a
    zero block.
    """
    if turns is session.turns:
        return compute_session_economic(session, rate_table)
    if not turns:
        return None
    records: list[Record] = []
    for turn in turns:
        records.extend(turn.records)
    model = resolve_pinned_model(session)
    return compute_economic_for_records(records, rate_table, model)


def _economic_block(economic: EconomicSession | None) -> dict[str, Any]:
    """Render an economic block with leaf triples."""
    if economic is None:
        zero = _metric(0, ANCHOR_SECONDARY, False)
        zero_cost = _metric(0.0, ANCHOR_PRIMARY, True)
        return {
            f"main_{cat}_tokens": zero
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        } | {
            f"delegated_{cat}_tokens": zero
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        } | {
            f"total_{cat}_tokens": zero
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        } | {
            "total_prompt_tokens": zero,
            "cost_usd": zero_cost,
        }
    return {
        "main_input_tokens":     _metric(economic.main.input,      ANCHOR_SECONDARY, False),
        "main_output_tokens":    _metric(economic.main.output,     ANCHOR_SECONDARY, False),
        "main_cache_read_tokens":_metric(economic.main.cache_read, ANCHOR_SECONDARY, False),
        "main_cache_5m_tokens":  _metric(economic.main.cache_5m,   ANCHOR_SECONDARY, False),
        "main_cache_1h_tokens":  _metric(economic.main.cache_1h,   ANCHOR_SECONDARY, False),
        "delegated_input_tokens":     _metric(economic.delegated.input,      ANCHOR_SECONDARY, False),
        "delegated_output_tokens":    _metric(economic.delegated.output,     ANCHOR_SECONDARY, False),
        "delegated_cache_read_tokens":_metric(economic.delegated.cache_read, ANCHOR_SECONDARY, False),
        "delegated_cache_5m_tokens":  _metric(economic.delegated.cache_5m,   ANCHOR_SECONDARY, False),
        "delegated_cache_1h_tokens":  _metric(economic.delegated.cache_1h,   ANCHOR_SECONDARY, False),
        "total_input_tokens":     _metric(economic.total.input,      ANCHOR_SECONDARY, False),
        "total_output_tokens":    _metric(economic.total.output,     ANCHOR_SECONDARY, False),
        "total_cache_read_tokens":_metric(economic.total.cache_read, ANCHOR_SECONDARY, False),
        "total_cache_5m_tokens":  _metric(economic.total.cache_5m,   ANCHOR_SECONDARY, False),
        "total_cache_1h_tokens":  _metric(economic.total.cache_1h,   ANCHOR_SECONDARY, False),
        "total_prompt_tokens": _metric(economic.total_prompt_tokens, ANCHOR_SECONDARY, False),
        "cost_usd":            _metric(round(economic.cost_usd, 4), ANCHOR_PRIMARY,   True),
    }


def _time_block(metrics: TimeMetrics) -> dict[str, Any]:
    """Render a time block with leaf triples."""
    return {
        "duration":             _metric(metrics.duration,             ANCHOR_SECONDARY, False),
        "turn_time":            _metric(metrics.turn_time,            ANCHOR_SECONDARY, True),
        "turn_time_solo":       _metric(metrics.turn_time_solo,       ANCHOR_SECONDARY, True),
        "turn_time_concurrent": _metric(metrics.turn_time_concurrent, ANCHOR_SECONDARY, True),
        "inter_turn_time":      _metric(metrics.inter_turn_time,      ANCHOR_PRIMARY,   True),
        "turn_count":           _metric(metrics.turn_count,           ANCHOR_PRIMARY,   True),
        "mean_turn_duration":   _metric(metrics.mean_turn_duration,   ANCHOR_PRIMARY,   True),
        "turn_duration_p50":    _metric(metrics.turn_duration_p50,    ANCHOR_SECONDARY, True),
        "turn_duration_p95":    _metric(metrics.turn_duration_p95,    ANCHOR_SECONDARY, True),
        "turn_duration_stdev":  _metric(metrics.turn_duration_stdev,  ANCHOR_SECONDARY, True),
    }


def _user_input_block(metrics: UserInputMetrics) -> dict[str, Any]:
    """Render a user-input block with leaf triples."""
    return {
        "turn_prompt_count":      _metric(metrics.turn_prompt_count,      ANCHOR_PRIMARY,   True),
        "steer_delivered_count":  _metric(metrics.steer_delivered_count,  ANCHOR_PRIMARY,   True),
        "steer_abandoned_count":  _metric(metrics.steer_abandoned_count,  ANCHOR_SECONDARY, True),
        "steer_attempted_count":  _metric(metrics.steer_attempted_count,  ANCHOR_PRIMARY,   True),
        "turn_prompts_bucket_shares":          _metric(metrics.turn_prompts_bucket_shares,          ANCHOR_SECONDARY, True),
        "steer_delivered_bucket_shares":       _metric(metrics.steer_delivered_bucket_shares,       ANCHOR_SECONDARY, True),
        "all_inputs_bucket_shares":            _metric(metrics.all_inputs_bucket_shares,            ANCHOR_PRIMARY,   True),
        "turn_prompts_magnitude_by_bucket":    _metric(metrics.turn_prompts_magnitude_by_bucket,    ANCHOR_SECONDARY, True),
        "steer_delivered_magnitude_by_bucket": _metric(metrics.steer_delivered_magnitude_by_bucket, ANCHOR_SECONDARY, True),
    }


def _reliability_block(metrics: ReliabilityMetrics) -> dict[str, Any]:
    """Render a reliability block with leaf triples."""
    return {
        "tool_success_rate": _metric(metrics.tool_success_rate, ANCHOR_PRIMARY, False),
        "tool_result_count": _metric(metrics.tool_result_count, ANCHOR_SECONDARY, False),
        "tool_error_count":  _metric(metrics.tool_error_count,  ANCHOR_SECONDARY, False),
    }


def _supplementary_block(metrics: SupplementaryMetrics) -> dict[str, Any]:
    """Render a supplementary block with leaf triples."""
    return {
        "subagent_count":        _metric(metrics.subagent_count,        ANCHOR_SUPPLEMENTARY, False),
        "subagent_tool_count":   _metric(metrics.subagent_tool_count,   ANCHOR_SUPPLEMENTARY, False),
        "reasoning_token_share": _metric(round(metrics.reasoning_token_share, 6), ANCHOR_SUPPLEMENTARY, True),
    }


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


def _build_diagnostics(session: Session, session_block: dict[str, Any]) -> dict[str, Any]:
    """Assemble the diagnostics block."""
    compaction_total = sum(
        len(view.conversation.compaction_events) for view in session.views
    )
    compaction_by_file = {
        view.conversation.session_id or view.conversation.path: len(view.conversation.compaction_events)
        for view in session.views
        if view.conversation.compaction_events
    }
    synthetic_excluded = sum(
        view.conversation.usage_index.synthetic_assistant_count
        for view in session.views
    )
    queue_warnings = [
        warning
        for view in session.views
        for warning in view.conversation.queue_lifecycle_warnings
    ]
    unknown_commands = _unknown_commands(session)
    economic_value = session_block["economic"]["cost_usd"]["value"]
    economic_full = session_block["economic"]
    invariants = _evaluate_invariants(session_block, economic_full)
    agent_dispatches_total, agent_dispatches_with_usage = _agent_dispatch_counts(session)
    return {
        "compaction_events_total": compaction_total,
        "compaction_events_by_file": compaction_by_file,
        "cost_excludes_compaction_synthesis": compaction_total > 0,
        "synthetic_assistant_records_excluded": synthetic_excluded,
        "agent_dispatches_total": agent_dispatches_total,
        "agent_dispatches_without_usage": agent_dispatches_total - agent_dispatches_with_usage,
        "queue_lifecycle_warnings": queue_warnings,
        "unknown_commands_observed": unknown_commands,
        "invariant_checks": invariants,
        "notes": [
            "cost_usd is the API-equivalent cost from visible API calls "
            "and excludes the synthesis cost of compaction events when present.",
            "reasoning_token_share is approximated from character counts because "
            "message.usage.output_tokens does not split by content block type.",
        ],
    }


def _evaluate_invariants(
    session_block: dict[str, Any],
    economic_full: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate every invariant identity on the session block."""
    time_block = session_block["process"]["time"]
    duration = time_block["duration"]["value"]
    turn_time = time_block["turn_time"]["value"]
    turn_time_solo = time_block["turn_time_solo"]["value"]
    turn_time_concurrent = time_block["turn_time_concurrent"]["value"]
    inter_turn_time = time_block["inter_turn_time"]["value"]
    user_input = session_block["process"]["user_input"]
    delivered = user_input["steer_delivered_count"]["value"]
    abandoned = user_input["steer_abandoned_count"]["value"]
    attempted = user_input["steer_attempted_count"]["value"]
    return {
        "time_composition_session": _check_close(
            duration, turn_time + inter_turn_time, INVARIANT_TOLERANCE_SECONDS
        ),
        "turn_time_decomposition": _check_close(
            turn_time, turn_time_solo + turn_time_concurrent, INVARIANT_TOLERANCE_SECONDS
        ),
        "steer_accounting": _check_close(attempted, delivered + abandoned, 0),
        "bucket_shares_turn_prompts": _check_close(
            sum(user_input["turn_prompts_bucket_shares"]["value"].values()),
            1.0 if user_input["turn_prompt_count"]["value"] > 0 else 0.0,
            INVARIANT_TOLERANCE_RATIO,
        ),
        "bucket_shares_steer_delivered": _check_close(
            sum(user_input["steer_delivered_bucket_shares"]["value"].values()),
            1.0 if user_input["steer_delivered_count"]["value"] > 0 else 0.0,
            INVARIANT_TOLERANCE_RATIO,
        ),
        "bucket_shares_all_inputs": _check_close(
            sum(user_input["all_inputs_bucket_shares"]["value"].values()),
            1.0 if (user_input["turn_prompt_count"]["value"] +
                    user_input["steer_delivered_count"]["value"]) > 0 else 0.0,
            INVARIANT_TOLERANCE_RATIO,
        ),
    }


def _check_close(left: float, right: float, tolerance: float) -> dict[str, Any]:
    """Return ``{"status": "ok"}`` when within tolerance, otherwise residuals."""
    residual = abs(left - right)
    if residual <= tolerance:
        return {"status": "ok"}
    return {"status": "fail", "left": left, "right": right, "residual": residual}


def _agent_dispatch_counts(session: Session) -> tuple[int, int]:
    """Count Agent dispatches and how many had populated usage at session level."""
    total = 0
    with_usage = 0
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != "assistant":
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            if message.get("model") == SYNTHETIC_MODEL_MARKER:
                continue
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Agent":
                    total += 1
        for record in view.conversation.records:
            if record.record_type != "user":
                continue
            tool_use_result = record.payload.get("toolUseResult")
            if isinstance(tool_use_result, dict) and isinstance(tool_use_result.get("usage"), dict):
                with_usage += 1
    return total, with_usage


def _unknown_commands(session: Session) -> list[str]:
    """Return the sorted set of command names observed that are not in the known set."""
    seen: set[str] = set()
    for view in session.views:
        for record in view.conversation.records:
            if not is_genuine_user_prompt(record):
                continue
            for command in extract_command_names(user_prompt_text(record)):
                if not is_known_command(command):
                    seen.add(command)
    return sorted(seen)


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


def _steer_events_in_turns(
    session: Session,
    turns: tuple[Turn, ...],
) -> list[SteerEvent]:
    """Return the steer events whose enqueue uuid matches any in the supplied turns.

    For session scope (every turn), this is every steer event in
    every conversation. For phase or role scope, the turn subset
    constrains which events count toward the scope's user-input
    metrics.
    """
    if turns is session.turns:
        return [
            event
            for view in session.views
            for event in view.conversation.steer_events
        ]
    turn_uuids = {turn.starting_prompt.uuid for turn in turns}
    paths_in_scope = {turn.conversation_path for turn in turns}
    events: list[SteerEvent] = []
    for view in session.views:
        if view.conversation.path not in paths_in_scope:
            continue
        for event in view.conversation.steer_events:
            ts = event.enqueue_record.timestamp
            if ts is None:
                continue
            for turn in turns:
                if (turn.conversation_path == view.conversation.path
                    and turn.start_timestamp <= ts <= turn.end_timestamp):
                    events.append(event)
                    break
    return events


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
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            if isinstance(model, str) and model and model != SYNTHETIC_MODEL_MARKER:
                counter[model] += 1
    return dict(counter)


def _earliest_timestamp_iso(session: Session) -> str | None:
    """Return the earliest record timestamp across the session as ISO-8601, or ``None``."""
    earliest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
    return _iso_or_none(earliest)


def _latest_timestamp_iso(session: Session) -> str | None:
    """Return the latest record timestamp across the session as ISO-8601, or ``None``."""
    latest = None
    for view in session.views:
        for record in view.conversation.records:
            if record.timestamp is None:
                continue
            if latest is None or record.timestamp > latest:
                latest = record.timestamp
    return _iso_or_none(latest)


def _iso_or_none(value: datetime | None) -> str | None:
    """Return an ISO-8601 string for a timestamp, or ``None`` when absent."""
    return value.isoformat() if value is not None else None
