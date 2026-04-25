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
queue lifecycle warnings, unknown command markers observed,
auxiliary tool-result counts that support the success rate, the
``entrypoint`` and authentication-mode validity flags, the
turns-with-missing-uuid count, and the per-invariant pass-or-fail
status with a numerical residual when a check fails.

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
    APM_PHASE_BY_ROLE,
    FRAMEWORK_APM,
    PHASE_IMPLEMENTATION,
    PHASE_OTHER,
    PHASE_PLANNING,
    ROLE_UNASSIGNED,
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
    is_synthetic_assistant,
    user_prompt_text,
)
from .session import ConversationView, Session
from .turns import Turn

ANCHOR_PRIMARY = "Primary"
ANCHOR_SECONDARY = "Secondary"
ANCHOR_SUPPLEMENTARY = "Supplementary"

PHASE_KEYS: tuple[str, ...] = (PHASE_PLANNING, PHASE_IMPLEMENTATION, PHASE_OTHER)

REAL_ROLE_PREFIXES: tuple[str, ...] = ("planner-", "manager-", "worker-")

EXPECTED_ENTRYPOINT = "cli"
EXPECTED_AUTH_MODE = "external"

INVARIANT_TOLERANCE_SECONDS = 0.001
INVARIANT_TOLERANCE_RATIO = 1e-9
INVARIANT_TOLERANCE_USD = 0.01
INVARIANT_TOLERANCE_TOKENS = 0


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
    artifact["diagnostics"] = _build_diagnostics(session, artifact, rate_table)
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
    steer_events = _steer_events_in_scope(session, scope_kind, role_view)
    economic = _compute_economic_for_scope(session, turns, rate_table)
    time_metrics = compute_time_metrics(turns, scope_start, scope_end)
    user_input = compute_user_input_metrics(turns, steer_events, short_threshold)
    scope_records = _records_in_scope(session, turns, scope_kind, role_view)
    reliability = compute_reliability_metrics(scope_records)
    supplementary = compute_supplementary_metrics(scope_records)
    if scope_kind == "role":
        time_block = _time_block_role(time_metrics)
    else:
        time_block = _time_block(time_metrics)
    return {
        "economic": _economic_block(economic),
        "process": {
            "time": time_block,
            "user_input": _user_input_block(user_input),
            "reliability": _reliability_block(reliability),
        },
        "supplementary": _supplementary_block(supplementary),
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
) -> list[SteerEvent]:
    """Return the steer events that belong to a scope.

    Session scope sees every steer event across every conversation.
    Role scope sees every steer in the role's conversation,
    regardless of whether the steer's enqueue timestamp falls
    inside a turn's interval; this catches inter-turn steers that
    happen during a model-quiet moment. Phase scope (APM) attributes
    each steer to the phase of its conversation's role; phase scope
    (Spec-kit) is left empty because the phase model uses a
    per-prompt ratchet whose attribution to phase scope at the
    steer level is open work.
    """
    if scope_kind == "session":
        return [
            event
            for view in session.views
            for event in view.conversation.steer_events
        ]
    if scope_kind == "role" and role_view is not None:
        return list(role_view.conversation.steer_events)
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


def _economic_block(economic: EconomicSession | None) -> dict[str, Any]:
    """Render an economic block with leaf triples."""
    if economic is None:
        zero_token = _metric(0, ANCHOR_SECONDARY, False)
        zero_cost = _metric(0.0, ANCHOR_PRIMARY, True)
        token_keys = (
            f"{population}_{cat}_tokens"
            for population in ("main", "delegated", "total")
            for cat in ("input", "output", "cache_read", "cache_5m", "cache_1h")
        )
        return {key: zero_token for key in token_keys} | {
            "total_prompt_tokens": zero_token,
            "cost_usd": zero_cost,
        }
    return {
        "main_input_tokens":            _metric(economic.main.input,            ANCHOR_SECONDARY, False),
        "main_output_tokens":           _metric(economic.main.output,           ANCHOR_SECONDARY, False),
        "main_cache_read_tokens":       _metric(economic.main.cache_read,       ANCHOR_SECONDARY, False),
        "main_cache_5m_tokens":         _metric(economic.main.cache_5m,         ANCHOR_SECONDARY, False),
        "main_cache_1h_tokens":         _metric(economic.main.cache_1h,         ANCHOR_SECONDARY, False),
        "delegated_input_tokens":       _metric(economic.delegated.input,       ANCHOR_SECONDARY, False),
        "delegated_output_tokens":      _metric(economic.delegated.output,      ANCHOR_SECONDARY, False),
        "delegated_cache_read_tokens":  _metric(economic.delegated.cache_read,  ANCHOR_SECONDARY, False),
        "delegated_cache_5m_tokens":    _metric(economic.delegated.cache_5m,    ANCHOR_SECONDARY, False),
        "delegated_cache_1h_tokens":    _metric(economic.delegated.cache_1h,    ANCHOR_SECONDARY, False),
        "total_input_tokens":           _metric(economic.total.input,           ANCHOR_SECONDARY, False),
        "total_output_tokens":          _metric(economic.total.output,          ANCHOR_SECONDARY, False),
        "total_cache_read_tokens":      _metric(economic.total.cache_read,      ANCHOR_SECONDARY, False),
        "total_cache_5m_tokens":        _metric(economic.total.cache_5m,        ANCHOR_SECONDARY, False),
        "total_cache_1h_tokens":        _metric(economic.total.cache_1h,        ANCHOR_SECONDARY, False),
        "total_prompt_tokens":          _metric(economic.total_prompt_tokens,   ANCHOR_SECONDARY, False),
        "cost_usd":                     _metric(round(economic.cost_usd, 4),    ANCHOR_PRIMARY,   True),
    }


def _time_block(metrics: TimeMetrics) -> dict[str, Any]:
    """Render a session-or-phase time block with leaf triples."""
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


def _time_block_role(metrics: TimeMetrics) -> dict[str, Any]:
    """Render a role-scope time block with its six measurement fields.

    A role's ``turn_time`` is the sum of per-turn durations rather
    than the union of intervals. Within a single conversation file
    the two coincide, because the participant cannot drive two
    overlapping prompts in one chat; the formula difference is a
    deliberate choice that surfaces if a future role rollup
    ever folds in turns from multiple files.
    """
    sum_of_turn_durations = metrics.mean_turn_duration * metrics.turn_count
    return {
        "turn_count":          _metric(metrics.turn_count,          ANCHOR_SECONDARY, True),
        "turn_time":           _metric(sum_of_turn_durations,       ANCHOR_SECONDARY, True),
        "mean_turn_duration":  _metric(metrics.mean_turn_duration,  ANCHOR_SECONDARY, True),
        "turn_duration_p50":   _metric(metrics.turn_duration_p50,   ANCHOR_SECONDARY, True),
        "turn_duration_p95":   _metric(metrics.turn_duration_p95,   ANCHOR_SECONDARY, True),
        "turn_duration_stdev": _metric(metrics.turn_duration_stdev, ANCHOR_SECONDARY, True),
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
    """Render a reliability block with leaf triples.

    Only ``tool_success_rate`` is an exposed measurement leaf.
    The supporting ``tool_result_count`` and ``tool_error_count``
    values move into the diagnostics block so the analysis layer's
    iteration over measurement metrics does not pick them up as
    hypothesis-test candidates.
    """
    return {
        "tool_success_rate": _metric(metrics.tool_success_rate, ANCHOR_PRIMARY, False),
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


def _build_diagnostics(
    session: Session,
    artifact: dict[str, Any],
    rate_table: RateTable,
) -> dict[str, Any]:
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
    invariants = _evaluate_invariants(artifact, rate_table)
    agent_dispatches_total, agent_dispatches_with_usage = _agent_dispatch_counts(session)
    metadata = artifact["session_metadata"]
    entrypoint_value = metadata["entrypoint"]
    auth_value = metadata["auth_mode_indicator"]
    tool_result_total, tool_error_total = _tool_result_counts(session)
    turns_with_missing_uuid = sum(
        1 for turn in session.turns if not turn.starting_prompt.uuid
    )
    return {
        "compaction_events_total": compaction_total,
        "compaction_events_by_file": compaction_by_file,
        "cost_excludes_compaction_synthesis": compaction_total > 0,
        "synthetic_assistant_records_excluded": synthetic_excluded,
        "agent_dispatches_total": agent_dispatches_total,
        "agent_dispatches_without_usage": agent_dispatches_total - agent_dispatches_with_usage,
        "tool_result_count": tool_result_total,
        "tool_error_count": tool_error_total,
        "queue_lifecycle_warnings": queue_warnings,
        "unknown_commands_observed": unknown_commands,
        "entrypoint_valid": entrypoint_value == EXPECTED_ENTRYPOINT,
        "auth_mode_valid": auth_value == EXPECTED_AUTH_MODE,
        "turns_with_missing_uuid": turns_with_missing_uuid,
        "invariant_checks": invariants,
        "notes": [
            "cost_usd is the API-equivalent cost from visible API calls "
            "and excludes the synthesis cost of compaction events when present.",
            "reasoning_token_share is approximated from character counts because "
            "message.usage.output_tokens does not split by content block type.",
        ],
    }


def _evaluate_invariants(
    artifact: dict[str, Any],
    rate_table: RateTable,
) -> dict[str, Any]:
    """Evaluate every invariant identity across every scope.

    Walks session, every phase, and every role scope. For each
    scope checks the time composition (where defined), the
    per-category token composition (main + delegated == total),
    the prompt-token composition, the cost composition against
    the rate table, the steer accounting, and the bucket share
    sums. Records partition is also checked: phase tokens and
    role tokens should sum to the session totals for each
    category. Each check returns ``{"status": "ok"}`` when within
    tolerance and a residual block otherwise.
    """
    checks: dict[str, Any] = {}
    pinned_model = artifact["session_metadata"]["model"]
    rates = rate_table.models.get(pinned_model)
    scopes: list[tuple[str, dict[str, Any]]] = [("session", artifact["session"])]
    for phase, block in artifact["phases"].items():
        scopes.append((f"phase_{phase}", block))
    for role, block in artifact.get("roles", {}).items():
        scopes.append((f"role_{role}", block))
    for scope_label, block in scopes:
        time_block = block["process"]["time"]
        if "duration" in time_block and "inter_turn_time" in time_block:
            checks[f"time_composition_{scope_label}"] = _check_close(
                time_block["duration"]["value"],
                time_block["turn_time"]["value"] + time_block["inter_turn_time"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        if "turn_time_solo" in time_block and "turn_time_concurrent" in time_block:
            checks[f"turn_time_decomposition_{scope_label}"] = _check_close(
                time_block["turn_time"]["value"],
                time_block["turn_time_solo"]["value"] + time_block["turn_time_concurrent"]["value"],
                INVARIANT_TOLERANCE_SECONDS,
            )
        economic = block["economic"]
        for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
            checks[f"token_composition_{scope_label}_{category}"] = _check_close(
                economic[f"total_{category}_tokens"]["value"],
                economic[f"main_{category}_tokens"]["value"]
                + economic[f"delegated_{category}_tokens"]["value"],
                INVARIANT_TOLERANCE_TOKENS,
            )
        checks[f"prompt_token_composition_{scope_label}"] = _check_close(
            economic["total_prompt_tokens"]["value"],
            economic["total_input_tokens"]["value"]
            + economic["total_cache_read_tokens"]["value"]
            + economic["total_cache_5m_tokens"]["value"]
            + economic["total_cache_1h_tokens"]["value"],
            INVARIANT_TOLERANCE_TOKENS,
        )
        if rates is not None:
            expected_cost = (
                economic["total_input_tokens"]["value"] * rates.input
                + economic["total_output_tokens"]["value"] * rates.output
                + economic["total_cache_read_tokens"]["value"] * rates.cache_read
                + economic["total_cache_5m_tokens"]["value"] * rates.cache_5m
                + economic["total_cache_1h_tokens"]["value"] * rates.cache_1h
            ) / 1_000_000.0
            checks[f"cost_composition_{scope_label}"] = _check_close(
                economic["cost_usd"]["value"], expected_cost, INVARIANT_TOLERANCE_USD
            )
        user_input = block["process"]["user_input"]
        checks[f"steer_accounting_{scope_label}"] = _check_close(
            user_input["steer_attempted_count"]["value"],
            user_input["steer_delivered_count"]["value"]
            + user_input["steer_abandoned_count"]["value"],
            0,
        )
        for share_key, denominator in (
            ("turn_prompts_bucket_shares",
             user_input["turn_prompt_count"]["value"]),
            ("steer_delivered_bucket_shares",
             user_input["steer_delivered_count"]["value"]),
            ("all_inputs_bucket_shares",
             user_input["turn_prompt_count"]["value"]
             + user_input["steer_delivered_count"]["value"]),
        ):
            shares = user_input[share_key]["value"]
            expected = 1.0 if denominator > 0 else 0.0
            checks[f"bucket_shares_{share_key}_{scope_label}"] = _check_close(
                sum(shares.values()), expected, INVARIANT_TOLERANCE_RATIO
            )
    session_economic = artifact["session"]["economic"]
    for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
        phase_sum = sum(
            artifact["phases"][phase]["economic"][f"total_{category}_tokens"]["value"]
            for phase in artifact["phases"]
        )
        checks[f"phase_partition_{category}"] = _check_close(
            session_economic[f"total_{category}_tokens"]["value"],
            phase_sum,
            INVARIANT_TOLERANCE_TOKENS,
        )
    # Role partition only holds when every conversation in the
    # session has a real APM role. Sessions with one or more
    # ``unassigned-N`` conversations contribute tokens to the
    # session and phase totals but do not appear in the roles
    # block, so the role-sum identity is partial by design.
    if "roles" in artifact and _every_conversation_has_real_role(artifact):
        for category in ("input", "output", "cache_read", "cache_5m", "cache_1h"):
            role_sum = sum(
                artifact["roles"][role]["economic"][f"total_{category}_tokens"]["value"]
                for role in artifact["roles"]
            )
            checks[f"role_partition_{category}"] = _check_close(
                session_economic[f"total_{category}_tokens"]["value"],
                role_sum,
                INVARIANT_TOLERANCE_TOKENS,
            )
    return checks


def _every_conversation_has_real_role(artifact: dict[str, Any]) -> bool:
    """Return ``True`` when every conversation in metadata is a real APM role."""
    conversations = artifact["session_metadata"]["conversations"]
    return all(_is_real_apm_role(conv["role_key"]) for conv in conversations)


def _check_close(left: float, right: float, tolerance: float) -> dict[str, Any]:
    """Return ``{"status": "ok"}`` when within tolerance, otherwise residuals."""
    residual = abs(left - right)
    if residual <= tolerance:
        return {"status": "ok"}
    return {"status": "fail", "left": left, "right": right, "residual": residual}


def _tool_result_counts(session: Session) -> tuple[int, int]:
    """Return ``(total_tool_results, total_errors)`` across every conversation."""
    total = 0
    errors = 0
    for view in session.views:
        for record in view.conversation.records:
            if record.record_type != "user":
                continue
            message = record.payload.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue
                total += 1
                if block.get("is_error") is True:
                    errors += 1
    return total, errors


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
